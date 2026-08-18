#!/usr/bin/env python3
"""Tests for mixed_signal_cosim_check.py — mixed-signal co-simulation gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "mixed_signal_cosim_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_analog(tmp_path):
    r = _run(tmp_path)
    # v0.2.17: no analog blocks => genuine SKIP (rc=2), consistent with the
    # codebase SKIP convention; the orchestrator maps rc=2 to VACUOUS_PASS.
    assert r.returncode == 2
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


def test_pass_cosim_passed(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "ldo" / "spec.json").write_text("{}")
    cd = tmp_path / "phase3" / "mixed_signal" / "cosim"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "ldo_cosim_results.json").write_text(json.dumps({
        "simulation_passed": True, "max_error_pct": 2.5
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["simulated"] == 1


def test_fail_cosim_missing(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["ldo"]))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("COSIM_MISSING" in f["rule"] for f in errors)


def test_fail_cosim_failed(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "ldo" / "spec.json").write_text("{}")
    cd = tmp_path / "phase3" / "mixed_signal" / "cosim"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "ldo_cosim_results.json").write_text(json.dumps({
        "simulation_passed": False, "failure_reason": "timing violation"
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("COSIM_FAILED" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
