#!/usr/bin/env python3
"""Tests for analog_a0_skip_forbidden_check.py.

Covers:
  - no A0_skip_decision.json → PASS
  - A0_skip_decision.json encoding a SKIP, no replacement → FAIL
  - same skip + A0_implementation_status.json replacement → PASS
  - same skip + L5.analog_blocks_detected=false → PASS
  - A0_skip_decision.json present but no skip verdict → PASS
  - garbage / unparsable A0_skip_decision.json → FAIL (honest)
  - missing project dir → rc=2
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent /
        "analog_a0_skip_forbidden_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _analog_dir(tmp_path: Path) -> Path:
    d = tmp_path / "analog"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_no_forbidden_artefact_pass(tmp_path):
    _analog_dir(tmp_path)  # analog/ exists but no A0 file
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_skip_without_replacement_fail(tmp_path):
    """A0_skip_decision.json: SKIPPED-CONDITION, no replacement → FAIL."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "SKIPPED-CONDITION",
         "reason": "looks digital"}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout


def test_skip_with_status_replacement_pass(tmp_path):
    """Skip but A0_implementation_status.json present → PASS."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "skip"}))
    (d / "A0_implementation_status.json").write_text(json.dumps(
        {"blocks": [{"name": "ldo", "A1": "done", "A2": "pending"}]}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_skip_with_l5_detected_false_pass(tmp_path):
    """Skip but L5.analog_blocks_detected=false → PASS."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"status": "no_analog"}))
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps(
        {"analog_blocks_detected": False, "analog_blocks": []}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_present_but_no_skip_verdict_pass(tmp_path):
    """File named A0_skip_decision.json but no skip verdict → PASS."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "proceed", "note": "8 blocks identified"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_garbage_skip_decision_fails_honestly(tmp_path):
    """Unparsable A0_skip_decision.json → FAIL (presence is the defect)."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text("{ not json at all")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout


def test_empty_status_replacement_does_not_rescue(tmp_path):
    """A0_implementation_status.json with empty blocks/steps → still FAIL."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps({"decision": "skip"}))
    (d / "A0_implementation_status.json").write_text(json.dumps(
        {"blocks": [], "steps": []}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def test_missing_project_dir_rc2(tmp_path):
    r = _run(tmp_path / "does_not_exist")
    assert r.returncode == 2, r.stdout + r.stderr


def test_json_report_written(tmp_path):
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps({"decision": "skip"}))
    out = tmp_path / "rep.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["status"] == "FAIL"


# ── REGRESSIONS: the four wrong answers this gate gave the first time it
#    was handed a project tree. Each one was measured before the repair.
#    They are the reason the gate is wired at all — an unwired gate that
#    fails a run for recording the RIGHT thing is worse than no gate.


def test_negated_decision_is_not_a_skip(tmp_path):
    """`NO_SKIP` differs from `SKIPPED` by the two characters the old
    matcher ignored. Measured before the repair: rc 1, evidence
    `decision='NO_SKIP'` — a FAIL for writing down the correct state."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "NO_SKIP",
         "rationale": "2 analog blocks detected; the analog track runs "
                      "in full"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_prose_in_a_non_verdict_field_is_not_a_verdict(tmp_path):
    """The old scan walked EVERY string value, so a note explaining that
    nothing was skipped FAILed the run. Verdicts live in verdict keys."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "PROCEED",
         "note": "no A-step was skipped in this run"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_archived_decision_from_another_run_is_not_this_run(tmp_path):
    """`**/A0_skip_decision.json` reached outside the project's own analog
    roots. An archived decision belonging to a previous run FAILed a
    project whose analog track ran in full."""
    _analog_dir(tmp_path)
    old = tmp_path / "archive" / "old_run" / "analog"
    old.mkdir(parents=True)
    (old / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "SKIPPED-CONDITION"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_foreign_status_file_does_not_excuse_a_real_skip(tmp_path):
    """The same unbounded glob in the OPPOSITE direction, and this is the
    one that matters: a REAL top-level skip was excused (rc 0) by an
    `A0_implementation_status.json` belonging to an unrelated nested run.
    A false negative on the single defect this gate exists for."""
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "SKIPPED-CONDITION"}))
    other = tmp_path / "archive" / "other_run" / "analog"
    other.mkdir(parents=True)
    (other / "A0_implementation_status.json").write_text(json.dumps(
        {"blocks": {"ldo": {"A1": "done"}}}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout


def test_digital_only_is_still_a_skip(tmp_path):
    """Negation-awareness must not disarm the `no analog` family, which
    carries its own leading `no` and IS the forbidden decision."""
    d = tmp_path / "phase1" / "analog"
    d.mkdir(parents=True)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "digital-only"}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def test_boolean_skip_flag_is_a_verdict(tmp_path):
    d = _analog_dir(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps({"skipped": True}))
    assert _run(tmp_path).returncode == 1
    (d / "A0_skip_decision.json").write_text(json.dumps({"skipped": False}))
    assert _run(tmp_path).returncode == 0


def test_report_discloses_where_it_looked(tmp_path):
    """A PASS from a bounded search has to say what the bound was."""
    _analog_dir(tmp_path)
    out = tmp_path / "rep.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["searched_roots"], rep
    assert rep["forbidden_artefact_name"] == "A0_skip_decision.json"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
