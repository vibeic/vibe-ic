#!/usr/bin/env python3
"""Tests for bitwidth_consistency_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "bitwidth_consistency_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_rtl(tmp_path):
    rtl = tmp_path / "good.v"
    rtl.write_text("module good;\n    reg [7:0] data_reg;\n    wire [7:0] data_out;\n    assign data_out = data_reg;\nendmodule\n")
    r = _run([str(rtl)])
    assert r.returncode == 0

def test_fail_bitwidth_mismatch(tmp_path):
    rtl = tmp_path / "bad.v"
    rtl.write_text("module bad;\n    reg [7:0] data_reg;\n    wire [3:0] narrow;\n    assign narrow = data_reg[11:0];\nendmodule\n")
    r = _run([str(rtl), "--json"])
    assert r.returncode == 1
