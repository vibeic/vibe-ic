#!/usr/bin/env python3
"""Tests for analog_hardmacro_check.py — hardmacro deliverables gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "analog_hardmacro_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_analog_blocks(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


def test_pass_complete_hardmacro(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "spec.json").write_text("{}")
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "ldo"
    hm.mkdir(parents=True)
    (hm / "ldo.gds").write_bytes(b"\x00\x01\x02\x03")
    (hm / "ldo.lef").write_text("MACRO ldo\n  PIN vout\n  END vout\nEND ldo\n")
    (hm / "ldo.lib").write_text('library (ldo_lib) {\n  cell (ldo) {}\n}\n')
    (hm / "ldo.v").write_text("module ldo(input vin, output vout);\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["complete"] == 1


def test_fail_missing_files(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "ldo" / "spec.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("HARDMACRO_INCOMPLETE" in f["rule"] for f in errors)


def test_fail_lef_no_macro(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["osc"]))
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "osc"
    hm.mkdir(parents=True)
    (hm / "osc.gds").write_bytes(b"\x00\x01")
    (hm / "osc.lef").write_text("VERSION 5.7;\nEND LIBRARY\n")
    (hm / "osc.lib").write_text('library (osc_lib) {\n  cell (osc) {}\n}\n')
    (hm / "osc.v").write_text("module osc(input en, output clk);\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("HARDMACRO_LEF_NO_MACRO" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
