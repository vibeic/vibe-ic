#!/usr/bin/env python3
"""Tests for vibe_ic_one_shot_runner.py — full Vibe-IC flow orchestrator.

Wave 83 — coverage for previously untested orchestrator.

Top-level chain that runs Phase 1 → Phase 2 (= 2a + 2b) → Analog A1..A8 →
Phase 3. Auto-detects entry-point and skips phases that are not
applicable. Tests exercise control-flow only (children invoke external
tools).

Cases:
  1. POSITIVE_FAIL_MISSING_PROJECT — non-existent project → exit 2.
  2. EMPTY_FIXTURE_HALTS_AT_PHASE2 — empty project → phase1 SKIPPED,
                                       phase2 FAILS → halt → exit 1 +
                                       aggregate report shape correct.
  3. SKIP_ALL_LOWER_PHASES — --skip-phase1 + --skip-phase3 (and no
                               analog declared) → only phase2 runs;
                               phase2 still fails → overall FAIL.
  4. INTEGRATION_AGGREGATE_REPORT_SHAPE — vibe_ic_one_shot.json contains
                                            phase / phases / verdict /
                                            halted_at.
  5. NEED_PHASE1_AUTO_DETECTS_PROMPT_INPUT — staging
                                               input/phase1_prompt.md flips
                                               phase1 from SKIPPED to
                                               run-attempt.
  6. EDGE_TOP_NAME_FORWARDED — --top-name accepted (smoke).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "vibe_ic_one_shot_runner.py"


def _run(args: list, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_empty_fixture_halts_at_phase2(tmp_path):
    """Empty project → phase1 SKIPPED, phase2 FAIL, halt."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--skip-phase3", "--skip-analog"])
    assert cp.returncode == 1
    rep = project / "reports" / "orchestrator" / "vibe_ic_one_shot.json"
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["verdict"] == "FAIL"
    assert body["halted_at"] == "phase2"


def test_skip_phase1_phase3(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project),
               "--skip-phase1", "--skip-phase3", "--skip-analog"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "vibe_ic_one_shot.json").read_text())
    p_names = {p["name"]: p["verdict"] for p in body["phases"]}
    assert p_names.get("phase1") == "SKIPPED"
    assert p_names.get("phase3") == "SKIPPED"
    # phase2 should have run and FAILed (no L docs, no input/docs/).
    assert p_names.get("phase2") == "FAIL"


def test_integration_aggregate_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--skip-phase3", "--skip-analog"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "vibe_ic_one_shot.json").read_text())
    for k in ("phase", "project", "phases", "verdict"):
        assert k in body
    assert body["phase"] == "vibe-ic"
    assert isinstance(body["phases"], list)
    # Each phase entry shape.
    for p in body["phases"]:
        assert "name" in p and "verdict" in p


def test_need_phase1_auto_detects_prompt_input(tmp_path):
    """Staging input/phase1_prompt.md → phase1 attempts to run.

    Without phase1_engine cli installed in the test env the engine
    runner returns FAIL or SKIP — but the orchestrator records phase1
    in the plan (i.e. NOT SKIPPED at the top level).
    """
    project = tmp_path / "proj"
    inp = project / "input"
    inp.mkdir(parents=True)
    (inp / "phase1_prompt.md").write_text(
        "Design a generic test chip TST_CHIP for orchestrator coverage.\n")
    cp = _run([str(project), "--skip-phase3", "--skip-analog",
               "--ic-name", "TST_CHIP"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "vibe_ic_one_shot.json").read_text())
    p_phase1 = next(p for p in body["phases"] if p["name"] == "phase1")
    # phase1 attempted → not SKIPPED at the top dispatcher level.
    # (Inside phase1, individual steps may be SKIP/WAIVED — that's fine.)
    assert p_phase1["verdict"] != "SKIPPED"


def test_edge_top_name_forwarded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project),
               "--skip-phase3", "--skip-analog",
               "--top-name", "tst_chip_top"])
    # Just smoke check — flag accepted, no argparse error.
    rep = project / "reports" / "orchestrator" / "vibe_ic_one_shot.json"
    assert rep.is_file()
