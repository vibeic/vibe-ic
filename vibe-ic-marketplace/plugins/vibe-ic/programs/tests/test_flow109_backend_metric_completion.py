"""SOURCE_ONLY D35/D37 canonical completion controls, never native qualification.

Reuse the promoted native/requirements method doubles and normal window-unit
admission fixture. Actual producer, worker receipt writer, version collector,
admission reader and finish_native_window execute. An explicitly eligible
owner-method double exercises the future qualified-owner path; production
owners still return PARTIAL/NOT_MEASURED. No EDA tool or carrier is run.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import flow109
import flow109_metric_acceptance as metrics
import execution_backend_worker as worker
import step_output_collector as versions
import test_flow109_window_continuation as window_tests
import test_flow109_d35_metric_binding as d35_tests
import test_flow109_d37_metric_binding as d37_tests
from test_flow109_d35_metric_binding import case as d35_case
from test_flow109_d37_metric_binding import case as d37_case


@pytest.fixture(params=['D35', 'D37'])
def scene(request, monkeypatch):
    row = request.param
    case = request.getfixturevalue('d35_case' if row == 'D35' else 'd37_case')
    module = d35_tests if row == 'D35' else d37_tests
    module.bounds_double(case, monkeypatch)
    project = case.project
    features = json.loads((project / 'context.json').read_text())['features']
    monkeypatch.setattr(window_tests, '_profile', lambda: copy.deepcopy(features))
    plan, context, _ = window_tests._window_fixture(project, monkeypatch, row, row)
    request_path = project / 'reports/flow109/requests' / (context['context_sha256'] + '.json')
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request_path))
    window_attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(window_attempt))
    native = context['native_step_id']
    for spec in worker.ROWS[native]['canonical_row']['required_outputs']:
        if not any(project.glob(spec)):
            path = project / spec
            assert '*' not in str(path) and ' OR ' not in str(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('SOURCE_ONLY_INVALID_GATE_REPORT_SENTINEL\n')
    inputs = {str(request_path.relative_to(project)): metrics._sha(request_path.read_bytes())}
    version_attempt = versions.begin_step(project, native, inputs=inputs)
    original_judge = getattr(metrics, 'accept_' + row.lower())

    def prior_eligible_owner(*args, **kwargs):
        result = original_judge(*args, **kwargs)
        if result['metric_status'] == 'PASS':
            result.update(status='PASS', qualification='PASS',
                          scope='SOURCE_ONLY_PRIOR_ELIGIBLE_OWNER_METHOD_DOUBLE_NOT_NATIVE_EVIDENCE')
        return result

    monkeypatch.setattr(metrics, 'accept_' + row.lower(), prior_eligible_owner)
    producer = case.complete()
    monkeypatch.setattr(metrics, 'accept_' + row.lower(), original_judge)
    monkeypatch.setattr(worker, '_current_step_producer_authority', lambda *a, **k: (
        True, 'SOURCE_ONLY_NATIVE_AUTHORITY_METHOD_DOUBLE', 'PASS'))
    monkeypatch.setattr(worker, 'evaluate', lambda *a: {
        'status': 'PASS', 'step': {'id': native, 'status': 'PASS'}, 'ledger': []})
    backend = worker.execute_current_step(project, step_id=native, producer=producer)
    receipt = project / 'reports/phase3/default_steps' / native / 'backend_result.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(backend, sort_keys=True, indent=2) + '\n')
    version = versions.finish_step(project, version_attempt, verdict=backend['verdict'],
                                   result=backend, canonical_pass=backend['verdict'] == 'PASS')
    selected = {r['id'] for r in plan['rows']}
    deps = set(context['resolved_row']['acceptance_deps']) | {
        dep['step'] for dep in context['resolved_row']['data_deps']}
    for dependency in deps & selected:
        original = flow109.execution_context(plan, dependency, dependency)
        path = request_path.parent / (original['context_sha256'] + '.json')
        path.write_text(json.dumps(original))
        case.put('reports/flow109/default_rows/' + dependency + '.json', {
            'step_id': dependency, 'default_row_status': 'PASS', 'completed': True,
            'context_sha256': original['context_sha256'], 'scope': 'SOURCE_ONLY_DEPENDENCY_METHOD_FIXTURE'})
    report = {'bounded': True, 'steps': [{'extras': {'canonical_steps': [{
        'status': backend['verdict'], 'detail': 'SOURCE_ONLY worker and producer method doubles',
        'extras': {'step_id': native, 'output_version': version['folder']}}]}}]}
    calls = []

    def install_owner(*, eligible):
        def fresh(project, current, component):
            result = original_judge(project, current, component)
            calls.append(copy.deepcopy(result))
            if eligible and result['metric_status'] == 'PASS':
                result.update(status='PASS', qualification='PASS',
                              scope='SOURCE_ONLY_ELIGIBLE_OWNER_METHOD_DOUBLE_NOT_NATIVE_EVIDENCE')
            return result
        monkeypatch.setattr(metrics, 'accept_' + row.lower(), fresh)

    def consume():
        result = flow109.finish_native_window(project, report)
        case.put('SOURCE_ONLY_CANONICAL_COMPLETION.json', result)
        return result

    def failed_backend():
        attempt = versions.begin_step(project, native, inputs=inputs)
        producer = case.complete()
        monkeypatch.setattr(worker, 'evaluate', lambda *a: {
            'status': 'FAIL', 'step': {'id': native, 'status': 'FAIL'},
            'ledger': [{'scope': 'SOURCE_ONLY_CANONICAL_GATE_METHOD_DOUBLE', 'verdict': 'FAIL'}]})
        failed = worker.execute_current_step(project, step_id=native, producer=producer)
        receipt.write_text(json.dumps(failed, sort_keys=True, indent=2) + '\n')
        record = versions.finish_step(project, attempt, verdict='FAIL', result=failed, canonical_pass=False)
        report['steps'][0]['extras']['canonical_steps'][0]['extras']['output_version'] = record['folder']
        # A missing/stale outer report verdict may not erase the bound FAIL.
        report['steps'][0]['extras']['canonical_steps'][0]['status'] = 'PASS'

    return SimpleNamespace(row=row, case=case, project=project, context=context,
        native=native, receipt=receipt, report=report, calls=calls, consume=consume,
        install_owner=install_owner, module=module, version=version,
        dependencies=sorted(deps & selected), failed_backend=failed_backend, plan=plan)


def test_fresh_eligible_owner_and_current_bound_receipt_complete_same_row(scene):
    scene.install_owner(eligible=True)
    result = scene.consume()
    assert result['default_row_status'] == 'PASS', result
    assert scene.calls and scene.calls[0]['metric_status'] == 'PASS'
    component = result['components'][0]
    assert component['qualification']['status'] == 'PASS'
    assert component['accepted_dependencies']
    assert component['completed'] is True
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False


def test_production_partial_owner_is_never_promoted_from_nested_pass(scene):
    assert json.loads(scene.receipt.read_text())['canonical_receipts'][0]['metric_acceptance']['status'] == 'PASS'
    scene.install_owner(eligible=False)
    result = scene.consume()
    assert scene.calls and scene.calls[0]['metric_status'] == 'PASS'
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['components'][0]['completed'] is False


def test_valid_original_receipt_for_another_context_cannot_be_relabelled(scene, monkeypatch):
    scene.install_owner(eligible=True)
    original = scene.context
    registry = scene.project / 'another-qualification-registry.json'
    registry.write_bytes((scene.project / 'qualifications.json').read_bytes())
    current = flow109.execution_context(scene.plan, scene.row, scene.row,
        runtime_tool_uses=original['runtime_tool_uses'], qualification_registry=registry.name)
    assert current['context_sha256'] != original['context_sha256']
    path = scene.project / 'reports/flow109/requests' / (current['context_sha256'] + '.json')
    path.write_text(json.dumps(current))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(scene.project, current)))
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert 'FLOW109_BACKEND_CONTEXT_MISMATCH' in result['components'][0]['reason']


def test_bound_backend_failure_survives_missing_qualification_and_incomplete_report(scene):
    scene.install_owner(eligible=True)
    scene.failed_backend()
    (scene.project / 'qualifications.json').unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'FAIL', result
    assert result['component_status'] == 'FAIL'
    assert scene.calls and scene.calls[-1]['metric_status'] == 'PASS'
    assert result['components'][0]['completed'] is False


@pytest.mark.parametrize('damage', ['missing_qualification', 'missing_receipt', 'forged_receipt',
    'wrong_step', 'wrong_context', 'missing_dependency', 'foreign_dependency', 'missing_version',
    'changed_input', 'symlink_receipt'])
def test_missing_forged_stale_or_context_mismatched_authority_cannot_pass(scene, damage):
    scene.install_owner(eligible=True)
    if damage == 'missing_qualification':
        (scene.project / 'qualifications.json').unlink()
    elif damage == 'missing_receipt':
        scene.receipt.unlink()
    elif damage == 'forged_receipt':
        scene.receipt.write_text('{"verdict":"PASS"}\n')
    elif damage in ('wrong_step', 'wrong_context'):
        body = json.loads(scene.receipt.read_text())
        if damage == 'wrong_step':
            body['step_id'] = 'not-this-row'
        else:
            prior = body['canonical_receipts'][0]['metric_acceptance']
            prior['obligations'][0]['measurement']['identity']['configuration']['context_sha256'] = '0' * 64
        scene.receipt.write_text(json.dumps(body))
    elif damage in ('missing_dependency', 'foreign_dependency'):
        dep = scene.dependencies[0]
        path = scene.project / 'reports/flow109/default_rows' / (dep + '.json')
        if damage == 'missing_dependency':
            path.unlink()
        else:
            body = json.loads(path.read_text())
            body['context_sha256'] = scene.context['context_sha256']
            path.write_text(json.dumps(body))
    elif damage == 'missing_version':
        version_path = versions._versions_root(scene.project) / scene.version['folder'] / 'outputs.json'
        version_path.unlink()
    elif damage == 'changed_input':
        path = scene.project / 'reports/flow109/requests' / (scene.context['context_sha256'] + '.json')
        path.write_text(path.read_text() + '\n')
    else:
        target = scene.receipt.with_name('source-only-foreign.json')
        target.write_bytes(scene.receipt.read_bytes())
        scene.receipt.unlink()
        scene.receipt.symlink_to(target.name)
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['components'][0].get('completed', False) is False


@pytest.mark.parametrize('damage', ['qualification', 'bounds', 'receipt'])
def test_fresh_measured_failure_survives_later_missing_authority(scene, monkeypatch, damage):
    scene.install_owner(eligible=True)
    if scene.row == 'D35':
        scene.module.bounds_double(scene.case, monkeypatch, setup_min=2)
    else:
        scene.module.bounds_double(scene.case, monkeypatch, density=0.03)
    if damage == 'qualification':
        (scene.project / 'qualifications.json').unlink()
    elif damage == 'bounds':
        path = ('requirements/base_23/congestion_targets.json' if scene.row == 'D35' else
                'requirements/base_24/required_spare_distribution.json')
        if scene.row == 'D37':
            scene.case.plan['measured']['pg_unconnected'] = 1
            scene.case.update_plan()
            scene.case.put('phase3/stage3/pnr/spare_cells.json', scene.case.plan)
        (scene.project / path).unlink()
    else:
        scene.receipt.unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'FAIL', result
    assert scene.calls and scene.calls[0]['metric_status'] == 'FAIL', result
    assert result['components'][0]['completed'] is False
