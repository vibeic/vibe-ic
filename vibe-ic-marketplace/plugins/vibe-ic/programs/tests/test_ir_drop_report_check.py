#!/usr/bin/env python3
"""Tests for ir_drop_report_check.py — wrapper for eda_report_audit --mode ir_drop"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "ir_drop_report_check.py"


def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def test_empty_project(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1


def test_pass_with_pdk_unavailable_waiver(tmp_path):
    """v0.119.21: custom PDK without OpenROAD PSM characterization data
    can declare the unavailability via waiver. ≥20-char reason required."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "ir_drop_report_unavailable_reason":
            "commercial 180nm PDK has no PSM-compatible PDN extraction; "
            "IR-drop deferred until commercial flow",
    }))
    r = _run([str(tmp_path)])
    assert r.returncode == 0, r.stdout


def test_short_reason_rejected(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "ir_drop_report_unavailable_reason": "no tool",
    }))
    r = _run([str(tmp_path)])
    assert r.returncode == 1
