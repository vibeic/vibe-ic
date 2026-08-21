#!/usr/bin/env python3
"""Tests for hw_vs_rtl_verdict_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "hw_vs_rtl_verdict_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_missing_dir(tmp_path):
    r = _run(["--responses-dir", str(tmp_path / "nope")])
    assert r.returncode == 2
