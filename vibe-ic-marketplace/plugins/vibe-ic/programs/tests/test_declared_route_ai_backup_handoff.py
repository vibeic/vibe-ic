#!/usr/bin/env python3
"""Declared route backups must remain inside the Program First handoff."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd                         # noqa: E402
import task_nature_route as tnr                          # noqa: E402


_DEBUG_PROMPT = """
Find the bug and fix this module.

module top_module(input wire a, output wire y);
  assign y = ~a;
endmodule
"""

_BUILD_PROMPT = """
Design a module named top_module with input a and output y.  The output y must
equal a combinationally.
"""


def _write_dataset(dataset: Path, prompts: dict[str, str]) -> None:
    dataset.mkdir(parents=True)
    for problem_id, prompt in prompts.items():
        (dataset / f"{problem_id}_prompt.txt").write_text(prompt)


def _write_rtl_gen_report(project: Path, status: str, *,
                          fallback_skill: str | None = None) -> None:
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    extras = ({"fallback_skill": fallback_skill} if fallback_skill else
              {"deterministic_generator": "generic-test-emitter"})
    report.write_text(json.dumps({
        "verdict": "PASS" if status == "PASS" else "WAIVED",
        "steps": [{
            "name": "rtl_gen", "status": status,
            "detail": f"generic fixture {status.lower()}",
            "extras": extras,
        }],
    }))


def _fake_runner(*, program_ids: set[str] | None = None,
                 waived_ids: dict[str, str] | None = None):
    programs = set(program_ids or set())
    waived = dict(waived_ids or {})

    def run(argv, **_kwargs):
        project = Path(argv[2])
        if project.name in programs:
            rtl = project / "phase2" / "stage1" / "rtl"
            rtl.mkdir(parents=True, exist_ok=True)
            (rtl / "top_module.v").write_text(
                "module top_module(input wire a, output wire y); "
                "assign y = a; endmodule\n")
            _write_rtl_gen_report(project, "PASS")
            return SimpleNamespace(returncode=0)
        if project.name in waived:
            _write_rtl_gen_report(
                project, "WAIVED", fallback_skill=waived[project.name])
        return SimpleNamespace(returncode=1)

    return run


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_solve_covers_program_and_declared_route_rows_exactly(tmp_path,
                                                               monkeypatch):
    """Dropping the declared-route branch must lose one assigned ID and rc=2."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {
        "generic_program": _BUILD_PROMPT,
        "generic_route_debug": _DEBUG_PROMPT,
    })
    monkeypatch.setattr(
        bd.subprocess, "run", _fake_runner(program_ids={"generic_program"}))

    assert bd.cmd_solve(
        "verilogeval-human", str(dataset), str(run)) == 2

    backup = _read_jsonl(run / bd._BACKUP_WORKLIST)
    review = _read_jsonl(run / bd._REVIEW_WORKLIST)
    assert {row["id"] for row in backup} == {"generic_route_debug"}
    assert {row["id"] for row in review} == {"generic_program"}
    assert {row["id"] for row in backup + review} == {
        "generic_program", "generic_route_debug"}

    task = backup[0]
    project = run / "projects" / "generic_route_debug"
    prompt = (project / "input" / "phase1_prompt.md").read_text()
    assert task["skill"] == "rtl-repair"
    assert task["declared_skills"] == ["rtl-repair"]
    assert task["handoff_source"] == "route_declaration"
    assert task["prompt_sha256"] == bd._sha256_text(prompt)
    assert task["write_rtl_to"] == str(project / "phase2" / "stage1" / "rtl")
    assert task["regate_entry_step"] == "2"
    assert task["review_required_after_regating"] is True

    report = json.loads((run / "solve_report.json").read_text())
    result = {row["id"]: row for row in report["results"]}[
        "generic_route_debug"]
    assert result["candidate_origin"] == "AI_BACKUP_PENDING"
    assert result["awaiting_ai_backup"] is True
    assert result["awaiting_ai"] is True
    assert result["route_ai_backup"] == {
        "status": "DECLARED", "skills": ["rtl-repair"]}


