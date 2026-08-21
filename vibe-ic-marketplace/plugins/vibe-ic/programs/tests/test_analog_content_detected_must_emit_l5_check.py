#!/usr/bin/env python3
"""Tests for analog_content_detected_must_emit_l5_check.py — Wave 47.

Verifies:
  - oscillator in docs + L5 has osc entry → PASS
  - oscillator in docs + L5 empty → FAIL
  - trim mention + L4 trim_registers → PASS (no L5 trim entry needed)
  - pure-digital docs → VACUOUS (rc 2, #833 — NOT a pass)
  - waiver covers all missing classes → PASS
  - "no analog" line negation → VACUOUS (rc 2, #833)

#833 moved the "nothing to compare" branch off rc 0. This file used to
assert rc 0 for it, i.e. it pinned the very credit the defect handed out:
the P0 structural umbrella reads the exit code and nothing else, so a
project whose docs mention no analog content held a full executed PASS for
a gate that had examined nothing. The keyword/negation SUBJECTS below are
unchanged; only the rc those branches leave behind moved.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _vacuous_exit as _vx  # noqa: E402

PROG = PROGRAMS / "analog_content_detected_must_emit_l5_check.py"


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _setup(tmp_path: Path, doc_text: str = "",
           l5: dict | None = None,
           l4: dict | None = None,
           waiver: dict | None = None) -> Path:
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "spec.txt").write_text(doc_text, encoding="utf-8")
    if l5 is not None:
        gd = tmp_path / "phase1" / "generated_docs"
        gd.mkdir(parents=True, exist_ok=True)
        (gd / "L5_ADI_SPEC.json").write_text(json.dumps(l5))
    if l4 is not None:
        gd = tmp_path / "phase1" / "generated_docs"
        gd.mkdir(parents=True, exist_ok=True)
        (gd / "L4_REGMAP.json").write_text(json.dumps(l4))
    if waiver is not None:
        (tmp_path / "waivers.json").write_text(json.dumps(waiver))
    return tmp_path


def test_oscillator_in_docs_l5_has_entry_pass(tmp_path):
    """fOSC mentioned in docs + L5 has oscillator entry → PASS."""
    doc = "fOSC = 4 MHz, FREQ_TRIM 99-101%\nTypical operation."
    l5 = {
        "schema_version": "1.0",
        "analog_blocks": [
            {"name": "main_oscillator", "type": "RC_oscillator",
             "freq_mhz": 4.0,
             "spec": "fOSC=4MHz",
             "evidence": "spec.txt:1"},
        ],
        "analog_blocks_detected": True,
    }
    _setup(tmp_path, doc, l5=l5)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_oscillator_in_docs_l5_empty_fail(tmp_path):
    """fOSC mentioned in docs + L5 analog_blocks=[] → FAIL."""
    doc = "Oscillator: fOSC = 4 MHz\nFREQ_TRIM range 3.96-4.04 MHz"
    l5 = {"schema_version": "1.0", "analog_blocks": []}
    _setup(tmp_path, doc, l5=l5)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "oscillator" in r.stdout.lower()


def test_trim_in_docs_l4_trim_registers_pass(tmp_path):
    """TRIM_VBG in docs + L4.otp_layout.trim_registers populated → PASS."""
    doc = "TRIM_VBG controls bandgap. TRIM_LDO controls regulator output."
    # L5 has bandgap entry to satisfy the bandgap class hit on "bandgap"
    # and "regulator" word in doc, plus an LDO entry for the LDO class.
    l5 = {"schema_version": "1.0",
          "analog_blocks": [
              {"name": "bg", "type": "bandgap", "spec": "VBG"},
              {"name": "ldo1", "type": "LDO", "spec": "regulator"},
          ]}
    l4 = {"otp_layout": {
        "trim_registers": [
            {"name": "TRIM_VBG", "addr": 112},
            {"name": "TRIM_LDO", "addr": 113},
        ]
    }}
    _setup(tmp_path, doc, l5=l5, l4=l4)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_no_analog_keywords_skip(tmp_path):
    """Pure-digital docs (only counters, FSM, registers) → VACUOUS, not PASS.

    #833: the docs were read and none of them describes analog content, so
    there is no doc-evidence-to-L5 correspondence for this gate to judge.
    That is `_vx.RC_VACUOUS`, never rc 0.
    """
    doc = "Counter module increments by 1 every clock. FSM has 5 states."
    _setup(tmp_path, doc)
    r = _run(tmp_path)
    assert r.returncode == _vx.RC_VACUOUS, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Explicit waiver per missing block → PASS."""
    doc = ("Oscillator: fOSC = 4 MHz\n"
           "RPD_WAKE 80-120 kΩ pull-down resistor\n"
           "ESD protection device on DP pin")
    l5 = {"schema_version": "1.0", "analog_blocks": []}
    waiver = {
        "analog_block_in_docs_intentionally_omitted_from_l5": [
            "Oscillator implementation deferred to A2 topology selection round; "
            "FREQ_TRIM range documented but design work pending.",
            "RPD_WAKE pull-down: hardmacro will be sourced from foundry library "
            "rather than custom SPICE block; documented in BACKLOG-v12.",
            "ESD protection: standard foundry ESD cell will be used; no custom "
            "design needed; foundry IP catalog reference in tapeout package.",
        ]
    }
    _setup(tmp_path, doc, l5=l5, waiver=waiver)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_keyword_negation_skip(tmp_path):
    """'no analog' / 'digital only' line → not classified as analog hit.

    Negation still suppresses the hit (the subject of this test). With no
    class claimed there is nothing to compare, so #833 makes the rc
    `_vx.RC_VACUOUS`.
    """
    doc = ("This block is digital only.\n"
           "No analog content.\n"
           "Pure digital counter chain.")
    _setup(tmp_path, doc)
    r = _run(tmp_path)
    assert r.returncode == _vx.RC_VACUOUS, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_pull_down_in_docs_l5_has_pull_entry_pass(tmp_path):
    """Pull-down resistor → L5 pulldown entry → PASS."""
    doc = "RPD_WAKE 80-120 kΩ internal pull-down resistor"
    l5 = {"schema_version": "1.0",
          "analog_blocks": [
              {"name": "rpd_wake", "type": "pulldown_resistor",
               "spec": "RPD_WAKE 80-120 kΩ"},
          ]}
    _setup(tmp_path, doc, l5=l5)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_l5_file_with_keywords_fail(tmp_path):
    """Keywords in docs but no L5 file at all → FAIL."""
    doc = "Oscillator fOSC 4MHz. LDO regulator. ESD protection."
    _setup(tmp_path, doc)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def test_waiver_too_short_fails(tmp_path):
    """Waiver string under 40 chars rejected → FAIL persists."""
    doc = "fOSC = 4 MHz oscillator block"
    l5 = {"schema_version": "1.0", "analog_blocks": []}
    waiver = {
        "analog_block_in_docs_intentionally_omitted_from_l5": "too short"
    }
    _setup(tmp_path, doc, l5=l5, waiver=waiver)
    r = _run(tmp_path)
    assert r.returncode == 1
