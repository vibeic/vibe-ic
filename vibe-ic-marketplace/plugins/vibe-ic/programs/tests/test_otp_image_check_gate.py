#!/usr/bin/env python3
"""Tests for otp_image_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "otp_image_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_missing_ver(tmp_path):
    regmap = tmp_path / "L4_REGMAP.json"
    regmap.write_text(json.dumps({"registers": []}))
    r = _run([str(tmp_path / "nope.ver"), "--regmap", str(regmap)]); assert r.returncode == 1
