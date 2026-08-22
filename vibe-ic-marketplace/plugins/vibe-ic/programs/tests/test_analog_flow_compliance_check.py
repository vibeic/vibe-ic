#!/usr/bin/env python3
"""Tests for analog_flow_compliance_check.py — A1-A9 analog flow compliance gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_flow_compliance_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_block_list(tmp_path):
    """#511 — a project with no block list holds ZERO A-step obligations, so
    this is the DISCLOSED skip tier (rc 2 = NOT CHECKED), not a PASS. `passed`
    keeps its literal meaning: nothing was applied, so nothing was signed off.
    """
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["verdict"] == "VACUOUS_PASS"
    assert rpt["passed"] is False
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"
    assert rpt["summary"]["denominator"]["examined"] == 0
    assert rpt["summary"]["denominator"]["not_applicable_reason"].strip()
    # It is NOT a FAIL: no ERROR finding, and the rc is the skip tier.
    assert not [f for f in rpt["findings"] if f["severity"] == "ERROR"]


def test_pass_all_steps(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["ldo"]))
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
    (ad / "topology.md").write_text("# LDO Topology\n")
    (ad / "ldo.sp").write_text(".title LDO\n.end\n")
    # WAS `{}`. This test asserts every A1-A9 cell reads PASS, and with an
    # empty object in it the A4 cell was reading PASS off a corner artefact
    # that declares no corners, no provenance and no statement of what circuit
    # it measured — a presence probe wearing a verdict's clothes. The A4 cell
    # is delegated to the A4 gate's own certification predicates, so the
    # fixture supplies what a signed-off A4 actually looks like.
    (ad / "corner_results.json").write_text(json.dumps({
        "netlist_provenance": "a3_netlist",
        "design_content": "structure_and_geometry",
        "corners": [{"name": "tt_27c", "simulator_run": True, "vout_v": 1.8}],
        "spec_results": [{"name": "vout", "status": "PASS", "target": None}],
    }))
    (ad / "layout.mag").write_text("magic\n")
    # A6 per-block PV markers (DRC clean + LVS match).
    (ad / "drc_clean.flag").write_text("violations: 0\n")
    (ad / "lvs_match.flag").write_text("lvs: match\n")
    # A7 post-layout resim.
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
    assert rpt["summary"]["total_missing"] == 9


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
            {"block": "osc", "step": "A9"},
        ]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["total_waived"] == 9


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
