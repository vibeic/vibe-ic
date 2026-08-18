#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF (timing rigor) — the SPEF-based sign-off STA must carry OCV
derating + recovery/removal + min-pulse-width, and the gate must FAIL an
optimistic report that omits them.

Two layers:
  1. sta_signoff_rigor_check.py — the gate (PASS only when all present; FAIL when
     any missing even if slack is MET; IO error when the report is absent).
  2. _emit_spef_sta source-pin — the SPEF STA TCL actually emits set_timing_derate
     + the OCV marker + report_check_types -recovery -removal -min_pulse_width.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from _source_pin import func_src

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import sta_signoff_rigor_check as G  # noqa: E402


_FULL_RIGOR = """\
Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)
Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)
   0.42   slack (MET)
tns 0.00
wns 0.00
worst slack max 0.42
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
Recovery/Removal checks:
   reg_rst recovery  0.31   slack (MET)
   reg_rst removal   0.12   slack (MET)
Min Pulse Width checks:
   clk min_pulse_width  1.80  slack (MET)
"""

_OPTIMISTIC = """\
Startpoint: reg_a
Endpoint: reg_b
   0.42   slack (MET)
tns 0.00
wns 0.00
worst slack max 0.42
"""


def test_full_rigor_report_passes():
    res = G.evaluate(_FULL_RIGOR)
    assert res["verdict"] == "PASS"
    assert res["ocv_derate_applied"] and res["recovery_checked"]
    assert res["removal_checked"] and res["min_pulse_width_checked"]
    assert res["missing"] == []


def test_optimistic_report_fails_even_if_slack_met():
    # §4.05: MET slack does NOT make it a sign-off — the missing OCV +
    # recovery/removal/MPW must FAIL it.
    res = G.evaluate(_OPTIMISTIC)
    assert res["verdict"] == "FAIL"
    assert res["ocv_derate_applied"] is False
    assert len(res["missing"]) == 4


def test_partial_report_fails_naming_the_gap():
    # derate present but recovery/removal/MPW absent → still FAIL, naming them.
    partial = _OPTIMISTIC + "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
    res = G.evaluate(partial)
    assert res["verdict"] == "FAIL"
    assert res["ocv_derate_applied"] is True
    assert any("recovery" in m for m in res["missing"])
    assert any("min-pulse-width" in m for m in res["missing"])


def test_absent_report_is_io_error_not_pass(tmp_path):
    res = G.check(tmp_path / "does_not_exist")
    assert res["verdict"] == "IO_ERROR"


def test_check_reads_report_from_dir(tmp_path):
    rpt = tmp_path / "post_route_timing.rpt"
    rpt.write_text(_FULL_RIGOR)
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS"
    assert res["report"].endswith("post_route_timing.rpt")


def test_main_exit_codes(tmp_path):
    good = tmp_path / "sta.rpt"
    good.write_text(_FULL_RIGOR)
    assert G.main([str(good)]) == 0
    bad = tmp_path / "opt.rpt"
    bad.write_text(_OPTIMISTIC)
    assert G.main([str(bad)]) == 1
    assert G.main([str(tmp_path / "nope")]) == 2


# ── TAPEOUT-SIGNOFF P1: AOCV vs flat-OCV distinction ─────────────────────────

_AOCV_RIGOR = """\
Startpoint: reg_a
Endpoint: reg_b
   0.42   slack (MET)
AOCV_TABLE_APPLIED file=/pdk/libs.tech/sky130.aocv
Recovery/Removal checks:
   reg_rst recovery  0.31   slack (MET)
   reg_rst removal   0.12   slack (MET)
Min Pulse Width checks:
   clk min_pulse_width  1.80  slack (MET)
"""


def test_aocv_report_passes_and_is_richer_mode():
    res = G.evaluate(_AOCV_RIGOR)
    assert res["verdict"] == "PASS"
    assert res["ocv_mode"] == "aocv"
    assert res["aocv_applied"] is True
    assert res["aocv_table"] == "/pdk/libs.tech/sky130.aocv"
    assert "AOCV" in res["ocv_scope"] or "richer" in res["ocv_scope"]


