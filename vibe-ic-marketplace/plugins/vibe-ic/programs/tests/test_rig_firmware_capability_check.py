#!/usr/bin/env python3
"""Tests for rig_firmware_capability_check.py — Wave 58 BACKLOG-v12 P0.5.

Covers four applicability paths:
  1. POSITIVE_PASS — capability gap declared + explicit waiver present.
  2. POSITIVE_FAIL — capability gap (or NEEDS_FIRMWARE_SUPPORT in
                     reports/) + no `rig_firmware_*` waiver.
  3. SKIP_NON_APPLICABLE — rig_capabilities.json present but fully
                     supports required modes (no gap, no triggers).
  4. SKIP_NO_CONSTRUCT — no rig_capabilities.json AND no reports/ entry.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "rig_firmware_capability_check.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


# -- Test 1: POSITIVE_PASS — capability gap + waiver --

def test_positive_pass_with_waiver(tmp_path):
    (tmp_path / "rig_capabilities.json").write_text(json.dumps({
        "rig_id": "test-rig-1.0",
        "supported_modes": ["connect_test", "send_raw"],
        "required_modes": ["connect_test", "send_raw", "force_low_pulse"],
    }))
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rig_firmware_blocker":
        "test-rig-1.0 firmware lacks force_low_pulse mode; ticket "
        "RIG-202 tracks firmware update; expected v1.1 release.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
    assert "force_low_pulse" in r.stdout


# -- Test 2: POSITIVE_FAIL — capability gap, no waiver --

def test_positive_fail_no_waiver(tmp_path):
    (tmp_path / "rig_capabilities.json").write_text(json.dumps({
        "rig_id": "test-rig-1.0",
        "supported_modes": ["connect_test"],
        "required_modes": ["connect_test", "force_low_pulse"],
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "force_low_pulse" in r.stdout
    assert "rig_firmware_" in r.stdout


# -- Test 2b: POSITIVE_FAIL via report scan trigger --

def test_positive_fail_report_trigger(tmp_path):
    rep = tmp_path / "reports" / "wave99"
    rep.mkdir(parents=True)
    (rep / "fpga_step.json").write_text(json.dumps({
        "step": "force_low_500ms",
        "verdict": "NEEDS_FIRMWARE_SUPPORT",
        "detail": "rig example_tester lacks long-low pulse mode",
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "NEEDS_FIRMWARE_SUPPORT" in r.stdout or \
        "fpga_step.json" in r.stdout


# -- Test 3: SKIP_NON_APPLICABLE — rig fully supports required modes --

def test_skip_no_gap(tmp_path):
    (tmp_path / "rig_capabilities.json").write_text(json.dumps({
        "rig_id": "fully-capable-rig",
        "supported_modes": ["connect_test", "send_raw", "force_low_pulse"],
        "required_modes": ["connect_test", "send_raw"],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# -- Test 4: SKIP_NO_CONSTRUCT — neither rig_capabilities.json nor
#    NEEDS_FIRMWARE_SUPPORT report exists.

def test_skip_no_construct(tmp_path):
    # Empty project — no rig_capabilities.json, no reports/.
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no rig firmware blocker" in r.stdout or "no rig" in \
        r.stdout.lower()


# -- Test 5: SKIP — reports/ exists but no triggers --

def test_skip_clean_reports(tmp_path):
    rep = tmp_path / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "clean.json").write_text(json.dumps({
        "step": "fpga_compile", "verdict": "PASS",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# -- Test 6: usage error --

def test_usage_error():
    r = subprocess.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 2
