"""Candidate publication preserves owner approval and the existing metric gate."""
import inspect
import json
from pathlib import Path
import shlex
import sys

import pytest

import flow109_metric_acceptance as metrics
import phase1_one_shot_runner as runner
from programs.tests._hostpaths import require_repo
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


def test_normal_second_track_publishes_only_pending_source_facts(tmp_path, monkeypatch, capsys):
    source = owner_case(tmp_path)
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    assert inspect.unwrap(runner.run_phase1_second_track)(tmp_path, 0) == 4
    output = capsys.readouterr().out
    assert 'INCOMPLETE: D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in output
    assert 'IC Expert' in output
    assert 'input/docs/**' in output
    assert 'requirements/base_01/requirements_trace.json' in output
    assert 'requirements/base_02/endpoint_delivery_items.json' in output
    assert '--second-track-only' in output
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
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
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


def test_publication_only_cli_does_not_dispatch_extraction(tmp_path, monkeypatch, capsys):
    owner_case(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('publication-only continuation dispatched unrelated extraction')
    for name in ['_run_docs_mode', '_run_step_0_5ic', '_run_expert_track', 'step_ingest_render']:
        monkeypatch.setattr(runner, name, forbidden)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path), '--publish-base-requirements'])
    assert runner.main() == 4
    output = capsys.readouterr().out
    assert 'INCOMPLETE: D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in output
    assert 'IC Expert' in output
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


@pytest.mark.parametrize('reader', ['population', 'document'])
@pytest.mark.parametrize('approver', [None, '', '  ', 17])
def test_authority_requires_a_named_approver(tmp_path, approver, reader):
    source = write(tmp_path, 'input/reviewed.json', {'required_items': [{'id': 'source-fact'}]})
    write(tmp_path, 'requirements/base_01/requirements_trace.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'required_items': [{'id': 'source-fact'}],
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'approver': approver, 'source_reference': source}})
    with pytest.raises(metrics.MetricRefusal, match='METRIC_AUTHORITY_UNAPPROVED'):
        if reader == 'population':
            metrics._approved_authority(tmp_path,
                'requirements/base_01/requirements_trace.json#/required_items', ('id',))
        else:
            metrics._approved_document(tmp_path,
                'requirements/base_01/requirements_trace.json',
                authority='requirements_owner', schema=metrics.AUTHORITY_SCHEMA)


@pytest.mark.parametrize('stale', [False, True], ids=['current', 'stale'])
def test_delegated_named_approval_requires_current_source(tmp_path, stale):
    source = write(tmp_path, 'input/reviewed.json', {'required_items': [{'id': 'source-fact'}]})
    write(tmp_path, 'requirements/base_01/requirements_trace.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'required_items': [{'id': 'source-fact'}],
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'approver': 'delegated-ic-expert', 'source_reference': source}})
    if stale:
        (tmp_path / source['path']).write_text('{"required_items": []}\n')
    try:
        accepted, _ = metrics._approved_authority(tmp_path,
            'requirements/base_01/requirements_trace.json#/required_items', ('id',))
        observed = accepted['status']
    except metrics.MetricRefusal as exc:
        observed = exc.code
    assert observed == ('METRIC_AUTHORITY_STALE' if stale else 'APPROVED')


def test_requirements_wait_does_not_hide_an_expert_failure(tmp_path, monkeypatch):
    owner_case(tmp_path)
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 1)
    assert inspect.unwrap(runner.run_phase1_second_track)(tmp_path, 0) == 1
    assert authority(tmp_path, 'base_01', 'requirements_trace')['approval']['status'] == 'PENDING'


def test_requirements_wait_is_not_measured_in_the_docs_runner(tmp_path, monkeypatch):
    import _path_layout as layout
    owner_case(tmp_path)
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    monkeypatch.setattr(runner, '_run_docs_mode', lambda *args: 0)
    monkeypatch.setattr(runner, '_run_step_0_5ic', lambda *args, **kwargs: 0)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path),
                                    '--mode', 'docs', '--route', 'ic'])
    assert runner.main() == 4
    summary = json.loads(layout.report_path(tmp_path, 'phase1_one_shot.json').read_text())
    assert summary['verdict'] == 'NOT_MEASURED'
    track = next(step for step in summary['steps'] if step['name'] == 'phase1_expert_parse_track')
    assert track['status'] == 'NOT_MEASURED'