def test_flat_ocv_report_passes_as_flat_mode():
    res = G.evaluate(_FULL_RIGOR)  # carries OCV_DERATE_APPLIED ... flat-OCV
    assert res["verdict"] == "PASS"
    assert res["ocv_mode"] == "flat"
    assert res["aocv_applied"] is False
    # honest disclosure: sky130 open PDK ships no AOCV table -> flat is real.
    assert "flat-OCV" in res["ocv_scope"]


def test_no_derate_report_has_null_mode_and_fails():
    res = G.evaluate(_OPTIMISTIC)
    assert res["verdict"] == "FAIL"
    assert res["ocv_mode"] is None
    assert res["aocv_applied"] is False


def test_read_aocv_command_echo_also_counts():
    txt = _OPTIMISTIC + "read_aocv /pdk/x.aocv\nrecovery removal min_pulse_width\n"
    res = G.evaluate(txt)
    assert res["ocv_derate_applied"] is True
    assert res["ocv_mode"] == "aocv"


# ── v1.10.3: CONTENT, not just coverage — a real (VIOLATED) finding inside
# report_check_types' own output must FAIL the gate even when every coverage
# dimension is present. Fixtures below are real OpenSTA 3.1.0 report shapes
# (byte-shape verified against live sign-off reports), not idealized text.

_REAL_MPW_VIOLATION = _FULL_RIGOR + """\

                                     Required  Actual
Pin                                    Width   Width   Slack
------------------------------------------------------------
u_otp.u_otp/PRD (high)                200.00  100.01  -99.99 (VIOLATED)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance max_fanout
"""

_REAL_MPW_CLEAN = _FULL_RIGOR + """\

                                     Required  Actual
Pin                                    Width   Width   Slack
------------------------------------------------------------
_25158_/CLK (high)                      0.84    3.81    2.97 (MET)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance
"""

_REAL_MAX_SLEW_AND_CAP_VIOLATION_ONLY = _FULL_RIGOR + """\

max slew

Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_15653_/Y                               1.46   23.33  -21.86 (VIOLATED)

max capacitance

Pin                                    Limit     Cap   Slack
------------------------------------------------------------
_21312_/Y                               0.33    1.88   -1.54 (VIOLATED)

                                     Required  Actual
Pin                                    Width   Width   Slack
------------------------------------------------------------
_25158_/CLK (high)                      0.84    3.81    2.97 (MET)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance
"""

_REAL_REMOVAL_VIOLATION = _FULL_RIGOR + """\

Startpoint: reset_n (input port clocked by clk)
Endpoint: _2738_ (removal check against rising-edge clock clk)
Path Group: asynchronous
Path Type: min
                           2.05   data arrival time
                           0.52   data required time
-----------------------------------------------------------------------
                           0.52   data required time
                          -2.05   data arrival time
-----------------------------------------------------------------------
                          -1.53   slack (VIOLATED)

SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance
"""


def test_real_min_pulse_width_violation_fails_the_gate():
    # LIVE-CAUGHT on an internal design's OTP macro PRD pin: coverage was 100%
    # dimensions present) but the actual table row VIOLATED — the old gate
    # (coverage-only) PASSed this; v1.10.3 must FAIL it.
    res = G.evaluate(_REAL_MPW_VIOLATION)
    assert res["verdict"] == "FAIL"
    assert res["min_pulse_width_checked"] is True  # coverage was fine
    assert len(res["check_types_violations"]) == 1
    assert "PRD" in res["check_types_violations"][0]
    assert "VIOLATED" in res["check_types_violations"][0]


def test_clean_min_pulse_width_table_still_passes():
    res = G.evaluate(_REAL_MPW_CLEAN)
    assert res["verdict"] == "PASS"
    assert res["check_types_violations"] == []


def test_max_slew_and_max_capacitance_violations_are_out_of_scope():
    # max_slew / max_capacitance are real DRV findings but NOT this gate's
    # declared dimensions (recovery / removal / min_pulse_width only) — they
    # must NOT be folded in here (that would be undisclosed scope creep and
    # would retroactively flip unrelated runs' verdicts). The min_pulse_width
    # table in this same fixture is clean, so the gate must PASS.
    res = G.evaluate(_REAL_MAX_SLEW_AND_CAP_VIOLATION_ONLY)
    assert res["verdict"] == "PASS"
    assert res["check_types_violations"] == []


