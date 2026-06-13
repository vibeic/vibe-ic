#!/usr/bin/env python3
"""Tests for device_response_no_br_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "device_response_no_br_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_no_br(tmp_path):
    (tmp_path / "top.v").write_text("module top; wire a; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_with_rtl_file(tmp_path):
    rtl = tmp_path / "resp.v"
    rtl.write_text("module resp;\n  reg br_pulse;\n  always @(posedge clk) br_pulse <= tx_done;\nendmodule\n")
    r = _run([str(rtl), "--json"])
    assert r.returncode == 0
