#!/usr/bin/env python3
"""Tests for hw_acceptance_test_passed_check.py (LL-24).

v0.119.15 hardening: acceptance_signature.json is REQUIRED when a
pass artifact exists. The EXAMPLE_TESTER-specific byte[6]=0xF2 default is no
longer applied silently — projects must opt in via the named template
or declare their own fingerprint.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / \
    "hw_acceptance_test_passed_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _evidence(tmp_path: Path) -> Path:
    e = tmp_path / "evidence"
    e.mkdir(parents=True, exist_ok=True)
    return e


def test_no_evidence_silent_pass(tmp_path):
    """No hw-debug-loop evidence directory → gate not yet applicable."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not yet applicable" in r.stdout or "PASS" in r.stdout


def test_baseline_present_pass_present_no_signature_fails(tmp_path):
    """v0.119.15 critical: when baseline + pass artifact both exist
    but acceptance_signature.json is missing, the gate must FAIL with
    a clear demand for the signature file. Previously it silently
    used the EXAMPLE_TESTER byte[6]=0xF2 fingerprint."""
    e = _evidence(tmp_path)
    (e / "baseline_fail.json").write_text(json.dumps({
        "verdict": "FAIL", "git_rev": "abc123",
    }))
    (e / "iter_03_pass.json").write_text(json.dumps({
        "verdict": "PASS",
        "e0_frames": [{"byte6": 0xF2}, {"byte6": 0xF2}],
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, \
        f"must FAIL when acceptance_signature.json missing; got: {r.stdout}"
    assert "acceptance_signature.json missing" in r.stdout


def test_example_tester_template_opt_in_passes(tmp_path):
    """Project explicitly opts into the EXAMPLE_TESTER legacy template."""
    e = _evidence(tmp_path)
    (e / "baseline_fail.json").write_text("{}")
    (e / "iter_05_pass.json").write_text(json.dumps({
        "verdict": "PASS",
        "e0_frames": [{"byte6": 0xF2}],
    }))
    (e / "acceptance_signature.json").write_text(json.dumps({
        "template": "example_tester_byte6_F2",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_example_tester_template_opt_in_fails_when_byte6_wrong(tmp_path):
    e = _evidence(tmp_path)
    (e / "baseline_fail.json").write_text("{}")
    (e / "iter_05_pass.json").write_text(json.dumps({
        "verdict": "PASS",
        "e0_frames": [{"byte6": 0x02}],  # 0x02 = the FAIL signature
    }))
    (e / "acceptance_signature.json").write_text(json.dumps({
        "template": "example_tester_byte6_F2",
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "byte[6]=0xF2" in r.stdout


def test_unknown_template_rejected(tmp_path):
    """v0.119.15: typo / unknown template → clear rejection, not
    silent skip or fallback to EXAMPLE_TESTER."""
    e = _evidence(tmp_path)
    (e / "baseline_fail.json").write_text("{}")
    (e / "iter_01_pass.json").write_text(json.dumps({"verdict": "PASS"}))
    (e / "acceptance_signature.json").write_text(json.dumps({
        "template": "spi_lin_byte99_xx",  # not in registry
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "not in registry" in r.stdout


def test_custom_expected_fields_pass(tmp_path):
    """Project-specific fingerprint via direct field equality."""
    e = _evidence(tmp_path)
    (e / "baseline_fail.json").write_text("{}")
    (e / "iter_07_pass.json").write_text(json.dumps({
        "verdict": "PASS",
        "host": "i2c_master",
        "ack_count": 16,
    }))
    (e / "acceptance_signature.json").write_text(json.dumps({
        "expected": {"verdict": "PASS", "ack_count": 16},
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_custom_expected_fields_fail_on_mismatch(tmp_path):
    e = _evidence(tmp_path)
    (e / "baseline_fail.json").write_text("{}")
    (e / "iter_07_pass.json").write_text(json.dumps({
        "verdict": "PASS",
        "ack_count": 12,  # wrong
    }))
    (e / "acceptance_signature.json").write_text(json.dumps({
        "expected": {"verdict": "PASS", "ack_count": 16},
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "ack_count" in r.stdout
