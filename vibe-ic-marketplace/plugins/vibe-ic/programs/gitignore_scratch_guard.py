#!/usr/bin/env python3
"""gitignore_scratch_guard.py — ORGANIC #720

Durable CI guard that the repo-root `.gitignore` carries the ROOT-ANCHORED
`/_*.js` rule, so session scratch Workflow/orchestration scripts created at the
repo root (`_review_backlog_*.js`, `_sweep_workflow.js`, …) can never be swept
into a commit and pushed to github. Also verifies the rule is correctly
root-anchored — it must NOT match a legitimately-tracked `_*.js` living in a
SUBDIR (the mcp-eda devices `_registry.js`).

This is the program-first persistence of the hygiene rule: a prose request a
future editor could drop becomes a CI-checkable invariant.

Exit codes:
    0  rule present AND correctly root-anchored (root scratch ignored,
       subdir _registry.js NOT ignored, no tracked root _*.js)
    1  rule missing / mis-anchored / a tracked file would be affected
    2  not in a git repo / git unavailable

chip-AGNOSTIC: pure repo-hygiene path rule; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_RULE = "/_*.js"
# a legitimately-tracked subdir _*.js that the ROOT anchor must NOT capture
_SUBDIR_TRACKED = ("vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/"
                   "_registry.js")


def _git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root),
                          capture_output=True, text=True)


def _repo_root(start: Path) -> Path | None:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                        cwd=str(start), capture_output=True, text=True)
    return Path(cp.stdout.strip()) if cp.returncode == 0 else None


def audit(root: Path) -> dict:
    """Evidence dict: {ok, rule_present, root_scratch_ignored,
    subdir_registry_ignored, tracked_root_scratch[]}."""
    gi = root / ".gitignore"
    rule_present = (gi.is_file()
                    and _RULE in gi.read_text().splitlines())
    root_scratch_ignored = _git(
        root, "check-ignore", "_scratch_probe.js").returncode == 0
    subdir_registry_ignored = _git(
        root, "check-ignore", _SUBDIR_TRACKED).returncode == 0
    tracked = _git(root, "ls-files").stdout.splitlines()
    tracked_root_scratch = [f for f in tracked
                            if "/" not in f and f.startswith("_")
                            and f.endswith(".js")]
    ok = (rule_present and root_scratch_ignored
          and not subdir_registry_ignored and not tracked_root_scratch)
    return {
        "ok": ok,
        "rule_present": rule_present,
        "root_scratch_ignored": root_scratch_ignored,
        "subdir_registry_ignored": subdir_registry_ignored,
        "tracked_root_scratch": tracked_root_scratch,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard the #720 root-anchored /_*.js gitignore rule.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: git toplevel of CWD)")
    ap.add_argument("--json", default=None, help="write evidence JSON here")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else _repo_root(Path.cwd())
    if root is None or not (root / ".git").exists() and not root.is_dir():
        print("ERROR: not in a git repo / git unavailable", file=sys.stderr)
        return 2
    if root is None:
        print("ERROR: could not resolve repo root", file=sys.stderr)
        return 2
    ev = audit(root)
    text = json.dumps(ev, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    if not ev["ok"]:
        print("FAIL: #720 scratch-script gitignore guard — "
              f"{ev}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
