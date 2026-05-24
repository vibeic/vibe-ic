#!/usr/bin/env python3
"""Tests for internal_vs_external_timing_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "internal_vs_external_timing_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_waveform(tmp_path):
    wf = tmp_path / "L8_TIMING_WAVEFORM.json"
    wf.write_text(json.dumps({"waveforms": []}))
    r = _run([str(wf)])
    assert r.returncode == 1
