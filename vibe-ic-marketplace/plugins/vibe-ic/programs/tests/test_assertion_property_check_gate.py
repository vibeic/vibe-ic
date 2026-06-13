#!/usr/bin/env python3
"""Tests for assertion_property_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "assertion_property_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_valid_assertion(tmp_path):
    sva = tmp_path / "assertions.sv"
    sva.write_text("module assert_mod;\n  property p_valid;\n    @(posedge clk) req |-> ##[1:3] ack;\n  endproperty\n  assert property (p_valid);\n  property p_reset;\n    @(posedge clk) disable iff (!rst_n) data_valid |-> !data_err;\n  endproperty\n  assert property (p_reset);\n  wire a, b, c, d;\n  wire e, f;\nendmodule\n")
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 0

def test_fail_no_assertion_files(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 1

def test_fail_stub_file(tmp_path):
    sva = tmp_path / "stub.sva"
    sva.write_text("// stub\nassert property (p);\n")
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 1
