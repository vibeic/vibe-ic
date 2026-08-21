#!/usr/bin/env python3
"""Tests for analog_netlist_path_lint.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_path_lint.py"

GOOD = """\
* whitelisted PDK paths + a relative include
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.include ./amp_models.inc
.subckt amp vin vout vss
.ends
"""

BAD = """\
* hardcoded absolute non-PDK path
.include /home/testuser/scratch/my_models.lib
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.subckt amp vin vout vss
.ends
"""

NO_INCLUDE = """\
* no include directives at all
.subckt amp vin vout vss
XMP1 vout gate vin vin pfet_03v3 W=20u L=4u
.ends
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


def test_pass_whitelisted_paths(tmp_path):
    _write(tmp_path, "amp.sp", GOOD)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["non_whitelisted_absolute_paths"] == 0
    assert rep["summary"]["files_with_includes"] == 1


def test_fail_hardcoded_home_path(tmp_path):
    _write(tmp_path, "amp.sp", BAD)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is False
    rules = {f["rule"] for f in rep["findings"]}
    assert "NON_WHITELISTED_ABSOLUTE_PATH" in rules


def test_edge_no_includes_no_false_pass_claim(tmp_path):
    _write(tmp_path, "amp.sp", NO_INCLUDE)
    r = _run(tmp_path)
    # no absolute paths => PASS, but files_with_includes must be 0 (visible)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["files_with_includes"] == 0
    assert rep["summary"]["files_checked"] == 1


def test_edge_no_sp_skips(tmp_path):
    (tmp_path / "analog").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"].get("skipped") is True


def test_edge_missing_dir_exit2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2
