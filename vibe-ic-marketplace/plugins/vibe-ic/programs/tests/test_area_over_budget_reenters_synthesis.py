"""A bounded area retry, and the measurement that says it is NOT the flow's edge.

`closed_loop_executable_coverage_check` publishes `EXECUTABLE = 0` over 18
`DECLARED_ONLY` edges: the flow declares them and nothing re-enters the fallback
step when the trigger fires. The area overflow is the one repair that needed no
candidate-rewrite executor:

  * the comparator exists            `area_total_vs_budget_check.py`
  * the runner already spawns it     `phase3_one_shot_runner.step_synth`
  * its trigger already blocks       `rc == 1 -> return StepResult(FAIL)`

What was missing was only the re-entry. This file proves the decision that
governs it, and the two readers it reads through.

AND THE PART THAT MATTERS MORE — THIS IS NOT THE FLOW'S 9 -> 1 EDGE, and the
census said so before anyone could talk themselves into it:

    CLC-ACTUATION-NOT-FALLBACK-REENTRY: edge 9 falls back to step 1, but its
    actuator calls step_synth; expected one of [step_rtl_gen]

9 -> 1 means go back to Spec-to-RTL. Re-running synthesis is a different edge.
The registration as edge 9 was withdrawn and `EXECUTABLE` stays 0. That
measurement is load-bearing and is pinned below, because a bounded retry whose
bound nobody can see is the timeout-as-verdict defect in another costume.

WHY THE UNDO IS SHAPED DIFFERENTLY FROM THE POST-ROUTE REPAIR'S. The repair can
decline to adopt by leaving files alone — its outputs sit beside the originals
under their own names. Re-synthesis cannot: it OVERWRITES the netlist. So this
loop declines by refusing the VERDICT — the step stays FAIL and says what the
retry measured, so nobody reads a relaxed-timing netlist as a repair that
worked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _adopt(before, after, budget):
    from phase3_one_shot_runner import area_retry_is_worth_adopting
    return area_retry_is_worth_adopting(before, after, budget)


def _area_loop_branch(width: int = 0) -> str:
    """The area-loop branch's own source, anchored at BOTH ends.

    THE WIDTH USED TO BE A HAND-TYPED CHARACTER COUNT (2400 / 3000 / 3200 /
    3600 / 5700) and every one of them was a hostage to the comment above the
    code. Registering this loop as flow edge 9 -> 9 added twenty lines of
    reasoning to that comment and FOUR of these tests went red at once — not one
    of them because the behaviour they guard had changed. A window measured in
    characters is asserting the prose length, which is the same defect as an
    evidence window cut by a fixed tail.

    So the end anchor is now STRUCTURAL: the branch ends where its enclosing
    `if` ends, and `_area_verdict = ` is the first statement after it at the
    outer indent. `width` is accepted and ignored so the call sites read the
    same; it is no longer a bound anyone has to maintain.

    Read whitespace-normalised because the sentences wrap across lines AND
    across adjacent string literals — a literal substring test would be
    asserting the line width rather than the behaviour.
    """
    del width  # kept for call-site compatibility; the window is anchored now
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    i = src.index("THE AREA LOOP, step 9 -> 9")
    j = src.index("_area_verdict = ", i)
    assert j > i, "the branch's closing anchor moved above its opening one"
    return " ".join(src[i:j].split())


# ── the adoption decision ───────────────────────────────────────────────────
def test_smaller_and_inside_the_budget_is_adopted():
    """The only shape that is a repair."""
    assert _adopt(1_800_000.0, 1_600_000.0, 1_690_000.0)


def test_smaller_but_still_over_budget_is_NOT_adopted():
    """The half that is easy to get wrong. A retry that shaves 3% off a netlist
    overflowing by 7% has not repaired anything, and adopting it would trade the
    design's timing target for a fit it did not achieve."""
    assert not _adopt(1_800_000.0, 1_750_000.0, 1_690_000.0)


def test_larger_but_inside_the_budget_is_NOT_adopted():
    """If a LARGER netlist fits, the first one fit too — so the trigger was
    wrong rather than the netlist, and adopting the slower one would be paying
    timing for nothing."""
    assert not _adopt(1_600_000.0, 1_650_000.0, 1_690_000.0)


def test_an_unmeasured_figure_is_never_an_improvement():
    """"We could not compare" and "it got better" are different facts. Treating
    the first as the second adopts a result nobody measured — the mistake the
    post-route repair made in the other direction, where two adjacent figures
    were never subtracted."""
    assert not _adopt(None, 1_500_000.0, 1_690_000.0)
    assert not _adopt(1_800_000.0, None, 1_690_000.0)


def test_no_declared_budget_means_no_adoption():
    """`die_area_budget_um` is null in 118 of 136 real runs. With no ceiling
    there is no fit to achieve, so there is nothing to adopt against."""
    assert not _adopt(1_800_000.0, 1_500_000.0, None)
    assert not _adopt(1_800_000.0, 1_500_000.0, 0)


# ── the readers, and that they delegate ─────────────────────────────────────
def _tree(tmp_path: Path, area, unit, budget):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth" / "stats.json").write_text(
        json.dumps({"chip_area": area, "chip_area_unit": unit,
                    "top_module": "t"}))
    if budget is not None:
        (tmp_path / "phase1" / "generated_docs"
         / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"die_area_budget_um": budget}))
    return tmp_path


