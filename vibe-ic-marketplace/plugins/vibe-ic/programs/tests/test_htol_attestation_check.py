#!/usr/bin/env python3
"""Every refusal path of `htol_attestation_check` — the step-44 reliability gate.

RENAMED from `test_htol_absent_input_is_blocked.py` (vibe-ic#220), which named the
one case it started as. The four sibling stage-5 gates each carry a test named for
the gate — manufacturing_fab_intake_check, wafer_sort_yield_check,
packaging_intake_check, final_test_attestation_check — and 785 of the 1188 top-level
programs follow that rule; this was the outlier. #220 is kept here in full, below,
because the old FILENAME was the only record of why the file exists.

WHY THIS GATE IS WORTH COVERING TWICE OVER. Steps 40-44 are this flow's INTAKE checks
on real silicon, and none of them has ever run — nothing has been taped out. So the
only thing between a fabricated reliability claim and a signed-off chip is whether
these gates refuse correctly, and a gate never seen to fail has not been shown to
discriminate.

THE ARITHMETIC IS THE PART NOBODY WAS WATCHING. `audit` does not merely validate
fields; it COMPUTES the published FIT number:

    fit = (max(failures, 0.5) / (device_hours * acceleration_factor)) * 1e9

The 0.5 floor is a chi-squared-style convention so that ZERO observed failures still
yields a finite upper-bound estimate rather than an infinitely good part. The
acceleration factor moves that number by orders of magnitude. An AF silently applied
when it should not be, or silently ignored when it should be, changes a reliability
claim by a factor of hundreds — and until this file, no test touched either.

vibe-ic#220 — an absent HTOL result must read as BLOCKED, never SKIP.

Reliability qualification (HTOL) is owed once silicon has been fabricated. The
gate used to return `verdict=SKIP` when phase3/stage5_manufacturing/
htol_results.json was absent, and "SKIP" reads as "nothing to do here" — but an
unperformed reliability qual is not nothing to do, it is an unanswered question.
The gate now names the missing input and returns BLOCKED with a non-zero rc,
while a genuinely-complete attestation still PASSes (the alarm must still be
able NOT to ring).

chip-AGNOSTIC: synthetic numeric fixture, no chip/PDK/vendor literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import htol_attestation_check as HTOL  # noqa: E402


def _mk(tmp_path: Path, results: dict | None) -> Path:
    proj = tmp_path / "proj"
    mfg = proj / "phase3" / "stage5_manufacturing"
    mfg.mkdir(parents=True, exist_ok=True)
    if results is not None:
        (mfg / "htol_results.json").write_text(json.dumps(results))
    return proj


# --------------------------------------------------------- the #220 fix
def test_absent_htol_is_blocked_not_skip(tmp_path):
    proj = _mk(tmp_path, None)
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "BLOCKED", rep
    assert rep["verdict"] != "SKIP"
    assert rep["rc"] == 2
    assert "missing_input" in rep and "htol_results.json" in rep["missing_input"]


def test_absent_htol_main_exits_nonzero(tmp_path):
    proj = _mk(tmp_path, None)
    assert HTOL.main([str(proj)]) == 2


# ------------------------------------------------- alarm can still ring
def test_complete_attestation_still_passes(tmp_path):
    proj = _mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                          "failures": 0})
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "PASS", rep
    assert rep["rc"] == 0


def test_failure_during_htol_still_fails(tmp_path):
    proj = _mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                          "failures": 1})
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "FAIL", rep
    assert rep["rc"] == 1


# ---------------------------------------------------- A: unparseable input
def test_unparseable_json_is_a_failure_not_a_pass(tmp_path):
    """Bytes that are not JSON must FAIL, never fall through to a verdict.

    An unreadable attestation and an absent one are different findings — the
    first says someone produced something, the second says nobody did — but
    neither may resolve to PASS, and a parser that swallows the error would
    make the first indistinguishable from a clean run.
    """
    proj = _mk(tmp_path, None)
    (proj / "phase3" / "stage5_manufacturing" / "htol_results.json").write_text(
        "{units_tested: 77, this is not json")
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "FAIL", rep
    assert rep["rc"] == 1
    assert "unparseable" in rep["reason"]


# ------------------------------------- B: present but not substantive
def test_missing_units_names_which_field_is_missing(tmp_path):
    rep = HTOL.audit(_mk(tmp_path, {"stress_hours": 1000, "failures": 0}))
    assert rep["verdict"] == "FAIL" and rep["rc"] == 1, rep
    assert "UNITS_MISSING" in rep["reason"], rep


def test_missing_hours_names_which_field_is_missing(tmp_path):
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "failures": 0}))
    assert rep["verdict"] == "FAIL" and rep["rc"] == 1, rep
    assert "HOURS_MISSING" in rep["reason"], rep


def test_missing_failures_names_which_field_is_missing(tmp_path):
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "stress_hours": 1000}))
    assert rep["verdict"] == "FAIL" and rep["rc"] == 1, rep
    assert "FAILURES_MISSING" in rep["reason"], rep


def test_every_missing_field_is_named_not_just_the_first(tmp_path):
    """A report that stops at the first fault sends someone back three times."""
    rep = HTOL.audit(_mk(tmp_path, {}))
    for tag in ("UNITS_MISSING", "HOURS_MISSING", "FAILURES_MISSING"):
        assert tag in rep["reason"], (tag, rep["reason"])


def test_zero_units_is_not_a_population(tmp_path):
    """units_tested must be POSITIVE. Zero parts under stress is not a test of
    zero failures — it is no test, and it would divide the FIT by zero."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 0, "stress_hours": 1000,
                                    "failures": 0}))
    assert rep["verdict"] == "FAIL", rep
    assert "UNITS_MISSING" in rep["reason"], rep


