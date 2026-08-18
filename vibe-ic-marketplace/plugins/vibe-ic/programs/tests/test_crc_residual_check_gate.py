#!/usr/bin/env python3
"""Tests for crc_residual_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "crc_residual_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_crc(tmp_path):
    rtl = tmp_path / "crc.v"
    rtl.write_text("module crc_check;\n  wire [7:0] crc_out;\n  assign crc_valid = (crc_out == 8'h00);\nendmodule\n")
    r = _run([str(rtl)])
    assert r.returncode == 0

def test_no_rtl(tmp_path):
    empty = tmp_path / "empty.v"
    empty.write_text("module empty; endmodule\n")
    r = _run([str(empty)])
    assert r.returncode == 0
