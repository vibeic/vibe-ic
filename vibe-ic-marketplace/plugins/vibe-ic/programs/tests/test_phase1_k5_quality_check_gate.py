#!/usr/bin/env python3
"""Tests for phase1_k5_quality_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "phase1_k5_quality_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_target(tmp_path):
    # ORGANIC #491: an empty target is "nothing to check", NOT "clean".
    # rc 2 = NOT CHECKED, which flow_compliance_check records as a NAMED
    # SKIP; the previous rc 0 was read by the umbrella as ("pass", None).
    r = _run([str(tmp_path)])
    assert r.returncode == 2, r.stdout
    assert "NOT CHECKED" in r.stdout
