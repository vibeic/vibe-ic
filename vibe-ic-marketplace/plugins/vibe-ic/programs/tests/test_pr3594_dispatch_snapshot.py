"""PR #3594: bind the fixed refinement input at actual dispatcher snapshots."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd  # noqa: E402


REFINEMENT = Path("phase1/behavioral_refinement.facts.yaml")


def _project(root: Path) -> Path:
    project = root / "project"
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Design a neutral state machine.\n")
    rtl = project / "phase2/stage1/rtl/dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module dut; endmodule\n")
    return project


def _author(project: Path, raw: bytes = b"facts: []\n") -> Path:
    path = project / REFINEMENT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _invocation(project: Path, monkeypatch) -> tuple[list[str], bd._ProcessOutcome]:
    calls = []

    def stopped(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bd.subprocess, "run", stopped)
    argv = [sys.executable, str(PROGRAMS / "vibe_ic_one_shot_runner.py"),
            str(project), "--no-dashboard"]
    outcome = bd._RunnerBudget(1, 1, 0).run(argv)
    assert len(calls) == 1
    return argv, outcome




def test_absence_preserves_the_existing_invocation_material_shape(tmp_path, monkeypatch):
    project = _project(tmp_path)
    argv, outcome = _invocation(project, monkeypatch)
    diagnostic = bd._runner_diagnostics(
        outcome, argv, project, require_phase2=False)
    assert diagnostic["status"] == "NO_FRESH_REPORTS"
    assert "reason" not in diagnostic




def test_identical_author_bytes_retain_actual_invocation_currentness(tmp_path,
                                                                    monkeypatch):
    project = _project(tmp_path)
    path = _author(project)
    argv, outcome = _invocation(project, monkeypatch)
    raw = path.read_bytes()
    path.write_bytes(raw)
    diagnostic = bd._runner_diagnostics(
        outcome, argv, project, require_phase2=False)
    assert diagnostic["status"] == "NO_FRESH_REPORTS"
    assert "reason" not in diagnostic
