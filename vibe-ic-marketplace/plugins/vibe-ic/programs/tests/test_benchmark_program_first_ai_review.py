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


def _simulator_absent() -> str:
    """Why this host cannot EXECUTE a verification challenge, or "" if it can.

    MEASURED, one host, one tree, one commit: with `iverilog` and `vvp` on PATH
    this module is 19 passed from four different working directories; with the
    same tree and the same directories but those two binaries off PATH it is
    `4 failed, 15 passed`, the first of them an IndexError on an empty repair
    worklist. The verdict is invariant in CWD and flips entirely on the
    capability -- so four tests that drive a REAL simulation were reporting a
    host capability gap as four behavioural defects.

    They now declare the dependency. This is NOT an unconditional skip: the
    condition is a live probe of the same two binaries the production code
    looks for, `test_the_skip_condition_is_the_production_question` pins it to
    that, and every branch those four tests cover is ALSO covered
    host-independently by the stubbed NOT_MEASURED tests at the end of this
    module -- so nothing here can go quiet on a bare host.
    """
    import shutil                                       # noqa: PLC0415
    missing = [tool for tool in ("iverilog", "vvp") if shutil.which(tool) is None]
    if not missing:
        return ""
    return ("NOT_MEASURED: this host has no " + " and no ".join(missing)
            + "; a verification challenge cannot be executed here, so this "
              "test would be measuring the host, not the code")


_NEEDS_SIMULATOR = pytest.mark.skipif(
    bool(_simulator_absent()),
    reason=_simulator_absent() or "iverilog and vvp are both present")


def _no_simulator(monkeypatch) -> None:
    """Make this process look like a host with no simulator, precisely.

    Only `iverilog` and `vvp` disappear; every other `which` answer is the real
    one, so nothing else in the flow changes shape underneath the assertion.
    """
    import shutil                                       # noqa: PLC0415
    real = shutil.which
    monkeypatch.setattr(
        bd.shutil, "which",
        lambda name, *a, **k: (None if name in ("iverilog", "vvp")
                               else real(name, *a, **k)))


ROUTING = {
    "nature": "spec_generation",
    "route": "SPEC_TO_RTL",
    "source": "no_context_heuristic",
    "needs_ai_parse": True,
}


def _project(tmp_path: Path, *, phase1: bool = True) -> Path:
    """A CANONICAL Program candidate, the shape `--solve` leaves behind.

    Two facts of that shape are load-bearing for `cmd_resume`, and both were
    missing from this fixture until 2026-09-02, when the front door landed in
    #2012 and turned eight resume-driven tests here red at once:

      * the project is RUNNER-OWNED, at `<run>/projects/<id>` -- the gate
        derives the project from the run root, exactly as `--solve` and the
        retry/backup paths do, so a project anywhere else is invisible to it;
      * a D1-entry run has been THROUGH Phase 1 and left hash-bound L-docs in
        `phase1/generated_docs/` -- `emit_attestation.phase1_provenance` is
        `{"ran": False}` without them, and a D1 candidate with no provenance
        is refused as non-canonical before any acceptance is written.

    `phase1=False` builds the same candidate minus the L-docs, for the test
    that pins that refusal.
    """
    project = tmp_path / "run" / "projects" / "p1"
    (project / "input").mkdir(parents=True)
    if phase1:
        docs = project / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L1_DATASHEET.json").write_text(
            '{"schema": 1, "module": "dut"}\n')
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
    review = {
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
    if (task.get("program_verification") or {}).get(
            "functional_confirmation_required") is True:
        review["verification_test"] = _write_direct_assignment_challenge(task)
    return review


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


def _truth_table_task(tmp_path: Path) -> tuple[Path, dict]:
    """A two-row contract whose AI confirmation exercises only one row."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "input" / "phase1_prompt.md").write_text(
        """Design module dut with this exact interface:
module dut(input wire [7:0] code, output reg [7:0] value);

| input | output |
|---|---|
| 8'hA5 | 8'h11 |
| 8'h3C | 8'hE7 |
""")
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        """module dut(input wire [7:0] code, output reg [7:0] value);
always @* begin
  case (code)
    8'hA5: value = 8'h11;
    8'h3C: value = 8'hE7;
    default: value = 8'h00;
  endcase
end
endmodule
""")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    return run, task


def _write_one_row_challenge(task: dict) -> dict:
    source = r"""
module vibeic_ai_challenge_tb;
  reg [7:0] code;
  wire [7:0] value;
  dut candidate(.code(code), .value(value));
  initial begin
    code = 8'hA5; #1;
    if (value !== 8'h11) begin
      $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1);
    end
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
            "excerpt": "| 8'hA5 | 8'h11 |",
            "supports": "The test exercises the first explicit truth-table row.",
        }],
        "expected_behavior": "Input 8'hA5 must produce output 8'h11.",
        "rationale": (
            "The prompt's first truth-table row supplies both the stimulus and "
            "the expected value, so this test checks that row without an oracle."),
    }


