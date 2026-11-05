"""Caller selection controls with explicit accepted-upstream boundary doubles."""
import json

import pytest
import design_one_shot_runner as runner
import flow109


@pytest.fixture
def accepted(tmp_path, monkeypatch):
    context = tmp_path / 'context.json'
    context.write_text(json.dumps({'requested_step': 'D30'}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context))
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda value: value)
    proof = {'functional_equivalence': {'path': 'reports/lec_eqy.json'}}
    monkeypatch.setattr(flow109, 'dft_preroute_admission', lambda *_: proof)
    mapped = {'result': {'site': 'step_sdc_validation_post_prelayout'}}
    monkeypatch.setattr(runner, '_current_phase2_consumer', lambda *_: mapped)
    reached = []

    def stop_before_producer(*args, **kwargs):
        reached.append(args[1])
        raise RuntimeError('TEST ONLY: stop before handoff production')

    monkeypatch.setattr(runner._spf, 'retained_call', stop_before_producer)
    return tmp_path, proof, mapped, reached


@pytest.mark.parametrize('path', ['reports/lec_eqy_execution.json', 'reports/lec_eqy.json'])
def test_accepted_native_report_reaches_handoff(accepted, path):
    project, proof, _, reached = accepted
    proof['functional_equivalence']['path'] = path
    result = runner.step_synthesis_handoff(project, plan=[])
    assert reached == ['14']
    assert result.status == 'NOT_MEASURED'  # no native delivery was executed


@pytest.mark.parametrize('damage', ['native_refusal', 'missing_sdc', 'early_sdc', 'measured_failure'])
def test_refused_upstream_cannot_reach_handoff(accepted, monkeypatch, damage):
    project, _, mapped, reached = accepted
    plan = []
    if damage == 'native_refusal':
        def refused(*_):
            raise flow109.Flow109Error('FLOW109_D25_PROOF_NOT_ACCEPTED', 'TEST ONLY')
        monkeypatch.setattr(flow109, 'dft_preroute_admission', refused)
    elif damage == 'missing_sdc':
        monkeypatch.setattr(runner, '_current_phase2_consumer', lambda *_: None)
    elif damage == 'early_sdc':
        mapped['result']['site'] = 'step_sdc_validation'
    else:
        plan.append(runner.StepResult('lec_equivalence', 'FAIL', 0, 'TEST ONLY'))
    result = runner.step_synthesis_handoff(project, plan=plan)
    assert not reached
    assert result.status == 'NOT_MEASURED'
