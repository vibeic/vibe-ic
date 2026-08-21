#!/usr/bin/env python3
"""Tests for memory_read_pipeline_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "memory_read_pipeline_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    """v1.6.125 (#47 Fix 3) — registered_read_undocumented is a WARN
    finding. Per #47 spec, WARN-only must NOT gate the flow. Earlier
    behaviour escalated WARN to exit 1; corrected to exit 0 with
    verdict=WARN surfaced via JSON for visibility.
    """
    rtl = tmp_path / "mem.v"
    rtl.write_text("module mem(input clk, input [7:0] addr, output reg [7:0] data);\n  reg [7:0] ram [0:255];\n  always @(posedge clk) data <= ram[addr];\nendmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0  # WARN-only no longer gates the flow.
