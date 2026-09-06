"""Source questions are not RTL failures, accepted responses, or scorer input."""
import copy
import json
from pathlib import Path

import pytest

import test_benchmark_program_first_ai_review as fixtures

bd = fixtures.bd
PROMPT = "Design module dut with input a and output y. Assert y for an invalid payload.\n"


def _case(tmp_path):
    run, task = fixtures._task_with(
        tmp_path, PROMPT,
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    review = fixtures._valid_review(task)
    review.pop("verification_test", None)
    review["semantic_review"].update({
        "verdict": "NEEDS_CLARIFICATION",
        "findings": ["The public spec does not define which payloads are invalid."],
        "rationale": "No executable expected result can be derived without a legality predicate.",
    })
    review["spec_clarification"] = {
        "schema": "vibeic.spec_clarification.v1",
        "source_sha256": [task["prompt_sha256"]],
        "requests": [{
            "source_sha256": task["prompt_sha256"],
            "excerpt": "Assert y for an invalid payload.",
            "missing_information": "The set of valid and invalid payload values is unspecified.",
            "question": "Which input values are invalid, and what is y for every other input?",
        }],
    }
    fixtures._write_review(task, review)
    fixtures._solve_report(run, task)
    return run, task, review


def test_existing_validator_distinguishes_question_from_rejected_review(tmp_path):
    _, task, _ = _case(tmp_path)
    outcome = bd._validate_ai_review(task)
    # Behavioral negative control: pre-fix returns REJECTED (not a missing API).
    assert outcome["status"] == "SPEC_CLARIFICATION_REQUIRED", outcome
    assert outcome["spec_clarification"]["requests"][0]["question"]
    assert outcome["verified_challenge"] is None


def test_real_resume_waits_on_spec_without_repair_acceptance_or_score(tmp_path, monkeypatch):
    run, task, _ = _case(tmp_path)
    protected = {p: Path(p).read_bytes() for p in
                 [task["prompt_path"], task["review_path"], *task["rtl_paths"]]}
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *args: pytest.fail("a question cannot be simulated"))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["review_outcomes"][0]["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert acceptance["accepted"] == 0
    assert acceptance["total"] == 1
    assert acceptance["status"] == "PENDING"
    assert acceptance["pending_spec_clarification"] == 1
    assert acceptance["pending_review"] == acceptance["pending_repair"] == 0
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    questions = bd._read_jsonl(run / "needs_spec_clarification.jsonl")
    assert len(questions) == 1
    assert questions[0]["prompt_sha256"] == task["prompt_sha256"]
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["awaiting_spec_clarification"] is True
    assert result["awaiting_ai_review"] is result["ai_repair_required"] is False
    assert not Path(task["response_path"]).exists()
    with pytest.raises(SystemExit, match="acceptance BLOCKED"):
        bd._require_program_first_ai_acceptance(run)
    assert {p: Path(p).read_bytes() for p in protected} == protected
    # Repeating resume is a stable waiting state, not another repair attempt.
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert bd._read_jsonl(run / "needs_spec_clarification.jsonl") == questions


@pytest.mark.parametrize("damage", ["prompt_hash", "rtl_hash", "oracle", "route",
                                    "quote", "missing", "corpus", "null",
                                    "obligations", "supersession", "inherited_shape"])
def test_clarification_keeps_material_blindness_and_review_guards(tmp_path, damage):
    _, task, review = _case(tmp_path)
    if damage == "prompt_hash":
        review["prompt_sha256"] = "0" * 64
    elif damage == "rtl_hash":
        review["rtl_sha256"] = "0" * 64
    elif damage == "oracle":
        review["blind"]["oracle_accessed"] = True
    elif damage == "route":
        review["routing"]["ai_nature"] = "unrelated"
    elif damage == "quote":
        review["spec_clarification"]["requests"][0]["excerpt"] = "An invented requirement."
    elif damage == "missing":
        review.pop("spec_clarification")
    elif damage == "corpus":
        review["spec_clarification"]["source_sha256"].append("0" * 64)
    elif damage == "null":
        review["spec_clarification"] = None
    elif damage == "obligations":
        task["program_review_obligations"] = {}
    elif damage == "supersession":
        review["challenge_supersessions"] = [{"challenge_sha256": "0" * 64}]
    elif damage == "inherited_shape":
        task["verification_challenges"] = ["malformed record"]
    fixtures._write_review(task, review)
    assert bd._validate_ai_review(task)["status"] == "REJECTED"


def test_inherited_obligations_are_not_executed_or_superseded(tmp_path, monkeypatch):
    _, task, _ = _case(tmp_path)
    inherited = fixtures._write_invalid_inherited_challenge(task)
    task["verification_challenges"] = [inherited]
    before = copy.deepcopy(task)
    source = Path(inherited["path"]).read_bytes()
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *args: pytest.fail("must preserve, not simulate"))
    outcome = bd._validate_ai_review(task)
    assert outcome["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert outcome["challenge_supersessions"] == []
    assert outcome["inherited_challenge_results"][0]["status"] == "NOT_RUN"
    assert task == before
    assert Path(inherited["path"]).read_bytes() == source


def test_old_repair_handoff_is_preserved_but_not_advertised_as_active(tmp_path):
    _, task, _ = _case(tmp_path)
    result = {"phases": {"phase4_debugging": {"ai_semantic_repair_handoff": {
        "status": "REPAIR_REQUIRED", "findings": ["Previous proven discrepancy."],
    }}}}
    bd._attach_ai_review_attribution(result, bd._validate_ai_review(task), task)
    old = result["phases"]["phase4_debugging"]["ai_semantic_repair_handoff"]
    assert old["status"] == "ON_HOLD_FOR_SPEC_CLARIFICATION"
    assert old["active"] is False
    assert old["prior_status"] == "REPAIR_REQUIRED"
    assert old["findings"] == ["Previous proven discrepancy."]


@fixtures._NEEDS_SIMULATOR
@pytest.mark.parametrize("verdict", ["PASS", "FAIL"])
def test_question_cannot_be_laundered_into_an_acceptance_or_repair(tmp_path, verdict):
    _, task, review = _case(tmp_path)
    review["semantic_review"]["verdict"] = verdict
    fixtures._write_review(task, review)
    assert bd._validate_ai_review(task)["status"] == "REJECTED"


@fixtures._NEEDS_SIMULATOR
def test_fresh_normal_review_clears_waiting_worklist_but_still_requires_proof(tmp_path):
    # Use a complete public spec: an AI can withdraw an erroneous question,
    # but only the existing ordinary PASS + functional proof can accept it.
    run, task, _ = fixtures._task(tmp_path)
    _, _, review = _case(tmp_path / "other")
    review.update({"prompt_sha256": task["prompt_sha256"],
                   "rtl_sha256": task["rtl_sha256"]})
    review["spec_clarification"]["source_sha256"] = [task["prompt_sha256"]]
    request = review["spec_clarification"]["requests"][0]
    request.update({"source_sha256": task["prompt_sha256"], "excerpt": "assign y = a"})
    fixtures._write_review(task, review)
    fixtures._solve_report(run, task)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    fixtures._write_review(task, fixtures._valid_review(task))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    assert bd._read_jsonl(run / "needs_spec_clarification.jsonl") == []
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["awaiting_spec_clarification"] is False
    bd._require_program_first_ai_acceptance(run)
