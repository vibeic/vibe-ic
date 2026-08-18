#!/usr/bin/env python3
"""Tests for waiver_growth_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "waiver_growth_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_no_waivers(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 0
def test_with_waivers(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({"waived_steps": [{"id": 28, "reason": "test", "cascades_to": []}]}))
    r = _run([str(tmp_path)]); assert r.returncode == 1
