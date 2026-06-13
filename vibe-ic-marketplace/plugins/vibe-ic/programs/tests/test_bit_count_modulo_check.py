#!/usr/bin/env python3
"""Tests for bit_count_modulo_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "bit_count_modulo_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_no_bit_counters(tmp_path):
    rtl = tmp_path / "simple.v"
    rtl.write_text("module simple; wire a; endmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0

def test_detect_bit_counter(tmp_path):
    rtl = tmp_path / "counter.v"
    rtl.write_text("module counter(input clk, input rst_n);\n    reg [3:0] bit_cnt;\n    always @(posedge clk or negedge rst_n)\n        if (!rst_n) bit_cnt <= 0;\n        else bit_cnt <= bit_cnt + 1;\nendmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0