@_NEEDS_SIMULATOR
def test_semantic_pass_cannot_leave_a_structural_prompt_obligation_uncovered(
        tmp_path):
    """One passing example is not whole-spec functional confirmation."""
    _, task = _truth_table_task(tmp_path)
    review = _valid_review(task)
    review["verification_test"] = _write_one_row_challenge(task)
    review["semantic_review"]["prompt_evidence"] = [{
        "excerpt": "| 8'hA5 | 8'h11 |",
        "supports": "The review confirms the first explicit table row.",
    }]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    assert verdict["program_review_coverage"]["blocking_gaps"] == 2
    assert any("structural prompt obligation" in reason
               for reason in verdict["reasons"]), verdict


def _write_defective_inversion_challenge(task: dict) -> dict:
    """A frozen older proof whose assertion contradicts the prompt."""
    source = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  dut candidate(.a(a), .y(y));
  initial begin
    a = 1'b0; #1;
    if (y !== 1'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    a = 1'b1; #1;
    if (y !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""
    path = (Path(task["challenge_path"]).parent /
            "inherited-defective-challenge.sv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "id": task["id"],
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_sha256": task["prompt_sha256"],
        "reviewed_rtl_sha256": "frozen-older-candidate",
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The old review incorrectly interpreted direct assignment.",
        }],
        "expected_behavior": "The defective test incorrectly expects inversion.",
        "rationale": (
            "This fixture represents a previously frozen challenge whose own "
            "assertions accidentally contradict the exact prompt behavior."),
    }


@_NEEDS_SIMULATOR
def test_fresh_ai_can_supersede_a_failing_defective_inherited_challenge(
        tmp_path):
    """A correction is explicit, prompt-bound, executable, and auditable."""
    _, task, _ = _task(tmp_path)
    inherited = _write_defective_inversion_challenge(task)
    task["verification_challenges"] = [inherited]

    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    review["challenge_supersessions"] = [{
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": inherited["sha256"],
        "rationale": (
            "The inherited test expects inversion even though the prompt states "
            "a direct assignment. The attached replacement exhaustively checks "
            "both values and therefore corrects that earlier test defect."),
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "Direct assignment requires equality, not inversion.",
        }],
    }]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED", verdict
    assert verdict["inherited_challenge_results"][0]["status"] == "SUPERSEDED"
    assert verdict["inherited_challenge_results"][0]["original_status"] == "FAIL"
    assert verdict["challenge_supersessions"][0]["challenge_sha256"] == \
        inherited["sha256"]


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda item: item.update(challenge_sha256="0" * 64),
         "must name an inherited challenge"),
        (lambda item: item.update(prompt_evidence=[]),
         "needs prompt-bound evidence"),
        (lambda item: item.update(rationale="too short"),
         "rationale must be at least 80"),
    ],
)
@_NEEDS_SIMULATOR
def test_challenge_supersession_fails_closed_without_bound_evidence(
        tmp_path, mutate, expected):
    _, task, _ = _task(tmp_path)
    inherited = _write_defective_inversion_challenge(task)
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    item = {
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": inherited["sha256"],
        "rationale": (
            "The inherited assertion requires inversion while the prompt "
            "requires equality; the replacement test exhaustively checks the "
            "prompt behavior and corrects that earlier test defect."),
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The exact prompt requires direct equality.",
        }],
    }
    mutate(item)
    review["challenge_supersessions"] = [item]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any(expected in reason for reason in verdict["reasons"]), verdict


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
    ai_review = item["phases"]["phase3_verifying"]["ai_semantic_review"]
    assert ai_review["program_functional_evidence"] == "NOT_RECORDED"
    assert ai_review["functional_confirmation_required"] is True
    assert ai_review["functional_confirmation_result"] == "PASS"
    assert ai_review["functional_confirmation_challenge_sha256"]
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


