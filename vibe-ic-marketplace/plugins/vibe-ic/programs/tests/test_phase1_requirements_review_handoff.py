"""Neutral producer/transport controls; no dataset, accepted project or native EDA claim."""
from argparse import Namespace
import hashlib
import json
from pathlib import Path

import pytest

import ai_signed_judgement as judgement
import benchmark_dispatch as dispatch
import flow109
import flow109_metric_acceptance as metrics
import phase1_base_requirements as producer
from test_flow109_phase1_metric_completion import case, write

PACK = 'reports/audit/phase1/expert_parse_track_pack'


def review_case(project, monkeypatch, *, prompt=None, exit_step="D01"):
    features = {name: False for name in flow109.load_registry()['predicate_names']
                if name not in flow109.load_registry()['predicate_definitions']}
    features.update(always=True, has_digital=True, rtl_only=True)
    write(project, 'input/phase1_prompt.md',
          prompt or 'Deliver RTL only for parcel_flag. Output ready is left AND right.\n')
    manifest = project / 'input/flow109-manifest.json'
    write(project, 'input/flow109-manifest.json', {'features': features, 'step_profiles': {}})
    monkeypatch.setenv(flow109.CONTEXT_ENV, '')
    monkeypatch.setenv(flow109.ATTEMPT_ENV, '')
    args = Namespace(flow='109', flow109_manifest=manifest, flow109_plan_only=False,
        execution_mode='default', entry_step='D01', exit_step=exit_step, delivery_target='rtl', route=None)
    assert flow109.prepare_front_door(args, project) is None
    write(project, 'phase1/generated_docs/L1_DATASHEET.json', {'ic_name': 'parcel_flag'})
    write(project, f'{PACK}/ic_expert_agent_handoff.json',
          {'answer_contract': {'schema': 'vibeic.phase1-expert-expectations.v1'}})
    write(project, f'{PACK}/authoring_schema.json',
          {'layers': {'L1_DATASHEET': {'declared_field_paths': ['ic_name']}}})
    return producer.publish(project)


def test_source_backed_rtl_publishes_pending_without_physical_answer_or_approval(tmp_path, monkeypatch):
    result = review_case(tmp_path, monkeypatch)
    assert result['status'] == 'PENDING', result
    descriptor = producer.read_review_action(tmp_path, result['pending_action'])
    assert descriptor['source_documents'] == [write_reference(tmp_path, 'input/phase1_prompt.md')]
    assert descriptor['output_contracts'][producer.SOURCE]['requirements_trace'] == [
        'required_items', 'source_documents', 'expectations', 'features']
    assert not (tmp_path / producer.SOURCE).exists()
    assert not (tmp_path / 'requirements').exists()
    assert not (tmp_path / 'input/step_0_5ic_answers.json').exists()
    assert judgement.check(tmp_path, 'D1')[0] is False
    assert review_case_again(tmp_path) == result


def review_case_again(project):
    return producer.publish(project)


def write_reference(project, relative):
    return {'path': relative, 'sha256': hashlib.sha256((project / relative).read_bytes()).hexdigest()}


@pytest.mark.parametrize('relative', ['input/phase1_prompt.md',
    'phase1/generated_docs/L1_DATASHEET.json', f'{PACK}/authoring_schema.json',
    f'{PACK}/ic_expert_agent_handoff.json'])
def test_current_reading_material_change_refuses_transport(tmp_path, monkeypatch, relative):
    result = review_case(tmp_path, monkeypatch)
    (tmp_path / relative).write_text('Changed bytes.\n')
    with pytest.raises((ValueError, metrics.MetricRefusal)):
        producer.read_review_action(tmp_path, result['pending_action'])


def test_added_original_or_layer_refuses_stale_descriptor(tmp_path, monkeypatch):
    result = review_case(tmp_path, monkeypatch)
    write(tmp_path, 'phase1/generated_docs/L8_TIMING.json', {'latency': 1})
    with pytest.raises(ValueError, match='INPUT_REVIEW_MATERIAL_STALE'):
        producer.read_review_action(tmp_path, result['pending_action'])


