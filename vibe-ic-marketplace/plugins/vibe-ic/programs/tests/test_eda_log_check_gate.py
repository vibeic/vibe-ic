#!/usr/bin/env python3
"""Tests for eda_log_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "eda_log_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_log(tmp_path):
    log = tmp_path / "synth.log"
    log.write_text("Starting synthesis...\nDone. 0 errors, 0 warnings.\n")
    r = _run(["--log-file", str(log)])
    assert r.returncode == 0

def test_reject_pattern(tmp_path):
    log = tmp_path / "err.log"
    log.write_text("FATAL ERROR: out of memory\n")
    r = _run(["--log-file", str(log), "--reject-pattern", "FATAL"])
    assert r.returncode == 1
