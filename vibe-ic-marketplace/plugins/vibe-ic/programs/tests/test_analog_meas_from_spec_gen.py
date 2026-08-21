#!/usr/bin/env python3
"""Tests for analog_meas_from_spec_gen.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_meas_from_spec_gen.py"


def _run(spec_path: Path, out: Path = None, jpath: Path = None):
    cmd = [sys.executable, str(PROG), str(spec_path)]
    if out:
        cmd += ["--out", str(out)]
    if jpath:
        cmd += ["--json", str(jpath)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_pass_emits_dc_ac_tran(tmp_path):
    spec = {
        "vout_dc": {"value": 3.3, "unit": "V"},
        "gain_db": 60,
        "tpd": {"value": 5, "unit": "ns"},
        "name": "amp",          # non-measurable, ignored
    }
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    out = tmp_path / "meas.inc"
    jp = tmp_path / "r.json"
    r = _run(sp, out=out, jpath=jp)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(jp.read_text())
    assert rep["summary"]["pass"] is True
    assert rep["summary"]["meas_lines"] == 3
    deck = out.read_text()
    assert ".meas DC vout_dc" in deck
    assert ".meas AC gain_db" in deck
    assert ".meas TRAN tpd" in deck


def test_pass_nested_specs_object(tmp_path):
    spec = {"specs": {"vref": 1.2, "ugbw": 1e6}}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 0
    rep = json.loads(jp.read_text())
    kinds = {e["kind"] for e in rep["summary"]["emitted"]}
    assert {"DC", "AC"} <= kinds


def test_fail_missing_spec(tmp_path):
    r = _run(tmp_path / "nope.json")
    assert r.returncode == 1


def test_fail_no_measurable_keys(tmp_path):
    spec = {"author": "x", "revision": 3, "notes": "draft"}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    jp = tmp_path / "r.json"
    r = _run(sp, jpath=jp)
    assert r.returncode == 1
    rep = json.loads(jp.read_text())
    assert rep["summary"]["pass"] is False
    assert rep["summary"]["reason"] == "no_measurable_keys"


def test_edge_garbage_json_exit2(tmp_path):
    sp = tmp_path / "spec.json"
    sp.write_text("{ not valid json ")
    r = _run(sp)
    assert r.returncode == 2


def test_edge_non_object_json_exit2(tmp_path):
    sp = tmp_path / "spec.json"
    sp.write_text("[1, 2, 3]")
    r = _run(sp)
    assert r.returncode == 2
