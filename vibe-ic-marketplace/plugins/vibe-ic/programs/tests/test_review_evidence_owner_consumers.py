"""Bounded consumer ownership; no fabricated gate reports or AI judgement.

Use real neutral native duplicate receipts. Full ordinary G3 resume reproduction
is parent-owned; these controls exercise its retained-result consumption seam.
"""
import copy
import json
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import flow_phase_attribution as fpa
import test_spec_coverage_bound_clock_periods as clocks
from test_issue2210_required_interface_omission import _candidate
from test_stored_runner_issued_consumer import ordinary_duplicate  # noqa: F401


def coverage_inputs(tmp_path, texts):
    candidate = _candidate(tmp_path, "neutral", clocks.RTL)
    tests = []
    for index, text in enumerate(texts):
        path = tmp_path / f"proof-{index}.sv"
        path.write_text(text)
        tests.append({"path": str(path), "sha256": bd._sha256_text(text)})
    return candidate, tests


def test_complete_standalone_clock_tests_do_not_collide_when_reviewed_together(tmp_path):
    texts = [clocks.TB, clocks.TB + "\n// independent proof\n"]
    candidate, tests = coverage_inputs(tmp_path, texts)
    for index, text in enumerate(texts):
        native = tmp_path / f"native-{index}"
        native.mkdir()
        simulation = clocks._native(native, text)
        assert simulation.returncode == 0, simulation.stdout + simulation.stderr
        assert all(item["covered"] for item in clocks._clocks(clocks._report(text)).values())
    result = bd._program_review_coverage_result(clocks.PROMPT, candidate, tests)
    assert result["status"] == "PASS", result
    assert result["blocking_gaps"] == 0
    assert result["active_challenge_sha256"] == [item["sha256"] for item in tests]
    assert set(result["covered_by_challenge"].values()) <= set(result["active_challenge_sha256"])


def test_distinct_obligations_can_be_fully_proven_by_different_tests(tmp_path):
    first = clocks.TB.replace(clocks.SLOW_PROOF, "")
    second = clocks.TB.replace(clocks.INPUT_PROOF, "").replace(clocks.FAST_PROOF, "")
    second = second.replace('if(!done_fast)$fatal(1,"disabled observer");', "")
    candidate, tests = coverage_inputs(tmp_path, [first, second])
    assert bd._program_review_coverage_result(clocks.PROMPT, candidate, tests)["status"] == "PASS"


@pytest.mark.parametrize("case", ["split_proof", "empty", "no_tests", "wrong_owner"])
def test_no_cross_test_half_proof_or_missing_evidence_can_cover_a_clock(tmp_path, case):
    if case == "split_proof":
        texts = [clocks.TB.replace(clocks.INPUT_PROOF, "").replace(clocks.FAST_PROOF, "").replace(clocks.SLOW_PROOF, ""),
                 clocks.TB.replace("always #4 drive=~drive;", "")]
    elif case == "empty":
        texts = [""]
    elif case == "no_tests":
        texts = []
    else:
        texts = [clocks.TB.replace("rate_pair dut", "unrelated_leaf dut")]
    candidate, tests = coverage_inputs(tmp_path, texts)
    result = bd._program_review_coverage_result(clocks.PROMPT, candidate, tests)
    assert result["status"] == "FAIL", result
    assert result["blocking_gaps"] > 0


def test_stale_standalone_challenge_hash_is_rejected(tmp_path):
    candidate, tests = coverage_inputs(tmp_path, [clocks.TB])
    tests[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash changed"):
        bd._program_review_coverage_result(clocks.PROMPT, candidate, tests)


@pytest.fixture(scope="module")
def retained_metadata(ordinary_duplicate):
    root, project, argv, measured, duplicate = ordinary_duplicate
    got = bio.collect("rtllm", "neutral", project, supplied_rtl=True)
    assert got["ok"]
    routing = {"nature": "spec_generation", "route": "SPEC_TO_RTL"}
    task = bd._make_ai_review_task("neutral", project, got, routing,
                                   measured.rc, root / "review-run", "PROGRAM",
                                   runner_invocation=measured.invocation)
    result = {"id": "neutral", "entry": "1", "exit": "2", "evidence": "RTL_LINT",
              "routing_verdict": routing, "accepted": False, "ok": False,
              "candidate_ready": False, "runner_invocation": duplicate.invocation,
              "runner_diagnostics": bd._runner_diagnostics(duplicate, argv, project),
              "phases": bd._phase_error_attribution(),
              "program_first_phases": {
                  "phase2_solving": {"neutral_program_first": "preserve"},
                  "phase4_debugging": {"neutral_history": "preserve"}}}
    for phase in result["phases"].values():
        phase["reason"] = "RUNNER_REPORT_NOT_FRESH"
    assert bd._gate_evidence_freshness_reasons(project, result)
    return root, project, task, result, got, measured, duplicate


def test_verified_measurement_refresh_reaches_existing_freshness_and_ledger(retained_metadata):
    root, project, task, original, got, measured, duplicate = retained_metadata
    result = copy.deepcopy(original)
    old_bytes = Path(measured.receipt_path).read_bytes()
    later_bytes = Path(duplicate.receipt_path).read_bytes()
    assert bd._refresh_retained_measurement_result(task, result, got)
    assert result["accepted"] is False  # metadata refresh is not acceptance
    assert result["ok"] and result["candidate_ready"]
    assert result["runner_invocation"] == measured.invocation
    assert result["runner_diagnostics"]["retained_after_duplicate"]["invocation_id"] == duplicate.invocation_id
    assert bd._required_gate_ledger(result)["eligibility"] == "ELIGIBLE"
    assert bd._gate_evidence_freshness_reasons(project, result) == []
    assert result["phases"]["phase2_solving"] == original["program_first_phases"]["phase2_solving"]
    assert result["phases"]["phase4_debugging"] == original["program_first_phases"]["phase4_debugging"]
    assert Path(measured.receipt_path).read_bytes() == old_bytes
    assert Path(duplicate.receipt_path).read_bytes() == later_bytes
    (root / "refreshed-result.json").write_text(json.dumps(result, indent=2))


@pytest.mark.parametrize("case", ["wrong_attempt", "wrong_completion", "collector_refused", "real_fail_snapshot", "wrong_task", "wrong_project", "material"])
def test_refresh_refuses_unproven_owner_or_changed_candidate(retained_metadata, case):
    root, project, original_task, original, original_got, measured, duplicate = retained_metadata
    task, result, got = copy.deepcopy(original_task), copy.deepcopy(original), dict(original_got)
    if case == "wrong_attempt":
        result["runner_invocation"]["invocation_id"] = "0" * 32
    elif case == "wrong_completion":
        got["completion"] += "\n// unsigned delta\n"
    elif case == "collector_refused":
        got["ok"] = False
    elif case == "real_fail_snapshot":
        result["phases"]["phase3_verifying"] = {"status": "FAIL", "ran": {"rtl_validate": "FAIL"}}
    elif case == "wrong_task":
        task["program_verification"]["runner_invocation"]["invocation_id"] = "0" * 32
    elif case == "wrong_project":
        task["project"] = str(root / "unrelated-project")
    before = copy.deepcopy(result)
    prompt = project / "input/phase1_prompt.md"
    original_prompt = prompt.read_bytes()
    try:
        if case == "material":
            prompt.write_bytes(original_prompt + b"Unadmitted requirement.\n")
        assert bd._refresh_retained_measurement_result(task, result, got) is False
    finally:
        if case == "material":
            prompt.write_bytes(original_prompt)
    assert result == before
