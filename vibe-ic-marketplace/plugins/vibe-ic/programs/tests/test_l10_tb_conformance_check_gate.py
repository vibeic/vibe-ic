#!/usr/bin/env python3
"""Tests for l10_tb_conformance_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "l10_tb_conformance_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_missing_l10(tmp_path):
    r = _run(["--l10", str(tmp_path / "nope.json"), "--out", str(tmp_path / "out.json")])
    assert r.returncode == 2
