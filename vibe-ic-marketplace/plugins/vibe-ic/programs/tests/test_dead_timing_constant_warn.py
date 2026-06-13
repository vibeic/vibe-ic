#!/usr/bin/env python3
"""Tests for dead_timing_constant_warn.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "dead_timing_constant_warn.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_no_timing_constants(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; wire a; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_warn_dead_timing(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "defs.v").write_text("`define T_SETUP_CYC 5\n`define T_HOLD_NS 10\nmodule defs; endmodule\n")
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; wire a; endmodule\n")
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 1
