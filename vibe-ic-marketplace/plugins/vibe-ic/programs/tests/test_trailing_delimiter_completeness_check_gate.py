#!/usr/bin/env python3
"""Tests for trailing_delimiter_completeness_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "trailing_delimiter_completeness_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_with_delimiter(tmp_path):
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; initial $finish; endmodule\n")
    r = _run([str(tmp_path), "--delimiter", "0xFF"]); assert r.returncode == 0
