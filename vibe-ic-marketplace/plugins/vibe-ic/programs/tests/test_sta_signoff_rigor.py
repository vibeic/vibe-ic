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


# ── _emit_spef_sta source-pin ────────────────────────────────────────────────

def test_spef_sta_tcl_emits_ocv_and_check_types():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def _emit_spef_sta")
    window = src[i:i + 5200]
    assert "set_timing_derate -early" in window
    assert "OCV_DERATE_APPLIED" in window
    assert "report_check_types -recovery -removal" in window
    assert "min_pulse_width" in window
    # the OCV marker is written via a native-Tcl channel append (a bare
    # `puts >> file` would be invalid Tcl).
    assert "open " in window and "puts $_ocvf" in window
