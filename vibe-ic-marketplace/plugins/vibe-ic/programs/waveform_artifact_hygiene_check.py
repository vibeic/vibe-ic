#!/usr/bin/env python3
"""waveform_artifact_hygiene_check.py — no sim waveform dumps in the bundle.

A raw simulation waveform dump (VCD/FST/GHW/SHM) is never a program: it
inflates the shipped package and actively pollutes repo-wide audits —
VCD identifier/timestamp tokens spuriously match issue-tag greps (e.g.
searching programs/ for an issue number hits the dump).  Simulation
byproducts belong in tmp/work dirs, never inside the plugin tree.

This checker walks a tree (filesystem level, so UNTRACKED strays count
too — that is exactly how the defect escaped git-based gates) and fails
when any waveform artifact exists.

Exit: 0 = PASS (tree clean), 1 = FAIL (artifacts listed).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

WAVEFORM_SUFFIXES = (".vcd", ".fst", ".ghw", ".shm")
# Directories that are never part of the shipped bundle.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def audit(root: str) -> List[str]:
    """Return paths of waveform artifacts under root (shipped-tree scope)."""
    root_p = Path(root)
    hits: List[str] = []
    for p in sorted(root_p.rglob("*")):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in WAVEFORM_SUFFIXES:
            hits.append(str(p))
    return hits


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", nargs="?", default=".",
                   help="tree to scan (default: cwd)")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    hits = audit(args.root)
    for h in hits:
        print(f"waveform artifact in shipped tree: {h}")
    print(f"{'FAIL' if hits else 'PASS'} — {len(hits)} waveform artifact(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
