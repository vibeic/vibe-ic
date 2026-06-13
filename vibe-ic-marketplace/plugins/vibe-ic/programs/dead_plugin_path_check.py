#!/usr/bin/env python3
"""dead_plugin_path_check.py — no retired-second-plugin path may ship.

After plugin unification the deterministic-edition plugin tree no longer
exists anywhere, so any doctrine/path that references it is dead: a guard
like "if you have the deterministic edition installed" never fires, and
an agent following the text verbatim runs a nonexistent checker.

This checker scans the shipped bundle (skills/ + programs/ + _shared/ by
default) for the retired plugin token and fails on any occurrence —
path forms (`plugins/<token>/...`) and bare prose mentions alike, since
both reintroduce dead doctrine.

Exit: 0 = PASS (no references), 1 = FAIL (references listed).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

# Constructed at runtime so this checker never matches itself.
RETIRED_PLUGIN_TOKEN = "vibe-ic-" + "d"

_SCAN_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".sh", ".tcl"}
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def audit(plugin_root: str) -> List[str]:
    """Return `path:lineno: line` hits for the retired token in the bundle."""
    root = Path(plugin_root)
    me = Path(__file__).resolve()
    hits: List[str] = []
    for sub in ("skills", "programs", "_shared"):
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in _SCAN_SUFFIXES:
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.resolve() == me:
                continue
            try:
                text = p.read_text(errors="replace")
            except Exception:
                continue
            if RETIRED_PLUGIN_TOKEN not in text:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if RETIRED_PLUGIN_TOKEN in line:
                    hits.append(f"{p}:{i}: {line.strip()[:120]}")
    return hits


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plugin_root", nargs="?", default=".",
                   help="plugin root containing skills/ programs/ _shared/")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    hits = audit(args.plugin_root)
    for h in hits:
        print(h)
    print(f"{'FAIL' if hits else 'PASS'} — {len(hits)} retired-plugin reference(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
