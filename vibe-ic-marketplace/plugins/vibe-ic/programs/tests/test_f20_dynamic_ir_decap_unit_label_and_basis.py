"""F20 — step 24's dynamic IR: the decap's unit, a MEASURED "genuine" label,
and one power basis for the static and the dynamic tier.

Every tool transcript here is real vibeic-eda 0.3.79 output (OpenROAD
26Q3-2963-gc73a322d30) on a copy of spm run23 (gf180mcuD), project path
replaced by <project>:

  calibration/dynamic_ir_decap_measured_positive.log    decap 1e-9 F, in the
      session's unit: VDD 1.48e-02 -> 1.37e-02 V, VSS 1.68e-02 -> 1.53e-02 V
  calibration/dynamic_ir_decap_unresolved_negative.log  decap 1e-12 F: the
      droop equals the quasi-static bound (ratio 2.00)
  fixtures/dynamic_ir_f20/raw_decap_1e-9.log            the pre-F20 deck's raw
      `-decap_cap 1e-09`: modelled and printed as 1.00e-21 F
  fixtures/dynamic_ir_f20/basis_quasi_static.log        VDD+VSS transient on
      DEF + SDC + propagated clocks + SPEF + cell and IO liberties
  fixtures/dynamic_ir_f20/static_ir_em.log              the runner's static
      session on the same basis (21.9 mW, VDD 7.41 / VSS 8.39 mV)
  fixtures/librelane_irdrop/transient_decap_1e-{9,12}_session_unit.rpt
      `Vibeic.TransientIR` with the decap in the session's unit

Only the tool's own execution is replaced (the transcript it would have
written); every reader, the deck builders and the runner helpers are the
shipped code. The controls are written so origin/main answers them WRONGLY
rather than crashing: optional arguments are passed only where the function
takes them.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dynamic_ir_vectored_emit as E  # noqa: E402
from _stated_eda_image import state_the_image  # noqa: E402


@pytest.fixture(autouse=True)
def _stated_image(monkeypatch):
    """Every test here STATES its EDA image: none may inherit this host's
    docker, so the file gives one verdict on a docker host and inside the
    vibeic-eda image (no docker client) alike."""
    return state_the_image(monkeypatch)

_FIX = _PROGRAMS / "tests" / "fixtures" / "dynamic_ir_f20"
_CAL = _PROGRAMS / "calibration"
_LL = _PROGRAMS / "tests" / "fixtures" / "librelane_irdrop"
_PLUGIN = _PROGRAMS / "librelane_plugins" / "librelane_plugin_vibeic"


def _kw(fn, **kw):
    """Only the keywords `fn` takes: the pre-F20 code answers, not crashes."""
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kw.items() if k in params}


def _views(tmp_path):
    tech = tmp_path / "t.lef"
    tech.write_text("VERSION 5.8 ;\n")
    cell = tmp_path / "c.lef"
    cell.write_text("MACRO CORE_BUF\nEND CORE_BUF\n")
    lib = tmp_path / "cells__tt_025C_5v00.lib"
    lib.write_text("library(neutral) {}\n")
    d = tmp_path / "top.def"
    d.write_text("DESIGN top ;\nSPECIALNETS 2 ;\n- VDD ( * VDD ) + USE POWER ;\n"
                 "- VSS ( * VSS ) + USE GROUND ;\nEND SPECIALNETS\nEND DESIGN\n")
    sdc = tmp_path / "constraint.sdc"
    sdc.write_text("create_clock -name clk -period 24.0 [get_ports clk]\n")
    spef = tmp_path / "top.spef"
    spef.write_text("*SPEF \"IEEE 1481-1998\"\n")
    return tech, cell, lib, d, sdc, spef


def _emit(tmp_path, monkeypatch, log, *, decap=None, net=None, static_json=None,
          basis=True):
    tech, cell, lib, d, sdc, spef = _views(tmp_path)
    decks = []

    def fake(_container, _cmd, *_a, **_kw):
        decks.append((tmp_path / "out" / "dynamic_ir_transient.tcl").read_text())
        return 0, log, ""

    monkeypatch.setattr(E._dw, "run_docker_supervised", fake)
    out = tmp_path / "out" / "dynamic_ir.json"
    kw = dict(def_file=d, tech_lef=tech, cell_lef=cell, liberty=lib, macro_lefs=[],
              sdc=sdc if basis else None, out_json=out, power_net=net,
              container="fixture", metal_prefix="Metal", static_json=static_json,
              budget_pct=15.0, period_ns=24.0, steps=100, decap_cap=decap)
    kw.update(_kw(E.emit, spef=spef if basis else None,
                  extra_liberties=[str(tmp_path / "io__tt_025C_5v00.lib")] if basis else []))
    rc, payload = E.emit(**kw)
    return rc, payload, decks


# ─── 1. the decap's unit ─────────────────────────────────────────────────────

def test_the_deck_passes_the_decap_in_the_sessions_unit(tmp_path):
    """RED on main: `-decap_cap 1e-09` — farads read as pF (1.00e-21 F)."""
    tech, cell, lib, d, *_ = _views(tmp_path)
    tcl = E._build_transient_tcl(d, tech, cell, lib, [], None, "VDD", 24.0, 100,
                                 1e-9, {}, "Metal")
    assert "-decap_cap 1e-09" not in tcl and "-decap_cap 1e-9 " not in tcl, tcl
    assert "-decap_cap [expr {1e-09 / [sta::capacitance_ui_sta 1.0]}]" in tcl, tcl


def test_each_net_is_first_solved_quasi_static_as_the_reference(tmp_path):
    tech, cell, lib, d, *_ = _views(tmp_path)
    tcl = E._build_transient_tcl(d, tech, cell, lib, [], None, ["VDD", "VSS"], 24.0,
                                 100, 1e-9, {}, "Metal")
    for net in ("VDD", "VSS"):
        ref = tcl.find(f"=== DYN_IR_REF {net} ")
        solve = tcl.find(f"=== DYN_IR PSM {net} ")
        assert 0 <= ref < solve, tcl
        ref_cmd = tcl[ref:solve]
        assert "-decap_cap" not in ref_cmd and "-transient" in ref_cmd


def test_without_a_decap_there_is_one_solve_per_net(tmp_path):
    tech, cell, lib, d, *_ = _views(tmp_path)
    tcl = E._build_transient_tcl(d, tech, cell, lib, [], None, "VDD", 24.0, 100,
                                 None, {}, "Metal")
    assert "DYN_IR_REF" not in tcl and "-decap_cap" not in tcl
    assert tcl.count("analyze_power_grid") == 1


def test_a_decap_the_solve_did_not_model_is_refused(tmp_path, monkeypatch):
    """The real pre-F20 transcript: 1e-9 requested, 1.00e-21 F modelled.
    RED on main: published rc 0 as a genuine decap-aware droop."""
    rc, payload, _ = _emit(tmp_path, monkeypatch,
                           (_FIX / "raw_decap_1e-9.log").read_text(), decap=1e-9)
    assert rc == 1, payload
    assert payload.get("status") == "ERROR_DECAP_READBACK", payload
    assert payload["dynamic_ir_report_emitted"] is False
    assert "1e-21" in payload["reason"]
    import dynamic_ir_drop_check as G
    assert G.main([str(tmp_path / "out" / "dynamic_ir.json")]) != 0


def test_the_tool_step_converts_the_decap_and_solves_a_reference():
    """RED on main: `lappend arg_list -decap_cap $::env(VIBEIC_DECAP_CAP)`."""
    tcl = (_PLUGIN / "transient_ir.tcl").read_text()
    assert "-decap_cap $::env(VIBEIC_DECAP_CAP)" not in tcl
    assert "sta::capacitance_ui_sta 1.0" in tcl
    assert tcl.index("VIBEIC_TRANSIENT_REF") < tcl.index("-decap_cap")






# ─── 2. "genuine" is a measured property ─────────────────────────────────────

def test_a_decap_that_measurably_lowers_the_droop_is_genuine(tmp_path, monkeypatch):
    """The over-correction guard: "flag every decap solve a bound" would
    understate a solve whose decap measurably lowered the droop."""
    rc, payload, _ = _emit(tmp_path, monkeypatch,
                           (_CAL / "dynamic_ir_decap_measured_positive.log").read_text(),
                           decap=1e-9)
    assert rc == 0, payload
    assert payload["scaled_static_bound"] is False
    assert "genuine dynamic droop" in payload["disclosure"]


def test_a_printed_capacitance_with_the_ratio_unchanged_is_the_bound(tmp_path, monkeypatch):
    """1 pF, unit right, printed 1.00e-12 F, droop = quasi-static bound.
    RED on main: 'on-die cap printed => genuine'."""
    rc, payload, _ = _emit(tmp_path, monkeypatch,
                           (_CAL / "dynamic_ir_decap_unresolved_negative.log").read_text(),
                           decap=1e-12)
    assert rc == 0, payload
    assert payload["scaled_static_bound"] is True, payload["disclosure"]
    assert "genuine dynamic" not in payload["disclosure"].lower()
    assert payload.get("decap_evidence", {}).get("state") == "DECAP_BELOW_RESOLUTION"


def test_the_measured_evidence_is_per_net(tmp_path, monkeypatch):
    rc, payload, _ = _emit(tmp_path, monkeypatch,
                           (_CAL / "dynamic_ir_decap_measured_positive.log").read_text(),
                           decap=1e-9)
    per = payload.get("per_net") or {}
    assert sorted(per) == ["VDD", "VSS"], payload
    assert per["VDD"]["decap"]["quasi_static_bound_v"] == pytest.approx(0.0148)
    assert per["VDD"]["decap"]["dynamic_v"] == pytest.approx(0.0137)
    assert per["VSS"]["decap"]["state"] == "DECAP_MEASURED"


def test_a_printed_on_die_capacitance_alone_does_not_earn_the_label():
    """build_result given only the tool's capacitance-model string.
    RED on main: `cap_model.startswith('on-die-cap')` => genuine."""
    r = E.build_result(worst_dyn_mv=14.8, vdd_v=5.0, static_tr_mv=7.41, ratio=2.0,
                       package_droop_mv=None, power_net="VDD", period_ns=24.0,
                       period_source="sdc_create_clock", steps=100, timestep_s=2.4e-10,
                       current_model="vectorless", cap_model="on-die-cap 1.00e-21F")
    assert r["scaled_static_bound"] is True


def _blocks(name):
    b = E.transient_blocks((_CAL / name).read_text())
    return b[("ref", "VDD")], b[("psm", "VDD")]


def test_one_unit_of_printed_precision_is_not_a_measured_difference():
    decap_effect = getattr(E, "decap_effect", None)
    assert decap_effect is not None, "no measured label on this tree"
    ref, solve = _blocks("dynamic_ir_decap_measured_positive.log")
    # The same real block with the droop printed one unit below the bound
    # (the 100 pF row: 1.48e-02 -> 1.47e-02): could be rounding, not decap.
    one_ulp = solve.replace("Worst dynamic IR drop  : 1.37e-02 V",
                            "Worst dynamic IR drop  : 1.47e-02 V")
    assert decap_effect(ref, one_ulp, 1e-9)["state"] == "DECAP_BELOW_RESOLUTION"
    two_ulp = solve.replace("Worst dynamic IR drop  : 1.37e-02 V",
                            "Worst dynamic IR drop  : 1.46e-02 V")
    assert decap_effect(ref, two_ulp, 1e-9)["state"] == "DECAP_MEASURED"


def test_the_readback_is_against_the_request_not_the_print():
    decap_effect = getattr(E, "decap_effect", None)
    assert decap_effect is not None
    ref, solve = _blocks("dynamic_ir_decap_measured_positive.log")
    assert decap_effect(ref, solve, 1e-9)["genuine"] is True
    # The same solve asked about another request: a different subject.
    assert decap_effect(ref, solve, 1e-8)["state"] == "DECAP_READBACK_MISMATCH"
    # No reference solve: nothing to measure against.
    assert decap_effect("", solve, 1e-9)["state"] == "NO_QUASI_STATIC_REFERENCE"






# ─── 3. one power basis ──────────────────────────────────────────────────────

def test_the_transient_deck_reads_the_declared_basis(tmp_path):
    """RED on main: no SPEF, no IO liberty, SDC read inside a silent catch."""
    tech, cell, lib, d, sdc, spef = _views(tmp_path)
    io = str(tmp_path / "io__tt_025C_5v00.lib")
    tcl = E._build_transient_tcl(d, tech, cell, lib, [], sdc, "VDD", 24.0, 100, None,
                                 {}, "Metal",
                                 **_kw(E._build_transient_tcl, spef=spef,
                                       extra_liberties=[io]))
    tail = tcl[tcl.index("read_def"):]
    assert f"read_liberty {io}" in tail
    assert "read_sdc" in tail and "set_propagated_clock [all_clocks]" in tail
    assert f"read_spef {spef}" in tail
    assert "IR_BASIS_SDC_UNREAD" in tail and "IR_BASIS_SPEF_UNREAD" in tail


def test_the_dynamic_tier_answers_about_every_supply_net(tmp_path, monkeypatch):
    """RED on main: VDD only, while the static tier's worst net is VSS."""
    rc, payload, decks = _emit(tmp_path, monkeypatch,
                               (_FIX / "basis_quasi_static.log").read_text())
    assert rc == 0, payload
    assert payload.get("nets_analysed") == ["VDD", "VSS"], payload
    assert payload["power_net"] == "VSS" and payload["max_dynamic_drop_mv"] == 16.8
    assert "-net VSS -transient" in decks[0]


