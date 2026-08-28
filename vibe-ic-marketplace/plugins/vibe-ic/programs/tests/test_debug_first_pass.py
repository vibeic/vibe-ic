#!/usr/bin/env python3
"""Tests for debug_first_pass.py — single dispatcher for 7 debug-tier first-pass.

Wave 83 — coverage for previously untested wired program.

The program writes <project>/reports/<step>_first_pass.json with
verdict=PASS_DEFERRED_TO_AI for any of seven valid step names. It is a
chip-AGNOSTIC scaffold whose role is to (a) validate inputs (b) emit a
machine-readable artefact pointing AI debug skills at the next step.

Cases:
  1. POSITIVE_PASS_drc_fix — emits drc_fix_first_pass.json with verdict.
  2. POSITIVE_PASS_synth_doctor — different step, same template path.
  3. POSITIVE_FAIL_invalid_step — argparse choices reject typo, exit 2.
  4. POSITIVE_FAIL_missing_project — non-existent project dir → exit 2.
  5. EDGE_ARTIFACT_SCHEMA — emitted JSON must contain step / description /
                            verdict / note keys.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / \
    "debug_first_pass.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def test_positive_pass_drc_fix(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "drc_fix"])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS_DEFERRED]" in cp.stdout
    assert "drc-fix" in cp.stdout  # skill name with dashes
    out = project / "reports" / "phase3" / "drc_fix_first_pass.json"
    assert out.is_file()
    body = json.loads(out.read_text())
    assert body["step"] == "drc_fix"
    assert body["verdict"] == "PASS_DEFERRED_TO_AI"


def test_positive_pass_synth_doctor(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "synth_doctor"])
    assert cp.returncode == 0
    out = project / "reports" / "phase2" / "synth_doctor_first_pass.json"
    body = json.loads(out.read_text())
    assert body["step"] == "synth_doctor"
    assert "synth" in body["description"].lower()
    assert "synth-doctor" in body["note"]


def test_positive_fail_invalid_step(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "not_a_real_step"])
    # argparse rejects unknown choices with exit 2.
    assert cp.returncode == 2
    assert "invalid choice" in cp.stderr or "invalid choice" in cp.stdout


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "does_not_exist"
    cp = _run([str(missing), "drc_fix"])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_edge_artifact_schema_complete(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "ir_drop_triage"])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase3" / "ir_drop_triage_first_pass.json").read_text())
    assert set(body.keys()) >= {"step", "description", "verdict", "note"}
    # No chip-specific identifiers in placeholder content.
    assert "EXAMPLE_CHIP" not in body["note"]
    assert "EXAMPLE_TESTER" not in body["note"]


def test_all_seven_steps_succeed(tmp_path):
    """Sanity: all 7 documented step names work."""
    valid = ["drc_fix", "hold_fix", "ir_drop_triage", "lvs_triage",
             "ppa_predict", "sta_review", "synth_doctor"]
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    step_phase = {
        "drc_fix": "phase3", "hold_fix": "phase3",
        "ir_drop_triage": "phase3", "lvs_triage": "phase3",
        "ppa_predict": "phase2", "sta_review": "phase3",
        "synth_doctor": "phase2",
    }
    for step in valid:
        cp = _run([str(project), step])
        assert cp.returncode == 0, f"step={step} failed: {cp.stderr}"
        out = project / "reports" / step_phase[step] / f"{step}_first_pass.json"
        assert out.is_file()
