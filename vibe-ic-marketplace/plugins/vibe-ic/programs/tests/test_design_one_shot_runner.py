#!/usr/bin/env python3
"""Tests for design_one_shot_runner.py — Phase 2b orchestrator (L docs → SOF).

Wave 83 — coverage for previously untested orchestrator.

Phase 2b runs RTL gen, reference TB, Yosys synth, QSF/SDC gen, FPGA
compile + burn, and example_tester verify. Most steps shell into Quartus / Yosys
which are not installed in the test environment, so we exercise the
orchestrator's control-flow only via:
  - precondition gate (13 L docs)
  - --dry-run early-exit
  - report shape

Cases:
  1. POSITIVE_FAIL_MISSING_PROJECT — non-existent project → exit 2.
  2. PRECONDITION_FAIL_NO_L_DOCS — empty project → phase1_precheck FAIL,
                                     verdict FAIL, exit 1, report emitted.
  3. DRY_RUN_WITH_13_L_DOCS — all 13 L docs present → --dry-run prints
                                plan JSON and exits 0 without invoking
                                Quartus / Yosys.
  4. INTEGRATION_REPORT_SHAPE — emitted phase2_one_shot.json contains
                                  ic_class / steps / verdict.
  5. EDGE_PARTIAL_L_DOCS_STILL_FAILS — 12/13 L docs → still FAIL.
  6. EDGE_TOP_NAME_FORWARDED — --top-name accepted (smoke).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "design_one_shot_runner.py"


def _run(args: list, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _seed_l_docs(project: Path, n: int = 13) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (gd / f"L{i}_TST.json").write_text("{}")


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_precondition_fail_no_l_docs(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 1
    rep = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["verdict"] == "FAIL"
    pre = next(s for s in body["steps"]
               if s["name"] == "phase1_precheck")
    assert pre["status"] == "FAIL"
    assert "13" in pre["detail"]


def test_dry_run_with_13_l_docs(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_l_docs(project, 13)
    cp = _run([str(project), "--dry-run"])
    # --dry-run path returns 0 after printing plan.
    assert cp.returncode == 0, cp.stderr
    # stdout starts with a JSON list of step plan
    out = cp.stdout.strip()
    assert out.startswith("[")
    plan = json.loads(out)
    assert any(s["name"] == "phase1_precheck" and s["status"] == "PASS"
               for s in plan)


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase2_one_shot.json").read_text())
    for k in ("project", "ic_class", "steps", "verdict"):
        assert k in body
    assert isinstance(body["steps"], list)


def test_edge_partial_l_docs_still_fails(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_l_docs(project, 12)
    cp = _run([str(project)])
    assert cp.returncode == 1
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase2_one_shot.json").read_text())
    assert body["verdict"] == "FAIL"
    pre = next(s for s in body["steps"]
               if s["name"] == "phase1_precheck")
    assert pre["status"] == "FAIL"
    assert "12" in pre["detail"]


def test_edge_top_name_forwarded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_l_docs(project, 13)
    cp = _run([str(project), "--dry-run", "--top-name", "tst_chip_top"])
    assert cp.returncode == 0
    # Plan parses without error; --top-name doesn't appear in dry-run plan
    # but the program at least accepted it without argparse error.
    plan = json.loads(cp.stdout.strip())
    assert isinstance(plan, list)
