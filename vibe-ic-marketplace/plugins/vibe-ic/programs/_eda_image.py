#!/usr/bin/env python3
"""Which vibeic-eda image to run — asked, not remembered.

WHY THIS EXISTS
===============
This plugin used to carry the image version as a literal in eleven places, kept
in step by `tools/vibeic-eda/sync_image_version.py --check` and advanced by a PR
that vibeic-eda's daily release opened on this repo. The stated reason was that
the pinned tag "matches what the plugin was VERIFIED AGAINST".

Measured 2026-08-20: nothing ever verified that. The release established that
the tag was PULLABLE and then wrote the claim anyway, on every publish. The
claim was false the moment it was written, and it cost a cross-repo check-in per
image release — plus a loop where the open anchor PR made the next round's
publish gate non-zero and skipped the public page.

And the claim was never needed. vibeic-eda is built FOR this plugin and sits
under it. Its own release gate already establishes what this layer would have
re-checked: `check_no_capability_lost` proves 78 commands across 17 replaced
prefixes still resolve in the new image, 439 fork self-checks run, every declared
PDK is present with the version shape it promises, and the build refuses unless
sby/yices, ALIGN, klayout and the xyce plugin builder all work. A release that
passes that is usable by construction. A second opinion from up here, with less
evidence, adds nothing.

So: no pinned version, no anchor, no sync tool, no PR. Ask which image is
current and run that.

A GATE JUDGES A DIGEST, NOT A REMEMBERED VERSION
================================================
This module used to answer a THIRD question — `anchor_image()`, "which image does
THIS CHECKOUT name" — read from `tools/vibeic-eda/VERSION`, a file in this repo
holding vibeic-eda's version number. Its purpose was vibe-ic#927's: a gate that
reports FAIL about the image's CONTENTS must not have its verdict moved by a third
party's push.

That file is GONE, and the reason is measured rather than preferred. It cost a PR
in this repo per vibeic-eda release, and what it bought was not protection:

  * MEASURED 2026-08-21 on 8HD-9: the anchor said 0.3.16 and this host's newest
    vibeic-eda image was 0.3.13. `docker run ...:0.3.16` printed "Unable to find
    image locally" and began a multi-gigabyte pull — inside a hygiene gate. The
    anchored gate was not judging an old image safely; it was judging an image the
    machine does not have, at a cost that gets a gate switched off;
  * `sync_image_version.py --check`, the gate that kept the anchor consistent, was
    RED on main for `crosslayer_rewrite_equivalence.py:379` — a comment recording
    which image a measurement was taken on. The coupling was demanding that a
    measurement record be falsified;
  * of 11 registered install docs only ONE still carried an X.Y.Z pin at all. The
    documentation had already decoupled itself.

The property #927 actually needs is REPRODUCIBILITY AND ATTRIBUTION, not
immutability: say exactly WHICH bytes were judged, so the verdict can be re-run and
so a red is attributable to the image rather than to the change under test.

TWO FACTS, ASKED OF THE IMAGE, NEITHER STORED HERE
==================================================
  the DIGEST   `repo@sha256:…` — immutable, and what you replay with;
  the VERSION  the image's own standard `org.opencontainers.image.version`
               label — immediately readable, and what a human says out loud.

The version is READ FROM THE IMAGE and BELIEVED. Nothing here validates its shape
or corrects it: published images today still inherit upstream iic-osic-tools'
value (`2026.06`), and from vibeic-eda 0.3.19 the label carries the fork's own
version. Both are recorded verbatim, and the changeover costs no edit here. A
shape check would be a workaround for one release window and dead code forever
after.

`judged_image()` replaces `anchor_image()` and returns both. It PREFERS THE IMAGE
ALREADY ON THIS HOST — which also removes the one new failure mode a resolved
reference introduces, two gates in one CI run resolving a floating tag at
different minutes and silently judging different images. A local image cannot
move under you. Reaching the registry, which can, is behind an explicit
`allow_pull`.

WHEN THE IMAGE WILL NOT SAY, THAT IS NOT_MEASURED, NOT A VERDICT. A gate that
could not resolve a digest, or could not read the label, exits its own
"cannot check" code with its marker printed. "I could not read it" and "I read it
and it was bad" must never produce the same verdict — see `unidentified_reason`.

`:latest` IS NOT ENOUGH, and this is the part worth keeping
===========================================================
`docker run …:latest` does NOT consult the registry. If the machine already has
something tagged `latest`, that is what runs — however old. The predecessor of
this module records the matching incident from the other direction: it was once
hardcoded to `hpretl/iic-osic-tools:latest`, and on a machine that had only the
fork pulled, `docker run` failed with image-not-found and the whole DFT step
silently died.

So `resolve()` asks the REGISTRY what `latest` means and returns that DIGEST.
A digest cannot be a stale local tag. When the registry cannot be reached the
fallback is the newest vibeic-eda tag actually present locally — and it SAYS SO
on stderr, because a toolchain quietly older than the one the caller believes it
is running is the failure this module exists to prevent.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import NamedTuple, Optional, Tuple

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

#: The published repository, and the DEFAULT half of the one config point. Kept
#: as a name here because this module also answers questions ABOUT a repository
#: (`local_tags`, `registry_digest`) that are not the pin. What RUNS comes from
#: `_eda_pin.image_reference()`, never from this constant.
IMAGE_REPO = _pin.IMAGE_REPO_DEFAULT
#: Last resort only. The upstream image this fork descends from; it lacks the
#: forked tools (Fault, the patched yosys/iverilog) that most callers need.
LEGACY_IMAGE = "hpretl/iic-osic-tools:latest"
_ENV_KEYS = ("VIBEIC_EDA_IMAGE", "IIC_EDA_IMAGE")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TIMEOUT_S = 20
#: The only shape this module accepts as an IDENTITY. A tag — any tag, `latest`
#: or `0.3.16` — is a NAME its publisher can re-point at other bytes; a digest is
#: the bytes. MEASURED 2026-08-21 on this host: the local `latest` tag carried
#: RepoDigest sha256:549357686ed1… while the registry's `latest` was
#: sha256:f34af8763eb0… — the same name, two different images, same minute.
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The standard OCI label every image carries. This is the ONE way this repo
#: learns a vibeic-eda version number: asked of the image, believed verbatim.
#: It is NOT validated, corrected or second-guessed — a check on its shape
#: would be a transition workaround for one release window and dead code
#: forever after. Today published images still inherit upstream
#: iic-osic-tools' value (`2026.06`); from vibeic-eda 0.3.19 the label is the
#: fork's own version, and nothing here changes when that happens.
VERSION_LABEL = "org.opencontainers.image.version"


def _run(*argv: str, timeout: int = _TIMEOUT_S):
    return _pr.run_best_effort(argv, capture_output=True, text=True)


def registry_digest(repo: str = IMAGE_REPO, tag: str = "latest") -> Optional[str]:
    """The digest `repo:tag` names IN THE REGISTRY, or None if it cannot be read.

    `docker manifest inspect` is authoritative and immediate — the same thing a
    `docker pull` consults — and unlike GHCR's `/tags/list` it is not cached.
    (That cache once still named 0.3.11 as newest a full hour after 0.3.12 was
    published and readable, which made a verified release record itself blocked.)
    """
    try:
        r = _run("docker", "manifest", "inspect", "--verbose", f"{repo}:{tag}")
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r'"digest"\s*:\s*"(sha256:[0-9a-f]{64})"', r.stdout or "")
    return m.group(1) if m else None


def local_tags(repo: str = IMAGE_REPO) -> list[str]:
    """Semver tags of `repo` present on this machine, newest first."""
    try:
        r = _run("docker", "images", "--format", "{{.Tag}}", repo)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    vers = [t for t in (r.stdout or "").split() if _SEMVER.match(t)]
    return sorted(vers, key=lambda v: tuple(int(x) for x in v.split(".")),
                  reverse=True)


def local_image(repo: str = IMAGE_REPO, env=None) -> Optional[str]:
    """A ref this machine can run WITHOUT a registry pull, else None.

    NOT the same question as `resolve()`, and the difference is load-bearing.
    `resolve()` always returns something runnable-in-principle; handing that to
    `docker run` when nothing is local starts a 6.68 GB fetch across 84 layers,
    which from the caller's point of view is not a slow run but an unbounded
    one. Callers that must distinguish "present" from "would have to be
    fetched" — skip guards, preflights — ask this instead.

    Never touches the network. An explicit override is honoured as-is: the
    caller named that image on purpose and may well intend it to be pulled.
    """
    env = os.environ if env is None else env
    for key in _ENV_KEYS:
        override = (env.get(key) or "").strip()
        if override:
            return override
    # THE PINNED BYTES, OR NOTHING. The newest local semver tag used to be the
    # answer here, and it answers a different question -- "what does this
    # machine happen to have?" -- which is how a host holding the pinned image
    # still reported the 0.3.16 tag it had also kept.
    ref, _why = _pin.pinned_image_present(env)
    return ref


class JudgedImage(NamedTuple):
    """What a verdict-bearing gate is judging, and how it knows.

    `ref` is what to hand `docker run` and is ALWAYS digest-pinned. `digest` is
    the same identity as a bare `sha256:…`, and it is what goes into the report:
    a verdict about an image nobody can name again is not reproducible, so a
    report without this field is not a valid report.

    `why_not` is non-empty exactly when `ref` is None, and it is a sentence the
    caller prints. "I could not open an image" and "I opened one and it was bad"
    must never reach a reader as the same verdict.
    """
    ref: Optional[str]
    digest: Optional[str]
    #: "repo-digest" (registry-portable, read locally) | "image-id"
    #: (content-addressed, this host only) | "registry-manifest" | "given".
    digest_kind: str
    #: "override" | "local" | "registry" | "" when nothing was found.
    source: str
    why_not: str
    #: What the image SAYS its version is — its `org.opencontainers.image.version`
    #: label, verbatim. The digest is what you REPLAY with; this is what a human
    #: says out loud. Both are recorded because neither substitutes for the other.
    version: Optional[str] = None
    #: "local-label" | "registry-label" | "".
    version_source: str = ""
    version_why_not: str = ""

    def as_report_fields(self) -> dict:
        """The fields every verdict-bearing report carries. One shape, so two
        gates cannot describe the same fact differently."""
        return {"image": self.ref, "image_digest": self.digest,
                "image_digest_kind": self.digest_kind,
                "image_source": self.source,
                "image_version": self.version,
                "image_version_source": self.version_source}


def _repo_of(ref: str) -> str:
    """The repository half of `ref`, with any tag or digest removed."""
    head = ref.split("@", 1)[0]
    name, _, tag = head.rpartition(":")
    # `host:5000/x` has a colon that is a PORT, not a tag: a tag never contains
    # a slash.
    return name if (name and "/" not in tag) else head


def local_digest(ref: str) -> Tuple[Optional[str], str, str]:
    """`(digest, kind, why_not)` for `ref` from LOCAL metadata only.

    Never touches the network, so a gate can identify what it is about to run
    without risking an unbounded fetch. Prefers the RepoDigest — the identity the
    registry would also use, so a recorded verdict can be replayed on another
    host — and falls back to the image `.Id`, which is content-addressed but
    means nothing off this machine. The KIND is returned rather than folded in,
    because "this digest is portable" and "this digest is local" are different
    claims and the report states which one it holds.
    """
    try:
        r = _run("docker", "image", "inspect", "--format",
                 "{{json .RepoDigests}}\t{{.Id}}", ref)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", f"docker unusable: {type(exc).__name__}: {exc}"
    if r.returncode != 0:
        return None, "", f"{ref} is not present on this host"
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return None, "", f"docker image inspect {ref} printed nothing"
    raw, _, image_id = line[0].partition("\t")
    try:
        repo_digests = json.loads(raw) or []
    except ValueError:
        repo_digests = []
    want = _repo_of(ref)
    ranked = sorted(repo_digests,
                    key=lambda d: 0 if d.split("@", 1)[0] == want else 1)
    for entry in ranked:
        _, _, digest = entry.partition("@")
        if DIGEST_RE.match(digest):
            return digest, "repo-digest", ""
    image_id = image_id.strip()
    if DIGEST_RE.match(image_id):
        return image_id, "image-id", ""
    return None, "", f"{ref} is present but carries no usable digest"


def image_digest(ref: str, *, allow_registry: bool = True
                 ) -> Tuple[Optional[str], str, str]:
    """`(digest, kind, why_not)` — local first, then the registry if permitted."""
    _, _, tail = ref.partition("@")
    if tail and DIGEST_RE.match(tail):
        return tail, "given", ""
    digest, kind, why = local_digest(ref)
    if digest:
        return digest, kind, why
    if not allow_registry:
        return None, "", why
    repo = _repo_of(ref)
    tag = ref.rsplit(":", 1)[-1] if ":" in ref.rsplit("/", 1)[-1] else "latest"
    remote = registry_digest(repo, tag)
    if remote:
        return remote, "registry-manifest", ""
    return None, "", (why or f"{ref} is not present locally") + \
        f" and the registry could not be read for {repo}:{tag}"


def local_version_label(ref: str) -> Tuple[Optional[str], str]:
    """`(version, why_not)` — the OCI version label, read from LOCAL metadata.

    13 ms and no network (measured). `docker image inspect` reads the same
    `org.opencontainers.image.version` the registry serves, out of the config
    blob this host already has.
    """
    try:
        r = _run("docker", "image", "inspect", "--format",
                 "{{index .Config.Labels \"" + VERSION_LABEL + "\"}}", ref)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"docker unusable: {type(exc).__name__}: {exc}"
    if r.returncode != 0:
        return None, f"{ref} is not present on this host"
    got = (r.stdout or "").strip()
    # Go's template prints `<no value>` for a missing key. An ABSENT label and a
    # label reading the empty string are both "the image does not say", and
    # neither may reach a report as a version.
    if not got or got == "<no value>":
        return None, f"{ref} carries no {VERSION_LABEL} label"
    return got, ""


def registry_version_label(ref: str) -> Tuple[Optional[str], str]:
    """`(version, why_not)` — the same label, read from the REGISTRY.

    `docker buildx imagetools inspect` reads a manifest without pulling, and it
    accepts a digest — which is the case that matters, because a digest is
    immutable and unreadable and this turns it back into something a human can
    say out loud.

    buildx is a CLI PLUGIN and is not always installed: measured 2026-08-21 on
    8HD-9, `docker buildx version` is "unknown command" on docker 29.1.3 with
    only `docker-compose` and `docker-trust` in the plugin directory. That is why
    `local_version_label` is tried first rather than this — not a fallback for
    the label's content, a second route to the identical label.
    """
    try:
        r = _run("docker", "buildx", "imagetools", "inspect", ref, "--format",
                 "{{index .Image.Config.Labels \"" + VERSION_LABEL + "\"}}",
                 timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"docker buildx unusable: {type(exc).__name__}: {exc}"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return None, (f"docker buildx imagetools inspect {ref} rc={r.returncode}"
                      + (f": {tail[0][:160]}" if tail else ""))
    got = (r.stdout or "").strip()
    if not got or got == "<no value>":
        return None, f"{ref} carries no {VERSION_LABEL} label"
    return got, ""


def image_version(ref: str) -> Tuple[Optional[str], str, str]:
    """`(version, source, why_not)` — what the image SAYS its version is.

    Believed verbatim. This function does not know what a vibeic-eda version
    looks like and must not learn: the whole point of deleting
    `tools/vibeic-eda/VERSION` was to stop this repo holding an opinion about
    the other repo's numbering.
    """
    version, why_local = local_version_label(ref)
    if version:
        return version, "local-label", ""
    version, why_remote = registry_version_label(ref)
    if version:
        return version, "registry-label", ""
    return None, "", f"{why_local}; and {why_remote}"


def judged_image(env=None, *, explicit: Optional[str] = None,
                 allow_pull: bool = False, repo: str = IMAGE_REPO
                 ) -> JudgedImage:
    """The image a VERDICT-BEARING gate judges, pinned by digest.

    THE THIRD QUESTION, and the one vibe-ic#927 asked first. `resolve()` asks the
    registry, so what it returns changes when anyone publishes — right for RUNNING
    a tool, and the reason a gate must not simply call it and report about
    whatever came back without saying what that was.

    The answer here is an IDENTITY, never a remembered version. Order:

      1. an explicit `--image` or `VIBEIC_EDA_IMAGE`/`IIC_EDA_IMAGE` override,
         resolved to its digest — naming an image by hand is the operator's
         deliberate call, and it is still pinned so the report can name it;
      2. the newest vibeic-eda image ALREADY ON THIS HOST, by its digest. No
         network, no pull, and it cannot move between two gates in one CI run;
      3. the registry's current `latest`, ONLY when the caller passes
         `allow_pull`. Handing `docker run` a digest this host does not have
         starts a multi-gigabyte fetch, and a gate that does that silently is a
         gate people switch off (the reasoning
         `input_doc_pdk_claim_vs_installed_pdk_check.start_pinned_container`
         already records, applied to the gates that never got it).

    With none of the three, `ref` is None and `why_not` says what was tried. It
    does NOT fall back to `LEGACY_IMAGE`: upstream iic-osic-tools carries none of
    the forked tools, so a verdict about it is a verdict about the wrong image.
    """
    env = os.environ if env is None else env
    chosen = (explicit or "").strip()
    if not chosen:
        for key in _ENV_KEYS:
            chosen = (env.get(key) or "").strip()
            if chosen:
                break
    if chosen:
        digest, kind, why = image_digest(chosen)
        if not digest:
            return JudgedImage(None, None, "", "override", (
                f"{chosen} was named explicitly but no immutable digest could be "
                f"resolved for it ({why}); a verdict about an image that cannot "
                f"be identified again is not reproducible"))
        return _with_version(JudgedImage(_pinned(chosen, digest, kind), digest,
                                         kind, "override", ""))

    # THE PIN, RESOLVED BY DIGEST. Not the newest local tag: MEASURED
    # 2026-09-07 on 8hd-3, this rung returned `ghcr.io/vibeic/vibeic-eda@
    # sha256:f6b09c13…` -- the 0.3.16 tag this host also happened to keep --
    # while the pinned bytes were present under the configured repository. The
    # gate judged 0.3.16 and the report named it, so it read as reproducible;
    # it was reproducibly about the wrong image.
    ref = _pin.image_reference(env)
    present, why_absent = _pin.pinned_image_present(env)
    if present:
        return _with_version(JudgedImage(present, _pin.IMAGE_DIGEST,
                                         "repo-digest", "pinned", ""))

    if allow_pull:
        # The registry is asked about THE PINNED DIGEST, never about `latest`.
        # Opting into a pull is opting into fetching the bytes that were
        # pinned, and cannot become opting into whichever bytes are newest.
        remote, _kind, _why = image_digest(ref, allow_registry=True)
        if remote == _pin.IMAGE_DIGEST:
            return _with_version(JudgedImage(ref, _pin.IMAGE_DIGEST,
                                             "registry-manifest", "registry", ""))

    # NO FALLBACK. Not another tag, not another version, not the upstream
    # image: each of those is an answer about a DIFFERENT toolchain, and
    # returning one is what made a verdict about the wrong image possible.
    tried = why_absent or f"{_pin.IMAGE_NOT_PRESENT}: {ref}"
    if not allow_pull:
        tried += ("; this gate does not pull, because a multi-gigabyte download "
                  "is the operator's call, not a gate's (pass --allow-pull, or "
                  "--image, if that is what you mean)")
    else:
        tried += " and the registry could not confirm the pinned digest"
    return JudgedImage(None, None, "", "", tried)


def _with_version(judged: JudgedImage) -> JudgedImage:
    """Ask the image what version it is, and record the answer or the reason.

    Asked ONCE, here, so a report cannot carry a digest and a version that were
    resolved from two different references. Costs 13 ms on the local path
    (measured); the registry path is only reached for an image this host does
    not hold, which is already the slow case.
    """
    version, source, why = image_version(judged.ref or "")
    return judged._replace(version=version, version_source=source,
                           version_why_not=why)


def _pinned(ref: str, digest: str, kind: str) -> str:
    """A runnable reference that names `digest` and nothing mutable.

    A RepoDigest becomes `repo@sha256:…`, which resolves against a locally
    pulled tag WITHOUT a network round-trip (verified: `docker run --pull never
    ghcr.io/vibeic/vibeic-eda@sha256:24b5…` exits 0 on a host holding only the
    `0.3.13` tag). An `.Id` is handed over bare — `docker run sha256:<id>` also
    works — because `repo@<config-id>` is not a reference docker can resolve.
    """
    if kind == "repo-digest":
        return f"{_repo_of(ref)}@{digest}"
    if kind == "image-id":
        return digest
    return ref if "@" in ref else f"{_repo_of(ref)}@{digest}"


class UnidentifiedImage(RuntimeError):
    """A verdict-bearing report was assembled without naming its image."""


def unidentified_reason(judged: "JudgedImage") -> str:
    """Why `judged` cannot carry a verdict — the empty string when it can.

    TWO facts are required and neither substitutes for the other:

      * the DIGEST, because a verdict about bytes nobody can name again can be
        neither replayed nor attributed;
      * the VERSION LABEL, because that is how this repo learns which vibeic-eda
        release it looked at now that it no longer stores the number itself. An
        image that will not say is NOT_MEASURED — the same rule as every other
        input in this repo: "I could not read it" and "I read it and it was bad"
        must never produce the same verdict.
    """
    if not judged.ref:
        return judged.why_not or "no image to judge"
    if not (judged.digest and DIGEST_RE.match(judged.digest)):
        return (f"{judged.ref} resolved to no usable digest "
                f"({judged.digest!r}); an unidentifiable verdict cannot be "
                f"reproduced or attributed")
    if not judged.version:
        return (f"{judged.ref} would not say which version it is: "
                f"{judged.version_why_not or 'no ' + VERSION_LABEL + ' label'}")
    return ""


def verdict_report(program: str, judged: "JudgedImage", payload: dict) -> dict:
    """The report body a gate that judges an image is allowed to write.

    ONE implementation, deliberately, and it REFUSES rather than warns. A report
    saying "these two STA engines disagree" or "this via patch is too narrow"
    without saying which bytes were read cannot be replayed, and cannot be
    attributed: the reader has no way to tell a regressed image from a regressed
    change. That is the whole property the deleted `tools/vibeic-eda/VERSION`
    was standing in for, so it is enforced here rather than remembered by each
    caller.
    """
    why = unidentified_reason(judged)
    if why:
        raise UnidentifiedImage(f"{program}: {why}")
    return {"program": program, **judged.as_report_fields(), **payload}


def _note(message: str) -> None:
    print(f"_eda_image: {message}", file=sys.stderr)


def resolve(env=None, *, repo: str = IMAGE_REPO) -> str:
    """A runnable image reference for the vibeic-eda toolchain.

    Order: explicit override → the registry's current `latest`, by digest →
    the newest locally-present tag → the legacy upstream image. Every step past the registry is announced. Never returns a bare `:latest`, which is the one answer that
    can silently mean "whatever this machine happened to pull months ago".
    """
    env = os.environ if env is None else env
    for key in _ENV_KEYS:
        override = (env.get(key) or "").strip()
        if override:
            return override

    # THE RUN PATH READS THE SAME PIN THE GATE PATH DOES, from the same config
    # point. It used to ask the registry what `latest` meant and then walk down
    # through the newest local tag to upstream iic-osic-tools -- three rungs,
    # each naming a DIFFERENT toolchain, none of them the one anybody pinned.
    # Composing the reference cannot fail and cannot go stale; whether this host
    # HOLDS those bytes is `local_image()`'s question and is deliberately still
    # a separate one, because collapsing the two turns a skip guard's local
    # check into an unbounded fetch.
    ref = _pin.image_reference(env)
    if not local_image(env=env):
        _note(f"{_pin.IMAGE_NOT_PRESENT}: {ref} is not on this host; running it "
              f"will fetch exactly those pinned bytes. Nothing older is "
              f"substituted.")
    return ref


def main(argv=None) -> int:
    """`--judged` answers the gate question, no argument answers the run question.

    Two questions, two answers, one implementation — which is why `restart-eda.sh`
    shells out to this instead of growing a second copy in bash.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--judged" in argv:
        judged = judged_image(allow_pull="--allow-pull" in argv)
        if judged.ref is None:
            print(f"_eda_image: {judged.why_not}", file=sys.stderr)
            return 2
        print(judged.ref)
        return 0
    print(resolve())
    return 0


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main))
