"""The first closed-loop edge that actually re-enters, and its undo.

`closed_loop_executable_coverage_check` publishes `EXECUTABLE = 0` over 18
`DECLARED_ONLY` edges: the flow declares them and nothing re-enters the fallback
step when the trigger fires. Step 9 -> 1 (area over the declared die) is the one
that needed no candidate-rewrite executor:

  * the comparator exists            `area_total_vs_budget_check.py`
  * the runner already spawns it     `phase3_one_shot_runner.step_synth`
  * its trigger already blocks       `rc == 1 -> return StepResult(FAIL)`

What was missing was only the re-entry. This file proves the decision that
governs it, and the two readers it reads through.

WHY THE UNDO IS SHAPED DIFFERENTLY FROM THE ECO'S. The ECO can decline to adopt
by leaving files alone — its outputs sit beside the originals under their own
names. Re-synthesis cannot: it OVERWRITES the netlist. So this loop declines by
refusing the VERDICT — the step stays FAIL and says what the retry measured, so
nobody reads a relaxed-timing netlist as a repair that worked.
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
    ECO made in the other direction, where two adjacent figures were never
    subtracted."""
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
    so there is no budget to leak and no `--max-eco` to tune."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    i = src.index("THE AREA LOOP, step 9 -> 1")
    branch = src[i:i + 2600]
    assert "if period_relax == 1.0:" in branch
    assert "period_relax=AREA_RETRY_PERIOD_RELAX" in branch


def test_a_retry_that_did_not_repair_keeps_the_step_FAILING():
    """Re-synthesis OVERWRITES the netlist, so declining to adopt cannot be
    done by leaving files alone. It is done by refusing the verdict — and the
    detail must say what the retry measured, so nobody reads a relaxed-timing
    netlist as a repair that worked."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    i = src.index("THE AREA LOOP, step 9 -> 1")
    # Wide enough to reach the not-adopted arm at the end of the branch;
    # bounded so it cannot drift into an unrelated step.
    branch = " ".join(src[i:i + 4200].split())
    assert "AREA LOOP RAN AND DID NOT REPAIR" in branch
    assert "NOT adopted as a fix" in branch
