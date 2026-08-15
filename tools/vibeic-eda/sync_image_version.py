#!/usr/bin/env python3
"""vibeic-eda image-version sync — one source of truth + a fool-proof drift gate.

WHY THIS EXISTS
    The image tag `vibeic-eda:X.Y.Z` is copy-pasted into many install docs across
    this repo (and the sibling `vibeic/vibeic-eda` repo). The forked tools are
    upgraded OFTEN — any one tool bump → a new image version — so every reference
    must move together or users pull a stale / nonexistent tag. This makes the
    propagation mechanical and the drift a hard error:

        SOURCE OF TRUTH            the `VERSION` file (X.Y.Z, one line)
        --check      (default)     BLOCKING. FAIL if any LIVE pointer disagrees
                                   with VERSION, or if the anchor moved BELOW what
                                   this repo already committed. Reads the repo and
                                   git ONLY — never the registry.
        --report-upstream          NON-BLOCKING. Resolve the registry and RECORD
                                   what it said and when. Never returns 1.
        --set X.Y.Z                write VERSION + rewrite every live pointer
        --bump patch|minor|major   compute the next version, then --set it
        --print                    print the current VERSION

    TWO QUESTIONS, TWO SIDES OF ONE LINE (vibe-ic#927)
        (a) IS THE PINNED ANCHOR THE ONE THIS REPO INTENDS?
            Decidable from the repo alone — the pointers, and git's record of
            what the anchor already was. Deterministic, has a fixed point, and
            no third party can move it. SAFE TO BLOCK ON, and `--check` is
            exactly this and nothing else.

        (b) HAS UPSTREAM PUBLISHED SOMETHING NEWER?
            Decidable only by asking a registry another org mutates on its own
            cadence. REPORTED, never blocking — `--report-upstream`.

        The line between them is not a style preference. A verdict that depends
        on a MUTABLE THIRD-PARTY POINTER has three defects at once:
          * it goes red for a reason nobody in this repo caused;
          * it goes green again when the third party ships nothing;
          * it cannot distinguish "we are behind" from "the registry moved under
            us" — different facts, with different owners.
        Measured: the anchor moved 0.2.75 -> .81 -> .82 -> .83 inside about
        twelve hours, once per fork release, each time re-opening a gap no
        commit in this tree caused. Bumping the number closes the instance and
        leaves the mechanism; this split removes the mechanism.

        WHAT COUNTS AS MUTABLE IS A PREDICATE, NOT A LIST (`is_mutable_tag`).
        `latest` is not special — it is merely the non-semver tag we happen to
        publish today. Any tag that is not an immutable X.Y.Z release is a NAME
        the publisher can re-point at different bytes tomorrow, so the rule is
        written against the shape, and `edge` / `nightly` / `main` are covered
        the day someone publishes one without editing this file.

        WHERE THE ADOPTION CALL LIVES. Whether to take a newer image is THIS
        repo's call, made deliberately by running `--set`. That is the moment
        the target is verified to resolve (vibe-ic#354's protection, kept), and
        the moment a human is present to make the call. It is not a thing a
        landing gate should decide on the repo's behalf at an arbitrary minute.

    ANCHOR-vs-REALITY (issue #215) — now REPORTED, not blocking
        Internal consistency (every pointer == VERSION) is NECESSARY but NOT
        SUFFICIENT: if the VERSION file is ITSELF stale, the whole tree is
        *consistently wrong*. That comparison is still MADE and still printed in
        full by `--report-upstream`; what changed is that it no longer sets a
        landing verdict. Registry query is best-effort: pin/override it with the
        `VIBEIC_EDA_PUBLISHED_TAG` env (tests / offline / CI); if the registry
        can't be reached AND no override is set, the report says UNVERIFIED /
        NOT CHECKED rather than silently claiming clean.

        The #215 state it was written for is still BLOCKED, from the side that
        has a fixed point: `check_anchor_no_regress` compares the anchor against
        this repo's own committed history, which the other repo cannot move.

    RESOLVABLE IS NOT PULLABLE (issue #1297) — the third question
        Everything above asks about NAMES: does the pointer equal the anchor,
        does the anchor resolve, does the floating tag mean the same bytes.
        `0.2.92` through `0.2.99` pass every one of them and NONE of them can be
        pulled onto a host that does not already have the image: 126 layers
        against the daemon's layer-store ceiling of 125, so `docker pull`
        downloads 22 GB and exits 1 with `failed to register layer: max depth
        exceeded`. Published, resolvable, current, internally consistent — and
        unusable, with nothing in the tree saying so.

        `check_layer_depth` reads the count off the registry MANIFEST (no pull)
        and is wired in twice, deliberately asymmetrically:
          * `--report-upstream` REPORTS it, dated, in the printed reading and in
            the JSON record. Never a landing verdict: the repair is a squash in
            the `vibeic/vibeic-eda` build, so a red gate here would be one no
            commit in this repo could turn green.
          * `--set` BLOCKS on it, because that is this repo ADOPTING the tag —
            the same moment, and the same reason, as #354's does-it-resolve
            check. `--allow-over-depth` adopts anyway, loudly and on the record.
        `--check` is untouched and still makes no registry call at all.

TWO KINDS of `vibeic-eda:X.Y.Z`, treated DIFFERENTLY (verified empirically):
    * LIVE POINTER — "pull / run / build THIS image now". Lives in the install
      docs, and every fully-qualified pull uses `ghcr.io/vibeic/vibeic-eda:X.Y.Z`.
      These TRACK the VERSION file.
    * HISTORY — "fix shipped in vibeic-eda:0.2.5". Lives in code comments, tests,
      SKILL docs, and FIX_STATUS / CHANGELOG, always in the short prose form.
      These are IMMUTABLE and never touched.

FOOL-PROOF two ways:
    (1) strict check of the known install docs (they contain only live pointers);
    (2) a repo-wide NET that flags any fully-qualified `ghcr.io/...:X.Y.Z` — the
        form only a live pull uses — at a version != VERSION ANYWHERE (minus the
        history files), so a new or unregistered doc cannot silently drift. The
        short prose form used by history is never matched by the net.

    A drift the net finds but --set can't fix (a ghcr pull in a file that isn't a
    registered install doc) FAILS on purpose: register the file in
    INSTALL_DOC_CANDIDATES, or mark it history in `.image-version-ignore`.

Runs from either repo with no arguments — it locates the git root and the VERSION
file itself. Exit: 0 = in sync, 1 = drift, 2 = misconfig (no/invalid VERSION).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

# The published image whose newest semver tag is the ground truth for the anchor.
GHCR_REPO = "vibeic/vibeic-eda"

# The deepest layer stack the Docker daemon's LAYER STORE will register — and
# therefore the most layers an image may carry and still be `docker pull`-able
# onto a host that does not already have it.
#
# MEASURED, NOT INFERRED (vibe-ic#1297). That issue reasoned "storage driver is
# overlay2, so the ceiling is 128" from the driver's refusal message, and the
# inference is wrong by three IN THE UNSAFE DIRECTION. Measured directly with a
# synthetic image — `FROM scratch` plus N one-byte `COPY` layers, classic
# builder, Docker 29.1.3 / overlay2:
#
#     Step 126/129 : COPY f.txt /l125
#      ---> 8750d92102e6          <- the 125th layer REGISTERS
#     Step 127/129 : COPY f.txt /l126
#     max depth exceeded          <- the 126th is REFUSED
#
# So the limit is moby's layer-store `maxLayerDepth` (125), not overlay2's mount
# limit (128). An image ONE layer over resolves in the registry, downloads in
# full, and then fails at the very last step with
#
#     failed to register layer: max depth exceeded
#
# which is exactly why nothing that reads tags, digests or manifests could see
# it coming: the image is published, resolvable, and internally consistent with
# every pointer in this tree, and it still cannot be materialised.
#
# NOT AN ENV OVERRIDE, deliberately. Every other registry fact in this file has
# a test pin because it is a value ANOTHER ORG MOVES on its own cadence. This
# one is a property of the daemon, not of the fork, and a knob that let a caller
# raise it would let the next bump wish the ceiling away instead of squashing
# the image — which is the actual repair, and lives in the `vibeic/vibeic-eda`
# build, not here.
MAX_REGISTRABLE_LAYERS = 125
# Test / offline / CI pin: when set to X.Y.Z it is used verbatim as "the newest
# published tag" instead of querying the registry. Lets the RED/GREEN fixtures for
# the stale-anchor case run with no network and keeps CI deterministic.
PUBLISHED_TAG_ENV = "VIBEIC_EDA_PUBLISHED_TAG"

# Install docs (relative to repo root). EVERY vibeic-eda tag in these is a live
# pointer. Only the ones that exist in the current repo are used, so the SAME
# script serves both the plugin repo and the standalone vibeic-eda repo.
INSTALL_DOC_CANDIDATES = [
    "README.md",
    "docs/INSTALL.md",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/README.md",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/INSTALL_GUIDE.md",
    "tools/vibeic-eda/README.md",
    # Not a doc, but a code file whose image-fallback tags are pinned live
    # pointers (never :latest) — registered so --set/--bump rewrites them and
    # --check catches drift the same way as the install docs.
    "vibe-ic-marketplace/plugins/vibe-ic/programs/fault_atpg_run.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/fmeda_fault_injection_coverage.py",
    # A test's `docker image inspect ghcr.io/vibeic/vibeic-eda:<v>` availability
    # probe is a live pointer too — it must track VERSION or the skip guard checks
    # for a stale image that is never present (v1.4.40: registered so it syncs).
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_v1_4_21_dft_atpg_liberty_resolver.py",
    # Two more live pointers, found by grepping the anchor version across the
    # tree while advancing 0.2.46 -> 0.2.47 and comparing the hits against what
    # --set would rewrite. Both are `ghcr.io/vibeic/vibeic-eda:<v>` defaults
    # that decide which image actually runs:
    #   sta_engine_parity_check.py            DEFAULT_IMAGE
    #   test_extraction_input_capability_check.py  _IMAGE
    # An unregistered live pointer is invisible in exactly the direction that
    # matters: --check passes while the code keeps pulling the old image.
    "vibe-ic-marketplace/plugins/vibe-ic/programs/sta_engine_parity_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_extraction_input_capability_check.py",
    # Same shape again: `DEFAULT_IMAGE` is the image whose PDK trees the via-
    # patch min-width gate actually reads with `--from-image`. Registered when
    # it was written, rather than after a bump left it reading a stale PDK —
    # which is exactly what the two entries above were added for.
    "vibe-ic-marketplace/plugins/vibe-ic/programs/pdk_via_patch_meets_layer_min_width_check.py",
]

# Files that legitimately carry OLD versions — never checked, never rewritten.
# Changelog / status / roadmap docs record what shipped in each past version, so a
# stale tag in them is HISTORY, not drift. Add repo-specific one-offs (a doc that
# quotes an old pull command on purpose) to `.image-version-ignore` instead.
HISTORY_GLOBS = ["FIX_STATUS.md", "CHANGELOG*", "*CHANGELOG*", "*ROADMAP*.md",
                 "*_STATUS.md", "sync_image_version.py"]

# The floating tag this repo publishes today. Named ONCE, here, and only so the
# report has something to resolve — every RULE below is written against
# `is_mutable_tag`, never against this constant, so a second floating tag needs
# no rule change.
FLOATING_TAG = "latest"

TAG_RE = re.compile(r"vibeic-eda:(\d+\.\d+\.\d+)")
# The SAME image reference, read WITHOUT the semver assumption. `TAG_RE` is the
# gate's numerator and it can only see pins; a file whose every tag is floating
# is invisible to it, which is exactly how a registered install doc contributed
# nothing to `--check`'s denominator and nobody could see it (vibe-ic#970). This
# one reads whatever tag is written, and `is_mutable_tag` — the predicate that
# already exists, not a second list of names — decides what it is.
ANY_TAG_RE = re.compile(r"vibeic-eda:([A-Za-z0-9_][A-Za-z0-9._-]*)")
GHCR_RE = re.compile(r"ghcr\.io/vibeic/vibeic-eda:(\d+\.\d+\.\d+)")
CURRENT_RE = re.compile(r"(Current:\s*\*\*)(\d+\.\d+\.\d+)(\*\*)")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _sh(args, cwd):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


def repo_root(start: Path) -> Path:
    r = _sh(["git", "rev-parse", "--show-toplevel"], start)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip())
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return start


def find_version_file(root: Path, script_dir: Path):
    for c in (script_dir / "VERSION", root / "tools" / "vibeic-eda" / "VERSION", root / "VERSION"):
        if c.is_file():
            return c
    return None


def read_version(vf: Path) -> str:
    v = vf.read_text(encoding="utf-8").strip()
    if not SEMVER_RE.match(v):
        print(f"[FAIL] VERSION '{v}' is not X.Y.Z ({vf})", file=sys.stderr)
        raise SystemExit(2)
    return v


def next_version(cur: str, kind: str) -> str:
    x, y, z = (int(n) for n in cur.split("."))
    if kind == "major":
        return f"{x + 1}.0.0"
    if kind == "minor":
        return f"{x}.{y + 1}.0"
    # patch, with the 0..99 rollover scheme (x.y.99 -> x.(y+1).0)
    return f"{x}.{y + 1}.0" if z >= 99 else f"{x}.{y}.{z + 1}"


def _semver_key(v: str):
    return tuple(int(n) for n in v.split("."))


def is_mutable_tag(tag: str) -> bool:
    """Is `tag` a name whose bytes a third party can change under us?

    THE PREDICATE THE WHOLE (a)/(b) SPLIT TURNS ON, and deliberately written
    against the SHAPE of the tag rather than against a list of names.

    An immutable X.Y.Z release tag is a promise: `:0.2.83` means the same
    manifest tomorrow as today, so a check that reads it has a fixed point and
    can be blocked on. Everything else — `latest`, `edge`, `nightly`, `main`, a
    branch name — is a POINTER the publisher re-aims on their own cadence, so a
    verdict computed from it changes for reasons that are not in this commit.

    Written as a predicate so the rule survives the next floating tag somebody
    publishes: enumerating today's names would leave the rule silently
    incomplete the first time that happened, which is the same shape of defect
    as a per-file ignore list that is always one landing behind.
    """
    return not bool(SEMVER_RE.match(tag.strip()))


def _query_ghcr_tags(repo: str, timeout: float = 6.0):
    """List tags for a public ghcr image via the anonymous Docker-registry v2 API.
    Raises on any transport / parse failure — the caller degrades gracefully."""
    tok_url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    with urllib.request.urlopen(tok_url, timeout=timeout) as r:  # noqa: S310 (fixed host)
        token = json.load(r).get("token", "")
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{repo}/tags/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed host)
        return json.load(r).get("tags", []) or []


def _query_ghcr_digest(repo: str, tag: str, timeout: float = 6.0):
    """The manifest DIGEST a tag resolves to, via the same anonymous v2 API.
    Raises on any transport / parse failure — the caller degrades gracefully.

    vibe-ic#423. The tag list alone cannot answer "does `latest` mean the
    latest": tags/list returns names, not what they point AT. `latest` sat on
    the 0.2.28 manifest for four days while 0.2.30 was current, and every
    check here passed — they compared our POINTERS against the anchor, and
    the anchor was right. What nobody compared was the tag an outside reader
    actually pulls.
    """
    tok_url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    with urllib.request.urlopen(tok_url, timeout=timeout) as r:  # noqa: S310
        token = json.load(r).get("token", "")
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{repo}/manifests/{tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join((
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            )),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        d = r.headers.get("Docker-Content-Digest")
        if d:
            return d
        import hashlib
        return "sha256:" + hashlib.sha256(r.read()).hexdigest()


def _query_ghcr_layer_count(repo: str, tag: str, timeout: float = 6.0) -> int:
    """How many layers the linux/amd64 image behind `tag` carries.

    READS MANIFESTS ONLY — NO PULL. One or two small HTTP GETs answer a question
    about a 22 GB image, which is the only reason a check like this can run at
    the adoption moment at all.

    Handles BOTH manifest shapes this repository's own registry actually serves,
    because it serves both and both were read while writing this:

      OCI INDEX        0.2.89 / 0.2.92 — a platform list whose entries include an
                       `unknown/unknown` ATTESTATION manifest. That entry carries
                       a handful of layers, so an implementation that took the
                       first (or any) entry would read ~1 and report vast
                       headroom on an image that is over the ceiling — a
                       VACUOUS PASS in the exact direction this check exists to
                       prevent. The platform is therefore matched explicitly and
                       a missing linux/amd64 entry RAISES rather than defaulting.
      IMAGE MANIFEST   0.2.98 / 0.2.99 — `layers` at the top level, no index.

    Raises on any transport / parse failure — same contract as
    `_query_ghcr_digest`, and the caller degrades to NOT CHECKED.
    """
    accept = ", ".join((
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ))
    tok_url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    with urllib.request.urlopen(tok_url, timeout=timeout) as r:  # noqa: S310
        token = json.load(r).get("token", "")

    def _fetch(ref: str):
        req = urllib.request.Request(
            f"https://ghcr.io/v2/{repo}/manifests/{ref}",
            headers={"Authorization": f"Bearer {token}", "Accept": accept},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.load(r)

    man = _fetch(tag)
    if "manifests" in man:
        for entry in man.get("manifests", []):
            plat = entry.get("platform") or {}
            if plat.get("os") == "linux" and plat.get("architecture") == "amd64":
                man = _fetch(entry["digest"])
                break
        else:
            raise ValueError(
                f"{repo}:{tag} is an index with no linux/amd64 entry — refusing "
                f"to count layers off an attestation manifest")
    layers = man.get("layers")
    if not isinstance(layers, list):
        raise ValueError(f"{repo}:{tag} manifest carries no `layers` list")
    return len(layers)


def check_layer_depth(tag: str, require_remote: bool = False,
                      label: str = "anchor"):
    """Is `tag` shallow enough for a clean host to actually REGISTER it?

    vibe-ic#1297. Every instrument in this file answers a question about NAMES —
    does the pointer equal the anchor, does the anchor resolve, does the
    floating tag mean the same bytes. All of them passed on `0.2.92` through
    `0.2.99`, and none of them could see that those images cannot be unpacked:
    126 layers against a ceiling of 125, so `docker pull` downloads 22 GB and
    then exits 1 with `failed to register layer: max depth exceeded`. A tag can
    be published, resolvable, current, and unusable, and until this function
    existed nothing in the tree said so.

    Returns `(severity, count)`. Severity is a FINDING SEVERITY in the same
    vocabulary `check_latest_points_at_anchor` already uses — the CALLER decides
    whether it blocks:

        0  under the ceiling, or the registry could not be reached and
           `require_remote` is off (count may be None)
        1  OVER the ceiling — this tag cannot be pulled onto a clean host
        2  could not look, and the caller asked to be told (count is None)

    "Could not look" is never a pass. It prints NOT CHECKED and says the count
    was not read, because an unreachable registry has told us nothing about
    layer depth — the same rule this file applies to every other reading.
    """
    try:
        n = _query_ghcr_layer_count(GHCR_REPO, tag)
    except Exception as e:  # noqa: BLE001
        if require_remote:
            print(f"[NOT CHECKED] {label} layer depth: registry unverifiable "
                  f"({e.__class__.__name__}). This is NOT a pass — the layer "
                  f"count of {tag} was never read, so whether a clean host can "
                  f"register it is UNKNOWN.")
            return 2, None
        print(f"  {label+' layer depth':<25}: UNVERIFIED "
              f"({e.__class__.__name__}) — count not read")
        return 0, None
    if n > MAX_REGISTRABLE_LAYERS:
        print(f"[REPORT] LAYER DEPTH OVER CEILING: {GHCR_REPO}:{tag} carries "
              f"{n} layers; the daemon registers at most "
              f"{MAX_REGISTRABLE_LAYERS} (measured, vibe-ic#1297).")
        print(f"       A host that does not already carry this image downloads "
              f"it in full and then fails with `failed to register layer: max "
              f"depth exceeded`. `docker pull` is not a step that can be "
              f"retried into success, and no tag/digest/pointer check can see "
              f"this — they all pass.")
        print(f"       Fix: SQUASH the image (multi-stage build, or export/"
              f"import flatten) in the `vibeic/vibeic-eda` build, then publish "
              f"a tag under {MAX_REGISTRABLE_LAYERS} layers. Raising the number "
              f"here is not a fix; the ceiling belongs to the daemon.")
        return 1, n
    print(f"  {label+' layer depth':<25}: OK ({n} layers, ceiling "
          f"{MAX_REGISTRABLE_LAYERS}, headroom "
          f"{MAX_REGISTRABLE_LAYERS - n})")
    return 0, n


def check_latest_points_at_anchor(version: str,
                                  require_remote: bool = False) -> int:
    """Does the floating tag resolve to the SAME manifest as the anchor?

    #423: it did not, for four days, and nothing said so. A reader who pulls
    the tag that means "newest" got an older toolchain than the campaign runs
    on, and their results were not comparable to the published ones. That
    OBSERVATION is worth making and this function still makes it, in full.

    WHAT ITS RETURN VALUE MEANS CHANGED (vibe-ic#927). It is a FINDING
    SEVERITY, not a verdict: 0 = agrees / nothing to compare, 1 = disagrees,
    2 = could not look. `do_report_upstream` is the only caller, and it never
    turns 1 into a non-zero exit, because the thing being compared is a
    MUTABLE THIRD-PARTY POINTER (`is_mutable_tag`) — an answer that flips when
    the fork publishes, with no commit here. `do_check` does not call this at
    all. Skipped when the override env is set: that mode exists for offline /
    deterministic CI and there is no registry to ask.
    """
    if os.environ.get(PUBLISHED_TAG_ENV):
        print("  latest-vs-anchor         : SKIPPED "
              f"({PUBLISHED_TAG_ENV} override set — no registry to query)")
        return 0
    try:
        d_latest = _query_ghcr_digest(GHCR_REPO, FLOATING_TAG)
        d_anchor = _query_ghcr_digest(GHCR_REPO, version)
    except Exception as e:  # noqa: BLE001
        if require_remote:
            # UNVERIFIABLE, NOT WRONG — and the distinction is the whole point
            # of rc 2 in this repo (`run_tolerating_uncheckable`,
            # `DIRTY_CHECKOUT`, `NOTHING_SCANNED`). #354 added
            # --require-remote so an unreachable registry could not be a silent
            # PASS, and that still holds: rc 2 is not a pass, it prints NOT
            # CHECKED and the hygiene script says so on stderr. What it stops
            # doing is reporting a transient network timeout in the SAME words
            # as a genuinely wrong pin — measured 2026-07-27, one run failed on
            # TimeoutError and the next two passed, on an unchanged tree.
            print(f"[NOT CHECKED] latest-vs-anchor: registry unverifiable "
                  f"({e.__class__.__name__}). This is NOT a pass — the tag an "
                  f"outside reader pulls was not compared against the anchor.")
            return 2
        print(f"  latest-vs-anchor         : UNVERIFIED "
              f"({e.__class__.__name__})")
        return 0
    if d_latest != d_anchor:
        print(f"[REPORT] DIVERGENCE: `:latest` does NOT point at the anchor version.")
        print(f"       latest  -> {d_latest}")
        print(f"       {version:<8}-> {d_anchor}")
        print(f"       Anyone pulling the tag that means 'newest' gets a "
              f"different toolchain from the one this repo pins, and their "
              f"results are not comparable (vibe-ic#423).")
        print(f"       Fix: docker buildx imagetools create "
              f"-t ghcr.io/{GHCR_REPO}:latest ghcr.io/{GHCR_REPO}:{version}")
        return 1
    print(f"  latest-vs-anchor         : OK (:latest == :{version})")
    return 0


def published_tags(repo: str = GHCR_REPO):
    """(tags, source) — the set of PUBLISHED semver image tags, or (None,
    reason) if it can't be determined.

    Order: explicit override (env — tests / offline / CI pin) beats a live
    query; the override names ONE tag and the set becomes {that tag}. Never
    raises: any registry failure returns (None, reason) so --check can fall
    back to internal-consistency-only rather than crash or false-fail."""
    ov = os.environ.get(PUBLISHED_TAG_ENV)
    if ov is not None:
        ov = ov.strip()
        if not ov:
            return None, f"{PUBLISHED_TAG_ENV} set but empty"
        if not SEMVER_RE.match(ov):
            return None, f"{PUBLISHED_TAG_ENV}='{ov}' is not X.Y.Z"
        return {ov}, f"override:{PUBLISHED_TAG_ENV}"
    try:
        tags = _query_ghcr_tags(repo)
    except Exception as e:  # network down, 404, auth, JSON — all degrade the same
        return None, f"registry unreachable ({e.__class__.__name__})"
    sem = {t for t in tags if SEMVER_RE.match(t)}
    if not sem:
        return None, "registry returned no X.Y.Z tags"
    return sem, "ghcr"


def newest_published_tag(repo: str = GHCR_REPO):
    """(tag, source) for the newest PUBLISHED semver image tag; see
    published_tags for the override / degrade contract."""
    tags, src = published_tags(repo)
    if tags is None:
        return None, src
    return max(tags, key=_semver_key), src


def check_anchor_no_regress(root: Path, vf: Path, version: str) -> int:
    """The anchor must never move BACKWARDS from what this repo already shipped.

    vibe-ic#566 relaxed "behind the newest published tag" from FAIL to WARNING,
    because that comparison is against a value another repository mutates while
    this repo's landing gate runs. This check is what keeps that relaxation
    honest, and it compares against something the OTHER REPO CANNOT MOVE: the
    anchor recorded in this repo's own committed history.

    Being one release behind is a currency question (WARNING). Rolling the
    anchor from 0.2.51 back to 0.2.40 is a REGRESSION, and it reintroduces
    exactly the state vibe-ic#215 was opened for — every pointer internally
    consistent and consistently pointing at the wrong image. Without this, the
    #566 relaxation would have opened that door from the other side.

    Compares against `git show HEAD:<VERSION path>`, not against the registry:
    the committed value is a fact about this repository, so the check has a
    fixed point and cannot flap. rc 2 (NOT CHECKED) when git cannot answer — an
    unavailable baseline is not a pass.
    """
    if vf is None:
        print("[NOT CHECKED] no-regress: no VERSION file located")
        return 2
    try:
        rel = str(vf.relative_to(root))
    except ValueError:
        print(f"[NOT CHECKED] no-regress: {vf} is outside {root}")
        return 2
    try:
        prev = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{rel}"],
            capture_output=True, text=True, timeout=30)
    except Exception as e:                                   # noqa: BLE001
        print(f"[NOT CHECKED] no-regress: git unavailable ({e.__class__.__name__})")
        return 2
    if prev.returncode != 0:
        # New file, or not a git tree. Nothing to regress FROM.
        print("  anchor-no-regress        : OK (no committed baseline yet)")
        return 0
    base = prev.stdout.strip()
    if not SEMVER_RE.match(base):
        print(f"[NOT CHECKED] no-regress: committed baseline {base!r} is not X.Y.Z")
        return 2
    if _semver_key(version) < _semver_key(base):
        print(f"[FAIL] ANCHOR REGRESSED: VERSION={version} is BELOW the committed "
              f"{base}.")
        print(f"       Moving the anchor backwards makes every pointer "
              f"consistently wrong (vibe-ic#215) — the state the anchor-vs-"
              f"reality check exists to prevent, reached from the other side.")
        print(f"       Fix: --set {base} or newer, or explain the rollback.")
        return 1
    print(f"  anchor-no-regress        : OK ({version} >= committed {base})")
    return 0


def check_anchor_vs_reality(version: str, require_remote: bool = False) -> int:
    """Verify the VERSION anchor names a tag that EXISTS on the registry and
    is not STALE relative to the newest published one. Prints one status
    line; returns 0 = ok (or unverified without --require-remote), 1 = fail.

    vibe-ic#354: the old check treated VERSION *ahead* of the newest
    published tag as 'OK (unreleased)'. That is exactly how 0.2.29 — a tag
    that never existed on ghcr — stayed pinned in 13 places for six
    versions while every clean-room install failed. A pin the registry
    cannot resolve is a FAIL, not a future."""
    tags, src = published_tags()
    if tags is None:
        if require_remote:
            # Same split as latest-vs-anchor above: a registry we cannot reach
            # has told us nothing. rc 2 = NOT CHECKED, never a pass.
            print(f"[NOT CHECKED] anchor-vs-reality: registry unverifiable "
                  f"({src}). This is NOT a pass — no published tag was read. "
                  f"Set {PUBLISHED_TAG_ENV}=X.Y.Z to pin, or fix "
                  f"network/registry access.")
            return 2
        print(f"  anchor-vs-reality        : UNVERIFIED ({src}) — internal "
              f"consistency only; set {PUBLISHED_TAG_ENV}=X.Y.Z or enable network")
        return 0
    pub = max(tags, key=_semver_key)
    if _semver_key(version) < _semver_key(pub) and version not in tags:
        print(f"[REPORT] DIVERGENCE: STALE ANCHOR: VERSION={version} is OLDER than the newest "
              f"published image tag {pub} (source={src}).")
        print(f"       Internal consistency is not correctness — every pointer "
              f"equal to VERSION is *consistently wrong*.")
        print(f"       Fix: python3 {Path(__file__).name} --set {pub}")
        return 1
    if _semver_key(version) < _semver_key(pub):
        # BEHIND, but the anchor still RESOLVES — vibe-ic#566.
        #
        # This was a FAIL, and it made this repo's ~35-minute landing gate
        # depend on a value ANOTHER repository mutates on a cadence this one
        # does not control and cannot see coming. Measured on the 2026-07-31
        # landing: vibeic-eda published 0.2.47 -> .48 -> .49 -> .50 -> .51 at
        # 60-140 minute intervals, so four consecutive gate runs were
        # invalidated mid-flight and the tip commit was amended four times, for
        # a batch of eight commits that touch no image pin at all. Fixing the
        # anchor rewrites the tip, which voids the gate stamp, which restarts
        # the 35 minutes — against a target that moves every ~2 hours. That
        # race has no fixed point, and while it ran, NOBODY could land here.
        #
        # KEPT, because #215 and #354 are both still true:
        #   * an anchor the registry cannot resolve is a FAIL — the branch
        #     above (older AND absent) and UNRESOLVABLE PIN below. 0.2.29 stayed
        #     pinned in 13 places for six versions while every clean-room
        #     install failed; that must never pass again.
        #   * an anchor rolled BACKWARDS below what this repo already shipped is
        #     a FAIL (`--check-no-regress`), so the "consistently wrong" state
        #     #215 found cannot be reintroduced from the other direction.
        #
        # CHANGED: being behind a tag that was published WHILE THE GATE RAN is a
        # WARNING. Every pointer still names an image that exists and pulls,
        # which is the property a consumer actually needs. Whether we have
        # adopted the newest release is a currency question, and answering it
        # inside a landing gate meant answering it against a moving target.
        print(f"  anchor-vs-reality        : BEHIND (VERSION={version}, newest "
              f"published {pub}; source={src}) — resolvable, not stale-broken")
        print(f"       WARNING: a newer image exists. Not a landing blocker "
              f"(vibe-ic#566) — {version} resolves on the registry, so every "
              f"pointer directs a clean-room install at a real image.")
        print(f"       To adopt it: python3 {Path(__file__).name} --set {pub}")
        return 0
    if version not in tags:
        print(f"[REPORT] DIVERGENCE: UNRESOLVABLE PIN: VERSION={version} does not exist on the "
              f"registry (newest published: {pub}; source={src}).")
        print(f"       Every pointer equal to VERSION directs a clean-room "
              f"install at a tag `docker pull` cannot resolve (vibe-ic#354).")
        print(f"       Fix: publish ghcr.io/{GHCR_REPO}:{version}, or --set to "
              f"a published tag.")
        return 1
    print(f"  anchor-vs-reality        : OK (VERSION={version} == published {pub}; "
          f"source={src})")
    return 0


def _matches(rel: str, globs) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(base, g) or fnmatch.fnmatch(rel, g) for g in globs)


def is_history(rel: str) -> bool:
    return _matches(rel, HISTORY_GLOBS)


def load_extra_ignore(root: Path):
    ig = root / ".image-version-ignore"
    extra = []
    if ig.is_file():
        for ln in ig.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                extra.append(ln)
    return extra


def install_doc_refs(root: Path):
    """(rel, lineno, version, kind) for every tag / Current banner in the install docs."""
    out = []
    for rel in INSTALL_DOC_CANDIDATES:
        p = root / rel
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in TAG_RE.finditer(line):
                out.append((rel, i, m.group(1), "tag"))
            for m in CURRENT_RE.finditer(line):
                out.append((rel, i, m.group(2), "current"))
    return out


def install_doc_coverage(root: Path, refs=None):
    """RECONCILE the registered install docs against the ones that were COUNTED.

    vibe-ic#970. `INSTALL_DOC_CANDIDATES` is a DECLARED POPULATION — the comment
    on it says "EVERY vibeic-eda tag in these is a live pointer" — and
    `install_doc_refs` returns only the ones that matched `TAG_RE`, i.e. only
    the PINNED ones. Those two sets are not the same set, and the difference was
    invisible: `mcp-eda/README.md` is registered, exists, is the install path a
    user of the MCP server follows, and both of its pull commands are floating,
    so it contributed ZERO refs while `--check` printed "25 across 10 file(s)"
    and `[PASS]`. A stale PIN on those same two lines is caught loudly; a
    FLOATING pointer on them is not counted at all.

    Returns (counted, uncounted, absent):
        counted    rel paths that contributed at least one ref
        uncounted  rel paths that EXIST and contributed NONE, each with the
                   floating tags found in it (discovered by reading the file
                   and asking `is_mutable_tag`, never by naming `latest`)
        absent     rel paths not present in this checkout — legitimate, the one
                   script serves two repos, but still a shrunk denominator and
                   therefore still stated

    NOT A VERDICT. Whether those lines should be pinned to the anchor is a call
    somebody makes; the defect this repairs is that nobody could see there was
    a call to make. Same rule `gate_discloses_denominator_check` enforces on
    every other gate here: a PASS must say how much it looked at, and
    `declared` vs `probed` must both be printed when they differ.
    """
    refs = install_doc_refs(root) if refs is None else refs
    contributed = {r[0] for r in refs}
    counted, uncounted, absent = [], [], []
    for rel in INSTALL_DOC_CANDIDATES:
        p = root / rel
        if not p.is_file():
            absent.append(rel)
            continue
        if rel in contributed:
            counted.append(rel)
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        # HOW MANY pointers, and WHICH NAMES. The count is occurrences (two
        # `:latest` pull lines are two pointers a reader can follow), the names
        # are the distinct set (repeating `latest` twice tells nobody anything).
        hits = [t for t in ANY_TAG_RE.findall(text) if is_mutable_tag(t)]
        uncounted.append((rel, len(hits), sorted(set(hits))))
    return sorted(counted), uncounted, absent


def print_install_doc_coverage(counted, uncounted, absent) -> None:
    """Say what was NOT counted, every run, in the same breath as the count.

    The per-file line is printed for the UNCOUNTED class only. `absent` is a
    bare count with its reason: it is by construction (the script serves both
    the plugin repo and the standalone vibeic-eda repo, and ten of the eleven
    candidates are missing from the latter), so a name per file would be ten
    lines of noise in the fixture repos and zero lines here — while the count
    is what the reader needs to reconcile 10 + 1 + 0 = 11.
    """
    print(f"  registered but UNCOUNTED : {len(uncounted)} present-with-no-"
          f"pinned-ref, {len(absent)} not-present-in-this-repo")
    for rel, n_floating, names in uncounted:
        what = (f"{n_floating} floating pointer(s) "
                f"({', '.join(':' + t for t in names)}) and no X.Y.Z pin"
                if n_floating else "no vibeic-eda tag of any shape")
        print(f"     {rel} — {what}. Registered as an install doc where every "
              f"tag is a live pointer, so it contributes NOTHING to the count "
              f"above and --set cannot rewrite it; the anchor does not reach "
              f"this file (vibe-ic#970).")
    if absent:
        print(f"     ({len(absent)} registered candidate(s) absent from this "
              f"checkout — the same script serves both repos, so this is by "
              f"design, and it is still a shrunk denominator.)")


def ghcr_hits(root: Path, ignore):
    """(rel, lineno, version) for every ghcr.io/...:X.Y.Z in tracked files, minus history/ignore."""
    r = _sh(["git", "grep", "-nI", "-E", r"ghcr\.io/vibeic/vibeic-eda:[0-9]+\.[0-9]+\.[0-9]+"], root)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        rel, lineno, text = parts
        if is_history(rel) or _matches(rel, ignore):
            continue
        for m in GHCR_RE.finditer(text):
            out.append((rel, int(lineno), m.group(1)))
    return out


def do_check(root: Path, version: str, ignore,
             require_remote: bool = False, vf: Path | None = None) -> int:
    """THE BLOCKING HALF — question (a), and ONLY question (a).

    "Is the pinned anchor the one this repo intends?" Two sub-questions, both
    answered from things nobody outside this repository can move:

        every live pointer == the anchor        the tree, read directly
        the anchor >= what this repo committed   git, via check_anchor_no_regress

    NO REGISTRY CALL HAPPENS HERE, and that is the property, not an
    optimisation. `--require-remote` is accepted and ignored on this path (see
    main) so the old CI invocation keeps working while meaning the right thing.

    Consequences worth stating plainly, because they are the point:
      * an offline run and an online run return the SAME verdict;
      * a fork release published mid-gate cannot turn this red;
      * this gate is host-independent again — it was excluded from the
        two-invocations-must-agree probe precisely because it made a network
        round-trip (vibe-ic#539), and it no longer does.

    What was NOT bought by this: a genuinely wrong anchor still fails here. A
    drifted pointer fails. A rolled-back anchor fails. The currency question
    moved to `do_report_upstream`; it did not evaporate.
    """
    strict = install_doc_refs(root)
    net = ghcr_hits(root, ignore)
    install_set = set(INSTALL_DOC_CANDIDATES)

    drift_strict = [r for r in strict if r[2] != version]
    drift_net = [h for h in net if h[2] != version and h[0] not in install_set]

    ok_docs = sorted({r[0] for r in strict})
    # vibe-ic#970 — the denominator must say what it did NOT count. `ok_docs` is
    # the numerator's file set; `INSTALL_DOC_CANDIDATES` is the declared
    # population, and the two differ silently whenever a registered doc's tags
    # are all floating.
    counted, uncounted, absent = install_doc_coverage(root, strict)
    print(f"vibeic_eda_version_sync: VERSION = {version}")
    print(f"  install-doc refs checked : {len(strict)} across {len(ok_docs)} of "
          f"{len(INSTALL_DOC_CANDIDATES)} registered file(s)")
    print_install_doc_coverage(counted, uncounted, absent)
    print(f"  repo-wide ghcr pointers  : {len(net)}")
    # vibe-ic#566/#215 — the anchor must never move BELOW what this repo already
    # committed. Compares against git, which the other repo cannot move, so it
    # has a fixed point and cannot flap. This is the whole of the anchor's
    # blocking axis now.
    regress_rc = check_anchor_no_regress(root, vf, version)

    if drift_strict or drift_net:
        print(f"[FAIL] {len(drift_strict) + len(drift_net)} live pointer(s) != {version}:")
        for rel, ln, ver, kind in drift_strict:
            print(f"   {rel}:{ln}  {kind}={ver}  (want {version})")
        for rel, ln, ver in drift_net:
            print(f"   {rel}:{ln}  ghcr={ver}  (want {version}) — unregistered live pointer; "
                  f"add to INSTALL_DOC_CANDIDATES or .image-version-ignore")
        return 1
    if regress_rc == 1:
        return 1
    if regress_rc == 2:
        # "I could not read the baseline" is not "the baseline is fine".
        return 2
    # The PASS sentence carries the shrinkage too, not only the block above it.
    # A summary that reads COMPLETE while one member of the declared population
    # was never measurable is the #901 shape, and it is what made #970 invisible
    # for the whole life of the registration.
    unreached = (f" {len(uncounted)} registered install doc(s) carry no pinned "
                 f"pointer and were NOT counted — named above (vibe-ic#970)."
                 if uncounted else "")
    print(f"[PASS] all live pointers == {version} and the anchor has not "
          f"regressed.{unreached} Upstream currency is NOT judged here — run "
          f"--report-upstream (vibe-ic#927).")
    return 0


def do_report_upstream(version: str, require_remote: bool = False,
                       json_path: str | None = None) -> int:
    """THE REPORTED HALF — question (b). An OBSERVATION, never a verdict.

    "Has upstream published something newer, and does the floating tag still
    resolve to what we pinned?" Both are facts about a registry another org
    mutates, so the honest thing to produce is a dated reading, not a pass/fail.

    NEVER RETURNS 1. Two exit codes only:
        0  the registry answered and the reading below was taken
        2  the registry could not be reached — NOT CHECKED, and it says so

    AND THAT IS ENFORCED, not asserted (vibe-ic#969). It used to be a property
    of the code as written, and the code as written raised an uncaught
    FileNotFoundError — rc 1 — when `--json` named a directory that does not
    exist. The write is guarded below; the CLAMP that makes the sentence true
    for inputs nobody has tried yet lives at the `--report-upstream` dispatch
    in `main`, which turns any escape into rc 2 NOT CHECKED and can never turn
    one into 0.

    A reading that disagrees exits 0 ON PURPOSE. "The fork published 0.2.84
    while this gate ran" is true, useful, and NOT a defect in this commit; it
    is an input to an adoption decision that belongs to a human running
    `--set`. Exiting non-zero on it is how a landing gate ends up unobtainable
    at arbitrary minutes through nobody's fault.

    WHAT AND WHEN, both recorded. A reading with no timestamp cannot be told
    apart from a current one by a later reader, so every line carries the UTC
    instant it was taken and the digest/tag it actually resolved — not "there
    is a newer image", but "at 2026-08-11T04:00:00Z, `latest` resolved to
    sha256:... and the anchor 0.2.83 resolved to sha256:...".
    """
    from datetime import datetime, timezone
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"vibeic_eda_upstream_report: anchor = {version}")
    print(f"  observed_at (UTC)        : {observed_at}")
    print(f"  floating tag under watch : :{FLOATING_TAG} "
          f"(mutable={is_mutable_tag(FLOATING_TAG)})")

    anchor_rc = check_anchor_vs_reality(version, require_remote)
    latest_rc = check_latest_points_at_anchor(version, require_remote)
    # vibe-ic#1297 — REPORTED here, never blocking here. The anchor's depth is a
    # property of an image ANOTHER repo built, and the repair (squash) is in
    # that repo's Dockerfile, not in this tree. Turning it into a landing
    # verdict would hand every agent in this repo a red gate that no commit
    # here can make green — the same unsatisfiable shape the issue warns about.
    # What it CAN do is be visible and dated, which it was not before.
    depth_rc, depth_n = check_layer_depth(version, require_remote)

    newest, src = newest_published_tag()
    record = {
        "observed_at": observed_at,
        "anchor": version,
        "floating_tag": FLOATING_TAG,
        "newest_published_tag": newest,
        "newest_published_source": src,
        "anchor_vs_newest": ("unreachable" if anchor_rc == 2 else
                             "disagrees" if anchor_rc == 1 else "agrees"),
        "floating_vs_anchor": ("unreachable" if latest_rc == 2 else
                               "disagrees" if latest_rc == 1 else "agrees"),
        "anchor_layers": depth_n,
        "max_registrable_layers": MAX_REGISTRABLE_LAYERS,
        "anchor_registrable": ("unknown" if depth_n is None else
                               "no" if depth_rc == 1 else "yes"),
        "blocking": False,
        "why_not_blocking": (
            "both comparisons are against a registry another org mutates; a "
            "verdict computed from them changes with no commit in this tree "
            "(vibe-ic#927). The adoption call is this plugin's, made by "
            "running --set."),
    }
    if json_path:
        # vibe-ic#969 — THE EXIT CODE IS A PROPERTY OF THE OBSERVATION, NOT OF
        # THE FILESYSTEM. This write was unguarded, so `--json` pointed at a
        # directory that does not exist raised FileNotFoundError and python
        # exited 1 — the one code the docstring above promises this path can
        # never produce, and the one `run_tolerating_uncheckable` does NOT
        # tolerate (it tolerates rc 2 only; rc 1 is a FAIL). The reading was
        # already taken and printed in full by then; failing to persist a copy
        # of it cannot make the reading wrong, and must not be able to turn a
        # landing red.
        try:
            p = Path(json_path)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            print(f"  wrote                    : {json_path}")
        except OSError as e:
            print(f"  [warn] could not write {json_path}: "
                  f"{e.__class__.__name__}: {e}")
            print(f"         The reading above still stands and was printed in "
                  f"full; only the persisted copy is missing. This path never "
                  f"sets a verdict (vibe-ic#969).")

    if anchor_rc == 2 or latest_rc == 2 or depth_rc == 2:
        print("[NOT CHECKED] upstream currency: the registry did not answer. "
              "This is NOT a pass and NOT a failure — nothing was compared.")
        return 2
    if depth_rc == 1:
        # Said in its own sentence, not folded into "upstream has moved".
        # "A newer image exists" is an adoption question with a `--set` answer;
        # "the anchor cannot be materialised" is a DEFECT IN THE IMAGE, and
        # `--set` cannot fix it — nor can anything else in this repository.
        print(f"[REPORT] the anchor {version} carries {depth_n} layers and "
              f"CANNOT BE PULLED onto a host that does not already have it "
              f"(ceiling {MAX_REGISTRABLE_LAYERS}, observed {observed_at}). "
              f"Not a landing verdict — the repair is a squash in the "
              f"`vibeic/vibeic-eda` build (vibe-ic#1297) — but every remedy "
              f"line in this repo that says `docker pull` is UNSATISFIABLE "
              f"until it lands.")
    if anchor_rc == 1 or latest_rc == 1:
        print(f"[REPORT] upstream has moved relative to the anchor "
              f"{version} (observed {observed_at}). This is INFORMATION, not a "
              f"landing verdict: adopt it deliberately with "
              f"`--set {newest or 'X.Y.Z'}` when this repo chooses to.")
        return 0
    print(f"[REPORT] anchor {version} agrees with upstream as of "
          f"{observed_at}.")
    return 0


def check_adoption_target_resolves(new: str, allow_over_depth: bool = False) -> int:
    """THE ADOPTION MOMENT — where vibe-ic#354's protection now lives.

    #354: `0.2.29`, a tag that never existed on ghcr, stayed pinned in 13
    places for six versions while every clean-room install failed. That must
    never pass again, and it does not.

    It is checked HERE, at `--set`, rather than in the landing gate, because
    this is the instant the repo makes the adoption call — a deliberate,
    human-initiated action with a person present to read the answer. Asking
    "does the tag we are about to adopt exist" at that moment validates an
    ACTION THIS REPO IS TAKING. Asking it on every landing instead validates a
    STATE A THIRD PARTY MOVED INTO, which is the whole defect of #927.

    Blocking when the registry answers and the target is absent. NOT CHECKED —
    and permitted — when the registry cannot be reached: refusing to pin
    offline would make the anchor unmaintainable on a plane, and the pointer
    drift the gate really guards is unaffected either way.

    RESOLVING IS NOT THE SAME AS BEING PULLABLE (vibe-ic#1297). #354 asked "does
    the tag exist"; `0.2.92` through `0.2.99` all answer yes, and every one of
    them fails `docker pull` on a clean host with `failed to register layer: max
    depth exceeded` because they carry 126 layers against a ceiling of 125.
    That is the SAME defect #354 is about — a pin that directs every install at
    an image nobody can obtain — reached one step further down the pull. It is
    blocked at the same moment and for the same reason, and this is the only
    place in the file that spends a registry round-trip to do it: `--check`
    stays offline (vibe-ic#927).

    `allow_over_depth` exists because the anchor is ALREADY over the ceiling and
    the repair lives in another repo. Without it this function would freeze the
    anchor until somebody else squashes the image, which is a worse failure than
    the one it prevents. It does NOT silence the finding: the full refusal text
    is printed either way, and the override is announced on its own line so the
    decision is on the record rather than implied by a green run.
    """
    if is_mutable_tag(new):                      # belt-and-braces; do_set also checks
        print(f"[FAIL] refusing to anchor on '{new}': not an immutable X.Y.Z "
              f"release tag. A floating tag as the anchor would make every "
              f"pointer in this tree mean different bytes on different days.")
        return 1
    tags, src = published_tags()
    if tags is None:
        print(f"[NOT CHECKED] adoption target {new}: registry unverifiable "
              f"({src}). Proceeding — but nothing confirmed that {new} exists.")
        return 0
    if new not in tags:
        newest = max(tags, key=_semver_key)
        print(f"[FAIL] UNRESOLVABLE ADOPTION TARGET: {new} does not exist on "
              f"the registry (newest published: {newest}; source={src}).")
        print(f"       Pinning it would point every install at a tag "
              f"`docker pull` cannot resolve (vibe-ic#354).")
        return 1
    print(f"  adoption-target-resolves : OK ({new} is published; source={src})")
    depth_rc, depth_n = check_layer_depth(new, label="adoption target")
    if depth_rc == 1:
        if allow_over_depth:
            print(f"[OVERRIDDEN] --allow-over-depth was passed: adopting {new} "
                  f"at {depth_n} layers ANYWAY. The finding above stands — a "
                  f"host without this image already cached still cannot pull "
                  f"it, and the tests that need it will report NOT VERIFIED "
                  f"rather than pass. Recorded here so the choice is visible.")
            return 0
        print(f"[FAIL] UNPULLABLE ADOPTION TARGET: {new} resolves but cannot be "
              f"registered on a clean host ({depth_n} layers > "
              f"{MAX_REGISTRABLE_LAYERS}).")
        print(f"       Adopting it would make every `docker pull "
              f"ghcr.io/{GHCR_REPO}:{new}` in this tree — including the remedy "
              f"line every NOT VERIFIED skip prints — a command that cannot "
              f"succeed (vibe-ic#1297).")
        print(f"       Fix: publish a squashed tag, or, if this bump is needed "
              f"before the squash lands, re-run with --allow-over-depth to "
              f"adopt it deliberately and on the record.")
        return 1
    return 0


def do_set(root: Path, vf: Path, new: str, ignore, dry: bool,
           verify_target: bool = True, allow_over_depth: bool = False) -> int:
    """Write the anchor and every live pointer.

    `verify_target` distinguishes the two things this script is asked to do,
    which look identical and are not:

      ADOPTING an image that exists   `--set X.Y.Z`, run in THIS repo after the
                                      fork published X.Y.Z. The tag must
                                      resolve, or we recreate vibe-ic#354.
      MINTING a version that does not `--bump`, run in the vibeic-eda repo to
                                      choose the number about to be BUILT. The
                                      tag cannot exist yet, by construction, so
                                      demanding that it resolve would make
                                      `--bump` permanently unusable.

    Found by `--bump patch --dry-run` going red the moment the adoption check
    was added: the script serves both repos, and a rule written for one of them
    broke the other. Verification is also skipped for `--dry-run`, which writes
    nothing and should not need a network to say what it would do.
    """
    if not SEMVER_RE.match(new):
        print(f"[FAIL] target '{new}' is not X.Y.Z", file=sys.stderr)
        return 2
    # Verified BEFORE anything is written: a refused adoption must leave the
    # tree exactly as it found it, not half-rewritten to an unpullable tag.
    if verify_target and not dry and \
            check_adoption_target_resolves(new, allow_over_depth) != 0:
        return 1
    changed = []
    for rel in INSTALL_DOC_CANDIDATES:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        nt = TAG_RE.sub(f"vibeic-eda:{new}", text)
        nt = CURRENT_RE.sub(lambda m: m.group(1) + new + m.group(3), nt)
        if nt != text:
            changed.append(rel)
            if not dry:
                p.write_text(nt, encoding="utf-8")
    verb = "would write" if dry else "wrote"
    print(f"vibeic_eda_version_sync: {verb} VERSION -> {new}")
    if not dry:
        vf.write_text(new + "\n", encoding="utf-8")
    for rel in changed:
        print(f"  {verb}: {rel}")
    if not changed:
        print("  (no install-doc changes — already at target)")
    if dry:
        return 0
    print("--- re-checking ---")
    return do_check(root, new, ignore, vf=vf)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="vibeic-eda image-version sync + drift gate")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true",
                   help="BLOCKING: every live pointer == VERSION and the anchor has not "
                        "regressed. Repo + git only, never the registry (default)")
    g.add_argument("--report-upstream", action="store_true", dest="report_upstream",
                   help="NON-BLOCKING: resolve the registry and record what it said and "
                        "when. Exits 0 (read taken) or 2 (unreachable), never 1")
    g.add_argument("--set", metavar="X.Y.Z", help="set VERSION and rewrite every live pointer")
    g.add_argument("--bump", choices=["patch", "minor", "major"], help="increment VERSION, then --set it")
    g.add_argument("--print", action="store_true", dest="print_", help="print the current VERSION")
    ap.add_argument("--dry-run", action="store_true", help="with --set/--bump: show changes, write nothing")
    ap.add_argument("--json", metavar="PATH", dest="json_path",
                    help="with --report-upstream: also write the dated reading as JSON")
    ap.add_argument("--require-remote", action="store_true",
                    help="with --report-upstream: an unverifiable registry reports NOT "
                         "CHECKED (rc 2) instead of UNVERIFIED (rc 0). ACCEPTED AND "
                         "IGNORED with --check, which makes no registry call at all "
                         "(vibe-ic#927) — kept so existing CI invocations keep working")
    ap.add_argument("--allow-over-depth", action="store_true",
                    dest="allow_over_depth",
                    help="with --set: adopt a tag whose layer count is ABOVE the "
                         f"daemon's registration ceiling ({MAX_REGISTRABLE_LAYERS}) "
                         "anyway. The finding is still printed in full and the "
                         "override is announced — use it when a bump is needed before "
                         "the image squash lands (vibe-ic#1297), not to make the "
                         "message go away")
    args = ap.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    root = repo_root(script_dir)
    vf = find_version_file(root, script_dir)
    if vf is None:
        print(f"[FAIL] no VERSION file found (looked in {script_dir}, {root}/tools/vibeic-eda, {root})",
              file=sys.stderr)
        return 2
    version = read_version(vf)
    ignore = load_extra_ignore(root)

    if args.print_:
        print(version)
        return 0
    if args.report_upstream:
        # THE INVARIANT IS ENFORCED HERE, NOT MERELY PROMISED IN A DOCSTRING
        # (vibe-ic#969). "NEVER RETURNS 1" was a claim about the code as
        # written, and the code as written could return 1 the moment `--json`
        # named an unwritable path — a claim that holds only for the inputs
        # somebody happened to try is not an invariant, it is a habit.
        #
        # Guarding the one write that was found (above) fixes the one instance.
        # This clamp is what makes the SENTENCE true: whatever else this path
        # ever grows — a second output file, a new registry accessor, a library
        # that raises where today's does not — an unexpected failure degrades to
        # rc 2 NOT CHECKED, which is this repo's word for "nothing was
        # compared", and which `run_tolerating_uncheckable` accepts. It cannot
        # silently become a PASS: 0 is returned only by the function itself.
        #
        # KeyboardInterrupt / SystemExit are BaseException and are deliberately
        # NOT swallowed — a user's Ctrl-C is not an unreachable registry.
        try:
            rc = do_report_upstream(version, args.require_remote,
                                    args.json_path)
        except Exception as e:                                   # noqa: BLE001
            print(f"[NOT CHECKED] upstream currency: the report itself failed "
                  f"({e.__class__.__name__}: {e}). NOTHING was compared. This "
                  f"is not a pass and not a landing verdict — the reporting "
                  f"half never sets one (vibe-ic#969).")
            return 2
        if rc not in (0, 2):
            print(f"[NOT CHECKED] upstream currency: the report returned an "
                  f"out-of-contract code ({rc}); reported as NOT CHECKED "
                  f"because this path may never fail a landing (vibe-ic#969).")
            return 2
        return rc
    if args.set:
        return do_set(root, vf, args.set, ignore, args.dry_run,
                      allow_over_depth=args.allow_over_depth)
    if args.bump:
        # MINTING, not adopting — see do_set's docstring. The computed version
        # does not exist on the registry yet and must not be required to.
        return do_set(root, vf, next_version(version, args.bump), ignore,
                      args.dry_run, verify_target=False)
    return do_check(root, version, ignore, args.require_remote, vf)


if __name__ == "__main__":
    raise SystemExit(main())
