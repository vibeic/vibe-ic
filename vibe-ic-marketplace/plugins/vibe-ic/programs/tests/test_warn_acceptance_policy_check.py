#!/usr/bin/env python3
"""Tests for warn_acceptance_policy_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "warn_acceptance_policy_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_project(tmp_path):
    # #521 — a project with no reports directory is VACUOUS (rc 2): not a
    # single gate report was read, so "every WARN is addressed" is true only
    # because no WARN was ever loaded.
    r = _run(["--project-dir", str(tmp_path)]); assert r.returncode == 2
