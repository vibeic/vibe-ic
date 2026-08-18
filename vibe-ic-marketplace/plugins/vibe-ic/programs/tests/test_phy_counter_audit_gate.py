#!/usr/bin/env python3
"""Tests for phy_counter_audit.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "phy_counter_audit.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_clean_rtl(tmp_path):
    rtl = tmp_path / "phy.v"
    rtl.write_text("module phy; wire a; endmodule\n")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-files", str(rtl), "--out-dir", str(out)]); assert r.returncode == 0
