#!/usr/bin/env python3
"""Tests for lvs_report_check.py — wrapper for eda_report_audit --mode lvs"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "lvs_report_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_empty_project(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1
