#!/usr/bin/env python3
"""R-0915-82 — an INCONCLUSIVE LEC record is not one state, and none of its
states is SKIP.

MEASURED, sha256 run16 (main c0dcb5e27, image 89a8fd72…, sky130A, the
R-0915-67 carry-save RTL). `reports/lec.json` said:

    verdict INCONCLUSIVE | compared_points 846 | unproven_points 481
    non_equivalent_points 0 | budget_exhausted false | exhausted_resource null
    progress_stalled false | induction_wall_kind "induction_depth"

i.e. the ladder ran to its LAST rung (`equiv_induct -seq 64`, the top of
`lec_run.LEC_LADDER`) in 8306 s of a 28800 s budget and did not close. The step
booked that SKIP. Then a re-entered run read the SAME kept record in 2 s,
printed the SAME sentence, booked the SAME SKIP, phase 2 reported
PASS_WITH_WAIVERS, and phase 3 measured DRC/LVS/STA sign-off on a netlist whose
equivalence to the RTL nobody had proven.

Two defects, pinned here:
  (1) INCONCLUSIVE -> SKIP was UNCONDITIONAL, on a docstring premise ("0 points
      compared") that the record itself contradicted.
  (2) a reused record was indistinguishable from a fresh proof in the step's
      own sentence, although `lec_run` records the reuse in full.

These tests drive the PURE functions with dicts. They are behaviour tests, not
text-presence tests: each asserts the STATUS a record earns, and the three
INCONCLUSIVE sentences are required to DIFFER from one another — a naming that
collapses is a naming that says nothing.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import design_one_shot_runner as dosr  # noqa: E402


#: The record sha256 run16 actually produced, field for field.
RUN16_UNCLOSED = {
    "verdict": "INCONCLUSIVE",
    "equivalent": False,
    "compared_points": 846,
    "unproven_points": 481,
    "non_equivalent_points": 0,
    "budget_exhausted": False,
    "exhausted_resource": None,
    "progress_stalled": False,
    "step_budget_exhausted": False,
    "step_budget_stopped_this_proof": False,
    "induction_wall_kind": "induction_depth",
    "execution_mode": "fresh-yosys-proof",
}

#: The state R-0915-48's backstop produces: the proof was CUT OFF.

#: The state the old docstring described: the miter judged nothing.
NOTHING_COMPARED = {
    "verdict": "INCONCLUSIVE", "equivalent": False,
    "compared_points": 0, "unproven_points": 0,
    "budget_exhausted": False, "exhausted_resource": None,
}

#: What `lec_run` wrote for run16 pass 2: a 2 s process that climbed no rung.




# ---------------------------------------------------------------------------
# (1) the three INCONCLUSIVE states, and none of them is SKIP
#
# EVERY assertion below is a BARE `assert` on purpose. pytest rewrites those and
# puts the COMPARED VALUES into the failure text, so a control run over the
# pre-fix tree reports `assert 'SKIP' == 'FAIL'` -- a value that was observed --
# rather than a bespoke message a reader (or `control_substance_check`) cannot
# tell apart from a symbol that simply was not there. unittest's assertEqual
# does not get rewritten, and that is exactly the difference between evidence
# and a claim about evidence.
# ---------------------------------------------------------------------------
































# ---------------------------------------------------------------------------
# (2) a verdict earned by an earlier run must say whose work it was
# ---------------------------------------------------------------------------














# ---------------------------------------------------------------------------
# (3) SECOND ORDER -- phase 3 must be able to grade the row this change emits
#
# `run_step11_dft_after_synth` republishes `step_dft_lec_chain`'s rows VERBATIM
# as `step11_<name>`. So the moment the LEC step can answer NOT_EXECUTED, that
# word reaches `_aggregate_verdict`, whose known set is `union(_TIERS.values())`
# and which REFUSES BY NAME anything outside it (vibe-ic#2153). Unclassified, a
# correction to ONE step would have turned every budget-stopped run's whole
# phase-3 verdict into `UNKNOWN_STATUS:` -- a fix acquiring a second defect one
# file away.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def p3():
    return pytest.importorskip("phase3_one_shot_runner")


def test_NOT_EXECUTED_is_inside_the_known_vocabulary(p3):
    plan = [p3.StepResult("pnr", "PASS"),
            p3.StepResult("step11_lec_equivalence", dosr.NOT_EXECUTED_STATUS,
                          reason_class=dosr.NOT_EXECUTED_REASON)]
    verdict = p3._aggregate_verdict(plan)
    assert not str(verdict).startswith("UNKNOWN_STATUS:")


def test_a_stopped_proof_does_not_block_phase3(p3):
    """R-0915-48 word for word: the backstop fires, the flow proceeds. The tier
    must be the disclosed-gap tier, not FAIL."""
    plan = [p3.StepResult("pnr", "PASS"),
            p3.StepResult("step11_lec_equivalence", dosr.NOT_EXECUTED_STATUS,
                          reason_class=dosr.NOT_EXECUTED_REASON)]
    # R-0915-85 — the disclosed-gap tier is `NOT_MEASURED(not_executed)`, and
    # that is the whole R-0915-48 sentence in one row: the proof was STOPPED,
    # so nothing was measured; it is not a FAIL, and it is not a waiver either
    # (nobody owns a row here). The run is off PASS and says why.
    assert p3._aggregate_verdict(plan) == "NOT_MEASURED"


def test_an_unclosed_ladder_DOES_block_phase3(p3):
    """THE OTHER DIRECTION. Classifying NOT_EXECUTED must not also let the FAIL
    through -- that would re-open the hole from the other side."""
    plan = [p3.StepResult("pnr", "PASS"),
            p3.StepResult("step11_lec_equivalence", "FAIL")]
    assert p3._aggregate_verdict(plan) == "FAIL"
