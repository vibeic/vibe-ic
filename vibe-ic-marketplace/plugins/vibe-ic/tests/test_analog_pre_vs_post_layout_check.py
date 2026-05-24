#!/usr/bin/env python3
"""Tests for analog_pre_vs_post_layout_check.py — pre/post-layout comparison gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "analog_pre_vs_post_layout_check.py"


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


def test_skip_no_pre_vs_post(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_pre_vs_post_data"


def test_pass_acceptable_degradation(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [
            {"name": "vout", "pre_layout": 3.30, "post_layout": 3.25},
            {"name": "iq", "pre_layout": 50e-6, "post_layout": 52e-6},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["specs_compared"] == 2


def test_fail_severe_degradation(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "pre_vs_post.json").write_text(json.dumps({
        "comparisons": [
            {"name": "vout", "pre_layout": 3.30, "post_layout": 2.0},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("LAYOUT_SEVERE_DEGRADATION" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