def test_resume_refreshes_only_program_owned_obligations_for_unchanged_task(
        tmp_path):
    run, task, _ = _task(tmp_path)
    current = copy.deepcopy(task["program_review_obligations"])
    stale = copy.deepcopy(current)
    stale["obligation_count"] += 1
    stale["obligations"].append({
        "id": "obsolete-program-false-positive",
        "kind": "analog_converter",
        "requirement": "obsolete Program-derived obligation",
        "evidence": "ADC token was formerly over-classified",
        "coverage_tokens": ["adc"],
    })
    stale["sha256"] = "0" * 64
    task["program_review_obligations"] = stale
    _solve_report(run, task)
    _write_review(task, _valid_review(task))

    assert bd._validate_ai_review(task)["status"] == "REJECTED"
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0

    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert refreshed["program_review_obligations"] == current
    audit = refreshed["program_review_obligation_refreshes"]
    assert audit == [{
        "schema": "vibeic.benchmark.program_review_obligations_refresh.v1",
        "basis": "UNCHANGED_HASH_BOUND_PROMPT_AND_CANDIDATE",
        "prior_contract": stale,
        "replacement_sha256": current["sha256"],
    }]
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())[
        "status"] == "COMPLETE"


def test_program_obligation_refresh_refuses_changed_prompt_or_candidate(
        tmp_path):
    _, prompt_task, _ = _task(tmp_path / "prompt-case")
    prompt_task["program_review_obligations"] = {"stale": True}
    Path(prompt_task["prompt_path"]).write_text("changed prompt\n")
    assert bd._refresh_program_review_obligations(prompt_task) is False
    assert prompt_task["program_review_obligations"] == {"stale": True}

    _, rtl_task, _ = _task(tmp_path / "rtl-case")
    rtl_task["program_review_obligations"] = {"stale": True}
    Path(rtl_task["rtl_paths"][0]).write_text("module changed(); endmodule\n")
    assert bd._refresh_program_review_obligations(rtl_task) is False
    assert rtl_task["program_review_obligations"] == {"stale": True}


