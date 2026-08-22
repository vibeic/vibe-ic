#!/usr/bin/env python3
"""Tests for module_port_audit.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "module_port_audit.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    (tmp_path / "top.v").write_text("module top(input clk, output data);\n  assign data = 1'b0;\nendmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0
