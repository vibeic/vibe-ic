#!/usr/bin/env python3
"""Tests for analog_tb_supply_pdk_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_tb_supply_pdk_check.py"

# GF180 3.3V supply + 03v3 devices — consistent.
GOOD_GF180 = """\
* GF180 tb — consistent
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
X1 vin vout vdd vss amp
Vdd vdd 0 DC 3.3
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
.end
"""

# SKY130 1.8V supply + 01v8 devices — consistent.
GOOD_SKY130 = """\
* SKY130 tb — consistent
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
X1 vin vout vdd vss amp
Vdd vdd 0 DC 1.8
XMP1 vout gate vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u
.end
"""

# SKY130 markers but 3.3V supply — mismatch.
BAD_SUPPLY = """\
* SKY130 1v8 device but 3.3V supply — over-stress
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
Vdd vdd 0 DC 3.3
XMP1 vout gate vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u
.end
"""

# GF180 markers but a sky130 01v8 device flavor — illegal flavor for PDK.
BAD_FLAVOR = """\
* GF180 PDK but 01v8 device flavor
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
Vdd vdd 0 DC 3.3
XMP1 vout gate vdd vdd pfet_01v8 W=2u L=0.15u
.end
"""

UNKNOWN_PDK = """\
* no PDK markers
Vdd vdd 0 DC 1.2
XMP1 vout gate vdd vdd genericpmos W=2u L=0.1u
.end
"""


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)


def _write(tmp_path: Path, name: str, content: str):
    d = tmp_path / "analog" / "amp"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


def test_pass_gf180_consistent(tmp_path):
    _write(tmp_path, "tb_amp.sp", GOOD_GF180)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["files_judged"] == 1


def test_pass_sky130_consistent(tmp_path):
    _write(tmp_path, "tb_amp.sp", GOOD_SKY130)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True


def test_fail_supply_device_mismatch(tmp_path):
    _write(tmp_path, "tb_amp.sp", BAD_SUPPLY)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    # 3.3V vs sky130 (only 1.8 legal) trips SUPPLY_PDK_MISMATCH and/or
    # SUPPLY_DEVICE_MISMATCH
    assert rules & {"SUPPLY_PDK_MISMATCH", "SUPPLY_DEVICE_MISMATCH"}
    assert rep["passed"] is False


def test_fail_illegal_device_flavor(tmp_path):
    _write(tmp_path, "tb_amp.sp", BAD_FLAVOR)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "DEVICE_FLAVOR_PDK_MISMATCH" in rules


def test_edge_unknown_pdk_not_vacuous(tmp_path):
    _write(tmp_path, "tb_amp.sp", UNKNOWN_PDK)
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["files_unknown_pdk"] == 1
    assert rep["summary"]["files_judged"] == 0


def test_edge_missing_dir_exit2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2
