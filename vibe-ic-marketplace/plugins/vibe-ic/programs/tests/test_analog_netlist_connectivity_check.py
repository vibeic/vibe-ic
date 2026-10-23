#!/usr/bin/env python3
"""Tests for analog_netlist_connectivity_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_connectivity_check.py"

# Every internal net (gate, tail) touched by >=2 pins; all ports used.
GOOD = """\
* current mirror — well connected
.subckt mirror vin vout vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMP2 gate gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 vout vin vss vss nfet_03v3 W=10u L=2u
.ends
"""

# 'orphan' net touched by exactly one device pin (drain of XMN2), internal.
FLOATING = """\
* floating internal node 'orphan'
.subckt bad vin vout vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMP2 gate gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 orphan vin vss vss nfet_03v3 W=10u L=2u
.ends
"""

# declared port 'enable' never used by any device.
UNUSED_PORT = """\
* unused declared port 'enable'
.subckt bad2 vin vout enable vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 vout vin vss vss nfet_03v3 W=10u L=2u
.ends
"""

NO_SUBCKT = """\
* just a stimulus file, no subckt
Vdd vdd 0 DC 3.3
Vin in 0 DC 1.65
.end
"""


def _run(tmp_path: Path, block=None):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         *(["--block", block] if block is not None else []),
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)


def _write(tmp_path: Path, name: str, content: str):
    d = tmp_path / "analog" / "blk"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


def test_pass_well_connected(tmp_path):
    _write(tmp_path, "blk.sp", GOOD)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["files_with_subckt"] == 1


def test_fail_floating_node(tmp_path):
    _write(tmp_path, "blk.sp", FLOATING)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is False
    floats = [f for f in rep["findings"] if f["rule"] == "FLOATING_NODE"]
    assert floats and any(f["net"] == "orphan" for f in floats)


def test_fail_unused_port(tmp_path):
    _write(tmp_path, "blk.sp", UNUSED_PORT)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "UNUSED_PORT" in rules
    assert any(f.get("net") == "enable" for f in rep["findings"])


def test_edge_no_subckt_not_vacuous(tmp_path):
    _write(tmp_path, "stim.sp", NO_SUBCKT)
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["files_with_subckt"] == 0
    rules = {f["rule"] for f in rep["findings"]}
    assert "NO_SUBCKT" in rules


def test_edge_missing_dir_exit2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2


@pytest.mark.parametrize("root", ["phase3/analog", "phase2/analog", "analog"])
@pytest.mark.parametrize("selected,rc,checked", [(None, 1, 2), ("clean", 0, 1),
                                              ("broken", 1, 1), ("absent", 2, 0)])
def test_explicit_block_scope_preserves_default_and_selected_defect(tmp_path, root, selected, rc, checked):
    for name, body in (("clean", GOOD), ("broken", FLOATING)):
        folder = tmp_path / root / name / "derived"
        folder.mkdir(parents=True)
        (folder / "deck.sp").write_text(body)
    result = _run(tmp_path, selected)
    assert result.returncode == rc, result.stdout + result.stderr
    report = json.loads((tmp_path / "r.json").read_text())
    assert report["summary"].get("files_checked", 0) == checked
