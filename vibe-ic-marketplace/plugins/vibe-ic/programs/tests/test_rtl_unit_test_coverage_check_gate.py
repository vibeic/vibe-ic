#!/usr/bin/env python3
"""Tests for rtl_unit_test_coverage_check.py."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "rtl_unit_test_coverage_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_pass_with_coverage(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"; rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text("module top(input clk); endmodule\n")
    sim = tmp_path / "phase2" / "stage1" / "sim" / "tb"; sim.mkdir(parents=True)
    (sim / "tb_top.v").write_text("module tb_top; initial $display(\"PASS\"); endmodule\n")
    r = _run(str(tmp_path))
    assert r.returncode == 0

def test_empty_project(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode == 1