def test_static_ai_pass_is_blocked_without_program_functional_evidence(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _valid_review(task)
    review.pop("verification_test", None)
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("semantic PASS without Program functional evidence" in reason
               for reason in verdict["reasons"])


def test_program_functional_pass_does_not_require_a_duplicate_ai_test(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM",
        program_phases={"phase3_verifying": {"ran": {
            "step4_functional_evidence": "PASS"}}})
    review = _valid_review(task)
    assert "verification_test" not in review
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED"
    assert verdict["challenge_result"] is None


@_NEEDS_SIMULATOR
def test_prompt_derived_confirmation_can_close_missing_program_evidence(tmp_path):
    _, task, _ = _task(tmp_path)
    _write_review(task, _valid_review(task))

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED"
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["verified_challenge"]["prompt_evidence"]


@_NEEDS_SIMULATOR
def test_semantic_pass_is_rejected_when_its_confirmation_fails(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _write_review(task, _valid_review(task))

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["challenge_result"]["status"] == "FAIL"
    assert any("AI semantic PASS is not confirmed" in reason
               for reason in verdict["reasons"])


def test_unrunnable_pass_confirmation_is_not_measured(tmp_path, monkeypatch):
    _, task, _ = _task(tmp_path)
    _write_review(task, _valid_review(task))
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["reasons"] == []
    assert any("PASS confirmation could not be RUN" in reason
               for reason in verdict["unmeasurable"])


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


@_NEEDS_SIMULATOR
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


@_NEEDS_SIMULATOR
def test_ai_resigns_exact_candidate_after_program_gate_normalization(tmp_path):
    run, task, _ = _task(tmp_path)
    project = Path(task["project"])
    working_rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    review = _proven_fail_review(task)
    _write_review(task, review)
    challenge = bd._validate_ai_review(task)["verified_challenge"]

    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    record = _write_ai_repair_record(run, task, challenge)
    record_path = bd._repair_record_path(run, task)
    repair_provenance, reasons = bd._validate_repair_record(
        record_path, task, record["repaired_rtl_sha256"], challenge)
    assert reasons == []

    # Model a deterministic PROGRAM-gate normalization after the AI supplied
    # its first repair.  The old signature must not authorize the new bytes.
    working_rtl.write_text(
        "module dut(input wire a, output wire y); "
        "assign y = a & 1'b1; endmodule\n")
    got = bio.collect("rtllm", "p1", project, supplied_rtl=True)
    final_task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "AI_REPAIR",
        verification_challenges=[challenge],
        program_candidate=task["candidate_snapshot"],
        repair_provenance=repair_provenance)
    rebound, reasons = bd._refresh_final_repair_provenance(final_task)
    assert rebound is None
    assert any("repaired_rtl_sha256" in reason for reason in reasons)

    final_hash = final_task["rtl_sha256"]
    record["pre_gate_ai_rtl_sha256"] = record["repaired_rtl_sha256"]
    record["repaired_rtl_sha256"] = final_hash
    record_path.write_text(json.dumps(record))
    rebound, reasons = bd._refresh_final_repair_provenance(final_task)
    assert reasons == []
    assert rebound["repaired_rtl_sha256"] == final_hash
    assert rebound["pre_gate_ai_rtl_sha256"] != final_hash


@_NEEDS_SIMULATOR
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


@_NEEDS_SIMULATOR
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


@_NEEDS_SIMULATOR
def test_fresh_ai_fail_plus_inherited_fail_requests_another_repair(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    review = _proven_fail_review(task)
    _write_review(task, review)
    inherited = bd._validate_ai_review(task)["verified_challenge"]
    task["verification_challenges"] = [inherited]

    # Both the fresh prompt-bound challenge and the immutable inherited one
    # reject this candidate.  Agreement that it is still wrong authorizes the
    # next repair; only an attempted PASS over the inherited failure is invalid.
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    assert verdict["challenge_result"]["status"] == "FAIL"
    assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"
    assert verdict["reasons"] == []


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


@_NEEDS_SIMULATOR
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
    review.pop("verification_test", None)
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


# ---------------------------------------------------------------------------
# a MISSING CAPABILITY is NOT_MEASURED, never a finding about the subject
#
# Everything below runs identically on every host: the simulator is removed by
# a `which` stub, never by the host's luck. That is what stops the four
# `_NEEDS_SIMULATOR` tests above from being a hole -- the branch they cannot
# reach on a bare host is reached here instead.
# ---------------------------------------------------------------------------
def test_the_skip_condition_is_the_production_question(tmp_path, monkeypatch):
    """The probe that gates the four tests must ask the production question.

    If it ever drifted -- probing a different binary, or nothing at all -- the
    four tests could skip on a host that can in fact run them, which is the
    silenced-test failure mode. So it is pinned to the observable behaviour of
    `_run_verification_challenge` in both directions.
    """
    _, task, _ = _task(tmp_path)
    challenge = _write_direct_assignment_challenge(task)
    candidate = task["candidate_snapshot"]

    _no_simulator(monkeypatch)
    assert _simulator_absent(), "the probe must see the stubbed-away simulator"
    assert bd._run_verification_challenge(candidate, challenge)["status"] == \
        bd._CHALLENGE_UNAVAILABLE

    monkeypatch.undo()
    if not _simulator_absent():
        assert bd._run_verification_challenge(candidate, challenge)["status"] \
            != bd._CHALLENGE_UNAVAILABLE, (
            "the probe says this host has a simulator but the production code "
            "still reports UNAVAILABLE -- the skip condition is asking the "
            "wrong question")


def test_an_unrunnable_challenge_is_NOT_MEASURED_not_a_rejected_review(
        tmp_path, monkeypatch):
    """THE BUG. A proven-FAIL review on a host with no simulator was coming
    back REJECTED with "AI finding is not proven" -- an accusation assembled
    out of a missing binary. Nothing about this candidate was established, and
    the verdict must say so in those words."""
    _, task, _ = _task(tmp_path)
    _write_review(task, _proven_fail_review(task))
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["reasons"] == [], (
        "an unrunnable proof is not a finding against the review", verdict)
    assert not any("not proven" in r for r in verdict["decision_reasons"]), \
        verdict["decision_reasons"]
    assert any("could not be RUN on this host" in r
               for r in verdict["unmeasurable"]), verdict["unmeasurable"]
    assert any("iverilog" in r for r in verdict["unmeasurable"]), \
        "the reader must be told WHICH capability is missing"


def test_an_unrunnable_INHERITED_challenge_is_also_NOT_MEASURED(
        tmp_path, monkeypatch):
    """The other UNAVAILABLE site. Folding it into `!= PASS` charged a repair
    with failing a test nobody ran."""
    _, task, _ = _task(tmp_path)
    task["verification_challenges"] = [{
        **_write_direct_assignment_challenge(task),
        "id": task["id"], "prompt_sha256": task["prompt_sha256"],
    }]
    _write_review(task, _valid_review(task))
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert not any("does not pass" in r for r in verdict["decision_reasons"])
    assert any("inherited" in r for r in verdict["unmeasurable"]), \
        verdict["unmeasurable"]


def test_a_real_disagreement_is_still_RED_with_the_simulator_stubbed(
        tmp_path, monkeypatch):
    """The other branch, and the reason NOT_MEASURED is not a way out.

    When the challenge DOES run and the candidate DOES fail it, the verdict is
    REPAIR_REQUIRED and a repair row is written -- exactly as before. The fix
    carved out UNAVAILABLE and nothing else.
    """
    _, task, _ = _task(tmp_path)
    _write_review(task, _proven_fail_review(task))
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *_a, **_k: {"status": "FAIL", "returncode": 1})

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    assert verdict["unmeasurable"] == []


def test_a_challenge_the_candidate_PASSES_is_still_a_rejected_finding(
        tmp_path, monkeypatch):
    """And the accusation itself must survive. A review that claims FAIL over
    a candidate that passes its own test is wrong, and that is a finding about
    the review -- not a NOT_MEASURED."""
    _, task, _ = _task(tmp_path)
    _write_review(task, _proven_fail_review(task))
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *_a, **_k: {"status": "PASS", "returncode": 0})

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("not proven" in r for r in verdict["reasons"])


