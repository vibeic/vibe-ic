#!/usr/bin/env python3
"""Tests for payload_bit_position_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "payload_bit_position_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_with_bitmap(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; wire [7:0] data; endmodule\n")
    bm = tmp_path / "bitmap.json"
    bm.write_text(json.dumps({"0": {"0": "bit0", "7": "bit7"}}))
    r = _run([str(tmp_path), "--bitmap", str(bm)]); assert r.returncode == 0
