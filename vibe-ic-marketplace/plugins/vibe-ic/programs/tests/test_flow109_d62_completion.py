"""D62 completion at the canonical boundary, not PDK/whole-flow qualification.

The single-row controls run actual OpenROAD fill, readback and density checks.
The unsupported D62/D63 ownership crossing remains refused before execution.
No native D62 process or metric consumer is doubled.
"""
import copy
import hashlib
import json
import pytest

import _delivery_route
import flow109
from programs.tests import test_flow109_d62_metric_acceptance as fixture


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(project):
    return {str(path.relative_to(project)): _sha(path)
            for root in ('input', 'requirements', 'adopted', 'manifest.json', 'qualifications.json')
            for path in ([project / root] if (project / root).is_file()
                         else (project / root).rglob('*')) if path.is_file()}


def _launch(project, name, expected):
    before = _inputs(project)
    attempts = {path: _sha(path) for path in
                (project / 'reports/flow109/attempts').glob('*/result.json')}
    known = set((project / 'reports/flow109/attempts').glob('window-*'))
    run = fixture._run(project)
    (project / (name + '.log')).write_text(run.stdout + run.stderr)
    assert _inputs(project) == before
    assert run.returncode == {'PASS': 0, 'FAIL': 1, 'NOT_MEASURED': 2}[expected], run.stdout + run.stderr
    report, context = fixture._report_context(project)
    assert report['default_row_status'] == report['metric_acceptance_status'] == expected
    assert report['step_id'] == 'D62'
    assert report['context_sha256'] == context['context_sha256']
    assert report['completed'] is (expected == 'PASS')
    if expected == 'PASS':
        assert report['component_status'] == 'PASS'
        assert {item['id'] for item in report['metric_acceptance']['obligations']} == set(fixture.metrics.D62_BINDINGS)
        assert all(item['status'] == 'PASS' for item in report['metric_acceptance']['obligations'])
    assert report['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert report['delivery_accepted'] is False
    created = set((project / 'reports/flow109/attempts').glob('window-*')) - known
    assert len(created) == 1
    terminal = json.loads((created.pop() / 'result.json').read_text())
    assert terminal['default_row_status'] == expected
    assert terminal['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert terminal['delivery_accepted'] is False
    assert all(_sha(path) == value for path, value in attempts.items())
    (project / (name + '.control.json')).write_text(json.dumps({
        'control_id': name, 'rc': run.returncode, 'row': expected,
        'component': report['component_status'], 'write_guard': 'PASS',
        'declared_inputs': before}, indent=2) + '\n')
    return report, context


def test_public_d62_current_missing_stale_metric_completion(tmp_path):
    assert _delivery_route.admit(tmp_path, 'ic') is None
    fixture._case(tmp_path)
    report, context = _launch(tmp_path, 'missing_reference', 'NOT_MEASURED')
    assert report['component_status'] == 'PASS'
    measured = fixture.metrics._d62_measurement(tmp_path, report, context)
    assert measured['status'] == 'MEASURED'
    fixture._adopt(tmp_path, measured['value'])
    report, context = _launch(tmp_path, 'current_complete', 'PASS')

    # Reopen the actual current proof under foreign/unregistered requests.
    # These are consumer controls, not altered producer evidence or launches.
    foreign = copy.deepcopy(context)
    foreign['context_sha256'] = '0' * 64
    refused = fixture.metrics.accept_d62(tmp_path, foreign, report)
    assert refused['status'] == 'NOT_MEASURED' and refused['delivery_blocked'] is True
    unknown = copy.deepcopy(context)
    unknown['resolved_row']['obligations'].append({'id': 'unregistered.control'})
    refused = fixture.metrics.accept_d62(tmp_path, unknown, report)
    assert refused['status'] == 'NOT_MEASURED' and refused['delivery_blocked'] is True
    assert any(item['status'] == 'UNIMPLEMENTED_METRIC_BINDING' for item in refused['obligations'])

    source = tmp_path / 'input/approved-d62-requirements.md'
    original = source.read_bytes()
    source.write_text('Changed after the recorded approval.\n')
    report, _ = _launch(tmp_path, 'stale_authority', 'NOT_MEASURED')
    assert report['reason'] == 'METRIC_AUTHORITY_STALE'
    source.write_bytes(original)
    authority = tmp_path / 'requirements/base_43/fill_density_rules.json'
    authority.unlink()
    report, _ = _launch(tmp_path, 'missing_authority', 'NOT_MEASURED')
    assert report['component_status'] == 'PASS'


def test_d62_backend_crossing_remains_explicitly_unsupported():
    features = next(profile['features'] for profile in flow109.load_registry()['reference_profiles']
                    if profile['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(features)
    with pytest.raises(flow109.Flow109Error, match='FLOW109_WINDOW_DISPATCH_UNSUPPORTED'):
        flow109.resolve_execution_window(plan, 'D62', 'D63')
