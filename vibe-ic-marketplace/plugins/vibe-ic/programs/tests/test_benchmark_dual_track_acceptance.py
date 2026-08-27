#!/usr/bin/env python3
"""A PROGRAM candidate is not scoreable until a blind AI rail agrees."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd                         # noqa: E402
import benchmark_io_adapter as bio                      # noqa: E402


ROUTING = {
    "nature": "spec_generation",
    "route": "SPEC_TO_RTL",
    "source": "no_context_heuristic",
    "needs_ai_parse": True,
}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "input" / "phase1_prompt.md").write_text(
        "Design module dut with input a and output y; assign y = a.\n")
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{
            "name": "rtl_gen", "status": "PASS", "detail": "fixture",
            "extras": {"deterministic_generator": "fixture_emitter"},
        }],
    }))
    return project


def _task(tmp_path: Path) -> tuple[Path, dict, dict]:
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    return run, task, got


def _valid_review(task: dict) -> dict:
    return {
        "schema": bd._AI_REVIEW_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "reviewer": {"kind": "AI", "model": "test-review-model"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "AGREE", "ai_nature": "spec_generation"},
        "semantic_review": {
            "verdict": "PASS", "findings": [],
            "rationale": "Ports and combinational behavior match the prompt.",
        },
    }


def _write_review(task: dict, review: dict) -> None:
    path = Path(task["review_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review))


def _solve_report(run: Path, task: dict) -> None:
    result = {
        "id": task["id"], "ok": True, "candidate_ready": True,
        "accepted": False, "entry": "D1", "evidence": "RTL_SIM",
        "exit": "8", "routing_verdict": ROUTING,
        "candidate_origin": "PROGRAM", "ai_repair_required": False,
        "awaiting_ai": True, "awaiting_ai_review": True,
        "awaiting_ai_backup": False,
    }
    (run / "solve_report.json").write_text(json.dumps({
        "bench": "rtllm", "format": "rtllm", "total": 1,
        "solved": 1, "accepted": 0,
        "acceptance_policy": {"required": True},
        "results": [result],
    }))
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    bd._write_jsonl(run / bd._BACKUP_WORKLIST, [])


def test_valid_blind_ai_review_is_hash_bound_and_accepted(tmp_path):
    run, task, got = _task(tmp_path)
    _solve_report(run, task)
    _write_review(task, _valid_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["accepted_ids"] == ["p1"]
    response = json.loads(Path(task["response_path"]).read_text())
    assert response["completion"] == got["completion"]
    solve = json.loads((run / "solve_report.json").read_text())
    item = solve["results"][0]
    route_review = item["phases"]["phase1_routing"][
        "ai_decided_routing_review"]
    assert route_review["actor"] == "test-review-model"
    assert route_review["authority"] == "FINAL_SEMANTIC_AUTHORITY"
    assert route_review["status"] == "ACCEPTED"
    assert route_review["verdict"] == "AGREE"
    assert item["phases"]["phase3_verifying"]["ai_semantic_review"][
        "verdict"] == "PASS"
    assert solve["four_phase_summary"]["phase1_ai_review_models"] == {
        "test-review-model": 1}
    assert solve["four_phase_summary"]["phase2_candidate_origin"] == {
        "PROGRAM": 1}
    assert solve["four_phase_summary"]["phase3_ai_semantic_verdict"] == {
        "PASS": 1}
    bd._require_dual_track_acceptance(run)

    # A post-review byte change invalidates both the review and score gate.
    Path(task["rtl_paths"][0]).write_text("module dut(); endmodule\n")
    with pytest.raises(SystemExit, match="dual-track acceptance BLOCKED"):
        bd._require_dual_track_acceptance(run)


def test_missing_review_stays_pending_and_writes_no_response(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["pending_review"] == 1
    assert not Path(task["response_path"]).exists()


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda r: r["reviewer"].update(model="unknown"), "name the AI model"),
        (lambda r: r["blind"].update(oracle_accessed=True), "must be false"),
        (lambda r: r["routing"].update(verdict="DISAGREE"),
         "AGREE or OVERRIDE_PROGRAM"),
        (lambda r: r["semantic_review"].update(verdict="MAYBE"),
         "PASS or FAIL"),
        (lambda r: r.update(rtl_sha256="0" * 64), "stale or wrong"),
    ],
)
def test_review_contract_rejects_fake_or_disagreeing_ai_rail(
        tmp_path, mutate, expected):
    _, task, _ = _task(tmp_path)
    review = copy.deepcopy(_valid_review(task))
    mutate(review)
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any(expected in reason for reason in verdict["reasons"])


def test_complete_label_cannot_omit_a_problem(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    _write_review(task, _valid_review(task))
    (run / bd._ACCEPTANCE_REPORT).write_text(json.dumps({
        "schema": bd._ACCEPTANCE_SCHEMA, "status": "COMPLETE",
        "accepted": 0, "total": 1, "accepted_ids": [],
    }))
    with pytest.raises(SystemExit, match="does not account for every"):
        bd._require_dual_track_acceptance(run)


def _override_review(task: dict) -> dict:
    review = _valid_review(task)
    review["routing"] = {
        "verdict": "OVERRIDE_PROGRAM",
        "ai_nature": "existing_rtl_transform",
    }
    review["override"] = {
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The requested behavior is a direct combinational path.",
        }],
        "explanation": (
            "The prose explicitly defines direct combinational behavior, so "
            "the AI route supersedes the program's generic generation label."),
        "program_limitation": (
            "The structural router treats every prompt-only task as generation."),
        "proposed_program_enhancement": {
            "component": "task_nature_route",
            "proposal": "Recognize explicit transform semantics before fallback.",
            "regression_fixture": "prompt-only direct assignment fixture",
        },
    }
    return review


def test_ai_can_override_program_with_prompt_bound_evidence(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    _write_review(task, _override_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["review_outcomes"][0]["routing_verdict"] == \
        "OVERRIDE_PROGRAM"
    enhancement = bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)
    assert len(enhancement) == 1
    assert enhancement[0]["blocking_acceptance"] is False
    assert enhancement[0]["verified_prompt_evidence"][0]["excerpt"] == \
        "assign y = a"


def test_unexplained_program_override_is_rejected(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _override_review(task)
    review["override"]["prompt_evidence"] = []
    review["override"]["explanation"] = "AI disagrees."
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("prompt-bound evidence" in r for r in verdict["reasons"])


def test_detailed_ai_interpretation_can_substitute_for_a_literal_excerpt(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _override_review(task)
    review["override"]["prompt_evidence"] = []
    review["override"]["explanation"] = (
        "The request describes a continuously observable output whose value "
        "tracks the input without any clock, reset, enable, latency, storage, "
        "or transaction boundary. Those omissions are semantically material: "
        "adding sequential state changes when the output becomes visible and "
        "therefore implements a different interface contract from the prose.")
    _write_review(task, review)
    assert bd._validate_ai_review(task)["status"] == "ACCEPTED"


def test_semantic_disagreement_converges_to_repair_not_deadlock(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    review = _valid_review(task)
    review["semantic_review"] = {
        "verdict": "FAIL",
        "findings": [{"issue": "output is registered but prompt requires direct"}],
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The prompt explicitly requests a direct assignment.",
        }],
        "rationale": (
            "The candidate adds state that the prompt never requests, so its "
            "observable timing differs from the described combinational behavior."),
    }
    _write_review(task, review)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["review_outcomes"][0]["status"] == "REPAIR_REQUIRED"
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED"
    assert "fresh AI review" in repairs[0]["required_next"]
    assert not Path(task["response_path"]).exists()
    assert len(bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)) == 1


def test_semantic_override_without_evidence_or_explanation_is_rejected(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _valid_review(task)
    review["semantic_review"] = {
        "verdict": "FAIL", "findings": [{"issue": "AI disagrees"}],
        "rationale": "This output looks wrong.",
    }
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("prompt-bound evidence" in r for r in verdict["reasons"])
