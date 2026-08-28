#!/usr/bin/env python3
"""Unit tests for the TRANSIENT (dynamic) IR emitter's PURE helpers + the gate's
honest-SKIP / budget handling. No docker / no OpenROAD — these test the
static/dynamic regex-collision, SDC-period derivation, result shaping, and the
skip-flip (no VCD is no longer a skip; missing-input / no-PDN still are)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dynamic_ir_vectored_emit as E  # noqa: E402
import dynamic_ir_drop_check as G  # noqa: E402

# A real `analyze_power_grid -transient` stdout: it prints BOTH the static
# "########## IR report" (Worstcase IR drop) AND the "Dynamic (transient) IR
# report" (Worst dynamic IR drop). The dynamic parser MUST pick the dynamic
# value, NOT the static — the regex-collision case the wiring notes flag.
_TRANSIENT_LOG = """
########## IR report #################
Net              : VDD
Corner           : default
Total power      : 1.30e-03 W
Supply voltage   : 1.80e+00 V
Worstcase voltage: 1.75e+00 V
Average voltage  : 1.77e+00 V
Average IR drop  : 3.10e-02 V
Worstcase IR drop: 5.30e-02 V
Percentage drop  : 2.94 %
######################################
########## Dynamic (transient) IR report ##########
Net                    : VDD
Corner                 : default
Supply voltage         : 1.80e+00 V
Timestep               : 1.00e-11 s
Steps                  : 100
Capacitance model      : quasi-static (no on-die cap supplied)
Worst static IR drop   : 5.30e-02 V
Worst dynamic IR drop  : 1.06e-01 V
Dynamic/static ratio   : 2.00
Current model          : vectorless (simultaneous worst case)
Worst droop time       : 5.00e-10 s (step 50)
###################################################
"""

# A transient run WITH an on-die decap + a package L·di/dt droop (vectored).
_TRANSIENT_LOG_PKG = """
########## Dynamic (transient) IR report ##########
Net                    : VDD
Supply voltage         : 1.80e+00 V
Timestep               : 2.00e-11 s
Steps                  : 50
On-die capacitance     : 3.10e-12 F
Worst static IR drop   : 4.00e-02 V
Worst dynamic IR drop  : 7.20e-02 V
Dynamic/static ratio   : 1.80
Current model          : vectored (128 instances matched)
Package L*di/dt droop  : 9.00e-03 V
Worst droop time       : 4.00e-10 s (step 20)
###################################################
"""


# ── the static/dynamic regex-collision (THE load-bearing parse test) ────────────

def test_dynamic_parser_picks_dynamic_not_static():
    # both "Worstcase IR drop: 5.30e-02 V" (static) and "Worst dynamic IR drop
    # : 1.06e-01 V" (dynamic) are present; the dynamic parser must return 0.106.
    assert abs(E.parse_worst_dynamic_ir_v(_TRANSIENT_LOG) - 0.106) < 1e-9


def test_static_parser_does_not_pick_dynamic():
    # the legacy static "Worstcase IR drop" parser must return the STATIC 0.053,
    # NOT the dynamic 0.106 — the two regexes never cross-match.
    assert abs(E.parse_worst_ir_v(_TRANSIENT_LOG) - 0.053) < 1e-9


def test_worst_static_from_transient_report():
    assert abs(E.parse_worst_static_tr_v(_TRANSIENT_LOG) - 0.053) < 1e-9


def test_dynamic_static_ratio():
    assert E.parse_dynamic_static_ratio(_TRANSIENT_LOG) == 2.0


def test_parse_supply_timestep_steps_models():
    assert E.parse_supply_v(_TRANSIENT_LOG) == 1.8
    assert abs(E.parse_timestep_s(_TRANSIENT_LOG) - 1.0e-11) < 1e-18
    assert E.parse_steps(_TRANSIENT_LOG) == 100
    assert E.parse_current_model(_TRANSIENT_LOG) == "vectorless"
    assert E.parse_cap_model(_TRANSIENT_LOG) == "quasi-static"


def test_package_droop_and_vectored_and_ondie_cap():
    assert abs(E.parse_package_droop_v(_TRANSIENT_LOG_PKG) - 9.0e-3) < 1e-12
    assert E.parse_current_model(_TRANSIENT_LOG_PKG) == "vectored"
    assert E.parse_cap_model(_TRANSIENT_LOG_PKG).startswith("on-die-cap")
    # no package line in the base log → None (never fabricated)
    assert E.parse_package_droop_v(_TRANSIENT_LOG) is None


def test_dynamic_parser_absent_is_none():
    assert E.parse_worst_dynamic_ir_v("no transient ran here") is None
    # a STATIC-only report (Step-24) must NOT yield a dynamic number.
    static_only = ("########## IR report #################\n"
                   "Worstcase IR drop: 5.30e-02 V\n")
    assert E.parse_worst_dynamic_ir_v(static_only) is None


# ── SDC clock-period derivation ─────────────────────────────────────────────────

def test_parse_sdc_period_single_clock():
    sdc = "create_clock -name clk -period 8.0 [get_ports clk]\n"
    assert E.parse_sdc_period_ns(sdc) == 8.0


def test_parse_sdc_period_takes_min_of_multiple_clocks():
    sdc = ("create_clock -period 10 [get_ports clk]\n"
           "create_clock -period 4 -name fast [get_ports clk2]\n")
    assert E.parse_sdc_period_ns(sdc) == 4.0   # tightest clock = worst di/dt


def test_parse_sdc_period_none_when_absent():
    assert E.parse_sdc_period_ns("set_units -time ns\n") is None


def test_derive_period_from_sdc_file(tmp_path):
    sdc = tmp_path / "x.sdc"
    sdc.write_text("create_clock -period 6.5 [get_ports clk]\n")
    p, src = E.derive_period_ns(sdc)
    assert p == 6.5 and src == "sdc_create_clock"


def test_derive_period_default_fallback_when_no_sdc():
    p, src = E.derive_period_ns(None)
    assert p == E._DEFAULT_PERIOD_NS and src == "default_fallback"


# ── DEF power-net discovery (unchanged) ─────────────────────────────────────────

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


# ── result shaping (new transient signature) ────────────────────────────────────

def test_build_result_transient_keys_and_gate_consumable():
    r = E.build_result(
        worst_dyn_mv=106.0, vdd_v=1.8, static_tr_mv=53.0, ratio=2.0,
        package_droop_mv=None, power_net="VDD", period_ns=8.0,
        period_source="sdc_create_clock", steps=100, timestep_s=1e-11,
        current_model="vectorless", cap_model="quasi-static")
    assert r["analysis_mode"] == "transient_psm"
    assert r["max_dynamic_drop_mv"] == 106.0
    assert r["vdd_v"] == 1.8 and r["vdd"] == 1.8
    assert r["max_dynamic_drop_pct"] == round(106.0 / 1800.0 * 100, 3)
    assert r["dynamic_static_ratio"] == 2.0
    assert r["period_ns"] == 8.0 and r["period_source"] == "sdc_create_clock"
    assert r["current_model"] == "vectorless"
    assert "backward-Euler" in r["disclosure"]  # honest real-solve disclosure
    # the gate must be able to read the payload (round-trip).
    droop, vdd = G._extract_from_json(r)
    assert droop == 106.0 and vdd == 1.8


def test_build_result_exceeds_static_vs_external_static():
    # external Step-24 static number wins over the transient-report static.
    r = E.build_result(
        worst_dyn_mv=106.0, vdd_v=1.8, static_tr_mv=53.0, ratio=2.0,
        package_droop_mv=None, power_net="VDD", period_ns=8.0,
        period_source="cli", steps=100, timestep_s=1e-11,
        current_model="vectorless", cap_model="quasi-static", static_mv=50.0)
    assert r["static_ir_mv"] == 50.0
    assert r["exceeds_static"] is True
    assert r["dynamic_vs_static_ratio"] == round(106.0 / 50.0, 3)


# ── V→mV at the EMIT seam (the caller, not build_result) ───────────────────────
# build_result's own tests pass mV in by hand, so none of them can see a caller
# that forgets the V→mV conversion. These drive `emit()` with docker stubbed out,
# so the PSM log is the only input and the payload is the only output — exactly
# the path that produced the published deliverables.

def _emit_on_log(tmp_path, log_text, static_json=None):
    """Run E.emit() with the openroad launch replaced by a canned PSM stdout.

    The injection point is `_wd.run_host_supervised`, not `subprocess.run`:
    `emit` no longer bounds openroad by RUNTIME — a transient PSM solve over a
    large die is exactly the honest long work a 1800 s cap destroys — and now
    launches it under progress supervision instead. Nothing these tests assert
    has changed; they are about the V->mV conversion at the emit seam, and the
    canned log is still the only input and the payload still the only output.
    """
    class _Res:
        rc = 0
        out = log_text
        err = ""
        outcome = "natural"
        elapsed_s = 0.1

    def _fake_supervised(*_a, **_kw):
        return _Res()

    def_file = tmp_path / "routed.def"
    def_file.write_text("SPECIALNETS 1 ;\n    - VDD ( * VDD ) + USE POWER\nEND SPECIALNETS\n")
    out_json = tmp_path / "reports" / "dynamic_ir.json"
    real_run = E._wd.run_host_supervised
    E._wd.run_host_supervised = _fake_supervised
    try:
        rc, payload = E.emit(
            def_file=def_file, tech_lef=tmp_path / "t.lef",
            cell_lef=tmp_path / "c.lef", liberty=tmp_path / "l.lib",
            macro_lefs=[], sdc=None, out_json=out_json, power_net="VDD",
            container="none", metal_prefix="Metal", static_json=static_json,
            budget_pct=15.0, period_ns=10.0, steps=100, decap_cap=None)
    finally:
        E._wd.run_host_supervised = real_run
    return rc, payload


def test_emit_static_from_transient_is_millivolts_not_volts(tmp_path):
    # The log's "Worst static IR drop: 5.30e-02 V" is 53.0 mV. A caller that
    # forwards the parser's VOLTS straight into the `_mv` field publishes 0.053
    # — wrong by 1000x. This assertion fails when that defect is present.
    _rc, r = _emit_on_log(tmp_path, _TRANSIENT_LOG)
    assert r["static_from_transient_mv"] == 53.0, r["static_from_transient_mv"]


def test_emit_without_external_static_keeps_ratio_dimensionally_sane(tmp_path):
    # With no Step-24 ir_drop.json, static_ir_mv falls back to the transient
    # report's own static. The V/mV mixup made dynamic_vs_static_ratio 2000x
    # instead of the tool's own "Dynamic/static ratio : 2.00".
    _rc, r = _emit_on_log(tmp_path, _TRANSIENT_LOG, static_json=None)
    assert r["static_ir_mv"] == 53.0, r["static_ir_mv"]
    assert r["dynamic_vs_static_ratio"] == 2.0, r["dynamic_vs_static_ratio"]
    assert r["max_dynamic_drop_mv"] == 106.0


def test_build_result_package_droop_recorded_when_present():
    r = E.build_result(
        worst_dyn_mv=72.0, vdd_v=1.8, static_tr_mv=40.0, ratio=1.8,
        package_droop_mv=9.0, power_net="VDD", period_ns=8.0,
        period_source="sdc_create_clock", steps=50, timestep_s=2e-11,
        current_model="vectored", cap_model="on-die-cap 3.10e-12F")
    assert r["package_ldidt_droop_mv"] == 9.0
    assert r["current_model"] == "vectored"


# ── skip-flip (§4.05): no-VCD is NOT a skip anymore; missing-input / no-PDN are ──

def test_skip_result_missing_inputs_default_status():
    s = E.skip_result("missing --def")
    assert s["status"] == "SKIPPED_MISSING_INPUTS"
    assert s["dynamic_ir_report_emitted"] is False
    assert s["analysis_mode"] == "transient_psm"


def test_skip_result_no_pdn_status():
    s = E.skip_result("no SPECIALNETS", status="SKIPPED_NO_PDN")
    assert s["status"] == "SKIPPED_NO_PDN"


# ── LIBERTY is a REQUIRED transient input (runner must wire pdk.liberty) ─────────

def test_liberty_is_a_required_input():
    # the transient solve needs the cell timing/power models; a missing liberty
    # is an honest skip, and all-present means the emit proceeds (no skip).
    assert E.missing_required_inputs("d.def", "t.lef", "c.lef", None) \
        == ["--liberty"]
    assert E.missing_required_inputs("d.def", "t.lef", "c.lef", "x.lib") == []
    # DEF / LEF still required too.
    assert "--def" in E.missing_required_inputs(None, "t", "c", "l")
    assert "--tech-lef" in E.missing_required_inputs("d", None, "c", "l")


def _synth_project(tmp_path, with_liberty: bool, with_pdn: bool):
    """Minimal run-dir layout the emitter auto-discovers. DEF has no SPECIALNETS
    unless with_pdn, so the emit reaches the (docker-free) no-PDN skip — enough
    to prove it got PAST the missing-inputs gate without needing a container."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    body = "DESIGN chip_top ;\n"
    if with_pdn:
        body += ("SPECIALNETS 1 ;\n- VDD ( * VDD ) + USE POWER ;\n"
                 "END SPECIALNETS\n")
    body += "END DESIGN\n"
    (pnr / "chip_top.def").write_text(body)
    pdk = tmp_path / "input" / "pdk"
    (pdk / "lef").mkdir(parents=True)
    (pdk / "lef" / "sky_tech.lef").write_text("LAYER MET1 ;\n")
    (pdk / "lef" / "sky_macro.lef").write_text("MACRO m ;\n")
    if with_liberty:
        (pdk / "liberty").mkdir(parents=True)
        (pdk / "liberty" / "cells_typ.lib").write_text("library(x){}\n")
    return tmp_path


