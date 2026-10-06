#!/usr/bin/env python3
"""Issue #1970: bounded project fan-out with one shared-state coordinator.

The CLI probe reads the real checked-in dispatcher.  The behavioural fixtures
then drive the public solve/resume commands with two distinct project roots and
record the runner intervals.  They deliberately make the first project slower
so completion order differs from dataset order; the shared artifacts must
still be byte-equivalent to ``--jobs 1`` and remain dataset ordered.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent / "benchmark"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_dispatch as bd                         # noqa: E402
import benchmark_entry_surface_check as bes             # noqa: E402
import benchmark_io_adapter as bio                      # noqa: E402
import flow_phase_attribution as fpa                    # noqa: E402
import task_nature_route as tnr                         # noqa: E402
from _hostpaths import require_repo                     # noqa: E402
import _runtime_pair_fixture as _rt_pair                # noqa: E402
import _ai_route_fixture as _ai_route                    # noqa: E402
import test_benchmark_program_first_ai_review as review_fixture  # noqa: E402


def _solve_after_ai_route(bench, dataset, run, *, jobs=1,
                          heavy_jobs=None, worker_threads=0):
    assert bd.cmd_solve(bench, str(dataset), str(run), jobs=jobs,
                        heavy_jobs=heavy_jobs,
                        worker_threads=worker_threads) == 2
    return _ai_route.complete_ai_routes(bd, bench, dataset, run, jobs=jobs,
                                        heavy_jobs=heavy_jobs,
                                        worker_threads=worker_threads)


def _phase_record() -> dict:
    return {
        "phase1_routing": {},
        "phase2_solving": {},
        "phase3_verifying": {},
        "phase4_debugging": {},
    }


def _install_common_fakes(monkeypatch) -> None:
    # A MATCHING RUNTIME PAIR, because these fixtures are about what the
    # coordinator does AFTER it fans out (#2120 gates fan-out on the pair) and
    # `fake_run` below replaces `subprocess.run` on the module object, which is
    # how `_eda_pin` reaches docker. See `_runtime_pair_fixture`.
    _rt_pair.assume_matching_runtime_pair(monkeypatch)
    monkeypatch.setattr(bes, "audit", lambda _root: {
        "verdict": "PASS", "findings": []})
    monkeypatch.setattr(bd, "_completeness_adapters", lambda: {})
    monkeypatch.setattr(fpa, "rtl_present_at_input", lambda _project: False)
    monkeypatch.setattr(fpa, "attribute", lambda *_a, **_k: _phase_record())
    monkeypatch.setattr(fpa, "summarize", lambda _results: {})
    monkeypatch.setattr(
        tnr, "classify_task_nature",
        lambda *_a, **_k: {"nature": "fixture", "entry_nature": "fixture",
                           "route": "plugin_loop", "plugin_entry": {}})
    monkeypatch.setattr(tnr, "NATURE_ENTRY", {
        "fixture": {"entry_step": "D1", "default_evidence": "RTL_SIM",
                    "then": ["2"],
                    "route": "plugin_loop", "plugin_entry": {}}})
    monkeypatch.setattr(tnr, "EVIDENCE_EXIT", {
        "RTL_SIM": {"exit_step": "8"}})
    monkeypatch.setattr(tnr, "flow_step_ids", lambda: ["D1", "2", "8", "15"])


def _install_solve_fakes(monkeypatch, intervals: dict[str, tuple[float, float]],
                         *, fail_pid: str | None = None,
                         seen_env: dict[str, dict] | None = None) -> None:
    _install_common_fakes(monkeypatch)

    def prepare(_bench, _dataset, run, _fmt, _limit):
        run.mkdir(parents=True, exist_ok=True)
        for child in ("projects", "responses", "reports", "transcripts"):
            (run / child).mkdir(parents=True, exist_ok=True)
        bd._atomic_write_json(run / ".bench_config.json", {
            "bench": _bench, "dataset": str(Path(_dataset).resolve()),
            "format": _fmt, "diagnostic_limit": int(_limit or 0),
        })

    monkeypatch.setattr(bd, "_prepare_general_solve_run", prepare)
    monkeypatch.setattr(
        bio, "problems",
        lambda _fmt, _dataset: [{"id": "p1"}, {"id": "p2"}])

    def stage(_fmt, problem, project):
        prompt = project / "input" / "phase1_prompt.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        text = f"Design {problem['id']} with an input and an output.\n"
        prompt.write_text(text)
        # `public_original_input` is a TOTAL part of the real `stage()`
        # contract -- `benchmark_io_adapter.stage` has exactly one return and
        # always carries it -- and `_cmd_solve_locked` reads it by subscript.
        # Built with the SAME helper the real one uses rather than a literal,
        # so this fake cannot drift from the contract a second time. An empty
        # context is the honest fixture shape: status NOT_PROVIDED.
        original = bio._stage_public_original(
            problem["id"], text, {}, project)
        return {"prompt_chars": len(text),
                "public_original_input": original}

    monkeypatch.setattr(bio, "stage", stage)
    monkeypatch.setattr(
        bio, "collect",
        lambda *_a, **_k: {"ok": False, "reason": "fixture-no-candidate"})

    interval_lock = threading.Lock()

    def fake_run(argv, *args, **kwargs):
        project = Path(argv[2])
        if argv[argv.index("--exit-step") + 1] == "D1":
            review_fixture._emit_d1_fixture_report(
                project, json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
            return SimpleNamespace(returncode=0)
        pid = project.name
        run_name = project.parents[1].name
        started = time.monotonic()
        time.sleep(0.18 if pid == "p1" else 0.06)
        finished = time.monotonic()
        with interval_lock:
            intervals[f"{run_name}:{pid}"] = (started, finished)
            if seen_env is not None:
                seen_env[f"{run_name}:{pid}"] = dict(kwargs.get("env") or {})
        if pid == fail_pid:
            raise RuntimeError("synthetic runner worker failure")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)


def _write_resume_fixture(run: Path) -> None:
    run.mkdir(parents=True)
    results = []
    backups = []
    for pid in ("p1", "p2"):
        project = run / "projects" / pid
        prompt = project / "input" / "phase1_prompt.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text(f"Design {pid}.\n")
        rtl = project / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True)
        (rtl / "dut.v").write_text("module dut; endmodule\n")
        results.append({
            "id": pid, "ok": False, "candidate_ready": False,
            "accepted": False, "entry": "D1", "evidence": "RTL_SIM",
            "exit": "8", "routing_verdict": {
                "nature": "fixture", "plugin_entry": {}},
            "candidate_origin": "AI_BACKUP_PENDING",
            "program_first_ai_review": {"status": "PENDING"},
            "awaiting_ai": True, "awaiting_ai_review": False,
            "awaiting_ai_backup": True, "ai_repair_required": False,
        })
        # d854185 ("converge LEC, stamp reports and public input handoffs",
        # v1.19.90) made the AI-backup handoff BLOCKING: `_validate_backup_
        # completion` refuses to dispatch a worker until the coordinator-issued
        # task, the staged public original input and a named-author completion
        # record all agree. A three-key row cannot reach the dispatch this test
        # measures. Every field below is produced by the PRODUCTION helper that
        # defines it, never by a literal, so this fixture cannot drift from the
        # contract the way the three-key one did.
        original = bio._stage_public_original(pid, prompt.read_text(), {},
                                              project)
        item = {
            "id": pid,
            "project": str(project),
            "prompt_sha256": bd._sha256_text(prompt.read_text()),
            "public_original_input": original,
            # An empty prior manifest makes the disposition CHANGED, which is
            # the arm that does not additionally require prompt-bound
            # no-change evidence.
            "initial_output_manifest": [],
        }
        item["task_sha256"] = bd._sha256_text(
            json.dumps(item, sort_keys=True))
        issued = run / "ai_backup_tasks"
        issued.mkdir(parents=True, exist_ok=True)
        (issued / f"{item['task_sha256']}.json").write_text(json.dumps(item))
        (project / "phase2" / "stage1" / "ai_backup_author.json").write_text(
            json.dumps({
                "schema": "vibeic.benchmark.ai_backup_record.v1",
                "id": pid,
                "task_sha256": item["task_sha256"],
                "prompt_sha256": item["prompt_sha256"],
                "source_sha256": original.get("source_sha256"),
                "output_manifest": bd._backup_output_manifest(project),
                "rtl_sha256": bd._sha256_text(
                    bd._candidate_text(bd._rtl_files(project))),
                "author": {"kind": "AI", "model": "fixture-backup-author"},
                "oracle_accessed": False,
                "rationale": ("Fixture author record: the RTL was authored "
                              "from the staged prompt alone, with no oracle "
                              "or harness read."),
                "disposition": "CHANGED",
            }))
        backups.append(item)
    (run / "solve_report.json").write_text(json.dumps({
        "bench": "rtllm", "format": "rtllm", "total": 2,
        "solved": 0, "accepted": 0,
        "acceptance_policy": {
            "required": True,
            "review_task_schema": bd._REVIEW_TASK_SCHEMA,
            "review_schema": bd._AI_REVIEW_SCHEMA,
        },
        "results": results,
    }))
    bd._write_jsonl(run / bd._BACKUP_WORKLIST, backups)
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [])
    # These resume controls start AFTER routing/D1. Issue the same immutable
    # input/config and real coordinator admissions as solve, with only the
    # synthetic D1 producer mocked; a writable backup row is not authority.
    extra_routes = [bd._make_ai_route_task(
        item["id"], Path(item["project"]),
        {"public_original_input": item["public_original_input"]},
        review_fixture.ROUTING, run, "rtllm", benchmark="rtllm",
        dataset_path=Path("/unused")) for item in backups[1:]]
    routes = review_fixture._write_issued_run_envelope(
        run, dict(backups[0]), extra_routes=extra_routes)
    for result, route in zip(results, routes):
        result["route_receipt"] = review_fixture._issue_active_route_fixture(
            run, route, nature="fixture", requested_evidence="RTL_SIM")
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    solve["results"] = results
    solve_path.write_text(json.dumps(solve))


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


def _prior_collectable_report(project: Path, *, invocation_context=None):
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    from design_one_shot_runner import _write_phase2_report
    _write_phase2_report(report, {"verdict": "PASS", "steps": [
        {"name": "rtl_gen", "status": "PASS"},
        {"name": "rtl_validate", "status": "PASS"}]}, project,
                         invocation_context=invocation_context)
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    ldoc = docs / "L1_DATASHEET.json"
    if not ldoc.exists():
        ldoc.write_text('{"schema": 1}\n')
    return report


def test_real_runner_refusal_is_preserved_instead_of_being_an_outcome(tmp_path):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "vibe_ic_one_shot_runner.py")
    outcome = bd._RunnerBudget(1, 1, 0).run([
        sys.executable, str(runner), str(tmp_path), "--no-dashboard",
        "--entry-step", "2", "--exit-step", "2", "--skip-phase3"])
    assert outcome.rc == 2
    assert (outcome.error or "COMPLETED").split(":", 1)[0] == "RUNNER_INVOCATION_REFUSED"
    receipt = outcome.invocation
    assert receipt["status"] == "REFUSED"
    assert json.loads(Path(receipt["record_path"]).read_text()) == receipt
    stderr = Path(receipt["stderr_path"]).read_text()
    assert stderr.startswith("REFUSED: DELIVERY_ROUTE_UNDECLARED")
    assert bd._sha256_text(stderr) == receipt["stderr_sha256"]


def test_real_refusal_cannot_collect_old_reports_and_resume_retries_only_that_backup(
        tmp_path, monkeypatch):
    _install_common_fakes(monkeypatch)
    # This mocked transport test uses local challenge execution. The real
    # challenge runtime selector must not inspect a daemon through our runner
    # fake when it issues the healthy worker's review task.
    monkeypatch.setenv("VIBEIC_CHALLENGE_BACKEND", "host")
    run = tmp_path / "run"
    _write_resume_fixture(run)
    for pid in ("p1", "p2"):
        project = run / "projects" / pid
        _prior_collectable_report(project)
        assert bio.collect("rtllm", pid, project, supplied_rtl=True)["ok"] is True
    prior_report = run / "projects" / "p1" / "reports" / "orchestrator" / "phase2_one_shot.json"
    before = prior_report.read_bytes()
    # The refusal must survive the explicit IP route fix: this operator has
    # declared a DIE deliverable, so asking for IP conflicts before any gate.
    from _delivery_route import admit
    from _submission_template import DESIGN_ANSWERS_REL
    assert admit(run / "projects" / "p1", "ic") is None
    declaration = run / "projects" / "p1" / DESIGN_ANSWERS_REL
    declared_bytes = declaration.read_bytes()
    native_run = bd.subprocess.run
    refuse = True
    calls = []

    def run_worker(argv, **kwargs):
        pid = Path(argv[2]).name
        calls.append(pid)
        if pid == "p1" and refuse:
            return native_run(argv + ["--no-dashboard", "--route", "ip"], **kwargs)
        _prior_collectable_report(Path(argv[2]), invocation_context=json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
        return SimpleNamespace(returncode=1, stdout="bounded NOT_MEASURED\n", stderr="")

    monkeypatch.setattr(bd.subprocess, "run", run_worker)
    assert bd.cmd_resume("rtllm", "/unused", str(run), jobs=2) == 2
    rows = {r["id"]: r for r in json.loads((run / "solve_report.json").read_text())["results"]}
    assert rows["p1"]["candidate_ready"] is False
    assert rows["p1"]["rc"] == 2
    assert "RUNNER_INVOCATION_REFUSED" in rows["p1"]["worker_error"]
    assert "contradicts the existing owner-provenance answer DIE" in rows["p1"]["worker_error"]
    assert rows["p2"]["candidate_ready"] is True
    assert rows["p2"]["rc"] == 1
    assert prior_report.read_bytes() == before
    assert declaration.read_bytes() == declared_bytes
    assert [r["id"] for r in bd._read_jsonl(run / bd._BACKUP_WORKLIST)] == ["p1"]
    healthy = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    assert [r["id"] for r in healthy] == ["p2"]
    assert rows["p1"]["accepted"] is rows["p2"]["accepted"] is False
    refuse = False
    calls.clear()
    assert bd.cmd_resume("rtllm", "/unused", str(run), jobs=2) == 2
    assert calls == ["p1"]
    assert declaration.read_bytes() == declared_bytes
    after = {r["id"]: r for r in bd._read_jsonl(run / bd._REVIEW_WORKLIST)}
    assert after["p2"] == healthy[0]
    assert after["p1"]["program_verification"]["runner_rc"] == 1
    assert after["p1"]["program_verification"]["runner_invocation"]["status"] == "COMPLETED"


@pytest.mark.parametrize("rc,stderr,expected", [
    (1, "ERROR: RTL compiler rejected the candidate", "COMPLETED"),
    (1, "", "COMPLETED"),
    (-9, "", "RUNNER_WORKER_FAILED"),
    (2, "", "RUNNER_INVOCATION_NOT_MEASURED"),
    (3, "CONCURRENT_RUN_REFUSED: occupied project", "RUNNER_INVOCATION_REFUSED"),
])
def test_runner_process_disposition_does_not_confuse_gate_results(
        tmp_path, monkeypatch, rc, stderr, expected):
    monkeypatch.setattr(bd.subprocess, "run", lambda *_a, **_k:
                        SimpleNamespace(returncode=rc, stdout="complete stdout\n", stderr=stderr))
    outcome = bd._RunnerBudget(1, 1, 0).run([sys.executable, str(PROGRAMS / "vibe_ic_one_shot_runner.py"), str(tmp_path)])
    assert outcome.rc == rc
    assert (outcome.error or "COMPLETED").split(":", 1)[0] == expected
    assert Path(outcome.invocation["stdout_path"]).read_text() == "complete stdout\n"
    assert Path(outcome.invocation["stderr_path"]).read_text() == stderr


def test_timeout_retains_the_partial_output(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", "1")
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("runner", 1, output=b"partial stdout", stderr=b"partial stderr")
    monkeypatch.setattr(bd.subprocess, "run", timeout)
    outcome = bd._RunnerBudget(1, 1, 0).run([sys.executable, str(PROGRAMS / "vibe_ic_one_shot_runner.py"), str(tmp_path)])
    assert outcome.rc is None
    assert outcome.error.startswith("RUNNER_WORKER_FAILED")
    assert Path(outcome.invocation["stdout_path"]).read_text() == "partial stdout"
    assert Path(outcome.invocation["stderr_path"]).read_text() == "partial stderr"


def test_legacy_unmeasured_review_is_regated_without_rebinding_the_old_review(
        tmp_path, monkeypatch):
    from test_benchmark_program_first_ai_review import _task, _solve_report, _write_review, _valid_review
    _rt_pair.assume_matching_runtime_pair(monkeypatch)
    run, task, _ = _task(tmp_path)
    task["program_verification"]["runner_rc"] = 2
    # Retain this legacy control's explicit step-8 span in its test route
    # table; the product now defaults spec_generation to lint at step 2.
    monkeypatch.setitem(tnr.EVIDENCE_EXIT, "fixture_spec_conformance", {
        "exit_step": "8"})
    _solve_report(run, task, active_route=True,
                  requested_evidence="fixture_spec_conformance")
    _write_review(task, _valid_review(task))
    old_review = Path(task["review_path"]).read_bytes()
    seen = []
    native_run = bd.subprocess.run
    def worker(argv, **_kwargs):
        if Path(str(argv[1])).name != "vibe_ic_one_shot_runner.py":
            return native_run(argv, **_kwargs)
        seen.append(argv)
        _prior_collectable_report(Path(argv[2]), invocation_context=json.loads(_kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
        return SimpleNamespace(returncode=1, stdout="bounded NOT_MEASURED", stderr="")
    monkeypatch.setattr(bd.subprocess, "run", worker)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert len(seen) == 1
    assert seen[0][seen[0].index("--entry-step") + 1] == "2"
    assert seen[0][seen[0].index("--exit-step") + 1] == "8"
    fresh = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert fresh["rtl_sha256"] == task["rtl_sha256"]
    assert fresh["review_path"] != task["review_path"]
    assert fresh["verification_challenges"] == task["verification_challenges"]
    assert Path(task["review_path"]).read_bytes() == old_review
    assert not Path(fresh["review_path"]).exists()
    assert bd._runner_reentry_reason(fresh, {}) is None
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["accepted"] == 0
    preserved = list((run / "runner_regates").rglob("prior_task.json"))
    assert len(preserved) == 1 and json.loads(preserved[0].read_text()) == task


def test_cli_exposes_jobs_for_solve_and_resume() -> None:
    dispatch = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "benchmark_dispatch.py")
    proc = subprocess.run(
        [sys.executable, str(dispatch), "--list", "--jobs", "2"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "--jobs JOBS" in subprocess.run(
        [sys.executable, str(dispatch), "--help"], capture_output=True,
        text=True, check=True).stdout


def test_solve_jobs_overlap_and_commit_shared_artifacts_in_dataset_order(
        tmp_path, monkeypatch) -> None:
    intervals: dict[str, tuple[float, float]] = {}
    _install_solve_fakes(monkeypatch, intervals)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    serial = tmp_path / "serial"
    parallel = tmp_path / "parallel"

    assert _solve_after_ai_route(
        "rtllm", str(dataset), str(serial), jobs=1) == 1
    assert _solve_after_ai_route(
        "rtllm", str(dataset), str(parallel), jobs=2) == 1

    assert _overlap(intervals["parallel:p1"], intervals["parallel:p2"])
    assert not _overlap(intervals["serial:p1"], intervals["serial:p2"])
    serial_report = json.loads((serial / "solve_report.json").read_text())
    parallel_report = json.loads((parallel / "solve_report.json").read_text())
    assert [row["id"] for row in parallel_report["results"]] == ["p1", "p2"]
    # NON-VACUITY, BEFORE THE COMPARISON. Equality of two reports is evidence
    # that jobs=1 and jobs=2 AGREE only if the runs actually ran. Measured on
    # the tree before v1.20.33: `bio.stage`'s fake omitted
    # `public_original_input`, EVERY worker died with
    # `KeyError: 'public_original_input'`, the coordinator wrote an ERROR row
    # for each — and this case compared two IDENTICALLY BROKEN runs, which are
    # equal, so it PASSED while measuring no dispatch whatsoever. v1.20.33
    # repaired the fixture and the case went green again; nothing yet stops it
    # going quietly green the next time a worker-side contract moves.
    #
    # `worker_status` is written ONLY on the coordinator's except path
    # (`benchmark_dispatch._cmd_solve_locked`), so its presence is the
    # program's own statement that the worker did not finish. Reading it here
    # asks the report the one question equality cannot: did anything run.
    for label, report in (("serial", serial_report),
                          ("parallel", parallel_report)):
        errored = [row["id"] for row in report["results"]
                   if row.get("worker_status") == "ERROR"]
        assert not errored, (
            f"the {label} workers did not run, so comparing the two reports "
            f"proves nothing: {errored}\n"
            + json.dumps(report["results"], indent=1)[:1200])
    # Route responses bind the distinct run roots, so their hashes differ;
    # compare execution outcomes after excluding that expected identity.
    for root, report in ((serial, serial_report), (parallel, parallel_report)):
        for row in report["results"]:
            state = bd._validated_route_reentry_state(
                bench="rtllm", dataset=dataset, fmt="rtllm", run_p=root,
                pid=row["id"], result=row,
                route_worklist=bd._read_jsonl(root / bd._ROUTE_WORKLIST),
                allow_d1_only=False)
            assert state["status"] == "ACTIVE", state
            assert row["d1_activation"] == state["activation"]
            binding = row["routing_verdict"]["coordinator_binding"]
            assert binding == state["task"]["coordinator_binding"]
            for key in ("project_handle", "prompt_handle", "response_handle", "binding_sha256"):
                binding.pop(key)
            row["routing_verdict"].pop("ai_route_response_sha256", None)
            # Invocation identities name their own run root and immutable
            # log archive. Validate those facts before comparing outcomes.
            invocation = row.pop("runner_invocation", None)
            if invocation is not None:
                assert invocation["status"] == "COMPLETED"
                assert Path(invocation["project"]).name == row["id"]
                assert json.loads(Path(invocation["record_path"]).read_text()) == invocation
                diagnostic = bd._stored_runner_diagnostics(invocation)
                assert not diagnostic or not diagnostic.get("reason"), diagnostic
            frontdoor = row["phase1_frontdoor"]
            d1_invocation = frontdoor.pop("runner_invocation")
            assert json.loads(Path(d1_invocation["record_path"]).read_text()) == d1_invocation
            gate = frontdoor["d1_gate"]
            assert gate == row["d1_activation"]["d1_gate"]
            assert gate["invocation_id"] == d1_invocation["invocation_id"]
            assert gate["current_call"] is True and gate["verdict"] == "PASS"
            for key in ("task_sha256", "invocation_id", "report_sha256", "ldoc_root_handle", "gate_sha256"):
                gate.pop(key)
            # Admission above validated the complete activation and D1 gate.
            # Compare semantic evidence after removing only the named run
            # identities; every route/producer binding was checked first.
            activation = row["d1_activation"]
            activation["d1_gate"] = dict(gate)
            for key in ("task_sha256", "d1_gate_sha256", "activation_sha256", "ldoc_root_handle"):
                activation.pop(key)
    assert parallel_report == serial_report
    for name in (bd._BACKUP_WORKLIST, bd._REVIEW_WORKLIST,
                 bd._ACCEPTANCE_REPORT):
        assert (parallel / name).read_bytes() == (serial / name).read_bytes()


def test_resume_jobs_overlap_but_coordinator_writes_worklists_in_solve_order(
        tmp_path, monkeypatch) -> None:
    _install_common_fakes(monkeypatch)
    run = tmp_path / "resume"
    _write_resume_fixture(run)
    intervals: dict[str, tuple[float, float]] = {}
    argv_by_id: dict[str, list[str]] = {}
    interval_lock = threading.Lock()

    def fake_run(argv, *args, **kwargs):
        pid = Path(argv[2]).name
        started = time.monotonic()
        time.sleep(0.18 if pid == "p1" else 0.06)
        finished = time.monotonic()
        with interval_lock:
            intervals[pid] = (started, finished)
            argv_by_id[pid] = list(argv)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    monkeypatch.setattr(
        bio, "collect",
        lambda *_a, **_k: {"ok": False, "reason": "fixture gate rejection"})

    assert bd.cmd_resume("rtllm", "/unused", str(run), jobs=2) == 2
    assert _overlap(intervals["p1"], intervals["p2"])
    for pid in ("p1", "p2"):
        argv = argv_by_id[pid]
        assert argv[argv.index("--entry-step") + 1] == "2", argv
        assert argv[argv.index("--exit-step") + 1] == "8", argv
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert [row["id"] for row in repairs] == ["p1", "p2"]
    assert [row["id"] for row in bd._read_jsonl(
        run / bd._BACKUP_WORKLIST)] == ["p1", "p2"]


def test_one_runner_worker_error_is_loud_and_does_not_erase_other_results(
        tmp_path, monkeypatch) -> None:
    intervals: dict[str, tuple[float, float]] = {}
    _install_solve_fakes(monkeypatch, intervals, fail_pid="p1")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    run = tmp_path / "worker-error"

    assert _solve_after_ai_route("rtllm", dataset, run, jobs=2) == 2
    results = json.loads((run / "solve_report.json").read_text())["results"]
    assert [row["id"] for row in results] == ["p1", "p2"]
    assert results[0]["worker_status"] == "ERROR"
    assert results[0]["rc"] is None
    assert "worker_status" not in results[1]
    assert results[1]["rc"] == 0

    def recovered_runner(argv, **kwargs):
        if argv[argv.index("--exit-step") + 1] == "D1":
            review_fixture._emit_d1_fixture_report(
                Path(argv[2]), json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(bd.subprocess, "run", recovered_runner)
    assert bd.cmd_resume("rtllm", str(dataset), str(run), jobs=2) == 1
    resumed = json.loads((run / "solve_report.json").read_text())["results"]
    assert [row["id"] for row in resumed] == ["p1", "p2"]
    assert "worker_status" not in resumed[0]
    assert resumed[0]["rc"] == 0
    assert "worker_status" not in resumed[1]


def test_heavy_jobs_and_worker_threads_are_independent_resource_bounds(
        tmp_path, monkeypatch) -> None:
    intervals: dict[str, tuple[float, float]] = {}
    seen_env: dict[str, dict] = {}
    _install_solve_fakes(monkeypatch, intervals, seen_env=seen_env)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    run = tmp_path / "bounded"

    assert _solve_after_ai_route(
        "rtllm", str(dataset), str(run), jobs=2, heavy_jobs=1,
        worker_threads=3) == 1
    assert not _overlap(intervals["bounded:p1"], intervals["bounded:p2"])
    for pid in ("p1", "p2"):
        env = seen_env[f"bounded:{pid}"]
        assert env["VIBEIC_EDA_THREADS"] == "3"
        assert env["OMP_NUM_THREADS"] == "3"


def test_same_run_root_rejects_a_second_resume_coordinator(
        tmp_path, capsys) -> None:
    run = tmp_path / "locked"
    run.mkdir()
    with bd._run_root_coordinator_lock(run, "test-holder"):
        assert bd.cmd_resume("rtllm", "/unused", str(run), jobs=2) == 2
    err = capsys.readouterr().err
    assert "another benchmark_dispatch coordinator" in err
    assert str(run.resolve()) in err


def test_the_matching_pair_is_stated_not_asked_of_this_host(monkeypatch) -> None:
    """The pair precondition must not depend on which test ran first.

    `_install_common_fakes` states the pair and then replaces `subprocess.run`
    with a runner fake. Until the fixture stated the identity too, its stubs
    read `_pin.IMAGE_DIGEST`, which resolves from this host: with a cold
    per-process cache and no override env that is `docker image ls --digests`,
    answered by the runner fake (IndexError / AttributeError). Every behavioural
    test in this module was red alone and green after any test that had warmed
    the cache. This models the COLD process deterministically: empty cache, no
    override env, and a daemon route that records itself.
    """
    import _runtime_pair_preflight as rpp               # noqa: PLC0415
    pin = _rt_pair._pin
    asked: list = []

    def _daemon(*argv, **_k):
        asked.append(list(argv))
        return -1, "", "docker unusable: this test models no daemon"

    monkeypatch.setattr(pin, "_RESOLVED", {})
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)
    monkeypatch.setattr(pin, "_docker", _daemon)
    _rt_pair.assume_matching_runtime_pair(monkeypatch)

    record = rpp.preflight()
    assert record["verdict"] == rpp.RUNTIME_PAIR_MATCH, record
    assert record["required_digest"] == record["found_digest"], record
    assert pin.DIGEST_RE.match(record["required_digest"]), record
    assert asked == [], (
        f"the stated pair still asked this host's docker: {asked}")
    # A resolve that succeeds EXPORTS the identity into os.environ outside
    # monkeypatch; a stated pair must leave nothing behind for later tests.
    assert "VIBEIC_EDA_IMAGE" not in os.environ
