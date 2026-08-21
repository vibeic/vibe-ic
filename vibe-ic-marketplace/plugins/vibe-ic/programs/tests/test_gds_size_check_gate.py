#!/usr/bin/env python3
"""Tests for gds_size_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "gds_size_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_missing_gds(tmp_path):
    r = _run(["--gds-file", str(tmp_path / "nope.gds")])
    assert r.returncode == 1

def test_tiny_gds(tmp_path):
    gds = tmp_path / "tiny.gds"
    gds.write_bytes(b"\\x00" * 100)
    r = _run(["--gds-file", str(gds), "--min-size-kb", "1.0"])
    assert r.returncode == 1
