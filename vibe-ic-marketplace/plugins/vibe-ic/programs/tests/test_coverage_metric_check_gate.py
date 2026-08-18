#!/usr/bin/env python3
"""Tests for coverage_metric_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "coverage_metric_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_empty_project(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1

def test_with_coverage_report(tmp_path):
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "coverage.txt").write_text("Line coverage: 85.0%\nBranch coverage: 72.3%\nToggle coverage: 65.1%\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0
