#!/usr/bin/env python3
"""Tests for waiver_legitimacy_check.py — lazy waiver anti-pattern detection."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "waiver_legitimacy_check.py"


def _run(tmp_path: Path, strict: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")]
    if strict:
        cmd.insert(3, "--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _write_waivers(tmp_path: Path, waived_steps: list):
    (tmp_path / "waivers.json").write_text(json.dumps({"waived_steps": waived_steps}))


# -- Test: skip when no waivers.json --

def test_skip_no_waivers(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["skip"] is True
    assert rpt["summary"]["pass"] is True


# -- Test: PASS with legitimate waivers --

def test_pass_legitimate_waivers(tmp_path):
    _write_waivers(tmp_path, [
        {"id": 28, "reason": "Full foundry DRC deck requires NDA sign-off with TSMC.",
         "cascades_to": []},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["pass"] is True
    assert rpt["summary"]["anti_patterns_detected"] == 0


# -- Test: WARN on SYNTH_FAKE (default mode → still PASS) --

def test_warn_synth_fake(tmp_path):
    _write_waivers(tmp_path, [
        {"id": 9, "reason": "Yosys does not support SystemVerilog packages used in RTL.",
         "cascades_to": []},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0  # WARN only, not ERROR
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["anti_patterns_detected"] == 1
    assert rpt["findings"][0]["pattern"] == "SYNTH_FAKE"
    assert rpt["findings"][0]["severity"] == "WARN"


# -- Test: FAIL on SYNTH_FAKE with --strict --

def test_fail_synth_fake_strict(tmp_path):
    _write_waivers(tmp_path, [
        {"id": 9, "reason": "Yosys rejects SystemVerilog enum constructs.",
         "cascades_to": []},
    ])
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["pass"] is False
    assert rpt["findings"][0]["severity"] == "ERROR"


# -- Test: WARN on PNR_FAKE --

def test_warn_pnr_fake(tmp_path):
    _write_waivers(tmp_path, [
        {"id": 14, "reason": "Commercial OpenROAD deck needed for production floorplan.",
         "cascades_to": []},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["anti_patterns_detected"] == 1
    assert rpt["findings"][0]["pattern"] == "PNR_FAKE"


# -- Test: WARN on DRC_FAKE --

def test_warn_drc_fake(tmp_path):
    _write_waivers(tmp_path, [
        {"id": 28, "reason": "KLayout DRC failed: L_lname not defined for metal layers.",
         "cascades_to": []},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["anti_patterns_detected"] == 1
    assert rpt["findings"][0]["pattern"] == "DRC_FAKE"


# -- Test: WARN on ANALOG_OVERWAIVER --

def test_warn_analog_overwaiver(tmp_path):
    _write_waivers(tmp_path, [
        {"id": "A1",
         "reason": "All analog blocks are vendor hardmacro — skip entire analog track.",
         "cascades_to": ["A2", "A3", "A4", "A5", "A6", "A7", "A8"]},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    patterns = [f["pattern"] for f in rpt["findings"]]
    assert "ANALOG_OVERWAIVER" in patterns


# -- Test: WARN on CASCADE_OVERREACH --

def test_warn_cascade_overreach(tmp_path):
    _write_waivers(tmp_path, [
        {"id": 14,
         "reason": "Backend flow deferred to foundry commercial deck.",
         "cascades_to": list(range(15, 34))},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    patterns = [f["pattern"] for f in rpt["findings"]]
    assert "CASCADE_OVERREACH" in patterns


# -- Test: CASCADE_OVERREACH suppressed when plan covers all targets --

def test_pass_cascade_with_plan(tmp_path):
    cascades = list(range(15, 26))
    _write_waivers(tmp_path, [
        {"id": 14,
         "reason": "Legitimate foundry deferral with full closure plan.",
         "cascades_to": cascades},
    ])
    closures = [{"waiver_id": c, "tool": "Innovus", "proof_artefact": f"step{c}.rpt"}
                for c in cascades]
    (tmp_path / "foundry_signoff_plan.json").write_text(json.dumps({
        "foundry_signoff_plan": {"closures": closures}
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    patterns = [f["pattern"] for f in rpt["findings"]]
    assert "CASCADE_OVERREACH" not in patterns
