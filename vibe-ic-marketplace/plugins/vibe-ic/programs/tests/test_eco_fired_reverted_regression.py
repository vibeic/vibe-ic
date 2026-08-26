"""The repository's only rollback, and until now nothing proved it works.

`closed_loop_executable_coverage_check` publishes `ROLLBACK_PROVEN = 0` over 21
declared closed-loop edges, and names why in as many words:

    The step-32 ECO DOES implement a rollback — `eco_fired_reverted_regression`,
    which retains the pre-ECO artefacts — and

        grep -rn 'eco_fired_reverted_regression' programs/tests/  ->  no files

    so nothing proves it works. `test_eco_loop_audit.py` tests the AUDIT of an
    already-regressed record, which is a different claim. An unproven rollback
    is exactly the thing this census exists to keep out of a success report.

This file is that proof. It exercises the DECISION the branch turns on, not a
re-implementation of it: `eco_result_is_a_regression` is the expression that was
inline in `step_canonicalize_artefacts` and now has an address.

WHY A REVERT THAT MOVES NO FILES IS STILL A REVERT. The branch does not restore
anything — it declines to ADOPT. "The ECO outputs stay on disk under their own
names for debug; they are NOT adopted as the shipped artefacts." Not adopting a
worse result is the same guarantee as restoring a better one and it cannot fail
half-way, which is why it is the right shape here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _regressed(delta, comparable):
    from phase3_one_shot_runner import eco_result_is_a_regression
    return eco_result_is_a_regression(delta, comparable)


# ── the undo fires when the repair made things worse ────────────────────────
def test_a_measured_regression_triggers_the_revert():
    """The instance this guard was written for, in its own numbers: a real cell
    went setup -0.68 -> -8.92 ns, a 12x regression, and the record said `pass`
    because the two figures sat adjacent and were never SUBTRACTED."""
    assert _regressed(-8.92 - (-0.68), True)


def test_a_one_picosecond_regression_still_counts():
    """The epsilon is one picosecond — below any real repair effect, above
    float noise on nanosecond quantities. A repair that loses measurable time
    is a repair that lost time."""
    assert _regressed(-2e-9, True)


# ── and does NOT fire otherwise ─────────────────────────────────────────────
def test_an_improvement_is_adopted():
    """The other direction matters as much: a rollback that fires on a good
    result throws away the repair it was asked for."""
    assert not _regressed(+8.24, True)


def test_a_zero_delta_is_not_a_regression():
    """An ECO that changed nothing changed nothing."""
    assert not _regressed(0.0, True)


def test_float_noise_below_a_picosecond_is_not_a_regression():
    assert not _regressed(-1e-12, True)


def test_an_unmeasured_delta_is_not_a_regression():
    """"We could not compare" and "it got worse" are different facts. Treating
    the first as the second would revert on missing evidence."""
    assert not _regressed(None, True)


# ── the guard that is easiest to get wrong ──────────────────────────────────
def test_a_delta_across_DIFFERENT_parasitics_is_not_charged_to_the_ECO():
    """The subtle half. When the before and after were measured on different
    parasitics the number is not a repair delta at all — an ECO that changed
    NOTHING was recorded at `eco_setup_delta_ns = -8.220` and failed for a
    regression it never made. Charging that to the ECO reverts a repair that
    was never applied, and the epsilon cannot tell the two apart because the
    magnitude is real; only the COMPARABILITY flag can."""
    assert not _regressed(-8.220, False)
    # ...and the same magnitude IS a regression once the two sides are
    # comparable, so the flag is what decides, not the number.
    assert _regressed(-8.220, True)


def test_the_two_guards_are_independent():
    """Pinned as a truth table so a future edit cannot collapse one guard into
    the other and still look correct on the common cases."""
    table = {
        (-1.0, True): True,
        (-1.0, False): False,
        (+1.0, True): False,
        (+1.0, False): False,
        (None, True): False,
        (None, False): False,
    }
    for (delta, comparable), want in table.items():
        assert _regressed(delta, comparable) is want, (delta, comparable)


# ── the branch this decision drives ─────────────────────────────────────────
def test_the_runner_still_wires_the_decision_to_the_revert_branch():
    """The test above proves a FUNCTION. This one proves the function is still
    what the rollback branch consults — otherwise the proof could go on passing
    while the branch reads something else."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    assert "_eco_regressed = eco_result_is_a_regression(" in src, (
        "the revert branch no longer consults the proven decision")
    assert "eco_fired_reverted_regression" in src
    assert 'elif _eco_regressed:' in src


def test_the_revert_declines_to_adopt_rather_than_restoring():
    """The shape is load-bearing and worth pinning: the ECO outputs stay on
    disk under their own names, and the pre-ECO artefacts are retained. A
    revert that moved files could fail half-way; this one cannot."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(errors="replace")
    # Scoped to the revert branch itself, and whitespace-normalised. The
    # sentences wrap across lines AND across adjacent string literals, so a
    # literal substring test would be asserting the line width rather than the
    # behaviour — and an unscoped one would pass on this file's own docstrings.
    i = src.index("elif _eco_regressed:")
    branch = " ".join(src[i:i + 1200].split())
    assert "NOT adopted as the shipped artefacts" in branch
    assert "pre-ECO" in branch and "retained" in branch
