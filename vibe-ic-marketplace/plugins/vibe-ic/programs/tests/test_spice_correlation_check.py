#!/usr/bin/env python3
"""Tests for spice_correlation_check.py — post-layout SPICE verification gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "spice_correlation_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _setup_spef(tmp_path: Path):
    """Create minimal SPEF so the gate doesn't self-skip."""
    d = tmp_path / "phase3" / "stage3" / "extracted"
    d.mkdir(parents=True, exist_ok=True)
    (d / "parasitic.spef").write_text(
        "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"test\"\n*DATE \"2026\"\n"
        "*D_NET net1 0.001\n*END\n"
    )


def _setup_sta(tmp_path: Path, worst_delay: float = 5.0):
    """Create minimal STA report."""
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True, exist_ok=True)
    (d / "post_route_timing.rpt").write_text(
        f"Startpoint: ff1 (rising edge-triggered flip-flop)\n"
        f"Endpoint: ff2 (rising edge-triggered flip-flop)\n"
        f"Path Delay       {worst_delay}\n"
        f"slack (MET)      0.5\n"
    )


# -- Test: self-skip when no SPEF --

def test_skip_no_spef(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_spef"


# -- Test: self-skip when no STA --

def test_skip_no_sta(tmp_path):
    _setup_spef(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_sta"


# -- Test: FAIL when SPEF+STA exist but no SPICE run --

def test_fail_no_spice_verification(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("NO_SPICE_VERIFICATION" in f["rule"] for f in errors)


# -- Test: PASS with correlation JSON within tolerance --

def test_pass_correlation_within_tolerance(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path, worst_delay=5.0)
    sd = tmp_path / "phase3" / "stage3" / "spice"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "crit_path.sp").write_text(".title test\n.tran 1n 100n\n.end\n")
    (sd / "correlation.json").write_text(json.dumps({
        "paths": [
            {"path": "ff1->ff2", "sta_delay_ns": 5.0, "spice_delay_ns": 5.3},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["correlation"]["max_discrepancy_pct"] < 10


# -- Test: FAIL with >10% SPICE-STA mismatch --

def test_fail_correlation_mismatch(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path, worst_delay=5.0)
    sd = tmp_path / "phase3" / "stage3" / "spice"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "crit_path.sp").write_text(".title test\n.tran 1n 100n\n.end\n")
    (sd / "correlation.json").write_text(json.dumps({
        "paths": [
            {"path": "ff1->ff2", "sta_delay_ns": 5.0, "spice_delay_ns": 6.5},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("MISMATCH" in f["rule"] for f in errors)


# -- Test: FAIL with >25% critical mismatch --

def test_fail_critical_mismatch(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path, worst_delay=5.0)
    sd = tmp_path / "phase3" / "stage3" / "spice"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "crit_path.sp").write_text(".title test\n.end\n")
    (sd / "correlation.json").write_text(json.dumps({
        "paths": [
            {"path": "ff1->ff2", "sta_delay_ns": 5.0, "spice_delay_ns": 8.0},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("CRITICAL_MISMATCH" in f["rule"] for f in errors)


# -- Test: analog module detected but no SPICE → FAIL --

def test_fail_analog_missing_spice(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path)
    sd = tmp_path / "phase3" / "stage3" / "spice"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "digital_path.sp").write_text(".title test\n.end\n")
    (sd / "correlation.json").write_text(json.dumps({"paths": [
        {"path": "ff1->ff2", "sta_delay_ns": 5.0, "spice_delay_ns": 5.1},
    ]}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ldo_reg.v").write_text("module ldo_regulator(input vin, output vout);\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("ANALOG_SPICE_MISSING" in f["rule"] for f in errors)


# -- Test: analog module with matching SPICE → PASS --

def test_pass_analog_covered(tmp_path):
    _setup_spef(tmp_path)
    _setup_sta(tmp_path)
    sd = tmp_path / "phase3" / "stage3" / "spice"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "ldo_regulator.sp").write_text(".title LDO test\n.end\n")
    (sd / "ldo_regulator.log").write_text("vout_dc = 1.800\n")
    (sd / "correlation.json").write_text(json.dumps({"paths": [
        {"path": "ff1->ff2", "sta_delay_ns": 5.0, "spice_delay_ns": 5.2},
    ]}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ldo_regulator.v").write_text("module ldo_regulator(input vin, output vout);\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["analog"]["covered"] == 1


# -- Test: exit 2 on non-existent directory --

def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
