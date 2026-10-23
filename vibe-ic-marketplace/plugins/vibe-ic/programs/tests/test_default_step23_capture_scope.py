"""Default must judge current DRV evidence before final GDS/LVS exists.

These are scheduling/consumer controls with native instruments controlled.
They establish neither a native DRV measurement nor whole-IC acceptance.
"""
import copy
import importlib
import shlex
import sys

import pytest

import execution_backend_gates as gates
import execution_backend_producers as producers
import execution_backend_worker as worker
import flow_compliance_check as compliance
import phase3_one_shot_runner as runner


def _capture_point(row):
    commands = [c['program_exit_zero'] for c in row['gate']['all_of']
                if c.get('program_exit_zero', '').startswith('drv_signoff_judge ')]
    assert len(commands) == 1
    args = shlex.split(commands[0])
    return args[args.index('--capture-point') + 1]


def _schedule(monkeypatch, project, mode, verdict='PASS'):
    seen = []
    monkeypatch.setattr(producers, 'produce_signoff', lambda *a: {'verdict': 'PASS'})
    monkeypatch.setattr(producers, '_native_current_step_producer', lambda *a: None)
    monkeypatch.setattr(producers, '_run_current_step_declared_producers', lambda *a: {})
    monkeypatch.setattr(producers, '_current_step_producer_authority',
                        lambda *a, **k: (True, '', 'PASS'))

    def instrument(project, name, program, output, extra):
        seen.append((name, tuple(extra)))
        status = verdict if name == 'drv_signoff' else 'PASS'
        return runner.StepResult(
            name, status, 0, 'controlled capture result',
            reason_class=runner._V.ReasonClass.NOT_EXECUTED if status == 'NOT_MEASURED' else '')

    monkeypatch.setattr(runner, '_run_declared_signoff_gate', instrument)
    result = producers.produce(project, {'step_id': '23', 'execution_mode': mode})
    return result, seen


@pytest.mark.parametrize('mode', ['default', 'ultra'])
def test_only_default_current_step_schedules_the_existing_in_flow_capture(tmp_path, monkeypatch, mode):
    result, seen = _schedule(monkeypatch, tmp_path, mode)
    capture = [extra for name, extra in seen if name == 'drv_signoff']
    assert capture == ([()] if mode == 'default' else [])
    assert result['verdict'] == 'PASS'


@pytest.mark.parametrize('verdict', ['FAIL', 'NOT_MEASURED'])
def test_default_refuses_when_the_fresh_drv_capture_is_not_pass(tmp_path, monkeypatch, verdict):
    result, seen = _schedule(monkeypatch, tmp_path, 'default', verdict)
    assert any(name == 'drv_signoff' for name, _ in seen)
    assert result['verdict'] == verdict


def test_default_current_consumer_does_not_borrow_final_drv_credit(tmp_path, monkeypatch):
    canonical = copy.deepcopy(worker.ROWS['23']['canonical_row'])
    final_row = copy.deepcopy(worker.ROWS['31']['canonical_row'])
    observed = []

    def controlled_in_flow_instrument(project, row, waivers, **kwargs):
        if str(row['id']) == '23':
            commands = [c.get('program_exit_zero', '')
                        for c in row['gate']['all_of']]
            assert not any(c.startswith('drv_signoff_judge ') for c in commands)
            point = None
        else:
            point = _capture_point(row)
        observed.append(point)
        # The controlled instrument has no final GDS/LVS. Step23 no longer
        # owns final DRV acceptance; Step31 must still require that identity.
        status = 'PASS' if point is None else 'NOT_MEASURED'
        return compliance.StepResult(id=row['id'], name=row['name'], stage=row['stage'], status=status)

    # Reproduce the full-process alias shape: a package-qualified alias retains
    # the module this test imported, while the evaluator's top-level dynamic
    # import resolves a distinct current module instance. Patch that actual
    # consumer, not this stale alias and not either evaluator.
    monkeypatch.setitem(sys.modules, 'programs.flow_compliance_check', compliance)
    monkeypatch.delitem(sys.modules, 'flow_compliance_check')
    consumed_compliance = importlib.import_module('flow_compliance_check')
    assert consumed_compliance is not compliance
    assert sys.modules['programs.flow_compliance_check'] is compliance
    assert worker.evaluate is gates.evaluate
    monkeypatch.setattr(consumed_compliance, 'check_step', controlled_in_flow_instrument)
    monkeypatch.setattr(worker, '_current_step_producer_authority',
                        lambda *a, **k: (True, '', 'PASS'))
    monkeypatch.setattr(worker, 'resolve_contract', lambda *a: ({}, []))
    result = worker.execute_current_step(tmp_path, step_id='23', producer={'verdict': 'PASS'})
    assert result['verdict'] == 'PASS', result
    assert observed == [None]
    assert worker.evaluate is gates.evaluate
    assert sys.modules['flow_compliance_check'] is consumed_compliance
    assert worker.ROWS['23']['canonical_row'] == canonical
    final = gates.evaluate(tmp_path, final_row)
    assert observed == [None, 'post_stream']
    assert final['status'] == 'NOT_MEASURED'
    assert worker.evaluate is gates.evaluate
    assert worker.ROWS['31']['canonical_row'] == final_row


