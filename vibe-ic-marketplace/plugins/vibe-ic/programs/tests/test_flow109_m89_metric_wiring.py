"""Read-only M08/M09 consumers: synthetic controls, no native qualification.

Native owner completions are controlled seams here; requirement approval,
operator grading, row aggregation and current file hashing execute for real.
The baseline fallback exercises its existing completion value, never imports a
missing new symbol to manufacture a red control.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import flow109_mixed_native as mixed
import flow109_metric_acceptance as metrics
from test_flow109_mixed_native import context, install_fakes, project, sha


def consume(root, step, component):
    binder = getattr(mixed, 'bind_metrics', None)
    if binder:
        result = binder(root, context(step), component)
        (root / 'metric_result.json').write_text(json.dumps(result, indent=2))
        return result
    completed = mixed.consume_default_row_completion(root, context(step), component)
    return {'status': completed['default_row_status'], 'reason': completed['reason']}


def approved(root, name, **body):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema': metrics.AUTHORITY_SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': {'path': 'input.bin', 'sha256': sha(root / 'input.bin')}}, **body}))
    return path


def setup(monkeypatch, tmp_path, step):
    import _mixed_signal_native as native
    import _mixed_signal_current as current
    import mixed_signal_m3_run as m3
    import flow109_final_extract as final_extract

    install_fakes(monkeypatch)
    root = project(tmp_path, step)
    geometry = root / 'phase3/mixed_signal/top_merged.gds'
    inputs = {'input.bin': sha(root / 'input.bin'),
              'phase3/mixed_signal/top_merged.gds': sha(geometry)}
    monkeypatch.setattr(m3, 'inputs', lambda *_args: dict(inputs))
    monkeypatch.setattr(m3, 'verify', lambda *_args: {'execution': [{'command': ['controlled-owner'], 'exit_code': 0}]})
    monkeypatch.setattr(native, 'contract', lambda *_args: {'scope': current.SCOPE, '_current': {'model': 'bound'}})
    monkeypatch.setattr(final_extract, 'validate_final_parasitics', lambda *_args: {
        'final_gds': {'path': 'phase3/mixed_signal/top_merged.gds', 'sha256': sha(geometry)}})
    upstream = {name: {'default_row_status': 'PASS', 'completed': True,
        'input_sha256': dict(inputs), 'selected_obligations': [name + '.required']}
        for name in ('M02', 'M05', 'M06', 'A17', 'D69', 'D70', 'M08')}
    monkeypatch.setattr(mixed, '_accepted_upstream', lambda _p, _m, name: upstream[name], raising=False)
    cosim = root / m3.COSIM
    si = root / m3.SI
    cosim.parent.mkdir(parents=True, exist_ok=True)
    si.parent.mkdir(parents=True, exist_ok=True)
    cosim.write_text(json.dumps({'scenarios': [{'id': 'functional', 'status': 'PASS',
        'criteria': [{'native_metric': 'settled_voltage_min_v', 'measured': 1.0}]}]}))
    (root / m3.RECEIPT).write_text(json.dumps({'execution': 'controlled upstream seam'}))
    si.write_text(json.dumps({'receiver_noise': {'metrics': {
        'integrated_output_noise_v_rms': {'measured': 0.001, 'units': 'V_RMS'}}}}))
    if step == 'M08':
        approved(root, 'requirements/ams_final/final_ams_scenarios.json', required_items=[{'scenario': 'functional'}])
        bounds = approved(root, 'requirements/ams_final/final_ams_noise_settling_calibration.json',
            limits={'functional/settled_voltage_min_v': {'min': 0.9, 'max': 1.1},
                    'receiver_noise/integrated_output_noise_v_rms': {'max': 0.002}},
            units={'functional/settled_voltage_min_v': 'V',
                   'receiver_noise/integrated_output_noise_v_rms': 'V_RMS'})
    else:
        (root / 'input/flow109/M08.json').write_text(json.dumps({'d69_receipt': {'path': 'd69.json'}}))
        approved(root, 'requirements/base_M7/mixed_requirement_evidence.json', required_items=[
            *({'step': name, 'obligation': name + '.required'} for name in ('M02', 'M06', 'M08', 'D70')),
            {'step': 'A19', 'obligation': 'macro'}])
        bounds = approved(root, 'adopted/base_M7/mixed_model_final_geometry_identity.json',
            reference={'geometry': {'path': 'phase3/mixed_signal/top_merged.gds', 'sha256': sha(geometry)},
                       'inputs': inputs}, reference_identity={'producer': 'requirements_owner', 'checker': 'controlled_review',
                'tool_execution': 'controlled_approval', 'consumed_inputs': inputs,
                'requirements': 'approved_reference', 'configuration': 'adopted'})
        monkeypatch.setattr(mixed, '_m09_prerequisites', lambda *_args: {
            'a19_packages': {'macro': {'signoff_sha256': 'a' * 64}}, 'inputs': {}})
    component = mixed.execute(root, context(step))
    assert component['component_status'] == 'PASS'
    return root, component, cosim, si, bounds, upstream


@pytest.mark.parametrize('step', ['M08', 'M09'])
def test_positive_actual_metric_consumer(monkeypatch, tmp_path, step):
    root, component, *_ = setup(monkeypatch, tmp_path, step)
    result = consume(root, step, component)
    assert result['status'] == 'PASS', result
    if 'metric_status' in result:
        assert result['qualification'] == 'NOT_MEASURED'
        assert result['whole_ic_acceptance'] == 'NOT_MEASURED'
        assert result['delivery_blocked'] is True
        assert {r['id'] for r in result['obligations']} == set(mixed.ROWS[step]['obligations'])


@pytest.mark.parametrize('mutation,expected', [
    ('missing_scenario', 'FAIL'), ('numeric', 'FAIL'), ('noise', 'FAIL'),
    ('unit', 'NOT_MEASURED'), ('calibration_absent', 'NOT_MEASURED'),
    ('bounds_absent', 'NOT_MEASURED'), ('authority_stale', 'NOT_MEASURED'),
    ('component_model', 'NOT_MEASURED'), ('foreign_final_geometry', 'NOT_MEASURED'),
    ('upstream_geometry', 'NOT_MEASURED')])
def test_m08_bad_values_are_not_final_ams_pass(monkeypatch, tmp_path, mutation, expected):
    import _mixed_signal_native as native
    import flow109_final_extract as final_extract
    root, component, cosim, si, bounds, upstream = setup(monkeypatch, tmp_path, 'M08')
    if mutation == 'missing_scenario':
        approved(root, 'requirements/ams_final/final_ams_scenarios.json', required_items=[
            {'scenario': 'functional'}, {'scenario': 'calibration'}])
    elif mutation == 'numeric':
        value = json.loads(cosim.read_text()); value['scenarios'][0]['criteria'][0]['measured'] = 2.0
        cosim.write_text(json.dumps(value))
    elif mutation == 'noise':
        value = json.loads(si.read_text()); value['receiver_noise']['metrics']['integrated_output_noise_v_rms']['measured'] = 0.01
        si.write_text(json.dumps(value))
    elif mutation == 'authority_stale':
        value = json.loads(bounds.read_text()); value['approval']['source_reference']['sha256'] = '0' * 64
        bounds.write_text(json.dumps(value))
    elif mutation == 'bounds_absent':
        bounds.unlink()
    elif mutation in ('unit', 'calibration_absent'):
        value = json.loads(bounds.read_text())
        if mutation == 'unit':
            value['units']['functional/settled_voltage_min_v'] = 'ns'
        else:
            value['limits']['calibration/error'] = {'max': 1.0}
            value['units']['calibration/error'] = 'V'
        bounds.write_text(json.dumps(value))
    elif mutation == 'component_model':
        monkeypatch.setattr(native, 'contract', lambda *_args: {'scope': 'declared_model_component'})
    elif mutation == 'foreign_final_geometry':
        (root / 'foreign.gds').write_bytes(b'foreign carrier')
        monkeypatch.setattr(final_extract, 'validate_final_parasitics', lambda *_args: {
            'final_gds': {'path': 'foreign.gds', 'sha256': sha(root / 'foreign.gds')}})
    else:
        upstream['M06']['input_sha256'].pop('phase3/mixed_signal/top_merged.gds')
    result = consume(root, 'M08', component)
    assert result['status'] == expected, result


@pytest.mark.parametrize('mutation,expected', [('missing_requirement', 'FAIL'),
    ('foreign_identity', 'FAIL'), ('incomplete_a19', 'FAIL'), ('a19_refused', 'NOT_MEASURED')])
def test_m09_population_and_geometry_are_consumed(monkeypatch, tmp_path, mutation, expected):
    root, component, _c, _s, adopted, _u = setup(monkeypatch, tmp_path, 'M09')
    if mutation == 'missing_requirement':
        path = root / 'requirements/base_M7/mixed_requirement_evidence.json'
        value = json.loads(path.read_text()); value['required_items'].append({'step': 'M02', 'obligation': 'absent'})
        path.write_text(json.dumps(value))
    elif mutation == 'foreign_identity':
        value = json.loads(adopted.read_text()); value['reference']['geometry']['sha256'] = '0' * 64
        adopted.write_text(json.dumps(value))
    elif mutation == 'incomplete_a19':
        monkeypatch.setattr(mixed, '_m09_prerequisites', lambda *_args: {'a19_packages': {}, 'inputs': {}})
    else:
        def refuse(*_args):
            raise mixed.Refusal('MIXED_ROW_A19_POPULATION_INVALID', 'missing block')
        monkeypatch.setattr(mixed, '_m09_prerequisites', refuse)
    result = consume(root, 'M09', component)
    assert result['status'] == expected, result


def test_native_reader_is_reopened_and_cannot_be_bypassed(monkeypatch, tmp_path):
    import mixed_signal_m3_run as m3
    root, component, *_ = setup(monkeypatch, tmp_path, 'M08')
    def refuse(*_args):
        raise m3.Refusal('STALE_INPUT', 'changed native model')
    monkeypatch.setattr(m3, 'verify', refuse)
    assert consume(root, 'M08', component)['status'] == 'NOT_MEASURED'


def test_real_checked_in_component_contract_cannot_be_final(monkeypatch, tmp_path):
    import _mixed_signal_native as native
    from programs.tests._hostpaths import require_repo
    root, component, *_ = setup(monkeypatch, tmp_path, 'M08')
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                        'fixtures', 'm3_native', 'input', 'mixed_signal', 'native.json')
    original = json.loads(path.read_text())
    monkeypatch.setattr(native, 'contract', lambda *_args: original)
    assert consume(root, 'M08', component)['status'] == 'NOT_MEASURED'


def test_real_a19_population_reader_rejects_incomplete_blocks(monkeypatch, tmp_path):
    import analog_hardmacro_check as hardmacro
    import analog_native_flow as analog
    import flow109
    root = tmp_path.resolve()
    for name in ('reports/flow109/M08/current/component.json', 'reports/flow109/requests/' + 'c' * 64 + '.json',
                 'reports/analog_native/status.json'):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / 'reports/flow109/M08/current/component.json').write_text(json.dumps({'context_sha256': 'c' * 64}))
    (root / ('reports/flow109/requests/' + 'c' * 64 + '.json')).write_text(json.dumps({'requested_step': 'M08'}))
    (root / 'reports/analog_native/status.json').write_text(json.dumps({
        'source_sha256': sha(Path(analog.__file__)), 'steps': []}))
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda value: value)
    monkeypatch.setattr(mixed, 'consume_default_row_completion', lambda *_args: {'default_row_status': 'PASS', 'completed': True})
    monkeypatch.setattr(hardmacro, '_load_block_list', lambda _p: ['first', 'second'])
    with pytest.raises(mixed.Refusal, match='MIXED_ROW_A19_POPULATION_INVALID'):
        mixed._m09_prerequisites(root, {'m08_receipt': {'path': 'reports/flow109/M08/current/component.json'}})


def test_upstream_consumer_reopens_real_context_and_changed_readset(monkeypatch, tmp_path):
    import flow109
    install_fakes(monkeypatch)
    root = project(tmp_path, 'M06')
    features = next(row['features'] for row in flow109.load_registry()['reference_profiles']
                    if row['name'] == 'Mixed IC on-chip digital trim')
    plan = flow109.resolve_plan(features)
    request = flow109.execution_context(plan, 'M06', 'M06')
    path = root / 'reports/flow109/requests' / (request['context_sha256'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request))
    component = mixed.execute(root, request)
    manifest = {'upstream_receipts': {'M06': component['receipt']}}
    reader = getattr(mixed, '_accepted_upstream', None)
    if reader is None:
        # Old completion's actual PASS is the baseline observation.
        observed = mixed.consume_default_row_completion(root, request, component)
        assert observed['default_row_status'] == 'PASS'
        return
    accepted = reader(root, manifest, 'M06')
    assert accepted['default_row_status'] == 'PASS'
    (root / 'input.bin').write_text('changed material')
    with pytest.raises(mixed.Refusal, match='M89_UPSTREAM_NOT_ACCEPTED'):
        reader(root, manifest, 'M06')


def test_canonical_selected_row_consumes_metric_failure_when_integrated(monkeypatch, tmp_path):
    import flow109
    root, component, cosim, *_ = setup(monkeypatch, tmp_path, 'M08')
    value = json.loads(cosim.read_text())
    value['scenarios'][0]['criteria'][0]['measured'] = 2.0
    cosim.write_text(json.dumps(value))
    result = flow109._selected_step_result(root, context('M08'), component, mixed)
    if hasattr(metrics, 'accept_m89'):
        assert result['metric_acceptance_status'] == 'FAIL', result
        assert result['default_row_status'] == 'FAIL', result
        assert result['completed'] is False
    else:
        # Standalone owner branch requires the separately delivered root patch.
        assert result['default_row_status'] == 'PASS'
        assert 'metric_acceptance' not in result
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False


@pytest.mark.parametrize('step', ['D69', 'D70', 'M05'])
def test_existing_material_consumers_do_not_promote_upstream_components(monkeypatch, tmp_path, step):
    import flow109
    import flow109_final_extract as extract
    import flow109_final_electrical as electrical
    import mixed_signal_m3_run as m3
    reader = getattr(mixed, '_accepted_upstream', None)
    if reader is None:
        return  # This positive wiring check is not a baseline-red claim.
    root = tmp_path.resolve()
    features = next(row['features'] for row in flow109.load_registry()['reference_profiles']
                    if row['name'] == 'Mixed IC on-chip digital trim')
    request = flow109.execution_context(flow109.resolve_plan(features), step, step)
    request_path = root / 'reports/flow109/requests' / (request['context_sha256'] + '.json')
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request))
    record = root / 'component.json'
    record.write_text(json.dumps({'context_sha256': request['context_sha256'], 'component_status': 'PASS'}))
    calls = []
    monkeypatch.setattr(extract, 'validate_final_parasitics', lambda *args: calls.append('D69') or {})
    monkeypatch.setattr(electrical, 'validate_final_electrical', lambda *args: calls.append('D70') or {})
    monkeypatch.setattr(m3, 'audit', lambda *_args: calls.append('M05') or {'verdict': 'NOT_MEASURED'})
    manifest = {'upstream_receipts': {step: {'path': 'component.json', 'sha256': sha(record)}}}
    if step == 'D69':
        manifest['d69_receipt'] = manifest['upstream_receipts'][step]
    with pytest.raises(mixed.Refusal) as exc:
        reader(root, manifest, step)
    assert calls == [step]
    assert exc.value.code == ('M05_SUBSTRATE_SUPPLY_MODEL_UNSUPPORTED_OPEN_DEFAULT' if step == 'M05'
                              else 'M89_UPSTREAM_NOT_ACCEPTED')
    assert exc.value.status == 'NOT_MEASURED'


@pytest.mark.parametrize('change', ['linked', 'wrapper_claims_pass', 'missing_raw',
                                    'changed_raw', 'foreign_raw', 'selected_obligations'])
def test_canonical_upstream_raw_link_uses_real_owner_reader(monkeypatch, tmp_path, record_property, change):
    """Only native subprocess is controlled; request/manifest/receipt readers run.

    A genuine canonical wrapper of a controlled native FAIL must retain FAIL.
    This is link/error propagation evidence, not positive native acceptance.
    """
    import os
    import shutil
    import flow109
    import librelane_contract as contract
    from programs.tests._hostpaths import require_repo

    root = tmp_path / 'linked_owner'
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'm3_native')
    shutil.copytree(fixture, root)
    geometry = root / 'phase3/mixed_signal/top_merged.gds'
    geometry.parent.mkdir(parents=True)
    geometry.write_text('SOURCE_CONTROL geometry; no native qualification\n')
    (root / 'phase3/stage3/pnr/routed.def').write_text('SOURCE_CONTROL routed input\n')
    sdc = root / 'phase2/stage2/constraints/bridge_top.sdc'
    sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -period 20 [get_ports clk]\n')
    image = contract.resolve_image(root, record=False)
    features = next(row['features'] for row in flow109.load_registry()['reference_profiles']
                    if row['name'] == 'Mixed IC on-chip digital trim')
    request = flow109.execution_context(flow109.resolve_plan(features), 'M06', 'M06')
    request_path = root / 'reports/flow109/requests' / (request['context_sha256'] + '.json')
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request))
    manifest_path = root / 'input/flow109/M06.json'
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({
        'schema': mixed.INPUT_SCHEMA, 'step_id': 'M06', 'scope': 'candidate',
        'top': 'bridge_top', 'pdk': 'neutral', 'image': image,
        'required_scenarios': ['enable_receiver'], 'geometry_sha256': sha(geometry),
        'input_sha256': mixed._current_inputs(root, 'M06', 'bridge_top')}))
    calls = []
    def controlled_native_failure(argv, log):
        calls.append(argv)
        log.write_text('SOURCE_CONTROL native subprocess failure; no EDA launched\n')
        return {'argv': argv, 'returncode': 1,
                'stdout_sha256': sha(log), 'stderr_sha256': sha(log),
                'log': {'path': str(log), 'sha256': sha(log)}}
    monkeypatch.setattr(mixed, '_run', controlled_native_failure)
    raw = mixed.execute(root, request)
    assert raw['component_status'] == 'FAIL', raw
    assert len(calls) == 1
    direct = mixed.consume_default_row_completion(root, request, raw)
    assert direct['default_row_status'] == 'FAIL', direct
    wrapper = flow109._selected_step_result(root, request, raw, mixed)
    assert wrapper['schema'] == mixed.COMPLETION_SCHEMA
    assert wrapper['component_receipt'] == direct['component_receipt']
    assert wrapper != raw
    wrapper_path = root / 'reports/flow109/default_rows/M06.json'
    raw_path = root / raw['receipt']['path']
    if change == 'wrapper_claims_pass':
        wrapper.update(default_row_status='PASS', completed=True)
    elif change == 'missing_raw':
        raw_path.unlink()
    elif change == 'changed_raw':
        value = json.loads(raw_path.read_text()); value['reason'] = 'changed component bytes'
        raw_path.write_text(json.dumps(value))
    elif change == 'foreign_raw':
        # A linked receipt from another attempt/context is not this wrapper's owner.
        foreign = root / 'reports/flow109/M06/foreign/component.json'
        foreign.parent.mkdir(parents=True)
        value = dict(raw, context_sha256='f' * 64,
                     receipt={'path': str(foreign.relative_to(root))})
        foreign.write_text(json.dumps(value))
        wrapper['component_receipt'] = {'path': str(foreign.relative_to(root)), 'sha256': sha(foreign)}
        wrapper['receipt'] = value['receipt']
    elif change == 'selected_obligations':
        wrapper['selected_obligations'] = []
    wrapper_path.write_text(json.dumps(wrapper))
    manifest = {'upstream_receipts': {'M06': {'path': str(wrapper_path.relative_to(root)),
                                            'sha256': sha(wrapper_path)}}}
    with pytest.raises(mixed.Refusal) as exc:
        mixed._accepted_upstream(root, manifest, 'M06')
    if change in ('linked', 'wrapper_claims_pass'):
        assert exc.value.status == direct['default_row_status'], str(exc.value)
    elif change == 'selected_obligations':
        assert exc.value.code == 'M89_UPSTREAM_COMPLETION_MISMATCH', str(exc.value)
    else:
        assert exc.value.status == 'NOT_MEASURED', str(exc.value)
    record_property('scope', 'actual canonical/raw receipt readers; only mixed._run mocked; no native benchmark')
    record_property('change', change)
    record_property('raw_owner_completion', direct)
    record_property('upstream_refusal', {'code': exc.value.code, 'status': exc.value.status})
    record_property('image', image)
    record_property('source_sha256', mixed.operation_sources())
    assert os.environ.get(contract.LOCAL_ATTESTATION_ENV), 'fresh live launch identity is required'


@pytest.mark.parametrize('case,expected', [
    ('noise', 'PASS'), ('noise_limit', 'FAIL'), ('noise_unit', 'NOT_MEASURED'),
    ('crosstalk', 'PASS'), ('settled_max', 'PASS'),
    ('missing_interface', 'NOT_MEASURED'), ('foreign_scenario', 'NOT_MEASURED'),
    ('incomplete_population', 'NOT_MEASURED'), ('unobserved_calibration', 'NOT_MEASURED')])
def test_final_metrics_consume_current_producer_observations(monkeypatch, tmp_path, record_property, case, expected):
    """Existing producer parser feeds the final numeric consumer, no row credit.

    The optional observation is a retained real neutral ngspice run. Without it,
    the existing native-format source fixture exercises the same parser; neither
    mode asserts real PDK/final-layout or upstream-owner acceptance.
    """
    import copy
    import hashlib
    import os
    import _mixed_signal_current as current
    from test_mixed_signal_current_contract import _current_case, _coupling_observations

    root, component, cosim_path, si_path, bounds_path, _ = setup(monkeypatch, tmp_path, 'M08')
    observation_path = os.environ.get('M89_NATIVE_OBSERVATION')
    if observation_path:
        path = Path(observation_path)
        record = json.loads(path.read_text())
        for name, digest in record['files'].items():
            assert hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == digest
        measured = current.measure(path.parent, record['inputs'], record['scenario'],
                                   path.parent / 'source_run/functional', 'source_run')
        assert measured == record['measured']
        sample_metrics = record['native_sample_metrics']
        record_property('observation_sha256', sha(path))
        record_property('observation_scope', record['scope'])
    else:
        source = tmp_path / 'source_observation'
        source.mkdir()
        data, row, _drive = _current_case(source)
        work = source / 'observations'
        _coupling_observations(work, data, row)
        measured = current.measure(source, data, row, work, 'source_run')
        sample_metrics = {'settled_voltage_max_v': 1.0}
        measured['id'] = 'functional'
        record_property('observation_scope', 'native-format source fixture only')
    assert measured['verdict'] == 'PASS'
    cosim = json.loads(cosim_path.read_text())
    cosim['scenarios'][0]['metrics'] = sample_metrics
    interfaces = [copy.deepcopy(measured)]
    if case == 'missing_interface':
        interfaces = []
    elif case == 'foreign_scenario':
        interfaces[0]['id'] = 'foreign'
    elif case == 'incomplete_population':
        extra = copy.deepcopy(cosim['scenarios'][0]); extra['id'] = 'calibration'
        cosim['scenarios'].append(extra)
    cosim_path.write_text(json.dumps(cosim))
    # This is the real physical producer field; legacy receiver_noise is absent.
    si_path.write_text(json.dumps({'current_interfaces': interfaces}))
    metric, unit, limit = 'integrated_output_noise_v_rms', 'V_RMS', 1.0
    if case == 'noise_limit':
        limit = 0.0
    elif case == 'noise_unit':
        unit = 'V'
    elif case == 'crosstalk':
        metric, unit, limit = 'peak_crosstalk_v', 'V_PEAK', 2.0
    elif case == 'settled_max':
        metric, unit, limit = 'settled_voltage_max_v', 'V', 1.1
    elif case == 'unobserved_calibration':
        metric, unit = 'calibration_error', 'V'
    key = 'functional/' + metric
    approved(root, str(bounds_path.relative_to(root)), limits={key: {'max': limit}}, units={key: unit})
    result = mixed.bind_metrics(root, context('M08'), component)
    record_property('case', case)
    record_property('consumer_result', result)
    assert result['status'] == expected, result
    if expected in ('PASS', 'FAIL'):
        bound = next(r for r in result['obligations'] if r.get('measurement', {}).get('name') == key)
        assert bound['measurement']['unit'] == unit
        if metric == 'integrated_output_noise_v_rms':
            assert bound['measurement']['value'] == measured['noise']['metrics'][metric]['measured']
    assert result['whole_ic_acceptance'] == 'NOT_MEASURED'
