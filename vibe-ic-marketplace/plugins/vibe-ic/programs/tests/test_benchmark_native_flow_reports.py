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