def test_emit_path_with_resolved_liberty_does_not_skip_missing_inputs(tmp_path):
    # LIBERTY present (as the runner now wires pdk.liberty) → the emit gets PAST
    # the missing-inputs gate and reaches the transient path (here the honest
    # no-PDN skip, since this synthetic DEF has no power grid). The point:
    # status is NOT SKIPPED_MISSING_INPUTS.
    proj = _synth_project(tmp_path, with_liberty=True, with_pdn=False)
    out = proj / "dynamic_ir.json"
    rc = E.main(["--project", str(proj), "--out", str(out)])
    payload = json.loads(out.read_text())
    assert payload["status"] != "SKIPPED_MISSING_INPUTS"
    assert payload["status"] == "SKIPPED_NO_PDN"   # reached emit(), not missing
    assert rc == 0


def test_emit_path_without_liberty_honestly_skips_missing_inputs(tmp_path):
    # genuine no-liberty → the honest SKIPPED_MISSING_INPUTS is preserved.
    proj = _synth_project(tmp_path, with_liberty=False, with_pdn=True)
    out = proj / "dynamic_ir.json"
    E.main(["--project", str(proj), "--out", str(out)])
    payload = json.loads(out.read_text())
    assert payload["status"] == "SKIPPED_MISSING_INPUTS"
    assert "--liberty" in payload["reason"]


