#!/usr/bin/env python3
"""Tests for l9_response_delay_schema_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "l9_response_delay_schema_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_minimal_l9(tmp_path):
    l9 = tmp_path / "L9.json"
    l9.write_text(json.dumps({"top_module": "top", "submodules": []}))
    r = _run([str(l9)])
    assert r.returncode == 0
