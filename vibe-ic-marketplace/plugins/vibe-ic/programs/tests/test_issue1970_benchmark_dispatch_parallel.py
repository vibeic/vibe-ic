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
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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


def _phase_record() -> dict:
    return {
        "phase1_routing": {},
        "phase2_solving": {},
        "phase3_verifying": {},
        "phase4_debugging": {},
    }


def _install_common_fakes(monkeypatch) -> None:
    monkeypatch.setattr(bes, "audit", lambda _root: {
        "verdict": "PASS", "findings": []})
    monkeypatch.setattr(bd, "_completeness_adapters", lambda: {})
    monkeypatch.setattr(fpa, "rtl_present_at_input", lambda _project: False)
    monkeypatch.setattr(fpa, "attribute", lambda *_a, **_k: _phase_record())
    monkeypatch.setattr(fpa, "summarize", lambda _results: {})
    monkeypatch.setattr(
        tnr, "classify_task_nature",
        lambda *_a, **_k: {"nature": "fixture", "entry_nature": "fixture",
                           "plugin_entry": {}})
    monkeypatch.setattr(tnr, "NATURE_ENTRY", {
        "fixture": {"entry_step": "D1", "default_evidence": "RTL_SIM"}})
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

    monkeypatch.setattr(bd, "_prepare_general_solve_run", prepare)
    monkeypatch.setattr(
        bio, "problems",
        lambda _fmt, _dataset: [{"id": "p1"}, {"id": "p2"}])

    def stage(_fmt, problem, project):
        prompt = project / "input" / "phase1_prompt.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        text = f"Design {problem['id']} with an input and an output.\n"
        prompt.write_text(text)
        return {"prompt_chars": len(text)}

    monkeypatch.setattr(bio, "stage", stage)
    monkeypatch.setattr(
        bio, "collect",
        lambda *_a, **_k: {"ok": False, "reason": "fixture-no-candidate"})

    interval_lock = threading.Lock()

    def fake_run(argv, *args, **kwargs):
        project = Path(argv[2])
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
        backups.append({
            "id": pid,
            "project": str(project),
            "prompt_sha256": bd._sha256_text(prompt.read_text()),
        })
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


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


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

    assert bd.cmd_solve(
        "rtllm", str(dataset), str(serial), jobs=1) == 1
    assert bd.cmd_solve(
        "rtllm", str(dataset), str(parallel), jobs=2) == 1

    assert _overlap(intervals["parallel:p1"], intervals["parallel:p2"])
    assert not _overlap(intervals["serial:p1"], intervals["serial:p2"])
    serial_report = json.loads((serial / "solve_report.json").read_text())
    parallel_report = json.loads((parallel / "solve_report.json").read_text())
    assert [row["id"] for row in parallel_report["results"]] == ["p1", "p2"]
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
    interval_lock = threading.Lock()

    def fake_run(argv, *args, **kwargs):
        pid = Path(argv[2]).name
        started = time.monotonic()
        time.sleep(0.18 if pid == "p1" else 0.06)
        finished = time.monotonic()
        with interval_lock:
            intervals[pid] = (started, finished)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    monkeypatch.setattr(
        bio, "collect",
        lambda *_a, **_k: {"ok": False, "reason": "fixture gate rejection"})

    assert bd.cmd_resume("rtllm", "/unused", str(run), jobs=2) == 2
    assert _overlap(intervals["p1"], intervals["p2"])
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

    assert bd.cmd_solve("rtllm", str(dataset), str(run), jobs=2) == 1
    results = json.loads((run / "solve_report.json").read_text())["results"]
    assert [row["id"] for row in results] == ["p1", "p2"]
    assert results[0]["worker_status"] == "ERROR"
    assert results[0]["rc"] is None
    assert "worker_status" not in results[1]
    assert results[1]["rc"] == 0

    monkeypatch.setattr(
        bd.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0))
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

    assert bd.cmd_solve(
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
