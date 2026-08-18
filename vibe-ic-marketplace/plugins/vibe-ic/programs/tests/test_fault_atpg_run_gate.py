#!/usr/bin/env python3
"""Tests for fault_atpg_run.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fault_atpg_run.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_missing_netlist(tmp_path):
    r = _run([str(tmp_path), "--clock", "clk"])
    assert r.returncode == 2
