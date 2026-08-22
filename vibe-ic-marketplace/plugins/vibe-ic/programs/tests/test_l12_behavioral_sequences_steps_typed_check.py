#!/usr/bin/env python3
"""Tests for l12_behavioral_sequences_steps_typed_check.py (Wave 38 / B6)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l12_behavioral_sequences_steps_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l12):
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L12_BEHAVIORAL_SEQUENCES.json").write_text(
        json.dumps(l12)
    )
    return proj


def test_skip_when_no_l12(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_sequences(tmp_path):
    proj = _make(tmp_path, {"description": "x"})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_steps_missing(tmp_path):
    proj = _make(tmp_path, {"sequences": [
        {"name": "wake_handshake", "description": "free-form prose"},
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "steps" in r.stdout


def test_fail_when_steps_lack_detail(tmp_path):
    proj = _make(tmp_path, {"sequences": [
        {"name": "wake", "trigger": "host_BR",
         "steps": [{"action": "drive_low"},
                   {"action": "release"}]},
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "expected_signal" in r.stdout or "latency_us" in r.stdout


def test_pass_with_typed_steps(tmp_path):
    proj = _make(tmp_path, {"sequences": [
        {"name": "wake_handshake", "trigger": "host_BR",
         "steps": [
             {"action": "drive_id_bus_low",
              "expected_signal": "id_bus=0",
              "latency_us": 0},
             {"action": "release", "next_state": "WAIT_RX",
              "duration_us": 24},
         ]},
    ]})
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_with_alias_keys(tmp_path):
    proj = _make(tmp_path, {"behavioral_sequences": [
        {"id": "engineer_mode_entry", "entry": "0x70 0x55 0xAA",
         "phases": [
             {"action": "send_unlock", "expected": "ack=1",
              "duration_us": 100},
         ]},
    ]})
    r = _run(proj)
    assert r.returncode == 0


# Wave 43 (v0.119.75) — ic_class_profile SKIP case.
def test_skip_on_pure_analog(tmp_path):
    """Pure-analog parts have no behavioural protocol."""
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "PMIC-X", "interface": "pure analog"})
    )
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(
        json.dumps({"ic_name": "PMIC-X", "interface": "pure analog"})
    )
    (proj / "phase1" / "generated_docs" / "L5_ADI_SPEC.json").write_text(
        json.dumps({"analog_blocks": [{"name": "BANDGAP_REF"}]})
    )
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=pure_analog" in r.stdout
