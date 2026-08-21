#!/usr/bin/env python3
"""Tests for gap_reset_granularity_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "gap_reset_granularity_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; wire a; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0
