#!/usr/bin/env python3
"""Tests for verilator_coverage_measure.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "verilator_coverage_measure.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
