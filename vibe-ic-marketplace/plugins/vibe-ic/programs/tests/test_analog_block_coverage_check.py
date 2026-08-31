#!/usr/bin/env python3
"""Tests for analog_block_coverage_check.py — analog design coverage gate."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _hostpaths import require_repo

PROG = Path(__file__).resolve().parent.parent / "analog_block_coverage_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# -- Test: self-skip when no analog modules detected --

def test_pass_no_analog(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "counter.v").write_text("module counter(input clk, output [7:0] q);\nendmodule\n")
    r = _run(tmp_path)
    # #521 — a design with no analog block is VACUOUS (rc 2), not a PASS over
    # analog content that does not exist. The report assertions are unchanged.
    assert r.returncode == 2
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


# -- Test: FAIL when analog module in RTL but no design directory --

def test_fail_missing_spec(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "ldo_regulator.v").write_text(
        "module ldo_regulator(input vin, output vout);\nendmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("ANALOG_BLOCK_UNCOVERED" in f["rule"] for f in errors)


# -- Test: PASS when all deliverables present --

def test_pass_all_covered(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "ldo_regulator.v").write_text(
        "module ldo_regulator(input vin, output vout);\nendmodule\n"
    )
    ad = tmp_path / "phase3" / "analog" / "ldo_regulator"
    ad.mkdir(parents=True)
    (ad / "spec.json").write_text(json.dumps({"block_name": "ldo_regulator", "specs": {}}))
    (ad / "ldo.sp").write_text(".title LDO\n.end\n")
    (ad / "corner_results.json").write_text(json.dumps({
        "total_corners": 15, "results_found": 15, "spec_results": []
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["covered"] == 1


def test_explicit_block_list_is_authoritative_over_rtl_name_hints(tmp_path):
    """A product-like digital module name must not invent an analog block."""
    source_list = require_repo(
        "docs", "research", "fleet_run_folder_triage_evidence", "121",
        "_c3_adc_scratch", "a3runnable", "phase3", "analog",
        "analog_block_list.json",
    )
    block_list = json.loads(source_list.read_text())
    declared_block = block_list["blocks"][0]["name"]

    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "product_top.v").write_text(
        "module product_adc_top(input clk);\nendmodule\n"
    )

    analog = tmp_path / "phase3" / "analog"
    analog.mkdir(parents=True)
    shutil.copyfile(source_list, analog / "analog_block_list.json")
    block_dir = analog / declared_block
    block_dir.mkdir()
    (block_dir / "spec.json").write_text("{}")
    (block_dir / f"{declared_block}.sp").write_text(".title block\n.end\n")
    (block_dir / "corner_results.json").write_text("{}")

    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["from_block_list"] == [declared_block]
    assert rpt["summary"]["from_rtl"] == ["product_adc_top"]
    assert rpt["summary"]["rtl_name_hints_not_in_block_list"] == [
        "product_adc_top"
    ]
    assert rpt["summary"]["total_blocks"] == 1
    assert rpt["summary"]["uncovered"] == []
    warnings = [f for f in rpt["findings"] if f["severity"] == "WARNING"]
    assert [f["rule"] for f in warnings] == [
        "RTL_ANALOG_NAME_NOT_IN_BLOCK_LIST"
    ]
    assert "product_adc_top" in warnings[0]["message"]


def test_explicit_block_list_missing_deliverables_remains_blocking(tmp_path):
    source_list = require_repo(
        "docs", "research", "fleet_run_folder_triage_evidence", "121",
        "_c3_adc_scratch", "a3runnable", "phase3", "analog",
        "analog_block_list.json",
    )
    block_list = json.loads(source_list.read_text())
    declared_block = block_list["blocks"][0]["name"]
    analog = tmp_path / "phase3" / "analog"
    analog.mkdir(parents=True)
    shutil.copyfile(source_list, analog / "analog_block_list.json")

    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    assert rpt["summary"]["roster_source"] == "analog_block_list"
    assert rpt["summary"]["uncovered"] == [declared_block]
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert [f["rule"] for f in errors] == ["ANALOG_BLOCK_UNCOVERED"]
    assert declared_block in errors[0]["message"]


def test_invalid_explicit_block_list_fails_instead_of_suppressing_rtl(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "product_top.v").write_text(
        "module product_adc_top(input clk);\nendmodule\n"
    )
    analog = tmp_path / "phase3" / "analog"
    analog.mkdir(parents=True)
    (analog / "analog_block_list.json").write_text("{not-json\n")

    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    assert rpt["summary"]["roster_source"] == "invalid_analog_block_list"
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert [f["rule"] for f in errors] == ["ANALOG_BLOCK_LIST_INVALID"]


# -- Test: self-skip when no rtl/ dir --

def test_skip_no_rtl(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS, not a plain PASS
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
