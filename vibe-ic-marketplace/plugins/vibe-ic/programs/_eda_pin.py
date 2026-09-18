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
    "ImageNotResolvable",
    "IMAGE_NOT_RESOLVABLE",
    "resolved_image_digest",
    "reset_resolved_image_digest",
    "IMAGE_REPO_DEFAULT",
    "IMAGE_REPO_ENV",
    "CONTAINER_NAME_ENV",
    "DIGEST_RE",
    "IMAGE_NOT_PRESENT",
    "IMAGE_ID_NOT_A_REFERENCE",
    "CONTAINER_IMAGE_MISMATCH",
    "CONTAINER_ABSENT",
    "image_repo",
    "image_reference",
    "is_bare_image_id",
    "reference_digest",
    "repository_of",
    "local_repo_digests",
    "local_references_for_digest",
    "container_image_reference",
    "pinned_image_present",
    "default_container_name",
    "container_image_digest",
    "container_matches_pin",
    "container_attach_refusal",
    "container_pin_state",
]

#: THE IDENTITY IS RESOLVED, NOT REMEMBERED.
#:
#: This module used to carry the digest as a literal, which made adopting a new
#: EDA image an edit to plugin SOURCE — two repositories with two release
#: cadences forced to move together. `f1653caa4`
#: ("stop storing vibeic-eda's version number in this repo") had already removed
#: exactly that coupling; `11a82fb68` reintroduced it while fixing a real
#: incident (one host naming three different images in one minute). Both
#: properties are kept here: the digest is still the IDENTITY every verdict is
#: recorded against, and it is still compared before attaching to a container —
#: it is simply ASKED FOR rather than stored.
#:
#: RESOLUTION ORDER — the one `_eda_image.judged_image` documented before the pin:
#:
#:   1. an explicit `VIBEIC_EDA_IMAGE` / `IIC_EDA_IMAGE` override, reduced to its
#:      digest. Naming an image by hand is the operator's deliberate call.
#:   2. the vibeic-eda image ALREADY ON THIS HOST, newest first, by its digest.
#:      No network and no pull — and, the load-bearing half, **a local image
#:      cannot move under you**, so two gates in one run cannot resolve to
#:      different bytes.
#:   3. the registry, ONLY when the caller passes `allow_pull=True`. A gate that
#:      silently starts a multi-gigabyte fetch is a gate people switch off.
#:
#: RESOLVED ONCE PER PROCESS. The first read fixes the answer for the whole run,
#: which is the run-wide consistency the literal was reaching for.
#:
#: UNRESOLVABLE IS NOT A VERDICT. With none of the three available this raises
#: `ImageNotResolvable` rather than returning a string nobody measured: "I could
#: not read which image this is" and "I read it and it was the wrong one" must
#: never reach a caller in the same shape — the same rule `CONTAINER_IMAGE_MISMATCH`
#: and `IMAGE_NOT_PRESENT` already state for their own failures.
IMAGE_NOT_RESOLVABLE = "IMAGE_NOT_RESOLVABLE"


class ImageNotResolvable(RuntimeError):
    """No EDA image identity could be established on this host.

    Carries the reasons each resolution step failed, in order, so the caller
    reports what was tried instead of a bare absence.
    """

    def __init__(self, tried: Sequence[str]):
        self.tried = tuple(tried)
        super().__init__(
            f"{IMAGE_NOT_RESOLVABLE}: no vibeic-eda image identity could be "
            f"resolved on this host; tried: " + "; ".join(self.tried))


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

#: A CONTENT-ADDRESSED ID, in every spelling docker accepts — including the
#: truncated prefixes it resolves. Deliberately NOT `DIGEST_RE`: that one is the
#: exact identity shape and is used to ACCEPT, this one exists to RECOGNISE AND
#: REFUSE, so it has to match everything that can arrive rather than only the
#: canonical spelling. `sha256:<hex>` is never a `repository:tag`: docker parses
#: the `sha256:` prefix as an id before it considers a repository at all, so
#: there is no repository half to recover and any attempt to split one out
#: invents one (#2085).
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]+$")

