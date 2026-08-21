#!/usr/bin/env python3
"""An ALREADY_RED replay is UNMEASURABLE, not a failed mutation — vibe-ic#1432.

WHY THIS FILE EXISTS
====================
`matrix_mutation_ledger` replays each recorded mutation and asserts the witness
goes red. When the witness is ALREADY RED before the edit, the experiment did
not run — and the module knew that: `replay_artefact`'s docstring says "a
mutation against an already-red gate proves nothing and is reported ALREADY_RED,
never skipped", and `ReplayResult.verdict` already returned `ALREADY_RED`.

What was missing is that BOTH consumers scored it as a defect. `proved` and
`as_recorded` are False for an already-red pair exactly as they are for
`STAYED_GREEN`, so `test_lock2_...` reported *"the ledger says this edit reddens
the cell; re-running it says otherwise"* about a tree state. That is what batch
R1 read as a gate that lost its teeth.

`policy_direction_pin_check` already handles the identical situation the other
way and in the same words — it ABSTAINS when candidate tests are red before any
flip, "so a kill proves nothing about this call site". One instrument abstained;
this one scored it as a defect.

THE THREE THINGS THIS MUST NOT BECOME (from #1432), each guarded below:
  1. not a silent skip  — the pairs are counted, disclosed and ratcheted;
  2. not a re-record    — no ledger entry may declare ALREADY_RED as expected;
  3. not a relaxation   — a genuine STAYED_GREEN is still a failure.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent


def _ledger():
    path = _PLUGIN / "programs" / "matrix_mutation_ledger.py"
    spec = importlib.util.spec_from_file_location("_ledger_1432", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ledger_1432"] = mod
    spec.loader.exec_module(mod)
    return mod


L = _ledger()


def _result(**kw):
    base = dict(mutation="X", dim=3, step_id="15", applied=True,
                baseline_rc=0, mutant_rc=1, signal_seen=True, detail="")
    base.update(kw)
    return L.ReplayResult(**base)


def test_an_already_red_witness_is_unmeasurable_not_a_failed_mutation():
    """The regression itself: baseline red -> UNMEASURABLE, not "stayed green"."""
    r = _result(baseline_rc=1, mutant_rc=1)
    assert r.verdict == L.ALREADY_RED
    assert r.unmeasurable is True
    assert r.proved is False, (
        "an already-red pair must not count as proof — nothing was demonstrated")


def test_a_gate_that_genuinely_stops_catching_is_STILL_a_failure():
    """The load-bearing guard: this must not become a way to excuse a lost gate.

    Baseline GREEN and the mutant stays green is a finding about the GATE, and
    it must survive #1432 untouched.
    """
    r = _result(baseline_rc=0, mutant_rc=0, signal_seen=False)
    assert r.verdict == "STAYED_GREEN"
    assert r.unmeasurable is False, (
        "a gate that stopped catching was classified as unmeasurable; that is "
        "exactly the excuse #1432 must not create")
    assert r.proved is False
    assert r.as_recorded is False, (
        "a REDDENED entry whose replay stayed green must still fail the grid")


def test_a_reddened_pair_is_unaffected():
    r = _result()
    assert r.verdict == "REDDENED"
    assert r.unmeasurable is False
    assert r.proved is True and r.as_recorded is True


def test_a_recorded_STAYED_GREEN_entry_still_pins_the_day_the_gate_learns():
    """The ARTEFACT_MUTATION channel keeps its meaning.

    An entry that RECORDS `STAYED_GREEN` is a published finding that the gate
    does not move. #1432 must not disturb it: the day the gate learns to notice,
    the verdict stops matching and the grid says so.
    """
    r = _result(expected=L.CANNOT_REDDEN, baseline_rc=0, mutant_rc=0,
                signal_seen=False)
    assert r.as_recorded is True and r.unmeasurable is False
    learned = _result(expected=L.CANNOT_REDDEN)
    assert learned.as_recorded is False, (
        "the gate started catching and the record did not have to say so")


def test_ALREADY_RED_is_not_a_recordable_expectation():
    """#1432's "not a re-record": no entry may declare itself unmeasurable."""
    entries = list(L.MUTATIONS) + list(getattr(L, "ARTEFACT_MUTATIONS", ()))
    declared = {getattr(m, "expected", L.REDDENS) for m in entries}
    assert declared, "no ledger entries to check"
    assert L.ALREADY_RED not in declared, (
        "a ledger entry declares ALREADY_RED as its expected verdict — that "
        "would re-record a measured gap as an unmeasurable one, which is how "
        "the evidence of a regression gets deleted")


def test_the_default_mode_ceiling_is_zero_and_that_is_measured():
    """`witness` = 0 is why the default mode is trustworthy.

    Every witness is green on clean main. Raising this is never the right fix:
    it would mean a witness went red, and a red witness hides whatever its
    mutation would have proved.
    """
    from test_matrix_mutation_ledger import UNMEASURABLE_CEILING
    assert UNMEASURABLE_CEILING["witness"] == 0
    assert UNMEASURABLE_CEILING["all"] >= 0