def test_negative_failures_is_refused(tmp_path):
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                                    "failures": -1}))
    assert rep["verdict"] == "FAIL", rep
    assert "FAILURES_MISSING" in rep["reason"], rep


def test_zero_failures_is_legal_and_is_not_treated_as_missing(tmp_path):
    """The success case shares its shape with the missing case — 0 is falsy.
    A gate that tested truthiness would refuse exactly the runs that qualify."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                                    "failures": 0}))
    assert rep["verdict"] == "PASS", rep


# ------------------------- C: the stated device-hours must reconcile
def test_device_hours_that_disagrees_by_more_than_one_percent_fails(tmp_path):
    """77 x 1000 = 77000. A stated 90000 is 16.9% off and must not stand."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                                    "failures": 0, "device_hours": 90000}))
    assert rep["verdict"] == "FAIL" and rep["rc"] == 1, rep
    assert "DEVICE_HOURS_INCONSISTENT" in rep["reason"], rep


def test_device_hours_within_one_percent_is_accepted(tmp_path):
    """THE OTHER SIDE OF THE SAME BOUNDARY. Testing only the failing side would
    pass a gate hard-wired to refuse every stated device_hours."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                                    "failures": 0, "device_hours": 77500}))
    assert rep["verdict"] == "PASS", rep          # 0.65% off
    assert rep["device_hours"] == 77500, rep


def test_device_hours_is_derived_and_says_so_when_absent(tmp_path):
    """A derived number and a stated one must not be indistinguishable in the
    report — the reader has to know which one they are being shown."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                                    "failures": 0}))
    assert rep["device_hours"] == 77000.0, rep
    assert rep["device_hours_note"], rep
    assert "derived" in rep["device_hours_note"]


# ---------------------------------- D: the FIT arithmetic nobody watched
def test_zero_failures_yields_a_finite_fit_via_the_half_failure_floor(tmp_path):
    """0 observed failures is not 0 FIT. The chi-squared-style 0.5 floor keeps
    the estimate an UPPER BOUND; without it a part with no failures reads as
    infinitely reliable, which is a claim no sample size can support."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 100, "stress_hours": 1000,
                                    "failures": 0}))
    assert rep["verdict"] == "PASS", rep
    fit = rep["fit_point_estimate"]
    assert fit is not None and fit > 0, rep
    assert abs(fit - (0.5 / 100000.0) * 1e9) < 1e-6, rep    # 5000 FIT


def test_acceleration_factor_is_applied_and_the_basis_says_so(tmp_path):
    """AF is the difference between a stress-hour and a use-hour. Applying it
    silently, or not applying it silently, moves the published number by
    orders of magnitude with nothing in the report to show which happened."""
    rep = HTOL.audit(_mk(tmp_path, {"units_tested": 100, "stress_hours": 1000,
                                    "failures": 0, "acceleration_factor": 50}))
    assert rep["acceleration_factor"] == 50, rep
    assert abs(rep["fit_point_estimate"] - (0.5 / 5000000.0) * 1e9) < 1e-6, rep
    assert "accelerated" in rep["fit_basis"], rep


def test_an_af_of_one_or_less_is_not_applied_and_the_basis_says_unaccelerated(tmp_path):
    """AF <= 1 accelerates nothing. Treating it as an accelerator would inflate
    reliability off a factor that carries no information."""
    for af in (1, 0.5):
        rep = HTOL.audit(_mk(tmp_path, {"units_tested": 100, "stress_hours": 1000,
                                        "failures": 0, "acceleration_factor": af}))
        assert rep["acceleration_factor"] is None, (af, rep)
        assert "UNACCELERATED" in rep["fit_basis"], (af, rep)
        assert abs(rep["fit_point_estimate"] - (0.5 / 100000.0) * 1e9) < 1e-6, (af, rep)
