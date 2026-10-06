"""Focused normal-dispatch controls for the external Ultra choice handoff."""
import json
from dataclasses import replace
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_modes as em
import execution_policy as policy
from programs.tests import test_execution_modes as H


def _runtime(tmp_path, monkeypatch, *, arms=None, response=None, wait_s=2, mode='ultra'):
    project = (tmp_path / 'project').resolve()
    project.mkdir(parents=True)
    input_path = project / 'source.txt'
    input_path.write_text('one input\n')
    arms = arms or (H.adapter('a', cost=8), H.adapter('b', cost=3))
    controller = H.controller(*arms)
    neutral_route = {'kind': 'neutral-test', 'ic_ip_path': 'IC'}
    monkeypatch.setattr(em, 'Context', H.NeutralContext)
    monkeypatch.setattr(policy, '_fixed_inputs', lambda runtime, step: {'text.txt': input_path})
    monkeypatch.setattr(policy, 'controller_fields', lambda **kwargs: {
        'ic_ip_path': 'IC', 'route_receipt': neutral_route,
        'intent_label': 'PROGRAM_DEFAULT', 'request_digest': ''})
    monkeypatch.setattr(policy, '_ordinary_runtime', {
        'identity': ('neutral-test',), 'project': project,
        'policy': {'mode': mode, 'choice': str(response.resolve()) if response else None,
                   'choice_wait_s': wait_s,
                   'request_receipt': {'invocation_id': 'wait-test-invocation'}},
        'route': {'source_sha': H.BASE, 'project_digest': '', 'ic_ip_path': 'IC',
                  'route_receipt': neutral_route},
        'parameters': {}, 'registry': controller.registry, 'controller': controller,
        'contexts': {}, 'bindings': {}, 'runs': {},
    })
    return project, controller, input_path, policy._ordinary_runtime


def _dispatch_in_thread(project, response, outcome):
    try:
        outcome['result'] = policy.dispatch_fixed_step(project, '1')
    except BaseException as exc:  # test thread must return the exact Controller refusal
        outcome['error'] = exc


