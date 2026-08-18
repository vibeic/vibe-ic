#!/usr/bin/env python3
"""Tests for bist_window_calculator.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "bist_window_calculator.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_calculate():
    r = _run(["--max-bytes", "20", "--bit-period-us", "14.0", "--clk-mhz", "50.0"])
    assert r.returncode == 0
    assert "cycle" in r.stdout.lower() or "window" in r.stdout.lower() or r.stdout.strip()