def _static_record(tmp_path, *, same=True):
    tech, cell, lib, d, sdc, spef = _views(tmp_path)
    io = str(tmp_path / "io__tt_025C_5v00.lib")
    log = (_FIX / "static_ir_em.log").read_text()
    basis = E.power_basis(d, sdc, spef if same else None, [str(lib), io], log=log)
    j = tmp_path / "ir_drop.json"
    j.write_text(json.dumps({"worst_ir_uv": 8390.0, "power_basis": basis}))
    return j


def test_both_numbers_are_reported_on_one_basis(tmp_path, monkeypatch):
    """RED on main: the Step-24 static number was reported beside the
    dynamic one whatever it was solved on (15.0 mV beside 1.25 mV)."""
    j = _static_record(tmp_path, same=False)
    rc, payload, _ = _emit(tmp_path, monkeypatch,
                           (_FIX / "basis_quasi_static.log").read_text(), static_json=j)
    assert payload["static_ir_mv"] == 8.39 and payload["exceeds_static"] is True
    tier = payload.get("static_tier") or {}
    assert tier.get("reason") == "the Step-24 static record is on another power basis"


def test_the_step24_record_on_the_same_basis_is_reported_beside_it(tmp_path, monkeypatch):
    j = _static_record(tmp_path, same=True)
    rc, payload, _ = _emit(tmp_path, monkeypatch,
                           (_FIX / "basis_quasi_static.log").read_text(), static_json=j)
    assert rc == 0
    assert payload["static_tier"]["source"] == "step24 ir_drop.json, same basis and power"
    assert payload["power_basis"]["id"] == json.loads(j.read_text())["power_basis"]["id"]
    assert payload["power_basis"]["total_power_w"] == pytest.approx(0.0219)
    assert payload["power_basis"]["complete"] is True


