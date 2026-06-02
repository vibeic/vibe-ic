#!/usr/bin/env python3
"""Tests for spec_response_delay_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "spec_response_delay_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_with_spec(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    r = _run([str(tmp_path), "--spec", "CMD:10us"])
    assert r.returncode == 2
