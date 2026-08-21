#!/usr/bin/env python3
"""Tests for analog_block_coverage_check.py — analog design coverage gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_block_coverage_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# -- Test: self-skip when no analog modules detected --

def test_pass_no_analog(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "counter.v").write_text("module counter(input clk, output [7:0] q);\nendmodule\n")
    r = _run(tmp_path)
    # #521 — a design with no analog block is VACUOUS (rc 2), not a PASS over
    # analog content that does not exist. The report assertions are unchanged.
    assert r.returncode == 2
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


# -- Test: FAIL when analog module in RTL but no design directory --

def test_fail_missing_spec(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "ldo_regulator.v").write_text(
        "module ldo_regulator(input vin, output vout);\nendmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("ANALOG_BLOCK_UNCOVERED" in f["rule"] for f in errors)


# -- Test: PASS when all deliverables present --

def test_pass_all_covered(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "ldo_regulator.v").write_text(
        "module ldo_regulator(input vin, output vout);\nendmodule\n"
    )
    ad = tmp_path / "phase3" / "analog" / "ldo_regulator"
    ad.mkdir(parents=True)
    (ad / "spec.json").write_text(json.dumps({"block_name": "ldo_regulator", "specs": {}}))
    (ad / "ldo.sp").write_text(".title LDO\n.end\n")
    (ad / "corner_results.json").write_text(json.dumps({
        "total_corners": 15, "results_found": 15, "spec_results": []
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["covered"] == 1


# -- Test: self-skip when no rtl/ dir --

def test_skip_no_rtl(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS, not a plain PASS
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
