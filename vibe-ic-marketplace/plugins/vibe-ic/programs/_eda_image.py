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

import os
import re
import subprocess
import sys
from typing import Optional

IMAGE_REPO = "ghcr.io/vibeic/vibeic-eda"
#: Last resort only. The upstream image this fork descends from; it lacks the
#: forked tools (Fault, the patched yosys/iverilog) that most callers need.
LEGACY_IMAGE = "hpretl/iic-osic-tools:latest"
_ENV_KEYS = ("VIBEIC_EDA_IMAGE", "IIC_EDA_IMAGE")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TIMEOUT_S = 20
#: A reference nobody else can move: a digest, or an X.Y.Z tag.
_IMMUTABLE_REF = re.compile(r"(@sha256:[0-9a-f]{64}$|:\d+\.\d+\.\d+$)")


def _run(*argv: str, timeout: int = _TIMEOUT_S):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


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
    tags = local_tags(repo)
    if tags:
        return f"{repo}:{tags[0]}"
    try:
        r = _run("docker", "image", "inspect", LEGACY_IMAGE)
    except (OSError, subprocess.SubprocessError):
        return None
    return LEGACY_IMAGE if r.returncode == 0 else None


def anchor_image(env=None) -> Optional[str]:
    """The image THIS CHECKOUT names — for gates whose verdict must not be
    changeable by somebody else's push.

    THE THIRD QUESTION, and the one I got wrong first (vibe-ic#927 got it right
    long before). `resolve()` asks the registry, so what it returns changes when
    anyone publishes. That is exactly right for RUNNING a tool and exactly wrong
    for a gate that reports FAIL about the image's contents: a third party's push
    would then change a blocking verdict with no commit in this tree.

    So a verdict-bearing caller asks this. The answer comes from
    `tools/vibeic-eda/VERSION`, which moves only by a commit here, and when that
    file is absent the answer is None — the caller reports nothing-to-look-at.
    It does NOT fall back to a floating tag, because that is the failure mode.

    An explicit override is honoured, with a warning when it is mutable: the
    caller asked for it, but they should know their gate can now move under them.

    NOTE: `pdk_registry_selectable_check` carries the original of this logic and
    still has its own copy; folding it into this one is a follow-up. Two copies
    of a rule is the drift this module exists to end.
    """
    env = os.environ if env is None else env
    for key in _ENV_KEYS:
        override = (env.get(key) or "").strip()
        if override:
            if not _IMMUTABLE_REF.search(override):
                _note(f"{override} is a floating reference: what a gate using "
                      f"it reports can change without any commit in this tree.")
            return override
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(here, "tools", "vibeic-eda", "VERSION")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as fh:
                version = fh.read().strip()
            return f"{IMAGE_REPO}:{version}" if version else None
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def _note(message: str) -> None:
    print(f"_eda_image: {message}", file=sys.stderr)


def resolve(env=None, *, repo: str = IMAGE_REPO) -> str:
    """A runnable image reference for the vibeic-eda toolchain.

    Order: explicit override → the registry's current `latest`, by digest →
    the newest locally-present tag → the anchor this checkout names → the
    legacy upstream image. Every step past the registry is announced. Never returns a bare `:latest`, which is the one answer that
    can silently mean "whatever this machine happened to pull months ago".
    """
    env = os.environ if env is None else env
    for key in _ENV_KEYS:
        override = (env.get(key) or "").strip()
        if override:
            return override

    digest = registry_digest(repo)
    if digest:
        return f"{repo}@{digest}"

    tags = local_tags(repo)
    if tags:
        _note(f"registry unreachable; using the newest LOCAL {repo} tag "
              f"({tags[0]}). It may be older than what is published.")
        return f"{repo}:{tags[0]}"

    # THE ANCHOR BEFORE THE LEGACY IMAGE. Dropping straight to upstream here
    # was a regression I shipped and a test caught: with docker unavailable the
    # old resolver still named the vibeic-eda tag this checkout knows, while
    # mine named an image that does NOT carry the forked tools — so a DFT step
    # would run against a toolchain missing Fault and the patched yosys. Being
    # unable to ASK which image is current is not a reason to forget which one
    # this tree names.
    anchored = anchor_image(env)
    if anchored:
        _note(f"registry unreachable and no local {repo} image; using the "
              f"anchor this checkout names ({anchored}).")
        return anchored

    _note(f"registry unreachable, no local {repo} image and no anchor; falling "
          f"back to {LEGACY_IMAGE}, which does NOT carry the forked tools.")
    return LEGACY_IMAGE


def main(argv=None) -> int:
    print(resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