def test_real_removal_path_violation_fails_the_gate():
    res = G.evaluate(_REAL_REMOVAL_VIOLATION)
    assert res["verdict"] == "FAIL"
    assert len(res["check_types_violations"]) == 1
    assert "removal check against" in res["check_types_violations"][0]


def test_ordinary_setup_hold_path_violation_is_not_double_counted():
    # An ordinary (non recovery/removal) path violation elsewhere in the
    # report is a DIFFERENT gate's concern; it must not appear in this
    # gate's check_types_violations list.
    txt = _FULL_RIGOR + """
Startpoint: reg_c (rising edge-triggered flip-flop clocked by clk)
Endpoint: reg_d (rising edge-triggered flip-flop clocked by clk)
Path Type: max
           -1.20   slack (VIOLATED)
"""
    res = G.evaluate(txt)
    assert res["check_types_violations"] == []
    assert res["verdict"] == "PASS"


# ── _emit_spef_sta source-pin ────────────────────────────────────────────────

def test_spef_sta_tcl_emits_ocv_and_check_types():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    window = func_src(src, "_emit_spef_sta")
    # v1.2.x — the derate is emitted via the shared _flat_ocv_derate_tcl() helper
    # (TWO separate set_timing_derate commands; this OpenSTA build rejects the
    # combined -early -late form). The emitter must CALL that helper.
    assert "_flat_ocv_derate_tcl" in window
    assert "OCV_DERATE_APPLIED" in window
    # v1.2.x — the recovery/removal/MPW check types are emitted via the shared
    # _report_check_types_tcl() helper (guarded + marked), which the emitter CALLS.
    assert "_report_check_types_tcl" in window
    # the shared helper itself carries the check-type command + the authoritative
    # marker (OpenSTA 3.1.0's report output omits the literal check-type words).
    helper = func_src(src, "_report_check_types_tcl")
    assert "report_check_types -recovery -removal" in helper
    assert "min_pulse_width" in helper
    assert "_SIGNOFF_CHECK_TYPES_MARKER" in helper   # writes the marker
    # the marker constant names the check types (module-level).
    assert "SIGNOFF_CHECK_TYPES_REPORTED recovery removal" in src
    # the OCV marker is written via a native-Tcl channel append (a bare
    # `puts >> file` would be invalid Tcl).
    assert "open " in window and "puts $_ocvf" in window
    # AOCV ingest path: read_aocv guarded by catch, with the AOCV_TABLE_APPLIED
    # marker on success and a flat-OCV fallback on failure.
    assert "read_aocv" in window
    assert "AOCV_TABLE_APPLIED" in window
    assert "_discover_aocv_table" in src


def test_source_pin_helper_is_not_shadowed_by_the_other_conftest():
    """REGRESSION (v1.5.78): the shared source-pin helper lived in
    programs/tests/conftest.py and was imported as `from conftest import
    func_src`. There are TWO conftest.py on the path — this one and the
    plugin-root one — so on some file-set collections pytest resolved
    `conftest` to the plugin-root module, which has no func_src, and FOUR test
    modules failed to import with:
        ImportError: cannot import name 'func_src' from 'conftest'
    Single-file runs passed, which is why it survived the original landing.

    The helper now lives in its own uniquely-named module, which cannot be
    shadowed. This test fails if anyone reintroduces the bare-conftest import.
    """
    import _source_pin
    assert callable(_source_pin.func_src)

    # Match a real IMPORT STATEMENT (start of line, allowing indentation), not
    # any occurrence of the text — this very test mentions the bad form in its
    # own detector string and docstring, and matched itself on the first run.
    bad_import = re.compile(r"^[ \t]*from[ \t]+conftest[ \t]+import[ \t]+"
                            r"[^\n]*\bfunc_src\b", re.M)
    tests_dir = Path(__file__).resolve().parent
    offenders = [p.name for p in tests_dir.glob("test_*.py")
                 if bad_import.search(p.read_text())]
    assert offenders == [], (
        f"{offenders} import func_src from the ambiguous `conftest` name; "
        f"use `from _source_pin import func_src`")

    root_conftest = tests_dir.parents[1] / "conftest.py"
    if root_conftest.is_file():
        assert "def func_src" not in root_conftest.read_text(), (
            "the plugin-root conftest must NOT also define func_src — two "
            "definitions is how the shadowing became invisible")
