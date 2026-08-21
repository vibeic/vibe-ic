#!/usr/bin/env python3
"""Tests for tristate_bus_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "tristate_bus_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_generate(tmp_path):
    r = _run(["--bus-name", "data_io", "--drivers", "drv_a,drv_b", "--out-dir", str(tmp_path)]); assert r.returncode == 0
