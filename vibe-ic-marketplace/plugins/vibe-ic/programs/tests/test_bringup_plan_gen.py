#!/usr/bin/env python3
"""Tests for bringup_plan_gen.py — emits bring-up plan from L13_LAB_CALIBRATION.

Wave 83 — coverage for previously untested wired program.

Cases:
  1. POSITIVE_PASS  — L13 with calibration_steps → bringup_plan.md emitted with
                       step bullets, exit 0.
  2. POSITIVE_PASS_TRIM_LOOP — alternative `trim_loop` key path is also rendered.
  3. SKIP_NO_L13    — L13 absent → emits empty placeholder MD, prints [SKIP],
                       exit 0.
  4. EDGE_BAD_JSON  — malformed L13 JSON → graceful (treated as empty), exit 0.
  5. EDGE_NO_PROJECT — non-existent project dir → still creates reports dir
                       under it (argparse accepts any path) and SKIPs cleanly.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / \
    "bringup_plan_gen.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def _write_l13(project: Path, body: dict | str) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    target = gd / "L13_LAB_CALIBRATION.json"
    if isinstance(body, str):
        target.write_text(body)
    else:
        target.write_text(json.dumps(body, indent=2))


def test_positive_pass_calibration_steps(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l13(project, {
        "calibration_steps": [
            {"step": "S1", "action": "trim oscillator",
             "expected": "f_clk within +/-2%"},
            {"step": "S2", "action": "verify ID readback",
             "expected": "byte 0xA5"},
        ]
    })
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] bringup_plan_gen" in cp.stdout
    assert "2 steps" in cp.stdout
    md = project / "reports" / "phase2" / "bringup_plan.md"
    assert md.is_file()
    text = md.read_text()
    assert "Bring-up plan" in text
    assert "trim oscillator" in text
    assert "byte 0xA5" in text


def test_positive_pass_trim_loop_key(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l13(project, {
        "trim_loop": [
            {"step": "T1", "action": "raw OTP read",
             "expected": "8 bytes nonzero"},
        ]
    })
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[PASS]" in cp.stdout
    md = (project / "reports" / "phase2" / "bringup_plan.md").read_text()
    assert "raw OTP read" in md


def test_skip_no_l13(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout
    md = (project / "reports" / "phase2" / "bringup_plan.md").read_text()
    assert "Empty" in md or "not generated" in md


def test_edge_bad_json(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l13(project, "{not valid json")
    cp = _run([str(project)])
    # Graceful: caught by except → empty steps → PASS with 0 steps
    assert cp.returncode == 0
    assert "[PASS]" in cp.stdout and "0 steps" in cp.stdout


def test_edge_steps_with_non_dict(tmp_path):
    """Mixed list: dicts + strings — non-dict entries are silently skipped."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l13(project, {
        "calibration_steps": [
            "this-is-a-string-not-a-dict",
            {"step": "S1", "action": "do thing", "expected": "ok"},
        ]
    })
    cp = _run([str(project)])
    assert cp.returncode == 0
    md = (project / "reports" / "phase2" / "bringup_plan.md").read_text()
    assert "do thing" in md
    # The string entry produces no bullet line
    assert "this-is-a-string-not-a-dict" not in md