#: Refusal codes. Machine-readable, and each one says a DIFFERENT thing.
IMAGE_NOT_PRESENT = "IMAGE_NOT_PRESENT"
IMAGE_ID_NOT_A_REFERENCE = "IMAGE_ID_NOT_A_REFERENCE"
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


#: The envs an operator uses to name an image by hand. Same two `_eda_image`
#: has always honoured, in the same order.
_IMAGE_OVERRIDE_ENVS = ("VIBEIC_EDA_IMAGE", "IIC_EDA_IMAGE")

#: One resolve per process. `reset_resolved_image_digest()` clears it; tests use
#: that, and nothing in a run should.
_RESOLVED: dict = {}


#: Set alongside the cache when THIS module published the identity, so a reset
#: can tell its own export from one the operator set.
_EXPORTED = "_vibeic_eda_image_exported_by_pin"


def reset_resolved_image_digest() -> None:
    """Forget the resolved identity, INCLUDING the copy published to the env.

    Clearing only the in-process cache left `VIBEIC_EDA_IMAGE` behind, and the
    next resolve then took step 1 (the explicit override) and answered with the
    stale value — which silently bypasses whatever the caller reset in order to
    exercise. Measured: it turned three mutation arms of
    `test_the_eda_image_is_resolved_not_remembered` green against mutations
    they exist to catch. An operator-set override is NOT removed; only the one
    this module wrote.
    """
    if _RESOLVED.pop(_EXPORTED, None):
        os.environ.pop("VIBEIC_EDA_IMAGE", None)
    _RESOLVED.clear()


#: The shape vibeic-eda stamps on itself from 0.3.19. A label that does not
#: match is not this image's version — see `_version_key`.
_FORK_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _host_image_digest(repo: str) -> Tuple[Optional[str], str]:
    """The newest EDA image ON THIS HOST, by its own version label, as a digest.

    THREE THINGS THIS HAS TO GET RIGHT, all of them measured on the fleet
    2026-09-17 and all of them wrong in the obvious implementation:

    ACROSS EVERY REPOSITORY NAME, not the configured one. The same bytes are
    held under different names on different hosts, and docker attaches the
    RepoDigest to the name it was actually PULLED from. Measured: on one host
    the ghcr name carried the digest and the mirror name showed `<none>`; on
    another the mirror carried it and ghcr showed `<none>` — for the identical
    image. Asking only the configured repository finds nothing on half the
    fleet and then silently answers with something older.

    ONLY ENTRIES THAT CARRY A REGISTRY DIGEST. A locally built or `docker
    load`ed image has an Id but no RepoDigest, and an Id is not an identity any
    other host can replay (`IMAGE_ID_NOT_A_REFERENCE`). Offering one here makes
    the attach check refuse the host's own correct container.

    NEWEST BY THE IMAGE'S OWN `org.opencontainers.image.version` LABEL, not by
    tag text and not by docker's ordering. Tags are re-pointed — a mirror
    `latest` was measured sitting on an image five releases old — so the label
    the build stamped on itself is the only statement of which release this is.
    """
    rc, out, _err = _docker("image", "ls", "--digests", "--format",
                            "{{.Repository}}\t{{.Digest}}\t{{.ID}}")
    if rc == -1:
        return None, _err
    if rc != 0:
        return None, f"docker image ls failed: {rc}"

    short = repo.rsplit("/", 1)[-1]
    seen, candidates = set(), []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, digest, image_id = (x.strip() for x in parts[:3])
        if short not in name:
            continue
        got = reference_digest(f"{name}@{digest}") if digest and digest != "<none>" else None
        if not got or got in seen:
            continue
        seen.add(got)
        candidates.append((got, image_id))

    if not candidates:
        # FALL BACK TO ASKING THE CONFIGURED REPOSITORY DIRECTLY. The listing
        # above is the better question -- it sees the image under whatever name
        # this host pulled it as -- but it is not the only one, and an
        # environment whose docker does not answer `images` in this shape would
        # otherwise report "no image" while holding one. Asking the configured
        # reference by inspect is the narrow question, and a narrow answer beats
        # a wrong absence.
        digests, why_direct = local_repo_digests(repo)
        got = next((d for d in (reference_digest(x) for x in digests) if d), None)
        if got:
            return got, ""
        return None, (f"no {short} image on this host carries a registry digest "
                      f"(listing found none; {repo}: {why_direct or 'no digest'})")

    def _version_key(image_id: str):
        rc2, o2, _ = _docker("image", "inspect", "--format",
                             '{{index .Config.Labels "org.opencontainers.image.version"}}',
                             image_id)
        label = o2.strip() if rc2 == 0 else ""
        # THE FORK'S OWN VERSION ONLY. Images before vibeic-eda 0.3.19 inherit
        # upstream iic-osic-tools' `2026.06` in this label — a calendar stamp,
        # not a release of this image. Sorted numerically it outranks every
        # 0.3.x, so an inherited label on a months-old build would present
        # itself as the newest thing on the host (MEASURED: it did, and picked
        # a 0.3.13 image over 0.3.63). Only the three-part shape the fork
        # stamps counts; anything else is NO version statement.
        m = _FORK_VERSION_RE.fullmatch(label)
        return tuple(int(x) for x in m.groups()) if m else ()

    ranked = sorted(candidates, key=lambda c: _version_key(c[1]), reverse=True)
    top, _ = ranked[0]
    if not _version_key(ranked[0][1]):
        return None, (f"{len(candidates)} {short} image(s) carry a digest but none "
                      "states org.opencontainers.image.version; which release this "
                      "is cannot be read, and a guess is not an identity")
    return top, ""


