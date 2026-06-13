#!/usr/bin/env python3
"""version_bump_monotonic_check.py — strict version-bump gate for the
core-agent loop (extracted from vibe-ic:core-agent-loop §Step 3).

The skill's Step 3 says the core-agent must "bump the patch version in
BOTH locations" before pushing. Two distinct invariants are implied:

  (A) plugin.json.version == marketplace.json plugins[].version  (equality)
      — already enforced by ``marketplace_version_sync_check.py``.

  (B) the NEW version is STRICTLY GREATER than the PREVIOUS commit's
      version (monotonic bump).  No existing program checked this. If the
      agent commits without bumping (or accidentally lowers the version),
      ``/plugin update`` sees no version change and silently no-ops,
      leaving end-users on a stale cache.

This program implements invariant (B): it reads the current working-tree
``plugin.json.version`` and compares it (semver) against the version
recorded in ``plugin.json`` at a baseline git ref (default: HEAD, i.e.
the previous commit). PASS iff current > baseline. It ALSO re-asserts
(A) so the loop has one self-contained gate.

Semver compare is numeric per-component (so 0.2.10 > 0.2.9, not the
lexical opposite).

Usage
-----
    # compare working-tree plugin.json vs the version at HEAD
    python3 version_bump_monotonic_check.py --plugin-json <path/plugin.json> \
            [--marketplace-json <path/marketplace.json>] [--base HEAD] \
            [--json <out>]

    # explicit two-value compare (no git; for testing / CI)
    python3 version_bump_monotonic_check.py --current 0.2.13 --previous 0.2.12

Exit codes
----------
    0   PASS — current strictly greater than previous (and, if a
            marketplace.json was given, equality holds).
    1   FAIL — current <= previous (no bump / regression), OR
            plugin.json != marketplace.json.
    2   argument / I/O / git error (e.g. baseline ref has no plugin.json,
            malformed version) — an HONEST error, never a silent PASS.

Missing files / unparseable versions -> rc 2. There is no vacuous PASS
path: a bump cannot be "verified" without two real, comparable versions.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


_SEMVER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)")


def parse_semver(v: str) -> Optional[Tuple[int, int, int]]:
    """Parse 'X.Y.Z' (optional leading v) into a numeric tuple, or None."""
    if not isinstance(v, str):
        return None
    m = _SEMVER_RE.match(v)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _read_json_version(path: Path) -> Optional[str]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d.get("version")


def _read_marketplace_version(path: Path) -> Optional[str]:
    """Return plugins[0].version (or first plugin with a version)."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    plugins = d.get("plugins")
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if isinstance(entry, dict) and entry.get("version") is not None:
            return entry.get("version")
    return None


def _git_show_version(repo_dir: Path, ref: str, rel_path: str) -> Optional[str]:
    """git show <ref>:<rel_path> -> parse .version. None on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir), "show", f"{ref}:{rel_path}"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout).get("version")
    except Exception:
        return None


@dataclass
class Report:
    passed: bool
    current: Optional[str]
    previous: Optional[str]
    bump_ok: bool
    equality_checked: bool
    equality_ok: Optional[bool]
    reason: str


def evaluate(current: Optional[str], previous: Optional[str],
             market: Optional[str], equality_checked: bool) -> Tuple[Report, int]:
    cur_t = parse_semver(current) if current is not None else None
    prev_t = parse_semver(previous) if previous is not None else None

    if cur_t is None:
        return Report(False, current, previous, False, equality_checked,
                      None, f"current version unparseable: {current!r}"), 2
    if prev_t is None:
        return Report(False, current, previous, False, equality_checked,
                      None, f"previous version unparseable: {previous!r}"), 2

    bump_ok = cur_t > prev_t

    equality_ok: Optional[bool] = None
    if equality_checked:
        mkt_t = parse_semver(market) if market is not None else None
        if market is None or mkt_t is None:
            return Report(False, current, previous, bump_ok, True, False,
                          f"marketplace version unparseable: {market!r}"), 2
        equality_ok = (current == market) or (cur_t == mkt_t)

    if not bump_ok:
        return Report(False, current, previous, False, equality_checked,
                      equality_ok,
                      f"version not bumped: current {current} <= previous "
                      f"{previous}"), 1
    if equality_checked and not equality_ok:
        return Report(False, current, previous, True, True, False,
                      f"plugin.json {current} != marketplace.json "
                      f"{market}"), 1

    return Report(True, current, previous, True, equality_checked, equality_ok,
                  f"OK: {previous} -> {current} (strict bump"
                  + (", marketplace in sync" if equality_checked else "")
                  + ")"), 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Assert the version bump is strictly monotonic vs the "
                    "previous commit (chip-AGNOSTIC).")
    p.add_argument("--plugin-json", type=Path, default=None,
                   help="Path to working-tree plugin.json.")
    p.add_argument("--marketplace-json", type=Path, default=None,
                   help="Path to marketplace.json (optional; re-asserts equality).")
    p.add_argument("--base", default="HEAD",
                   help="Git ref to compare against (default: HEAD = previous commit).")
    p.add_argument("--current", default=None,
                   help="Explicit current version (skips git / plugin.json read).")
    p.add_argument("--previous", default=None,
                   help="Explicit previous version (skips git read).")
    p.add_argument("--json", default=None, help="Write JSON report to this path.")
    args = p.parse_args(argv)

    current: Optional[str] = None
    previous: Optional[str] = None
    market: Optional[str] = None
    equality_checked = False

    if args.current is not None and args.previous is not None:
        current = args.current
        previous = args.previous
    else:
        if args.plugin_json is None:
            print("ERROR: provide --plugin-json (and optionally --base) "
                  "or both --current and --previous.", file=sys.stderr)
            return 2
        pj = args.plugin_json
        if not pj.is_file():
            print(f"ERROR: plugin.json not found: {pj}", file=sys.stderr)
            return 2
        current = _read_json_version(pj)
        if current is None:
            print(f"ERROR: cannot read 'version' from {pj}", file=sys.stderr)
            return 2
        # Resolve repo dir + path relative to repo root for `git show`.
        repo_dir = pj.resolve().parent
        try:
            top = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=False)
            if top.returncode != 0:
                print(f"ERROR: not a git repo: {repo_dir}", file=sys.stderr)
                return 2
            repo_root = Path(top.stdout.strip())
            rel = pj.resolve().relative_to(repo_root).as_posix()
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot resolve git path for {pj}: {e}", file=sys.stderr)
            return 2
        previous = _git_show_version(repo_root, args.base, rel)
        if previous is None:
            print(f"ERROR: cannot read plugin.json version at {args.base} "
                  f"({rel}). If this is the first commit, supply --previous.",
                  file=sys.stderr)
            return 2

    if args.marketplace_json is not None:
        mj = args.marketplace_json
        if not mj.is_file():
            print(f"ERROR: marketplace.json not found: {mj}", file=sys.stderr)
            return 2
        market = _read_marketplace_version(mj)
        equality_checked = True

    report, rc = evaluate(current, previous, market, equality_checked)
    report_json = json.dumps(asdict(report), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json + "\n", encoding="utf-8")

    tag = {0: "PASS", 1: "FAIL", 2: "ERROR"}[rc]
    print(f"[{tag}] version_bump_monotonic_check: {report.reason}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
