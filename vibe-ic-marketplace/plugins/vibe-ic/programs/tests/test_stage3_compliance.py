#!/usr/bin/env python3
"""Tests for stage3_compliance.py — wrapper for flow_compliance_check --stage 3"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "stage3_compliance.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_empty_project(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 1
