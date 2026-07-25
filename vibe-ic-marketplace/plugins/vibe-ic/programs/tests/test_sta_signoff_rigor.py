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

import sys
from pathlib import Path

from conftest import func_src

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
