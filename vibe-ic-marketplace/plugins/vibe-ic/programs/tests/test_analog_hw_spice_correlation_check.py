#!/usr/bin/env python3
"""Tests for analog_hw_spice_correlation_check.py — HW-vs-SPICE correlation gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_hw_spice_correlation_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_analog_dir(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_dir"


def test_skip_no_hw_data(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "ldo" / "spec.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_hw_data"


def test_pass_within_tolerance(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "hw_measurements.json").write_text(json.dumps({
        "measurements": {"vout": 3.25, "iq": 48e-6}
    }))
    (ad / "corner_results.json").write_text(json.dumps({
        "pvt_results": {"TT_25C": {"vout": 3.3, "iq": 50e-6}}
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["measurements_compared"] == 2


def test_fail_critical_mismatch(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "hw_measurements.json").write_text(json.dumps({
        "measurements": {"vout": 2.0}
    }))
    (ad / "corner_results.json").write_text(json.dumps({
        "pvt_results": {"TT_25C": {"vout": 3.3}}
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("HW_SPICE_CRITICAL_MISMATCH" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
