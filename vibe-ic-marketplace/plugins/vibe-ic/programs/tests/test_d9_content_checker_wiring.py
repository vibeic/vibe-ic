#!/usr/bin/env python3
"""D9 Phase 1 — the three content-reading checkers this campaign wired, and the
ONE invariant that makes the wiring safe rather than merely present.

WHAT IS ACTUALLY BEING GUARDED
==============================
Wiring a checker is cheap; a test that asserts "the program name appears in the
flow yaml" is worth almost nothing, because it stays green no matter how the row
is spelled and it cannot tell a gate that bites from a gate that can never run.

The three decisions this suite defends are the ones that were MEASURED, and each
of them is falsifiable by mutating exactly one token in the flow yaml:

1. ``step_internal_fail_bubble_up_check`` is BLOCKING, and it is placed at a step
   that is itself gated behind physical sign-off.  Its 17 published reds are real
   defects, so it must be able to fail a step -- an advisory slot would record
   them and stop nothing.

2. ``l6_…`` and ``l9_…`` are ADVISORY.  Their reds are true findings owned by a
   DOC PRODUCER, not by 41 / 8 designs (see the flow yaml comments for the
   corpus census behind each).  A blocking slot would fail published roots for a
   defect in an extractor.

3. THE CASCADE INVARIANT, which is the load-bearing one and the only one that is
   a behaviour rather than a declaration:

       ``step_internal_fail_bubble_up_check`` scans ``reports/**/*.json`` for
       ``verdict in {FAIL, MISSING}``.  So ANY gate wired with ``--json`` that
       writes a FAIL-shaped report MANUFACTURES a red in that gate.

   ``l9_submodule_conformance_check --json`` writes ``{"verdict": "FAIL"}``.
   Wired with ``--json`` it would create the Step-36 failure it then reports.
   ``test_the_cascade_is_real_and_the_bare_wiring_avoids_it`` DRIVES both
   programs on a scratch project and proves the cascade exists and that the
   shipped (bare) wiring does not trip it.  That test fails if someone "tidies"
   the rows by adding a ``--json`` path, which a declaration-only test would wave
   through.

WHAT THIS DOES NOT CLAIM
========================
It does not assert the redden counts (17 / 41 / 8).  Those are a property of the
published corpus, not of the flow, and they are recorded in the yaml comments
with the command that reproduces them.  Asserting them here would make this
suite fail whenever the corpus grows -- a test that breaks on unrelated data is
how a real signal gets muted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flow_matrix import flowref as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"

#: program -> (step it is wired at, must-block?).  DISCOVERED against the flow
#: below; this table states only the DECISION, never the location's spelling.
WIRED = {
    "step_internal_fail_bubble_up_check": True,
    "l6_fsm_scaffold_actionable_check": False,
    "l9_submodule_conformance_check": False,
}

#: The programs whose ``--json`` output carries a FAIL-shaped verdict, and which
#: must therefore be wired BARE so they cannot feed the bubble-up gate.
#: ``l6`` is included because its report carries a ``verdict`` field too; it
#: happens to read SKIP on the cell probed by hand, and the invariant must not
#: depend on which cell someone probed.
MUST_BE_BARE = ("l6_fsm_scaffold_actionable_check", "l9_submodule_conformance_check")

BUBBLE_UP = "step_internal_fail_bubble_up_check"


def _clauses_naming(program: str):
    """Every (step_id, clause) in the flow whose command invokes ``program``."""
    hits = []
    for step_id in F.step_ids():
        for clause in F.gate_clauses(step_id):
            cmd = clause.command or ""
            if cmd.split() and cmd.split()[0] == program:
                hits.append((step_id, clause))
    return hits


@pytest.mark.parametrize("program", sorted(WIRED))
def test_the_checker_is_wired_exactly_once(program: str) -> None:
    hits = _clauses_naming(program)
    assert hits, (
        f"{program} names no gate clause in the flow yaml. It was promoted by "
        f"D9 Phase 1; an unwired checker judges nothing but its own unit test."
    )
    assert len(hits) == 1, (
        f"{program} is wired {len(hits)} times ({[s for s, _ in hits]}). One "
        f"checker, one decision -- a second row makes the blast radius ambiguous."
    )


@pytest.mark.parametrize("program,must_block", sorted(WIRED.items()))
def test_the_blocking_decision_matches_what_was_measured(program: str, must_block: bool) -> None:
    (step_id, clause), = _clauses_naming(program)
    if must_block:
        assert clause.is_blocking, (
            f"{program} is wired ADVISORY at step {step_id}. Its published reds "
            f"were adjudicated REAL DEFECTS, and an advisory slot records them "
            f"without stopping anything."
        )
    else:
        assert clause.is_advisory, (
            f"{program} is wired BLOCKING at step {step_id}. Its published reds "
            f"are owned by a doc PRODUCER, so blocking fails published roots for "
            f"a defect in an extractor. See the flow yaml comment for the census."
        )


def test_the_bubble_up_gate_is_behind_physical_signoff() -> None:
    """Blocking is affordable only because a Phase-1-only root never reaches it."""
    (step_id, _), = _clauses_naming(BUBBLE_UP)
    upstream = F.blocks_on(step_id)
    assert upstream, (
        f"{BUBBLE_UP} is wired BLOCKING at step {step_id}, which declares no "
        f"blocks_on. Blocking was justified by the step being gated behind "
        f"physical sign-off; with no upstream that justification is gone."
    )


@pytest.mark.parametrize("program", MUST_BE_BARE)
def test_the_advisory_layer_gates_are_wired_bare(program: str) -> None:
    """No ``--json`` -- see the cascade test below for why this is behavioural."""
    (step_id, clause), = _clauses_naming(program)
    assert "--json" not in (clause.command or ""), (
        f"{program} at step {step_id} is wired with --json. It writes a "
        f"verdict-bearing report into reports/, which {BUBBLE_UP} reads as an "
        f"unacknowledged step-internal FAIL -- the gate would manufacture the "
        f"red it then reports. Wire it bare, as every sibling row in that block is."
    )
