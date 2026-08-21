#!/usr/bin/env python3
"""Tests for threshold_range_contiguity_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "threshold_range_contiguity_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_with_constants(tmp_path):
    c = tmp_path / "L8_RTL_CONSTANTS.json"
    c.write_text(json.dumps({"constants": []}))
    r = _run([str(c)]); assert r.returncode == 0
