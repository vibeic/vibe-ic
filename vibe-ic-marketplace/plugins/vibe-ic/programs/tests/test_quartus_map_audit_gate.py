#!/usr/bin/env python3
"""Tests for quartus_map_audit.py."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "quartus_map_audit.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_pass_clean_report(tmp_path):
    rpt = tmp_path / "test.map.rpt"
    rpt.write_text("Analysis & Synthesis report\nInfo: Total logic elements: 100\n")
    r = _run(str(rpt))
    assert r.returncode == 0

def test_fail_stuck_at_gnd(tmp_path):
    rpt = tmp_path / "test.map.rpt"
    rpt.write_text("Analysis & Synthesis report\nWarning: Stuck at GND due to missing driver\n")
    r = _run(str(rpt))
    assert r.returncode == 1
