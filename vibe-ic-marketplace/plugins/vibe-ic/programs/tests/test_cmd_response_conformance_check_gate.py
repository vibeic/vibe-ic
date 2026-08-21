#!/usr/bin/env python3
"""Tests for cmd_response_conformance_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "cmd_response_conformance_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_vectors(tmp_path):
    vf = tmp_path / "vectors.json"
    vf.write_text(json.dumps({"cases": [
        {"cmd": "A0 01", "expected_rsp": "A0 01 00"},
    ]}))
    cap = tmp_path / "capture.json"
    cap.write_text(json.dumps(["A0 01 00"]))
    r = _run([str(tmp_path), "--vectors", str(vf), "--capture-json", str(cap)])
    assert r.returncode == 1