def _registry_image_digest(repo: str) -> Tuple[Optional[str], str]:
    """What the registry currently calls `repo:latest`, by digest."""
    rc, out, err = _docker("manifest", "inspect", "-v", f"{repo}:latest",
                           timeout=60)
    if rc != 0:
        return None, f"registry did not answer for {repo}:latest: " \
                     f"{(err or out).strip()[:120] or rc}"
    m = re.search(r'"digest"\s*:\s*"(sha256:[0-9a-f]{64})"', out)
    return (m.group(1), "") if m else (
        None, f"registry answer for {repo}:latest carried no digest")


def resolved_image_digest(env=None, *, allow_pull: bool = False) -> str:
    """THE identity, resolved once per process. Never stored in this repo.

    Raises `ImageNotResolvable` when no step answers — see the doctrine comment
    above `IMAGE_NOT_RESOLVABLE`.
    """
    env = os.environ if env is None else env
    if "digest" in _RESOLVED:
        return _RESOLVED["digest"]

    def _hold(digest: str) -> str:
        """Fix this identity for the whole PROCESS TREE, not just this process.

        A run is many processes: the runner spawns a step, the step spawns a
        gate. If each resolved independently, an image landing on the host
        mid-run would move the answer under them — and the attach check, which
        re-asks on EVERY exec, would start refusing the very container the run
        has been using for hours. Publishing the resolved identity into the
        environment makes every child take step 1 (the explicit override) and
        agree by construction, which is what "resolve once per run" means when
        the run is not one process.
        """
        _RESOLVED["digest"] = digest
        if not (env.get("VIBEIC_EDA_IMAGE") or "").strip():
            try:
                os.environ["VIBEIC_EDA_IMAGE"] = f"{image_repo(env)}@{digest}"
                _RESOLVED[_EXPORTED] = True
            except Exception:
                pass
        return digest

    tried = []
    repo = image_repo(env)

    for key in _IMAGE_OVERRIDE_ENVS:
        named = (env.get(key) or "").strip()
        if not named:
            continue
        if is_bare_image_id(named):
            tried.append(f"{key}={named} is {IMAGE_ID_NOT_A_REFERENCE}")
            continue
        got = reference_digest(named)
        if got:
            return _hold(got)
        digests, why = local_repo_digests(named)
        got = next((d for d in (reference_digest(x) for x in digests) if d), None)
        if got:
            return _hold(got)
        tried.append(f"{key}={named} carries no digest ({why or 'not present'})")

    got, why = _host_image_digest(repo)
    if got:
        return _hold(got)
    tried.append(f"this host: {why}")

    if allow_pull:
        got, why = _registry_image_digest(repo)
        if got:
            return _hold(got)
        tried.append(f"registry: {why}")
    else:
        tried.append("registry: not asked (allow_pull=False)")

    raise ImageNotResolvable(tried)


