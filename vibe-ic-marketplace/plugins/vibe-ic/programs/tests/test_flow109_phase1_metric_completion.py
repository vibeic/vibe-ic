"""Synthetic source controls, not native or real-IC qualification receipts.

The unchanged expert comparator observes real fixture L-document bytes. The
retained canonical ledger is a synthetic historical qualification fixture;
these tests do not claim its listed commands executed on either real IC.
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
import flow109
import flow109_metric_acceptance as metrics
import phase1_one_shot_runner as runner
import execution_backend_gates as gates
import step_output_collector as versions
import _flow_yaml
import _path_layout as layout


def write(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n' if not isinstance(value, str) else value)
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def case(project, monkeypatch, *, analog=False):
    profile = 'Analog IC external trim' if analog else 'Small digital IC without DFT'
    feature = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                   if p['name'] == profile)
    feature = copy.deepcopy(feature)
    # Two distinct fixture documents exercise the same source-agnostic consumer.
    token = 'converter_alpha' if analog else 'arithmetic_beta'
    feature_literal = 'has_analog=' + str(feature['has_analog']).lower()
    source = write(project, 'input/docs/spec.md', token + '\nDIE\n' + feature_literal + '\n')
    write(project, 'input/step_0_5ic_answers.json', {
        'schema': 'vibe-ic/step_0_5ic_answers/1', 'answers': {'deliverable': 'DIE'},
        'answer_provenance': {'deliverable': {'answered_by': 'owner', 'citation': 'synthetic fixture owner'}},
        'operator_template': {'absent_reason': 'Synthetic fixture explicitly selects self tapeout without an operator.'}})
    exp = {'id': 'identity', 'layer': 'L1_DATASHEET', 'field_path': 'ic_name',
           'requirement': 'Preserve the source product identifier.', 'expected_tokens': [token],
           'evidence': [f"input/docs/spec.md:1 sha256:{source['sha256']} — {token}"]}
    endpoint = {'id': 'endpoint', 'layer': 'L1_DATASHEET', 'field_path': 'description',
                'requirement': 'Preserve the source endpoint.', 'expected_tokens': ['DIE'],
                'evidence': [f"input/docs/spec.md:2 sha256:{source['sha256']} — DIE"]}
    payload = {
        'requirements_trace': {'required_items': [{'id': 'identity'}], 'source_documents': [source],
            'expectations': [exp], 'features': [{'feature': 'has_analog', 'declared': feature['has_analog'],
                'layer': 'L1_DATASHEET', 'field_path': '/has_analog',
                'evidence': [f"input/docs/spec.md:3 sha256:{source['sha256']} — {feature_literal}"]}]},
        'endpoint_delivery_items': {'required_items': [{'id': 'endpoint'}], 'source_documents': [source],
            'expectations': [endpoint], 'assignments': [{'id': 'identity', 'endpoint': 'DIE',
                'layer': 'L1_DATASHEET', 'field_path': 'ic_name'}]}}
    approve(project, payload)
    # Materialize only synthetic output fixtures required by the actual legacy
    # contracts. Never call an IC producer, extractor or native executable.
    rows = {str(r['id']): r for r in _flow_yaml.load()['steps']}
    for native in ('D1', '0.5ic'):
        for spec in rows[native].get('required_outputs', []):
            name = spec.split(' OR ')[0].replace('*', 'fixture')
            if name.endswith('/'):
                name += 'fixture.json'
            write(project, name, {'fixture': True})
    write(project, 'phase1/generated_docs/L1_DATASHEET.json', {
        'schema_version': 2, 'ic_name': token, 'description': 'DIE', 'has_analog': feature['has_analog']})
    report = {'phase': 1, 'project': str(project), 'verdict': 'PASS', 'delivery_route': 'IC',
              'deliverable': 'DIE', 'canonical_producer': {'runner': 'phase1_one_shot_runner',
                  'site': 'doc_extract', 'step_id': 'D1'}}
    out = layout.report_path(project, 'phase1_one_shot.json')
    write(project, out.relative_to(project).as_posix(), report)
    for native in ('D1', '0.5ic'):
        inputs = {source['path']: source['sha256']}
        attempt = versions.begin_step(project, native, inputs)
        commands = gates.required_commands(rows[native])
        consumer = {'status': 'PASS', 'required_commands': commands,
                    'ledger': [{'cmd': cmd, 'rc': 0, 'verdict': 'PASS'} for cmd in commands],
                    'outputs': gates.contracts(project, rows[native])}
        versions.finish_step(project, attempt, verdict='PASS', canonical_pass=True,
            result={'runner': 'phase1_one_shot_runner', 'producer_return': 0,
                    'canonical_consumer': consumer})
    context = flow109.execution_context(flow109.resolve_plan(feature), 'D01', 'D02')
    context_path = project / 'context.json'
    write(project, 'context.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    return payload, context


def approve(project, payload):
    ref = write(project, 'input/approved-requirements.json', payload)
    for key, metric in [('base_01', 'requirements_trace'), ('base_02', 'endpoint_delivery_items')]:
        write(project, f'requirements/{key}/{metric}.json', {
            'schema': metrics.AUTHORITY_SCHEMA,
            'required_items': payload[metric]['required_items'],
            'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': ref}})


def complete(project):
    """BASE exercises its actual component-only publication, not an import error."""
    if hasattr(runner, 'complete_retained_metrics'):
        return runner.complete_retained_metrics(project)
    return flow109.finish_native_window(project, {'steps': [
        {'status': 'PASS', 'extras': {'step_id': native}} for native in ('D1', '0.5ic')]})


def row(project, step):
    return json.loads((project / f'reports/flow109/default_rows/{step}.json').read_text())


@pytest.mark.parametrize('analog', [False, True], ids=['digital-source', 'converter-source'])
def test_current_complete_source_evidence_publishes_whole_rows(tmp_path, monkeypatch, analog):
    case(tmp_path, monkeypatch, analog=analog)
    before = {p: p.read_bytes() for root in ('input', 'phase1', 'steps')
              for p in (tmp_path / root).rglob('*') if p.is_file()}
    result = complete(tmp_path)
    assert result['default_row_status'] == 'PASS', result
    for step, count in [('D01', 3), ('D02', 2)]:
        accepted = row(tmp_path, step)
        assert accepted['completed'] is True
        assert accepted['metric_acceptance']['qualification'] == 'PASS'
        assert len(accepted['metric_acceptance']['obligations']) == count
        assert all(o['status'] == 'PASS' for o in accepted['metric_acceptance']['obligations'])
        assert accepted['whole_flow_acceptance'] == 'NOT_MEASURED'
        assert accepted['delivery_accepted'] is False
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize('change,step,expected', [
    ('missing_requirement', 'D01', 'FAIL'), ('unrouted_fact', 'D01', 'NOT_MEASURED'),
    ('feature_contradiction', 'D01', 'FAIL'), ('missing_source', 'D01', 'NOT_MEASURED'),
    ('foreign_source', 'D01', 'NOT_MEASURED'), ('stale_source', 'D01', 'NOT_MEASURED'),
    ('unassigned_delivery', 'D02', 'FAIL'), ('forged_component', 'D01', 'NOT_MEASURED'),
    ('partial_canonical_checks', 'D01', 'NOT_MEASURED'), ('missing_population_item', 'D01', 'NOT_MEASURED'),
    ('unknown_feature', 'D01', 'NOT_MEASURED'), ('unapproved_source', 'D01', 'NOT_MEASURED'),
    ('route_contradiction', 'D01', 'FAIL'), ('unknown_assignment', 'D02', 'NOT_MEASURED'),
    ('foreign_assignment', 'D02', 'NOT_MEASURED')])
def test_actual_publication_refuses_incomplete_or_contradictory_evidence(tmp_path, monkeypatch, change, step, expected):
    payload, context = case(tmp_path, monkeypatch)
    doc = tmp_path / 'phase1/generated_docs/L1_DATASHEET.json'
    if change == 'missing_requirement':
        payload['requirements_trace']['expectations'][0].update(met=True, usable=True, observed='arithmetic_beta')
        approve(tmp_path, payload)
        value = json.loads(doc.read_text()); value['ic_name'] = 'different_product'; write(tmp_path, doc.relative_to(tmp_path).as_posix(), value)
    elif change == 'unrouted_fact':
        payload['requirements_trace']['expectations'][0]['layer'] = 'UNSUPPORTED_LAYER'; approve(tmp_path, payload)
    elif change in ('feature_contradiction', 'unknown_feature'):
        value = json.loads(doc.read_text()); value['has_analog'] = True if change == 'feature_contradiction' else None
        write(tmp_path, doc.relative_to(tmp_path).as_posix(), value)
    elif change == 'missing_source':
        (tmp_path / 'input/docs/spec.md').unlink()
    elif change == 'foreign_source':
        payload['requirements_trace']['source_documents'][0]['path'] = 'input/docs/foreign.md'; approve(tmp_path, payload)
    elif change == 'stale_source':
        (tmp_path / 'input/docs/spec.md').write_text('changed source\n')
    elif change == 'unassigned_delivery':
        payload['endpoint_delivery_items']['assignments'] = []; approve(tmp_path, payload)
    elif change in ('forged_component', 'partial_canonical_checks'):
        record = versions.latest_pass(tmp_path, 'D1')
        p = tmp_path / record['storage_root'] / record['folder'] / 'outputs.json'
        value = json.loads(p.read_text())
        if change == 'forged_component':
            value['result']['canonical_consumer'] = {'status': 'PASS'}
        else:
            value['result']['canonical_consumer']['ledger'].pop()
        write(tmp_path, p.relative_to(tmp_path).as_posix(), value)
    elif change == 'missing_population_item':
        payload['requirements_trace']['expectations'] = []; approve(tmp_path, payload)
    elif change == 'unapproved_source':
        p = tmp_path / 'requirements/base_01/requirements_trace.json'
        value = json.loads(p.read_text()); value['approval']['status'] = 'PENDING'; write(tmp_path, p.relative_to(tmp_path).as_posix(), value)
    elif change == 'route_contradiction':
        p = tmp_path / 'input/step_0_5ic_answers.json'
        value = json.loads(p.read_text()); value['answers']['deliverable'] = 'HARDMACRO'
        write(tmp_path, p.relative_to(tmp_path).as_posix(), value)
    elif change == 'unknown_assignment':
        value = json.loads(doc.read_text()); value['ic_name'] = None
        write(tmp_path, doc.relative_to(tmp_path).as_posix(), value)
    elif change == 'foreign_assignment':
        payload['endpoint_delivery_items']['assignments'][0]['field_path'] = 'description'
        approve(tmp_path, payload)
    complete(tmp_path)
    accepted = row(tmp_path, step)
    assert accepted['default_row_status'] == expected, accepted
    assert accepted['completed'] is False
    assert accepted['delivery_accepted'] is False


def test_component_success_is_not_a_metric_completion(tmp_path, monkeypatch):
    _, context = case(tmp_path, monkeypatch)
    result = flow109.finish_native_window(tmp_path, {'steps': [
        {'status': 'PASS', 'extras': {'step_id': native}} for native in ('D1', '0.5ic')]})
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert all(c['completed'] is False for c in result['components'])


def test_phase1_retained_completion_entry_never_dispatches_a_producer(tmp_path, monkeypatch):
    case(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('retained metric completion dispatched a producer')
    for name in ('_run_docs_mode', '_run_step_0_5ic', '_run_expert_track', 'step_ingest_render'):
        monkeypatch.setattr(runner, name, forbidden)
    if not hasattr(runner, 'complete_retained_metrics'):
        assert complete(tmp_path)['default_row_status'] == 'PASS'
        return
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path), '--complete-retained-metrics'])
    assert runner.main() == 0
    assert row(tmp_path, 'D01')['default_row_status'] == 'PASS'
    assert row(tmp_path, 'D02')['default_row_status'] == 'PASS'


def test_existing_expert_second_pass_publishes_completed_metrics(tmp_path, monkeypatch):
    import ai_signed_judgement
    case(tmp_path, monkeypatch)
    if not hasattr(runner, 'complete_retained_metrics'):
        complete(tmp_path)  # Existing BASE publication carries component success only.
    monkeypatch.setattr(runner, 'run_phase1_second_track', lambda *a: 0)
    monkeypatch.setattr(runner, '_expert_track_summary', lambda *a: 'consumed synthetic source expectations')
    monkeypatch.setattr(ai_signed_judgement, 'pending', lambda *a: {})
    assert runner.run_second_pass_only(tmp_path, 'fixture', None) == 0
    assert row(tmp_path, 'D01')['default_row_status'] == 'PASS'
    assert row(tmp_path, 'D02')['default_row_status'] == 'PASS'
