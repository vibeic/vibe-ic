#!/usr/bin/env python3
"""Tests for waivers_schema_check.py."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "waivers_schema_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_skip_no_waivers(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode == 0

def test_pass_valid_schema(tmp_path):
    waivers = {"waived_steps": [
        {"id": 28, "reason": "Full foundry DRC deck requires NDA sign-off with TSMC vendor.",
         "evidence": "email_thread_123", "ticket_id": "TICK-1",
         "review_required": True, "cascades_to": [], "approver": "eng_lead"}
    ]}
    (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    r = _run(str(tmp_path))
    assert r.returncode == 0

def test_fail_missing_approver(tmp_path):
    waivers = {"waived_steps": [
        {"id": 28, "reason": "Short", "cascades_to": []}
    ]}
    (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    r = _run(str(tmp_path))
    assert r.returncode == 1


def test_per_gate_waivers_only_no_waived_steps_passes(tmp_path):
    """v0.119.21: a project may have waivers.json containing only per-gate
    keys (no flow-step waivers). Earlier code rejected this with
    'top-level-structure: must be {waived_steps: [...]}' even though the
    per-gate keys are valid and consumed by individual gate scripts.
    Now: the schema validator accepts any JSON dict; absent waived_steps
    just means there are no flow-step waivers to validate."""
    waivers = {
        "frame_end_idle_reset_alternative":
            "Uses EOM bit in CRC byte instead of gap counter — confirmed by oracle dump",
        "otp_field_map_unresolved": [
            "AV — vendor doc names but does not place; needs silicon decode"
        ],
    }
    (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    r = _run(str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_top_level_must_be_dict(tmp_path):
    """Negative: a waivers.json that's a list (not a dict) is still invalid."""
    (tmp_path / "waivers.json").write_text(json.dumps([{"id": 1}]))
    r = _run(str(tmp_path))
    assert r.returncode == 1
    assert "JSON object" in r.stdout or "JSON object" in r.stderr


def test_review_required_missing_warns(tmp_path):
    """v1.6.12: missing review_required field should emit a WARN
    (not ERROR by default) so PASS exit code is preserved but the
    omission is visible."""
    waivers = {"waived_steps": [
        {"id": 28,
         "reason": "Foundry DRC deck requires NDA sign-off with vendor.",
         "approver": "eng_lead",
         "ticket": "TICK-1"}
    ]}
    (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    r = _run(str(tmp_path))
    # Default mode: WARN, exit 0 (no errors).
    assert r.returncode == 0, r.stdout + r.stderr
    assert "review-required-missing" in r.stdout or "review_required" in r.stdout


def test_review_required_strict_fails(tmp_path):
    """v1.6.12: with --strict-review-required, missing field is ERROR."""
    waivers = {"waived_steps": [
        {"id": 28,
         "reason": "Foundry DRC deck requires NDA sign-off with vendor.",
         "approver": "eng_lead",
         "ticket": "TICK-1"}
    ]}
    (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    r = _run(str(tmp_path), "--strict-review-required")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "review-required-missing" in r.stdout
