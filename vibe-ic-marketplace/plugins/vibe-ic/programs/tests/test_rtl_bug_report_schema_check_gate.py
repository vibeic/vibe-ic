#!/usr/bin/env python3
"""Tests for rtl_bug_report_schema_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "rtl_bug_report_schema_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_project(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 2
