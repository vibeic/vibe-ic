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

import sys as _rt_sys
from pathlib import Path as _rt_path
_rt_sys.path.insert(0, str(_rt_path(__file__).resolve().parent))
import _runtime_pair_fixture as _rt_pair  # noqa: E402
import _ai_route_fixture as _ai_route  # noqa: E402


@pytest.fixture(autouse=True)
def _matching_runtime_pair(monkeypatch):
    """This module measures the coordinator AFTER fan-out; #2120 gates fan-out
    on a live runtime-pair check (the pinned image is here, the container a run
    selects exists, its digest IS the pin). Stating that precondition here keeps
    these assertions about the code rather than about which containers this host
    happens to be holding, and keeps `_eda_pin` out of the `subprocess.run`
    fakes below. See `_runtime_pair_fixture` for why this is a precondition and
    not a weakening; the mismatch direction is measured against the pin and the
    PREVIOUS pin in `test_issue2120_runtime_pair_preflight.py`."""
    _rt_pair.assume_matching_runtime_pair(monkeypatch)



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
                          fallback_skill: str | None = None,
                          context: dict | None = None) -> None:
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    extras = ({"fallback_skill": fallback_skill} if fallback_skill else
              {"deterministic_generator": "generic-test-emitter"})
    document = {
        "verdict": "PASS" if status == "PASS" else "WAIVED",
        "steps": [{
            "name": "rtl_gen", "status": status,
            "detail": f"generic fixture {status.lower()}",
            "extras": extras,
        }],
    }
    if context is not None:
        document = bd._bind_runner_report(
            document, project, __file__, report.name, context=context)
    report.write_text(json.dumps(document))


def _runner_invocation_context(kwargs: dict) -> dict | None:
    env = kwargs.get("env")
    raw = (env.get("VIBEIC_RUNNER_INVOCATION_CONTEXT")
           if isinstance(env, dict) else None)
    return json.loads(raw) if raw is not None else None


def _is_d1_frontdoor(argv: list[str]) -> bool:
    """The canonical D1-only Phase-1 pass: exit at D1, no routed entry."""
    return ("--exit-step" in argv
            and argv[argv.index("--exit-step") + 1] == "D1"
            and "--entry-step" not in argv)


def _emit_phase1_docs(project: Path, context: dict) -> None:
    from test_benchmark_program_first_ai_review import _emit_d1_fixture_report
    _emit_d1_fixture_report(project, context)


def _fake_runner(*, program_ids: set[str] | None = None,
                 waived_ids: dict[str, str] | None = None):
    programs = set(program_ids or set())
    waived = dict(waived_ids or {})
    real_run = bd.subprocess.run

    def run(argv, **_kwargs):
        if not any(Path(str(arg)).name == "vibe_ic_one_shot_runner.py"
                   for arg in argv):
            return real_run(argv, **_kwargs)
        project = Path(argv[2])
        if _is_d1_frontdoor(argv):
            # Every routed mid-flow entry is preceded by the canonical D1-only
            # Phase-1 pass, which emits both L-doc provenance and a typed
            # current-call report. Neither the rc nor L-doc presence alone
            # admits the owning loop's later call.
            _emit_phase1_docs(project, _runner_invocation_context(_kwargs))
            return SimpleNamespace(returncode=0)
        if project.name in programs:
            rtl = project / "phase2" / "stage1" / "rtl"
            rtl.mkdir(parents=True, exist_ok=True)
            (rtl / "top_module.v").write_text(
                "module TopModule(input wire a, output wire y); "
                "assign y = a; endmodule\n")
            _write_rtl_gen_report(
                project, "PASS", context=_runner_invocation_context(_kwargs))
            return SimpleNamespace(returncode=0)
        if project.name in waived:
            _write_rtl_gen_report(
                project, "WAIVED", fallback_skill=waived[project.name],
                context=_runner_invocation_context(_kwargs))
        return SimpleNamespace(returncode=1)

    return run


def _phase1_dead_runner():
    """A runner whose D1-only front door emits no L-doc at all.

    Every call returns 1 and writes nothing; the calls are recorded so a test
    can prove the owning loop never ran once the front door blocked.
    """
    calls: list[list[str]] = []

    def run(argv, **_kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=1)

    run.calls = calls
    return run


