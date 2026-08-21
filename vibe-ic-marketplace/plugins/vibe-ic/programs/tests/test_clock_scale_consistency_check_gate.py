#!/usr/bin/env python3
"""Tests for clock_scale_consistency_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "clock_scale_consistency_check.py"

def _run(tmp_path: Path, input_json: str, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), input_json, "--json", str(tmp_path / "report.json")] + list(extra),
        capture_output=True, text=True,
    )

def _load(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_pass_consistent(tmp_path):
    data = {
        "timing_thresholds": {
            "break_min_us": {
                "value": 100, "unit": "us",
                "domain_clock": "sys_clk", "source_clock": "sys_clk",
            },
        },
    }
    jf = tmp_path / "L8.json"
    jf.write_text(json.dumps(data))
    r = _run(tmp_path, str(jf))
    assert r.returncode == 0


def test_fail_no_clock(tmp_path):
    data = {
        "timing_thresholds": {
            "break_min_us": {"value": 100, "unit": "us"},
        },
    }
    jf = tmp_path / "L8.json"
    jf.write_text(json.dumps(data))
    r = _run(tmp_path, str(jf))
    assert r.returncode == 1
    rpt = _load(tmp_path)
    assert len(rpt["errors"]) >= 1
