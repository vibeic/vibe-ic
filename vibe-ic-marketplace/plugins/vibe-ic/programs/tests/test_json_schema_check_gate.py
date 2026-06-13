#!/usr/bin/env python3
"""Tests for json_schema_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "json_schema_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_valid_json(tmp_path):
    jf = tmp_path / "data.json"
    jf.write_text(json.dumps({"name": "test", "version": "1.0"}))
    r = _run(["--json-file", str(jf), "--required-keys", "name,version"])
    assert r.returncode == 0

def test_missing_key(tmp_path):
    jf = tmp_path / "data.json"
    jf.write_text(json.dumps({"name": "test"}))
    r = _run(["--json-file", str(jf), "--required-keys", "name,version"])
    assert r.returncode == 1