def test_the_budget_is_read_through_the_comparator(tmp_path):
    """`1300x1300` is 1,690,000 um2, and the loop must get that from
    `area_total_vs_budget_check.read_ceiling` rather than parsing it again — the
    gate that decides the trigger and the loop that answers it have to read the
    SAME number from the SAME place, or the loop repairs against a budget the
    gate does not use."""
    from phase3_one_shot_runner import _area_budget_um2
    assert _area_budget_um2(_tree(tmp_path, 1.0, "um^2", "1300x1300")) == 1_690_000.0


def test_the_area_is_read_through_the_comparator(tmp_path):
    from phase3_one_shot_runner import _synth_chip_area
    assert _synth_chip_area(
        _tree(tmp_path, 1_690_000.0, "um^2", "1300x1300")) == 1_690_000.0


def test_a_figure_whose_unit_was_never_established_is_refused(tmp_path):
    """`read_areas` carries an unlabelled figure with `unit_established: False`
    rather than dropping it, so the refusal can name it. Comparing two areas
    whose units were never established produces a ratio with no meaning."""
    from phase3_one_shot_runner import _synth_chip_area
    t = _tree(tmp_path, 1_690_000.0,
              "cell-library area unit (as declared by the library)", "1300x1300")
    assert _synth_chip_area(t) is None


# ── the loop's bound and its default ────────────────────────────────────────
def test_the_relaxation_default_is_a_no_op():
    """At `period_relax=1.0` every yosys command is byte-identical to what it
    was, so a run that never overflows its die cannot tell this parameter
    exists."""
    import inspect
    from phase3_one_shot_runner import step_synth
    assert inspect.signature(step_synth).parameters["period_relax"].default == 1.0


def test_the_retry_cannot_re_enter_itself():
    """The recursion bound is the guard, not a counter: the retry runs at
    `period_relax != 1.0` and the re-entry is gated on `period_relax == 1.0`,
    so there is no budget to leak and no retry counter to tune."""
    branch = _area_loop_branch(3600)
    assert "if period_relax == 1.0:" in branch
    assert "period_relax=AREA_RETRY_PERIOD_RELAX" in branch


def test_a_retry_that_did_not_repair_keeps_the_step_FAILING():
    """Re-synthesis OVERWRITES the netlist, so declining to adopt cannot be
    done by leaving files alone. It is done by refusing the verdict — and the
    detail must say what the retry measured, so nobody reads a relaxed-timing
    netlist as a repair that worked."""
    branch = _area_loop_branch(5700)
    assert "AREA LOOP RAN AND DID NOT REPAIR" in branch
    assert "NOT adopted as a fix" in branch


# ── the measurement that says this is NOT the flow's 9 -> 1 edge ────────────
def test_the_branch_records_that_it_IS_the_flows_9_to_9_edge_and_why():
    """THE LOAD-BEARING HALF, and the reason this retry is honest rather than
    merely bounded.

    It used to assert the opposite, and correctly: while the flow said
    `fallback_to: 1` the census REFUSED to register this loop as edge 9, because
    9 -> 1 means re-enter Spec-to-RTL and this re-enters synthesis. The
    declaration has since moved to the step the actuator re-enters, so the
    branch now records that it IS the edge — and it keeps the old refusal
    verbatim, which is the part that matters: the refusal is the evidence that
    the TARGET followed the ACTUATOR, and not the other way round."""
    branch = _area_loop_branch(3200)
    assert "THIS IS THE FLOW'S EDGE 9 -> 9" in branch
    # the refusal that used to stand, kept so the direction of the fix is
    # readable from the code rather than only from a commit message
    assert "CLC-ACTUATION-NOT-FALLBACK-REENTRY" in branch
    assert "expected one of [step_rtl_gen]" in branch
    # ...and the anti-cheat, named at the site: the edge was NOT made reachable
    # by editing the trigger text.
    assert "NOT" in branch and "write a metric name into a trigger" in branch


def test_the_branch_records_that_rollback_is_not_claimed():
    """The tier stops at REMEASURED, and the reason is a property of this code:
    re-synthesis overwrites the first netlist before the comparison happens."""
    branch = _area_loop_branch(3200)
    assert "ROLLBACK IS NOT CLAIMED" in branch
    assert "OVERWRITTEN" in branch


def test_the_three_measurements_for_why_9_to_1_was_never_reachable_are_recorded():
    """A bounded retry whose bound nobody can see is the timeout-as-verdict
    defect in another costume. The claim "9 -> 1 cannot be closed today" is
    falsifiable only if the three measurements behind it travel with it. They
    are why the FALLBACK TARGET moved rather than the actuator, so they are
    still load-bearing after the move: no RTL
    producer reads an area budget, `step_rtl_gen` is deterministic, and the one
    remediation path takes two hint kinds and neither is area. Break any one of
    those and the conclusion changes — which is what makes it a measurement
    rather than an opinion."""
    branch = _area_loop_branch(3000)
    assert "deterministic_emit_chain.py" in branch
    assert "spec_artifact_registry.py" in branch
    assert "no hits" in branch
    assert "`step_rtl_gen` is deterministic" in branch
    assert "reserved_keyword_port_leak" in branch
    assert "port_mismatch_l9_vs_rtl" in branch
    # ...and the consequence, in the detector the RTL loop already has.
    assert "FAIL_RTL_REPAIR_INERT" in branch
