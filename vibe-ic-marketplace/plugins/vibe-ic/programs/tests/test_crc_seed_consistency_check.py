#!/usr/bin/env python3
"""Tests for crc_seed_consistency_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "crc_seed_consistency_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_missing_vectors(tmp_path):
    r = _run(["--vectors-json", str(tmp_path / "nope.json"), "--out-dir", str(tmp_path)])
    assert r.returncode == 2