def test_final_capture_table_still_requires_post_stream_identity():
    final = next(row for row in runner._DECLARED_SIGNOFF_GATES if row[0] == 'drv_signoff')
    current = next(row for row in runner._PRESTREAM_GATES if row[0] == 'drv_signoff')
    assert final[3] == ('--capture-point', 'post_stream')
    assert current[3] == ()


@pytest.mark.parametrize('verdict', ['FAIL', 'NOT_MEASURED'])
def test_capture_failure_detail_survives_backend_and_receipt(tmp_path, monkeypatch, verdict):
    result, _ = _schedule(monkeypatch, tmp_path, 'default', verdict)
    assert 'drv_signoff: controlled capture result' in result['detail']
    assert result['canonical_receipts'][0]['detail'] == result['detail']


def test_native_current_sta_selection_reaches_capture_only(tmp_path, monkeypatch):
    selection = {'capture_step': '23', 'final': {
        'sta_state': '/current/23/state_out.json', 'sta_state_sha256': 'a' * 64}}
    _schedule(monkeypatch, tmp_path, 'default')
    monkeypatch.setattr(producers, 'produce_signoff', lambda *a: {
        'verdict': 'PASS', 'drv_final_state': selection})
    seen = []
    def instrument(project, name, program, output, extra, **kwargs):
        seen.append((name, kwargs))
        return runner.StepResult(name, 'PASS', 0, 'controlled result')
    monkeypatch.setattr(runner, '_run_declared_signoff_gate', instrument)
    result = producers.produce(tmp_path, {'step_id': '23', 'execution_mode': 'default'})
    assert result['verdict'] == 'PASS'
    assert [kwargs for name, kwargs in seen if name == 'drv_signoff'] == [
        {'drv_final_state': selection}]
    assert all(not kwargs for name, kwargs in seen if name != 'drv_signoff')


def test_current_capture_selection_is_passed_before_judge(tmp_path, monkeypatch):
    import drv_capture_plan
    selection = {'capture_step': '23', 'final': {'sta_state': 'current'}}
    seen = []
    def capture(project, *, final_state=None, capture_point='in_flow'):
        seen.append((project, final_state, capture_point))
        raise ValueError('RCX receipt image differs from producer image')
    monkeypatch.setattr(drv_capture_plan, 'capture_and_publish', capture)
    monkeypatch.setattr(runner._pr, 'run', lambda *a, **k: pytest.fail('judge ran after refused capture'))
    row = runner._run_declared_signoff_gate(tmp_path, 'drv_signoff',
        'drv_signoff_judge.py', 'reports/phase3/sta/drv_signoff.json',
        drv_final_state=selection)
    assert seen == [(tmp_path, selection, 'in_flow')]
    assert row.status == 'NOT_MEASURED'
    assert 'RCX receipt image differs from producer image' in row.detail
