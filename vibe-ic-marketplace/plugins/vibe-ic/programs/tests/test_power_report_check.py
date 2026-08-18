#!/usr/bin/env python3
"""Tests for power_report_check.py — wrapper for eda_report_audit --mode power"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "power_report_check.py"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def test_empty_project(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1


def test_pass_with_pdk_unavailable_waiver(tmp_path):
    """v0.119.22: parallel to ir_drop / spef. Custom PDK without
    OpenROAD power-characterization data can declare unavailability via
    waiver. ≥20-char reason required (anti-rubber-stamp policy)."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "power_report_unavailable_reason":
            "commercial 180nm PDK has no OpenROAD power group definition; "
            "switching/leakage analysis deferred until commercial flow",
    }))
    r = _run([str(tmp_path)])
    assert r.returncode == 0, r.stdout


def test_short_reason_rejected(tmp_path):
    """A reason under 20 chars must NOT silence the gate (anti-rubber-stamp)."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "power_report_unavailable_reason": "no tool",
    }))
    r = _run([str(tmp_path)])
    assert r.returncode == 1