def __getattr__(name):
    """`IMAGE_DIGEST` stays readable as a module attribute (PEP 562).

    Every caller in this tree reads it as `_pin.IMAGE_DIGEST`; keeping that
    spelling is what lets the identity become resolved without touching them.
    """
    if name == "IMAGE_DIGEST":
        return resolved_image_digest()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def image_reference(env=None) -> str:
    """`<configured repo>@<pinned digest>` — the only reference this plugin runs.

    Composed, never stored: a second composed constant would be a second
    definition of the runtime, which is precisely how the harness and the
    landing preflight came to name images forty patch releases apart.
    """
    return f"{image_repo(env)}@{resolved_image_digest(env)}"


def is_bare_image_id(value) -> bool:
    """True when `value` is a bare content-addressed id — `sha256:<hex>`.

    THE SHAPE THAT LOOKS LIKE A REFERENCE AND IS NOT, and the reason this
    predicate is public. `docker run sha256:<id>` works, so a bare Id reaches
    every site that merely RUNS one without complaint; but it carries no
    repository half, so it names nothing another host can fetch and a verdict
    holding it can be neither replayed nor attributed. Worse, it survives the
    `repository:tag` split that every reference parser starts with: `sha256`
    becomes the repository and the hex becomes the tag.

    MEASURED 2026-09-07 on 8hd-3 (#2085): the front door exported a container's
    `.Image` into `VIBEIC_EDA_IMAGE`, `_eda_image` re-attached the pinned digest
    to that invented repository, and the run handed `docker run` the reference
    ``sha256@sha256:8c5694…`` -- rc=125, "pull access denied for sha256". The
    step degraded to NOT_DETERMINED, so a malformed reference and a technology
    that states no database unit reached the reader as the same answer.

    An Id is a fine ARGUMENT and never an IDENTITY. `image_reference()` composes
    the identity this plugin runs, and it always carries a repository.
    """
    return bool(_IMAGE_ID_RE.match(str(value or "").strip()))


def reference_digest(ref) -> Optional[str]:
    """The digest `<repo>@sha256:<digest>` names, else None.

    BOTH HALVES ARE REQUIRED. A `@` tail that is a digest is not enough with
    nothing in front of it: a repository-less `@sha256:…` is the same malformed
    shape as `sha256@sha256:…` and this module refuses to recognise either as a
    reference.
    """
    head, sep, tail = str(ref or "").strip().partition("@")
    return tail if (sep and head and DIGEST_RE.match(tail)) else None


def repository_of(ref) -> str:
    """The repository half of `ref`, or "" when it has none.

    Returns "" for a bare Id rather than inventing `sha256` from the colon, and
    that empty string is load-bearing: a caller composing `f"{repo}@{digest}"`
    must be able to tell "this reference names a place" from "this one does
    not", because #2085 is exactly what happens when it cannot.
    """
    ref = str(ref or "").strip()
    if is_bare_image_id(ref):
        return ""
    head = ref.split("@", 1)[0]
    name, _, tag = head.rpartition(":")
    # `host:5000/x` has a colon that is a PORT, not a tag: a tag never contains
    # a slash.
    return name if (name and "/" not in tag) else head


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



