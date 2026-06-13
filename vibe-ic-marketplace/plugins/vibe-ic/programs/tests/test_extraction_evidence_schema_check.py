#!/usr/bin/env python3
"""Tests for extraction_evidence_schema_check.py (LL-40, BACKLOG-v13 Wave 7).

LL-40 validates the SHAPE of the `extraction_evidence` field that
Wave 2 / Wave 5 / Wave 7 SKILL.md updates require every Phase 2a-emitted
L*.json to carry. Companion to LL-38 (substring matching) and LL-39
(report presence + threshold).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "extraction_evidence_schema_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put_l(project: Path, name: str, data: dict):
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data, ensure_ascii=False))


def _put_waiver(project: Path, key: str, reason: str):
    (project / "waivers.json").write_text(
        json.dumps({key: reason}, ensure_ascii=False))


def _ok_evidence():
    return {
        "spec.pdf": [
            {"literal": "RSP_71[91]", "label": "RSP_71 latency"},
            "Section 4.2",
        ],
        "regmap.xlsx": [
            {"literal": "0x60"},
        ],
    }


# ----------------------------------------------------------------
# 1. Silent-skip when generated_docs/ is absent.
# ----------------------------------------------------------------
def test_skip_when_generated_docs_absent(tmp_path):
    # Wave 30 (v0.119.62) — bare skeleton (no input/docs/) still
    # silent-skips. Only when input/docs/ has vendor docs does the
    # gate fail closed.
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "bare-skeleton project" in r.stdout


# ----------------------------------------------------------------
# 2. All required L docs present + valid evidence -> PASS.
# ----------------------------------------------------------------
def test_pass_when_all_required_have_valid_evidence(tmp_path):
    for n in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
              "L4_REGMAP.json", "L6_CONTROL_LOGIC.json",
              "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
              "L11_CALIBRATION.json"):
        _put_l(tmp_path, n, {"extraction_evidence": _ok_evidence()})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ----------------------------------------------------------------
# 3. Required L doc missing the field -> FAIL.
# ----------------------------------------------------------------
def test_fail_when_required_l_missing_field(tmp_path):
    _put_l(tmp_path, "L1_DATASHEET.json",
           {"extraction_evidence": _ok_evidence()})
    # L2 missing the field entirely.
    _put_l(tmp_path, "L2_FRS.json", {"some": "other_data"})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "L2_FRS.json" in r.stdout
    assert "missing top-level `extraction_evidence`" in r.stdout


# ----------------------------------------------------------------
# 4. Malformed evidence (list-of-int) -> FAIL.
# ----------------------------------------------------------------
def test_fail_when_evidence_list_malformed(tmp_path):
    _put_l(tmp_path, "L1_DATASHEET.json", {
        "extraction_evidence": {
            "spec.pdf": [1, 2, 3],  # ints not allowed
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "malformed" in r.stdout
    assert "L1_DATASHEET.json" in r.stdout


# ----------------------------------------------------------------
# 5. Evidence as a string (not a dict) -> FAIL.
# ----------------------------------------------------------------
def test_fail_when_evidence_not_a_dict(tmp_path):
    _put_l(tmp_path, "L1_DATASHEET.json", {
        "extraction_evidence": "all_evidence_in_separate_file.yaml"
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "must be a dict" in r.stdout
    assert "L1_DATASHEET.json" in r.stdout


# ----------------------------------------------------------------
# 6. Dict entry without `literal` -> FAIL.
# ----------------------------------------------------------------
def test_fail_when_dict_entry_missing_literal(tmp_path):
    _put_l(tmp_path, "L1_DATASHEET.json", {
        "extraction_evidence": {
            "spec.pdf": [{"label": "no literal here"}],
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "missing required `literal`" in r.stdout


# ----------------------------------------------------------------
# 7. Wave 23 (v0.119.55) — waiver no longer suppresses missing
#    extraction_evidence; the legacy waiver path is gone.
# ----------------------------------------------------------------
def test_waiver_no_longer_accepts_failures(tmp_path):
    _put_l(tmp_path, "L1_DATASHEET.json", {"some": "thing"})
    _put_waiver(
        tmp_path, "extraction_evidence_schema_alternative",
        "Project uses external evidence_map.yaml format tracked via "
        "TICKET-9876; LL-40 shape check intentionally bypassed.",
    )
    r = _run(tmp_path)
    # Wave 23 — waiver path removed; FAIL.
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "L1_DATASHEET.json" in r.stdout


# ----------------------------------------------------------------
# 8. Wave 23 (v0.119.55) — every L1-L23 doc that exists in
#    generated_docs/ must carry extraction_evidence; the previous
#    "soft prefix" tier is gone (L7/L10/L12/L13 are now hard-required).
# ----------------------------------------------------------------
def test_l7_missing_field_now_fails(tmp_path):
    # All previously-hard L docs present + valid.
    for n in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
              "L4_REGMAP.json", "L6_CONTROL_LOGIC.json",
              "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
              "L11_CALIBRATION.json"):
        _put_l(tmp_path, n, {"extraction_evidence": _ok_evidence()})
    # L7 missing field — under Wave 23 this is HARD FAIL (no soft tier).
    _put_l(tmp_path, "L7_TEST_DEBUG.json", {"some": "thing"})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "L7_TEST_DEBUG.json" in r.stdout


# ----------------------------------------------------------------
# 9. Wired into _STRUCTURAL_RTL_GATES.
# ----------------------------------------------------------------
def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "extraction_evidence_schema_check" in txt, (
        "LL-40 gate not wired into flow_compliance_check.py "
        "_STRUCTURAL_RTL_GATES tuple")
