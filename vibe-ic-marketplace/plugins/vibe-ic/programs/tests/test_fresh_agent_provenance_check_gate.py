#!/usr/bin/env python3
"""Tests for fresh_agent_provenance_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fresh_agent_provenance_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_empty_dirs(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    ref = tmp_path / "ref"
    ref.mkdir(parents=True, exist_ok=True)
    r = _run([str(rtl), str(ref)])
    assert r.returncode == 0
