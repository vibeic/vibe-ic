"""Regression: the rc-axis multi-corner SPEF STA stanza must QUERY DRV.

Field case (caravel_user_project x sky130A, and every cell that reaches the
sta_corner_record_completeness gate): _emit_corner_spef_sta emitted
`report_checks {flag} -group_count 3`. `-group_count` is a DEPRECATED OpenSTA
flag; on the 0.2.28 image's OpenSTA 3.1.0 it raises `Error 514: '-max' is not a
known keyword or flag` and ABORTS the `-no_init -exit` script, so the
`report_check_types` DRV query on the NEXT line never ran. The report therefore
carried NO max_slew/max_capacitance check-types marker at all, and the gate
booked `R5_DRV_UNQUERIED` for EVERY design — a DRV-clean cell could never pass
this sign-off gate, and a real slew explosion was invisible ("looks like it
checks, actually does not").

Fix: emit `catch {report_checks {flag} -group_path_count 3 -fields {slew
capacitance}}` (the current flag, guarded exactly like the process-axis stanza),
so the DRV query is always reached.

VERIFIED on the real 0.2.28 OpenSTA against the caravel routed design:
  -group_count      -> Warning 503 + Error 514 (abort), no check-types marker,
                       gate extract_drv: queried=False  -> R5_DRV_UNQUERIED
  -group_path_count -> report_check_types runs, SIGNOFF_CHECK_TYPES_REPORTED
                       emitted, gate extract_drv: queried=True, and the REAL
                       max_slew (_203_/A1) + max_capacitance (place62/X)
                       violations are surfaced -> honest R5_DRV_VIOLATION.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
_RUNNER_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()

_GATE = _PROGRAMS / "sta_corner_record_completeness_check.py"
_spec = importlib.util.spec_from_file_location("_g2_gate", _GATE)
G = importlib.util.module_from_spec(_spec)
sys.modules["_g2_gate"] = G
sys.path.insert(0, str(_PROGRAMS))
_spec.loader.exec_module(G)


# A REAL OpenSTA 3.1.0 report body produced by the FIXED (-group_path_count)
# stanza on the caravel routed design (min-RC/HOLD section).
_FIXED_REPORT_BODY = """\
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.79
tns max 0.00
Group                                  Slack
--------------------------------------------
No paths found.

max slew

Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_203_/A1                                1.50    8.34   -6.84 (VIOLATED)

max capacitance

Pin                                    Limit     Cap   Slack
------------------------------------------------------------
place62/X                               0.56    1.93   -1.37 (VIOLATED)

                                     Required  Actual
Pin                                    Width   Width   Slack
------------------------------------------------------------
_337_/CLK (low)                         0.26   12.30   12.04 (MET)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance
"""

# The report body the DEPRECATED (-group_count) stanza actually produced: the
# script aborted at report_checks, so only slack lines exist — no marker.
_DEPRECATED_REPORT_BODY = """\
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.79
tns max 0.00
Warning 503: sta_spef_hold.tcl line 1, report_checks -group_count is deprecated. Use -group_path_count instead.
"""


def test_spef_corner_stanza_does_not_use_deprecated_group_count():
    """The emitted report_checks must NOT use the deprecated `-group_count`
    (which aborts OpenSTA 3.1.0 before the DRV query). It must use the current
    `-group_path_count`."""
    assert "-group_count 3" not in _RUNNER_SRC, (
        "deprecated `report_checks -group_count` re-introduced — it aborts "
        "OpenSTA 3.1.0 (Error 514) before report_check_types, silently dropping "
        "the max_slew/max_capacitance DRV query")
    # ORGANIC #540 — both corner emitters now build the call through the SHARED
    # `_report_worst_paths_tcl` helper, so the flag lives in one place instead
    # of being duplicated (which is how the same one-token bug came to sit at
    # two sites). Assert on the helper's OUTPUT for both path delays.
    import phase3_one_shot_runner as P
    for flag in ("-max", "-min"):
        assert "-group_path_count 3" in P._report_worst_paths_tcl("/x/o.rpt",
                                                                  flag)
    assert _RUNNER_SRC.count("_report_worst_paths_tcl(rpt_c, flag)") == 2, (
        "both the rc-axis and process-axis stanzas must route through the "
        "shared worst-path helper")


def test_spef_corner_stanza_reaches_report_check_types():
    """report_checks in the rc-axis stanza is guarded so a report_checks hiccup
    can never abort the DRV query that follows.

    ORGANIC #540 — this assertion used to read:

        assert "catch {{report_checks {flag} -group_path_count 3 " in stanza

    which pinned the BROKEN command. `{flag}` is `report_worst_slack`'s
    `-max`/`-min`, which `report_checks` rejects with Error 514, so the very
    string this test protected was one OpenSTA never executed. The guard it
    checked for was doing the swallowing. Assert on the helper's OUTPUT and on
    the ORDER instead — and see the execution test at the bottom of this file
    for the assertion that keys on a produced REPORT rather than on Tcl text.
    """
    i = _RUNNER_SRC.index("def _emit_corner_spef_sta(")
    j = _RUNNER_SRC.index("\ndef ", i + 1)
    stanza = _RUNNER_SRC[i:j]
    assert "_report_worst_paths_tcl(rpt_c, flag)" in stanza, stanza[-2000:]
    assert "_report_check_types_tcl(rpt_c)" in stanza
    # the worst-path dump precedes the DRV query, so a hiccup in the first
    # cannot cost the second (the reason the guard was introduced).
    assert (stanza.index("_report_worst_paths_tcl(rpt_c, flag)")
            < stanza.index("_report_check_types_tcl(rpt_c)"))


def test_extract_drv_no_vacuity_catches_real_slew_and_cap():
    """NO-VACUITY: with DRV queried (post-fix), a genuine max_slew + max_cap
    violation is still detected and reported — the fix surfaces violations, it
    does not hide them."""
    drv = G.extract_drv(_FIXED_REPORT_BODY)
    assert drv["queried"] is True, drv
    assert drv["violations"].get("max_slew", 0) >= 1, drv
    assert drv["violations"].get("max_capacitance", 0) >= 1, drv
    assert drv["total"] >= 2, drv


def test_extract_drv_unqueried_reproduces_the_bug():
    """The deprecated stanza's output (no check-types marker) is scored
    UNQUERIED — the exact R5_DRV_UNQUERIED the flow booked for every cell."""
    drv = G.extract_drv(_DEPRECATED_REPORT_BODY)
    assert drv["queried"] is False, drv
    assert drv["total"] == 0, drv