def test_auto_discover_finds_project_liberty(tmp_path):
    proj = _synth_project(tmp_path, with_liberty=True, with_pdn=True)
    disc = E._auto_discover(proj)
    assert disc["liberty"] is not None
    assert disc["liberty"].name == "cells_typ.lib"


def test_no_vcd_skip_marker_is_gone():
    # the emitter no longer produces a "SKIPPED_NO_VCD" marker — transient needs
    # no VCD. (The gate still tolerates the legacy string for old reports.)
    assert "find_vcd" in dir(E)          # helper kept (future vectored path)
    # a default skip is missing-inputs, never no-vcd.
    assert E.skip_result("x")["status"] != "SKIPPED_NO_VCD"


# ── gate honors the honest skip markers ─────────────────────────────────────────

def test_gate_honors_missing_inputs_skip(tmp_path):
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps(E.skip_result("missing --liberty")))
    res = G.check(j, 1.8)
    assert res["verdict"] == "SKIPPED_CONDITION"
    assert G.main([str(j)]) == 0  # skip is rc 0, not a blocker


def test_gate_honors_no_pdn_skip(tmp_path):
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps(E.skip_result("no PDN", status="SKIPPED_NO_PDN")))
    assert G.check(j, 1.8)["verdict"] == "SKIPPED_CONDITION"


