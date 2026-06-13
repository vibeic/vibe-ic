#!/usr/bin/env python3
"""Tests for cmd_protocol_crc_verify.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "cmd_protocol_crc_verify.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_verify_crc8(tmp_path):
    vectors = tmp_path / "vectors.json"
    vectors.write_text(json.dumps({
        "width": 8,
        "vectors": [
            {"data_hex": "01 02 03", "crc_hex": "48"},
            {"data_hex": "A0 B1 C2", "crc_hex": "D3"},
            {"data_hex": "FF 00 FF", "crc_hex": "12"}
        ]
    }))
    r = _run([str(vectors)])
    assert r.returncode == 1
