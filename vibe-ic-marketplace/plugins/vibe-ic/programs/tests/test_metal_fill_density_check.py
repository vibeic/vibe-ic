#!/usr/bin/env python3
"""Tests for metal_fill_density_check.py (G5: Metal Fill + Density)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "metal_fill_density_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_pass_filled_def(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("x" * 1000)
    (pnr / "filled.def").write_text("x" * 2000)
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True


def test_pass_fill_done_marker(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "metal_fill.done").write_text("done")
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_no_fill(tmp_path):
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_warn_filled_not_larger(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("x" * 2000)
    (pnr / "filled.def").write_text("x" * 500)
    result = _run(tmp_path)
    assert result.returncode == 0  # warning only, not error


def test_fail_density_out_of_bounds(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "filled.def").write_text("x" * 2000)
    _write_json(tmp_path / "reports" / "phase3" / "density.json", {
        "layers": [
            {"name": "M1", "density_pct": 50.0},
            {"name": "M2", "density_pct": 95.0},
        ]
    })
    result = _run(tmp_path)
    assert result.returncode == 1


def test_pass_density_in_bounds(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "filled.def").write_text("x" * 2000)
    _write_json(tmp_path / "reports" / "phase3" / "density.json", {
        "layers": [
            {"name": "M1", "density_pct": 45.0},
            {"name": "M2", "density_pct": 60.0},
        ]
    })
    result = _run(tmp_path)
    assert result.returncode == 0


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2