def local_references_for_digest(digest: str) -> Tuple[Tuple[str, ...], str]:
    """`(references, why_not)` — every LOCAL reference carrying `digest`, under
    ANY repository name.

    THE DIGEST IS THE IDENTITY; THE REPOSITORY IS CONFIGURATION (#2170). The
    same bytes, pushed to a second registry and pulled from it, are the same
    runtime: they carry the same repo digest and differ only in the half that
    says WHERE they were fetched. Asking "is this exact reference present"
    therefore answers a question about this host's network, not about the
    runtime, and MEASURED 2026-09-07 on 8HD-9 it answered NO about an image
    that was right there — `<fleet-mirror>/vibeic-eda@<pin>` was held and
    `ghcr.io/vibeic/vibeic-eda@<pin>` was the string being compared.

    THIS DOES NOT WIDEN ANYTHING. A reference is returned only when its digest
    IS the requested one, so an image whose digest differs is refused exactly
    as strictly as before; the only thing that stopped mattering is which
    repository name the bytes arrived under. Local metadata only — never the
    network, so no caller can be made to start a pull.

    THE `-a` IS LOAD-BEARING AND WAS MISSING (#2170, isolated by lane czpinconf
    on 8HD-9). An image pulled BY DIGEST and never tagged is DANGLING, and plain
    `docker image ls` lists tagged images only — it HIDES exactly the state a
    digest-pinned deployment produces. Measured on 8HD-9, which holds the pin
    under one name and no tag: 0 rows without `-a`, 1 row with it. So this
    returned `((), "")` — EMPTY, WITH NO ERROR, the worst possible pair — about a
    host that demonstrably held the pinned image, and no caller could tell
    "nothing carries it" from "I did not ask for it".
    """
    rc, out, err = _docker("image", "ls", "-a", "--digests", "--no-trunc",
                           "--format", "{{.Repository}}@{{.Digest}}")
    if rc == -1:
        return (), err
    if rc != 0:
        return (), "docker image ls could not be read"
    found = []
    for line in out.splitlines():
        entry = line.strip()
        # `<none>@<none>` and untagged rows carry no reference; `reference_digest`
        # already refuses anything without BOTH halves.
        if reference_digest(entry) == digest and repository_of(entry) not in (
                "", "<none>"):
            found.append(entry)
    return tuple(dict.fromkeys(found)), ""


def pinned_image_present(env=None) -> Tuple[Optional[str], str]:
    """`(ref, why_not)` — the pinned reference IF this host holds those bytes.

    Resolved by DIGEST, never by tag AND NEVER BY REPOSITORY (#2170). The
    question asked is exactly "does this host hold an image whose registry
    digest is ``<pinned digest>``", under whatever repository name it was
    pulled from. The digest is the identity a verdict can be replayed against
    on another host; the repository is where that host was told to fetch the
    bytes, and on a fleet serving them from a mirror it is a different string
    for the same runtime.

    There is deliberately NO fallback here. Not the newest local semver tag, not
    `:latest`, not the upstream image: every one of those answers a DIFFERENT
    question ("what does this machine happen to have?") and returning it would
    reproduce the defect this module was written for.
    """
    ref = image_reference(env)
    digests, why = local_repo_digests(ref)
    pinned = resolved_image_digest(env)
    if not why and any(reference_digest(d) == pinned for d in digests):
        # The configured repository holds the pinned bytes. Answer with the
        # reference the operator named, so a reader sees the name they set.
        return ref, ""
    # THE CONFIGURED REPOSITORY IS NOT THE IDENTITY (#2170). Either that name
    # is not held here, or docker resolved it to bytes carrying a different
    # digest. Both are answered by the same question, asked correctly: does
    # THIS HOST hold an image whose digest is the pinned one, under ANY name?
    held, why_ls = local_references_for_digest(pinned)
    if held:
        return held[0], ""
    if why_ls:
        # "Could not read it" is not "read it and it was absent".
        return None, (f"{IMAGE_NOT_PRESENT}: {pinned} (this host could "
                      f"not be asked what it holds: {why_ls})")
    return None, (f"{IMAGE_NOT_PRESENT}: {pinned} (no image on this host "
                  f"carries that digest under any repository; {ref} "
                  + (f"is not present: {why}" if why else
                     f"resolved to an image whose RepoDigests are "
                     f"{list(digests) or 'empty'}") + ")")