def test_existing_review_sources_and_approvals_are_preserved(tmp_path, monkeypatch):
    review_case(tmp_path, monkeypatch)
    source = write(tmp_path, producer.SOURCE, {'external': 'preexisting exact bytes'})
    for key, metric in producer.ROWS:
        write(tmp_path, f'requirements/{key}/{metric}.json', {
            'schema': metrics.AUTHORITY_SCHEMA, 'required_items': [{'id': 'prior'}],
            'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                         'source_reference': source}})
    originals = {p: p.read_bytes() for root in ('input', 'requirements')
                 for p in (tmp_path / root).rglob('*') if p.is_file()}
    result = producer.publish(tmp_path)
    assert result['status'] == 'PENDING'  # Independent D1 review remains missing.
    assert all(p.read_bytes() == raw for p, raw in originals.items())


def test_transport_waits_for_review_outputs_and_has_no_rtl_completion_contract(tmp_path, monkeypatch):
    run = tmp_path / 'run'; project = run / 'projects/neutral-task'
    result = review_case(project, monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('requirements handoff touched RTL output authoring contract')
    monkeypatch.setattr(dispatch, '_backup_output_manifest', forbidden)
    item = dispatch._make_ai_backup_task('neutral-task', project, ['vibe-ic:ic-expert-agent'],
        'normal_input_review', '', 'neutral', tmp_path / 'unused', run,
        pending_action=result['pending_action'])
    assert item['action_kind'] == 'INPUT_REVIEW'
    assert not any(name in item for name in ('write_rtl_to', 'regate_entry_step', 'completion_record_contract'))
    assert dispatch._input_review_completion(item, run) == (False, ['INPUT_REVIEW_OUTPUTS_PENDING'])
    # This is deliberately invalid judgement data. Transport cannot approve it.
    write(project, 'reports/audit/ai_judgements/D1.json', {'verdict': 'PASS', 'fixture': True})
    assert dispatch._input_review_completion(item, run) == (True, [])
    assert judgement.check(project, 'D1')[0] is False
    argv = dispatch._resume_solver_argv(Path('normal-runner.py'), project, False,
                                       'D1', 'D1', delivery_target='rtl')
    assert argv[argv.index('--entry-step') + 1] == 'D01'
    assert '--rtl-input' not in argv
    assert not (project / 'phase2/stage1/rtl').exists()


def test_native_requirement_comparator_still_rejects_wrong_observed_value(tmp_path, monkeypatch):
    # Existing source-bound authority fixture is explicitly synthetic; the real
    # comparator rereads actual L-doc bytes rather than trusting supplied claims.
    payload, _ = case(tmp_path, monkeypatch)
    layer = tmp_path / 'phase1/generated_docs/L1_DATASHEET.json'
    actual = json.loads(layer.read_text()); actual['ic_name'] = 'wrong_value'
    write(tmp_path, 'phase1/generated_docs/L1_DATASHEET.json', actual)
    _, body = metrics._d0102_population(tmp_path, 'base_01', 'requirements_trace', {})
    assert body == payload['requirements_trace']
    observed, unresolved, unrouted = metrics._d0102_compare(tmp_path, body, {})
    assert observed == []
    assert unresolved == []
    assert unrouted == []


def test_initial_pending_d1_is_forwarded_and_resume_reenters_normal_program(tmp_path, monkeypatch):
    # Existing helpers stage only these invented public words and instrument the
    # actual subprocess seam. No external dataset or native receipt is used.
    from types import SimpleNamespace
    import test_declared_route_ai_backup_handoff as fixture
    fixture._rt_pair.assume_matching_runtime_pair(monkeypatch)
    inputs, run = tmp_path / 'neutral-input', tmp_path / 'run'
    prompt = 'Deliver RTL only for parcel_flag. Output ready is left AND right.\n'
    fixture._write_dataset(inputs, {'neutral-task': prompt})
    calls = []
    real_run = dispatch.subprocess.run
    def normal_program(argv, **kwargs):
        if not any(Path(str(arg)).name == 'vibe_ic_one_shot_runner.py' for arg in argv):
            return real_run(argv, **kwargs)
        calls.append(list(argv))
        project = Path(argv[2])
        fixture._emit_phase1_docs(project, fixture._runner_invocation_context(kwargs))
        review_case(project, monkeypatch)
        report = project / 'reports/orchestrator/phase1_one_shot.json'
        document = json.loads(report.read_text()); document['verdict'] = 'NOT_MEASURED'
        report.write_text(json.dumps(document))
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(dispatch.subprocess, 'run', normal_program)
    assert fixture._solve_after_ai_route('verilogeval-human', inputs, run) == 2
    tasks = dispatch._read_jsonl(run / dispatch._BACKUP_WORKLIST)
    assert len(tasks) == 1
    assert tasks[0].get('action_kind') == 'INPUT_REVIEW', tasks
    assert all('write_rtl_to' not in task for task in tasks)
    issued_calls = len(calls)
    assert dispatch.cmd_resume('verilogeval-human', str(inputs), str(run)) == 2
    assert len(calls) == issued_calls  # Missing AI output cannot trigger authoring.
    project = Path(tasks[0]['project'])
    write(project, 'reports/audit/ai_judgements/D1.json', {'fixture': 'changed but invalid'})
    assert dispatch.cmd_resume('verilogeval-human', str(inputs), str(run)) == 2
    assert len(calls) > issued_calls
    new_calls = calls[issued_calls:]
    # The normal D1 front door executes and refuses the invalid review again.
    assert all(argv[argv.index('--entry-step') + 1] != '2'
               for argv in new_calls if '--entry-step' in argv)
    assert not (project / 'phase2/stage1/rtl').exists()
    report = json.loads((run / 'solve_report.json').read_text())
    assert report['accepted'] == 0
    assert all(result.get('accepted') is False for result in report['results'])


def test_structural_approval_keeps_review_until_native_population_acceptance(tmp_path, monkeypatch):
    review_case(tmp_path, monkeypatch)
    source = write(tmp_path, 'input/reviewer-authored.json', {'fixture': 'review output'})
    for key, metric in producer.ROWS:
        write(tmp_path, f'requirements/{key}/{metric}.json', {
            'schema': metrics.AUTHORITY_SCHEMA, 'required_items': [{'id': 'fixture'}],
            'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                         'source_reference': source}})
    write(tmp_path, 'reports/audit/ai_judgements/D1.json', {
        'schema': judgement.SCHEMA, 'step_id': 'D1', 'verdict': 'PASS',
        'evidence_sha256': judgement.evidence_sha256(tmp_path, 'D1'),
        'signed_by': 'synthetic-test-model', 'judgement': 'Synthetic fixture receipt; not a project review.'})
    result = producer.publish(tmp_path)
    assert result['pending_action']['action_kind'] == 'INPUT_REVIEW'
    assert result['status'] == 'PENDING'
    assert result['native_acceptance'][0]['status'] == 'NOT_MEASURED'
    assert result['native_acceptance'][0]['reason'] == 'D0102_SOURCE_POPULATION_DIFFERS'
    # A superficially approved record does not supply a valid population.
    with pytest.raises(metrics.MetricRefusal):
        metrics._d0102_population(tmp_path, 'base_01', 'requirements_trace', {})


def test_missing_native_authoring_schema_declares_refusal_before_rtl_fallback(tmp_path, monkeypatch):
    review_case(tmp_path, monkeypatch)
    (tmp_path / PACK / 'authoring_schema.json').unlink()
    result = producer.publish(tmp_path)
    assert result['status'] == 'NOT_MEASURED'
    assert result['reason'] == 'INPUT_REVIEW_PUBLICATION_REFUSED'
    assert result['pending_action']['action_kind'] == 'INPUT_REVIEW'
    with pytest.raises(ValueError, match='INPUT_REVIEW_PUBLICATION_REFUSED'):
        dispatch._pending_input_review_action(tmp_path)
    assert not (tmp_path / 'phase2/stage1/rtl').exists()
    assert not (tmp_path / 'requirements').exists()


def _sign_fixture(project):
    write(project, 'reports/audit/ai_judgements/D1.json', {
        'schema': judgement.SCHEMA, 'step_id': 'D1', 'verdict': 'PASS',
        'evidence_sha256': judgement.evidence_sha256(project, 'D1'),
        'signed_by': 'synthetic-test-model',
        'judgement': 'Synthetic independent review precondition; not an actual project approval.'})


def _approve_fixture(project, payload):
    reference = write(project, producer.SOURCE, payload)
    for key, metric in producer.ROWS:
        write(project, f'requirements/{key}/{metric}.json', {
            'schema': metrics.AUTHORITY_SCHEMA, 'required_items': payload[metric]['required_items'],
            'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                         'source_reference': reference}})


@pytest.mark.parametrize('damage,step,refusal', [
    ('census', 'D01', 'D0102_SOURCE_DOCUMENT_CENSUS_STALE'),
    ('feature', 'D01', 'D0102_FEATURE_POPULATION_ABSENT'),
    ('assignment', 'D02', 'D0102_ASSIGNMENT_FOREIGN'),
])
def test_native_refused_approved_review_cannot_release_rtl_through_public_resume(
        tmp_path, monkeypatch, damage, step, refusal):
    from types import SimpleNamespace
    import test_declared_route_ai_backup_handoff as fixture
    fixture._rt_pair.assume_matching_runtime_pair(monkeypatch)
    inputs, run = tmp_path / 'neutral-input', tmp_path / 'run'
    prompt = ('Deliver RTL only for parcel_flag.\nOutput ready is left AND right.\n'
              'There is no analog circuitry; has_analog=false.\n')
    fixture._write_dataset(inputs, {'neutral-task': prompt})
    calls, native_results = [], []
    real_run = dispatch.subprocess.run
    def normal_program(argv, **kwargs):
        if not any(Path(str(arg)).name == 'vibe_ic_one_shot_runner.py' for arg in argv):
            return real_run(argv, **kwargs)
        calls.append(list(argv))
        project = Path(argv[2])
        fixture._emit_phase1_docs(project, fixture._runner_invocation_context(kwargs))
        if not (project / producer.SOURCE).exists():
            review_case(project, monkeypatch, prompt=prompt, exit_step='D02')
            write(project, 'phase1/generated_docs/L1_DATASHEET.json', {
                'ic_name': 'parcel_flag', 'description': 'RTL; ready = left AND right', 'has_analog': False})
            documents = metrics._d0102_documents(project, {})
            sources = [{'path': name, 'sha256': digest} for name, digest in documents.items()]
            source = sources[0]
            def expectation(identifier, path, token, line):
                return {'id': identifier, 'layer': 'L1_DATASHEET', 'field_path': path,
                    'requirement': prompt.splitlines()[line - 1], 'expected_tokens': [token],
                    'evidence': [f"{source['path']}:{line} sha256:{source['sha256']} — {prompt.splitlines()[line - 1]}"]}
            expectations = [expectation('identity', 'ic_name', 'parcel_flag', 1),
                expectation('behavior', 'description', 'left AND right', 2),
                expectation('endpoint', 'description', 'RTL', 1)]
            population = [{'id': item['id']} for item in expectations]
            feature = {'feature': 'has_analog', 'declared': False, 'layer': 'L1_DATASHEET',
                'field_path': '/has_analog', 'evidence': [
                    f"{source['path']}:3 sha256:{source['sha256']} — {prompt.splitlines()[2]}"]}
            payload = {
                'requirements_trace': {'required_items': population, 'source_documents': sources,
                    'expectations': expectations, 'features': [feature]},
                'endpoint_delivery_items': {'required_items': [{'id': 'endpoint'}],
                    'source_documents': sources, 'expectations': [expectations[-1]],
                    'assignments': [{'id': item['id'], 'endpoint': 'RTL',
                        'layer': item['layer'], 'field_path': item['field_path']} for item in expectations]}}
            if damage == 'census':
                payload['requirements_trace']['source_documents'] = []
            elif damage == 'feature':
                payload['requirements_trace']['features'] = []
            else:
                payload['endpoint_delivery_items']['assignments'][0]['field_path'] = 'description'
            _approve_fixture(project, payload)
            _sign_fixture(project)
        import os
        context = flow109.validate_execution_context(json.loads(
            Path(os.environ[flow109.CONTEXT_ENV]).read_bytes()))
        current = flow109.component_context(context, requested_step=step)
        observed = (metrics.accept_d01 if step == 'D01' else metrics.accept_d02)(project, current)
        native_results.append(observed)
        assert observed['reason'] == refusal, observed
        producer.publish(project)
        report = project / 'reports/orchestrator/phase1_one_shot.json'
        document = json.loads(report.read_text()); document['verdict'] = 'NOT_MEASURED'
        report.write_text(json.dumps(document))
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(dispatch.subprocess, 'run', normal_program)
    assert fixture._solve_after_ai_route('verilogeval-human', inputs, run) == 2
    tasks = dispatch._read_jsonl(run / dispatch._BACKUP_WORKLIST)
    assert len(tasks) == 1
    assert tasks[0].get('action_kind') == 'INPUT_REVIEW', tasks
    assert 'write_rtl_to' not in tasks[0] and 'regate_entry_step' not in tasks[0]
    project = Path(tasks[0]['project'])
    preserved = {path: path.read_bytes() for relative in (producer.SOURCE,
        'requirements/base_01/requirements_trace.json', 'requirements/base_02/endpoint_delivery_items.json')
        for path in [project / relative]}
    calls_before = len(calls)
    assert dispatch.cmd_resume('verilogeval-human', str(inputs), str(run)) == 2
    assert len(calls) == calls_before
    receipt_path = project / 'reports/audit/ai_judgements/D1.json'
    receipt = json.loads(receipt_path.read_text()); receipt['judgement'] += ' Reviewed again.'
    write(project, receipt_path.relative_to(project).as_posix(), receipt)
    assert dispatch.cmd_resume('verilogeval-human', str(inputs), str(run)) == 2
    assert len(calls) > calls_before
    assert all(value['reason'] == refusal for value in native_results)
    tasks = dispatch._read_jsonl(run / dispatch._BACKUP_WORKLIST)
    assert len(tasks) == 1 and tasks[0]['action_kind'] == 'INPUT_REVIEW'
    producer.read_review_action(project, tasks[0]['pending_action'])
    assert all(path.read_bytes() == raw for path, raw in preserved.items())
    assert not (project / 'phase2/stage1/rtl').exists()
    report = json.loads((run / 'solve_report.json').read_text())
    assert report['accepted'] == 0


def _qualified_rtl_review_fixture(project, monkeypatch):
    # Reuse the existing explicitly synthetic complete canonical-consumer
    # fixture. It runs the actual qualifiers, not the underlying native tools.
    from test_flow109_d02_rtl_qualification import scoped_case
    import os
    payload, _ = scoped_case(project, monkeypatch)
    manifest = project / 'input/flow109-manifest.json'
    args = Namespace(flow='109', flow109_manifest=manifest, flow109_plan_only=False,
        execution_mode='default', entry_step='D01', exit_step='D02', delivery_target='rtl', route=None)
    assert flow109.prepare_front_door(args, project) is None
    scope = flow109.active_rtl_scope(project)
    write(project, 'reports/phase1/submission_scope.json', {'name': 'submission_template',
        'status': 'NOT_APPLICABLE', 'delivery_scope': scope})
    write(project, f'{PACK}/ic_expert_agent_handoff.json', {'fixture': 'existing native expert pack'})
    write(project, f'{PACK}/authoring_schema.json', {'fixture': 'current native schema'})
    return payload, json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_bytes())


def test_qualified_native_completion_clears_pending_action_and_preserves_reviews(tmp_path, monkeypatch):
    import phase1_one_shot_runner as runner
    payload, context = _qualified_rtl_review_fixture(tmp_path, monkeypatch)
    pending = producer.publish(tmp_path)
    assert pending['pending_action']['action_kind'] == 'INPUT_REVIEW'
    _sign_fixture(tmp_path)
    before = {path: path.read_bytes() for root in ('input', 'requirements')
              for path in (tmp_path / root).rglob('*') if path.is_file()}
    for step, consume in [('D01', metrics.accept_d01), ('D02', metrics.accept_d02)]:
        observed = consume(tmp_path, flow109.component_context(context, requested_step=step))
        assert observed['status'] == observed['qualification'] == 'PASS', observed
        assert observed['delivery_blocked'] is False
    completed = runner.complete_retained_metrics(tmp_path)
    assert completed['default_row_status'] == 'PASS', completed
    current = json.loads(producer.layout.report_path(tmp_path, producer.REPORT).read_text())
    assert 'pending_action' not in current
    assert all(item['status'] == item['qualification'] == 'PASS' for item in current['native_acceptance'])
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert not (tmp_path / 'phase2/stage1/rtl').exists()
    assert completed['delivery_accepted'] is False


def test_stale_complete_canonical_ledger_keeps_review_pending(tmp_path, monkeypatch):
    import step_output_collector as versions
    _, context = _qualified_rtl_review_fixture(tmp_path, monkeypatch)
    _sign_fixture(tmp_path)
    record = versions.latest_pass(tmp_path, 'D1')
    ledger = tmp_path / record['storage_root'] / record['folder'] / 'outputs.json'
    data = json.loads(ledger.read_bytes())
    data['result']['canonical_consumer']['ledger'].pop()
    ledger.write_text(json.dumps(data))
    result = producer.publish(tmp_path)
    assert result['pending_action']['action_kind'] == 'INPUT_REVIEW'
    assert all(item['reason'] == 'D0102_CANONICAL_CHECKS_INCOMPLETE'
               for item in result['native_acceptance'])
