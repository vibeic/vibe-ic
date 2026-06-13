#!/usr/bin/env python3
"""Tests for fpga_wrapper_input_polluter_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fpga_wrapper_input_polluter_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    rtl = tmp_path / "wrapper.v"
    rtl.write_text("module fpga_wrapper(input clk, input data_in, output data_out);\n  assign data_out = data_in;\nendmodule\n")
    r = _run(["--rtl", str(rtl)])
    assert r.returncode == 0
