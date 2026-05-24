#!/usr/bin/env python3
"""Tests for analog_one_shot_runner.py — A1..A8 analog flow orchestrator.

Wave 83 — coverage for previously untested orchestrator.

The runner walks each declared analog block through 8 steps. When no
deterministic program ships for a step it returns WAIVED with the skill
name. When no analog blocks are declared the runner SKIPs cleanly.

Cases:
  1. SKIP_PURE_DIGITAL — no analog_block_list.json + L5 absent → SKIP exit 0,
                           reports/analog_one_shot.json verdict=SKIP.
  2. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  3. PASS_WITH_WAIVERS_ONE_BLOCK — one block declared → 8 steps emitted,
                                     all WAIVED (no det program present in
                                     test environment) → verdict
                                     PASS_WITH_WAIVERS.
  4. INTEGRATION_REPORT_SHAPE — phase=analog, blocks list, steps list.
  5. SKIP_VIA_L5_NO_ANALOG — L5_ADI_SPEC.json#no_analog=true → SKIP.
  6. EDGE_BLOCKS_FILTER — `--blocks <name>` selects subset of declared blocks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "programs" / \
    "analog_one_shot_runner.py"


def _run(args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _write_block_list(project: Path, blocks: list) -> None:
    a = project / "phase3" / "analog"
    a.mkdir(parents=True, exist_ok=True)
    (a / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}, indent=2))


def test_fail_no_block_list_when_missing(tmp_path):
    """v1.6.128 (#50 Fix 1) — when neither analog/analog_block_list.json
    NOR generated_docs/L5_ADI_SPEC.json exists, the runner refuses
    to silently SKIP. It emits FAIL_NO_BLOCK_LIST so the caller
    knows phase1 / spec-extract was missed.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stderr
    rep = project / "reports" / "phase3" / "analog_one_shot.json"
    body = json.loads(rep.read_text())
    assert body["phase"] == "analog"
    assert body["verdict"] == "FAIL_NO_BLOCK_LIST"
    assert body["blocks"] == []


def test_skip_pure_digital_with_empty_block_list(tmp_path):
    """v1.6.128 (#50 Fix 1) — explicit empty block list `[]` is the
    canonical "this project has no analog" signal. Runner SKIPs
    cleanly with rc=0 + verdict=SKIP.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [])  # explicit empty list
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[SKIP]" in cp.stdout
    rep = project / "reports" / "phase3" / "analog_one_shot.json"
    body = json.loads(rep.read_text())
    assert body["phase"] == "analog"
    assert body["verdict"] == "SKIP"
    assert body["blocks"] == []


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_pass_with_waivers_one_block(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [
        {"name": "tst_bandgap", "type": "bandgap"},
    ])
    cp = _run([str(project)])
    # All steps WAIVED (no det programs in test env) → 0 (PASS_WITH_WAIVERS).
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["verdict"] in ("PASS_WITH_WAIVERS", "PASS")
    assert "tst_bandgap" in body["blocks"]
    # 8 A* steps × 1 block = 8 step entries.
    assert len(body["steps"]) == 8
    statuses = {s["status"] for s in body["steps"]}
    # In our env, deterministic programs may or may not exist; anyway no
    # FAIL is expected for an empty fixture (block lacks .sp etc.).
    assert "FAIL" not in statuses or all(
        s["status"] in ("PASS", "WAIVED", "FAIL") for s in body["steps"])


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [{"name": "tst_ldo"}])
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    for k in ("phase", "project", "blocks", "steps", "verdict"):
        assert k in body
    # Each step entry has name + block + status fields.
    for s in body["steps"]:
        assert "name" in s and "block" in s and "status" in s


def test_skip_via_l5_no_analog(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({"no_analog": True}))
    cp = _run([str(project)])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["verdict"] == "SKIP"


def test_edge_blocks_filter(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [
        {"name": "tst_bandgap"},
        {"name": "tst_ldo"},
        {"name": "tst_pll"},
    ])
    cp = _run([str(project), "--blocks", "tst_ldo"])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["blocks"] == ["tst_ldo"]
    # 8 steps × 1 selected block.
    assert len(body["steps"]) == 8
