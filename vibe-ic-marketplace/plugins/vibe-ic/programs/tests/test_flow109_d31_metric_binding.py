"""D31 normal metric consumer on retained real native artifacts.

External input is a separate neutral method carrier, never ADC qualification.
Each case uses an isolated output mount at the ORIGINAL logical project path.
Only native readback runs; no placement, authority or upstream PASS is made.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
import flow109
import flow109_analog_floorplan as owner


@pytest.fixture
def case():
    relative = os.environ.get('D31_METRIC_SUBJECT')
    if not relative:
        pytest.skip('retained actual D31 native project not supplied')
    source, project = Path('/prior') / relative, Path('/evidence') / relative
    shutil.copytree(source, project)
    raw_path = next((project / 'reports/flow109/D31').glob('*/component.json'))
    raw = json.loads(raw_path.read_bytes())
    manifest = json.loads((project / 'manifest.json').read_bytes())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'D31', 'D31')
    return project, raw_path, raw, context


def consume(case):
    project, path, raw, context = case
    hook = getattr(owner, 'consume_default_row_completion', None)
    if hook is not None:
        result = hook(project, context, raw)
        measured = result['metric_acceptance']
    else:
        # Exact-base normal finisher exposes its existing UNIMPLEMENTED state.
        # This is an observed legacy binding value, not an import/field failure.
        result = flow109._selected_step_result(project, context, raw, adapter=owner)
        measured = {'status': result['default_row_status'],
                    'metric_status': context['resolved_row']['metric_acceptance_status'],
                    'obligations': context['resolved_row']['obligations']}
    (project.parent / 'metric-observation.json').write_text(json.dumps(result, indent=2))
    return result, measured


def test_normal_consumer_reopens_complete_real_population_without_row_credit(case):
    result, measured = consume(case)
    assert measured['metric_status'] == 'PASS', measured
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    assert measured['qualification'] == 'NOT_MEASURED' and measured['delivery_blocked'] is True
    assert len(measured['obligations']) == 2
    assert all(r['measurement_complete'] is True and r['measurement_status'] == 'PASS'
               for r in measured['obligations'])
    assert {r['id'] for r in measured['obligations']} == {r['id'] for r in case[3]['resolved_row']['obligations']}
    assert all(set(r['bindings']) == set(declared['binding_keys'])
               for r, declared in zip(measured['obligations'], case[3]['resolved_row']['obligations']))
    observed = measured['observation']['measurement']
    assert observed['illegal_macro_overlap'] == 0 and observed['violations'] == []
    plan = json.loads((case[0] / 'input/flow109/D31.json').read_bytes())
    assert {r['name'] for r in observed['instances']} == set(plan['placements'])
    assert all(r['pins'] == len(plan['placements'][r['name']]['pins']) for r in observed['instances'])
    assert measured['observation']['source_projection']['consumed_definitions_unchanged'] is True
    assert measured['observation']['readback']['returncode'] == 0
    assert measured['upstream']['logical'] == {} and measured['upstream']['missing']
    assert measured['admission']['reason'] == 'QUALIFICATION_RUNTIME_ABSENT'


@pytest.mark.parametrize('subject', ['overlap', 'boundary', 'oversized'])
def test_existing_native_fail_survives_missing_qualification_and_adoption(case, subject):
    assert os.environ['D31_METRIC_KIND'] == subject
    result, measured = consume(case)
    assert measured['metric_status'] == 'FAIL', measured
    assert measured['status'] == result['default_row_status'] == 'FAIL'
    assert any(r['measurement_status'] == 'FAIL' and r['status'] == 'FAIL' for r in measured['obligations'])
    assert measured['qualification'] == 'NOT_MEASURED' and measured['delivery_blocked'] is True
    assert result['completed'] is False and result['delivery_accepted'] is False


@pytest.mark.parametrize('damage', ['missing_gds', 'missing_readback', 'returned_scalar',
    'bounds', 'source', 'tool', 'request_project'])
def test_missing_stale_or_foreign_binding_never_passes(case, damage):
    project, raw_path, raw, _ = case
    if damage == 'missing_gds':
        (project / raw['outputs'][0]['path']).unlink()
    elif damage == 'missing_readback':
        (project / raw['outputs'][1]['path']).unlink()
    elif damage == 'returned_scalar':
        raw['measurements']['illegal_macro_overlap'] = 0x123
    elif damage == 'bounds':
        path = project / 'requirements/base_20/floorplan_boundary_pin_feasibility.json'
        body = json.loads(path.read_text());body['limits']['core'][2] -= 1
        path.write_text(json.dumps(body))
    elif damage == 'source':
        raw['operation_sources']['programs/flow109_analog_floorplan.py'] = '0' * 64
        raw_path.write_text(json.dumps(raw))
    elif damage == 'tool':
        raw['tool']['sha256'] = '0' * 64
        raw_path.write_text(json.dumps(raw))
    else:
        path = raw_path.parent / 'consume-request.json'
        body = json.loads(path.read_text());body['project'] += '-foreign'
        path.write_text(json.dumps(body))
    result, measured = consume(case)
    assert measured['metric_status'] == 'NOT_MEASURED', measured
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    assert all(r['status'] == 'NOT_MEASURED' for r in measured['obligations'])
    assert not list((project / 'reports/flow109/D31_metric_readback').glob('*'))


def test_coherent_printed_counts_cannot_replace_native_readback(case):
    project, raw_path, raw, _ = case
    report = project / raw['outputs'][1]['path']
    forged = json.loads(report.read_text())
    forged['illegal_macro_overlap'] = 1
    forged['overlap_pairs'] = [[r['name'] for r in forged['instances']]]
    forged['status'] = 'FAIL'
    report.write_text(json.dumps(forged))
    raw['measurements'], raw['component_status'] = forged, 'FAIL'
    raw['outputs'][1]['sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    raw_path.write_text(json.dumps(raw))
    result, measured = consume(case)
    assert measured['metric_status'] == 'NOT_MEASURED', measured
    assert measured['reason'] == 'D31_NATIVE_READBACK_DISAGREEMENT'
    assert 'D31_NATIVE_READBACK_DISAGREEMENT' in measured['detail']
    assert result['completed'] is False


def test_late_actual_bounds_change_revokes_measurement_pass(case, monkeypatch):
    import flow109_metric_acceptance as metrics
    def absent_qualification(project, context, observed):
        path = project / 'requirements/base_20/floorplan_boundary_pin_feasibility.json'
        path.write_text(path.read_text() + '\n ')
        raise metrics.MetricRefusal('TEST_ONLY_QUALIFICATION_ABSENT', 'changed actual copy after readback')
    monkeypatch.setattr(metrics, '_d31_qualification', absent_qualification)
    result, measured = consume(case)
    assert measured['metric_status'] == 'NOT_MEASURED', measured
    assert measured['reason'] == 'D31_INPUT_CHANGED_BEFORE_METRIC_PUBLICATION'
    assert result['default_row_status'] == 'NOT_MEASURED' and measured['delivery_blocked'] is True


def test_late_upstream_refusal_cannot_erase_bound_native_failure(case, monkeypatch):
    import flow109_metric_acceptance as metrics
    def missing(*args):
        raise metrics.MetricRefusal('TEST_ONLY_UPSTREAM_UNREADABLE', 'independent adoption unavailable')
    monkeypatch.setattr(metrics, '_d31_upstream', missing)
    result, measured = consume(case)
    assert measured['metric_status'] == 'FAIL', measured
    assert result['default_row_status'] == 'FAIL' and measured['delivery_blocked'] is True
    assert any(r['status'] == 'FAIL' for r in measured['obligations'])
    assert measured['qualification'] == 'NOT_MEASURED' and result['completed'] is False


@pytest.mark.parametrize('model', ['current', 'stale'])
def test_model_binding_uses_current_sources_without_manufacturing_qualification(tmp_path, monkeypatch, model):
    """SOFTWARE qualification-stage control; neither registry nor authority issued."""
    import flow109_admission as admission
    import flow109_metric_acceptance as metrics
    if not hasattr(metrics, 'd31_model_sources'):
        pytest.skip('new D31-only software model control; base normal-output discriminator is separate')
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles'] if p['name'] == 'Analog IC external trim')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D31', 'D31')
    use = context['resolved_row']['tool_uses'][0]
    config = {'purpose': use['purpose'], 'native_steps': use['native_steps'], 'model_sources': metrics.d31_model_sources()}
    if model == 'stale':
        key = 'flow109_analog_floorplan.py:observe_component';config['model_sources'][key] = '0' * 64
    (tmp_path / 'config.json').write_text(json.dumps(config))
    context['runtime_tool_uses'] = [{'tool_id': 'klayout', 'semantics': {'purpose': use['purpose']},
                                  'config': {'path': 'config.json'}, 'build_sha256': '1' * 64}]
    monkeypatch.setattr(admission, 'require_admission', lambda *a: {'status': 'PASS'})
    with pytest.raises(metrics.MetricRefusal) as error:
        metrics._d31_qualification(tmp_path, context, {'original_context': {}, 'component': {'launch_admission': {}}})
    assert error.value.code == ('D31_MODEL_QUALIFICATION_STALE' if model == 'stale' else 'D31_ORIGINAL_EXECUTION_UNQUALIFIED')


@pytest.mark.parametrize('proof', ['valid_cross_cid', 'tampered', 'missing', 'foreign_image', 'legacy_absent'])
def test_existing_original_launch_reader_reuses_cid_without_granting_qualification(tmp_path, monkeypatch, proof):
    """SOFTWARE interface fixture using the existing D23 host-record protocol.

    This is neither a host-issued launch nor a native qualification record.
    It proves adapter compatibility and refusal behavior only.
    """
    import flow109_metric_acceptance as metrics
    old_cid, current_cid = '12' * 32, '34' * 32
    image = 'sha256:' + 'ab' * 32
    host = {'cid': old_cid, 'image': image,
        'container_inspect': {'Id': old_cid, 'Image': image,
            'Config': {'Image': image, 'Hostname': old_cid[:12]},
            'State': {'Running': True, 'Paused': False, 'Dead': False}},
        'image_inspect': [{'Id': image, 'RepoDigests': []}]}
    path = tmp_path / 'original-launch.json'
    path.write_text(json.dumps(host))
    original = {'cid': old_cid, 'image': image, 'image_id': image,
        'attestation_path': str(path), 'attestation_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    current = {'cid': current_cid, 'image': image, 'image_id': image,
        'attestation_path': str(tmp_path / 'different-current-launch.json')}
    monkeypatch.delenv('VIBEIC_FLOW109_D23_ATTESTATION', raising=False)
    if proof == 'tampered':
        path.write_text(path.read_text() + ' ')
    elif proof == 'missing':
        path.unlink()
    elif proof == 'foreign_image':
        current['image_id'] = 'sha256:' + 'cd' * 32
    elif proof == 'legacy_absent':
        original = None
    try:
        metrics._d31_original_launch(original, current)
        observed = 'REUSABLE_HOST_RECORD'
    except metrics.MetricRefusal as exc:
        observed = exc.code
    assert observed == ('REUSABLE_HOST_RECORD' if proof == 'valid_cross_cid' else
        'D31_ORIGINAL_LAUNCH_UNBOUND' if proof == 'legacy_absent' else 'D31_ORIGINAL_LAUNCH_UNPROVEN')
    assert current['cid'] == current_cid