def default_container_name(env=None) -> str:
    """The container name a run uses when the operator names none.

    THE SHARED NAME, which is also what `.mcp.json` sets as `EDA_CONTAINER`, so
    the MCP tools and the programs address ONE container instead of two.

    This was a digest-derived name while the digest was a literal: with a pin
    that never moved, the shared name was guaranteed to hold the wrong bytes,
    and deriving the name from the pin was the way to avoid attaching to it.
    That reasoning does not survive the pin's removal — the identity is now
    whatever this host actually has, so the shared container IS the right one by
    construction, and the two paths were only ever split because the pin had
    gone stale.

    THE SAFETY THAT MATTERS IS UNCHANGED, and it never lived in the name:
    `container_matches_pin` still measures the container's image digest and
    still refuses a container holding different bytes. A name cannot make that
    check weaker; it only decides which container gets asked.

    `VIBEIC_EDA_CONTAINER` still names one explicitly, for an operator running
    lanes side by side that must not share a container.
    """
    env = os.environ if env is None else env
    named = (env.get(CONTAINER_NAME_ENV) or "").strip()
    return named or CONTAINER_NAME_PREFIX


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


def container_image_reference(container: str) -> Tuple[Optional[str], str]:
    """`(reference, why_not)` — a REGISTRY-PORTABLE `<repo>@sha256:<digest>` for
    the bytes `container` is running, or the reason there is none.

    THE SHAPE A CHILD CAN RUN, which is a different question from
    `container_image_digest`'s. That one answers WHICH BYTES, and a digest alone
    is the right answer for a verdict and the wrong one for a value handed to a
    child that will `docker run` it: a digest is not a reference
    (`is_bare_image_id`). Both are composed here out of the SAME inspection, so
    the value a child receives and the identity the provenance record asserts
    cannot be two different images.

    NO INVENTED REPOSITORY, and no fallback to an Id. A container started from
    an Id, whose image carries no RepoDigest, has no portable reference and this
    says so — "I could not name it portably" and "here, run this" must not reach
    the caller as the same answer (#2085).
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
    image_id, config_image = image_id.strip(), config_image.strip()
    # STARTED FROM A DIGEST-PINNED REFERENCE. docker records it verbatim in
    # `.Config.Image`, and it is already the answer -- same repository the
    # operator named, same digest, nothing recomposed.
    if reference_digest(config_image):
        return config_image, ""
    # Started from a tag, or from an Id. Recover the portable reference from the
    # image's own RepoDigests, preferring the repository the container was
    # started from so a host holding the same bytes under two names answers with
    # the one the operator named.
    digests, why = local_repo_digests(image_id or config_image)
    want = repository_of(config_image)
    ranked = sorted(digests, key=lambda d: 0 if repository_of(d) == want else 1)
    for entry in ranked:
        if reference_digest(entry):
            return entry, ""
    return None, (f"{container} runs an image carrying no registry digest, so "
                  f"it cannot be named by a reference any other host resolves"
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
    try:
        required = resolved_image_digest(env)
    except ImageNotResolvable as exc:
        # Both identities must be readable to measure a disagreement. Keep
        # resolution failure in the same third state as an unreadable container:
        # attach may proceed, but container_matches_pin cannot certify it.
        return "UNREADABLE", str(exc)
    if got == required:
        return "MATCH", ""
    return "MISMATCH", (
        f"{CONTAINER_IMAGE_MISMATCH}: container {container} runs {got}, "
        f"but the pinned runtime is {image_repo(env)}@{required}; "
        f"required {required}, found {got}")


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
