#!/usr/bin/env python3
"""Tests for def_stage_progression_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "def_stage_progression_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_no_def_files(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1

def test_with_def_file(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "floorplan.def").write_text("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 10 ;\nEND COMPONENTS\nEND DESIGN\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 1
