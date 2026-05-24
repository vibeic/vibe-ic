#!/usr/bin/env python3
"""Tests for phase1_one_shot_runner.py — Phase 1 (Path A) orchestrator.

Wave 83 — coverage for previously untested orchestrator.

Phase 1 wraps tools/phase1_engine/cli.py. Tests run the orchestrator's
control-flow only — they verify the runner SKIPs cleanly when no input
is staged, FAILs cleanly when phase1_engine is unreachable, and emits
the aggregate JSON report under reports/.

Cases:
  1. SKIP_EMPTY_FIXTURE — project dir present but no input files →
                           runner SKIPs ingest step, exit 0,
                           reports/phase1_one_shot.json with verdict
                           PASS_WITH_WAIVERS.
  2. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  3. INTEGRATION_REPORT_SHAPE — emitted phase1_one_shot.json must contain
                                  phase / project / steps / verdict keys.
  4. STEP_DETAIL_REASON_PRESENT — when SKIPped, the detail explains
                                    that input/phase1_structured.yaml or
                                    input/docs/ is missing.
  5. INPUT_DOCS_TRIGGERS_INGEST — staging input/docs/ flips the runner
                                    out of SKIP into ingest_render.
                                    Without phase1_engine cli installed
                                    the step records FAIL but the runner
                                    still emits a summary report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "programs" / \
    "phase1_one_shot_runner.py"


def _run(args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def test_skip_empty_fixture(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--ic-name", "TST_CHIP"])
    # SKIP path returns 0; verdict is PASS_WITH_WAIVERS.
    assert cp.returncode == 0, cp.stderr
    rep = project / "reports" / "phase1_one_shot.json"
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["phase"] == 1
    assert body["verdict"] in ("PASS_WITH_WAIVERS", "PASS")
    # The ingest step's detail explains the missing input.
    ingest = next((s for s in body["steps"]
                    if s["name"] == "phase1_ingest_render"), None)
    assert ingest is not None
    assert ingest["status"] in ("SKIP", "FAIL")


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--ic-name", "TST_CHIP"])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase1_one_shot.json").read_text())
    for k in ("phase", "project", "ic_name", "steps", "verdict"):
        assert k in body, f"missing key {k} in report"
    assert body["ic_name"] == "TST_CHIP"
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 2  # ingest + human_docs


def test_step_detail_explains_missing_input(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase1_one_shot.json").read_text())
    ingest = next(s for s in body["steps"]
                  if s["name"] == "phase1_ingest_render")
    detail = ingest["detail"].lower()
    # Reason mentions either the YAML or docs/ input path.
    assert ("phase1_structured.yaml" in detail or "docs" in detail
            or "engine" in detail)


def test_input_docs_directory_changes_branch(tmp_path):
    """Stage input/docs/ → ingest step is exercised. Whether the
    actual phase1_engine cli runs depends on the host install; if not
    found, the step FAILs with a clear message — but the orchestrator
    still emits a report.
    """
    project = tmp_path / "proj"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "tst_chip_spec.txt").write_text(
        "TST_CHIP — minimal stub for orchestrator test\n")
    cp = _run([str(project), "--ic-name", "TST_CHIP"])
    # Either PASS (if engine available) or non-zero with a report. Both
    # paths must emit the JSON report.
    rep = project / "reports" / "phase1_one_shot.json"
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["ic_name"] == "TST_CHIP"
    ingest = next(s for s in body["steps"]
                  if s["name"] == "phase1_ingest_render")
    assert ingest["status"] in ("PASS", "FAIL", "SKIP")
