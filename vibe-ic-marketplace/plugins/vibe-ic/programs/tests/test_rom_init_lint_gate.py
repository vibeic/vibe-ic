#!/usr/bin/env python3
"""Tests for rom_init_lint.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "rom_init_lint.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_clean_rtl(tmp_path):
    rtl = tmp_path / "rom.v"
    rtl.write_text("module rom(input [7:0] addr, output [7:0] data);\n  reg [7:0] mem [0:255];\n  initial $readmemh(\"rom.hex\", mem);\n  assign data = mem[addr];\nendmodule\n")
    r = _run([str(rtl)]); assert r.returncode == 0
