#!/usr/bin/env python3
"""Is the published benchmark corpus present in THIS checkout?

WHY THIS EXISTS
===============
The published results moved to https://github.com/vibeic/benchmark-data.

THIS PARAGRAPH USED TO SAY that what stays in vibe-ic under `benchmark-data/` is the
DESIGN INPUT the flow reads — 542 files — and three contract documents. That was true
of the FIRST move and stopped being true at the second: v1.10.56 took the remainder
too, and `git ls-tree -r HEAD -- benchmark-data` now matches NOTHING. A reader who
believed this module's own docstring would look for a design input that is not there.

The design input was not lost, which is the part worth stating rather than implying:
all 542 of those files are accounted for in the published repository — 521 present
there (55 of them under a renamed prefix), and 21 dropped one commit earlier as
duplicates of an IC-level input the published tree does carry.

So NOTHING under `benchmark-data/` is in this checkout, cells and input alike, and
every check over either has to reach the pointer below or say it could not look.

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
cells — every one of these tests runs exactly as before and can still fail.

THE FIRST VERSION OF THIS DOCSTRING WAS ITSELF A LYING CHECK. It claimed a test named
`test_the_skip_is_not_reachable_when_the_corpus_is_present` pinned that property. No
such test existed — the sentence was the entire guarantee. An adversarial review
grepped for the name, found it only here, and then demonstrated the hole it was
covering: `VIBE_IC_BENCHMARK_DATA=<empty dir>` gave `29 passed, 2 skipped`, a green
run with every corpus check switched off.

The guarantees now live in `test_published_corpus_helper.py`, which is a file that
exists, and a broken pointer raises instead of skipping — see `corpus_root`.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import pytest

#: Where a caller may point us at a clone of `vibeic/benchmark-data`.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"

_PLUGIN = Path(__file__).resolve().parents[1]
_REPO = _PLUGIN.parents[2]

#: The four states this module answers, spelled once so a caller can branch on
#: them instead of matching the message text.
#:
#: `UNSET` and `PUBLISHES_NOTHING` are both SKIPs and they are NOT the same skip:
#: one is "nobody offered a corpus", the other is "I read the corpus you named
#: and it publishes zero cells". `BROKEN` is neither, and never becomes either.
UNSET = "unset"
BROKEN = "broken"
PUBLISHES_NOTHING = "publishes_nothing"
PRESENT = "present"


class CorpusPointerBroken(RuntimeError):
    """`VIBE_IC_BENCHMARK_DATA` was set and there is nothing readable there."""


def corpus_root() -> Optional[Path]:
    """The directory holding published cells, or None if none was ever offered.

    TWO ABSENCES THAT ARE NOT THE SAME FACT
    =======================================
    Nobody set the pointer and the repo has no cells
        -> None. Honest: no corpus was offered, so a check over it skips.

    Somebody SET the pointer and it holds no cells
        -> raise. They named a corpus. The name is wrong, or the clone failed, or
           the CI step that was meant to fetch it did nothing. Returning None here
           renders "your path is broken" as "there is no corpus", and every corpus
           check goes green-by-skip.

    That second path was REAL, not hypothetical:

        VIBE_IC_BENCHMARK_DATA=<empty dir> pytest ... -> 29 passed, 2 skipped

    A mistyped path, a failed clone, or a no-op fetch step turned the whole set
    green. An adversarial review found it, and it found it because this module's
    docstring claimed a test pinned the property while no such test existed. Both
    are fixed: the pointer now refuses, and the test is written below the module
    it guards (`test_published_corpus_helper.py`).
    """
    state, root, reason = corpus_state()
    if state == PRESENT:
        return root
    if state == BROKEN:
        raise CorpusPointerBroken(reason)
    # UNSET and PUBLISHES_NOTHING both mean "there is no cell to measure", and
    # the two are told apart by the REASON, which is what `needs_corpus` puts on
    # the skip and what a reader sees in the junit record.
    return None


def _not_a_corpus_checkout(root: Path) -> Optional[str]:
    """None when `root` is a readable checkout of a published-corpus repository;
    otherwise the sentence naming why it is not one.

    THIS IS THE DISCRIMINATOR BETWEEN A BROKEN POINTER AND AN EMPTY CORPUS, and
    it has to be a property a mistake CANNOT accidentally satisfy. A mistyped
    path, a failed clone, a no-op CI fetch step and a bare `mkdir` all produce a
    path that is not a git checkout, or is one that tracks nothing under `ic/`.
    A real clone of the published-corpus repository is a checkout AND tracks its
    `ic/` tree even in the weeks when it publishes no cell at all — which is the
    live state as of 2026-08-20, when `bcf2f94` withdrew all four.

    Git's INDEX, never a walk: an untracked `ic/` somebody created by hand inside
    a checkout is not the published tree.
    """
    if not root.is_dir():
        return (f"the path does not exist" if not root.exists()
                else "the path is not a directory")
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse",
                              "--show-toplevel"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:   # noqa: BLE001
        return f"the path exists but git could not be asked about it ({exc})"
    if top.returncode != 0 or not top.stdout.strip():
        return ("the path exists but is not a git checkout, so it cannot be a "
                "clone of the published-corpus repository — a tarball fetch, an "
                "archive export, a dead clone or a bare mkdir all produce this")
    if not (root / "ic").is_dir():
        return ("the path is a git checkout but carries no ic/ tree, so it is "
                "not the published-corpus repository")
    try:
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-z",
                                  "--", "ic"],
                                 capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:   # noqa: BLE001
        return f"git could not enumerate ic/ in {root} ({exc})"
    if tracked.returncode != 0 or not tracked.stdout.strip():
        return ("the path is a git checkout but git TRACKS nothing under ic/, "
                "so its ic/ tree is not the published one")
    return None


def corpus_state() -> Tuple[str, Optional[Path], str]:
    """``(state, root, reason)`` — the whole resolution, in one place.

    FOUR OUTCOMES, AND COLLAPSING ANY TWO OF THEM IS THE DEFECT.

        nobody set the pointer, no cells here
            -> UNSET. No corpus was offered; a check over one skips.

        set, and there is nothing readable / it is not a corpus checkout
            -> BROKEN. They named a corpus and the name is wrong, or the clone
               failed, or the CI step meant to fetch it did nothing. Rendering
               that as "there is no corpus" is the measured exploit this module
               exists to close: `VIBE_IC_BENCHMARK_DATA=<empty dir> pytest …`
               once gave `29 passed, 2 skipped` — a green run with every corpus
               check switched off.

        set, a real corpus checkout, and it publishes ZERO cells
            -> PUBLISHES_NOTHING. **A TREE WITH NO CELLS IS NOT A TREE NOBODY
               LOOKED AT.** This state was previously indistinguishable from
               BROKEN: both raised, and the raise happens at module import (the
               `needs_corpus` marker below), so a whole test FILE died as a
               COLLECTION ERROR — including its tests that never touch the
               corpus. MEASURED 2026-08-20 against `vibeic/benchmark-data`
               @ `bcf2f94` ("withdraw all four published cells"), a clean clone
               of upstream head:

                   ERROR collecting tests/test_matrix_artefact_mutation_channel.py
                   ERROR collecting tests/test_matrix_d3_outputs_produced.py
                   Interrupted: 2 errors during collection

               and the remedy it printed — "point it at a clone of
               vibeic/benchmark-data" — was already satisfied. A refusal whose
               remedy is already in force is not a refusal, it is a dead end.

        set, a real corpus checkout, cells readable
            -> PRESENT. Everything runs exactly as it always did.

    chip-AGNOSTIC: path/git plumbing only.
    """
    env = os.environ.get(CORPUS_ENV)
    if env:
        root = Path(env)
        if _has_cells(root):
            return PRESENT, root, ""
        why = _not_a_corpus_checkout(root)
        if why is not None:
            return BROKEN, None, (
                f"{CORPUS_ENV}={env!r} names a corpus with no published cell "
                f"under ic/<design>/v<version>_<PDK>/ ({why}). This is NOT the "
                f"same as having no corpus: you said where it is. Unset "
                f"{CORPUS_ENV} to run these checks as skipped, or point it at a "
                f"clone of vibeic/benchmark-data.")
        return PUBLISHES_NOTHING, root, (
            f"{CORPUS_ENV}={env!r} IS a readable checkout of the published-corpus "
            f"repository and it publishes 0 cells right now — no "
            f"ic/<design>/v<version>_<PDK>/ anywhere under it. The pointer is "
            f"NOT broken and there is nothing to fix here: this check has no "
            f"subject until a cell is published. Read this as 'I looked and the "
            f"corpus is empty', never as 'nothing was wrong' and never as "
            f"'nobody told me where the corpus is'.")
    here = _REPO / "benchmark-data"
    if _has_cells(here):
        return PRESENT, here, ""
    return UNSET, None, SKIP_REASON


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
#:
#: Evaluated ONCE, at import, and the reason carried is the STATE's reason, not a
#: single string — so `unset` and `publishes_nothing` are two different skips in
#: the junit record and a reader can tell which happened without re-running.
#: BROKEN still raises here, which is deliberate: the exploit it closes is a
#: broken pointer being swallowed into a skip.
_STATE, _ROOT, _REASON = corpus_state()
if _STATE == BROKEN:
    raise CorpusPointerBroken(_REASON)
needs_corpus = pytest.mark.skipif(_STATE != PRESENT, reason=_REASON)
