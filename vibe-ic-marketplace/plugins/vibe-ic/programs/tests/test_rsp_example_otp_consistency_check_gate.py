#!/usr/bin/env python3
"""Tests for rsp_example_otp_consistency_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "rsp_example_otp_consistency_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_missing_files(tmp_path):
    l3 = tmp_path / "L3.json"
    l3.write_text(json.dumps({"commands": []}))
    otp = tmp_path / "L11.json"
    otp.write_text(json.dumps({"otp_content": []}))
    r = _run([str(l3), "--otp", str(otp)]); assert r.returncode == 1
