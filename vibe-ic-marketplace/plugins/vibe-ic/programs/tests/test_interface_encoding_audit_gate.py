#!/usr/bin/env python3
"""Tests for interface_encoding_audit.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "interface_encoding_audit.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_clean_rtl(tmp_path):
    (tmp_path / "top.v").write_text("module top(input clk); endmodule\n")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--top-module", "top", "--out-dir", str(out)])
    assert r.returncode == 0
