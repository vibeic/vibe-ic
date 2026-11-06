"""Benchmark collection follows process outcomes and native reports."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_dispatch as dispatch
import flow_phase_attribution as attribution


def runner(tmp_path, status="PASS", code=0):
    project = tmp_path / "project"
    project.mkdir()
    script = tmp_path / "vibe_ic_one_shot_runner.py"
    script.write_text(
        "import json, os, pathlib, sys\n"
        "project = pathlib.Path(sys.argv[1])\n"
        "(project / 'reports').mkdir(exist_ok=True)\n"
        f"(project / 'reports/flow_engine.json').write_text(json.dumps({{'selected': 1, 'steps': [{{'name': 'rtl_validation_and_lint', 'status': {status!r}, 'tool_ran': True}}]}}))\n"
        "print(json.dumps({'threads': os.environ.get('OMP_NUM_THREADS'), 'project': str(project)}))\n"
        f"sys.exit({code})\n")
    argv = [sys.executable, str(script), str(project)]
    return project, script, argv


def test_native_report_needs_no_receipt_or_unchanged_source(tmp_path):
    project, script, argv = runner(tmp_path)
    outcome = dispatch._RunnerBudget(1, 1, 2).run(argv)
    assert outcome.rc == 0 and outcome.error is None
    assert json.loads(outcome.stdout)["threads"] == "2"
    for path in (project / "reports/orchestrator/runner_invocations").glob("*.json"):
        path.unlink()
    script.write_text(script.read_text() + "\n# edited after the completed process\n")
    assert dispatch._stored_runner_diagnostics(outcome.invocation)["status"] == "REPORTS_AVAILABLE"
    assert dispatch._runner_reentry_reason({"program_verification": {
        "runner_invocation": outcome.invocation}}, {}) is None
    assert not any("sha256" in key or key.startswith(("source_", "material_"))
                   for key in outcome.invocation)


def test_repeated_native_measurement_with_identical_report_is_usable(tmp_path):
    project, _, argv = runner(tmp_path)
    budget = dispatch._RunnerBudget(1, 1, 1)
    first = budget.run(argv)
    before = (project / "reports/flow_engine.json").read_bytes()
    second = budget.run(argv)
    assert before == (project / "reports/flow_engine.json").read_bytes()
    assert first.rc == second.rc == 0
    assert first.error is second.error is None
    assert dispatch._runner_diagnostics(second, argv, project)["native_verdict"] == "PASS"


def test_native_failure_is_a_measured_result(tmp_path):
    project, _, argv = runner(tmp_path, "FAIL", 1)
    outcome = dispatch._RunnerBudget(1, 1, 1).run(argv)
    assert outcome.rc == 1 and outcome.error is None
    report, why = attribution.step_report(project)
    ledger = dispatch._required_gate_ledger({"phases": {
        "phase3_verifying": attribution.phase3_verifying(report, why)}})
    assert ledger["eligibility"] == "INELIGIBLE"
    assert ledger["failed_required"] == ["rtl_validation_and_lint"]


def test_missing_native_report_stays_unmeasured(tmp_path):
    project, _, argv = runner(tmp_path)
    outcome = dispatch._RunnerBudget(1, 1, 1).run(argv)
    (project / "reports/flow_engine.json").unlink()
    result = dispatch._collect_runner_result(outcome, argv, "rtllm", "neutral", project)
    assert result["ok"] is False
    assert result["runner_diagnostics"]["status"] == "NOT_MEASURED"


def test_logging_failure_does_not_change_native_tool_result(tmp_path, monkeypatch):
    project, _, argv = runner(tmp_path)
    def unavailable(*_args, **_kwargs):
        raise OSError("diagnostic directory unavailable")
    monkeypatch.setattr(dispatch, "_atomic_write_json", unavailable)
    outcome = dispatch._RunnerBudget(1, 1, 1).run(argv)
    assert outcome.rc == 0 and outcome.error is None
    assert "unavailable" in outcome.invocation["log_error"]
    assert dispatch._runner_diagnostics(outcome, argv, project)["native_verdict"] == "PASS"


@pytest.mark.parametrize("unknown", ["BLOCKED", "UNRECOGNIZED"])
def test_unknown_native_status_cannot_become_a_pass(unknown):
    verifying = attribution.phase3_verifying({"steps": [
        {"name": "lint", "status": "PASS"},
        {"name": "sim", "status": unknown}],
        "native_selected_steps": 2, "native_steps_recorded": 2}, None)
    ledger = dispatch._required_gate_ledger({"phases": {"phase3_verifying": verifying}})
    assert ledger["eligibility"] == "NOT_MEASURED"
    assert ledger["in_scope"]["sim"] == unknown
    assert ledger["unmeasured_required"] == ["sim"]


def test_native_phase1_result_needs_no_activation(tmp_path):
    reports = tmp_path / "reports/orchestrator"
    reports.mkdir(parents=True)
    (reports / "phase1_one_shot.json").write_text(json.dumps({"verdict": "PASS"}))
    assert dispatch._phase1_native_status(tmp_path) == "PASS"
    (tmp_path / "reports/flow_engine.json").write_text(json.dumps({"steps": [
        {"name": "requirements_and_delivery_route", "status": "FAIL"}]}))
    assert dispatch._phase1_native_status(tmp_path) == "FAIL"


def test_runner_timeout_preserves_process_failure(tmp_path, monkeypatch):
    _, script, argv = runner(tmp_path)
    script.write_text("import time\ntime.sleep(5)\n")
    monkeypatch.setenv("VIBEIC_SOLVE_RUNNER_TIMEOUT_S", "0.05")
    outcome = dispatch._RunnerBudget(1, 1, 1).run(argv)
    assert outcome.rc is None
    assert "TimeoutExpired" in outcome.error


def test_phase1_frontdoor_reads_native_result_without_an_activation(tmp_path):
    project, script, _ = runner(tmp_path)
    script.write_text(
        "import json, pathlib, sys\n"
        "project = pathlib.Path(sys.argv[1])\n"
        "reports = project / 'reports/orchestrator'\n"
        "reports.mkdir(parents=True, exist_ok=True)\n"
        "(reports / 'phase1_one_shot.json').write_text(json.dumps({'verdict': 'PASS', 'steps': [{'name': 'document_extraction', 'status': 'PASS'}]}))\n"
        "docs = project / 'phase1/generated_docs'\n"
        "docs.mkdir(parents=True, exist_ok=True)\n"
        "(docs / 'L1_REQUIREMENTS.json').write_text('{}')\n"
        "print('document extraction completed')\n")
    result = dispatch._ensure_phase1_frontdoor(
        script, project, dispatch._RunnerBudget(1, 1, 1), force_current=True)
    assert result["status"] == "GENERATED", result
    assert result["native_verdict"] == "PASS"
    assert result["runner_rc"] == 0
    assert not (project / "reports/orchestrator/receipts").exists()
    repeated = dispatch._ensure_phase1_frontdoor(
        script, project, dispatch._RunnerBudget(1, 1, 1))
    assert repeated["status"] == "REUSED"


def test_structured_route_reentry_reads_native_phase1(tmp_path, monkeypatch):
    run = tmp_path / "run"
    project = run / "projects/neutral"
    reports = project / "reports/orchestrator"
    reports.mkdir(parents=True)
    (reports / "phase1_one_shot.json").write_text(json.dumps({"verdict": "PASS"}))
    receipt = {"delivery_target": "ip_hardmacro", "input_contract": "structured",
               "entry_step": "2", "verify_through": "2"}
    monkeypatch.setattr(dispatch, "_read_current_receipt", lambda *_args: {"receipt": receipt})
    monkeypatch.setattr(dispatch, "_require_route_admission", lambda *_args: None)
    import route_decision
    monkeypatch.setattr(route_decision, "validate_route_receipt", lambda _receipt: [])
    state = dispatch._validated_route_reentry_state(
        bench="neutral", dataset=None, fmt=None, run_p=run, pid="neutral",
        result={"route_receipt": receipt},
        route_worklist=[{"id": "neutral", "project": str(project)}], allow_d1_only=False)
    assert state["status"] == "ACTIVE"
    assert state["effective_entry"] == state["exit_step"] == "2"
    assert "activation" not in state
    assert not (project / "reports/orchestrator/receipts").exists()


@pytest.mark.parametrize("payload,expected", [
    ("not-json", "NOT_MEASURED"),
    (json.dumps({"steps": {}}), "NOT_MEASURED"),
    (json.dumps({"steps": [{"name": "rtl_validate", "status": "PASS"}]}), "REPORTS_AVAILABLE"),
])
def test_owner_fallback_handles_unreadable_or_incomplete_reports(tmp_path, payload, expected):
    from flow_engine_frontend import native_diagnostics
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(payload)
    result = native_diagnostics(dispatch._ProcessOutcome(0, stdout="", stderr=""), [], tmp_path)
    assert result["status"] == expected
    if expected == "REPORTS_AVAILABLE":
        assert result["native_verdict"] == "NOT_MEASURED"
