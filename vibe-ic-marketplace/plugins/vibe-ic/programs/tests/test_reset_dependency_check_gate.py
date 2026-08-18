#!/usr/bin/env python3
"""Tests for reset_dependency_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "reset_dependency_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_project(tmp_path):
    """ORGANIC #887 — an EMPTY project is not a clean one.

    This asserted rc 0, the flow's word for "I examined the design and found it
    correct", for a scan that read zero files. rc 2 is the shared input-missing
    code (`_vacuous_exit.RC_VACUOUS`); the clause still passes and the P0
    umbrella records a SKIP rather than a plain PASS. The disclosure line is
    pinned in `test_organic887_zero_file_scan_is_not_a_plain_pass.py`.
    """
    r = _run([str(tmp_path)]); assert r.returncode == 2
