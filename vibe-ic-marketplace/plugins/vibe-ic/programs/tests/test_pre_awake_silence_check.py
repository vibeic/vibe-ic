#!/usr/bin/env python3
"""Tests for pre_awake_silence_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "pre_awake_silence_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_rtl(tmp_path):
    # #521 — RTL with no wake/sleep signal at all is VACUOUS (rc 2), not a
    # PASS over wake gating that this design does not have.
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)]); assert r.returncode == 2
