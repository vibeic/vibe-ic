"""A reasoned non-scan input can run the ordinary producer and native copy."""
import hashlib
import json
from pathlib import Path

import pytest
import design_one_shot_runner as runner
import vibe_ic_one_shot_runner as public
import flow109
from test_flow109_selection import profile


def case(project, monkeypatch, status='NOT_MEASURED', produced=True):
    decision = project / 'input/feature-decisions.json'
    decision.parent.mkdir(parents=True)
    decision.write_text(json.dumps({'dft': {'requires_scan': False,
        'reason': 'The delivered functional logic has no requested scan interface or scan insertion requirement.'}}))
    context = flow109.execution_context(flow109.resolve_plan(profile('Small digital IC without DFT')), 'D19', 'D19')
    context_file = project / 'context.json'
    context_file.write_text(json.dumps(context))
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(context_file))
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    sdc = project / 'phase2/stage2/constraints/asic.sdc'
    sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -name core -period 10 [get_ports clk_i]\n')
    record = {'path': str(sdc.relative_to(project)),
              'sha256': hashlib.sha256(sdc.read_bytes()).hexdigest(), 'pdk': 'sky130A'}
    extras = {'step7_record': record, 'corner_count': 3 if produced else 1}
    if produced:
        extras.update(producer_status='PASS', deferred_until='post_prelayout')
    monkeypatch.setattr(runner, '_step_asic_sdc_producer', lambda *args, **kwargs:
        runner.StepResult('asic_sdc', status, extras=dict(extras),
                          reason_class='input_absent' if status == 'NOT_MEASURED' else ''))
    monkeypatch.setattr(flow109, '_new_attempt', lambda *args: project / 'native-attempt')
    return context, sdc


def test_non_scan_fact_reaches_actual_native_copy_without_plan_envelope(tmp_path, monkeypatch):
    _, source = case(tmp_path, monkeypatch)
    result = runner.step_asic_sdc(tmp_path, 'neutral', pdk_name='sky130A', _use_controller=False)
    assert result.status == 'PASS', result.detail
    copies = result.extras['native_sdc_outputs']
    assert len(copies) == 1
    assert (tmp_path / copies[0]['sdc']['path']).read_bytes() == source.read_bytes()
    assert result.extras['qualification'] == 'NOT_MEASURED'


@pytest.mark.parametrize('status,produced', [('FAIL', True), ('NOT_MEASURED', False)])
def test_failed_or_partial_producer_cannot_become_native_pass(tmp_path, monkeypatch, status, produced):
    case(tmp_path, monkeypatch, status, produced)
    monkeypatch.setattr(runner, '_d19_load_base_sdc', lambda *args: pytest.fail('incomplete producer must not copy'))
    result = runner.step_asic_sdc(tmp_path, 'neutral', pdk_name='sky130A', _use_controller=False)
    assert result.status == status, result.detail
    assert result.extras.get('completed') is not True


def test_parent_publishes_fresh_native_result_without_metric_reacceptance(tmp_path, monkeypatch):
    import flow109_metric_acceptance as metrics
    monkeypatch.setattr(metrics, 'accept_d19', lambda *args: pytest.fail('legacy acceptance is not a native result'))
    report = {'steps': [{'name': 'asic_sdc', 'status': 'PASS', 'extras': {'step_id': '7', 'completed': True}}]}
    seen = []
    monkeypatch.setattr(flow109, 'finish_native_window', lambda project, result:
        seen.append(result) or {'default_row_status': result['steps'][0]['status']})
    result = public._finish_d19_selected_owner(tmp_path, report, {}, published_current=True)
    assert result['verdict'] == 'PASS' and seen == [report]
    result = public._finish_d19_selected_owner(tmp_path, report, {}, published_current=False)
    assert result['verdict'] == 'NOT_MEASURED' and len(seen) == 1
    report['steps'][0]['status'] = 'FAIL'
    result = public._finish_d19_selected_owner(tmp_path, report, {}, published_current=True)
    assert result['verdict'] == 'FAIL' and len(seen) == 2
