#!/usr/bin/env python3
"""The ONE place the plugin says WHICH EDA image, and WHICH container holds it.

WHY THIS MODULE EXISTS
======================
Two facts were being answered in two different places, and they disagreed.

MEASURED 2026-09-07 on 8hd-3, with `VIBEIC_EDA_IMAGE_REPO` exported and the
pinned image present::

    $ python3 -c 'import _eda_image as E; print(E.judged_image().ref)'
    ghcr.io/vibeic/vibeic-eda@sha256:f6b09c1388c6…      # the 0.3.16 LOCAL TAG

while the pin every landing site names is
``sha256:8da785a8d3275884ad0d0ee0fb10f7e90d8b7bf11a08d38e9559b0764112480f``,
which was on that host, pulled, under the configured repository. A
verdict-bearing gate judged 0.3.16 while the operator believed it had pinned
0.3.47. Nothing warned, because nothing on the RUN path had ever read the pin:
``VIBEIC_EDA_IMAGE_REPO`` was read by exactly one shipped file
(``landing_pytest_runtime_preflight``) and by nothing that runs a tool.

THE PIN IS THE DIGEST. THE REPOSITORY IS DEPLOYMENT CONFIGURATION.
==================================================================
Stated first by ``tools/ci/hermetic_candidate_runner.py``, and this module is
the plugin-side half of the SAME statement, spelled with the same constant
names so the two cannot drift without a test noticing. The digest names the
bytes and is the identity — it is what every check here actually asserts. The
repository names a place those bytes can be fetched from, and which place a
given host can reach is a fact about the network, not about the runtime: the
same image, distributed to five hosts, carries the same repo digest on every
host that pulled it, while its image Id differs by storage driver.

So a deployment that serves the same bytes from elsewhere sets one env. It does
NOT edit this file, and it CANNOT change which bytes are demanded.

A DIGEST IS NOT A VERSION, AND THAT DISTINCTION IS THE WHOLE POINT
==================================================================
``_eda_image``'s own guards forbid a pinned *version* — ``vibeic-eda:0.3.16`` —
in any shipped program, and they are right: a version literal freezes silently
and keeps running an older toolchain than everything around it, and it costs a
cross-repo check-in per release. None of that is true of a digest. A version is
a NAME its publisher can re-point at other bytes; a digest IS the bytes. The
guard regex (``vibeic-eda:\\d+\\.\\d+\\.\\d+``) draws exactly this line, and
this module stays on the right side of it.

WHAT REFUSAL LOOKS LIKE
=======================
Never a fallback to another tag or another version. A host that does not hold
the pinned bytes is a host that cannot answer, and it says so by name:

    IMAGE_NOT_PRESENT: <repo>@sha256:<digest>

"I could not open the pinned image" and "I opened it and it was bad" must never
reach a reader as the same verdict — the same rule every other input in this
repo is held to.

A CONTAINER NAME IS NOT A CONTAINER IDENTITY
============================================
The second half, and the second measured defect. Every ``--container`` in this
plugin defaulted to the SHARED name ``vibeic-eda``, and no override could move
it apart from ``VIBEIC_EDA_CONTAINER``. MEASURED 2026-09-07 on 8hd-3: the
container actually named ``vibeic-eda`` on that host was running image
``sha256:06537f7e…`` (0.3.46) while the pin demanded ``sha256:8da785a8…``. A run
that attached to it recorded image provenance PASS about the WRONG image — the
report named a digest, so it looked reproducible, and it was reproducibly wrong.

A name is not a measurement. So:

  * the DEFAULT container name is DERIVED from the required digest
    (``vibeic-eda-<first 12 hex>``), which makes two different pins two
    different containers by construction, and makes the collision above
    impossible to reach by default rather than merely unlikely;
  * attaching to an EXISTING container is allowed only when that container's
    image digest IS the required one. Otherwise ``CONTAINER_IMAGE_MISMATCH``,
    naming BOTH digests, because a refusal that does not say what it found is a
    refusal the reader cannot act on;
  * "the container is gone" and "the container is the wrong image" are
    different answers and are returned as different codes.

chip-AGNOSTIC: image and container identity only. No design, PDK, vendor, IC or
host-address literal appears here — the fleet's registry is CONFIGURATION and
is never written into this tree.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional, Sequence, Tuple

__all__ = [
    "IMAGE_DIGEST",
    "IMAGE_REPO_DEFAULT",
    "IMAGE_REPO_ENV",
    "CONTAINER_NAME_ENV",
    "DIGEST_RE",
    "IMAGE_NOT_PRESENT",
    "CONTAINER_IMAGE_MISMATCH",
    "CONTAINER_ABSENT",
    "image_repo",
    "image_reference",
    "local_repo_digests",
    "pinned_image_present",
    "default_container_name",
    "container_image_digest",
    "container_matches_pin",
    "container_attach_refusal",
    "container_pin_state",
]

#: THE PIN. One literal, in one place on the plugin side, spelled exactly as
#: `tools/ci/hermetic_candidate_runner.IMAGE_DIGEST` spells it — see
#: `tests/test_the_run_path_resolves_the_pinned_image.py`, which reads that file
#: and refuses to let the two drift.
IMAGE_DIGEST = (
    "sha256:8da785a8d3275884ad0d0ee0fb10f7e90d8b7bf11a08d38e9559b0764112480f"
)
IMAGE_REPO_DEFAULT = "ghcr.io/vibeic/vibeic-eda"
IMAGE_REPO_ENV = "VIBEIC_EDA_IMAGE_REPO"

#: The one env that names a container explicitly. It OVERRIDES the derived name;
#: it does NOT override the digest requirement, and `container_matches_pin`
#: still has to agree before anything is run in it.
CONTAINER_NAME_ENV = "VIBEIC_EDA_CONTAINER"

#: The prefix a derived container name carries, so an operator reading
#: `docker ps` can still tell at a glance what a container is for.
CONTAINER_NAME_PREFIX = "vibeic-eda"

#: The only shape accepted as an identity.
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Refusal codes. Machine-readable, and each one says a DIFFERENT thing.
IMAGE_NOT_PRESENT = "IMAGE_NOT_PRESENT"
CONTAINER_IMAGE_MISMATCH = "CONTAINER_IMAGE_MISMATCH"
CONTAINER_ABSENT = "CONTAINER_ABSENT"

_TIMEOUT_S = 20


def _docker(*argv: str, timeout: int = _TIMEOUT_S) -> Tuple[int, str, str]:
    """`(rc, stdout, stderr)`; rc is -1 when docker itself could not be run.

    A docker that cannot be run is NOT a verdict about the image, and the -1 is
    what keeps the callers below from turning it into one.
    """
    try:
        r = subprocess.run(["docker", *argv], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", f"docker unusable: {type(exc).__name__}: {exc}"
    return r.returncode, r.stdout or "", r.stderr or ""


def image_repo(env=None) -> str:
    """The repository half of the pinned reference.

    Deployment configuration, read from one env. Empty or unset means the
    published repository.
    """
    env = os.environ if env is None else env
    return (env.get(IMAGE_REPO_ENV) or "").strip() or IMAGE_REPO_DEFAULT


def image_reference(env=None) -> str:
    """`<configured repo>@<pinned digest>` — the only reference this plugin runs.

    Composed, never stored: a second composed constant would be a second
    definition of the runtime, which is precisely how the harness and the
    landing preflight came to name images forty patch releases apart.
    """
    return f"{image_repo(env)}@{IMAGE_DIGEST}"


def local_repo_digests(ref: str) -> Tuple[Tuple[str, ...], str]:
    """`(repo_digests, why_not)` for `ref`, from LOCAL metadata only.

    Never touches the network, so a caller can identify what it is about to run
    without risking an unbounded multi-gigabyte fetch inside a gate.
    """
    rc, out, err = _docker("image", "inspect", "--format", "{{json .RepoDigests}}",
                           ref)
    if rc == -1:
        return (), err
    if rc != 0:
        return (), f"{ref} is not present on this host"
    line = out.strip().splitlines()
    if not line:
        return (), f"docker image inspect {ref} printed nothing"
    # FIRST TAB-SEPARATED FIELD. `_eda_image.local_digest` asks for
    # `{{json .RepoDigests}}\t{{.Id}}`, and the repo's own fake `docker`
    # answers any RepoDigests query in that two-field shape. Taking the whole
    # line here made a valid answer read as unreadable JSON -- which surfaced as
    # a gate reporting IMAGE_NOT_PRESENT about an image that was right there.
    raw, _, _rest = line[0].partition("\t")
    try:
        entries = json.loads(raw) or []
    except ValueError:
        return (), f"{ref} reported unreadable RepoDigests"
    return tuple(str(e) for e in entries), ""


def pinned_image_present(env=None) -> Tuple[Optional[str], str]:
    """`(ref, why_not)` — the pinned reference IF this host holds those bytes.

    Resolved by DIGEST, never by tag. The question asked is exactly "do this
    host's RepoDigests for the pinned reference contain
    ``<configured repo>@<pinned digest>``", because that is the identity the
    registry would also use and therefore the one a verdict can be replayed
    against on another host.

    There is deliberately NO fallback here. Not the newest local semver tag, not
    `:latest`, not the upstream image: every one of those answers a DIFFERENT
    question ("what does this machine happen to have?") and returning it would
    reproduce the defect this module was written for.
    """
    ref = image_reference(env)
    digests, why = local_repo_digests(ref)
    if why:
        return None, f"{IMAGE_NOT_PRESENT}: {ref} ({why})"
    if ref in digests:
        return ref, ""
    # `docker image inspect <repo>@<digest>` resolving while that exact
    # RepoDigest is absent would mean docker matched something else. Say what
    # was found rather than accepting it.
    return None, (f"{IMAGE_NOT_PRESENT}: {ref} (this host resolved that "
                  f"reference to an image whose RepoDigests are "
                  f"{list(digests) or 'empty'})")


def default_container_name(env=None) -> str:
    """The container name a run uses when the operator names none.

    DERIVED FROM THE REQUIRED DIGEST, so that two different pins are two
    different containers by construction. The shared literal `vibeic-eda` is
    what let a run attach to another lane's 0.3.46 container and report a PASS
    about it; a name that carries the digest cannot collide that way, and a
    reader of `docker ps` can still see what it is.

    `VIBEIC_EDA_CONTAINER` still names one explicitly — that is the operator's
    call and it is honoured. It moves the NAME only: `container_matches_pin`
    still has to agree about the bytes.
    """
    env = os.environ if env is None else env
    named = (env.get(CONTAINER_NAME_ENV) or "").strip()
    if named:
        return named
    return f"{CONTAINER_NAME_PREFIX}-{IMAGE_DIGEST.split(':', 1)[1][:12]}"


def container_image_digest(container: str) -> Tuple[Optional[str], str]:
    """`(repo_digest, why_not)` — which image bytes `container` is running.

    Prefers the container's `.Config.Image` when that is already a
    `repo@sha256:` reference (which is what `docker run` records for a
    digest-pinned start), and otherwise reads the RepoDigests of the image the
    container resolved to. Either way the answer is a REGISTRY-PORTABLE digest,
    because a verdict naming an image Id means nothing on another host.
    """
    rc, out, err = _docker("inspect", "--format",
                           "{{.Image}}\t{{.Config.Image}}", container)
    if rc == -1:
        return None, err
    if rc != 0:
        return None, f"{CONTAINER_ABSENT}: no container named {container}"
    line = out.strip().splitlines()
    if not line:
        return None, f"docker inspect {container} printed nothing"
    image_id, _, config_image = line[0].partition("\t")
    config_image = config_image.strip()
    _, _, tail = config_image.partition("@")
    if tail and DIGEST_RE.match(tail):
        return tail, ""
    digests, why = local_repo_digests(image_id.strip() or config_image)
    for entry in digests:
        _, _, digest = entry.partition("@")
        if DIGEST_RE.match(digest):
            return digest, ""
    return None, (f"{container} runs an image carrying no registry digest"
                  + (f" ({why})" if why else ""))


def container_pin_state(container: str, env=None) -> Tuple[str, str]:
    """`(state, detail)` — THREE answers, because there are three facts.

    THE ATTACH CHECK. `docker exec <name>` addresses a container by NAME, and a
    name is a label whichever process got there first is holding. Requiring the
    digest to match turns "there is something here called vibeic-eda" into "the
    bytes I pinned are here", which is the only one of the two a verdict may
    rest on.

    The third state is the one this module got WRONG on its first cut, and the
    repo's own suite caught it: `MATCH` and `MISMATCH` were returned, and
    everything else — an absent container, a docker that will not run, an image
    built locally and carrying no registry digest — was folded into the refusal.
    That makes "I could not read it" and "I read it and it was the wrong image"
    the same verdict, which is the one thing this repo holds every input to.
    They are separated here, and the two callers want different halves:

      * a VERDICT may be PASS only on ``MATCH`` — `container_matches_pin`;
      * an ATTACH may be refused only on ``MISMATCH`` — `run_in_container`.
        Refusing on ``UNREADABLE`` would turn "docker cannot describe this" into
        a claim about the image, and would stop a legitimately locally-built
        container from being used at all. Docker reports its own failure there,
        as it always did.
    """
    got, why = container_image_digest(container)
    if got is None:
        return "UNREADABLE", (why or f"{CONTAINER_ABSENT}: {container}")
    if got == IMAGE_DIGEST:
        return "MATCH", ""
    return "MISMATCH", (
        f"{CONTAINER_IMAGE_MISMATCH}: container {container} runs {got}, "
        f"but the pinned runtime is {image_repo(env)}@{IMAGE_DIGEST}; "
        f"required {IMAGE_DIGEST}, found {got}")


def container_matches_pin(container: str, env=None) -> str:
    """The empty string when `container` PROVABLY runs the pinned bytes.

    THE VERDICT-BEARING HALF. Anything short of proof is a reason, so a
    provenance verdict cannot be PASS about a container whose image nobody could
    read — the same rule as every other input in this repo.

    The refusal names BOTH digests deliberately. A reader who is told only that
    something mismatched cannot tell a stale container from a mis-set
    `VIBEIC_EDA_IMAGE_REPO`, and will re-run it.
    """
    state, detail = container_pin_state(container, env)
    return "" if state == "MATCH" else detail


def container_attach_refusal(container: str, env=None) -> str:
    """The empty string unless `container` is PROVABLY the WRONG image.

    THE ATTACH HALF. Only a measured disagreement stops a command running; a
    digest that could not be read is not one, and is left to docker to report.
    """
    state, detail = container_pin_state(container, env)
    return detail if state == "MISMATCH" else ""
