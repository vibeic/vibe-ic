#!/usr/bin/env python3
"""Tests for tester_oracle_health_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "tester_oracle_health_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_missing_config(tmp_path):
    r = _run(["--config", str(tmp_path / "nope.json")]); assert r.returncode == 2
