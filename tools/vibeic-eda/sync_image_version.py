#!/usr/bin/env python3
"""vibeic-eda image-version sync — one source of truth + a fool-proof drift gate.

WHY THIS EXISTS
    The image tag `vibeic-eda:X.Y.Z` is copy-pasted into many install docs across
    this repo (and the sibling `vibeic/vibeic-eda` repo). The forked tools are
    upgraded OFTEN — any one tool bump → a new image version — so every reference
    must move together or users pull a stale / nonexistent tag. This makes the
    propagation mechanical and the drift a hard error:

        SOURCE OF TRUTH            the `VERSION` file (X.Y.Z, one line)
        --check      (default)     FAIL if any LIVE pointer disagrees with VERSION
        --set X.Y.Z                write VERSION + rewrite every live pointer
        --bump patch|minor|major   compute the next version, then --set it
        --print                    print the current VERSION

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
import re
import subprocess
import sys
from pathlib import Path

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


def do_check(root: Path, version: str, ignore) -> int:
    strict = install_doc_refs(root)
    net = ghcr_hits(root, ignore)
    install_set = set(INSTALL_DOC_CANDIDATES)

    drift_strict = [r for r in strict if r[2] != version]
    drift_net = [h for h in net if h[2] != version and h[0] not in install_set]

    ok_docs = sorted({r[0] for r in strict})
    print(f"vibeic_eda_version_sync: VERSION = {version}")
    print(f"  install-doc refs checked : {len(strict)} across {len(ok_docs)} file(s)")
    print(f"  repo-wide ghcr pointers  : {len(net)}")
    if not drift_strict and not drift_net:
        print(f"[PASS] all live pointers == {version}")
        return 0
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
    return do_check(root, version, ignore)


if __name__ == "__main__":
    raise SystemExit(main())
