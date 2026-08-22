#!/usr/bin/env python3
"""Tests for eda_report_audit.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "eda_report_audit.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_drc_mode_empty(tmp_path):
    r = _run([str(tmp_path), "--mode", "drc"])
    assert r.returncode == 1

def test_sta_mode_empty(tmp_path):
    r = _run([str(tmp_path), "--mode", "sta"])
    assert r.returncode == 1