def test_gate_no_psm_line_error_is_honest_skip(tmp_path):
    # ERROR_NO_PSM_IR sets dynamic_ir_report_emitted False → the gate treats the
    # dynamic tier as a non-blocking SKIP (static IR sign-off stays authoritative).
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"status": "ERROR_NO_PSM_IR",
                             "dynamic_ir_report_emitted": False,
                             "reason": "grid disconnected"}))
    assert G.check(j, 1.8)["verdict"] == "SKIPPED_CONDITION"


def test_gate_garbage_without_marker_still_fails(tmp_path):
    # §4.05: a report with no droop value AND no skip marker is FAIL, never SKIP.
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"unrelated": 1}))
    assert G.check(j, 1.8)["verdict"] == "FAIL"


# ── gate reads the emitter's own budget_pct (dynamic tier is looser) ────────────

def test_gate_uses_report_budget_pct(tmp_path):
    # emitter writes budget_pct=15; 200mV < 15%*1.8V(=270mV) → PASS with no CLI
    # budget. A stricter report budget_pct=10 (180mV) would FAIL the same droop.
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"dynamic_ir_report_emitted": True,
                             "max_dynamic_drop_mv": 200.0, "vdd": 1.8,
                             "budget_pct": 15.0}))
    res = G.check(j, None, None)  # no CLI budget → use the report's 15%
    assert res["verdict"] == "PASS" and res["budget_pct"] == 15.0

    j.write_text(json.dumps({"dynamic_ir_report_emitted": True,
                             "max_dynamic_drop_mv": 200.0, "vdd": 1.8,
                             "budget_pct": 10.0}))
    assert G.check(j, None, None)["verdict"] == "FAIL"


def test_gate_cli_budget_overrides_report(tmp_path):
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"dynamic_ir_report_emitted": True,
                             "max_dynamic_drop_mv": 200.0, "vdd": 1.8,
                             "budget_pct": 15.0}))
    # explicit CLI 10% (180mV) beats the report's 15% → FAIL
    assert G.check(j, None, 10.0)["verdict"] == "FAIL"


def test_gate_default_budget_when_no_report_budget(tmp_path):
    # no budget in report, no CLI → module default (15%). 250mV < 270mV → PASS.
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps({"dynamic_ir_report_emitted": True,
                             "max_dynamic_drop_mv": 250.0, "vdd": 1.8}))
    res = G.check(j, None, None)
    assert res["budget_pct"] == G._DEFAULT_BUDGET_PCT == 15.0
    assert res["verdict"] == "PASS"


# ── VCD helpers retained (optional; future vectored refinement) ─────────────────

def test_find_vcd_absent_is_none(tmp_path):
    assert E.find_vcd(tmp_path) is None


def test_discover_vcd_scope_still_works():
    vcd = ("$scope module tb $end\n$scope module u_dut $end\n"
           "$upscope $end\n$upscope $end\n")
    assert E.discover_vcd_scope(vcd) == "tb/u_dut"
