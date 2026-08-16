#!/usr/bin/env python3
"""Is the published benchmark corpus present in THIS checkout?

WHY THIS EXISTS
===============
The published results moved to https://github.com/vibeic/benchmark-data. What stays
in vibe-ic under `benchmark-data/` is the DESIGN INPUT the flow reads — 542 files —
and three contract documents. The result cells are no longer here.

Tests that assert something about a PUBLISHED CELL ("step 30 produced its declared
outputs", "every published cell is covered by a per-cell gate") were asking about
data this repository no longer holds. Left alone they FAIL, and a failure claims a
defect in the tree. There is no defect: the data moved.

THE RULE, which is this repository's own and not a new one
==========================================================
A check that cannot measure must never report that it measured. An absent corpus is
"I could not look", and the honest rendering of that is SKIP with the reason named —
exactly as vibe-ic#1357 established for an absent TOOL:

    iverilog absent  -> skip, naming the tool      (not: fail on a missing artefact)
    corpus absent    -> skip, naming the corpus    (not: fail on a missing cell)

WHAT THIS IS NOT
================
It is NOT a way to make a red test green. Where the corpus IS present — a clone of
benchmark-data placed at `VIBE_IC_BENCHMARK_DATA`, or a checkout that still carries
cells — every one of these tests runs exactly as before and can still fail. The skip
is reachable only when there is genuinely nothing to read, and
`test_the_skip_is_not_reachable_when_the_corpus_is_present` pins that.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

import pytest

#: Where a caller may point us at a clone of `vibeic/benchmark-data`.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"

_PLUGIN = Path(__file__).resolve().parents[1]
_REPO = _PLUGIN.parents[2]


def corpus_root() -> Optional[Path]:
    """The directory holding published cells, or None if there is none to read.

    Order matters: an explicit environment pointer wins, because a caller who
    supplied one is asking for THAT corpus and a silent fallback to an in-repo
    remnant would answer about a different tree than they named.
    """
    env = os.environ.get(CORPUS_ENV)
    if env:
        p = Path(env)
        return p if _has_cells(p) else None
    here = _REPO / "benchmark-data"
    return here if _has_cells(here) else None


def _has_cells(root: Path) -> bool:
    """A published CELL, not merely the directory.

    `benchmark-data/` still exists in vibe-ic — it holds the design inputs — so its
    presence proves nothing. The question is whether any published cell is readable,
    and PUBLISHING.md defines one as `ic/<IC>/v<version>_<PDK>/`.
    """
    ic = root / "ic"
    if not ic.is_dir():
        return False
    for design in ic.iterdir():
        if not design.is_dir():
            continue
        for entry in design.iterdir():
            if entry.is_dir() and entry.name.startswith("v"):
                return True
    return False


def cell_dirs() -> Tuple[Path, ...]:
    """Every published cell that is actually readable here. Empty when there is none."""
    root = corpus_root()
    if root is None:
        return ()
    out = []
    for design in sorted((root / "ic").iterdir()):
        if not design.is_dir():
            continue
        for entry in sorted(design.iterdir()):
            if entry.is_dir() and entry.name.startswith("v"):
                out.append(entry)
    return tuple(out)


#: The reason, written once so every skip in the suite says the same thing and a
#: reader who greps for one finds them all.
SKIP_REASON = (
    "the published benchmark corpus is not in this checkout — the result cells live "
    f"in vibeic/benchmark-data. Point {CORPUS_ENV} at a clone to run this check "
    "against them. This is 'could not look', not 'nothing was wrong'."
)

#: Apply to any test whose subject is a PUBLISHED CELL rather than plugin behaviour.
needs_corpus = pytest.mark.skipif(corpus_root() is None, reason=SKIP_REASON)