def test_a_basis_read_that_failed_is_recorded_not_swallowed(tmp_path):
    tech, cell, lib, d, sdc, spef = _views(tmp_path)
    rec = E.power_basis(d, sdc, spef, [str(lib)],
                        log="IR_BASIS_SPEF_UNREAD: no such file\nTotal power : 1.0e-03 W\n")
    assert rec["unread"] == ["IR_BASIS_SPEF_UNREAD"] and rec["complete"] is False


# ─── the runner: both tiers from one declaration ─────────────────────────────

def _runner_project(tmp_path, *, stale_spef=False):
    import os
    import phase3_one_shot_runner as R
    from test_phase3_signoff_chain_organic import _mk_project, _fake_pdk
    project = _mk_project(tmp_path)
    pnr = R._pl.pnr_dir(project)
    (pnr / "constraint.sdc").write_text("create_clock -period 24 [get_ports clk]\n")
    spef_dir = R._pl.extracted_dir(project)
    spef_dir.mkdir(parents=True, exist_ok=True)
    spef = spef_dir / "chip_top.spef"
    spef.write_text("*SPEF\n")
    if stale_spef:
        t = (pnr / "chip_top.def").stat().st_mtime
        os.utime(spef, (t - 100, t - 100))
    rpt = R._pl.reports_phase3_dir(project)
    rpt.mkdir(parents=True, exist_ok=True)
    io = "/foss/pdks/sky130A/io__tt.lib"
    (rpt / "io_pad_chip_top.json").write_text(json.dumps({"io_library_liberty": [io]}))
    pdk = _fake_pdk()
    pdk.liberty = "/foss/pdks/sky130A/cells__tt.lib"
    return R, project, pdk, io
