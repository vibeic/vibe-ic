"""Ordinary adapter aggregates the native owner; SOFTWARE tool boundary."""
import json
from pathlib import Path

import pytest
import flow109
import flow109_frontend as frontend
import design_one_shot_runner as producer
import step_preflight
from test_flow109_selection import profile


def case(root, monkeypatch, mode):
    for rel, body in {
        'input/project.json': {'pdk': 'sky130A'},
        'phase1/generated_docs/L9_INTEGRATION_SPEC.json': {'top_module': 'unit'},
        'phase3/librelane_switch.json': {'steps': {'9': mode}},
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D22', 'D22')
    request = root / 'request.json'
    request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setattr(step_preflight, 'retained_call',
        lambda project, step, fn, *a, **kw: fn(*a, **{k:v for k,v in kw.items() if k != 'canonical_acceptance'}))
    return context


@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_ordinary_native_synthesis_keeps_original_result_and_ppa_scope(tmp_path, monkeypatch, status):
    context = case(tmp_path, monkeypatch, 'librelane')
    def native(project, top, *a, **kw):
        assert top == 'unit'
        for operation in frontend.STEPS:
            frontend.require_librelane_launch(project, operation)
        return producer.StepResult('yosys_synth', status, 0.0,
            'SOFTWARE boundary; original native consumer result',
            reason_class='input_absent' if status == 'NOT_MEASURED' else '', extras={
                'default_row_status': status, 'completed': status == 'PASS',
                'ppa_acceptance': 'NOT_MEASURED'})
    monkeypatch.setattr(producer, 'step_yosys_synth', native)
    monkeypatch.setattr(frontend, '_canonical_publication', lambda *a:
        pytest.fail('ordinary native synthesis must not reopen generic die-area admission'))
    observed = frontend._execute_d22(tmp_path, context)
    assert observed['component_status'] == status, observed
    assert observed['native_started'] is True
    assert observed['producer']['extras']['ppa_acceptance'] == 'NOT_MEASURED'
    assert observed.get('completed') is True if status == 'PASS' else observed.get('completed') is not True


def test_direct_generic_synthesis_cannot_be_a_native_mapped_result(tmp_path, monkeypatch):
    context = case(tmp_path, monkeypatch, 'direct')
    monkeypatch.setattr(producer, 'step_yosys_synth', lambda *a, **kw:
        pytest.fail('generic synthesis is not the selected mapped owner'))
    observed = frontend._execute_d22(tmp_path, context)
    assert observed['component_status'] == 'NOT_MEASURED'
    assert observed['native_started'] is False
    assert observed['reason'] == 'D22_ROUTE_UNSUPPORTED'
