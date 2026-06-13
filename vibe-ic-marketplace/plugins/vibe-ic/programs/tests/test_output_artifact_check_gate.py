#!/usr/bin/env python3
"""Tests for output_artifact_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "output_artifact_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_check_artifacts(tmp_path):
    (tmp_path / "output.gds").write_bytes(b"\x00" * 100)
    r = _run(["--base-dir", str(tmp_path), "--artifacts", "output.gds"]); assert r.returncode == 0