@pytest.mark.parametrize(("damage", "reason"), [
    ("missing", "D1_GATE_REPORT_UNREADABLE"),
    ("invalid-json", "D1_GATE_REPORT_UNREADABLE"),
    ("unbound", "RUNNER_REPORT_UNBOUND"),
    ("failed", "D1_ACTIVATION_GATE_NOT_PASS"),
])
def test_d1_report_precondition_is_required_before_the_owning_loop(
        tmp_path, monkeypatch, damage, reason):
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_d1_control": _DEBUG_PROMPT})
    calls = []

    def producer(argv, **kwargs):
        calls.append(list(argv))
        assert _is_d1_frontdoor(argv), "invalid D1 evidence launched a later step"
        project = Path(argv[2])
        _emit_phase1_docs(project, _runner_invocation_context(kwargs))
        report = project / "reports/orchestrator/phase1_one_shot.json"
        if damage == "missing":
            report.unlink()
        elif damage == "invalid-json":
            report.write_text("{")
        else:
            document = json.loads(report.read_text())
            if damage == "unbound":
                document.pop("runner_binding")
            else:
                document["verdict"] = "FAIL"
            report.write_text(json.dumps(document))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", producer)
    # A refused/unmeasured worker remains pending (coordinator rc 2).
    assert _solve_after_ai_route("verilogeval-human", dataset, run) == 2
    assert len(calls) == 1
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["worker_status"] == "ERROR"
    assert reason in result["worker_error"]
    assert _read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert _read_jsonl(run / bd._REVIEW_WORKLIST) == []


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _solve_after_ai_route(bench: str, dataset, run, **kwargs) -> int:
    assert bd.cmd_solve(bench, str(dataset), str(run), **kwargs) == 2
    return _ai_route.complete_ai_routes(bd, bench, dataset, run,
                                        jobs=kwargs.get("jobs", 1))


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

    assert _solve_after_ai_route(
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

    assert _solve_after_ai_route(
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

    assert _solve_after_ai_route(
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
def test_ai_route_uses_canonical_backup_not_malformed_router_proposal(
        tmp_path, monkeypatch, plugin_entry, want_status):
    """A router proposal cannot smuggle an AI-backup declaration into execution."""
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

    assert bd._declared_route_ai_backup(verdict)["status"] == want_status
    assert _solve_after_ai_route(
        "verilogeval-human", str(dataset), str(run)) == 2
    assert [r["skill"] for r in _read_jsonl(run / bd._BACKUP_WORKLIST)] == ["rtl-repair"]
    assert _read_jsonl(run / bd._REVIEW_WORKLIST) == []

    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["candidate_origin"] == "AI_BACKUP_PENDING"
    assert result["awaiting_ai_backup"] is True
    assert result["route_ai_backup"] == {
        "status": "DECLARED", "skills": ["rtl-repair"]}


def test_backup_prompt_hash_change_blocks_before_regating(tmp_path,
                                                           monkeypatch):
    """Removing prompt-hash enforcement must let changed work enter the runner."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_prompt_bound": _DEBUG_PROMPT})
    monkeypatch.setattr(bd.subprocess, "run", _fake_runner())
    assert _solve_after_ai_route(
        "verilogeval-human", str(dataset), str(run)) == 2

    task = _read_jsonl(run / bd._BACKUP_WORKLIST)[0]
    rtl = Path(task["write_rtl_to"])
    rtl.mkdir(parents=True)
    (rtl / "top_module.v").write_text(
        "module TopModule(input wire a, output wire y); "
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


@pytest.mark.parametrize(("plugin_entry", "want_status", "want_skills"), [
    ({"ai_backup": ["rtl-repair"]}, "DECLARED", ["rtl-repair"]),
    (None, "UNDECLARED", []),
    ({"ai_backup": "rtl-repair"}, "INVALID", []),
])
def test_blocked_frontdoor_row_keeps_the_declaration_it_classified(
        tmp_path, monkeypatch, plugin_entry, want_status, want_skills):
    """Relabelling a blocked row NOT_MEASURED must lose a classified state.

    The route declaration is a function of the routing verdict alone, so it
    is known before the Phase-1 front door runs.  When that front door BLOCKS
    (the D1-only pass emits no hash-bound L-doc) the row still stops -- one
    runner call, no owning loop, no AI work, pending rc 2 -- but it reports the
    declaration it classified and the front door that stopped it.  A DECLARED
    backup is never dispatched past a blocked front door: resume re-runs the
    same front door before regating and refuses, so the AI work could only be
    wasted.
    """
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_dead_frontdoor": _DEBUG_PROMPT})
    verdict = {
        "nature": "debug", "entry_nature": "debug", "route": "plugin_loop",
        "source": "generic-test", "needs_ai_parse": True,
    }
    if plugin_entry is not None:
        verdict["plugin_entry"] = plugin_entry
    monkeypatch.setattr(tnr, "classify_task_nature", lambda *_args: verdict)
    runner = _phase1_dead_runner()
    monkeypatch.setattr(bd.subprocess, "run", runner)

    assert _solve_after_ai_route(
        "verilogeval-human", str(dataset), str(run)) == 2
    assert len(runner.calls) == 1
    assert _is_d1_frontdoor(runner.calls[0])
    assert _read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert _read_jsonl(run / bd._REVIEW_WORKLIST) == []

    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["worker_status"] == "ERROR"
    assert result["candidate_origin"] == "NONE"
    assert result["awaiting_ai_backup"] is False
    assert result["awaiting_ai"] is False
    assert bd._declared_route_ai_backup(verdict)["status"] == want_status
    assert bd._declared_route_ai_backup(verdict)["skills"] == want_skills
    assert result["route_ai_backup"] == {
        "status": "DECLARED", "skills": ["rtl-repair"]}
    # Typed activation raises before a successful frontdoor can be returned;
    # the coordinator retains the refusal in its worker error instead.
    assert result["phase1_frontdoor"] is None
    assert result["d1_activation"] is None
    assert "D1_ENTRY_PENDING" in result["worker_error"]
    assert "emitted no hash-bound L-doc provenance" in result["worker_error"]


def test_router_outage_still_requires_ai_route_before_runner(tmp_path,
                                                          monkeypatch):
    """An advisory-router outage cannot launch a runner without AI routing."""
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    _write_dataset(dataset, {"generic_unrouted": _DEBUG_PROMPT})

    def no_routing(*_args):
        raise RuntimeError("generic routing outage")

    monkeypatch.setattr(tnr, "classify_task_nature", no_routing)
    runner = _phase1_dead_runner()
    monkeypatch.setattr(bd.subprocess, "run", runner)

    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    assert runner.calls == []
    task = _read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    assert task["program_proposal"]["source"] == "router_error"
    assert _ai_route.complete_ai_routes(
        bd, "verilogeval-human", dataset, run) == 2
    assert len(runner.calls) == 1
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["worker_status"] == "ERROR"
    assert result["routing_verdict"]["source"] == "ai_override"
    assert result["phase1_frontdoor"] is None
    assert result["d1_activation"] is None
    assert "D1_ENTRY_PENDING" in result["worker_error"]
    assert "emitted no hash-bound L-doc provenance" in result["worker_error"]
