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

AND THE REFUSAL GREW A FOURTH CASE IT DID NOT HAVE (vibe-ic#1764, one layer down)
================================================================================
`corpus_root` named THREE causes for "you set the pointer and there are no cells" —
the name is wrong, the clone failed, the fetch step did nothing — and refused. On
2026-08-20 a fourth appeared that is none of them: the pointer is right, the clone
succeeded, and the published corpus genuinely holds zero cells because the publisher
withdrew all four of them. The refusal then closes by advising the reader to *point it
at a clone of vibeic/benchmark-data* — which is the action that produced it.

That is the same defect `routed_def_corpus.py` separates into rc 0 / rc 3 at the
producer, surviving here in the test helper. An index that was READ and holds none is
a MEASUREMENT; a path that is not a corpus is the ABSENCE of one, and they must not
share an outcome or a sentence.

MEASURED on a clean `a4caccefe` worktree with the pointer bound at a real
`git clone` of `vibeic/benchmark-data` @ `3b58ccd42` (6929 blobs, 9 designs under
`ic/`, **0** cell directories, **0** `.def` blobs at any path):

    pointer at a corpus carrying one cell  ->  1345 tests collected, 0 errors
    pointer at the real published corpus   ->    52 tests collected, 52 errors

52 of the 55 importing modules died AT IMPORT, so 1293 tests went dark — and most of
them have no published cell as their subject; they were collateral of the module-level
`needs_corpus` evaluation below. A correct pointer must not switch off the suite.

WHAT SEPARATES THE TWO, AND WHY IT IS NOT THE LOOSENING THIS MODULE FORBIDS
==========================================================================
The obvious edit — return None whenever there are no cells — is exactly the
`29 passed, 2 skipped` exploit reinstated, so it is not taken. What is taken is a
POSITIVE identification of the tree as the published corpus, which no accident
produces: the publishing contract at its root AND the `ic/` root cells live under.

    set + not a corpus (missing path, empty dir, dead clone) -> raise.  UNCHANGED.
    set + IS the corpus + it carries cells                   -> the path. UNCHANGED.
    set + IS the corpus + its cell population is 0           -> skip, SAYING SO. NEW.

The third row is a measurement of zero and its skip reason states the measurement, so
it can never be read as the second row's "I could not look". A mistyped path, a failed
clone and a no-op fetch step all still land in the first row: none of them leaves a
tree carrying `PUBLISHING.md` beside an `ic/` directory.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

import pytest

#: Where a caller may point us at a clone of `vibeic/benchmark-data`.
CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"

#: The publishing contract, at the ROOT of the corpus tree. It is what tells this
#: module what a cell IS (`ic/<IC>/v<version>_<PDK>/`, quoted in `_has_cells`), so a
#: tree that carries it is a tree that has declared itself the publisher of cells.
#: Used ONLY to tell "this is the corpus and it holds none" apart from "this is not
#: the corpus" — never to decide that a cell exists.
CORPUS_CONTRACT = "PUBLISHING.md"

#: The three answers `corpus_state` gives. Collapsing any two of them is the defect,
#: exactly as in `programs/_corpus_location.py` and `tools/ci/routed_def_corpus.py`.
PRESENT = "present"                #: the corpus was read and it carries cells
MEASURED_EMPTY = "measured-empty"  #: the corpus was read and it carries none
NOT_OFFERED = "not-offered"        #: nobody named a corpus and this repo has none

#: OFF BY ONE, BOTH OF THEM, until this comment was written. `parents[1]` from
#: `programs/tests/` is `programs/`, not the plugin, so `_REPO` resolved to
#: `vibe-ic-marketplace/` and the repo-local branch of `corpus_root()` looked
#: for `vibe-ic-marketplace/benchmark-data` — a path this repository has never
#: had. The error was INERT and therefore invisible: the corpus left the tree at
#: `c5d7f2d00`, so the branch that could not find it was also the branch with
#: nothing to find. It falsified this module's own promise that "a checkout that
#: still carries cells" runs every check as before; such a checkout would have
#: been reported as having no corpus at all.
_PLUGIN = Path(__file__).resolve().parents[2]
_REPO = _PLUGIN.parents[2]


class CorpusPointerBroken(RuntimeError):
    """`VIBE_IC_BENCHMARK_DATA` was set and there is nothing readable there."""


def is_published_corpus(root: Path) -> bool:
    """Does `root` IDENTIFY ITSELF as the published corpus, cells or no cells?

    This answers a different question from :func:`_has_cells`, and the whole
    fourth-state repair rests on the difference: `_has_cells` asks "is there
    anything to examine", this asks "is this the tree that would carry it".

    THE TEST IS DELIBERATELY POSITIVE AND DELIBERATELY NOT INFERRED FROM ABSENCE.
    Every accident this module exists to refuse — a mistyped path, a directory
    that was never populated, a `git clone` that died, a CI fetch step that did
    nothing — produces a tree that carries NEITHER the publishing contract NOR an
    `ic/` root. None of them can reach the measured-empty answer.

    `ic/` is required as well as the contract, and refusing a tree that has the
    contract without it is the honest outcome rather than a gap: a cell is defined
    as `ic/<design>/v<version>_<PDK>/`, so a tree with no `ic/` cannot be measured
    for cells at all, and calling it "measured empty" would claim a measurement
    over a shape that is not there.

    Git is NOT required. This module walks the filesystem rather than an index —
    unlike `_corpus_location.not_a_checkout_reason`, whose callers read
    `git ls-files` and must refuse a loose directory — so an archive export of the
    corpus is a perfectly readable corpus here and refusing it would be wrong.
    """
    return (root / CORPUS_CONTRACT).is_file() and (root / "ic").is_dir()


#: Cell CONTENTS as git's index spells them: one design level, a cell directory
#: whose name starts with `v`, anything beneath. `:(glob)` magic is required —
#: without it a bare `*` in a git pathspec matches `/` too, and `ic/*/v*` would
#: count `ic/<design>/verification/...` as a published cell.
_INDEX_CELL_PATHSPEC = ":(glob)ic/*/v*/**"


def _index_publishes_cells(root: Path) -> Optional[bool]:
    """Does git's INDEX under `root` carry published cells? None = cannot ask.

    THE WORKING TREE AND THE INDEX CAN DISAGREE, AND THE DIFFERENCE IS A STATE.
    :func:`_has_cells` walks the filesystem, so a corpus clone whose cells were
    deleted, half-checked-out, or never materialised looks identical to a corpus
    that publishes none. MEASURED on a checkout of the publisher at `146d665`
    with `ic/*/v*` removed from the working tree: **0** cells on disk, **1384**
    cell files still in the index. Calling that "the corpus publishes 0 cells"
    is a false measurement, and it is the loosening this module exists to refuse.

    None — not False — when git cannot be asked, because git is deliberately not
    required here (an archive export of the corpus is a readable corpus for these
    tests). The caller treats None as "no contradiction available", which leaves
    the filesystem answer standing rather than inventing one.
    """
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", _INDEX_CELL_PATHSPEC],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0:
        return None
    return bool(probe.stdout.strip())


def corpus_state() -> Tuple[str, Optional[Path]]:
    """`(state, root)` — which of the THREE answers applies, and the path if any.

    THREE STATES, AND COLLAPSING ANY TWO OF THEM IS THE DEFECT
    ==========================================================
    Nobody set the pointer and the repo has no cells
        -> (:data:`NOT_OFFERED`, None). Honest: no corpus was offered, so a check
           over it skips, and :data:`SKIP_REASON` says it could not look.

    Somebody SET the pointer at something that is not the corpus
        -> raise. They named a corpus. The name is wrong, or the clone failed, or
           the CI step that was meant to fetch it did nothing. Returning None here
           renders "your path is broken" as "there is no corpus", and every corpus
           check goes green-by-skip.

    That path was REAL, not hypothetical:

        VIBE_IC_BENCHMARK_DATA=<empty dir> pytest ... -> 29 passed, 2 skipped

    A mistyped path, a failed clone, or a no-op fetch step turned the whole set
    green. An adversarial review found it, and it found it because this module's
    docstring claimed a test pinned the property while no such test existed. Both
    are fixed: the pointer now refuses, and the test is written below the module
    it guards (`test_published_corpus_helper.py`).

    Somebody set the pointer at the corpus and the corpus publishes no cell
        -> (:data:`MEASURED_EMPTY`, None). NEW, and it is the row that was missing.
           The tree was OPENED and its cell population is 0. That is a measurement,
           it is not a broken configuration, and it gets :data:`MEASURED_EMPTY_REASON`
           rather than :data:`SKIP_REASON` so a reader is never told the suite could
           not look at something it did look at.

    None of the three is a PASS. Two of them do not run the check at all; what the
    fourth-state repair changes is WHICH SENTENCE the reader gets, and that a
    correct pointer stops killing collection for modules whose subject is not a
    published cell.
    """
    env = os.environ.get(CORPUS_ENV)
    if env:
        p = Path(env)
        if _has_cells(p):
            return PRESENT, p
        if is_published_corpus(p):
            # READ, not merely looked for. Do not launder this into NOT_OFFERED:
            # the two get different reasons precisely so they stay distinguishable.
            if _index_publishes_cells(p):
                raise CorpusPointerBroken(
                    f"{CORPUS_ENV}={env!r} IS the published corpus, but its "
                    f"working tree carries no cell under "
                    f"ic/<design>/v<version>_<PDK>/ while git's index still "
                    f"tracks some. The checkout is incomplete or damaged — a "
                    f"half-finished clone, an interrupted checkout, or files "
                    f"removed by hand. This is NOT a corpus that publishes "
                    f"nothing: it publishes cells you do not have. Restore the "
                    f"working tree (`git -C {env} checkout -- ic`) or re-clone.")
            return MEASURED_EMPTY, None
        raise CorpusPointerBroken(
            f"{CORPUS_ENV}={env!r} names a corpus with no published cell under "
            f"ic/<design>/v<version>_<PDK>/ "
            f"({'the path does not exist' if not p.exists() else 'the path exists but is empty of cells'}). "
            f"This is NOT the same as having no corpus: you said where it is. "
            f"Unset {CORPUS_ENV} to run these checks as skipped, or point it at a "
            f"clone of vibeic/benchmark-data. "
            f"(It is not the published corpus either: a tree that IS the corpus "
            f"carries {CORPUS_CONTRACT} beside an ic/ directory and would have been "
            f"reported as a measured-empty corpus rather than a broken pointer.)"
        )
    here = _REPO / "benchmark-data"
    if _has_cells(here):
        return PRESENT, here
    if is_published_corpus(here):
        if _index_publishes_cells(here):
            raise CorpusPointerBroken(
                f"{here} IS the published corpus, but its working tree carries "
                f"no cell while git's index still tracks some — the checkout is "
                f"incomplete or damaged. It publishes cells this tree does not "
                f"have, which is not the same as publishing none.")
        return MEASURED_EMPTY, None
    return NOT_OFFERED, None


def corpus_root() -> Optional[Path]:
    """The directory holding published cells, or None when there is no cell to read.

    Kept as the one-value entry point every caller already uses. It cannot tell
    NOT_OFFERED from MEASURED_EMPTY — both have no cell to hand back — which is
    why :func:`corpus_state` exists and why the skip reason is chosen from the
    state and not from this return value.
    """
    return corpus_state()[1]


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


def named_cell(*parts: str) -> Optional[Path]:
    """One SPECIFICALLY NAMED run tree under the resolved corpus, or None.

    `cell_dirs()` answers "what published cells are here"; this answers "is THIS
    one here", which is the question a check with a recorded subject asks. A
    ratchet that re-runs the attacks it recorded names its cell, its donor and
    its older run, and each is a separate presence question — a donor that went
    away and a cell that went away are not the same fact and must not share one
    boolean.

    WHY THIS IS NOT `corpus_root() / "ic" / ...` AT THE CALL SITE. It is exactly
    that, and the point is that it is written ONCE. The 63x8 adversarial
    ratchet's test module spelled it `REPO / "benchmark-data" / "ic"` inline
    instead, and when the corpus moved out of this repository at `c5d7f2d00`
    that spelling could no longer resolve on ANY host: the whole ratchet went to
    a silent skip with `VIBE_IC_BENCHMARK_DATA` set and readable, and its
    thirteen recorded findings stopped being adjudicated in either direction.
    The program it guards had written the failure mode down in advance — "a
    corpus prune would silently close all thirteen and the ratchet would be
    measuring the publication schedule instead of the gates" — and then the
    prune happened one layer below where that sentence could act.

    The module is deliberately NOT named here in full. Its own
    `test_the_unwired_state_is_disclosed_or_gone` treats any file in the plugin
    tree that contains the program's identifier as evidence the program is
    WIRED, so a prose mention from this helper would be read as a caller and
    fail a disclosure test on a docstring.

    A run tree is NOT required to be a `v<version>_<PDK>` cell here. `_has_cells`
    asks that of the corpus as a whole because PUBLISHING.md defines what a
    corpus contains; a donor named by a recorded finding is whatever that finding
    named, and re-spelling the publishing contract at this level would refuse the
    `clean_run_*` trees the recorded attacks actually used.
    """
    root = corpus_root()
    if root is None:
        return None
    p = root.joinpath("ic", *parts)
    return p if p.is_dir() else None


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

#: The OTHER reason a corpus check does not run, and it is not the one above.
#: The corpus WAS read; it publishes no cell. Written separately, and asserted
#: separately, because one sentence for two states is the defect this module and
#: `tools/ci/routed_def_corpus.py` were both repaired for.
MEASURED_EMPTY_REASON = (
    f"{CORPUS_ENV} names the published benchmark corpus and it was READ — it "
    "publishes 0 cells under ic/<design>/v<version>_<PDK>/, so this check has no "
    "published cell to examine. This is a MEASUREMENT of zero, not 'I could not "
    "look', and it is not a pass: nothing was verified about any cell. The "
    "pointer is correct; the corpus is empty."
)


def skip_reason() -> str:
    """The sentence for whichever non-running state applies, chosen by state.

    `SKIP_REASON` is still exported unchanged — the suite greps for it — but a
    measured-empty corpus must never be described with it, because it says the
    check "could not look" at a corpus that was opened and counted.
    """
    return (MEASURED_EMPTY_REASON if corpus_state()[0] == MEASURED_EMPTY
            else SKIP_REASON)


#: Evaluated ONCE at import, because that is when `needs_corpus` is built.
_STATE, _ROOT = corpus_state()

if _STATE == MEASURED_EMPTY:
    # Said out loud as well as in the skip reason. A reader of the log sees the
    # measurement even without `-rs`, and it is the line that distinguishes a
    # correct pointer from the broken one this module used to report instead.
    print(f"[_published_corpus] MEASURED EMPTY: {os.environ.get(CORPUS_ENV)} IS "
          f"the published corpus ({CORPUS_CONTRACT} beside ic/) and it publishes "
          f"0 cells. Corpus checks will SKIP over a counted zero, not over an "
          f"unreadable tree.", file=sys.stderr)

#: Apply to any test whose subject is a PUBLISHED CELL rather than plugin behaviour.
needs_corpus = pytest.mark.skipif(_ROOT is None, reason=skip_reason())
