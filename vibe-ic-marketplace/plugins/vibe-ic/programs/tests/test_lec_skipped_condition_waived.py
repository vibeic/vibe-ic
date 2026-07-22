#!/usr/bin/env python3
"""Regression: a step-13 LEC verdict of SKIPPED-CONDITION must be booked as
WAIVED-DEFERRED, never as a hard LEC_NOT_EQUIVALENT FAIL.

SKIPPED-CONDITION is lec_run's DISCLOSED-skip verdict — the producer explicitly
signalling "I did NOT decide equivalence": the gold top could not be resolved to
a real RTL module, an unstaged hard-macro module was referenced, or the netlist
carries SAT-unmodelable cells. In every such case lec_run built no deciding
miter and recorded NO counterexample. It is the SAME evidence class as
INCONCLUSIVE (#208): a visible non-PASS with zero equivalence evidence in either
direction, NOT a proof of non-equivalence.

THE BUG (observed on ibex × sky130A, campaign_v1550): lec_equivalence_check only
special-cased verdict=="INCONCLUSIVE". A verdict=="SKIPPED-CONDITION" (with
inconclusive:false) fell through to the substance verdict, where
`equivalent is not True` fired LEC_NOT_EQUIVALENT — a hard FAIL. Step 13 then
cascade-marked every downstream physical step MISSING, off a netlist that
nothing had proven NON-equivalent. That is the exact false-clean-vs-false-FAIL
mishandling #208 fixed for INCONCLUSIVE, just via the sibling verdict string.

FIX: SKIPPED-CONDITION with no counterexample (non_equiv in {None,0}) is a
non-blocking disclosed skip → rc=3 + the PASS_WITH_WAIVERS sentinel →
WAIVED-DEFERRED. §4.05 NO-LEAK: a genuine mismatch lands non_equiv>0 and still
hard-FAILs at the substance verdict, so this can never launder a real
non-equivalence into a waiver.

chip-AGNOSTIC: pure verdict-shape fixtures; no chip/PDK/vendor literal.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as fcc  # noqa: E402
import lec_equivalence_check as lec  # noqa: E402

_CHECKER = _PROGRAMS / "lec_equivalence_check.py"

# The ibex × sky130A signature: gold top 'ibex' not resolvable to a declared RTL
# module (the real top is the generated 'chip_top' wrapper) → lec_run emits a
# top-not-found SKIPPED-CONDITION with 0 decided points and no counterexample.
SKIPPED_TOP_NOT_FOUND = (
    '{"verdict":"SKIPPED-CONDITION","equivalent":false,"inconclusive":false,'
    '"proven_points":0,"unproven_points":0,"non_equivalent_points":0,'
    '"compared_points":0}')
# An unstaged hard-macro / SAT-unmodelable-cells SKIPPED-CONDITION: a miter that
# left points unproven but recorded NO counterexample.
SKIPPED_UNMODELABLE = (
    '{"verdict":"SKIPPED-CONDITION","equivalent":false,"inconclusive":false,'
    '"proven_points":40,"unproven_points":12,"non_equivalent_points":0,'
    '"compared_points":52}')
# NO-LEAK negative control: a SKIPPED-CONDITION verdict string but WITH a
# recorded counterexample — a real non-equivalence that must still hard-FAIL.
SKIPPED_WITH_COUNTEREXAMPLE = (
    '{"verdict":"SKIPPED-CONDITION","equivalent":false,"inconclusive":false,'
    '"proven_points":40,"unproven_points":11,"non_equivalent_points":1,'
    '"compared_points":52}')
CLEAN_PASS = (
    '{"verdict":"PASS","equivalent":true,"proven_points":128,'
    '"unproven_points":0,"non_equivalent_points":0,"compared_points":128}')


def _run(tmp_path, lec_json_body):
    """Run the checker exactly as the step-13 gate does and resolve the tier the
    way flow_compliance_check itself resolves it (incl. the stdout[-300:]
    truncation window a sentinel must survive)."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "lec.json").write_text(lec_json_body)
    proc = subprocess.run([sys.executable, str(_CHECKER), str(tmp_path)],
                          capture_output=True, text=True)
    snippet = (proc.stdout[-300:] + "\n" + proc.stderr[-300:]).strip()
    if proc.returncode == 0:
        tier = "PASS"
    elif proc.returncode == 2:
        tier = "VACUOUS_PASS"
    elif (proc.returncode == fcc._WAIVER_EXIT_CODE
          and fcc._stdout_signals_waiver(snippet)):
        tier = "WAIVED-DEFERRED"
    else:
        tier = "FAIL"
    return proc.returncode, tier


@pytest.mark.parametrize("body,label", [
    (SKIPPED_TOP_NOT_FOUND, "gold top not resolvable (chip_top wrapper)"),
    (SKIPPED_UNMODELABLE, "unstaged macro / SAT-unmodelable cells"),
])
def test_skipped_condition_is_waived_deferred_never_a_hard_fail(tmp_path, body,
                                                                label):
    """A disclosed SKIPPED-CONDITION must be WAIVED-DEFERRED, not a hard FAIL."""
    rc, tier = _run(tmp_path, body)
    assert tier != "FAIL", (
        f"{label}: a disclosed SKIPPED-CONDITION was booked as a hard FAIL — it "
        f"would cascade-mark every downstream physical step MISSING off a "
        f"netlist nothing proved non-equivalent")
    assert rc == fcc._WAIVER_EXIT_CODE, f"{label}: want rc=3, got rc={rc}"
    assert tier == "WAIVED-DEFERRED", f"{label}: got tier={tier}"


@pytest.mark.parametrize("body,label", [
    (SKIPPED_TOP_NOT_FOUND, "gold top not resolvable"),
    (SKIPPED_UNMODELABLE, "unmodelable cells"),
])
def test_skipped_condition_reports_its_own_rule(tmp_path, body, label):
    """The finding is the honest LEC_SKIPPED_CONDITION, not LEC_NOT_EQUIVALENT."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "lec.json").write_text(body)
    res = lec.audit(tmp_path)
    rules = [f.rule for f in res.findings]
    assert rules == ["LEC_SKIPPED_CONDITION"], f"{label}: got {rules}"
    assert res.inconclusive is True and res.passed is False


def test_sentinel_survives_the_300_char_truncation_window(tmp_path):
    """The PASS_WITH_WAIVERS sentinel must survive the trailing-300-char window
    flow_compliance actually inspects (last + short line)."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "lec.json").write_text(SKIPPED_TOP_NOT_FOUND)
    proc = subprocess.run([sys.executable, str(_CHECKER), str(tmp_path)],
                          capture_output=True, text=True)
    assert fcc._stdout_signals_waiver(proc.stdout[-300:]), (
        "sentinel fell outside the window flow_compliance inspects:\n"
        f"{proc.stdout[-300:]!r}")


def test_skipped_condition_with_counterexample_still_hard_fails(tmp_path):
    """NO-LEAK: a SKIPPED-CONDITION carrying a recorded counterexample
    (non_equiv>0) is a real non-equivalence and must still hard-FAIL."""
    rc, tier = _run(tmp_path, SKIPPED_WITH_COUNTEREXAMPLE)
    assert rc == 1, f"want rc=1 (hard FAIL), got rc={rc}"
    assert tier == "FAIL", f"got tier={tier}"


def test_clean_pass_still_passes(tmp_path):
    """A genuinely proven-equivalent design is unaffected by the new branch."""
    rc, tier = _run(tmp_path, CLEAN_PASS)
    assert rc == 0
    assert tier == "PASS"
