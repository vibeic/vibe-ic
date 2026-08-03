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


# ── vibe-ic#693 regressions ───────────────────────────────────────────────
# Every one of these FAILED (or falsely PASSED) before this gate was wired.
# It had never run outside this file, so nothing had ever exercised the
# branch that decides a real project's verdict.

def _l5(tmp_path: Path, detected: bool = True) -> None:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps(
        {"analog_blocks": [{"name": "b0"}], "analog_blocks_detected": detected}))


def test_verdict_recording_no_skip_is_not_a_skip(tmp_path):
    """`{"decision": "NO_SKIP"}` records the OPPOSITE of the defect.

    The skip regex was bare `skip`, so a file whose whole purpose was to
    record that nothing was skipped FAILed the gate that forbids skipping.
    """
    d = _analog_dir(tmp_path)
    _l5(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "NO_SKIP",
         "rationale": "2 analog blocks detected; the analog track runs in full"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_free_prose_in_an_unrelated_field_is_not_a_verdict(tmp_path):
    """A `note` saying "no A-step was skipped" used to decide the verdict,
    because the gate looped over EVERY string value in the document."""
    d = _analog_dir(tmp_path)
    _l5(tmp_path)
    (d / "A0_skip_decision.json").write_text(json.dumps(
        {"decision": "PROCEED", "note": "no A-step was skipped in this run"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_archived_nested_run_is_not_this_runs_verdict(tmp_path):
    """The globs ended in `**/`, so a retained `archive/old_run/...` skip
    decision FAILed a project whose analog track ran in full. The published
    corpus is itself this nested shape (a run dir inside its parent)."""
    _analog_dir(tmp_path)
    _l5(tmp_path)
    nested = tmp_path / "archive" / "old_run" / "analog"
    nested.mkdir(parents=True)
    (nested / "A0_skip_decision.json").write_text(
        json.dumps({"decision": "SKIPPED"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_nested_status_file_cannot_excuse_this_runs_skip(tmp_path):
    """The mirror-image FALSE NEGATIVE of the test above: a REAL top-level
    skip was excused by an A0_implementation_status.json belonging to an
    unrelated nested run. Same unbounded glob, deciding the wrong way."""
    d = _analog_dir(tmp_path)
    _l5(tmp_path)
    (d / "A0_skip_decision.json").write_text(
        json.dumps({"decision": "SKIPPED-CONDITION"}))
    other = tmp_path / "clean_run_old" / "analog"
    other.mkdir(parents=True)
    (other / "A0_implementation_status.json").write_text(
        json.dumps({"blocks": {"ldo": {"A1": "ok"}}}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout


def test_no_analog_verdict_is_still_forbidden(tmp_path):
    """Negation handling must not excuse `NO_ANALOG` / `digital_only`:
    those ARE the forbidden verdict, not a negation of it."""
    for verdict in ("NO_ANALOG", "digital_only"):
        proj = tmp_path / verdict
        d = proj / "analog"
        d.mkdir(parents=True)
        (d / "A0_skip_decision.json").write_text(
            json.dumps({"decision": verdict}))
        r = _run(proj)
        assert r.returncode == 1, f"{verdict}: {r.stdout}{r.stderr}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
