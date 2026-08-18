#!/usr/bin/env python3
"""Tests for fpga_pullup_lint.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fpga_pullup_lint.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk); endmodule\n")
    qsf = tmp_path / "top.qsf"
    qsf.write_text("set_global_assignment -name FAMILY \"MAX 10\"\n")
    r = _run(["--rtl-dir", str(tmp_path), "--top-module", "top", "--constraint", str(qsf)])
    assert r.returncode == 0
