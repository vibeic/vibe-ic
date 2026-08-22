#!/usr/bin/env python3
"""A wall-clock kill is never evidence of non-equivalence — at ANY level of
partial progress — and lec.json must say how big the proof obligation was.

MEASURED DEFECT
===============
`lec_run` already had three guards for a budget-exhausted LEC, and a partially
progressed one slipped past all of them:

  * the `parse_error + _TIMEOUT_RE` branch needs NOTHING parsed;
  * the `proven is None and unproven is None` branch needs NEITHER count;
  * `induction_did_not_converge` keys on `Proved 0` / `Circuit inherently
    diverges`, and `induction_ladder_exhausted` keys on an `equiv_induct`
    marker — none of which exist when the clock kills the run during
    `equiv_simple`, i.e. before `equiv_induct` ever starts.

So a run killed mid-`equiv_simple` after proving some cells parsed as
`proven=N>0`, `unproven=total-N>0`, no flat wall, no ladder, no counterexample,
and fell through to the blocking FAIL with

    "N/T proven, U unproven — the RTL and gate netlist may genuinely differ
     at these points."

from a log whose final line is lec_run's OWN `_TIMEOUT_MARKER`. The module
docstring names this exact harm ("a killed run produced NO evidence —
indistinguishable at the gate from a real mismatch").

Observed on a real benchmark cell: the miter was 43,942 `$equiv` points
because the RTL instantiates one arithmetic block 256 times and both LEC sides
are flattened, so the same obligation is replicated 256x. `equiv_simple`
measured at ~730 points/min there, i.e. ~1 h before induction even begins — so
every budget on that host is a kill. Any design with a replicated submodule
reaches the same shape.

SECOND HALF — the size was measured and thrown away
====================================================
`parse_equiv_output` has always computed `total` (it is what reconstructs the
other two counts), and `build_report` never surfaced it. An INCONCLUSIVE
lec.json therefore read `compared_points: 0` with no indication whether the
budget nearly covered the proof or was orders of magnitude short — two
situations calling for opposite actions.

BIDIRECTIONAL NEGATIVE CONTROL
==============================
`test_real_mismatch_in_budget_stays_fail` and
`test_counterexample_beats_the_budget_marker` must FAIL if the fix is written
too broadly (i.e. if any timeout marker softened a genuine mismatch), and
`test_budget_kill_with_partial_progress_is_inconclusive` must FAIL against
pre-fix code. chip-, PDK- and vendor-AGNOSTIC: pure yosys log phrases.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import lec_run  # noqa: E402

M = lec_run._TIMEOUT_MARKER


def _parse(log):
    return lec_run.parse_equiv_output(log)


def _report(log):
    return lec_run.build_report(_parse(log), "top", "netlist.v", None)


# --------------------------------------------------------------- the fix ----
def test_budget_kill_with_partial_progress_is_inconclusive():
    """Killed mid-equiv_simple AFTER proving some cells. equiv_induct never
    ran, so there is no flat-wall and no ladder signature — the shape that
    used to fall through to FAIL."""
    log = ("\nFound 43814 unproven $equiv cells (43814 groups) in equiv:\n"
           "Proved 1200 previously unproven $equiv cells.\n\n"
           + M + " after 7200s")
    p = _parse(log)
    assert p["verdict"] == "INCONCLUSIVE", p["verdict"]
    assert p["equivalent"] is False, "never a PASS"
    assert "may genuinely differ" not in p["verdict_explanation"], (
        "a budget kill must not be narrated as a possible real difference")
    assert "budget" in p["verdict_explanation"].lower()


def test_budget_kill_at_zero_progress_still_inconclusive():
    """Pre-existing behaviour must not regress."""
    log = ("\nFound 43814 unproven $equiv cells (43814 groups) in equiv:\n"
           "Proved 0 previously unproven $equiv cells.\n\n" + M + " after 7200s")
    assert _parse(log)["verdict"] == "INCONCLUSIVE"


def test_budget_kill_with_nothing_parsed_still_non_blocking():
    """Pre-existing behaviour must not regress."""
    assert _parse("\nnoise\n" + M + " after 900s")["verdict"] in (
        "INCONCLUSIVE", "SKIPPED-CONDITION")


# ------------------------------------------------------ negative controls ----
def test_real_mismatch_in_budget_stays_fail():
    """A completed miter with a counterexample and NO timeout marker is a real
    non-equivalence. If this ever turns INCONCLUSIVE the fix is too broad."""
    log = ("\nFound 40 unproven $equiv cells (40 groups) in equiv:\n"
           "Proved 33 previously unproven $equiv cells.\n"
           "Found 7 unproven $equiv cells in module equiv:\n"
           "  Of those cells 33 are proven and 7 are unproven.\n"
           "Trying to prove $equiv for \\x: failed.\n"
           "Equivalence check failed!\n")
    assert _parse(log)["verdict"] == "FAIL"


def test_counterexample_beats_the_budget_marker():
    """A run that recorded a counterexample AND then hit the budget is still a
    proven difference — a mismatch found is a mismatch found."""
    log = ("\nFound 40 unproven $equiv cells (40 groups) in equiv:\n"
           "Proved 33 previously unproven $equiv cells.\n"
           "  Of those cells 33 are proven and 7 are unproven.\n"
           "Equivalence check failed!\n" + M)
    assert _parse(log)["verdict"] == "FAIL"


def test_clean_pass_in_budget_stays_pass():
    log = ("\nFound 71 unproven $equiv cells (71 groups) in equiv:\n"
           "Proved 71 previously unproven $equiv cells.\n"
           "  Of those cells 71 are proven and 0 are unproven.\n"
           "Equivalence successfully proven!\n")
    p = _parse(log)
    assert p["verdict"] == "PASS" and p["equivalent"] is True


# ------------------------------------------------------- the miter size -----
def test_lec_json_reports_the_miter_size():
    log = ("\nFound 43814 unproven $equiv cells (43814 groups) in equiv:\n"
           "Proved 1200 previously unproven $equiv cells.\n\n"
           + M + " after 7200s")
    r = _report(log)
    assert r["miter_points"] == 43814, r.get("miter_points")
    # the old opacity: 0 decided points, and previously nothing said 43814
    assert r["compared_points"] == 1200


def test_miter_size_is_never_fabricated():
    """No parseable total → None, not 0 (0 would read as an empty miter)."""
    assert _report("\nnoise\n" + M)["miter_points"] is None


# ------- the doctrine boundary this fix must NOT cross (negative control) ----
def test_completed_equiv_status_under_a_timeout_still_fails():
    """A MEASURED per-point verdict is a real result. A timeout marker arriving
    afterwards (rc=137 re-attaches it) cannot retract it. This is the exact
    assertion of the two pre-existing doctrine tests
    `test_lec_run.test_container_timeout_rc_with_recorded_mismatch_still_fails`
    and `test_v1462_lvs_lec_manifest_capture
    .test_timeout_with_partial_completed_verdict_still_fails`; it is restated
    here so a future edit to THIS branch cannot break them silently."""
    log = ("Yosys 0.67+\nFound 8 $equiv cells in equiv:\n"
           "  Of those cells 0 are proven and 8 are unproven.\n" + M)
    assert _parse(log)["verdict"] == "FAIL"


def test_the_discriminator_is_measured_vs_inferred_not_the_marker():
    """Same timeout marker, same non-zero proven count. The ONLY difference is
    whether equiv_status actually emitted a verdict."""
    measured = ("Found 40 $equiv cells in equiv:\n"
                "  Of those cells 33 are proven and 7 are unproven.\n" + M)
    inferred = ("Found 40 unproven $equiv cells (40 groups) in equiv:\n"
                "Proved 33 previously unproven $equiv cells.\n" + M)
    assert _parse(measured)["verdict"] == "FAIL"
    assert _parse(inferred)["verdict"] == "INCONCLUSIVE"
