"""Synthetic public controls for the real stage/solve/resume handoff boundary.

No dataset, evaluator, scorer or reference output is opened. Runner calls are
instrumented at the existing subprocess boundary; these are coordinator tests,
not claims that the entire design pipeline passed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import test_declared_route_ai_backup_handoff as fixture
import test_benchmark_program_first_ai_review as review_fixture


ORIGINAL = "module TopModule(input wire a, output wire y); assign y = a; endmodule\n"
CHANGED = ORIGINAL.replace("y = a", "y = ~a")
PROMPT = "Find the bug and fix this module so output y is the inversion of input a, preserving the interface."


@pytest.fixture(autouse=True)
def runtime_pair(monkeypatch):
    fixture._rt_pair.assume_matching_runtime_pair(monkeypatch)


def _backup(tmp_path, monkeypatch):
    dataset, run = tmp_path / "input-prompts", tmp_path / "run"
    fixture._write_dataset(dataset, {"opaque-task": PROMPT})
    real_run = bd.subprocess.run

    def stage_only(argv, **kwargs):
        if not any(Path(str(arg)).name == "vibe_ic_one_shot_runner.py"
                   for arg in argv):
            return real_run(argv, **kwargs)
        project = Path(argv[2])
        if fixture._is_d1_frontdoor(argv):
            fixture._emit_phase1_docs(
                project, fixture._runner_invocation_context(kwargs))
            return SimpleNamespace(returncode=0)
        rtl = project / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "unit.v").write_text(ORIGINAL)
        fixture._write_rtl_gen_report(
            project, "WAIVED", fallback_skill="rtl-repair",
            context=fixture._runner_invocation_context(kwargs))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(bd.subprocess, "run", stage_only)
    assert fixture._solve_after_ai_route(
        "verilogeval-human", str(dataset), str(run)) == 2
    item = fixture._read_jsonl(run / bd._BACKUP_WORKLIST)[0]
    calls = []

    def regate(argv, **kwargs):
        if not any(Path(str(arg)).name == "vibe_ic_one_shot_runner.py"
                   for arg in argv):
            return real_run(argv, **kwargs)
        calls.append(list(argv))
        fixture._write_rtl_gen_report(
            Path(argv[2]), "PASS",
            context=fixture._runner_invocation_context(kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bd.subprocess, "run", regate)
    return dataset, run, item, calls


def _complete(item, *, changed=True):
    project = Path(item["project"])
    if changed:
        (project / "phase2/stage1/rtl/unit.v").write_text(CHANGED)
    outputs = []
    for path in sorted((project / "phase2/stage1/rtl").rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            outputs.append({"relative_path": str(path.relative_to(project / "phase2/stage1/rtl")),
                            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    # The baseline understands neither receipt nor task hash; the value-based
    # controls still reach its existing coordinator and measure actual calls.
    record = {"schema": "vibeic.benchmark.ai_backup_record.v1",
              "id": item["id"], "task_sha256": item.get("task_sha256", "baseline"),
              "prompt_sha256": item["prompt_sha256"],
              "source_sha256": (item.get("public_original_input") or {}).get("source_sha256"),
              "output_manifest": outputs,
              "rtl_sha256": bd._sha256_text(bd._candidate_text(bd._rtl_files(project))),
              "author": {"kind": "AI", "model": "synthetic-author"},
              "oracle_accessed": False,
              "rationale": "The author inspected the public scalar contract and completed the declared handoff.",
              "disposition": "CHANGED" if changed else "NO_CHANGE",
              "prompt_evidence": [{"excerpt": "preserving the interface",
                                   "supports": "The author explicitly preserves the declared interface."}]}
    path = project / "phase2/stage1/ai_backup_author.json"
    path.write_text(json.dumps(record))
    return path, record


@pytest.mark.parametrize("changed", [False, True], ids=["staged-original", "changed-without-completion"])
def test_presence_never_invokes_regate(tmp_path, monkeypatch, changed):
    dataset, run, item, calls = _backup(tmp_path, monkeypatch)
    if changed:
        (Path(item["project"]) / "phase2/stage1/rtl/unit.v").write_text(CHANGED)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == [], "File presence incorrectly invoked the Program worker"
    assert len(fixture._read_jsonl(run / bd._BACKUP_WORKLIST)) == 1
    assert fixture._read_jsonl(run / bd._REVIEW_WORKLIST) == []


@pytest.mark.parametrize("field", ["id", "task_sha256", "prompt_sha256", "source_sha256",
                                  "output_manifest", "author", "prompt_evidence"])
def test_incomplete_or_stale_completion_remains_pending(tmp_path, monkeypatch, field):
    dataset, run, item, calls = _backup(tmp_path, monkeypatch)
    path, record = _complete(item, changed=False)
    record.pop(field)
    path.write_text(json.dumps(record))
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == [], f"Invalid completion ({field}) invoked the Program worker"
    assert len(fixture._read_jsonl(run / bd._BACKUP_WORKLIST)) == 1


@pytest.mark.parametrize("changed", [True, False], ids=["changed", "explicit-no-change"])
def test_completed_backup_is_consumed_once_and_still_needs_review(tmp_path, monkeypatch, changed):
    dataset, run, item, calls = _backup(tmp_path, monkeypatch)
    _, record = _complete(item, changed=changed)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 1
    assert calls[0][calls[0].index("--entry-step") + 1] == "2"
    assert calls[0][calls[0].index("--exit-step") + 1] == "4"
    task = fixture._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert fixture._read_jsonl(run / bd._BACKUP_WORKLIST) == []
    assert task["rtl_sha256"] == record["rtl_sha256"]
    assert task["candidate_origin"] == "AI_BACKUP"
    assert task["backup_provenance"]["author_record"]["output_manifest"] == record["output_manifest"]
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert len(calls) == 1
    assert json.loads((run / "solve_report.json").read_text())["results"][0]["accepted"] is False


def test_output_changed_after_completion_does_not_run(tmp_path, monkeypatch):
    dataset, run, item, calls = _backup(tmp_path, monkeypatch)
    _complete(item)
    (Path(item["project"]) / "phase2/stage1/rtl/unit.v").write_text(ORIGINAL)
    assert bd.cmd_resume("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []


def _public_task(tmp_path, context=None):
    project, run = tmp_path / "project", tmp_path / "run"
    prompt = "Optimize the supplied module while preserving its behavior and interface."
    if context is None:
        context = {"rtl/unit.v": ORIGINAL}
    if not context:
        prompt = "Generate a module with output y equal to the inversion of input a."
    record = {"id": "opaque-task", "input": {"prompt": prompt, "context": context}}
    bio.stage("cvdp", {"id": record["id"], "record": record}, project)
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "unit.v").write_text(CHANGED)
    task = bd._make_ai_review_task(record["id"], project,
        {"ok": True, "completion": CHANGED, "rtl_gen": "BOUNDARY_CONTROL_ONLY"},
        {"nature": "optimization" if context else "spec_generation",
         "route": "plugin_loop", "source": "synthetic-public"},
        1, run, "PROGRAM")
    return project, task


def test_public_original_and_candidate_have_distinct_readable_roles(tmp_path):
    project, task = _public_task(tmp_path)
    # Probe only what the actual handoff permits an independent reader to see.
    visible = [Path(p).read_text() for p in task.get("public_original_input_paths", [])]
    assert (ORIGINAL in visible, CHANGED in visible) == (True, False)
    assert bd._candidate_text([Path(p) for p in task["rtl_paths"]]) == CHANGED
    assert task["program_verification"]["functional_confirmation_required"] is True


def test_public_dependency_paths_survive_stage_and_review(tmp_path):
    context = {"rtl/unit.v": '`include "left/defs.vh"\n' + ORIGINAL,
               "rtl/left/defs.vh": "`define PUBLIC_LEFT 1\n",
               "rtl/right/defs.vh": "`define PUBLIC_RIGHT 2\n"}
    project, task = _public_task(tmp_path, context)
    visible = {Path(p).relative_to(project / "input/public_original/files").as_posix():
               Path(p).read_text() for p in task.get("public_original_input_paths", [])}
    assert visible == context
    assert (project / "input/rtl/left/defs.vh").read_text() != (
        project / "input/rtl/right/defs.vh").read_text()


@pytest.mark.parametrize("mutation", ["intact", "bytes", "missing", "task", "prompt", "allowlist"])
def test_changed_original_is_rejected_at_review_consumer(tmp_path, mutation):
    project, task = _public_task(tmp_path)
    review = {"schema": bd._AI_REVIEW_SCHEMA, "id": task["id"],
              "prompt_sha256": task["prompt_sha256"], "rtl_sha256": task["rtl_sha256"],
              "source_sha256": (task.get("public_original_input") or {}).get("source_sha256"),
              "reviewer": {"kind": "AI", "model": "synthetic-reviewer"},
              "blind": {"oracle_accessed": False},
              "routing": {"verdict": "AGREE", "ai_nature": "optimization"},
              "semantic_review": {"verdict": "PASS", "findings": [],
                                  "rationale": "Synthetic consumer boundary control."}}
    # A pre-existing functional PASS isolates provenance from simulator policy.
    task["program_verification"]["functional_confirmation_required"] = False
    task["program_verification"]["functional_evidence"] = "PASS"
    if mutation in {"bytes", "missing"}:
        path = Path((task.get("public_original_input_paths") or [project / "input/rtl/unit.v"])[0])
        if mutation == "bytes":
            path.write_text(CHANGED)
        else:
            path.unlink()
    elif mutation in {"task", "prompt"}:
        original = task.setdefault("public_original_input", {})
        original["id" if mutation == "task" else "prompt_sha256"] = "sibling-task"
    elif mutation == "allowlist":
        task.setdefault("public_original_input_paths", []).append(str(project / "phase2/stage1/rtl/unit.v"))
    review_fixture._write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == ("ACCEPTED" if mutation == "intact" else "REJECTED"), verdict
    if mutation != "intact":
        assert any("PUBLIC_INPUT" in reason for reason in verdict["reasons"]), verdict


def test_generation_does_not_invent_original_from_candidate(tmp_path):
    _, task = _public_task(tmp_path, {})
    assert task["public_original_input"]["status"] == "NOT_PROVIDED"
    assert task["public_original_input_paths"] == []


def test_public_stage_never_reads_non_input_values(tmp_path):
    class PublicOnly(dict):
        def get(self, key, default=None):
            assert key in {"input", "id"}, f"non-input role was read: {key}"
            return super().get(key, default)
    record = PublicOnly(id="opaque-task", input={"prompt": PROMPT,
                        "context": {"rtl/unit.v": ORIGINAL}}, output=object(), harness=object())
    project = tmp_path / "project"
    staged = bio.stage("cvdp", {"id": "opaque-task", "record": record}, project)
    assert [row["relative_path"] for row in staged["public_original_input"]["files"]] == ["rtl/unit.v"]


@pytest.mark.parametrize("path", ["../escape.v", "/absolute.v"])
def test_public_role_does_not_authorize_path_escape(tmp_path, path):
    with pytest.raises(ValueError, match="PUBLIC_INPUT_PATH_INVALID"):
        _public_task(tmp_path, {path: ORIGINAL})
