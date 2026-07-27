#!/usr/bin/env python3
"""Tests for analog_netlist_include_order_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_include_order_check.py"

GOOD = """\
* GF180 deck — correct ordering
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.subckt amp vin vout vss
XMP1 vout gate vin vin pfet_03v3 W=20u L=4u
.ends
"""

BAD = """\
* GF180 deck — .lib BEFORE design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.subckt amp vin vout vss
XMP1 vout gate vin vin pfet_03v3 W=20u L=4u
.ends
"""

SKY130 = """\
* SKY130 deck — single lib, ordering inapplicable
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.subckt amp vin vout vss
XMP1 vout gate vin vin sky130_fd_pr__pfet_01v8 W=2u L=0.15u
.ends
"""


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    d = tmp_path / "analog" / "amp"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(content)
    return p


def test_pass_correct_order(tmp_path):
    _write(tmp_path, "amp.sp", GOOD)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["gf180_two_file_decks"] == 1


def test_fail_lib_before_include(tmp_path):
    _write(tmp_path, "amp.sp", BAD)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is False
    rules = {f["rule"] for f in rep["findings"]}
    assert "LIB_BEFORE_DESIGN_INCLUDE" in rules


def test_sky130_single_lib_inapplicable_passes(tmp_path):
    _write(tmp_path, "amp.sp", SKY130)
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    rules = {f["rule"] for f in rep["findings"]}
    assert "ORDER_INAPPLICABLE" in rules


def test_edge_no_sp_files_skips(tmp_path):
    """#511 — an analog dir with no deck in it put ZERO files through the
    ordering rule, so this is the DISCLOSED skip tier (rc 2 = NOT CHECKED),
    not a PASS that reads the same as a real clean run."""
    (tmp_path / "analog").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["summary"].get("skipped") is True
    assert rep["summary"]["denominator"]["examined"] == 0
    assert rep["summary"]["denominator"]["not_applicable_reason"].strip()


def test_edge_missing_project_dir_exit2(tmp_path):
    missing = tmp_path / "nope"
    r = subprocess.run(
        [sys.executable, str(PROG), str(missing)],
        capture_output=True, text=True)
    assert r.returncode == 2
