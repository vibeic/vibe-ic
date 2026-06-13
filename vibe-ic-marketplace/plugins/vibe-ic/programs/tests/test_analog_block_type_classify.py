#!/usr/bin/env python3
"""Tests for analog_block_type_classify.py.

Covers:
  - single-name classification (PASS / OK cases across taxonomy)
  - UNKNOWN for un-classifiable names (honest, not vacuous)
  - --block-list consistency PASS
  - --block-list FAIL when declared type contradicts the name
  - missing / garbage block-list FAILs honestly (rc=2)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent /
        "analog_block_type_classify.py")


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), *args],
        capture_output=True, text=True,
    )


@pytest.mark.parametrize("name,expected", [
    ("ldo_1v8", "LDO"),
    ("main_regulator", "LDO"),
    ("bgr_ref", "Bandgap"),
    ("bandgap", "Bandgap"),
    ("ring_osc", "Oscillator"),
    ("rcOscillator", "Oscillator"),
    ("por_block", "POR"),
    ("sar_adc", "ADC"),
    ("dac_8b", "DAC"),
    ("main_pll", "PLL"),
    ("charge_pump", "Charge_pump"),
    ("input_comparator", "Comparator"),
    ("bias_gen", "Bias"),
    ("level_shift_io", "Level_shifter"),
    ("esd_clamp", "ESD"),
    ("rpd_wake", "Pull"),
    ("trim_otp", "Trim"),
])
def test_single_name_classify(name, expected):
    """Name→type taxonomy lookup is deterministic and correct."""
    r = _run(name)
    assert r.returncode == 0, r.stderr
    assert f"-> {expected}" in r.stdout, r.stdout


def test_unknown_name_is_honest():
    """A name with no taxonomy token classifies UNKNOWN (not a guess)."""
    r = _run("widget_xyzzy")
    assert r.returncode == 0
    assert "-> UNKNOWN" in r.stdout, r.stdout


def test_block_list_consistent_pass(tmp_path):
    """Every block's declared type matches the name → PASS."""
    bl = tmp_path / "analog_block_list.json"
    bl.write_text(json.dumps({
        "blocks": [
            {"name": "ldo_1v8", "type": "LDO",
             "spec_file": "analog/ldo_1v8/spec.json"},
            {"name": "main_bandgap", "type": "Bandgap",
             "spec_file": "analog/main_bandgap/spec.json"},
            {"name": "rc_osc", "type": "RC_oscillator",
             "spec_file": "analog/rc_osc/spec.json"},
        ],
        "block_count": 3,
    }))
    r = _run("--block-list", str(bl))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_block_list_conflict_fail(tmp_path):
    """A block whose declared type contradicts its name → FAIL.

    This catches a REAL mislabel: name 'ldo_1v8' but type 'Oscillator'.
    """
    bl = tmp_path / "analog_block_list.json"
    bl.write_text(json.dumps({
        "blocks": [
            {"name": "ldo_1v8", "type": "Oscillator",
             "spec_file": "analog/ldo_1v8/spec.json"},
        ],
        "block_count": 1,
    }))
    r = _run("--block-list", str(bl))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CONFLICT" in r.stdout
    assert "[FAIL]" in r.stdout


def test_block_list_unknown_name_not_a_fail(tmp_path):
    """Un-classifiable name → declared type trusted, NOT a conflict."""
    bl = tmp_path / "analog_block_list.json"
    bl.write_text(json.dumps({
        "blocks": [
            {"name": "custom_frontend", "type": "OTA_OpAmp",
             "spec_file": "analog/custom_frontend/spec.json"},
        ],
        "block_count": 1,
    }))
    r = _run("--block-list", str(bl))
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_block_list_fails_honestly(tmp_path):
    """Absent file → rc=2 (honest IO error, never vacuous PASS)."""
    r = _run("--block-list", str(tmp_path / "nope.json"))
    assert r.returncode == 2, r.stdout + r.stderr


def test_garbage_block_list_fails_honestly(tmp_path):
    """Unparsable JSON → rc=2 (honest), never vacuous PASS."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json")
    r = _run("--block-list", str(bad))
    assert r.returncode == 2, r.stdout + r.stderr


def test_json_report_written(tmp_path):
    out = tmp_path / "rep.json"
    r = _run("ldo_1v8", "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["type"] == "LDO"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
