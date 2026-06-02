#!/usr/bin/env python3
"""Tests for doc_extract.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "doc_extract.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_empty_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--in-dir", str(tmp_path), "--out-dir", str(out)])
    assert r.returncode == 1
