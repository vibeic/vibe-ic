#!/usr/bin/env python3
"""Tests for l4_regmap_enumerated_values_typed_check.py (Wave 38 / B3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l4_regmap_enumerated_values_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l4):
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L4_REGMAP.json").write_text(json.dumps(l4))
    return proj


def test_skip_when_no_l4(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_eligible_field(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "EN", "bits": "[0:0]"},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_multibit_enum_field_lacks_values(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "OCP_DLY", "bits": "[1:0]"},
            {"name": "RES_MODE", "bits": "[3:2]"},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "OCP_DLY" in r.stdout or "RES_MODE" in r.stdout


def test_pass_when_enum_present(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "OCP_DLY", "bits": "[1:0]",
             "enumerated_values": [
                 {"code": "00", "meaning": "idle"},
                 {"code": "01", "meaning": "wait"},
                 {"code": "10", "meaning": "stable"},
                 {"code": "11", "meaning": "release"},
             ]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_when_alias_key_used(tmp_path):
    proj = _make(tmp_path, {"registers": [
        {"name": "CTRL", "fields": [
            {"name": "MODE", "width": 2,
             "encoding": [
                 {"code": 0, "meaning": "off"},
                 {"code": 1, "meaning": "low"},
                 {"code": 2, "meaning": "high"},
             ]},
        ]}
    ]})
    r = _run(proj)
    assert r.returncode == 0


# Wave 43 (v0.119.75) — ic_class_profile SKIP cases.
def test_skip_on_pure_analog(tmp_path):
    """Pure-analog parts have no command regmap."""
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


def test_skip_on_bare_fpga(tmp_path):
    """Bare-FPGA scaffolds have no fab-side regmap."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "facts.yaml").write_text("name: my_fpga_eval\n")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=bare_fpga" in r.stdout
