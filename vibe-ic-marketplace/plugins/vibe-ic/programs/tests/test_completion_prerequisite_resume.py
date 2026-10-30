"""Neutral SOFTWARE caller lifecycle controls; no benchmark/design/native result."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import benchmark_dispatch as bd
import flow109
import test_ai_first_route_handoff as route_fixture
import _runtime_pair_fixture as runtime

PROMPT = 'Complete the missing implementation from the described partial interface; provide lint-validated RTL only.'


@pytest.fixture(autouse=True)
def _runtime_precondition(monkeypatch):
    runtime.assume_matching_runtime_pair(monkeypatch)


def _setup(tmp_path, monkeypatch, *, nature='completion', ready=False, product_flow=True):
    dataset, run = tmp_path / 'neutral-inputs', tmp_path / 'run'
    dataset.mkdir(parents=True)
    prompt = PROMPT if nature == 'completion' else route_fixture.PROMPT
    (dataset / 'neutral_prompt.txt').write_text(prompt)
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'RTL-only')
    manifest = tmp_path / 'features.json'
    manifest.write_text(json.dumps({'features': features}))
    calls = []
    actual_budget_run = bd._RunnerBudget.run

    def boundary(budget, argv, **kwargs):
        first = argv[argv.index('--entry-step') + 1] if '--entry-step' in argv else 'D1'
        last = argv[argv.index('--exit-step') + 1]
        if last == 'D01':
            calls.append(('prerequisite', first, last))
            return actual_budget_run(budget, argv, **kwargs)
        calls.append(('author', first, last))
        return bd._ProcessOutcome(rc=1, error='SOFTWARE_AUTHOR_BOUNDARY')

    def prerequisite(argv, *args, **kwargs):
        context = json.loads(kwargs['env'][bd._RUNNER_CONTEXT_ENV])
        project = Path(context['project'])
        answer = project / 'input/step_0_5ic_answers.json'
        typed = list(argv)
        typed[typed.index('--exit-step') + 1] = 'D1'
        result = route_fixture._typed_d1_runner([])(typed, *args, **kwargs)
        if not answer.is_file():
            (project / 'phase1/generated_docs/L1.json').unlink()
            report = project / 'reports/orchestrator/phase1_one_shot.json'
            body = json.loads(report.read_text())
            body.update(verdict='NOT_MEASURED', reason_class='INPUT_REQUIRED',
                reason='SOFTWARE_INPUT_REQUIRED: operator_template.absent_reason')
            body['runner_binding']['material'] = bd._runner_material_snapshot(project)
            report.write_text(json.dumps(body, sort_keys=True))
            return SimpleNamespace(returncode=2, stdout='SOFTWARE_INPUT_REQUIRED', stderr='')
        return result

    monkeypatch.setattr(bd._RunnerBudget, 'run', boundary)
    monkeypatch.setattr(bd.subprocess, 'run', prerequisite)
    assert bd.cmd_solve('verilogeval-human', str(dataset), str(run),
                        flow109_manifest=str(manifest) if product_flow else None) == 2
    task = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    answer = route_fixture._answer(task, nature, disposition='OVERRIDE')
    answer['prompt_evidence'] = [{'excerpt': prompt, 'supports': f'The visible INPUT explicitly requests {nature} from the supplied description.'}]
    route_fixture._write_answer(task, answer)
    project = Path(task['project'])
    if ready:
        _update(project)
    assert bd.cmd_resume('verilogeval-human', str(dataset), str(run)) == 2
    project = Path(task['project'])
    return dataset, run, project, calls


def _update(project):
    # Explicit SOFTWARE prerequisite input, not an owner judgement or native approval.
    (project / 'input/step_0_5ic_answers.json').write_text(json.dumps({
        'answers': {'operator_template': {'absent_reason':
            'This neutral software lifecycle fixture supplies no physical submission template.'}}}))


def _state(run):
    task = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    row = json.loads((run / 'solve_report.json').read_text())['results'][0]
    return bd._validated_route_reentry_state(bench='verilogeval-human', dataset=None,
        fmt=None, run_p=run, pid=task['id'], result=row, route_worklist=[task],
        allow_d1_only=True)


def _observe(tmp_path, run, calls, rc):
    row = json.loads((run / 'solve_report.json').read_text())['results'][0]
    state = _state(run)
    data = {'scope': 'SOFTWARE_ONLY', 'resume_rc': rc, 'calls': calls,
        'worker_error': row.get('worker_error'), 'state': state['status'],
        'effective_entry': state.get('effective_entry'),
        'has_activation': state.get('activation') is not None,
        'route_nature': (row.get('route_receipt') or {}).get('task_nature')}
    (tmp_path / 'OBSERVATION.json').write_text(json.dumps(data, indent=2))
    return data


def test_input_update_resume_runs_prerequisite_then_requested_author_owner(tmp_path, monkeypatch):
    dataset, run, project, calls = _setup(tmp_path, monkeypatch)
    assert calls == [('prerequisite', 'D01', 'D01')]
    assert not bd._receipt_current_pointer(project, 'd1_activation').exists()
    _update(project)
    rc = bd.cmd_resume('verilogeval-human', str(dataset), str(run))
    observed = _observe(tmp_path, run, calls, rc)
    assert observed['worker_error'] == 'SOFTWARE_AUTHOR_BOUNDARY', observed
    assert observed['state'] == 'ACTIVE' and observed['has_activation']
    assert observed['route_nature'] == 'completion'
    assert calls == [('prerequisite', 'D01', 'D01'),
                     ('prerequisite', 'D01', 'D01'), ('author', 'D09', 'D11')]
    activation = bd._receipt_current_pointer(project, 'd1_activation').read_bytes()
    calls.clear()
    assert bd.cmd_resume('verilogeval-human', str(dataset), str(run)) == 2
    assert calls == [('author', 'D09', 'D11')]
    assert bd._receipt_current_pointer(project, 'd1_activation').read_bytes() == activation


def test_missing_input_retry_remains_pending_and_never_starts_author(tmp_path, monkeypatch):
    dataset, run, project, calls = _setup(tmp_path, monkeypatch)
    rc = bd.cmd_resume('verilogeval-human', str(dataset), str(run))
    observed = _observe(tmp_path, run, calls, rc)
    assert observed['state'] == 'D1_ONLY', observed
    assert calls == [('prerequisite', 'D01', 'D01'), ('prerequisite', 'D01', 'D01')]
    assert not observed['has_activation']


@pytest.mark.parametrize('mutation', ['prompt', 'report', 'activation_bytes', 'foreign_activation'])
def test_existing_invalid_activation_never_retries_prerequisite_or_author(tmp_path, monkeypatch, mutation):
    dataset, run, project, calls = _setup(tmp_path, monkeypatch, ready=True)
    assert _state(run)['activation'] is not None
    pointer = bd._receipt_current_pointer(project, 'd1_activation')
    if mutation == 'prompt':
        (project / 'input/phase1_prompt.md').write_text('Changed neutral source contract.')
    elif mutation == 'report':
        report = project / 'reports/orchestrator/phase1_one_shot.json'
        body = json.loads(report.read_text()); body['verdict'] = 'FAIL'
        report.write_text(json.dumps(body))
    elif mutation == 'activation_bytes':
        body = json.loads(pointer.read_text()); body['receipt_digest'] = '0' * 64
        pointer.write_text(json.dumps(body))
    else:
        other_dataset, other_run, other_project, _ = _setup(tmp_path / 'foreign', monkeypatch, ready=True)
        assert _state(other_run)['activation'] is not None
        pointer.write_bytes(bd._receipt_current_pointer(other_project, 'd1_activation').read_bytes())
    calls.clear()
    rc = bd.cmd_resume('verilogeval-human', str(dataset), str(run))
    observed = _observe(tmp_path, run, calls, rc)
    assert observed['state'] == 'REFUSED', observed
    assert observed['resume_rc'] == 2 and calls == []


def test_original_input_route_retains_no_prerequisite_and_exact_closure(tmp_path, monkeypatch):
    dataset, run, project, calls = _setup(tmp_path, monkeypatch, nature='spec_generation')
    before = _state(run)
    assert (before['status'], before['input_contract'], before['activation']) == ('ACTIVE', 'original', None)
    assert calls == [('author', 'D09', 'D11')]
    assert bd.cmd_resume('verilogeval-human', str(dataset), str(run)) == 2
    observed = _observe(tmp_path, run, calls, 2)
    assert calls == [('author', 'D09', 'D11'), ('author', 'D09', 'D11')], observed
    assert not bd._receipt_current_pointer(project, 'd1_activation').exists()


def test_actual_mixed_owner_window_is_still_unsupported():
    import task_nature_route as tnr
    manifest = {'features': next(p['features'] for p in flow109.load_registry()['reference_profiles']
                               if p['name'] == 'RTL-only')}
    with pytest.raises(ValueError, match='FLOW109_WINDOW_OWNER_CROSSING_UNSUPPORTED'):
        tnr.flow109_product_window(manifest, 'D1', '2', 'ip')


def test_legacy_completion_without_product_manifest_keeps_existing_entry(tmp_path, monkeypatch):
    dataset, run, project, calls = _setup(tmp_path, monkeypatch, product_flow=False)
    assert (_state(run)['status'], _state(run)['activation']) == ('ACTIVE', None)
    assert calls == [('author', 'D1', '2')]
    assert bd.cmd_resume('verilogeval-human', str(dataset), str(run)) == 2
    assert calls == [('author', 'D1', '2'), ('author', 'D1', '2')]
