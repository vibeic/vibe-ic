#!/usr/bin/env python3
"""Tests for rx_tolerance_sweep.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "rx_tolerance_sweep.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_with_table(tmp_path):
    dt = tmp_path / "decode.json"
    dt.write_text(json.dumps({"thresholds": [{"name": "BR", "min": 10, "max": 20}]}))
    r = _run(["--decode-table", str(dt)]); assert r.returncode == 1
