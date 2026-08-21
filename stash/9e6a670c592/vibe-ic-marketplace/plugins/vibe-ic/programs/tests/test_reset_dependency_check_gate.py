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
    """ORGANIC #887 — an empty tree is a DISCLOSED vacuous pass, not a PASS.

    This assertion used to read `returncode == 0`, which is how the defect
    survived: the gate answered rc 0 with zero bytes of output over a tree it
    had never read, `flow_compliance_check` scored that a plain PASS, and the
    step stayed in the published `X/Y executed PASS` numerator. The test that
    should have caught it was pinning it instead.
    """
    r = _run([str(tmp_path)])
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    combined = (r.stdout or "") + (r.stderr or "")
    assert any(line.lstrip().startswith("VACUOUS_PASS")
               for line in combined.splitlines()), combined
