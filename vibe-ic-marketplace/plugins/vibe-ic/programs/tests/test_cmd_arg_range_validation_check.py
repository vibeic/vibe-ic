#!/usr/bin/env python3
"""Tests for cmd_arg_range_validation_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "cmd_arg_range_validation_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_no_rtl(tmp_path):
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0

def test_detect_truncation(tmp_path):
    (tmp_path / "dispatch.v").write_text("module dispatch;\n  always @(*) begin\n    casez (cmd_opcode)\n      8'hA0: reg_val = cmd_arg[7:0];\n    endcase\n  end\nendmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0
