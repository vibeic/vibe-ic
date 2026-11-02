"""Synthetic retained source receipts; no real-IC or native submission credit."""
from argparse import Namespace
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import _flow_yaml
import execution_backend_gates as gates
import flow109
import flow109_metric_acceptance as metrics
import phase1_one_shot_runner as runner
import step_output_collector as versions
from programs.tests.test_flow109_phase1_metric_completion import (
    case, approve, write, synthetic_canonical_consumer)


def scoped_case(project, monkeypatch):
    payload, _ = case(project, monkeypatch)
    source = project / 'input/docs/spec.md'
    source.write_text('arithmetic_beta\nRTL\nhas_analog=false\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for population in payload.values():
        population['source_documents'] = [{'path': 'input/docs/spec.md', 'sha256': digest}]
        for item in [*population['expectations'], *population.get('features', [])]:
            item['evidence'] = [citation.replace('DIE', 'RTL').replace(
                citation.split('sha256:')[1][:64], digest) for citation in item['evidence']]
            if item.get('expected_tokens') == ['DIE']:
                item['expected_tokens'] = ['RTL']
    payload['endpoint_delivery_items']['assignments'][0]['endpoint'] = 'RTL'
    approve(project, payload)
    write(project, 'phase1/generated_docs/L1_DATASHEET.json', {
        'schema_version': 2, 'ic_name': 'arithmetic_beta', 'description': 'RTL', 'has_analog': False})
    (project / 'input/step_0_5ic_answers.json').unlink()
    # Retain only synthetic D1, never a native physical submission PASS.
    submission = versions.latest_pass(project, '0.5ic')
    shutil.rmtree(project / submission['storage_root'] / submission['folder'])
    native = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == 'D1')
    attempt = versions.begin_step(project, 'D1', {'input/docs/spec.md': digest})
    versions.finish_step(project, attempt, verdict='PASS', canonical_pass=True,
        result={'runner': 'phase1_one_shot_runner', 'producer_return': 0,
                'canonical_consumer': synthetic_canonical_consumer(project, native)})
    profile = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                                 if p['name'] == 'RTL-only'))
    manifest = project / 'input/flow109-manifest.json'
    write(project, 'input/flow109-manifest.json', {'features': profile})
    args = Namespace(flow='109', flow109_manifest=manifest, flow109_plan_only=False,
                     execution_mode='default', entry_step='D02', exit_step='D02',
                     delivery_target='rtl', route=None)
    monkeypatch.setenv(flow109.CONTEXT_ENV, '')
    monkeypatch.setenv(flow109.ATTEMPT_ENV, '')
    assert flow109.prepare_front_door(args, project) is None
    import os
    context = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_bytes())
    scope = flow109.active_rtl_scope(project)
    write(project, 'reports/phase1/submission_scope.json', {
        'name': 'submission_template', 'status': 'NOT_APPLICABLE',
        'reason': 'bounded RTL request has no physical submission obligation', 'delivery_scope': scope})
    return payload, context


def test_retained_completion_qualifies_real_endpoint_metrics_without_physical_pass(tmp_path, monkeypatch):
    scoped_case(tmp_path, monkeypatch)
    result = runner.complete_retained_metrics(tmp_path)
    assert result['default_row_status'] == 'PASS', result
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D02.json').read_bytes())
    acceptance = row['metric_acceptance']
    assert [o['status'] for o in acceptance['obligations']] == ['PASS', 'PASS']
    assert acceptance['admission']['native_step'] == 'D1'
    assert acceptance['admission']['submission_disposition']['status'] == 'NOT_APPLICABLE'
    assert versions.latest_pass(tmp_path, '0.5ic') is None
    assert not (tmp_path / 'input/step_0_5ic_answers.json').exists()
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['delivery_accepted'] is False


@pytest.mark.parametrize('change,expected', [
    ('unassigned', 'FAIL'), ('pending_approval', 'NOT_MEASURED'),
    ('missing_canonical', 'NOT_MEASURED'), ('partial_checks', 'NOT_MEASURED'),
])
def test_actual_completion_keeps_source_and_metric_guards(tmp_path, monkeypatch, change, expected):
    payload, _ = scoped_case(tmp_path, monkeypatch)
    if change == 'unassigned':
        payload['endpoint_delivery_items']['assignments'] = []
        approve(tmp_path, payload)
    elif change == 'pending_approval':
        path = tmp_path / 'requirements/base_02/endpoint_delivery_items.json'
        value = json.loads(path.read_bytes()); value['approval']['status'] = 'PENDING'
        write(tmp_path, path.relative_to(tmp_path).as_posix(), value)
    else:
        record = versions.latest_pass(tmp_path, 'D1')
        relative = record['storage_root'] + '/' + record['folder'] + '/outputs.json'
        value = json.loads((tmp_path / relative).read_bytes())
        if change == 'missing_canonical':
            value['canonical_pass'] = False
        else:
            consumer = value['result']['canonical_consumer']
            consumer['ledger'] = [item for item in consumer['ledger']
                                  if item['cmd'] != consumer['required_commands'][-1]]
        write(tmp_path, relative, value)
    result = runner.complete_retained_metrics(tmp_path)
    assert result['default_row_status'] == expected, result
    assert versions.latest_pass(tmp_path, '0.5ic') is None


