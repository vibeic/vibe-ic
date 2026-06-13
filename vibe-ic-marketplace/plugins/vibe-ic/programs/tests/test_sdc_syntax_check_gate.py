#!/usr/bin/env python3
"""Tests for sdc_syntax_check.py."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "sdc_syntax_check.py"

def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"]); assert r.returncode == 0

def test_empty_project(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 1

def test_valid_sdc(tmp_path):
    sdc = tmp_path / "constraints.sdc"
    sdc.write_text("create_clock -period 10.0 -name clk [get_ports clk]\n")
    r = _run([str(tmp_path)]); assert r.returncode == 1
