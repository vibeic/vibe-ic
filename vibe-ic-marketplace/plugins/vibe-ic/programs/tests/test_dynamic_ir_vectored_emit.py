#!/usr/bin/env python3
"""Unit tests for the VCD-vectored dynamic IR emitter's PURE helpers + the gate's
honest-SKIP recognition. No docker / no OpenROAD — these test parsing, discovery,
verdict shaping, and that an emitter SKIP JSON is honored by the budget gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dynamic_ir_vectored_emit as E  # noqa: E402
import dynamic_ir_drop_check as G  # noqa: E402

# A trimmed real OpenROAD PSM stdout (from the spm HP18E80 vectored run).
_PSM_LOG = """
[WARNING STA-0305] read_power_activities is deprecated. Use read_vcd.
Annotated 36 pin activities.
Group                  Internal  Switching    Leakage      Total
Total                  1.05e-03   9.79e-05   2.15e-08   1.15e-03 100.0%
Total power      : 8.76e-04 W
Supply voltage   : 1.80e+00 V
Worstcase voltage: 1.70e+00 V
Average voltage  : 1.72e+00 V
Average IR drop  : 7.67e-02 V
Worstcase IR drop: 9.94e-02 V
"""


# ── parse helpers ──────────────────────────────────────────────────────────────

def test_parse_worst_ir_v():
    assert abs(E.parse_worst_ir_v(_PSM_LOG) - 0.0994) < 1e-9


def test_parse_supply_v():
    assert E.parse_supply_v(_PSM_LOG) == 1.8


def test_parse_annotated_pins():
    assert E.parse_annotated_pins(_PSM_LOG) == 36


def test_parse_total_power_w():
    assert abs(E.parse_total_power_w(_PSM_LOG) - 8.76e-04) < 1e-12


def test_parse_worst_ir_absent_is_none():
    assert E.parse_worst_ir_v("no psm ran here") is None


# ── VCD scope discovery ─────────────────────────────────────────────────────────

def test_discover_vcd_scope_tb_dut_nesting():
    vcd = ("$scope module tb_spm_full $end\n"
           "$var wire 1 ! p $end\n"
           "$scope module u_dut $end\n"
           "$var wire 1 # clk $end\n"
           "$upscope $end\n"
           "$scope task drive_byte $end\n$upscope $end\n"
           "$upscope $end\n$enddefinitions $end\n")
    assert E.discover_vcd_scope(vcd) == "tb_spm_full/u_dut"


def test_discover_vcd_scope_task_not_mistaken_for_dut():
    # a testbench with only a helper task (no nested MODULE) → outermost module.
    vcd = ("$scope module tb $end\n"
           "$scope task drive $end\n$upscope $end\n$upscope $end\n")
    assert E.discover_vcd_scope(vcd) == "tb"


def test_discover_vcd_scope_none_when_no_module():
    assert E.discover_vcd_scope("$var wire 1 ! p $end\n") is None


# ── find_vcd ────────────────────────────────────────────────────────────────────

def test_find_vcd_picks_nonempty(tmp_path):
    simd = tmp_path / "phase2" / "stage1" / "sim_full_stack" / "run"
    simd.mkdir(parents=True)
    (simd / "empty.vcd").write_text("")
    good = simd / "waves.vcd"
    good.write_text("$scope module tb $end\n")
    assert E.find_vcd(tmp_path) == good


def test_find_vcd_absent_is_none(tmp_path):
    assert E.find_vcd(tmp_path) is None


# ── DEF power-net discovery ─────────────────────────────────────────────────────

def test_discover_power_nets(tmp_path):
    d = tmp_path / "x.def"
    d.write_text(
        "DESIGN spm ;\n"
        "SPECIALNETS 2 ;\n"
        "- VDD ( * VDD ) + USE POWER ;\n"
        "- VSS ( * VSS ) + USE GROUND ;\n"
        "END SPECIALNETS\n")
    assert E.discover_power_nets(d) == ["VDD"]


def test_discover_power_nets_no_pdn(tmp_path):
    d = tmp_path / "x.def"
    d.write_text("DESIGN spm ;\nEND DESIGN\n")
    assert E.discover_power_nets(d) == []


# ── static-IR read + result shaping ─────────────────────────────────────────────

def test_read_static_ir_mv(tmp_path):
    j = tmp_path / "ir_drop.json"
    j.write_text(json.dumps({"worst_ir_uv": 105000.0}))
    assert E.read_static_ir_mv(j) == 105.0


def test_build_result_exceeds_static_true():
    r = E.build_result(worst_dyn_mv=460.0, vdd_v=1.8, static_mv=105.0,
                       annotated_pins=4, total_power_w=4.45e-3, power_net="VDD",
                       vcd="/x/waves.vcd", scope="tb/u_dut")
    assert r["max_dynamic_drop_mv"] == 460.0
    assert r["exceeds_static"] is True
    assert r["dynamic_vs_static_ratio"] == round(460.0 / 105.0, 3)
    assert r["analysis_mode"] == "vcd_vectored_psm"
    assert "di/dt" in r["disclosure"]  # honest transient-gap disclosure present


def test_build_result_exceeds_static_false_is_honest():
    # idle-heavy functional VCD → vectored BELOW static; we report the truth.
    r = E.build_result(worst_dyn_mv=99.4, vdd_v=1.8, static_mv=105.0,
                       annotated_pins=36, total_power_w=8.76e-4, power_net="VDD",
                       vcd="/x/waves.vcd", scope="tb_spm_full/u_dut")
    assert r["exceeds_static"] is False
    assert r["max_dynamic_drop_pct"] == round(99.4 / (1.8 * 1000) * 100, 3)


def test_build_result_is_gate_consumable():
    # the emitter payload must be readable by the budget gate (round-trip).
    r = E.build_result(worst_dyn_mv=90.0, vdd_v=1.8, static_mv=105.0,
                       annotated_pins=36, total_power_w=1e-3, power_net="VDD",
                       vcd="/x/waves.vcd", scope="tb/u_dut")
    verdict = G._extract_from_json(r)
    assert verdict[0] == 90.0 and verdict[1] == 1.8


# ── honest SKIP path (§4.05): emitter SKIP JSON → gate SKIPPED_CONDITION ─────────

def test_gate_honors_emitter_skip_no_vcd(tmp_path):
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps(E.skip_result("no non-empty design VCD found")))
    res = G.check(j, 1.8, 10.0)
    assert res["verdict"] == "SKIPPED_CONDITION"
    assert G.main([str(j)]) == 0  # skip is rc 0, not a blocker


def test_gate_skip_via_status_marker(tmp_path):
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"status": "SKIPPED_NO_PDN",
                             "dynamic_ir_report_emitted": False,
                             "reason": "no PDN"}))
    assert G.check(j, 1.8, 10.0)["verdict"] == "SKIPPED_CONDITION"


def test_gate_garbage_without_marker_still_fails(tmp_path):
    # §4.05: a report with no droop value AND no skip marker is FAIL, never SKIP.
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"unrelated": 1}))
    assert G.check(j, 1.8, 10.0)["verdict"] == "FAIL"


def test_gate_real_number_beats_skip_marker(tmp_path):
    # a payload that carries BOTH a skip-ish flag AND a real droop must be graded,
    # not skipped (droop present → normal budget check).
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"dynamic_ir_report_emitted": True,
                             "max_dynamic_drop_mv": 90.0, "vdd": 1.8}))
    assert G.check(j, None, 10.0)["verdict"] == "PASS"
