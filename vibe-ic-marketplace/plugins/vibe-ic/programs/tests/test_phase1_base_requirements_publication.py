"""Candidate publication preserves owner approval and the existing metric gate."""
import inspect
import json
import sys

import pytest

import flow109_metric_acceptance as metrics
import phase1_one_shot_runner as runner
from test_flow109_phase1_metric_completion import approve, case, write


def owner_case(project):
    source = write(project, 'input/owner_request.md', 'Build an IC from the supplied specification.\n')
    write(project, 'input/docs/spec.md', 'The design has one signal input.\nNo calibration or trim interface is required.\n')
    write(project, 'input/step_0_5ic_answers.json', {
        'answers': {'deliverable': 'DIE'}, 'answer_provenance': {
            'deliverable': {'answered_by': 'owner',
                            'citation': 'Build an IC from the supplied specification.'}}})
    return source


def publication(project):
    import phase1_base_requirements as producer
    return producer.publish(project)


def authority(project, key, metric):
    return json.loads((project / f'requirements/{key}/{metric}.json').read_text())


def test_original_owner_request_reaches_existing_approved_population(tmp_path, monkeypatch):
    payload, _ = case(tmp_path, monkeypatch)
    source = write(tmp_path, 'input/owner_request.md', 'An owner-specified delivery constraint.\n')
    trace = payload['requirements_trace']
    trace['source_documents'].append(source)
    trace['expectations'][0]['evidence'].append(
        f"{source['path']}:1 sha256:{source['sha256']} — An owner-specified delivery constraint.")
    approve(tmp_path, payload)
    try:
        observed, body = metrics._d0102_population(tmp_path, 'base_01', 'requirements_trace', {})
        decision = observed['status']
    except metrics.MetricRefusal as exc:
        decision = exc.code
    assert decision == 'APPROVED'
    assert body['source_documents'] == trace['source_documents']


def test_legacy_approved_doc_census_preserved_with_unreferenced_owner_request(tmp_path, monkeypatch):
    payload, _ = case(tmp_path, monkeypatch)
    write(tmp_path, 'input/owner_request.md', 'Historical owner context not cited by this population.\n')
    observed, body = metrics._d0102_population(tmp_path, 'base_01', 'requirements_trace', {})
    assert observed['status'] == 'APPROVED'
    assert body == payload['requirements_trace']


def test_normal_second_track_publishes_only_pending_source_facts(tmp_path, monkeypatch):
    source = owner_case(tmp_path)
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    assert inspect.unwrap(runner.run_phase1_second_track)(tmp_path, 0) == 0
    for key, metric in [('base_01', 'requirements_trace'), ('base_02', 'endpoint_delivery_items')]:
        item = authority(tmp_path, key, metric)
        assert item['schema'] == metrics.AUTHORITY_SCHEMA
        assert item['approval']['status'] == 'PENDING'
        assert item['approval']['authority'] == 'requirements_owner'
        assert item['required_items'] == [{'id': 'delivery-route'}]
        with pytest.raises(metrics.MetricRefusal, match='METRIC_AUTHORITY_UNAPPROVED'):
            metrics._approved_authority(tmp_path, f'requirements/{key}/{metric}.json#/required_items', ('id',))
    ref = authority(tmp_path, 'base_01', 'requirements_trace')['approval']['source_reference']
    payload = json.loads((tmp_path / ref['path']).read_text())
    assert payload['requirements_trace']['features'] == []
    assert source in payload['requirements_trace']['source_documents']
    assert payload['requirements_trace']['expectations'][0]['expected_tokens'] == ['DIE']
    assert 'optional' not in json.dumps(payload).lower()


@pytest.mark.parametrize('damage', ['missing_owner', 'foreign_citation', 'changed_owner_source'])
def test_unbound_owner_route_does_not_create_authority(tmp_path, damage):
    owner_case(tmp_path)
    answers = tmp_path / 'input/step_0_5ic_answers.json'
    if damage == 'missing_owner':
        doc = json.loads(answers.read_text()); doc['answer_provenance']['deliverable']['answered_by'] = 'agent'
        write(tmp_path, 'input/step_0_5ic_answers.json', doc)
    elif damage == 'foreign_citation':
        doc = json.loads(answers.read_text()); doc['answer_provenance']['deliverable']['citation'] = 'A different owner statement.'
        write(tmp_path, 'input/step_0_5ic_answers.json', doc)
    else:
        (tmp_path / 'input/owner_request.md').write_text('Changed source without a matching owner answer.\n')
    result = publication(tmp_path)
    assert result['status'] == 'NOT_MEASURED'
    assert result['reason'] in ('D0102_OWNER_ROUTE_UNRESOLVED', 'D0102_OWNER_SOURCE_UNBOUND')
    assert not (tmp_path / 'requirements/base_01/requirements_trace.json').exists()


