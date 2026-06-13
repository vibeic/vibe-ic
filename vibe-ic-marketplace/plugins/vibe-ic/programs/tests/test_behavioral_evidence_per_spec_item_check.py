#!/usr/bin/env python3
"""Tests for behavioral_evidence_per_spec_item_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "behavioral_evidence_per_spec_item_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_no_l9(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1

def test_with_l9_and_sim(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l9 = {"submodules": [{"name": "ctrl", "ports": []}], "interfaces": []}
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "sim.log").write_text("PASS: all tests passed\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 1
