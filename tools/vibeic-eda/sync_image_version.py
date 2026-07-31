#!/usr/bin/env python3
"""vibeic-eda image-version sync — one source of truth + a fool-proof drift gate.

WHY THIS EXISTS
    The image tag `vibeic-eda:X.Y.Z` is copy-pasted into many install docs across
    this repo (and the sibling `vibeic/vibeic-eda` repo). The forked tools are
    upgraded OFTEN — any one tool bump → a new image version — so every reference
    must move together or users pull a stale / nonexistent tag. This makes the
    propagation mechanical and the drift a hard error:

        SOURCE OF TRUTH            the `VERSION` file (X.Y.Z, one line)
        --check      (default)     FAIL if any LIVE pointer disagrees with VERSION,
                                   OR if the VERSION anchor itself is STALE relative
                                   to the newest published image tag (see below)
        --set X.Y.Z                write VERSION + rewrite every live pointer
        --bump patch|minor|major   compute the next version, then --set it
        --print                    print the current VERSION

    ANCHOR-vs-REALITY (issue #215)
        Internal consistency (every pointer == VERSION) is NECESSARY but NOT
        SUFFICIENT: if the VERSION file is ITSELF stale, the whole tree is
        *consistently wrong* and the old check went green about it — it would have
        demanded a correct pointer be rolled BACK to the stale anchor. So --check
        also compares VERSION against the newest published `ghcr.io/vibeic/...`
        semver tag (the actual reality). VERSION older than the newest published
        tag FAILs loudly, naming both. Registry query is best-effort: pin/override
        it with the `VIBEIC_EDA_PUBLISHED_TAG` env (tests / offline / CI); if the
        registry can't be reached AND no override is set, the anchor line reports
        UNVERIFIED (internal consistency only) rather than silently claiming clean.

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
]

# Files that legitimately carry OLD versions — never checked, never rewritten.
# Changelog / status / roadmap docs record what shipped in each past version, so a
# stale tag in them is HISTORY, not drift. Add repo-specific one-offs (a doc that
# quotes an old pull command on purpose) to `.image-version-ignore` instead.
HISTORY_GLOBS = ["FIX_STATUS.md", "CHANGELOG*", "*CHANGELOG*", "*ROADMAP*.md",
                 "*_STATUS.md", "sync_image_version.py"]

TAG_RE = re.compile(r"vibeic-eda:(\d+\.\d+\.\d+)")
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


def check_latest_points_at_anchor(version: str,
                                  require_remote: bool = False) -> int:
    """`:latest` must resolve to the SAME manifest as the anchor version.

    #423: it did not, for four days, and nothing said so. A reader who pulls
    the tag that means "newest" got an older toolchain than the campaign runs
    on, and their results were not comparable to the published ones. Skipped
    (not failed) when the override env is set, because that mode exists for
    offline / deterministic CI and there is no registry to ask.
    """
    if os.environ.get(PUBLISHED_TAG_ENV):
        print("  latest-vs-anchor         : SKIPPED "
              f"({PUBLISHED_TAG_ENV} override set — no registry to query)")
        return 0
    try:
        d_latest = _query_ghcr_digest(GHCR_REPO, "latest")
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
        print(f"[FAIL] `:latest` does NOT point at the anchor version.")
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
    if _semver_key(version) < _semver_key(pub):
        print(f"[FAIL] STALE ANCHOR: VERSION={version} is OLDER than the newest "
              f"published image tag {pub} (source={src}).")
        print(f"       Internal consistency is not correctness — every pointer "
              f"equal to VERSION is *consistently wrong*.")
        print(f"       Fix: python3 {Path(__file__).name} --set {pub}")
        return 1
    if version not in tags:
        print(f"[FAIL] UNRESOLVABLE PIN: VERSION={version} does not exist on the "
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
             require_remote: bool = False) -> int:
    strict = install_doc_refs(root)
    net = ghcr_hits(root, ignore)
    install_set = set(INSTALL_DOC_CANDIDATES)

    drift_strict = [r for r in strict if r[2] != version]
    drift_net = [h for h in net if h[2] != version and h[0] not in install_set]

    ok_docs = sorted({r[0] for r in strict})
    print(f"vibeic_eda_version_sync: VERSION = {version}")
    print(f"  install-doc refs checked : {len(strict)} across {len(ok_docs)} file(s)")
    print(f"  repo-wide ghcr pointers  : {len(net)}")
    # Anchor-vs-reality (issue #215): the VERSION anchor must not itself be stale
    # relative to the newest published image tag, or the whole tree is consistently
    # wrong. This is a SEPARATE failure axis from pointer drift; either fails --check.
    anchor_rc = check_anchor_vs_reality(version, require_remote)
    # vibe-ic#423 — a THIRD failure axis. The two above compare our pointers
    # against the anchor and the anchor against the registry; both passed
    # while `:latest` sat on 0.2.28 and 0.2.30 was current. Nobody was
    # checking the tag an outside reader actually pulls.
    latest_rc = check_latest_points_at_anchor(version, require_remote)
    if not drift_strict and not drift_net:
        if anchor_rc == 0 and latest_rc == 0:
            print(f"[PASS] all live pointers == {version}, anchor tracks "
                  f"reality, and :latest resolves to it")
            return 0
        # A real disagreement (1) dominates an unverifiable one (2): if the
        # registry answered for one axis and disagreed, that is a defect even
        # though the other axis could not be reached.
        if anchor_rc == 1 or latest_rc == 1:
            return 1
        return 2
    print(f"[FAIL] {len(drift_strict) + len(drift_net)} live pointer(s) != {version}:")
    for rel, ln, ver, kind in drift_strict:
        print(f"   {rel}:{ln}  {kind}={ver}  (want {version})")
    for rel, ln, ver in drift_net:
        print(f"   {rel}:{ln}  ghcr={ver}  (want {version}) — unregistered live pointer; "
              f"add to INSTALL_DOC_CANDIDATES or .image-version-ignore")
    return 1


def do_set(root: Path, vf: Path, new: str, ignore, dry: bool) -> int:
    if not SEMVER_RE.match(new):
        print(f"[FAIL] target '{new}' is not X.Y.Z", file=sys.stderr)
        return 2
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
    return do_check(root, new, ignore)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="vibeic-eda image-version sync + drift gate")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="verify all live pointers == VERSION (default)")
    g.add_argument("--set", metavar="X.Y.Z", help="set VERSION and rewrite every live pointer")
    g.add_argument("--bump", choices=["patch", "minor", "major"], help="increment VERSION, then --set it")
    g.add_argument("--print", action="store_true", dest="print_", help="print the current VERSION")
    ap.add_argument("--dry-run", action="store_true", help="with --set/--bump: show changes, write nothing")
    ap.add_argument("--require-remote", action="store_true",
                    help="with --check: an unverifiable registry is a FAIL, not UNVERIFIED (CI mode, vibe-ic#354)")
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
    if args.set:
        return do_set(root, vf, args.set, ignore, args.dry_run)
    if args.bump:
        return do_set(root, vf, next_version(version, args.bump), ignore, args.dry_run)
    return do_check(root, version, ignore, args.require_remote)


if __name__ == "__main__":
    raise SystemExit(main())
