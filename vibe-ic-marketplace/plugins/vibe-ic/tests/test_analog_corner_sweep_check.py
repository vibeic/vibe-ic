#!/usr/bin/env python3
"""Tests for analog_corner_sweep_check.py — PVT corner coverage gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "analog_corner_sweep_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _setup_corner_results(tmp_path, block="ldo", total=15, found=15,
                          spec_results=None, mc_yield=None):
    d = tmp_path / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    data = {"total_corners": total, "results_found": found}
    if spec_results is not None:
        data["spec_results"] = spec_results
    if mc_yield is not None:
        data["mc_yield_pct"] = mc_yield
    (d / "corner_results.json").write_text(json.dumps(data))


# -- Test: PASS with sufficient corners and all specs passing --

def test_pass_all_corners(tmp_path):
    _setup_corner_results(tmp_path, total=15, found=15, spec_results=[
        {"spec": "vout", "corner": "tt_25C", "status": "PASS"},
        {"spec": "vout", "corner": "ss_125C", "status": "PASS"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["blocks_pass"] == 1


# -- Test: FAIL with insufficient corners --

def test_fail_missing_corner(tmp_path):
    _setup_corner_results(tmp_path, total=3, found=3)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("INSUFFICIENT_CORNERS" in f["rule"] for f in errors)


# -- Test: FAIL with spec violation --

def test_fail_spec_violation(tmp_path):
    _setup_corner_results(tmp_path, total=15, found=15, spec_results=[
        {"spec": "vout", "corner": "ss_125C", "status": "FAIL"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("SPEC_FAIL_AT_CORNER" in f["rule"] for f in errors)


# -- Test: self-skip when no corner data --

def test_skip_no_data(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True


# -- Test: exit 2 on non-existent directory --

def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
