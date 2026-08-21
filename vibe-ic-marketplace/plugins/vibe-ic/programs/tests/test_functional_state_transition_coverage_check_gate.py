#!/usr/bin/env python3
"""Tests for functional_state_transition_coverage_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "functional_state_transition_coverage_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_cov(tmp_path):
    tb = tmp_path / "tb.v"
    tb.write_text("module tb;\n  initial begin\n    $display(\"awake_q == 1'b1\");\n    $finish;\n  end\nendmodule\n")
    r = _run([str(tmp_path), "--cov", "0x74:awake_q == 1'b1"])
    assert r.returncode == 0
