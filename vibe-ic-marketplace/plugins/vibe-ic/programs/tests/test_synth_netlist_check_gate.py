#!/usr/bin/env python3
"""Tests for synth_netlist_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "synth_netlist_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_missing_netlist(tmp_path):
    r = _run(["--netlist", str(tmp_path / "nope.v")]); assert r.returncode == 1
