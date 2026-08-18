#!/usr/bin/env python3
"""Tests for analog_digital_interface_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_digital_interface_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_pass_complete_interface(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps({"blocks": [{"name": "ldo"}]}))
    iface = tmp_path / "phase3" / "analog" / "ldo" / "interface.json"
    iface.parent.mkdir(parents=True, exist_ok=True)
    iface.write_text(json.dumps({"pins": [
        {"name": "vin", "direction": "input", "type": "analog", "voltage_domain": "3.3V"},
        {"name": "vout", "direction": "output", "type": "analog", "voltage_domain": "3.3V"},
        {"name": "en", "direction": "input", "type": "digital", "voltage_domain": "1.8V"},
    ]}))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["complete"] == 1


def test_fail_missing_interface(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps({"blocks": [{"name": "bandgap"}]}))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    assert any(f["rule"] == "INTERFACE_MISSING" for f in rpt["findings"])


def test_fail_missing_voltage_domain(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps({"blocks": [{"name": "ldo"}]}))
    iface = tmp_path / "phase3" / "analog" / "ldo" / "interface.json"
    iface.parent.mkdir(parents=True, exist_ok=True)
    iface.write_text(json.dumps({"pins": [
        {"name": "vin", "direction": "input", "type": "analog"},
    ]}))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    assert any(f["rule"] == "INTERFACE_INCOMPLETE_PIN" for f in rpt["findings"])


def test_skip_no_analog(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS, not a plain PASS
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
