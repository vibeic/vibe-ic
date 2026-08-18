#!/usr/bin/env python3
"""Tests for fpga_program_chain_attest_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "fpga_program_chain_attest_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_manifest(tmp_path):
    mf = tmp_path / "latest_results.jsonl"
    mf.write_text(json.dumps({"step": "program", "pass": True}) + "\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 1
