#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P0 — dynamic (transient) IR-drop + per-layer metal-density gates.

Two deterministic sign-off axes the survey found missing:
  * dynamic_ir_drop_check.py — transient droop vs budget (static IR was covered,
    dynamic was a keyword string only).
  * metal_layer_density_check.py — PER-LAYER metal density vs a window (the existing
    metal_fill_density_check.py gates ROW utilization, the wrong axis vs the foundry
    CMP / met_min_ca_density rule).
Both §4.05: absent/mis-shaped report never yields a pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dynamic_ir_drop_check as DIR  # noqa: E402
import metal_layer_density_check as MLD  # noqa: E402


# ── dynamic IR ───────────────────────────────────────────────────────────────

def test_dynamic_ir_json_under_budget_passes(tmp_path):
    r = tmp_path / "dvd.json"
    r.write_text(json.dumps({"max_dynamic_drop_mv": 90, "vdd": 1.8}))
    res = DIR.check(r, None, 10.0)   # budget = 180 mV
    assert res["verdict"] == "PASS"
    assert res["budget_mv"] == 180.0


def test_dynamic_ir_over_budget_fails(tmp_path):
    r = tmp_path / "dvd.json"
    r.write_text(json.dumps({"worst_transient_drop_mv": 250, "vdd": 1.8}))
    assert DIR.check(r, None, 10.0)["verdict"] == "FAIL"


def test_dynamic_ir_pct_schema(tmp_path):
    r = tmp_path / "dvd.json"
    r.write_text(json.dumps({"worst_transient_drop_percent": 4.0, "vdd": 1.8}))
    # 4% of 1.8V = 72 mV < 180 mV budget → PASS
    assert DIR.check(r, None, 10.0)["verdict"] == "PASS"


def test_dynamic_ir_rpt_only_dynamic_section(tmp_path):
    r = tmp_path / "ir.rpt"
    # a static line must be ignored; only the transient line is read.
    r.write_text("Static IR drop: 500 mV\nWorst transient droop (DVD): 120 mV\n")
    res = DIR.check(r, 1.8, 10.0)
    assert res["verdict"] == "PASS"
    assert res["worst_transient_droop_mv"] == 120.0


def test_dynamic_ir_absent_is_io_error(tmp_path):
    assert DIR.check(tmp_path / "nope.json", 1.8, 10.0)["verdict"] == "IO_ERROR"
    assert DIR.main([str(tmp_path / "nope.json")]) == 2


def test_dynamic_ir_no_value_fails_not_pass(tmp_path):
    # §4.05: a report present but with no dynamic droop value → FAIL, never PASS.
    r = tmp_path / "empty.json"
    r.write_text(json.dumps({"unrelated": 1}))
    assert DIR.check(r, 1.8, 10.0)["verdict"] == "FAIL"


def test_dynamic_ir_mv_without_vdd_fails(tmp_path):
    r = tmp_path / "novdd.json"
    r.write_text(json.dumps({"max_dynamic_drop_mv": 90}))
    assert DIR.check(r, None, 10.0)["verdict"] == "FAIL"


# ── per-layer metal density ──────────────────────────────────────────────────

def test_metal_density_all_in_window_passes(tmp_path):
    r = tmp_path / "d.json"
    r.write_text(json.dumps({"layers": {"met1": 0.42, "met2": 0.55, "met3": 0.48}}))
    win = tmp_path / "w.json"
    win.write_text(json.dumps({"met1": [0.3, 0.7], "met2": [0.3, 0.7],
                               "met3": [0.3, 0.7]}))
    res = MLD.check(r, MLD._load_windows(win), None, None)
    assert res["verdict"] == "PASS"


def test_metal_density_layer_outside_window_fails(tmp_path):
    r = tmp_path / "d.json"
    r.write_text(json.dumps({"layers": {"met1": 0.12, "met2": 0.55}}))
    res = MLD.check(r, {"met1": (0.3, 0.7), "met2": (0.3, 0.7)}, None, None)
    assert res["verdict"] == "FAIL"
    assert any("met1" in f for f in res["failures"])


def test_metal_density_percentage_schema(tmp_path):
    r = tmp_path / "d.rpt"
    r.write_text("met1 density = 42.3%\nmet2 density = 55.0%\n")
    res = MLD.check(r, {"met1": (0.3, 0.7), "met2": (0.3, 0.7)}, None, None)
    assert res["verdict"] == "PASS"
    assert res["per_layer"]["met1"]["density"] == 0.423


def test_metal_density_unchecked_layer_is_not_pass(tmp_path):
    # §4.05: a metal layer with a density but no window (and no default) → NOT pass.
    r = tmp_path / "d.json"
    r.write_text(json.dumps({"layers": {"met1": 0.42, "met9": 0.50}}))
    res = MLD.check(r, {"met1": (0.3, 0.7)}, None, None)
    assert res["verdict"] == "FAIL"
    assert "met9" in res["unchecked_layers"]


def test_metal_density_generic_default_window(tmp_path):
    r = tmp_path / "d.json"
    r.write_text(json.dumps({"layers": {"met1": 0.42, "met2": 0.55}}))
    res = MLD.check(r, {}, MLD._DEFAULT_MIN, MLD._DEFAULT_MAX)
    assert res["verdict"] == "PASS"
    assert "window_note" in res


def test_metal_density_absent_is_io_error(tmp_path):
    assert MLD.check(tmp_path / "nope.json", {}, None, None)["verdict"] == "IO_ERROR"
    assert MLD.main([str(tmp_path / "nope.json")]) == 2


def test_metal_density_empty_report_fails_not_pass(tmp_path):
    # §4.05: a report with no per-layer metal density → FAIL, never PASS.
    r = tmp_path / "d.json"
    r.write_text(json.dumps({"row_utilization": 0.4}))   # wrong-axis data only
    assert MLD.check(r, {}, 0.3, 0.7)["verdict"] == "FAIL"
