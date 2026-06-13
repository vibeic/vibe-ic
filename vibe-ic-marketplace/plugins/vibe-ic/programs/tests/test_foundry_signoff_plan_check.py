#!/usr/bin/env python3
"""Tests for foundry_signoff_plan_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "foundry_signoff_plan_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_no_plan(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_with_plan(tmp_path):
    plan = {"foundry_signoff_plan": {"closures": [
        {"waiver_id": 14, "tool": "Innovus", "proof_artefact": "step14.rpt"}
    ]}}
    (tmp_path / "foundry_signoff_plan.json").write_text(json.dumps(plan))
    r = _run([str(tmp_path)])
    assert r.returncode == 0
