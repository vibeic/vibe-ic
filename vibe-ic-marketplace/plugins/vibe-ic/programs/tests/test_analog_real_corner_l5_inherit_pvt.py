#!/usr/bin/env python3
"""tests/test_analog_real_corner_l5_inherit_pvt.py

Pure-helper tests for the two analog corner-sweep enhancements in
analog_real_corner_sweep.py — no live SPICE required (ngspice is not on the CI
host). They exercise the deterministic helpers directly:

  GAP-ANALOG-2 (inherit the L5 block spec into the sweep)
    * l5_block_specs / resolve_spec read ONLY phase1/generated_docs/
      L5_ADI_SPEC.json (a Phase-1 generated doc — §4.05 blind-legal) and set
      the verdict target + the deck reference/divider from the L5 values.
    * When L5 lacks a value the helpers FALL BACK to the static per-type
      default and DISCLOSE the fallback (never fabricate a spec value).
    * render_deck rewrites the deck's OWN Vref/Vdd source lines to the
      inherited values (not the static 1.8-V literals).

  GAP-ANALOG-3 (real PVT corners, not arithmetic derivations)
    * build_pvt_grid marks a corner simulator_run=true ONLY when it was really
      simulated (present in real_sims with a log); full_pvt_sweep_executed is
      true ONLY when EVERY corner really ran.
    * A corner with no model/section (absent from real_sims), or one whose ok /
      log is missing, stays HONESTLY DERIVED with simulator_run=false — never a
      false "real" claim (negative no-leak).
    * render_deck stamps the real .lib section + a real .temp card per corner.

chip-AGNOSTIC: every fixture keys on the L5 `specs[].name` schema field and a
generic block name — no chip / vendor / SKU literal.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent / "analog_real_corner_sweep.py")
PDK_LIB = "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice"


def _load_module():
    spec = importlib.util.spec_from_file_location("analog_real_corner_sweep",
                                                  PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# LDO spec matching u_hawaii_adc's structure (1.2 V core, NOT the generic
# 1.8 V) — but expressed with a GENERIC block name so the test is chip-agnostic.
_LDO_SPECS_FULL = {
    "specs": [
        {"name": "Vout", "target": 1.2, "min": 1.1, "max": 1.3, "unit": "V"},
        {"name": "Iout", "target": 0.5, "min": 0.1, "max": 1.0, "unit": "mA"},
        {"name": "Vin", "target": 1.8, "min": 1.6, "max": 2.0, "unit": "V"},
        {"name": "Dropout", "max": 0.5, "unit": "V"},
        {"name": "PSRR", "min": 40.0, "unit": "dB"},
        {"name": "Iq", "max": 50.0, "unit": "µA"},
    ],
    "source": "L5_ANALOG_SPEC.md",
}


def _write_l5(project: Path, block: str, btype: str, spec):
    g = project / "phase1" / "generated_docs"
    g.mkdir(parents=True, exist_ok=True)
    (g / "L5_ADI_SPEC.json").write_text(json.dumps({
        "schema_version": 2, "doc_class": "adi_spec",
        "analog_blocks": [{"name": block, "type": btype, "spec": spec}],
    }))
    return project


# ───────────────────────── GAP-ANALOG-2 ─────────────────────────

def test_l5_block_specs_parses_named_values(tmp_path):
    m = _load_module()
    _write_l5(tmp_path, "u_reg", "ldo", _LDO_SPECS_FULL)
    got = m.l5_block_specs(tmp_path, "u_reg", "ldo")
    assert got["vout"]["value"] == 1.2
    assert got["vin"]["value"] == 1.8
    assert got["iout"]["value"] == 0.5
    assert got["psrr"]["value"] == 40.0 and got["psrr"]["bound"] == "min"
    assert got["iq"]["value"] == 50.0 and got["iq"]["bound"] == "max"


def test_resolve_spec_inherits_l5_target_not_static(tmp_path):
    m = _load_module()
    _write_l5(tmp_path, "u_reg", "ldo", _LDO_SPECS_FULL)
    r = m.resolve_spec(tmp_path, "u_reg", "ldo")
    # verdict target is the L5 1.2 V core, NOT the static 1.8 V default.
    assert r["target"] == 1.2
    assert r["target"] != m.TARGETS["ldo"]["target"]  # != 1.8
    assert r["target_source"] == "L5"
    # tolerance derived from the L5 1.1-1.3 range (± ~0.083), not static 0.05.
    assert abs(r["tol"] - (0.1 / 1.2)) < 1e-6
    # deck reference tracks the target through the fixed 2:1 divider: 1.2/2.
    assert r["deck_overrides"]["vref"] == pytest.approx(0.6)
    # supply inherited from the L5 Vin (headroom clears the output).
    assert r["deck_overrides"]["vdd"] == 1.8
    # the un-measured L5 requirements are recorded (measured=false), not faked.
    names = {sr["name"]: sr for sr in r["spec_requirements"]}
    assert names["psrr"]["value"] == 40.0 and names["psrr"]["measured"] is False
    assert names["iq"]["value"] == 50.0
    assert "iout" in names


def test_render_deck_uses_l5_reference_not_1v8(tmp_path):
    m = _load_module()
    _write_l5(tmp_path, "u_reg", "ldo", _LDO_SPECS_FULL)
    r = m.resolve_spec(tmp_path, "u_reg", "ldo")
    deck, applied = m.render_deck("ldo", "u_reg", "sky130", PDK_LIB, "tt",
                                  "m_pass", 40, deck_overrides=r["deck_overrides"])
    # the deck's Vref source line now regulates toward 1.2 V (Vref=0.6), and the
    # supply is the L5 Vin=1.8 — the static 0.9 / 3.3 literals are gone.
    assert "v_vref vref 0 0.6" in deck
    assert "v_vref vref 0 0.9" not in deck
    assert "v_vdd vdd 0 1.8" in deck
    assert "v_vdd vdd 0 3.3" not in deck
    assert applied.get("vref") == pytest.approx(0.6)
    assert applied.get("vdd") == 1.8


def test_resolve_spec_missing_value_falls_back_static_disclosed(tmp_path):
    m = _load_module()
    # L5 present but WITHOUT a Vout entry → the vout target must fall back.
    partial = {"specs": [{"name": "Iq", "max": 50.0, "unit": "µA"}],
               "source": "L5_ANALOG_SPEC.md"}
    _write_l5(tmp_path, "u_reg", "ldo", partial)
    r = m.resolve_spec(tmp_path, "u_reg", "ldo")
    assert r["target"] == m.TARGETS["ldo"]["target"]   # static 1.8
    assert r["target_source"] == "static_default"
    assert "target(vout)" in r["fields_fallback"]
    assert "deck.vref" in r["fields_fallback"]
    assert "fallback" in r["disclosure"].lower()
    # no vref override was fabricated for the missing Vout.
    assert "vref" not in r["deck_overrides"]
    # a rendered deck therefore keeps the static reference — no fabrication.
    deck, applied = m.render_deck("ldo", "u_reg", "sky130", PDK_LIB, "tt",
                                  "m_pass", 40, deck_overrides=r["deck_overrides"])
    assert "v_vref vref 0 0.9" in deck
    assert applied == {}


def test_resolve_spec_no_l5_file_is_static(tmp_path):
    m = _load_module()
    r = m.resolve_spec(tmp_path, "u_reg", "ldo")   # no phase1 dir at all
    assert r["target_source"] == "static_default"
    assert r["target"] == 1.8
    assert r["deck_overrides"] == {}


def test_no_leak_only_reads_l5_not_golden(tmp_path):
    """§4.05 negative no-leak: a golden/output file carrying a spec value must
    NOT be consulted — with no L5 present the resolver stays on the static
    default even though a golden Vout exists on disk."""
    m = _load_module()
    a = tmp_path / "phase3" / "analog" / "u_reg"
    a.mkdir(parents=True)
    # decoys the resolver must never read:
    (a / "output.json").write_text(json.dumps({"Vout": 0.8}))
    (a / "golden.json").write_text(json.dumps({"specs": [
        {"name": "Vout", "target": 0.8, "unit": "V"}]}))
    (a / "harness.env").write_text("VOUT=0.8\n")
    r = m.resolve_spec(tmp_path, "u_reg", "ldo")
    assert r["target"] == 1.8               # static default, NOT the golden 0.8
    assert r["target_source"] == "static_default"
    assert m.l5_block_specs(tmp_path, "u_reg", "ldo") == {}


def test_l5_bare_string_spec_is_not_structured(tmp_path):
    m = _load_module()
    # some L5 blocks carry `spec` as a bare string (e.g. "1.8 V, 1.2 V, 125 C")
    # — that is NOT structured data and must yield {} (→ static fallback).
    _write_l5(tmp_path, "u_mod", "delta_sigma", "1.8 V, 1.2 V, 125 C")
    assert m.l5_block_specs(tmp_path, "u_mod", "delta_sigma") == {}
    r = m.resolve_spec(tmp_path, "u_mod", "delta_sigma")
    assert r["target_source"] == "static_default"


def test_resolve_spec_is_chip_agnostic_by_schema(tmp_path):
    m = _load_module()
    # a DIFFERENT generic block name with the SAME schema resolves identically —
    # the logic keys on specs[].name, never a design name.
    _write_l5(tmp_path, "core_supply", "ldo", _LDO_SPECS_FULL)
    r = m.resolve_spec(tmp_path, "core_supply", "ldo")
    assert r["target"] == 1.2 and r["deck_overrides"]["vref"] == pytest.approx(0.6)


# ───────────────────────── GAP-ANALOG-3 ─────────────────────────

def _all_nine():
    return {(p, t): {"value": 1.2, "ok": True,
                     "log": f"phase3/analog/blk/sizing_loop/pvt_{p}_{t}.ngspice.log"}
            for p in ("ss", "tt", "ff") for t in ("m40c", "27c", "125c")}


def test_pvt_grid_all_real_marks_full_sweep():
    m = _load_module()
    grid, executed = m.build_pvt_grid(1.2, "base.log", _all_nine(), 0.05)
    assert len(grid) == 9
    assert executed == 9
    assert all(c["simulator_run"] is True for c in grid)
    assert all(c["_provenance"] == "real_ngspice" for c in grid)
    assert all(c["derived_from"] is None for c in grid)
    # the run_block flag: full ONLY when every corner really ran.
    assert (executed == len(grid)) is True


def test_pvt_grid_partial_only_tt_is_derived_rest():
    m = _load_module()
    real = {("tt", "27c"): {"value": 1.2, "ok": True, "log": "base.log"}}
    grid, executed = m.build_pvt_grid(1.2, "base.log", real, 0.05)
    assert executed == 1
    assert (executed == len(grid)) is False        # NOT a full PVT sweep
    tt = next(c for c in grid if c["name"] == "tt_27c")
    assert tt["simulator_run"] is True and tt["_provenance"] == "real_ngspice"
    derived = [c for c in grid if c["name"] != "tt_27c"]
    assert len(derived) == 8
    assert all(c["simulator_run"] is False for c in derived)
    assert all(c["_provenance"] == "DERIVED" for c in derived)
    assert all(c["derived_from"] for c in derived)


def test_pvt_grid_missing_section_stays_derived_no_false_real():
    """Negative no-leak: a corner with no model/section (absent from real_sims)
    stays DERIVED with simulator_run=false — no false 'real' claim."""
    m = _load_module()
    # ff section entirely unavailable (omitted) → its 3 corners must derive.
    real = {(p, t): {"value": 1.2, "ok": True, "log": f"pvt_{p}_{t}.log"}
            for p in ("ss", "tt") for t in ("m40c", "27c", "125c")}
    grid, executed = m.build_pvt_grid(1.2, "base.log", real, 0.05)
    assert executed == 6
    ff = [c for c in grid if c["process"] == "ff"]
    assert len(ff) == 3
    assert all(c["simulator_run"] is False for c in ff)
    assert all(c["_provenance"] == "DERIVED" for c in ff)
    assert (executed == len(grid)) is False


def test_pvt_grid_no_log_or_not_ok_never_claims_real():
    m = _load_module()
    # a corner present but WITHOUT a log, or with ok=False, must NOT be real —
    # §4.05: a real claim requires an on-disk ngspice log AND convergence.
    real = {
        ("tt", "27c"): {"value": 1.2, "ok": True, "log": "base.log"},
        ("ss", "27c"): {"value": 1.1, "ok": True, "log": None},   # no log
        ("ff", "27c"): {"value": 1.3, "ok": False, "log": "x.log"},  # failed
    }
    grid, executed = m.build_pvt_grid(1.2, "base.log", real, 0.05)
    assert executed == 1
    for name in ("ss_27c", "ff_27c"):
        c = next(x for x in grid if x["name"] == name)
        assert c["simulator_run"] is False
        assert c["_provenance"] == "DERIVED"


def test_pvt_grid_base_none_yields_null_values_not_fabricated():
    m = _load_module()
    grid, executed = m.build_pvt_grid(None, None, {}, 0.05)
    assert executed == 0
    assert all(c["vout_v"] is None for c in grid)   # never invents a number
    assert all(c["simulator_run"] is False for c in grid)


def test_render_deck_stamps_real_section_and_temp():
    m = _load_module()
    deck, _ = m.render_deck("ldo", "blk", "sky130", PDK_LIB, "ss",
                            "m_pass", 40, temp_c=-40)
    # the real ss process section is stamped into the .lib line ...
    assert "sky130.lib.spice ss" in deck
    # ... and a real operating-temperature card is injected before .control.
    assert ".temp -40" in deck
    idx_temp = deck.index(".temp -40")
    idx_ctrl = deck.index(".control")
    assert idx_temp < idx_ctrl              # temp card precedes the control block


def test_render_deck_no_temp_when_none():
    m = _load_module()
    deck, _ = m.render_deck("ldo", "blk", "sky130", PDK_LIB, "tt",
                            "m_pass", 40, temp_c=None)
    assert ".temp" not in deck              # 27 C base run stamps no temp card


@pytest.mark.parametrize("btype", ["ldo", "bandgap", "por", "delta_sigma",
                                   "comparator"])
def test_render_deck_all_btypes_render(btype):
    m = _load_module()
    knob, val = m.SWEEPS[btype][0]
    deck, _ = m.render_deck(btype, "blk", "sky130", PDK_LIB, "ff", knob, val,
                            temp_c=125)
    assert "{" not in deck                  # no leftover format placeholder
    assert deck.strip().endswith(".end")
    assert "sky130.lib.spice ff" in deck
