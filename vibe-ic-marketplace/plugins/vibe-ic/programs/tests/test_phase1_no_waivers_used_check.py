#!/usr/bin/env python3
"""Tests for phase1_no_waivers_used_check.py (Wave 23, v0.119.55).

The gate forbids any waiver whose name matches a Phase 2a-related
pattern. Non-Phase-2a waivers remain valid.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "phase1_no_waivers_used_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put_waivers(project: Path, data: dict):
    project.mkdir(parents=True, exist_ok=True)
    (project / "waivers.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2))


# ----------------------------------------------------------------
# 1. No waivers.json -> PASS.
# ----------------------------------------------------------------
def test_no_waivers_file_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ----------------------------------------------------------------
# 2. Empty waivers.json -> PASS.
# ----------------------------------------------------------------
def test_no_phase1_waivers_pass(tmp_path):
    _put_waivers(tmp_path, {})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ----------------------------------------------------------------
# 3. Each of the six banned waiver names individually -> FAIL.
# ----------------------------------------------------------------
def test_extraction_coverage_acceptable_below_95_fail(tmp_path):
    _put_waivers(tmp_path, {
        "extraction_coverage_acceptable_below_95":
            "Some long-enough rationale string for the waiver value.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "extraction_coverage_acceptable_below_95" in r.stdout


def test_phase1_coverage_below_threshold_intentional_fail(tmp_path):
    _put_waivers(tmp_path, {
        "phase1_coverage_below_threshold_intentional":
            "Some long-enough rationale string for the waiver value.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "phase1_coverage_below_threshold_intentional" in r.stdout


def test_extraction_evidence_schema_alternative_fail(tmp_path):
    _put_waivers(tmp_path, {
        "extraction_evidence_schema_alternative":
            "Some long-enough rationale string for the waiver value.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "extraction_evidence_schema_alternative" in r.stdout


def test_phase1_other_acceptable_fail(tmp_path):
    _put_waivers(tmp_path, {
        "phase1_extractor_gaps_acceptable":
            "Some long-enough rationale string for the waiver value.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "phase1_extractor_gaps_acceptable" in r.stdout


def test_phase1_other_intentional_fail(tmp_path):
    _put_waivers(tmp_path, {
        "phase1_partial_extraction_intentional":
            "Some long-enough rationale string for the waiver value.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "phase1_partial_extraction_intentional" in r.stdout


def test_extraction_other_alternative_fail(tmp_path):
    _put_waivers(tmp_path, {
        "extraction_format_alternative":
            "Some long-enough rationale string for the waiver value.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "extraction_format_alternative" in r.stdout


# ----------------------------------------------------------------
# 4. The exact 28th-attempt waiver trio together -> FAIL listing all 3.
# ----------------------------------------------------------------
def test_extraction_waiver_present_fail(tmp_path):
    _put_waivers(tmp_path, {
        "extraction_coverage_acceptable_below_95":
            "Phase 2a fresh-agent benchmark mode rationale aaaaaaaa.",
        "phase1_coverage_below_threshold_intentional":
            "Phase 2a fresh-agent benchmark mode rationale bbbbbbbb.",
        "extraction_evidence_schema_alternative":
            "Phase 2a fresh-agent benchmark mode rationale cccccccc.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "extraction_coverage_acceptable_below_95" in r.stdout
    assert "phase1_coverage_below_threshold_intentional" in r.stdout
    assert "extraction_evidence_schema_alternative" in r.stdout


# ----------------------------------------------------------------
# 5. Non-Phase-2a waivers are not affected -> PASS.
# ----------------------------------------------------------------
def test_other_waivers_pass(tmp_path):
    _put_waivers(tmp_path, {
        "nba_shift_register_intentional":
            "RTL pattern is intentional for shift-register lookahead.",
        "open_drain_active_drive_intentional":
            "Bus is open-drain by spec, drive HIGH would be incorrect.",
        "vendor_fpga_table_alternative":
            "Vendor table chosen vs ORG block per silicon-PASS oracle.",
        "review_required": True,
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ----------------------------------------------------------------
# 6. Mix of Phase-2a + non-Phase-2a -> FAIL only on Phase 2a names.
# ----------------------------------------------------------------
def test_mix_phase1_and_other(tmp_path):
    _put_waivers(tmp_path, {
        "nba_shift_register_intentional":
            "Allowed RTL pattern rationale string.",
        "extraction_coverage_acceptable_below_95":
            "Forbidden Phase 2a coverage waiver rationale.",
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "extraction_coverage_acceptable_below_95" in r.stdout
    # Non-Phase-2a waiver should not be flagged
    assert "nba_shift_register_intentional matches forbidden" not in r.stdout


# ----------------------------------------------------------------
# 7. Wired into _STRUCTURAL_RTL_GATES.
# ----------------------------------------------------------------
def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "phase1_no_waivers_used_check" in txt, (
        "Wave 23 gate not wired into flow_compliance_check.py "
        "_STRUCTURAL_RTL_GATES tuple")


# ----------------------------------------------------------------
# 8. Invalid project dir -> exit 2.
# ----------------------------------------------------------------
def test_invalid_project_dir(tmp_path):
    bogus = tmp_path / "does_not_exist"
    r = _run(bogus)
    assert r.returncode == 2
    assert "not found" in r.stdout
