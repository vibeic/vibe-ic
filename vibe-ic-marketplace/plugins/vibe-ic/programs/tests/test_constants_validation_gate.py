#!/usr/bin/env python3
"""Tests for constants_validation.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "constants_validation.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_with_constants(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "constants": [
            {"name": "CLK_FREQ", "value": 50000000, "width": 32}
        ]
    }))
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 0

def test_skip_no_constants_file(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1
