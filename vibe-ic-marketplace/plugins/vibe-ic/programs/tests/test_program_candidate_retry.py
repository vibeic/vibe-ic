"""A Program upgrade may replay signed input, never manufacture AI authority."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_benchmark_program_first_ai_review as fx

bd = fx.bd
pytestmark = fx._NEEDS_SIMULATOR


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity():
    # The pre-fix control reaches the OLD coordinator; no missing API failure.
    helper = getattr(bd, "_program_retry_identity", None)
    return helper() if helper else {"source_sha256": "0" * 64}


def _case(tmp_path, monkeypatch, *, reviewed=False, exit_step="2"):
    run = tmp_path / "run"
    project = fx._project(tmp_path)
    rtl = project / "phase2/stage1/rtl/dut.v"
    rtl.write_text(rtl.read_text().replace("y = a", "y = ~a"))
    parent = bd._make_ai_review_task("p1", project,
        fx.bio.collect("rtllm", "p1", project), fx.ROUTING, 0, run, "PROGRAM")
    fx._write_review(parent, fx._proven_fail_review(parent))
    verdict = bd._validate_ai_review(parent)
    assert verdict["status"] == "REPAIR_REQUIRED"
    challenge = verdict["verified_challenge"]
    rtl.write_text(rtl.read_text().replace("y = ~a", "y = a"))
    signed = fx._write_ai_repair_record(run, parent, challenge)
    preserved = bd._archive_candidate("p1", project,
        {"id": "p1", "ok": True, "completion": rtl.read_text()}, run, "AI_REPAIR_INPUT")
    fx._solve_report(run, parent)
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"][0]["exit"] = exit_step
    (run / "solve_report.json").write_text(json.dumps(solve))
    state = {"mode": "old", "calls": [], "on_run": None, "rc": 0}
    real_run = bd.subprocess.run

    def boundary(argv, **kwargs):
        if not any(str(a).endswith("vibe_ic_one_shot_runner.py") for a in argv):
            return real_run(argv, **kwargs)
        state["calls"].append(list(argv))
        candidate = Path(argv[2])
        current = candidate / "phase2/stage1/rtl/dut.v"
        if state["mode"] == "interrupt":
            raise KeyboardInterrupt("controlled runner interruption")
        if state["mode"] == "failure":
            return SimpleNamespace(returncode=1)
        if state["mode"] in {"old", "still_transforms"}:
            current.write_text(current.read_text().replace("y = a", "y = 1'b0"))
        report = candidate / "reports/orchestrator/phase2_one_shot.json"
        report.write_text(json.dumps({"verdict": "FAIL" if state["rc"] else "PASS",
            "steps": [{"name": "rtl_gen", "status": "SKIPPED-BY-ENTRY"}]}))
        if state["on_run"]:
            state["on_run"](candidate)
        assert kwargs["env"]["OMP_NUM_THREADS"] == "1"
        return SimpleNamespace(returncode=state["rc"])

    monkeypatch.setattr(bd.subprocess, "run", boundary)
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 2
    task = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert task["candidate_origin"] == "AI_REPAIR"
    assert task["rtl_sha256"] != signed["repaired_rtl_sha256"]
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 2
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert "AI_REPAIR_FINAL_PROVENANCE_REQUIRED" in {r["status"] for r in repairs}
    if reviewed:
        fx._write_review(task, fx._proven_fail_review(task))
    request = {
        "schema": "vibeic.benchmark.program_retry.v1", "id": task["id"],
        "task_sha256": bd._sha256_text(json.dumps(task, ensure_ascii=False, sort_keys=True)),
        "prompt_sha256": task["prompt_sha256"], "rtl_sha256": task["rtl_sha256"],
        "repair_record_sha256": _hash(task["repair_provenance"]["path"]),
        "input_manifest_path": preserved["manifest_path"],
        "input_manifest_sha256": _hash(preserved["manifest_path"]),
        "input_rtl_sha256": preserved["rtl_sha256"],
        "program_identity": _identity(),
        "reason": "Retry the preserved signed input after upgrading the generic Program transform.",
    }
    if reviewed:
        request.update(review_sha256=_hash(task["review_path"]),
                       challenge_sha256=_hash(task["challenge_path"]))
    path = run / "program_retry_request.json"
    path.write_text(json.dumps(request))
    state.update(mode="fixed", calls=[])
    return run, task, path, request, state


def _resume(run, request):
    kwargs = ({"program_retry": str(request)}
              if "program_retry" in inspect.signature(bd.cmd_resume).parameters else {})
    return bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1, **kwargs)


def _protected(run, task):
    paths = [run / bd._REVIEW_WORKLIST, run / "solve_report.json",
             Path(task["repair_provenance"]["path"]), Path(task["prompt_path"]),
             *map(Path, task["working_rtl_paths"]), *map(Path, task["rtl_paths"])]
    return {str(p): p.read_bytes() for p in paths}


def test_retry_replaces_frozen_output_from_signed_input_then_normal_review_accepts(tmp_path, monkeypatch):
    run, old, path, request, state = _case(tmp_path, monkeypatch, reviewed=True)
    old_signature = Path(old["repair_provenance"]["path"]).read_bytes()
    old_rtl = [Path(p).read_bytes() for p in old["rtl_paths"]]
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    # Non-vacuous pre-fix failure observes the old, transformed frozen hash.
    assert new["rtl_sha256"] == request["input_rtl_sha256"], new["rtl_sha256"]
    assert new["rtl_sha256"] != old["rtl_sha256"]
    assert bd._validate_ai_review(new)["status"] == "PENDING"
    assert not Path(new["review_path"]).exists()
    assert not Path(new["challenge_path"]).exists()
    assert not Path(new["response_path"]).exists()
    assert new["repair_provenance"] == old["repair_provenance"]
    assert Path(old["repair_provenance"]["path"]).read_bytes() == old_signature
    assert [Path(p).read_bytes() for p in old["rtl_paths"]] == old_rtl
    assert new["program_candidate_snapshot"] == old["program_candidate_snapshot"]
    assert new["repair_parent_candidate_snapshot"] == old["repair_parent_candidate_snapshot"]
    assert {c["sha256"] for c in old["verification_challenges"]} <= {c["sha256"] for c in new["verification_challenges"]}
    assert _hash(old["challenge_path"]) in {c["sha256"] for c in new["verification_challenges"]}
    archive = Path(new["program_retry"]["archive_path"])
    assert (archive / "prior_review.json").read_bytes() == Path(old["review_path"]).read_bytes()
    assert (archive / "prior_project/phase2/stage1/rtl/dut.v").read_bytes() == old_rtl[0]
    assert (archive / "staged_project/reports/orchestrator/phase2_one_shot.json").is_file()
    assert bd._read_jsonl(archive / "prior_state" / bd._REVIEW_WORKLIST)[0] == old
    argv = state["calls"][0]
    assert argv[argv.index("--entry-step") + 1] == "2"
    assert argv[argv.index("--exit-step") + 1] == "2"
    fx._write_review(new, fx._valid_review(new))
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 0
    accepted = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert accepted["accepted_ids"] == [old["id"]]
    assert json.loads(Path(new["response_path"]).read_text())["completion"] == Path(new["rtl_paths"][0]).read_text()


def test_plain_resume_keeps_transformed_output_and_requires_real_final_signature(tmp_path, monkeypatch):
    run, old, _, _, state = _case(tmp_path, monkeypatch)
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old
    assert state["calls"] == []
    assert bd._refresh_final_repair_provenance(old)[0] is None


@pytest.mark.parametrize("field", ["task_sha256", "prompt_sha256", "rtl_sha256", "repair_record_sha256",
                                  "input_manifest_sha256", "input_rtl_sha256", "program_identity", "schema", "reason"])
def test_stale_request_refuses_before_mutation(tmp_path, monkeypatch, field):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    request[field] = "stale"
    path.write_text(json.dumps(request))
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []
    assert not (run / "program_retries").exists()


@pytest.mark.parametrize("drift", ["working", "signature", "input", "prompt", "parent", "challenge",
                                  "accepted", "accepted_ledger", "published", "occupied", "occupied_review",
                                  "external", "symlink"])
def test_evidence_and_state_refusals_preserve_sources(tmp_path, monkeypatch, drift):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    if drift in {"working", "signature", "prompt", "parent", "challenge", "input"}:
        target = {"working": old["working_rtl_paths"][0], "signature": old["repair_provenance"]["path"],
                  "prompt": old["prompt_path"], "parent": old["program_candidate_snapshot"]["rtl_paths"][0],
                  "challenge": old["verification_challenges"][0]["path"],
                  "input": json.loads(Path(request["input_manifest_path"]).read_text())["rtl_paths"][0]}[drift]
        with Path(target).open("a") as stream:
            stream.write("\nchanged\n")
    elif drift == "accepted":
        solve = json.loads((run / "solve_report.json").read_text())
        solve["results"][0]["accepted"] = True
        (run / "solve_report.json").write_text(json.dumps(solve))
    elif drift == "published":
        Path(old["response_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(old["response_path"]).write_text("published")
    elif drift == "accepted_ledger":
        acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
        acceptance["accepted_ids"] = [old["id"]]
        (run / bd._ACCEPTANCE_REPORT).write_text(json.dumps(acceptance))
    elif drift in {"occupied", "occupied_review"}:
        key = "program-retry-" + bd._sha256_text(path.read_text())
        occupied = (run / "ai_verification_challenges/p1" / key / "challenge_tb.sv"
                    if drift == "occupied" else run / "ai_reviews/p1" / (key + ".json"))
        occupied.parent.mkdir(parents=True, exist_ok=True)
        occupied.write_text("already authored")
    elif drift == "external":
        outside = tmp_path / "outside.json"
        outside.write_bytes(Path(request["input_manifest_path"]).read_bytes())
        request["input_manifest_path"] = str(outside)
        path.write_text(json.dumps(request))
    elif drift == "symlink":
        linked = run / "linked_request.json"
        linked.symlink_to(path)
        path = linked
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []


@pytest.mark.parametrize("mode", ["failure", "source_drift", "program_drift", "output_symlink", "interrupt", "promotion_interrupt"])
def test_staged_failure_and_interruption_are_safe(tmp_path, monkeypatch, mode):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    before = _protected(run, old)
    if mode == "source_drift":
        def edit(_):
            Path(old["working_rtl_paths"][0]).write_text("owner edit\n")
        state["on_run"] = edit
    elif mode == "program_drift":
        def upgrade(_):
            monkeypatch.setattr(bd, "_program_retry_identity", lambda: {"changed": True})
        state["on_run"] = upgrade
    elif mode == "output_symlink":
        def escape(staged):
            (staged / "escaped").symlink_to(tmp_path / "outside")
        state["on_run"] = escape
    elif mode == "promotion_interrupt":
        real = Path.rename
        def interrupted(src, target):
            if src.name == "promotion_project":
                raise OSError("controlled promotion interruption")
            return real(src, target)
        monkeypatch.setattr(Path, "rename", interrupted)
    else:
        state["mode"] = mode
    if mode == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            _resume(run, path)
    else:
        assert _resume(run, path) == 2
    assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0] == old
    assert not Path(old["response_path"]).exists()
    if mode == "source_drift":
        assert Path(old["working_rtl_paths"][0]).read_text() == "owner edit\n"
    elif mode != "promotion_interrupt":
        assert _protected(run, old) == before
    if mode in {"interrupt", "promotion_interrupt"}:
        task_bytes = (run / bd._REVIEW_WORKLIST).read_bytes()
        assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
        assert (run / bd._REVIEW_WORKLIST).read_bytes() == task_bytes


def test_still_transforming_program_keeps_original_final_provenance_refusal(tmp_path, monkeypatch):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    state["mode"] = "still_transforms"
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["rtl_sha256"] == old["rtl_sha256"]
    assert new["repair_provenance"] == old["repair_provenance"]
    assert bd._refresh_final_repair_provenance(new)[0] is None
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert "AI_REPAIR_FINAL_PROVENANCE_REQUIRED" in {r["status"] for r in bd._read_jsonl(run / bd._REPAIR_WORKLIST)}


def test_normal_internal_links_and_declared_exit_predicate_are_preserved(tmp_path, monkeypatch):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    steps = Path(old["project"]) / "steps"
    steps.mkdir()
    (steps / "report").symlink_to("../reports/orchestrator/phase2_one_shot.json")
    (steps / "optional").symlink_to("../reports/not-yet-emitted.json")
    state["rc"] = 1
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["rtl_sha256"] != old["rtl_sha256"]
    assert new["program_verification"]["runner_rc"] == 1
    assert new["program_verification"]["functional_confirmation_required"] is True
    assert os.readlink(steps / "optional") == "../reports/not-yet-emitted.json"
    assert bd._validate_ai_review(new)["status"] == "PENDING"


def test_coordinator_lock_prevents_program_retry(tmp_path, monkeypatch):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    before = _protected(run, old)
    with bd._run_root_coordinator_lock(run, "owner"):
        assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []


@pytest.mark.parametrize("malformed", [[], None, {"schema": "vibeic.benchmark.program_retry.v1", "id": []}])
def test_malformed_requests_refuse_without_traceback(tmp_path, monkeypatch, malformed):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    path.write_text(json.dumps(malformed))
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []


def test_program_retry_capture_routes_to_shared_coordinator():
    routing = json.loads((bd.HARNESS / "CAPTURE_ROUTING.json").read_text())
    assert routing["steps"]["benchmark.program_retry"]["bucket_A_program"] == "programs/benchmark_dispatch.py"


@pytest.mark.parametrize("marker", ["complete.json", "failed.json"])
def test_malformed_terminal_marker_cannot_hide_interruption(tmp_path, monkeypatch, marker):
    run, old, path, _, state = _case(tmp_path, monkeypatch)
    state["mode"] = "interrupt"
    with pytest.raises(KeyboardInterrupt):
        _resume(run, path)
    archive = next((run / "program_retries/p1").iterdir())
    (archive / marker).write_text("{}")
    before = _protected(run, old)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert _protected(run, old) == before


def test_automatic_input_snapshot_matches_signed_pre_gate_bytes(tmp_path, monkeypatch):
    run, old, _, request, _ = _case(tmp_path, monkeypatch)
    preserved = old["repair_input_candidate_snapshot"]
    assert bd._validate_candidate_snapshot(preserved, old["id"]) == []
    assert preserved["rtl_sha256"] == request["input_rtl_sha256"]
    assert preserved["rtl_sha256"] == old["repair_provenance"]["repaired_rtl_sha256"]


def test_unchanged_program_cannot_retry_again(tmp_path, monkeypatch):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    assert _resume(run, path) == 2
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["rtl_sha256"] != old["rtl_sha256"]
    request.update(task_sha256=bd._sha256_text(json.dumps(new, ensure_ascii=False, sort_keys=True)),
                   rtl_sha256=new["rtl_sha256"], reason="A second retry with unchanged installed Program sources is not an upgrade.")
    path.write_text(json.dumps(request))
    before = _protected(run, new)
    state["calls"] = []
    assert _resume(run, path) == 2
    assert _protected(run, new) == before
    assert state["calls"] == []


@pytest.mark.parametrize("malformed", ["response_alias", "input_file_count"])
def test_exact_path_and_file_mapping_preflight(tmp_path, monkeypatch, malformed):
    run, old, path, request, state = _case(tmp_path, monkeypatch)
    if malformed == "response_alias":
        published = Path(old["response_path"])
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_text("already published")
        old["response_path"] = str(run / "different_response.json")
    else:
        old.pop("repair_input_candidate_snapshot", None)  # legacy manifest path
        candidate = json.loads(Path(request["input_manifest_path"]).read_text())
        original = Path(candidate["rtl_paths"][0]).read_text()
        assert original.endswith("\n")
        split = run / "split_input"
        split.mkdir()
        (split / "first.v").write_text(original[:-1])
        (split / "second.v").write_text("")
        candidate["rtl_paths"] = [str(split / "first.v"), str(split / "second.v")]
        manifest = split / "manifest.json"
        candidate["manifest_path"] = str(manifest)
        manifest.write_text(json.dumps(candidate))
        assert bd._validate_candidate_snapshot(candidate, old["id"]) == []
        request.update(input_manifest_path=str(manifest), input_manifest_sha256=_hash(manifest))
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [old])
    request["task_sha256"] = bd._sha256_text(json.dumps(old, ensure_ascii=False, sort_keys=True))
    path.write_text(json.dumps(request))
    before = _protected(run, old)
    assert _resume(run, path) == 2
    assert _protected(run, old) == before
    assert state["calls"] == []
    assert not (run / "program_retries").exists()
