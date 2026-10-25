"""Actual supplied Step-2 receipts remain PROGRAM after Program re-entry.

Collection uses the existing native neutral fixture and collector. No synthetic
gate reports, AI signatures, routed verdicts or candidate acceptance are made.
"""
import copy
import json
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import flow_phase_attribution as fpa
from test_stored_runner_issued_consumer import ordinary_duplicate  # noqa: F401


@pytest.fixture(scope="module")
def program_step2(ordinary_duplicate):
    root, project, argv, measured, duplicate = ordinary_duplicate
    got = bio.collect("rtllm", "neutral", project, supplied_rtl=True)
    assert got["ok"]
    task = bd._make_ai_review_task("neutral", project, got,
        {"nature": "spec_generation", "route": "SPEC_TO_RTL"},
        measured.rc, root / "review-run", "PROGRAM", runner_invocation=measured.invocation)
    result = {"candidate_origin": "PROGRAM", "rc": measured.rc}
    assert bd._runner_reentry_reason(task, result) is None
    return root, project, task, result, measured


def test_program_step2_collects_exact_measured_bytes_without_changing_origin(program_step2):
    root, project, task, result, measured = program_step2
    refused = bio.collect("rtllm", "neutral", project, supplied_rtl=False)
    assert refused["ok"] is False and refused["rtl_gen"] == "NOT_APPLICABLE"
    before = Path(measured.receipt_path).read_bytes()
    supplied = bd._review_collection_supplied_rtl(task, result)
    collected = bio.collect("rtllm", "neutral", project, supplied_rtl=supplied)
    assert collected["ok"] is True, collected
    assert bd._sha256_text(collected["completion"]) == task["rtl_sha256"]
    assert task["candidate_origin"] == result["candidate_origin"] == "PROGRAM"
    assert task["program_verification"]["rtl_gen"] == collected["rtl_gen"] == "NOT_APPLICABLE"
    assert Path(measured.receipt_path).read_bytes() == before
    (root / "collection-result.json").write_text(json.dumps({
        "supplied_rtl": supplied, "candidate_origin": result["candidate_origin"],
        "completion_sha256": bd._sha256_text(collected["completion"]),
        "without_supplied_reason": refused["reason"]}, indent=2))


@pytest.mark.parametrize("case", [
    "legacy", "unvalidated", "wrong_source", "wrong_argv", "entry1",
    "exit3", "duplicate_entry", "missing_entry", "unknown_origin",
])
def test_unvalidated_or_noncanonical_invocations_cannot_authorize_supplied(program_step2, case):
    root, project, original, original_result, measured = program_step2
    task, result = copy.deepcopy(original), dict(original_result)
    verification = task["program_verification"]
    invocation = verification["runner_invocation"]
    if case == "legacy":
        del verification["runner_invocation"]
    elif case == "unvalidated":
        invocation["status"] = "REFUSED"
    elif case == "wrong_source":
        invocation["source_after"]["runner"]["sha256"] = "0" * 64
    elif case == "wrong_argv":
        verification["runner_argv"].append("--not-issued")
    elif case in {"entry1", "exit3"}:
        option = "--entry-step" if case == "entry1" else "--exit-step"
        invocation["argv"][invocation["argv"].index(option) + 1] = "1" if case == "entry1" else "3"
    elif case == "duplicate_entry":
        invocation["argv"] += ["--entry-step", "2"]
    elif case == "missing_entry":
        index = invocation["argv"].index("--entry-step")
        del invocation["argv"][index:index + 2]
    else:
        result["candidate_origin"] = "NONE"
    assert bd._review_collection_supplied_rtl(task, result) is False
    collected = bio.collect("rtllm", "neutral", project,
        supplied_rtl=bd._review_collection_supplied_rtl(task, result))
    assert collected["ok"] is False and collected["rtl_gen"] == "NOT_APPLICABLE"


def test_actual_retained_producer_drift_cannot_authorize_supplied(program_step2):
    root, project, task, result, measured = program_step2
    producer = Path(measured.invocation["reports_after"]["phase2_one_shot.json"]["runner_binding"]["producer"]["path"])
    assert producer.is_relative_to(root)
    before = producer.read_bytes()
    try:
        producer.write_bytes(before + b"\n# neutral source drift\n")
        assert bd._review_collection_supplied_rtl(task, result) is False
    finally:
        producer.write_bytes(before)


@pytest.mark.parametrize("status", ["NOT_MEASURED", "BLOCKED", None, "FAIL"])
def test_existing_typed_validation_fact_never_promotes_nonmeasurement(program_step2, monkeypatch, status):
    # Typed reader controls, not claims of new native tool measurements.
    root, project, task, result, measured = program_step2
    report, why = fpa.step_report(project)
    report = copy.deepcopy(report)
    if status is None:
        report["steps"] = [row for row in report["steps"] if row["name"] != "rtl_validate"]
    else:
        next(row for row in report["steps"] if row["name"] == "rtl_validate")["status"] = status
    monkeypatch.setattr(fpa, "step_report", lambda _project: (report, why))
    supplied = bd._review_collection_supplied_rtl(task, result)
    assert supplied is (status == "FAIL")
    if status == "FAIL":
        ledger = bd._required_gate_ledger({"exit": "2", "phases": {
            "phase3_verifying": fpa.phase3_verifying(report, why)}})
        assert ledger["eligibility"] == "INELIGIBLE"
        assert "rtl_validate" in ledger["failed_required"]


@pytest.mark.parametrize("origin", ["AI_BACKUP", "AI_REPAIR"])
def test_existing_ai_origin_selection_is_unchanged(origin):
    assert bd._review_collection_supplied_rtl({}, {"candidate_origin": origin}) is True