def test_a_malformed_review_outranks_an_unrunnable_proof(tmp_path, monkeypatch):
    """Precedence, stated. A review that is wrong on every host stays REJECTED
    on a host with no simulator; NOT_MEASURED must not become a place for real
    defects to hide."""
    _, task, _ = _task(tmp_path)
    review = _proven_fail_review(task)
    review["semantic_review"]["rationale"] = "no"          # too short: a defect
    _write_review(task, review)
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("rationale" in r for r in verdict["reasons"])


def test_resume_reports_NOT_MEASURED_and_orders_no_repair(
        tmp_path, monkeypatch):
    """End to end, at the level a sweep report actually reads.

    The run must not be COMPLETE, must not accept the candidate, and must not
    put a row on the repair worklist -- telling an author to re-write RTL on
    the strength of a test that did not run is the misdirection this whole fix
    is about. It states the gap in its own field instead.
    """
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
    _no_simulator(monkeypatch)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["accepted"] == 0
    assert acceptance["review_outcomes"][0]["status"] == bd._NOT_MEASURED
    assert acceptance["not_measured"] == 1
    assert acceptance["pending_repair"] == 0
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    row = acceptance["not_measured_detail"][0]
    assert row["id"] == "p1"
    assert any("iverilog" in r for r in row["reasons"])
    assert "install the missing capability" in row["required_next"]
    assert not Path(task["response_path"]).exists(), \
        "NOT_MEASURED must never publish a result"


