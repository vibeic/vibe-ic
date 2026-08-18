#!/usr/bin/env python3
"""Tests for oe_pattern_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "oe_pattern_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_simple_oe(tmp_path):
    rtl = tmp_path / "oe.v"
    rtl.write_text("module oe_mod(inout data_io, input oe, input data_out);\n  assign data_io = oe ? data_out : 1'bz;\nendmodule\n")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-files", str(rtl), "--out-dir", str(out)])
    assert r.returncode == 1
