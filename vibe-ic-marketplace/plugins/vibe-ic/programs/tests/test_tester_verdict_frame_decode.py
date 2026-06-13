#!/usr/bin/env python3
"""Tests for tester_verdict_frame_decode.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "tester_verdict_frame_decode.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_decode_frame(tmp_path):
    layout = tmp_path / "layout.json"
    layout.write_text(json.dumps({"fields": [{"name": "status", "bits": 8}]}))
    r = _run(["--layout", str(layout), "--frame", "AB"]); assert r.returncode == 1
