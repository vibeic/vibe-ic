#!/usr/bin/env python3
"""Tests for eco_loop_audit.py (G4: ECO repair loop)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "eco_loop_audit.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_pass_no_eco_needed(tmp_path):
    flag = tmp_path / "phase3" / "stage3" / "eco" / "no_eco_needed.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("all sign-off passed first time")
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["eco_needed"] is False


def test_pass_eco_reverified(tmp_path):
    _write_json(tmp_path / "phase3" / "stage3" / "eco" / "eco_log.json", {
        "changes": [{"type": "buffer_insert", "net": "clk"}],
        "re_verified": True,
        "affected_steps": [21, 27],
    })
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_no_artifact(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_not_reverified(tmp_path):
    _write_json(tmp_path / "phase3" / "stage3" / "eco" / "eco_log.json", {
        "changes": [{"type": "resize", "cell": "U42"}],
        "re_verified": False,
        "affected_steps": [21],
    })
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_empty_changes(tmp_path):
    _write_json(tmp_path / "phase3" / "stage3" / "eco" / "eco_log.json", {
        "changes": [],
        "re_verified": True,
        "affected_steps": [],
    })
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2
