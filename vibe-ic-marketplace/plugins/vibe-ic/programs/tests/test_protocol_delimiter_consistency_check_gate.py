#!/usr/bin/env python3
"""Tests for protocol_delimiter_consistency_check.py."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "protocol_delimiter_consistency_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_help():
    r = _run("--help")
    assert r.returncode == 0

def test_error_no_delimiter(tmp_path):
    # v1.6.7: positional dir without delimiter source now SKIPs (rc=0) instead
    # of FAILing — keeps gate quiet on non-protocol / unwired targets.
    # Empty-file path (a single non-existent file) still errors as rc=2.
    r = _run(str(tmp_path / "no_such_file.v"))
    assert r.returncode == 2
    # Bare dir SKIPs:
    r2 = _run(str(tmp_path))
    assert r2.returncode == 0
    assert "SKIP" in r2.stdout

def test_pass_with_delimiter(tmp_path):
    (tmp_path / "rx.v").write_text("module rx(input clk, input rx_break);\nalways @(posedge clk) if (rx_break) ;\nendmodule\n")
    r = _run(str(tmp_path), "--delimiter", "BR_HIGH")
    assert r.returncode == 0