def test_requirements_wait_preserves_a_docs_extraction_failure(tmp_path, monkeypatch):
    import _path_layout as layout
    owner_case(tmp_path)
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    monkeypatch.setattr(runner, '_run_docs_mode', lambda *args: 1)
    monkeypatch.setattr(runner, '_run_step_0_5ic', lambda *args, **kwargs: 0)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path),
                                    '--mode', 'docs', '--route', 'ic'])
    assert runner.main() == 1
    summary = json.loads(layout.report_path(tmp_path, 'phase1_one_shot.json').read_text())
    assert summary['verdict'] == 'FAIL'
    assert summary['pass1']['rc'] == 1


@pytest.mark.parametrize('failed', [False, True], ids=['pass1-pass', 'pass1-fail'])
def test_requirements_wait_preserves_the_retained_first_pass(tmp_path, monkeypatch, failed):
    import _path_layout as layout
    owner_case(tmp_path)
    report = layout.report_path(tmp_path, 'phase1_one_shot.json')
    write(tmp_path, report.relative_to(tmp_path).as_posix(), {
        'phase': 1, 'mode': 'docs', 'verdict': 'FAIL' if failed else 'PASS',
        'pass1': {'verdict': 'FAIL' if failed else 'PASS', 'rc': 1 if failed else 0}})
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    assert runner.run_second_pass_only(tmp_path, 'neutral', route='ic') == (1 if failed else 4)
    summary = json.loads(report.read_text())
    assert summary['verdict'] == ('FAIL' if failed else 'NOT_MEASURED')
    assert summary['pass1']['rc'] == (1 if failed else 0)


