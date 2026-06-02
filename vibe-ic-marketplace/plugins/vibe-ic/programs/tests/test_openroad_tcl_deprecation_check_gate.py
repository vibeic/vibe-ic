#!/usr/bin/env python3
"""Tests for openroad_tcl_deprecation_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "openroad_tcl_deprecation_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_dir(tmp_path):
    r = _run(["--search-dir", str(tmp_path)]); assert r.returncode == 0
