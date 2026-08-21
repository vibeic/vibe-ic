#!/usr/bin/env python3
"""Tests for cdc_crossing_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "cdc_crossing_check.py"

def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )

def _load(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_pass_with_cdc_report(tmp_path):
    rpt_dir = tmp_path / "reports"
    rpt_dir.mkdir(parents=True)
    (rpt_dir / "cdc_analysis.rpt").write_text(
        "Clock Domain Crossing Report\n"
        "clock domain: clk_a -> clk_b\n"
        "crossing signal: data_sync\n"
        "synchronizer: 2-FF\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load(tmp_path)
    assert rpt["passed"] is True


def test_fail_no_cdc_report(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top(input clk_a, input clk_b); endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 1


def test_skip_empty_project(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 1
