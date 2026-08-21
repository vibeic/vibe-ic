#!/usr/bin/env python3
"""Tests for phase1_all_l_docs_present_check.py (Wave 23, v0.119.55)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "phase1_all_l_docs_present_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put_l(project: Path, name: str, data: dict | None = None):
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    if data is None:
        data = {"placeholder_field": "value"}
    (docs / name).write_text(json.dumps(data, ensure_ascii=False))


_FULL_SUITE = (
    "L1_DATASHEET.json",
    "L2_FRS.json",
    "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json",
    "L5_ADI_SPEC.json",
    "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json",
    "L8_TIMING_WAVEFORM.json",
    "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json",
    "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json",
    "L13_LAB_CALIBRATION.json",
)


# 1. generated_docs/ absent -> FAIL (Wave 30, v0.119.62 fail-closed).
def test_fail_when_generated_docs_absent(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "Phase 1 (doc-extraction) was not attempted" in r.stdout


# 2. generated_docs/ exists but empty -> FAIL (Wave 30 fail-closed).
def test_fail_when_generated_docs_empty(tmp_path):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "Phase 1 (doc-extraction) was not attempted" in r.stdout


# 3. All 13 L docs present + non-empty -> PASS.
def test_pass_when_all_13_present(tmp_path):
    for name in _FULL_SUITE:
        _put_l(tmp_path, name)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "13/13" in r.stdout


# 4. The exact 28th-attempt subset (only L2/L8/L9/L11) -> FAIL listing 9 missing.
def test_fail_when_only_4_present_28th_attempt_pattern(tmp_path):
    for name in (
        "L2_FRS.json", "L8_TIMING_WAVEFORM.json",
        "L9_INTEGRATION_SPEC.json", "L11_OTP_CONTENT.json",
    ):
        _put_l(tmp_path, name)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    # All 9 missing prefixes mentioned.
    for pref in ("L1_", "L3_", "L4_", "L5_", "L6_", "L7_",
                 "L10_", "L12_", "L13_"):
        assert pref in r.stdout, (
            f"missing prefix {pref} not surfaced in FAIL output")


# 5. One L doc missing -> FAIL listing it.
def test_fail_when_single_l_missing(tmp_path):
    for name in _FULL_SUITE:
        if name.startswith("L7_"):
            continue
        _put_l(tmp_path, name)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "L7_" in r.stdout


# 6. L doc present but empty dict -> FAIL.
def test_fail_when_l_doc_empty(tmp_path):
    for name in _FULL_SUITE:
        if name.startswith("L4_"):
            _put_l(tmp_path, name, data={})
        else:
            _put_l(tmp_path, name)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "L4_REGMAP.json" in r.stdout
    assert "empty" in r.stdout.lower()


# 7. L doc present but unparseable JSON -> FAIL.
def test_fail_when_l_doc_unparseable(tmp_path):
    for name in _FULL_SUITE:
        if name.startswith("L5_"):
            (tmp_path / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
            (tmp_path / "phase1" / "generated_docs" / name).write_text(
                "{not valid json")
        else:
            _put_l(tmp_path, name)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "L5_" in r.stdout
    assert "unparseable" in r.stdout.lower()


# 8. Alternative L doc filenames (chip-AGNOSTIC suffix) -> PASS.
def test_pass_with_alternative_suffixes(tmp_path):
    # Use a different but valid suffix per L for chip-agnostic check.
    for name in (
        "L1_OVERVIEW.json", "L2_FUNC_REQ.json", "L3_PROTOCOL.json",
        "L4_REG.json", "L5_ANALOG.json", "L6_CONTROL.json",
        "L7_TEST.json", "L8_TIMING.json", "L9_INTEGRATION.json",
        "L10_TC.json", "L11_OTP.json", "L12_BS.json",
        "L13_CALIB.json",
    ):
        _put_l(tmp_path, name)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# 9. Wired into _STRUCTURAL_RTL_GATES.
def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "phase1_all_l_docs_present_check" in txt, (
        "Wave 23 gate not wired into flow_compliance_check.py "
        "_STRUCTURAL_RTL_GATES tuple")


# 10. Invalid project dir -> exit 2.
def test_invalid_project_dir(tmp_path):
    bogus = tmp_path / "does_not_exist"
    r = _run(bogus)
    assert r.returncode == 2
    assert "not found" in r.stdout
