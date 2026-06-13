#!/usr/bin/env python3
"""Tests for l1_electrical_specs_typed_depth_check.py (Wave 38 / B1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l1_electrical_specs_typed_depth_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l1=None, doc_text=None):
    proj = tmp_path / "p"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if doc_text is not None:
        (proj / "phase1" / "input_doc" / "datasheet.txt").write_text(doc_text)
    if l1 is not None:
        (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
            json.dumps(l1)
        )
    return proj


def test_skip_when_empty(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_doc_mentions_but_no_l1(tmp_path):
    proj = _make(tmp_path, doc_text="VDD = 3.3 V Typ. 3.6 V Max")
    r = _run(proj)
    assert r.returncode == 1
    assert "L1_DATASHEET.json missing" in r.stdout


def test_fail_on_shallow_entries(tmp_path):
    proj = _make(
        tmp_path,
        doc_text="VDD 3.3V Typ Max 3.6V",
        l1={"electrical_specs": [{"name": "VDD", "value": 3.3}]},
    )
    r = _run(proj)
    assert r.returncode == 1
    assert "shallow" in r.stdout or "missing" in r.stdout


def test_pass_with_full_typed_entry(tmp_path):
    proj = _make(
        tmp_path,
        doc_text="VDD 3.3V Typ",
        l1={"electrical_specs": [
            {"name": "VDD", "min": 3.0, "typ": 3.3, "max": 3.6,
             "unit": "V", "evidence": "datasheet.txt:5"}
        ]},
    )
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_with_alias_array(tmp_path):
    proj = _make(
        tmp_path,
        doc_text="VDD 3.3V Typ",
        l1={"electrical_limits": [
            {"name": "VDD", "min_typ_max": {"min": 3.0, "typ": 3.3, "max": 3.6},
             "unit": "V", "evidence_path": "datasheet.txt:5"}
        ]},
    )
    r = _run(proj)
    assert r.returncode == 0


def test_skip_when_no_mention_no_entries(tmp_path):
    proj = _make(tmp_path, doc_text="hello world", l1={"description": "x"})
    r = _run(proj)
    assert r.returncode == 2


# Wave 43 (v0.119.75) — ic_class_profile SKIP cases.
def test_skip_on_pure_analog(tmp_path):
    """Pure-analog parts ship A1-A8 specs, not L1.electrical_specs[]."""
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
