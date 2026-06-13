#!/usr/bin/env python3
"""Tests for pdk_analog_completeness_check.py — chip-AGNOSTIC PDK gate.

Covers:
  1. POSITIVE_PASS — L5 declares analog blocks AND all 3 PDK axes
                     (spice / DRC / LVS) are present under input/pdk/.
  2. POSITIVE_FAIL — L5 declares analog blocks AND ≥1 axis missing
                     AND no waiver.
  3. SKIP_NON_APPLICABLE — L5 has analog_blocks_detected: false (no
                     meaningful analog content).
  4. SKIP_NO_CONSTRUCT — no L5_ADI_SPEC.json at all.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "pdk_analog_completeness_check.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


def _write_l5_with_blocks(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "doc_class": "adi_spec",
        "ic_name": "TEST_IC",
        "analog_blocks_detected": True,
        "analog_blocks": [
            {"name": "ldo_main", "type": "ldo", "spec": "1.8 V"},
        ],
    }))


def _make_full_pdk(project: Path) -> None:
    """Create input/pdk/ with all 3 axes satisfied."""
    pdk = project / "input" / "pdk"
    (pdk / "spice").mkdir(parents=True)
    (pdk / "spice" / "models.lib").write_text("* SPICE model\n")
    (pdk / "klayout").mkdir(parents=True)
    (pdk / "klayout" / "drc.drc").write_text("# klayout DRC deck\n")
    (pdk / "netgen").mkdir(parents=True)
    (pdk / "netgen" / "lvs.tcl").write_text("# netgen LVS\n")


# -- Test 1: POSITIVE_PASS --

def test_positive_pass_all_axes(tmp_path):
    _write_l5_with_blocks(tmp_path)
    _make_full_pdk(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "all 3 PDK axes" in r.stdout


# -- Test 2: POSITIVE_FAIL — missing DRC + LVS axes --

def test_positive_fail_missing_axes(tmp_path):
    _write_l5_with_blocks(tmp_path)
    pdk = tmp_path / "input" / "pdk" / "spice"
    pdk.mkdir(parents=True)
    (pdk / "models.lib").write_text("* SPICE only\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout
    assert "drc_deck" in r.stdout
    assert "lvs_deck" in r.stdout


# -- Test 3: SKIP_NON_APPLICABLE — analog_blocks_detected: false --

def test_skip_no_analog_blocks(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "doc_class": "adi_spec",
        "ic_name": "PURE_DIGITAL_IC",
        "analog_blocks_detected": False,
        "analog_blocks": [],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout
    assert "no L5.analog_blocks" in r.stdout


# -- Test 4: SKIP_NO_CONSTRUCT — no L5 file --

def test_skip_no_l5_file(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout


# -- Test 5: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    _write_l5_with_blocks(tmp_path)
    # Only SPICE axis present — DRC + LVS missing.  Need 2 waivers.
    pdk = tmp_path / "input" / "pdk" / "spice"
    pdk.mkdir(parents=True)
    (pdk / "models.lib").write_text("* SPICE\n")
    rationale = (
        "Foundry NDA pending; DRC/LVS decks delivered Q3 next year per "
        "ticket PDK-555 — placeholder waiver covers two missing axes."
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "pdk_analog_deck_pending_foundry_nda": [rationale, rationale],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_WITH_WAIVER]" in r.stdout


# -- Test 6: usage error --

def test_usage_error():
    r = subprocess.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 2


# -- Test 7: error on non-existent dir --

def test_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# v0.1.62 — low_confidence blocks are advisory, NOT gating (spm benchmark).
# spm's L5 lifted a "dac" block from a NEGATED sentence
# ("→ 不需 … analog trim DAC 等" = the DAC is NOT needed); both speculative
# blocks were marked low_confidence:true. A low-confidence guess must not
# hard-block the silicon flow by demanding spice/drc/lvs decks.
# ---------------------------------------------------------------------------
def _write_l5(project: Path, blocks, detected=True):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "doc_class": "adi_spec",
        "ic_name": "TEST_IC",
        "analog_blocks_detected": detected,
        "analog_blocks": blocks,
    }))


def test_low_confidence_blocks_do_not_gate(tmp_path):
    # spm-shape: two low_confidence speculative blocks, no PDK decks present.
    _write_l5(tmp_path, [
        {"name": "dac", "type": "dac", "low_confidence": True,
         "evidence": "L6 (DAC) — negated context"},
        {"name": "esd", "type": "esd", "low_confidence": True},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0, f"low-confidence blocks must not FAIL: {r.stdout}"


def test_high_confidence_block_still_gates(tmp_path):
    # A real (high-confidence) analog block with NO decks must still FAIL.
    _write_l5(tmp_path, [
        {"name": "ldo_main", "type": "ldo", "spec": "1.8 V"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1, f"real analog block w/o decks must FAIL: {r.stdout}"


def test_mixed_only_high_confidence_counts(tmp_path):
    # One low-confidence + one high-confidence → still gates on the real one.
    _write_l5(tmp_path, [
        {"name": "dac", "type": "dac", "low_confidence": True},
        {"name": "bandgap", "type": "bandgap", "spec": "1.2 V ref"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1
