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
def test_plain_container_selection_needs_no_image_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBEIC_EDA_CONTAINER", "selected-container")
    monkeypatch.delenv("VIBEIC_CHALLENGE_BACKEND", raising=False)
    assert dispatch._challenge_execution_declaration(tmp_path) == {
        "backend": "native", "selection": "explicit existing container",
        "container": "selected-container"}
    assert not list(tmp_path.iterdir())
    config = tmp_path / ".bench_config.json"
    config.write_text(json.dumps({"tool_container": "recorded-container"}))
    monkeypatch.delenv("VIBEIC_EDA_CONTAINER")
    assert dispatch._recorded_benchmark_container(tmp_path) == "recorded-container"


def challenge_fixture(tmp_path, expected):
    project = tmp_path / "project"
    rtl = project / "phase2/stage1/rtl/neutral.v"
    rtl.parent.mkdir(parents=True)
    body = "module neutral(output wire y); assign y=1'b1; endmodule\n"
    rtl.write_text(body)
    candidate = dispatch._archive_candidate("neutral", project,
        {"ok": True, "completion": body}, tmp_path / "run", "PROGRAM")
    tb = tmp_path / "challenge.sv"
    tb.write_text("module vibeic_ai_challenge_tb; wire y; neutral dut(.y(y));\n"
                  f"initial begin #1; if (y !== 1'b{expected}) begin $display(\"VIBEIC_AI_CHALLENGE=FAIL\"); $fatal(1, \"assertion failed\"); end\n"
                  "$display(\"VIBEIC_AI_CHALLENGE=PASS\"); $finish; end endmodule\n")
    return candidate, {"path": str(tb), "sha256": dispatch._sha256_text(tb.read_text())}


@pytest.mark.parametrize("expected,status", [(1, "PASS"), (0, "FAIL")])
def test_real_iverilog_challenge_keeps_native_verdict(tmp_path, expected, status):
    import shutil
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Icarus tools are unavailable on this test host")
    candidate, challenge = challenge_fixture(tmp_path, expected)
    result = dispatch._run_verification_challenge(candidate, challenge)
    assert result["status"] == status, result
    commands = result["execution"]["commands"]
    assert next(command for command in commands if command["stage"] == "compile")["returncode"] == 0
    simulation = next(command for command in commands if command["stage"] == "runtime")
    assert (simulation["returncode"] == 0) is (status == "PASS")


def test_native_challenge_executes_without_a_runtime_passport(tmp_path, monkeypatch):
    import shutil
    import subprocess
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Icarus tools are unavailable on this test host")
    candidate, challenge = challenge_fixture(tmp_path, 1)
    challenge["execution_backend"] = {"backend": "native", "container": "selected-container"}
    def inspect_mounts(argv, **_kwargs):
        assert argv == ["docker", "inspect", "--format", "{{json .Mounts}}", "selected-container"]
        return subprocess.CompletedProcess(argv, 0, json.dumps([
            {"Type": "bind", "Source": str(tmp_path), "Destination": str(tmp_path), "RW": True}]), "")
    def supervised(container, command, **_kwargs):
        assert container == "selected-container"
        if " -V" in command:
            return subprocess.CompletedProcess(["bash", "-lc", command], 1, "version unavailable", "")
        return subprocess.run(["bash", "-lc", command], capture_output=True, text=True)
    monkeypatch.setattr(dispatch._progress_run, "run", inspect_mounts)
    monkeypatch.setattr(dispatch._challenge_exec, "run_in_container_supervised", supervised)
    result = dispatch._run_verification_challenge(candidate, challenge)
    assert result["status"] == "PASS", result
    assert not any(key.startswith("identity_") for key in result["execution"])
    assert not (tmp_path / "ai_verification_challenges/native_execution.json").exists()
