#!/usr/bin/env python3
"""Tests for provenance_logger.py."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "provenance_logger.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_help():
    r = _run("--help")
    assert r.returncode == 0

def test_appends_entry(tmp_path):
    r = _run("--project", str(tmp_path), "--tool", "test_tool", "--step", "lint",
             "--", "echo", "hello")
    assert r.returncode == 0

def test_error_missing_required_args(tmp_path):
    r = _run("--project", str(tmp_path))
    assert r.returncode in (1, 2)