@_NEEDS_SIMULATOR
def test_with_a_REAL_simulator_no_verdict_is_NOT_MEASURED(tmp_path):
    """THE CONTROL ON THE FIX ITSELF.

    Everything above proves NOT_MEASURED appears where it should. Nothing above
    proves it stays away everywhere else -- and a "fix" that returned
    NOT_MEASURED for every review would satisfy every one of those tests while
    destroying the lane. So: with a real iverilog on this host, drive both
    substantive outcomes through the REAL challenge runner and require that
    neither is NOT_MEASURED and both carry an empty `unmeasurable`.

      candidate y = ~a  vs a challenge demanding y == a  -> challenge FAIL,
          the AI's finding is PROVEN            -> REPAIR_REQUIRED
      candidate y =  a  vs the same challenge             -> challenge PASS,
          the AI's FAIL claim is unfounded      -> REJECTED

    Note which is which. REPAIR_REQUIRED is the verdict when the candidate
    genuinely fails its proof: rejecting there would be discarding a proven
    finding. REJECTED belongs to the review that could not prove its claim.
    """
    outcomes = {}
    for rtl, label in (
            ("module dut(input wire a, output wire y); assign y = ~a; endmodule\n",
             "candidate fails the proof"),
            ("module dut(input wire a, output wire y); assign y = a; endmodule\n",
             "candidate passes the proof")):
        run = tmp_path / label.replace(" ", "_")
        (run / "responses").mkdir(parents=True)
        project = _project(tmp_path / label.replace(" ", "_") / "p")
        (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(rtl)
        got = bio.collect("rtllm", "p1", project)
        task = bd._make_ai_review_task(
            "p1", project, got, ROUTING, 0, run, "PROGRAM")
        _write_review(task, _proven_fail_review(task))
        verdict = bd._validate_ai_review(task)
        outcomes[label] = (verdict["status"],
                           verdict["challenge_result"]["status"],
                           verdict["unmeasurable"])

    assert outcomes["candidate fails the proof"][:2] == ("REPAIR_REQUIRED", "FAIL")
    assert outcomes["candidate passes the proof"][:2] == ("REJECTED", "PASS")
    assert all(u == [] for _s, _c, u in outcomes.values()), outcomes
    assert not any(s == bd._NOT_MEASURED for s, _c, _u in outcomes.values()), (
        "with a working simulator NOTHING may come back NOT_MEASURED", outcomes)


# ---------------------------------------------------------------------------
# the Phase-1 front door at resume: judged by what the run EMITTED
#
# #2012 (v1.15.55) put a BLOCKING front door in front of `cmd_resume`: a D1
# candidate must carry hash-bound Phase-1 provenance before anything is
# accepted. Its D1 branch, however, read the TASK's record and never the disk
# -- `current` was computed and ignored -- and it refused results still owed
# a Program retry, which have no outcome to guard at all. The three tests
# below pin the refusal that is right and the two that were not.
# ---------------------------------------------------------------------------
_FUNCTIONAL_PASS = {"phase3_verifying": {"ran": {
    "step4_functional_evidence": "PASS"}}}


def _canonical_task(tmp_path: Path, **kwargs) -> tuple[Path, dict]:
    """A reviewable D1 candidate whose Program evidence already says PASS, so
    the review needs no executable confirmation and no host simulator."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True, exist_ok=True)
    project = _project(tmp_path, **kwargs)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM",
        program_phases=_FUNCTIONAL_PASS)
    return run, task


def test_a_d1_candidate_without_phase1_provenance_is_refused_at_resume(
        tmp_path, capsys):
    """The refusal that is RIGHT, pinned so the canonical fixture above is
    known to pass THROUGH the gate rather than around it: the same candidate
    minus its L-docs is refused by the exact clause that reddened the eight,
    and nothing is published."""
    run, task = _canonical_task(tmp_path, phase1=False)
    assert task["phase1_provenance"] == {"ran": False}
    _solve_report(run, task)
    _write_review(task, _valid_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    err = capsys.readouterr().err
    assert "canonical D1-entry run emitted no Phase-1 provenance" in err, err
    assert not Path(task["response_path"]).exists()
    acceptance = run / bd._ACCEPTANCE_REPORT
    assert (not acceptance.exists()
            or json.loads(acceptance.read_text())["accepted_ids"] == [])


def test_emitted_phase1_provenance_is_bound_when_the_task_does_not_carry_it(
        tmp_path, monkeypatch):
    """THE DEFECT, first half. A task from before provenance was carried in
    review tasks (v1.13.70), or one not written yet, records nothing -- and
    the D1 branch answered that absence with "emitted no Phase-1 provenance"
    while the L-docs sat on disk. The emitted provenance must be read, bound
    into the task, and never regenerated by a runner call."""
    run, task = _canonical_task(tmp_path)
    emitted = task["phase1_provenance"]
    assert emitted["ran"] is True
    stale = {k: v for k, v in task.items() if k != "phase1_provenance"}
    _solve_report(run, stale)
    _write_review(stale, _valid_review(stale))

    def never(_self, argv):
        raise AssertionError(
            f"a D1 run's provenance is bound, never regenerated: {argv}")

    monkeypatch.setattr(bd._RunnerBudget, "run", never)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["accepted_ids"] == ["p1"]
    rebound = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert rebound["phase1_provenance"] == emitted
    solve = json.loads((run / "solve_report.json").read_text())
    assert solve["results"][0]["phase1_frontdoor"]["status"] == "REUSED"
    bd._require_program_first_ai_acceptance(run)


def test_a_retryable_worker_error_is_retried_not_refused_at_the_front_door(
        tmp_path, monkeypatch):
    """THE DEFECT, second half. A result whose Program worker died is owed
    the retry `cmd_resume` was built to give it, and has no candidate to
    guard. The front door refused it -- so one D1 crash froze every other
    result in the run behind a message about provenance nobody had yet had
    the chance to emit. The retry must be attempted, its failure must stay
    loud, and the reviewed sibling must still be accepted."""
    run, task = _canonical_task(tmp_path)
    _solve_report(run, task)
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"].append({
        "id": "p2", "ok": False, "candidate_ready": False,
        "accepted": False, "entry": "D1", "evidence": "RTL_SIM",
        "exit": "8", "routing_verdict": ROUTING, "rc": None,
        "worker_status": "ERROR", "worker_retryable": True,
        "worker_error": "fixture: the worker died before Phase 1",
    })
    solve["total"] = 2
    (run / "solve_report.json").write_text(json.dumps(solve))
    _write_review(task, _valid_review(task))
    attempted: list[list[str]] = []

    def retry(_self, argv):
        attempted.append([str(v) for v in argv])
        return bd._ProcessOutcome(
            rc=None, error="fixture: the worker died again")

    monkeypatch.setattr(bd._RunnerBudget, "run", retry)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    # The solve report exists on both sides of the fix; its VALUES are the
    # measurement. Before the fix the resume aborted at the front door and
    # left p1 exactly as --solve wrote it: accepted False.
    resumed = json.loads((run / "solve_report.json").read_text())["results"]
    assert resumed[0]["accepted"] is True
    assert resumed[1]["worker_status"] == "ERROR"
    assert [a[2] if len(a) > 2 else None for a in attempted] == [
        str(run / "projects" / "p2")], attempted
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["accepted_ids"] == ["p1"]
    assert Path(task["response_path"]).exists()
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert [r["status"] for r in repairs] == ["PROJECT_WORKER_ERROR"]
