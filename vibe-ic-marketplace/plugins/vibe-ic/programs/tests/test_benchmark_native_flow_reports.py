"""Benchmark acceptance uses the native runner's selected tool results."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_dispatch as dispatch
import flow_phase_attribution as attribution


def native_result(project, status, selected=1):
    reports = project / 'reports'
    (reports / 'orchestrator').mkdir(parents=True)
    (reports / 'flow_engine.json').write_text(json.dumps({
        'selected': selected,
        'steps': [{'name': 'rtl_lint', 'status': status, 'tool_ran': True}],
    }))
    (reports / 'orchestrator/phase2_one_shot.json').write_text(json.dumps({
        'steps': [{'name': 'rtl_gen', 'status': 'NOT_APPLICABLE'}],
    }))
    report, why = attribution.step_report(project)
    return {'exit': '2', 'phases': {
        'phase3_verifying': attribution.phase3_verifying(report, why),
    }}


def test_native_tool_failure_prevents_acceptance(tmp_path):
    ledger = dispatch._required_gate_ledger(native_result(tmp_path, 'FAIL'))
    assert ledger['eligibility'] == 'INELIGIBLE'
    assert ledger['failed_required'] == ['rtl_lint']


def test_bounded_native_pass_is_eligible_without_other_flow_rows(tmp_path):
    ledger = dispatch._required_gate_ledger(native_result(tmp_path, 'PASS'))
    assert ledger['eligibility'] == 'ELIGIBLE'
    assert ledger['in_scope'] == {'rtl_lint': 'PASS'}


def test_unfinished_native_window_is_not_measured(tmp_path):
    ledger = dispatch._required_gate_ledger(native_result(tmp_path, 'PASS', selected=2))
    assert ledger['eligibility'] == 'NOT_MEASURED'
    assert ledger['unmeasured_required'] == ['remaining selected steps']


def test_host_tools_need_no_runtime_supply_record(tmp_path, monkeypatch):
    monkeypatch.delenv('VIBEIC_EDA_CONTAINER', raising=False)
    monkeypatch.delenv('VIBEIC_CHALLENGE_BACKEND', raising=False)
    assert dispatch._challenge_execution_declaration(tmp_path) == {
        'backend': 'host', 'selection': 'installed host tools',
    }
    assert not list(tmp_path.iterdir())


def test_explicit_existing_container_is_forwarded_to_public_runner(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBEIC_EDA_CONTAINER', 'selected-existing-container')
    argv = dispatch._solver_argv(tmp_path / 'runner.py', tmp_path, '2', '2')
    assert argv[argv.index('--container') + 1] == 'selected-existing-container'


def test_native_only_authoring_report_collects_its_exact_rtl(tmp_path):
    import benchmark_io_adapter as adapter
    source = "module unit(input a, output y); assign y=a; endmodule\n"
    rtl = tmp_path / "phase2/stage1/rtl/unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(source)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "flow_engine.json").write_text(json.dumps({"route": {"entry_step": "1"},
        "steps": [{"name": "rtl_authoring", "status": "PASS"}]}))
    result = adapter.collect("rtllm", "neutral", tmp_path)
    assert result["ok"], result
    assert result["completion"] == source
    assert not (reports / "orchestrator/phase2_one_shot.json").exists()


def test_failed_native_authoring_does_not_reuse_a_stale_owner_pass(tmp_path):
    import benchmark_io_adapter as adapter
    rtl = tmp_path / "phase2/stage1/rtl/unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module unit; endmodule\n")
    reports = tmp_path / "reports"
    (reports / "orchestrator").mkdir(parents=True)
    (reports / "flow_engine.json").write_text(json.dumps({
        "steps": [{"name": "rtl_authoring", "status": "FAIL"}]}))
    (reports / "orchestrator/phase2_one_shot.json").write_text(json.dumps({
        "steps": [{"name": "rtl_gen", "status": "PASS"}]}))
    result = adapter.collect("rtllm", "neutral", tmp_path)
    assert result["ok"] is False
    assert result["rtl_gen"] == "FAIL"


def test_native_validation_window_requires_supplied_rtl_opt_in(tmp_path):
    import benchmark_io_adapter as adapter
    rtl = tmp_path / "phase2/stage1/rtl/unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module unit; endmodule\n")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "flow_engine.json").write_text(json.dumps({
        "route": {"entry_step": "2"},
        "steps": [{"name": "rtl_validation_and_lint", "status": "PASS"}]}))
    assert adapter.collect("rtllm", "neutral", tmp_path)["ok"] is False
    supplied = adapter.collect("rtllm", "neutral", tmp_path, supplied_rtl=True)
    assert supplied["ok"], supplied
    assert supplied["rtl_gen"] == "NOT_APPLICABLE"
