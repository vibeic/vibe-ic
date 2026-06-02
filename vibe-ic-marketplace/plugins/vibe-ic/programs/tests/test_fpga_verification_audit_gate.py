#!/usr/bin/env python3
"""Tests for fpga_verification_audit.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fpga_verification_audit.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_missing_report(tmp_path):
    r = _run(["--report", str(tmp_path / "nope.md"), "--out", str(tmp_path / "out.json")])
    assert r.returncode == 2
