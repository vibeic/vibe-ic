#!/usr/bin/env python3
"""Tests for fpga_qsf_lint.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fpga_qsf_lint.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_minimal_qsf(tmp_path):
    qsf = tmp_path / "top.qsf"
    qsf.write_text("set_global_assignment -name FAMILY \"MAX 10\"\nset_global_assignment -name TOP_LEVEL_ENTITY top\n")
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    r = _run(["--qsf-file", str(qsf), "--rtl-dir", str(tmp_path), "--out-dir", str(tmp_path)])
    assert r.returncode == 0
