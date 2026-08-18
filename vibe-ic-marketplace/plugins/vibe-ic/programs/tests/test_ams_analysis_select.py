#!/usr/bin/env python3
"""Tests for ams_analysis_select.py — the frozen spec->analysis table lookup."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "ams_analysis_select.py"


def _run(target: Path, jpath: Path = None):
    cmd = [sys.executable, str(PROG), str(target)]
    if jpath:
        cmd += ["--json", str(jpath)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _summary(r) -> dict:
    return json.loads(r.stdout)["summary"]


# ---------------------------------------------------------------------------
# PASS — the table deterministically selects the right analysis subset.
# ---------------------------------------------------------------------------
def test_pass_amp_spec_selects_ac_tran_noise_and_op(tmp_path):
    spec = {
        "gain_db": 60,            # -> .ac
        "ugbw": {"value": 50e6},  # -> .ac
        "phase_margin": 60,       # -> .ac
        "slew": {"value": 10},    # -> .tran
        "settling_1pct": 100,     # -> .tran
        "input_noise": 5e-9,      # -> .noise
        "vout_dc": 0.9,           # -> .op
        "name": "ota",            # non-measurable, ignored
    }
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 0, r.stdout + r.stderr
    block = json.loads(jp.read_text())["summary"]["blocks"][0]
    assert block["pass"] is True
    # .op always present; ac/tran/noise selected; NO unrelated .dc/.pss/.mc
    assert block["analyses"] == [".op", ".ac", ".tran", ".noise"]


def test_pass_op_always_emitted_with_one_spec(tmp_path):
    # A single bias spec -> .op only (never empty, never extra cards).
    spec = {"iq": {"value": 20e-6, "unit": "A"}}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    r = _run(sp)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _summary(r)["blocks"][0]["analyses"] == [".op"]


def test_pass_monte_carlo_is_additive(tmp_path):
    # Mismatch concern -> .mc added ON TOP of the metric-driven analyses.
    spec = {
        "gain_db": 60,                       # -> .ac
        "offset_sigma": {"value": 1e-3},     # 'sigma' -> mc requested
        "vref": 1.2,                         # -> .op
    }
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    r = _run(sp)
    assert r.returncode == 0, r.stdout + r.stderr
    an = _summary(r)["blocks"][0]["analyses"]
    assert ".ac" in an and ".op" in an and ".mc" in an
    assert an[-1] == ".mc"  # mc wraps last in canonical order


def test_pass_explicit_mc_directive_object(tmp_path):
    spec = {"gain_db": 40, "monte_carlo": {"n": 500}}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    r = _run(sp)
    assert r.returncode == 0
    assert ".mc" in _summary(r)["blocks"][0]["analyses"]


def test_pass_pss_for_switched_cap_or_rf(tmp_path):
    spec = {"pnoise_jitter": 1e-12, "gain_db": 30}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    r = _run(sp)
    assert r.returncode == 0
    an = _summary(r)["blocks"][0]["analyses"]
    assert ".pss" in an and ".ac" in an


def test_pass_dc_sweep_spec(tmp_path):
    spec = {"line_reg": {"value": 0.1}, "load_reg": {"value": 0.2}}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    r = _run(sp)
    assert r.returncode == 0
    assert _summary(r)["blocks"][0]["analyses"] == [".op", ".dc"]


def test_pass_nested_specs_container(tmp_path):
    spec = {"specs": {"gain_db": 60, "vref": 1.0}}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    r = _run(sp)
    assert r.returncode == 0
    assert _summary(r)["blocks"][0]["analyses"] == [".op", ".ac"]


# ---------------------------------------------------------------------------
# Determinism — same spec always yields same set (the whole point).
# ---------------------------------------------------------------------------
def test_determinism_identical_set_twice(tmp_path):
    spec = {"gain_db": 60, "slew": 10, "input_noise": 1e-9, "vout_dc": 0.9}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    a = _summary(_run(sp))["blocks"][0]["analyses"]
    b = _summary(_run(sp))["blocks"][0]["analyses"]
    assert a == b == [".op", ".ac", ".tran", ".noise"]


# ---------------------------------------------------------------------------
# REAL FAIL — a spec.json with no recognizable metric earns NO vacuous PASS.
# ---------------------------------------------------------------------------
def test_fail_no_recognizable_keys(tmp_path):
    spec = {"name": "mystery", "author": "x", "revision": 3, "notes": "tbd"}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 1, r.stdout + r.stderr
    block = json.loads(jp.read_text())["summary"]["blocks"][0]
    assert block["pass"] is False
    assert block["reason"] == "no_measurable_keys"
    assert block["analyses"] == []


# ---------------------------------------------------------------------------
# Missing-data / honesty.
# ---------------------------------------------------------------------------
def test_fail_missing_spec_file(tmp_path):
    r = _run(tmp_path / "does_not_exist.json")
    assert r.returncode == 1
    assert _summary(r)["blocks"][0]["reason"] == "spec_missing"


def test_error_garbage_json(tmp_path):
    sp = tmp_path / "spec.json"
    sp.write_text("{ this is : not json ]")
    r = _run(sp)
    assert r.returncode == 2
    assert "json_error" in _summary(r)["blocks"][0]["reason"]


def test_error_spec_not_object(tmp_path):
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(["gain_db", 60]))
    r = _run(sp)
    assert r.returncode == 2
    assert _summary(r)["blocks"][0]["reason"] == "spec_not_object"


# ---------------------------------------------------------------------------
# Project-dir mode — scans analog/<block>/spec.json, INFO-skips when none.
# ---------------------------------------------------------------------------
def test_project_dir_skip_when_no_analog_specs(tmp_path):
    (tmp_path / "rtl").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _summary(r)["reason"] == "no_analog_specs"


def test_project_dir_scans_blocks(tmp_path):
    b1 = tmp_path / "analog" / "ldo"
    b2 = tmp_path / "analog" / "ota"
    b1.mkdir(parents=True)
    b2.mkdir(parents=True)
    (b1 / "spec.json").write_text(json.dumps({"line_reg": 0.1, "vout_dc": 1.8}))
    (b2 / "spec.json").write_text(json.dumps({"gain_db": 60, "input_noise": 1e-9}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    blocks = _summary(r)["blocks"]
    assert len(blocks) == 2
    by = {Path(b["spec"]).parent.name: b for b in blocks}
    assert by["ldo"]["analyses"] == [".op", ".dc"]
    assert by["ota"]["analyses"] == [".op", ".ac", ".noise"]


def test_project_dir_propagates_block_fail(tmp_path):
    b = tmp_path / "analog" / "blk"
    b.mkdir(parents=True)
    (b / "spec.json").write_text(json.dumps({"name": "nope"}))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert _summary(r)["blocks"][0]["reason"] == "no_measurable_keys"
