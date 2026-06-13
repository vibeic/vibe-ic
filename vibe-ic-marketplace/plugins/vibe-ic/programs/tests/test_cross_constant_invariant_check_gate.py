#!/usr/bin/env python3
"""Tests for cross_constant_invariant_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "cross_constant_invariant_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_invariant(tmp_path):
    consts = tmp_path / "consts.json"
    consts.write_text(json.dumps({"A": 8, "B": 4}))
    r = _run(["--constants", str(consts), "--inv", "A >= B"])
    assert r.returncode == 0

def test_fail_invariant(tmp_path):
    consts = tmp_path / "consts.json"
    consts.write_text(json.dumps({"A": 3, "B": 10}))
    r = _run(["--constants", str(consts), "--inv", "A >= B"])
    assert r.returncode == 1