@pytest.mark.parametrize('change', ['status', 'foreign_scope', 'stale_input'])
def test_direct_acceptor_rejects_unbound_submission_disposition(tmp_path, monkeypatch, change):
    _, context = scoped_case(tmp_path, monkeypatch)
    path = tmp_path / 'reports/phase1/submission_scope.json'
    value = json.loads(path.read_bytes())
    if change == 'status':
        value['status'] = 'PASS'
    elif change == 'foreign_scope':
        value['delivery_scope']['project'] += '/foreign'
    else:
        source = tmp_path / 'input/docs/spec.md'
        source.write_text(source.read_text() + 'A changed requirement.\n')
    write(tmp_path, path.relative_to(tmp_path).as_posix(), value)
    result = metrics.accept_d02(tmp_path, context)
    assert result['status'] == 'NOT_MEASURED', result
    if change != 'stale_input':
        assert result['reason'] == 'D02_RTL_SUBMISSION_SCOPE_UNBOUND', result


def test_all_real_reference_profiles_keep_d02_selected():
    for profile in flow109.load_registry()['reference_profiles']:
        plan = flow109.resolve_plan(profile['features'])
        assert 'D02' in {row['id'] for row in plan['rows']}


@pytest.mark.parametrize('endpoint', ['source', 'rtl'])
@pytest.mark.parametrize('change', ['nonrequired_absent', 'required_only', 'conditional_activated'])
def test_direct_producer_requires_complete_applicable_ledger(tmp_path, monkeypatch, endpoint, change):
    if endpoint == 'rtl':
        scoped_case(tmp_path, monkeypatch)
        step = 'D02'
    else:
        case(tmp_path, monkeypatch)
        step = 'D01'
    native = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == 'D1')
    invocations = gates.program_invocations(native)
    record = versions.latest_pass(tmp_path, 'D1')
    relative = record['storage_root'] + '/' + record['folder'] + '/outputs.json'
    value = json.loads((tmp_path / relative).read_bytes())
    consumer = value['result']['canonical_consumer']
    if change == 'conditional_activated':
        conditional = next(item for item in invocations if item['condition_files_exist'])
        assert not any(item['cmd'] == conditional['command'] for item in consumer['ledger'])
        pattern = conditional['condition_files_exist'][0]
        write(tmp_path, pattern.replace('*', 'fixture'), {'synthetic': 'activated conditional input'})
    else:
        if change == 'nonrequired_absent':
            missing = next(item['command'] for item in invocations
                           if not item['blocking'] and not item['condition_files_exist'])
            consumer['ledger'] = [item for item in consumer['ledger'] if item['cmd'] != missing]
        else:
            consumer['ledger'] = [item for item in consumer['ledger']
                                  if item['cmd'] in consumer['required_commands']]
        write(tmp_path, relative, value)
    # Every required checker still has an executed PASS. The counterexample
    # removes other applicable observations, never a blocking checker result.
    assert all(any(item['cmd'] == cmd and item['rc'] == 0 and item['verdict'] == 'PASS'
                   for item in consumer['ledger']) for cmd in consumer['required_commands'])
    completed = runner.complete_retained_metrics(tmp_path)
    assert completed['default_row_status'] == 'NOT_MEASURED', completed
    accepted = json.loads((tmp_path / f'reports/flow109/default_rows/{step}.json').read_bytes())
    assert accepted['metric_acceptance']['reason'] == 'D0102_CANONICAL_CHECKS_INCOMPLETE', accepted


@pytest.mark.parametrize('observation', ['advisory_failure', 'advisory_not_applicable',
                                       'conditional_absent', 'conditional_executed'])
def test_complete_ledger_preserves_canonical_advisory_and_conditional_roles(tmp_path, monkeypatch, observation):
    scoped_case(tmp_path, monkeypatch)
    native = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == 'D1')
    invocations = gates.program_invocations(native)
    record = versions.latest_pass(tmp_path, 'D1')
    relative = record['storage_root'] + '/' + record['folder'] + '/outputs.json'
    value = json.loads((tmp_path / relative).read_bytes())
    consumer = value['result']['canonical_consumer']
    if observation.startswith('advisory_'):
        command = next(item['command'] for item in invocations
                       if not item['blocking'] and not item['condition_files_exist'])
        entry = next(item for item in consumer['ledger'] if item['cmd'] == command)
        if observation == 'advisory_failure':
            entry.update(rc=1, verdict='FAIL')
        else:
            entry.update(rc=0, verdict='NOT_APPLICABLE', reason_class='DESIGN_DECLARED_NA')
    else:
        conditional = next(item for item in invocations if item['condition_files_exist'])
        assert not any(item['cmd'] == conditional['command'] for item in consumer['ledger'])
        if observation == 'conditional_executed':
            write(tmp_path, conditional['condition_files_exist'][0].replace('*', 'fixture'),
                  {'synthetic': 'activated conditional input'})
            consumer['ledger'].append({'cmd': conditional['command'], 'rc': 0, 'verdict': 'PASS'})
    write(tmp_path, relative, value)
    before = (tmp_path / relative).read_bytes()
    completed = runner.complete_retained_metrics(tmp_path)
    assert completed['default_row_status'] == 'PASS', completed
    assert (tmp_path / relative).read_bytes() == before
