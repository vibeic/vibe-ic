#!/usr/bin/env python3
"""Tests for analog_flow_compliance_check.py — A1-A8 analog flow compliance gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "analog_flow_compliance_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_block_list(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


def test_pass_all_steps(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["ldo"]))
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
    (ad / "topology.md").write_text("# LDO Topology\n")
    (ad / "ldo.sp").write_text(".title LDO\n.end\n")
    (ad / "corner_results.json").write_text("{}")
    (ad / "layout.mag").write_text("magic\n")
    (ad / "pre_vs_post.json").write_text("{}")
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "ldo"
    hm.mkdir(parents=True)
    (hm / "ldo.lef").write_text("MACRO ldo\nEND ldo\n")
    cd = tmp_path / "phase3" / "mixed_signal" / "cosim"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "ldo_cosim_results.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["total_missing"] == 0


def test_fail_missing_steps(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["osc"]))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    assert rpt["summary"]["total_missing"] == 8


def test_waiver_support(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["osc"]))
    (tmp_path / "phase3" / "analog" / "waivers.json").write_text(json.dumps({
        "analog_waivers": [
            {"block": "osc", "step": "A1"},
            {"block": "osc", "step": "A2"},
            {"block": "osc", "step": "A3"},
            {"block": "osc", "step": "A4"},
            {"block": "osc", "step": "A5"},
            {"block": "osc", "step": "A6"},
            {"block": "osc", "step": "A7"},
            {"block": "osc", "step": "A8"},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["total_waived"] == 8


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
