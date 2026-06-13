#!/usr/bin/env python3
"""Tests for manifest_leak_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "manifest_leak_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_dir(tmp_path):
    (tmp_path / "readme.md").write_text("# Test\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0
