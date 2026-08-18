#!/usr/bin/env python3
"""Tests for l12_tb_coverage_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "l12_tb_coverage_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_l12_and_tb(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L12_BEHAVIORAL_SEQUENCES.json").write_text(json.dumps({"sequences": []}))
    tb = tmp_path / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "tb_top.v").write_text("module tb_top; initial $finish; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0
