#!/usr/bin/env python3
"""vibe-ic#440 — the published-evidence index, and the gate that keeps it honest.

WHAT IS PINNED
--------------
The index's whole value is that a reader can trust it without opening a JSON
per cell, and the only thing that can make it trustworthy is a gate that FAILS
when it stops describing the tree. So the load-bearing tests here are the
MUTATION CONTROLS: change a cell's audit verdict, leave the index alone, and
`--check` must go red.

The repo has already run the experiment for the ungated version.
`benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md` is hand-maintained, and all
three of its citations for the three cells that DID converge point at
directories that do not exist — the folders were renamed and the table was
not. `test_campaign_status_citations_are_stale_which_is_why_this_is_generated`
pins that as the measured justification rather than an assertion.

REAL-DATA CONTROL
-----------------
A gate justified only by its author's fixture has never judged a production
artefact. `test_real_tree_*` build the index from the actual published tree and
mutate a REAL audit verdict, so defect-in -> FAIL and defect-out -> PASS is
demonstrated on the same artefacts CI judges.

WHERE THAT TREE IS NOW
----------------------
The published cells moved to https://github.com/vibeic/benchmark-data. This
checkout still carries `benchmark-data/` — it holds the design INPUTS — so
`<repo>/benchmark-data/ic` is still a directory, and the old "not checked out"
guard therefore never fired; the four real-data tests below simply went red
about a corpus that had moved. `_published_corpus` answers the question the guard meant
to ask ("is a published CELL readable here?"), and `@needs_corpus` renders "I
could not look" as a SKIP naming the corpus rather than as a defect claim —
the same rule vibe-ic#1357 established for an absent TOOL. Where the corpus IS
readable these four run exactly as before and can still fail.

Fixture cells use deliberately synthetic names (`unit_one`, `unit_two/v0.0.1_procX`)
— no IC, PDK, vendor or SKU literal, per `source_chip_agnostic_check`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "benchmark_evidence_index.py"

sys.path.insert(0, str(PROGRAMS))

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─────────────────────────────────────────────────────────────────────
# Fixture construction
# ─────────────────────────────────────────────────────────────────────







# ─────────────────────────────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────────────────────────────







# ─────────────────────────────────────────────────────────────────────
# The contradiction the index exists to surface
# ─────────────────────────────────────────────────────────────────────







# ─────────────────────────────────────────────────────────────────────
# MUTATION CONTROLS — the gate must actually fire
# ─────────────────────────────────────────────────────────────────────













# ─────────────────────────────────────────────────────────────────────
# The curated sidecar
# ─────────────────────────────────────────────────────────────────────









# ─────────────────────────────────────────────────────────────────────
# Determinism — byte-equality is the mechanism, so nothing may drift
# ─────────────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────────────
# REAL-DATA controls — on the tree CI actually judges
# ─────────────────────────────────────────────────────────────────────











@needs_corpus
def test_campaign_status_citations_are_stale_which_is_why_this_is_generated():
    """The measured justification for generating rather than writing.

    `BENCHMARK_IC_CAMPAIGN_STATUS.md` is the hand-maintained equivalent. Its
    rows for the converged cells cite `RESULT.md` paths under directory names
    that no longer exist. Pinned as a fact, not an opinion — if someone repairs
    that file, this test tells them to reconsider whether the generated index
    is still needed rather than letting the claim rot in a docstring.

    Needs the corpus even though it was GREEN without it, and that is the whole
    point: with no published cells every citation dangles, so the assertion
    "the hand-maintained table has rotted" passes for a reason that says nothing
    about the table. A pass produced by having nothing to look at is the exact
    false certificate this file exists to prevent.
    """
    root = corpus_root()
    status = root / "BENCHMARK_IC_CAMPAIGN_STATUS.md"
    if not status.is_file():
        pytest.skip("campaign status not checked out")
    import re
    cited = re.findall(r"`(ic/[A-Za-z0-9_./-]+\.md)`", status.read_text())
    assert cited, "expected the hand-maintained table to cite cell paths"
    dead = [c for c in cited if not (root / c).is_file()]
    assert dead, ("BENCHMARK_IC_CAMPAIGN_STATUS.md citations now all resolve; "
                  "re-read whether the generated index is still the answer")