def _wait_request(runtime, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = runtime['runs']
        if runs:
            request = runs['1'][0] / 'selection-request.json'
            if request.is_file():
                return request
        time.sleep(.01)
    raise AssertionError('selection request was not published')


def test_delayed_core_choice_is_adopted_and_imported_in_same_dispatch(tmp_path, monkeypatch, capsys):
    response = tmp_path / 'choice.json'
    project, controller, _, runtime = _runtime(tmp_path, monkeypatch, response=response)
    outcome = {}
    thread = threading.Thread(target=_dispatch_in_thread, args=(project, response, outcome))
    thread.start()
    request_path = _wait_request(runtime)
    request = json.loads(request_path.read_text())
    assert request['step_id'] == '1'
    assert request['response_path'] == str(response.resolve())
    assert len(request['eligible_arms']) == 2
    assert all(Path(row['receipt_path']).is_file() and row['receipt_sha256']
               for row in request['eligible_arms'])
    ctx = runtime['contexts']['1']
    run = runtime['runs']['1'][0]
    response.write_text(json.dumps(H.choice(ctx, run, 'b')))
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert 'error' not in outcome
    assert outcome['result']['status'] == 'ADOPTED'
    assert outcome['result']['selected'] == 'b'
    assert (project / 'value.txt').read_text() == 'ONE INPUT\n'
    assert controller.verify_adoption(ctx, run)['selected'] == 'b'
    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert event['type'] == 'vibeic.ai_selection_request'
    assert event['binding'] == request['binding']


def test_step9_adoption_uses_product_importer_for_current_project(tmp_path, monkeypatch):
    project = (tmp_path / 'project').resolve()
    project.mkdir()
    input_path = project / 'source.txt'
    input_path.write_text('one input\n')
    arm = replace(H.adapter('a'), step_id='9')
    registry = em.Registry()
    registry.register(arm)
    controller = em.Controller(registry, em.Budget(2, 512), {
        'meta': {'test_only': True},
        'steps': [{'id': '9', 'mandatory_gate_programs': ['transform'],
                   'required_output_contract': ['value.txt', 'measurement.json']}],
    })
    neutral_route = {'kind': 'neutral-test', 'ic_ip_path': 'IC'}
    monkeypatch.setattr(em, 'Context', H.NeutralContext)
    monkeypatch.setattr(policy, '_fixed_inputs',
                        lambda runtime, step: {'text.txt': input_path})
    monkeypatch.setattr(policy, 'controller_fields', lambda **kwargs: {
        'ic_ip_path': 'IC', 'route_receipt': neutral_route,
        'intent_label': 'PROGRAM_DEFAULT', 'request_digest': ''})
    runtime = {
        'identity': ('neutral-step9',), 'project': project,
        'policy': {'mode': 'ultra', 'choice': None, 'choice_wait_s': 0,
                   'request_receipt': {'invocation_id': 'step9-import-test'}},
        'route': {'source_sha': H.BASE, 'project_digest': '', 'ic_ip_path': 'IC',
                  'route_receipt': neutral_route},
        'parameters': {}, 'registry': registry, 'controller': controller,
        'contexts': {}, 'bindings': {}, 'runs': {},
    }
    monkeypatch.setattr(policy, '_ordinary_runtime', runtime)
    # This neutral transform fixture measures importer transport. Native
    # installation and late input binding have their own lifecycle controls.
    preparations = []
    monkeypatch.setattr(policy, '_prepare_step9',
                        lambda current, parameters: preparations.append((current, parameters)))
    pending = policy.dispatch_fixed_step(project, '9')
    assert pending['status'] == 'AWAITING_AI_SELECTION'
    ctx = runtime['contexts']['9']
    run = runtime['runs']['9'][0]
    calls = []

    def import_selected(current_project, current_context, current_controller,
                        current_run, adoption):
        calls.append((current_project, current_context, current_controller,
                      current_run, adoption))
        (current_project / 'phase2/stage2/synth').mkdir(parents=True)
        (current_project / 'phase2/stage2/synth/netlist.v').write_text(
            'module top; endmodule\n')
        return {'status': 'IMPORTED', 'copied': {
            'phase2/stage2/synth/netlist.v': 'test-digest'}}

    import execution_production as production
    monkeypatch.setattr(production, 'import_selected', import_selected)
    adopted = policy.dispatch_fixed_step(project, '9',
                                         choice=H.choice(ctx, run, 'a'))
    assert adopted['status'] == 'ADOPTED'
    assert adopted['consumer']['status'] == 'IMPORTED'
    assert (project / 'phase2/stage2/synth/netlist.v').is_file()
    assert not (project / 'project').exists()
    assert len(calls) == 1
    assert calls[0][:4] == (project, ctx, controller, run)
    assert calls[0][4]['selected'] == 'a'
    assert preparations == [(runtime, {}), (runtime, {})]


def test_no_choice_times_out_without_adoption_or_import(tmp_path, monkeypatch):
    response = tmp_path / 'choice.json'
    project, _, _, runtime = _runtime(tmp_path, monkeypatch, response=response, wait_s=1)
    result = policy.dispatch_fixed_step(project, '1')
    run = runtime['runs']['1'][0]
    assert result['status'] == 'AWAITING_AI_SELECTION'
    assert (run / 'selection-request.json').is_file()
    assert not (run / 'adoption.json').exists()
    assert not (project / 'value.txt').exists()


def test_unchanged_previous_step_response_is_ignored(tmp_path, monkeypatch):
    old_root = tmp_path / 'old-run'
    old_project = tmp_path / 'old-project'
    old_project.mkdir()
    old_ctx = H.context(old_project)
    old_controller = H.controller(H.adapter('a', cost=8), H.adapter('b', cost=3))
    old_controller.run(old_ctx, old_root, 'ultra-mode')
    stale = H.choice(old_ctx, old_root, 'b')
    response = tmp_path / 'choice.json'
    response.write_text(json.dumps(stale))
    project, _, _, runtime = _runtime(tmp_path / 'current', monkeypatch,
                                      response=response, wait_s=1)
    result = policy.dispatch_fixed_step(project, '1')
    run = runtime['runs']['1'][0]
    assert result['status'] == 'AWAITING_AI_SELECTION'
    assert not (run / 'adoption.json').exists()
    assert not (project / 'value.txt').exists()


def test_new_wrong_receipt_digest_is_refused_by_core(tmp_path, monkeypatch):
    response = tmp_path / 'choice.json'
    project, _, _, runtime = _runtime(tmp_path, monkeypatch, response=response)
    outcome = {}
    thread = threading.Thread(target=_dispatch_in_thread, args=(project, response, outcome))
    thread.start()
    _wait_request(runtime)
    ctx = runtime['contexts']['1']
    run = runtime['runs']['1'][0]
    bad = H.choice(ctx, run, 'b')
    bad['receipt_sha256'] = '0' * 64
    response.write_text(json.dumps(bad))
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert isinstance(outcome.get('error'), em.Refusal)
    assert outcome['error'].code == 'AI_RECEIPT_DIGEST_MISMATCH'


@pytest.mark.parametrize('fault,expected', [
    ('fail_gate', 'FAIL'), ('process_error', 'NOT_MEASURED'),
])
def test_terminal_fail_or_unmeasured_does_not_read_shared_response(
        tmp_path, monkeypatch, fault, expected):
    response = tmp_path / 'choice.json'
    response.write_text('not-json')
    project, _, _, runtime = _runtime(
        tmp_path, monkeypatch, arms=(H.adapter('a', fault=fault),), response=response)
    result = policy.dispatch_fixed_step(project, '1')
    run = runtime['runs']['1'][0]
    assert result['status'] == expected
    assert not (run / 'selection-request.json').exists()
    assert not (run / 'adoption.json').exists()
    assert not (project / 'value.txt').exists()


def test_default_without_live_runtime_does_not_wait(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    monkeypatch.setattr(policy, '_wait_for_choice', lambda *args: called.append(args))
    assert policy.dispatch_fixed_step(tmp_path, '1') is None
    assert called == []


def test_explicit_choice_still_reaches_core_for_terminal_result(tmp_path, monkeypatch):
    response = tmp_path / 'choice.json'
    response.write_text('not-json')
    project, _, _, runtime = _runtime(
        tmp_path, monkeypatch, arms=(H.adapter('a', fault='fail_gate'),),
        response=response)
    first = policy.dispatch_fixed_step(project, '1')
    ctx = runtime['contexts']['1']
    run = runtime['runs']['1'][0]
    assert first['status'] == 'FAIL'
    with pytest.raises(em.Refusal, match='AI_CHOICE_INELIGIBLE'):
        policy.dispatch_fixed_step(project, '1', choice=H.choice(ctx, run, 'a'))
    assert not (run / 'selection-request.json').exists()
