#!/usr/bin/env python3
"""Tests for xlsx_extract.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "xlsx_extract.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_missing_file(tmp_path):
    r = _run([str(tmp_path / "nope.xlsx")]); assert r.returncode == 2