def test_rtl_gen_waive_remains_the_primary_backup_handoff(tmp_path,
                                                           monkeypatch):
    """Adding the route consumer must not replace the existing WAIVE contract."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_waive": _BUILD_PROMPT})
    monkeypatch.setattr(
        bd.subprocess, "run",
        _fake_runner(waived_ids={"generic_waive": "spec-to-rtl"}))

    assert bd.cmd_solve(
        "verilogeval-human", str(dataset), str(run)) == 2

    backup = _read_jsonl(run / bd._BACKUP_WORKLIST)
    assert [row["id"] for row in backup] == ["generic_waive"]
    assert backup[0]["skill"] == "spec-to-rtl"
    assert backup[0]["declared_skills"] == ["spec-to-rtl"]
    assert backup[0]["handoff_source"] == "rtl_gen_waive"
    assert backup[0]["runner_said"] == "generic fixture waived"


def test_backup_destination_stays_runner_owned_across_cwd_changes(
        tmp_path, monkeypatch):
    """Leaving task paths relative must rebind the destination after a chdir."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_relative": _DEBUG_PROMPT})
    monkeypatch.setattr(bd.subprocess, "run", _fake_runner())
    monkeypatch.chdir(tmp_path)

    assert bd.cmd_solve(
        "verilogeval-human", dataset.name, run.name) == 2

    task = _read_jsonl(run / bd._BACKUP_WORKLIST)[0]
    expected_project = (run / "projects" / "generic_relative").resolve()
    assert Path(task["project"]) == expected_project
    assert Path(task["write_rtl_to"]) == (
        expected_project / "phase2" / "stage1" / "rtl")
    assert Path(task["read_prompt_from"]) == (
        expected_project / "input" / "phase1_prompt.md")


@pytest.mark.parametrize(("plugin_entry", "want_status"), [
    (None, "UNDECLARED"),
    ({}, "UNDECLARED"),
    ({"ai_backup": []}, "INVALID"),
    ({"ai_backup": "rtl-repair"}, "INVALID"),
    ({"ai_backup": [""]}, "INVALID"),
    ({"ai_backup": ["rtl-repair", 7]}, "INVALID"),
])
def test_missing_empty_or_malformed_route_backup_blocks_without_ai_work(
        tmp_path, monkeypatch, plugin_entry, want_status):
    """Weakening declaration validation must create unauthorised AI work."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_blocked": _DEBUG_PROMPT})
    verdict = {
        "nature": "debug", "entry_nature": "debug", "route": "plugin_loop",
        "source": "generic-test", "needs_ai_parse": True,
    }
    if plugin_entry is not None:
        verdict["plugin_entry"] = plugin_entry
    monkeypatch.setattr(tnr, "classify_task_nature", lambda *_args: verdict)
    monkeypatch.setattr(bd.subprocess, "run", _fake_runner())

    assert bd.cmd_solve(
        "verilogeval-human", str(dataset), str(run)) == 1
    assert _read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert _read_jsonl(run / bd._REVIEW_WORKLIST) == []

    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["candidate_origin"] == "NONE"
    assert result["awaiting_ai_backup"] is False
    assert result["awaiting_ai"] is False
    assert result["route_ai_backup"]["status"] == want_status


def test_backup_prompt_hash_change_blocks_before_regating(tmp_path,
                                                           monkeypatch):
    """Removing prompt-hash enforcement must let changed work enter the runner."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_prompt_bound": _DEBUG_PROMPT})
    monkeypatch.setattr(bd.subprocess, "run", _fake_runner())
    assert bd.cmd_solve(
        "verilogeval-human", str(dataset), str(run)) == 2

    task = _read_jsonl(run / bd._BACKUP_WORKLIST)[0]
    rtl = Path(task["write_rtl_to"])
    rtl.mkdir(parents=True)
    (rtl / "top_module.v").write_text(
        "module top_module(input wire a, output wire y); "
        "assign y = a; endmodule\n")
    Path(task["read_prompt_from"]).write_text("changed prompt\n")

    def must_not_run(*_args, **_kwargs):
        pytest.fail("a stale prompt-bound AI backup reached the runner")

    monkeypatch.setattr(bd.subprocess, "run", must_not_run)
    assert bd.cmd_resume(
        "verilogeval-human", str(dataset), str(run)) == 2
    repairs = _read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["id"] == "generic_prompt_bound"
    assert repairs[0]["status"] == "PROMPT_CHANGED"
