#!/usr/bin/env python3
"""Tests for analog_a8_before_floorplan_check.py — A8↔floorplan ordering gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_a8_before_floorplan_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json")],
        capture_output=True, text=True,
    )


def _report(project: Path) -> dict:
    return json.loads((project / "report.json").read_text())


def _block_list(project: Path, blocks):
    bl = project / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True, exist_ok=True)
    bl.write_text(json.dumps(blocks))


def _floorplan(project: Path, name: str = "floorplan.def"):
    fp = project / "phase3" / "stage3" / "pnr" / name
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")


def _a8_lef(project: Path, block: str):
    lef = project / "phase3" / "analog" / "hardmacro" / block / f"{block}.lef"
    lef.parent.mkdir(parents=True, exist_ok=True)
    lef.write_text(f"MACRO {block}\n  CLASS BLOCK ;\nEND {block}\n")


# ── SKIP edges ───────────────────────────────────────────────────────────

def test_skip_no_block_list(tmp_path):
    """Pure-digital IC: no analog blocks → VACUOUS (rc 2).

    #521: this asserted rc 0, which is what put the skip in the plain PASS
    tier of `flow_compliance_check`. The report assertions below are
    unchanged — the gate's conclusion was always right; only the exit code
    that carried it was wrong."""
    r = _run(tmp_path)
    assert r.returncode == 2
    rpt = _report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


def test_skip_floorplan_not_run(tmp_path):
    """Block list present but floorplan has not run → constraint not yet
    triggered → VACUOUS, NOT a vacuous PASS of the ordering rule (#521)."""
    _block_list(tmp_path, ["ldo_1v8", "por"])
    r = _run(tmp_path)
    assert r.returncode == 2
    rpt = _report(tmp_path)
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "floorplan_not_run"


def test_garbage_block_list_skips(tmp_path):
    """Unparseable block list is treated as no analog content → VACUOUS."""
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True, exist_ok=True)
    bl.write_text("{ this is not valid json ::::")
    _floorplan(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 2
    rpt = _report(tmp_path)
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


# ── PASS ─────────────────────────────────────────────────────────────────

def test_pass_all_a8_present(tmp_path):
    """Floorplan ran AND every analog block has its A8 LEF → earned PASS."""
    _block_list(tmp_path, ["ldo_1v8", "por"])
    _a8_lef(tmp_path, "ldo_1v8")
    _a8_lef(tmp_path, "por")
    _floorplan(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is False
    assert sorted(rpt["summary"]["a8_present"]) == ["ldo_1v8", "por"]
    assert rpt["summary"]["a8_missing"] == []


def test_pass_legacy_pnr_def_path(tmp_path):
    """Floorplan DEF under the legacy phase3/pnr/<top>.def path is honored."""
    _block_list(tmp_path, ["bandgap"])
    _a8_lef(tmp_path, "bandgap")
    legacy = tmp_path / "phase3" / "pnr" / "top.def"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("DESIGN top ;\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert _report(tmp_path)["passed"] is True


def test_pass_a8_waived(tmp_path):
    """A block whose A8 is explicitly waived does not require a LEF."""
    _block_list(tmp_path, ["ldo_1v8", "esd_clamp"])
    _a8_lef(tmp_path, "ldo_1v8")  # esd_clamp has NO lef but is waived
    _floorplan(tmp_path)
    wf = tmp_path / "phase3" / "analog" / "waivers.json"
    wf.write_text(json.dumps({"analog_waivers": [
        {"block": "esd_clamp", "step": "A8",
         "reason": "ESD clamp is a foundry primitive cell, no custom hardmacro"}
    ]}))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["a8_waived"] == ["esd_clamp"]


# ── FAIL (the real defect) ────────────────────────────────────────────────

def test_fail_floorplan_ran_a8_missing(tmp_path):
    """Floorplan DEF exists but a block has no A8 LEF → ORDERING VIOLATION."""
    _block_list(tmp_path, ["ldo_1v8", "por"])
    _a8_lef(tmp_path, "ldo_1v8")  # por's LEF deliberately absent
    _floorplan(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["passed"] is False
    assert rpt["summary"]["a8_missing"] == ["por"]
    rules = {f["rule"] for f in rpt["findings"]}
    assert "A8_MISSING_BUT_FLOORPLAN_RAN" in rules


def test_fail_all_a8_missing(tmp_path):
    """Floorplan ran with zero analog hardmacros present → FAIL, all listed."""
    _block_list(tmp_path, ["a", "b", "c"])
    _floorplan(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["passed"] is False
    assert sorted(rpt["summary"]["a8_missing"]) == ["a", "b", "c"]


# ── IO error ──────────────────────────────────────────────────────────────

def test_nonexistent_project_dir_exit2(tmp_path):
    missing = tmp_path / "does_not_exist"
    r = subprocess.run(
        [sys.executable, str(PROG), str(missing)],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