def test_existing_external_approval_is_preserved(tmp_path):
    owner_case(tmp_path)
    reference = write(tmp_path, 'input/external.json', {
        'requirements_trace': {'required_items': [{'id': 'external-fact'}]}})
    protected = write(tmp_path, 'requirements/base_01/requirements_trace.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'required_items': [{'id': 'external-fact'}],
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': reference}})
    original = (tmp_path / protected['path']).read_bytes()
    result = publication(tmp_path)
    assert result['preserved'] == [protected['path']]
    assert (tmp_path / protected['path']).read_bytes() == original


def test_approval_preserves_its_bound_source_when_owner_input_changes(tmp_path):
    owner_case(tmp_path)
    publication(tmp_path)
    relative = 'requirements/base_01/requirements_trace.json'
    item = authority(tmp_path, 'base_01', 'requirements_trace')
    item['approval']['status'] = 'APPROVED'
    write(tmp_path, relative, item)
    source = tmp_path / item['approval']['source_reference']['path']
    original = {(tmp_path / relative): (tmp_path / relative).read_bytes(), source: source.read_bytes()}
    (tmp_path / 'input/owner_request.md').write_text('Build an IC from this revised specification.\n')
    answer = json.loads((tmp_path / 'input/step_0_5ic_answers.json').read_text())
    answer['answer_provenance']['deliverable']['citation'] = 'Build an IC from this revised specification.'
    write(tmp_path, 'input/step_0_5ic_answers.json', answer)
    result = publication(tmp_path)
    assert result['status'] == 'NOT_MEASURED'
    assert result['reason'] == 'D0102_PROTECTED_CANDIDATE_SOURCE'
    assert all(path.read_bytes() == raw for path, raw in original.items())


def test_foreign_original_source_is_refused_before_publication(tmp_path):
    owner_case(tmp_path)
    source = tmp_path.parent / (tmp_path.name + '-foreign.md')
    source.write_text('Build an IC from the supplied specification.\n')
    (tmp_path / 'input/owner_request.md').unlink()
    (tmp_path / 'input/owner_request.md').symlink_to(source)
    result = publication(tmp_path)
    assert result['status'] == 'NOT_MEASURED'
    assert result['reason'] == 'METRIC_FOREIGN_INPUT'
    assert not (tmp_path / 'requirements').exists()


def test_publication_only_cli_does_not_dispatch_extraction(tmp_path, monkeypatch):
    owner_case(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('publication-only continuation dispatched unrelated extraction')
    for name in ['_run_docs_mode', '_run_step_0_5ic', '_run_expert_track', 'step_ingest_render']:
        monkeypatch.setattr(runner, name, forbidden)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path), '--publish-base-requirements'])
    assert runner.main() == 2
    assert authority(tmp_path, 'base_02', 'endpoint_delivery_items')['approval']['status'] == 'PENDING'


def test_publication_is_idempotent_and_never_promotes_pending(tmp_path):
    owner_case(tmp_path)
    first = publication(tmp_path)
    files = {p: p.read_bytes() for root in ['input', 'requirements']
             for p in (tmp_path / root).rglob('*') if p.is_file()}
    second = publication(tmp_path)
    assert first == second
    assert all(p.read_bytes() == raw for p, raw in files.items())


@pytest.mark.parametrize('external', [
    [], {}, {'approval': None}, {'approval': []},
    {'approval': {'status': 'APPROVED', 'source_reference': None}},
    {'approval': {'status': 'APPROVED', 'source_reference': []}},
], ids=['array', 'missing-approval', 'null-approval', 'array-approval',
        'null-reference', 'array-reference'])
def test_invalid_external_authority_is_named_and_preserves_evidence(tmp_path, monkeypatch, external):
    import _path_layout as layout
    import phase1_base_requirements as producer
    owner_case(tmp_path)
    publication(tmp_path)
    relative = 'requirements/base_01/requirements_trace.json'
    write(tmp_path, relative, external)
    source = tmp_path / producer.SOURCE
    before = {(tmp_path / relative): (tmp_path / relative).read_bytes(), source: source.read_bytes()}
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    try:
        rc = inspect.unwrap(runner.run_phase1_second_track)(tmp_path, 0)
        observed = 'RETURNED'
    except AttributeError:
        observed = 'AttributeError'
    assert observed == 'RETURNED'
    assert rc == 0
    result = json.loads(layout.report_path(tmp_path, producer.REPORT).read_text())
    assert result['status'] == 'NOT_MEASURED'
    assert result['reason'] == 'D0102_EXISTING_AUTHORITY_INVALID'
    assert result['preserved'] == [relative]
    assert result['published'] == []
    assert all(path.read_bytes() == raw for path, raw in before.items())
