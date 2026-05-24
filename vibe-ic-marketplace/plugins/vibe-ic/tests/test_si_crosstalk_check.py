#!/usr/bin/env python3
"""Tests for si_crosstalk_check.py (G3: Signal Integrity)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "si_crosstalk_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_pass_json_no_violations(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.02, "violations_count": 0})
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True


def test_pass_rpt_format(tmp_path):
    rpt = tmp_path / "reports" / "phase3" / "si_crosstalk.rpt"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text("Crosstalk analysis complete\nNo violations\n")
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_no_report(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_violations_no_waiver(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.15, "violations_count": 3})
    result = _run(tmp_path)
    assert result.returncode == 1


def test_pass_violations_with_waiver(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json",
                {"max_crosstalk_noise": 0.15, "violations_count": 3})
    _write_json(tmp_path / "waivers.json",
                {"waivers": [{"step": "si_crosstalk", "reason": "accepted"}]})
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_missing_fields(tmp_path):
    _write_json(tmp_path / "reports" / "phase3" / "si_crosstalk.json", {"foo": "bar"})
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2