@pytest.mark.parametrize('failed', [False, True], ids=['pending-review', 'measured-failure'])
def test_retained_metric_entry_exposes_review_and_stops_later_rows(tmp_path, monkeypatch, capsys, failed):
    import phase1_base_requirements as producer
    case(tmp_path, monkeypatch)
    for key, metric in [('base_01', 'requirements_trace'), ('base_02', 'endpoint_delivery_items')]:
        if failed and key == 'base_01':
            continue
        item = authority(tmp_path, key, metric)
        item['approval']['status'] = 'PENDING'
        write(tmp_path, f'requirements/{key}/{metric}.json', item)
    if failed:
        path = 'phase1/generated_docs/L1_DATASHEET.json'
        value = json.loads((tmp_path / path).read_text())
        value['ic_name'] = 'different_product'
        write(tmp_path, path, value)
    before = {path: path.read_bytes() for root in ('input', 'requirements', 'phase1')
              for path in (tmp_path / root).rglob('*') if path.is_file()}
    def forbidden(*args, **kwargs):
        pytest.fail('retained metric completion dispatched a producer')
    for name in ('_run_docs_mode', '_run_step_0_5ic', '_run_expert_track', 'step_ingest_render'):
        monkeypatch.setattr(runner, name, forbidden)
    monkeypatch.setattr(runner, '_complete_retained_submission_input', forbidden)
    monkeypatch.setattr(producer, 'publish', forbidden)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path),
                                    '--complete-retained-metrics'])
    assert runner.main() == (1 if failed else 4)
    output = capsys.readouterr().out
    assert ('INCOMPLETE: D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in output) is (not failed)
    if not failed:
        assert 'input/docs/**' in output
        assert '--second-track-only' in output
        assert 'rerun the same /vibe-ic-all window' in output
    first = json.loads((tmp_path / 'reports/flow109/default_rows/D01.json').read_text())
    later = json.loads((tmp_path / 'reports/flow109/default_rows/D02.json').read_text())
    assert first['default_row_status'] == ('FAIL' if failed else 'NOT_MEASURED')
    assert first['completed'] is False
    assert later['default_row_status'] == 'NOT_MEASURED'
    assert later['completed'] is False
    assert later['native_started'] is False
    assert later['reason'] == 'not executed: an earlier row stopped'
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_reviewed_complete_population_clears_requirements_handoff(tmp_path, monkeypatch, capsys):
    payload, _ = case(tmp_path, monkeypatch)
    source = write(tmp_path, 'input/owner_request.md', 'Build an IC from the supplied specification.\n')
    answers = json.loads((tmp_path / 'input/step_0_5ic_answers.json').read_text())
    answers['answer_provenance']['deliverable']['citation'] = 'Build an IC from the supplied specification.'
    write(tmp_path, 'input/step_0_5ic_answers.json', answers)
    for value in payload.values():
        value['source_documents'].append(source)
    approve(tmp_path, payload)
    for key, metric in [('base_01', 'requirements_trace'), ('base_02', 'endpoint_delivery_items')]:
        item = authority(tmp_path, key, metric)
        item['approval']['approver'] = 'delegated-ic-expert'
        write(tmp_path, f'requirements/{key}/{metric}.json', item)
    before = {path: path.read_bytes() for path in (tmp_path / 'requirements').rglob('*.json')}
    monkeypatch.setattr(runner, '_run_expert_track', lambda project: 0)
    assert inspect.unwrap(runner.run_phase1_second_track)(tmp_path, 0) == 0
    assert 'INCOMPLETE: D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' not in capsys.readouterr().out
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_authority_documentation_names_owner_role_and_review_stop():
    root = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic')
    flow = (root / 'flow/FLOW109.md').read_text()
    command = (root / 'commands/vibe-ic-all.md').read_text()
    assert 'AI-owned authority remains' not in flow
    assert '`requirements_owner` is a role' in flow
    assert 'named approver' in flow
    assert 'current source hash' in flow
    assert 'Programs never write approvals' in flow
    assert 'D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in command
    assert 'exit 4' in command
    assert 'input/docs/**' in command


@pytest.mark.parametrize('present', [False, True], ids=['missing-pack', 'existing-pack'])
def test_review_action_names_a_real_pack_or_its_existing_producer(tmp_path, present):
    import _path_layout as layout
    owner_case(tmp_path)
    pack = layout.report_path(tmp_path, 'phase1/expert_parse_track.json').parent / 'expert_parse_track_pack'
    handoff = pack / 'ic_expert_agent_handoff.json'
    if present:
        write(tmp_path, handoff.relative_to(tmp_path).as_posix(), {'fixture': True})
    action = publication(tmp_path)['next_action']
    prerequisite = shlex.join(['python3', str(Path(runner.__file__).with_name('phase1_expert_parse_track.py')),
                              str(tmp_path)])
    assert (prerequisite in action) is (not present)
    assert str(handoff) in action
    assert not handoff.exists() or present


def test_retained_review_wait_is_scoped_to_the_first_unresolved_authority(tmp_path, monkeypatch, capsys):
    case(tmp_path, monkeypatch)
    first = authority(tmp_path, 'base_01', 'requirements_trace')
    first['approval'].pop('approver')
    write(tmp_path, 'requirements/base_01/requirements_trace.json', first)
    later = authority(tmp_path, 'base_02', 'endpoint_delivery_items')
    later['approval']['status'] = 'PENDING'
    write(tmp_path, 'requirements/base_02/endpoint_delivery_items.json', later)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path),
                                    '--complete-retained-metrics'])
    assert runner.main() == 1
    assert 'D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' not in capsys.readouterr().out
    result = json.loads((tmp_path / 'reports/flow109/default_rows/D01.json').read_text())
    assert result['metric_acceptance']['reason'] == 'METRIC_AUTHORITY_UNAPPROVED'
    assert result['default_row_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('mixed', [False, True], ids=['all-invalid-approved', 'invalid-approved-and-pending'])
def test_publication_does_not_replace_preserved_authority_refusal_with_pending(tmp_path, mixed):
    owner_case(tmp_path)
    publication(tmp_path)
    reference = write(tmp_path, 'input/external.json', {})
    for key, metric in [('base_01', 'requirements_trace'), ('base_02', 'endpoint_delivery_items')]:
        if mixed and key == 'base_02':
            continue
        item = authority(tmp_path, key, metric)
        item['approval'].update(status='APPROVED', source_reference=reference)
        write(tmp_path, f'requirements/{key}/{metric}.json', item)
    before = {path: path.read_bytes() for root in ('input', 'requirements')
              for path in (tmp_path / root).rglob('*') if path.is_file()}
    result = publication(tmp_path)
    assert result['status'] == 'NOT_MEASURED'
    assert result['reason'] == 'METRIC_AUTHORITY_UNAPPROVED'
    assert 'next_action' not in result
    assert all(path.read_bytes() == raw for path, raw in before.items())
