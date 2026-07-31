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
from typing import List, Tuple

WAVEFORM_SUFFIXES = (".vcd", ".fst", ".ghw", ".shm")
# Directories that are never part of the shipped bundle.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def audit(root: str) -> Tuple[List[str], int]:
    """Waveform artefacts under root, WITH the number of files examined.

    The count is returned rather than left for the caller to re-derive, because
    `PASS - 0 waveform artifact(s)` was printed identically for a clean tree and
    for a path that does not exist. This gate looks for something that should be
    ABSENT, so zero is the expected answer — which is exactly why "I walked
    3000 files and found none" and "I walked nothing" must not read the same
    (#564).
    """
    root_p = Path(root)
    hits: List[str] = []
    examined = 0
    for p in sorted(root_p.rglob("*")):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        examined += 1
        if p.suffix.lower() in WAVEFORM_SUFFIXES:
            hits.append(str(p))
    return hits, examined


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", nargs="?", default=".",
                   help="tree to scan (default: cwd)")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    hits, examined = audit(args.root)
    for h in hits:
        print(f"waveform artifact in shipped tree: {h}")
    if not hits and examined == 0:
        # Not clean — nothing was walked. Measured over 40 corpus projects
        # before landing: 38 answer 0 artefacts over a real tree and 2 answer 1
        # (a genuine finding), so no real project reaches this branch.
        print(f"VACUOUS_PASS: waveform_artifact_hygiene_check examined nothing "
              f"(reason: no files under {args.root!r}) — an absent tree has no "
              f"waveform artefacts for the same reason it has nothing else",
              file=sys.stderr)
        return 2
    # The denominator goes on its OWN line, BEFORE the verdict, and the verdict
    # line stays free of it.
    #
    # `gate_host_independence_check` compares the LAST non-empty line between a
    # working checkout and a fresh worktree, and it is right to treat a differing
    # count as a real difference. But this gate walks the whole repo root, so its
    # count legitimately differs — measured 3753 vs 3693, the 60 being run
    # leftovers under benchmark-data/ that a fresh worktree does not have. Both
    # sides said PASS with rc 0; only the number moved.
    #
    # Putting the count on the verdict line made an honest disclosure into a
    # host-dependent verdict. Disclosure and verdict are different jobs, and the
    # consumers differ too: a human reads the count, the aggregator reads the
    # last line.
    print(f"examined {examined} file(s) under {args.root!r}")
    print(f"{'FAIL' if hits else 'PASS'} — {len(hits)} waveform artifact(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
