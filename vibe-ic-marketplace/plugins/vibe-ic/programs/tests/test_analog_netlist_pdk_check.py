#!/usr/bin/env python3
"""Tests for analog_netlist_pdk_check.py — SPICE netlist PDK compliance gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_pdk_check.py"

GF180_GOOD_NETLIST = """\
* LDO Regulator — GF180
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

.subckt ldo_regulator vin vout vss
XMP1 vout gate vin vin pfet_03v3 W=20u L=4u
XMN1 gate vref vss vss nfet_03v3 W=20u L=2u
XMN2 n_out vfb vss vss nfet_03v3 W=20u L=2u
.ends
"""

GF180_BAD_BODY_NETLIST = """\
* LDO with wrong PMOS body
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

.subckt ldo_bad vin vout vss
XMP1 vout gate vin 0 pfet_03v3 W=20u L=4u
XMN1 gate vref vss vss nfet_03v3 W=20u L=2u
.ends
"""

NO_INCLUDE_NETLIST = """\
* Missing model include
.subckt osc_bad vdd vss out
XMP1 out in vdd vdd pfet_03v3 W=1u L=1u
XMN1 out in vss vss nfet_03v3 W=0.5u L=1u
.ends
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# -- Test: PASS with correct GF180 netlist --

def test_pass_correct_pdk(tmp_path):
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True)
    (d / "ldo.sp").write_text(GF180_GOOD_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["files_pass"] == 1


# -- Test: FAIL with wrong PMOS body connection --

def test_fail_wrong_body(tmp_path):
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True)
    (d / "ldo.sp").write_text(GF180_BAD_BODY_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("PMOS_BODY_TO_VSS" in f["rule"] for f in errors)


# -- Test: FAIL with no model include --

def test_fail_no_model_include(tmp_path):
    d = tmp_path / "phase3" / "analog" / "osc"
    d.mkdir(parents=True)
    (d / "osc.sp").write_text(NO_INCLUDE_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("NO_MODEL_INCLUDE" in f["rule"] for f in errors)


# -- Test: self-skip when no .sp files --

def test_skip_no_sp(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True


# -- Test: exit 2 on non-existent directory --

def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
