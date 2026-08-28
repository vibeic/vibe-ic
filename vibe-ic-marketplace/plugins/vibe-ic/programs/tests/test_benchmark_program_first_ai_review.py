#!/usr/bin/env python3
"""Program First is scoreable only after evidence-bound blind AI review."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _write_direct_assignment_challenge(task: dict) -> dict:
    source = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  dut candidate(.a(a), .y(y));
  initial begin
    a = 1'b0; #1;
    if (y !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    a = 1'b1; #1;
    if (y !== 1'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""
    path = Path(task["challenge_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The test drives both input values and checks direct equality.",
        }],
        "expected_behavior": "Output y must equal input a combinationally.",
        "rationale": (
            "The prompt states a direct assignment, so two exhaustive scalar "
            "vectors establish whether the candidate implements that exact "
            "observable combinational behavior without relying on any oracle."),
    }


def _proven_fail_review(task: dict) -> dict:
    review = _valid_review(task)
    review["semantic_review"] = {
        "verdict": "FAIL",
        "findings": [{"issue": "output does not directly track input"}],
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The prompt explicitly requests a direct assignment.",
        }],
        "rationale": (
            "The candidate inverts the input instead of implementing the direct "
            "assignment stated by the prompt; the attached exhaustive one-bit "
            "test demonstrates the mismatch without any benchmark oracle."),
    }
    review["verification_test"] = _write_direct_assignment_challenge(task)
    return review


def _write_ai_repair_record(run: Path, task: dict, challenge: dict) -> dict:
    repaired_hash = bd._sha256_text(bd._candidate_text(
        bd._rtl_files(Path(task["project"]))))
    record = {
        "schema": bd._AI_REPAIR_RECORD_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "parent_rtl_sha256": task["rtl_sha256"],
        "repaired_rtl_sha256": repaired_hash,
        "challenge_sha256": challenge["sha256"],
        "author": {"kind": "AI", "model": "test-repair-model"},
        "oracle_accessed": False,
        "rationale": (
            "Replace the proven inversion with the prompt-required direct "
            "assignment, then re-run the immutable challenge."),
    }
    path = bd._repair_record_path(run, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


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
        "acceptance_policy": {
            "required": True,
            "review_task_schema": bd._REVIEW_TASK_SCHEMA,
            "review_schema": bd._AI_REVIEW_SCHEMA,
        },
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
    bd._require_program_first_ai_acceptance(run)

    # A post-review byte change invalidates both the review and score gate.
    Path(task["rtl_paths"][0]).write_text("module dut(); endmodule\n")
    with pytest.raises(SystemExit, match="Program First.*acceptance BLOCKED"):
        bd._require_program_first_ai_acceptance(run)


def test_supplied_rtl_accepts_only_explicit_step2_reentry(tmp_path):
    project = _project(tmp_path)
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{
            "name": "rtl_gen", "status": "SKIPPED-BY-ENTRY",
            "detail": "run declared --entry-step 2",
        }],
    }))

    ordinary = bio.collect("rtllm", "p1", project)
    supplied = bio.collect("rtllm", "p1", project, supplied_rtl=True)

    assert ordinary["ok"] is False
    assert supplied["ok"] is True
    assert supplied["rtl_gen"] == "SKIPPED-BY-ENTRY"
    assert supplied["supplied_rtl"] is True


def test_ai_repair_reenters_at_validation_without_regeneration(
        tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    working_rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))

    # First resume proves the Program candidate wrong and emits the repair task.
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED"
    assert repairs[0]["challenge_result"]["status"] == "FAIL"

    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    _write_ai_repair_record(
        run, task, bd._validate_ai_review(task)["verified_challenge"])
    seen = []
    real_run = bd.subprocess.run

    def fake_run(argv, *args, **kwargs):
        if "vibe_ic_one_shot_runner.py" not in " ".join(str(v) for v in argv):
            return real_run(argv, *args, **kwargs)
        seen.append(argv)
        report = (Path(task["project"]) / "reports" / "orchestrator" /
                  "phase2_one_shot.json")
        report.write_text(json.dumps({
            "verdict": "PASS",
            "steps": [{
                "name": "rtl_gen", "status": "SKIPPED-BY-ENTRY",
                "detail": "run declared --entry-step 2",
            }],
        }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert seen and seen[0][-2:] == ["--entry-step", "2"]
    solve = json.loads((run / "solve_report.json").read_text())
    assert solve["results"][0]["candidate_origin"] == "AI_REPAIR"
    assert solve["results"][0]["candidate_ready"] is True
    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert refreshed["rtl_sha256"] != task["rtl_sha256"]
    assert len(refreshed["verification_challenges"]) == 1

    # The next resume must accept the independently reviewed repair even
    # though rtl_gen correctly remains SKIPPED-BY-ENTRY from re-entry step 2.
    _write_review(refreshed, _valid_review(refreshed))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["accepted_ids"] == ["p1"]
    response = json.loads(Path(refreshed["response_path"]).read_text())
    assert "assign y = a" in response["completion"]
    captures = bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)
    recovery = next(row for row in captures
                    if row["status"] ==
                    "VERIFIED_AI_RECOVERY_READY_FOR_PROGRAM_CAPTURE")
    assert recovery["program_candidate_snapshot"]["rtl_sha256"] == \
        task["rtl_sha256"]
    assert recovery["repaired_candidate_snapshot"]["rtl_sha256"] == \
        refreshed["rtl_sha256"]
    assert recovery["repair_challenge_results"][0]["status"] == "PASS"
    assert recovery["repair_provenance"]["author"]["model"] == \
        "test-repair-model"
    phases = json.loads((run / "solve_report.json").read_text())["results"][0][
        "phases"]
    assert phases["phase4_debugging"]["ai_semantic_repair"]["actor"] == \
        "test-repair-model"


def test_proven_ai_edit_cannot_reenter_without_repair_author_record(
        tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2

    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")

    real_run = bd.subprocess.run

    def must_not_run(argv, *args, **kwargs):
        if "vibe_ic_one_shot_runner.py" in " ".join(str(v) for v in argv):
            raise AssertionError(
                "unattributed AI repair must not enter Program gates")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", must_not_run)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repair = bd._read_jsonl(run / bd._REPAIR_WORKLIST)[0]
    assert repair["status"] == "AI_REPAIR_PROVENANCE_REQUIRED"
    assert repair["repaired_rtl_sha256"] == bd._sha256_text(
        bd._candidate_text([rtl]))
    assert not Path(task["response_path"]).exists()


def test_missing_review_stays_pending_and_writes_no_response(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["pending_review"] == 1
    assert not Path(task["response_path"]).exists()


def test_ai_cannot_edit_program_candidate_before_proving_a_finding(
        tmp_path, monkeypatch):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    Path(task["working_rtl_paths"][0]).write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")

    def must_not_run(*args, **kwargs):
        raise AssertionError("unproven AI edit must not enter Program gates")

    monkeypatch.setattr("subprocess.run", must_not_run)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repair = bd._read_jsonl(run / bd._REPAIR_WORKLIST)[0]
    assert repair["status"] == "UNPROVEN_AI_EDIT_REJECTED"
    assert repair["restore_from"] == task["candidate_snapshot"]["manifest_path"]
    assert not Path(task["response_path"]).exists()


def test_repair_must_pass_the_same_immutable_challenge(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    original = bio.collect("rtllm", "p1", project)
    program_task = bd._make_ai_review_task(
        "p1", project, original, ROUTING, 0, run, "PROGRAM")
    _write_review(program_task, _proven_fail_review(program_task))
    proven = bd._validate_ai_review(program_task)
    assert proven["status"] == "REPAIR_REQUIRED"

    # This edit differs from Program but still fails the exact same a=0/a=1 test.
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = 1'b0; endmodule\n")
    repair_payload = bio.collect("rtllm", "p1", project, supplied_rtl=True)
    repair_task = bd._make_ai_review_task(
        "p1", project, repair_payload, ROUTING, 0, run, "AI_REPAIR",
        verification_challenges=[proven["verified_challenge"]],
        program_candidate=program_task["candidate_snapshot"])
    _write_review(repair_task, _valid_review(repair_task))
    verdict = bd._validate_ai_review(repair_task)
    assert verdict["status"] == "REJECTED"
    assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"
    assert any("immutable verification" in reason for reason in verdict["reasons"])


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
        bd._require_program_first_ai_acceptance(run)


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


def test_semantic_disagreement_requires_executable_proof_before_repair(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["review_outcomes"][0]["status"] == "REPAIR_REQUIRED"
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED"
    assert repairs[0]["verified_challenge"]["sha256"] == \
        _proven_fail_review(task)["verification_test"]["sha256"]
    assert "SAME challenge" in repairs[0]["required_next"]
    assert not Path(task["response_path"]).exists()
    assert len(bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)) == 1


def test_semantic_fail_without_executable_verification_is_rejected(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _valid_review(task)
    review["semantic_review"] = {
        "verdict": "FAIL", "findings": [{"issue": "AI disagrees"}],
        "rationale": "This output looks wrong.",
    }
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("verification_test" in r for r in verdict["reasons"])


def test_verification_test_cannot_read_external_oracle_files(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    review = _proven_fail_review(task)
    challenge = Path(task["challenge_path"])
    source = challenge.read_text().replace(
        "module vibeic_ai_challenge_tb;",
        "module vibeic_ai_challenge_tb; reg [7:0] oracle [0:1]; "
        "initial $readmemh(\"golden.txt\", oracle);")
    challenge.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("self-contained" in reason for reason in verdict["reasons"])
