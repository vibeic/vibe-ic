#!/usr/bin/env python3
"""Tests for nba_addr_read_race_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "nba_addr_read_race_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    rtl = tmp_path / "reg.v"
    rtl.write_text("module reg_mod(input clk, input [7:0] wdata, output reg [7:0] rdata);\n  always @(posedge clk) rdata <= wdata;\nendmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0
