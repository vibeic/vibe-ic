#!/usr/bin/env python3
"""Tests for l1_pin_table_aliases_typed_check.py (Wave 38 / B2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l1_pin_table_aliases_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l1):
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(json.dumps(l1))
    # Wave 43 (v0.119.75): supply minimal L2 + L3 so detect_ic_class
    # resolves to digital_cmd_driven (not bare_fpga). Without this
    # the new ic_class_profile guard would SKIP the gate.
    (proj / "phase1" / "generated_docs" / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "TEST", "protocol_type": "spi",
    }))
    (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({"opcodes": [{"hex": "0x10", "name": "READ"}]})
    )
    return proj


def test_skip_when_no_l1(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_pin_table(tmp_path):
    proj = _make(tmp_path, {"description": "no pins here"})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_mode_missing(tmp_path):
    proj = _make(tmp_path, {"pin_table": [
        {"name": "VDD", "aliases": ["vdd_io"]},
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "mode" in r.stdout


def test_fail_when_alias_missing(tmp_path):
    proj = _make(tmp_path, {"pin_table": [
        {"name": "VDD", "mode": "power"},
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "aliases" in r.stdout


def test_pass_with_full_typed(tmp_path):
    proj = _make(tmp_path, {"pin_table": [
        {"name": "ID_BUS", "mode": "inout",
         "aliases": ["ACC_ID", "GPIO_0[0]", "id_bus"]},
        {"name": "VDD", "mode": "power",
         "aliases": ["VDDIO"]},
    ]})
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_with_rtl_name_alias_form(tmp_path):
    proj = _make(tmp_path, {"pinout": [
        {"name": "ACC_ID", "direction": "inout",
         "rtl_name": "id_bus", "board_name": "GPIO_0[0]"},
    ]})
    r = _run(proj)
    assert r.returncode == 0


# Wave 43 (v0.119.75) — ic_class_profile SKIP case.
def test_skip_on_bare_fpga(tmp_path):
    """Bare-FPGA scaffolds use a fixed eval-board pinout."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    # facts.yaml present + no L1/L2/L3 -> bare_fpga class.
    (proj / "facts.yaml").write_text("name: my_fpga_eval\n")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=bare_fpga" in r.stdout
