"""D70 completion/metric controls. Upstream qualification is SOFTWARE ONLY.

Synthetic native receipts exercise readback, not a real D69/mission signoff.
The retained calibration test reads real ngspice output for parser coverage.
"""
import copy
import json
from pathlib import Path

import pytest

import flow109
import flow109_final_electrical as final
import flow109_metric_acceptance as metrics
from test_flow109_analog_final_mission import case, put
from test_flow109_scan_timing_modes import software, qualified, ref, put as write


def context(profile='Analog IC external trim', **changes):
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                                  if p['name'] == profile))
    features.update(changes)
    return flow109.execution_context(flow109.resolve_plan(features), 'D70', 'D70')


def approved(project, name, **payload):
    source = put(project, 'input/authority-' + name + '.json', payload)
    return put(project, 'requirements/final_electrical/' + name + '.json', {
        'schema': metrics.AUTHORITY_SCHEMA, **payload,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': source}})


def software_mission(tmp_path, monkeypatch, upper=0.7, **features):
    import analog_bound_measurements as measured
    import analog_native_flow
    import librelane_contract as launch
    project, manifest, basis = case(tmp_path, monkeypatch, upper)
    ctx = context(**features)
    monkeypatch.setattr(final, 'require_launch_admission', lambda *a, **k: None)
    monkeypatch.setattr(launch, 'local_image_attestation', lambda *a: {'image': 'SOFTWARE_ONLY_NOT_NATIVE'})

    def synthetic_acquisition(self, program, argv, **kwargs):
        destination = Path(argv[argv.index('--out') + 1]); destination.mkdir(parents=True)
        paths = {name: final.files._bound(project, manifest['scenarios'][0][name])
                 for name in ('bindings', 'testbench', 'load', 'spec')}
        netlist = final.files._bound(project, basis['simulation_netlists']['tt'])
        inputs = {name: {'path': str(path.resolve()), 'sha256': final.digest(path)} for name, path in
                  [('netlist', netlist), ('testbench', paths['testbench']), ('bindings', paths['bindings']),
                   ('deck', paths['testbench'])]}
        inputs.update(measured.consumed_input_views(project, paths['testbench']))
        log = destination / 'stdout.log'; log.write_text('SOFTWARE_ONLY acquisition\nMEAS vout=0.6\n')
        execution = {'returncode': 0, 'log': str(log), 'log_sha256': final.digest(log)}
        put(project, str(destination.relative_to(project) / 'result.json'), {
            'status': 'PASS', 'native_inputs': inputs, 'bindings': json.loads(paths['bindings'].read_text()),
            'measurements': {'vout': 0.6}, 'temperature': {'matched': True}, 'executions': [execution]})
        return execution

    monkeypatch.setattr(analog_native_flow.NativeCommands, '__call__', synthetic_acquisition)
    result = final.execute(project, ctx)
    assert result['component_status'] in ('PASS', 'FAIL'), result
    approved(project, 'final_mission_scenario_coverage', required_items=[{'scenario': 'loaded', 'corner': 'tt'}])
    approved(project, 'final_analog_mission_targets',
             limits={'loaded': {'vout': {'min': 0.5, 'max': upper}}}, units={'loaded': {'vout': 'V'}})
    return project, ctx, result, manifest


def completion(project, ctx, result):
    # Existing canonical seam also executes on the exact base. No import or
    # missing-function failure is used as the reverse behavioral observation.
    return flow109._selected_step_result(project, ctx, result, final)


def obligations(result):
    return {row['metric']: row for row in result['metric_acceptance']['obligations']}


def test_current_analog_values_bind_approved_limits_without_upstream_promotion(tmp_path, monkeypatch):
    project, ctx, native, _ = software_mission(tmp_path, monkeypatch, requires_ir=False, requires_em=False)
    result = completion(project, ctx, native)
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    measured = obligations(result)
    assert {name: row['status'] for name, row in measured.items()} == {
        'final_mission_scenario_coverage': 'PASS', 'final_analog_mission_targets': 'PASS'}
    assert result['metric_acceptance_status'] == 'PASS'
    assert {'D65', 'D69'} <= set(result['metric_acceptance']['required_acceptance_dependencies'])
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED' and result['delivery_accepted'] is False


def test_retained_measured_failure_survives_a_functional_pass_claim(tmp_path, monkeypatch):
    project, ctx, native, _ = software_mission(tmp_path, monkeypatch, upper=0.55)
    assert native['component_status'] == 'FAIL'
    claimed = {**native, 'component_status': 'PASS'}
    result = completion(project, ctx, claimed)
    # Substantive base-red: the base seam returns NOT_MEASURED here. The
    # candidate must reopen the retained 0.6 > 0.55 violation and return FAIL.
    assert result['flow109_acceptance'] == 'FAIL', result
    assert obligations(result)['final_analog_mission_targets']['status'] == 'FAIL'


@pytest.mark.parametrize('fault', ['netlist', 'load', 'bindings', 'limits', 'model', 'native_log',
                                 'receipt', 'foreign_context', 'foreign_receipt', 'manifest_alias',
                                 'empty_scenarios', 'missing_corner'])
def test_changed_or_missing_final_input_never_measures_pass(tmp_path, monkeypatch, fault):
    project, ctx, native, manifest = software_mission(tmp_path, monkeypatch)
    if fault in ('netlist', 'load', 'bindings', 'limits', 'model'):
        name = {'netlist': 'network.sp', 'load': 'load.sp', 'bindings': 'bindings.json',
                'limits': 'spec.json', 'model': 'models.lib'}[fault]
        (project / name).write_text('SOFTWARE_ONLY changed input\n')
    elif fault == 'native_log':
        receipt = final._read(final.files._bound(project, native['scenarios'][0]['native_receipt']))
        Path(receipt['executions'][0]['log']).write_text('SOFTWARE_ONLY changed native log\n')
    elif fault == 'receipt':
        final.files._bound(project, native['receipt']).write_text('{}')
    elif fault == 'foreign_context':
        ctx = context(requires_thermal=True)
    elif fault == 'foreign_receipt':
        other = tmp_path / 'other-carrier.json'
        other.write_text(final.files._bound(project, native['receipt']).read_text())
        native = {**native, 'receipt': {'path': str(other), 'sha256': final.digest(other)}}
    elif fault == 'manifest_alias':
        original = final._read(final.files._bound(project, native['receipt']))
        original['manifest'] = put(project, 'input/old-mission.json', manifest)
        native['receipt'] = put(project, 'SOFTWARE_ONLY-alias.json', original)
    else:
        manifest['scenarios'] = [] if fault == 'empty_scenarios' else manifest['scenarios']
        if fault == 'missing_corner': manifest['scenarios'][0].pop('corner')
        put(project, final.INPUT, manifest)
    if fault == 'foreign_context':
        # Caller wrapper identity matches the new request, retained acquisition does not.
        native = {**native, 'context_sha256': ctx['context_sha256']}
    result = completion(project, ctx, native)
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert all(row['status'] == 'NOT_MEASURED' for row in obligations(result).values())


@pytest.mark.parametrize('fault', ['missing', 'stale_approval', 'different_limits', 'different_units', 'unvalidated_empty'])
def test_approved_requirement_authority_is_consumed(tmp_path, monkeypatch, fault):
    project, ctx, native, _ = software_mission(tmp_path, monkeypatch)
    name = 'final_mission_scenario_coverage' if fault == 'unvalidated_empty' else 'final_analog_mission_targets'
    path = project / ('requirements/final_electrical/' + name + '.json')
    if fault == 'missing': path.unlink()
    elif fault == 'stale_approval': (project / ('input/authority-' + name + '.json')).write_text('{}')
    else:
        body = json.loads(path.read_text())
        if fault == 'different_limits': body['limits']['loaded']['vout']['max'] = 1.0
        elif fault == 'different_units': body['units']['loaded']['vout'] = 'mV'
        else: body['required_items'] = []
        path.write_text(json.dumps(body))
    result = completion(project, ctx, native)
    assert obligations(result)[name]['status'] == 'NOT_MEASURED'


def test_selected_unsupported_requirements_stay_precisely_unmeasured(tmp_path, monkeypatch):
    project, ctx, native, _ = software_mission(tmp_path, monkeypatch, requires_thermal=True, requires_aging=True)
    result = completion(project, ctx, native); measured = obligations(result)
    assert measured['final_analog_mission_targets']['status'] == 'PASS'
    for name in ('final_ir_em_thermal_aging_targets', 'thermal_temperature_gradient_targets',
                 'thermal_aware_em_timing_feedback', 'aged_analog_margin_targets', 'aging_mission_coverage'):
        assert measured[name]['status'] == 'NOT_MEASURED' and 'PRODUCER_UNAVAILABLE' in measured[name]['reason']
    assert 'final_timing_si_targets' not in measured and 'final_sdf_annotation' not in measured


@pytest.mark.parametrize('damage', ['clean', 'shift-hold', 'capture-setup', 'missing-capture',
                                   'changed-library', 'changed-functional-sdc', 'ir-fail'])
def test_final_scan_modes_feed_the_canonical_metric_consumer(software, monkeypatch, damage):
    project, paths, state, native, failures = software
    ctx = qualified(project, 'D70', True)
    if damage == 'shift-hold': failures['shift'] = 'hold_ws'
    if damage == 'capture-setup': failures['capture'] = 'setup_ws'
    parasitics = {'odb': ref(project, paths['routed.odb']), 'filled_def': ref(project, paths['routed.def']),
        'adopted_views': {'netlist': ref(project, paths['netlist.v']), 'sdc': ref(project, paths['functional.sdc'])},
        'spefs': {'nom': ref(project, paths['nom.spef'])}, 'final_spefs': {'nom': ref(project, paths['nom.spef'])}}
    d69 = ref(project, write(project / 'input/software-final.json', {'scope': 'SOFTWARE_ONLY_NOT_D69_ACCEPTANCE'}))
    write(project / final.INPUT, {'schema': final.SCHEMA, 'required_corners': ['nom_tt'],
        'final_parasitics_receipt': d69, 'librelane': {**native, 'pdk_root': str(native['pdk_root'])}})
    monkeypatch.setattr(final.extract, 'validate_final_parasitics', lambda *a: parasitics)
    result = final.execute(project, ctx)
    if damage == 'missing-capture':
        result['scan_timing_coverage']['modes'].pop('capture')
        result['receipt'] = put(project, 'SOFTWARE_ONLY-incomplete.json', result)
    if damage == 'changed-library': paths['cells.lib'].write_text('SOFTWARE_ONLY changed library')
    if damage == 'changed-functional-sdc': paths['functional.sdc'].write_text('SOFTWARE_ONLY changed SDC')
    if damage == 'ir-fail':
        put(project, final.OWNER_INPUT, {'schema': final.OWNER_INPUT_SCHEMA, 'd70_component': result['receipt']})
        monkeypatch.setattr(final, '_activity_binding', lambda *a: {'scope': 'SOFTWARE_ONLY D55 double'})
        monkeypatch.setattr(final, '_power_binding', lambda *a: {'verdict': 'PASS', 'scope': 'SOFTWARE_ONLY D56 double'})
        monkeypatch.setattr(final, '_ir_binding', lambda *a: {'verdict': 'FAIL', 'scope': 'SOFTWARE_ONLY D57 double'})
    # A claimed functional PASS must not hide retained shift/capture violations.
    result = completion(project, ctx, {**result, 'component_status': 'PASS'})
    expected = 'FAIL' if damage in ('shift-hold', 'capture-setup', 'ir-fail') else 'NOT_MEASURED'
    assert result['flow109_acceptance'] == expected, result
    measured = obligations(result)
    assert measured['final_timing_si_targets']['status'] == ('NOT_MEASURED' if damage == 'ir-fail' else expected)
    if damage == 'ir-fail': assert measured['final_ir_em_thermal_aging_targets']['status'] == 'FAIL'
    assert measured['final_sdf_annotation']['status'] == 'NOT_MEASURED'


def test_retained_real_ngspice_output_is_read_as_values_not_exit_zero(tmp_path, monkeypatch):
    """Raw parser control only: no synthetic final-geometry qualification claim."""
    from _hostpaths import require_repo
    import analog_bound_measurements as measured
    base = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'calibration')
    deck = base / 'ngspice47_cal_meas_rows.sp'
    transcript = base / 'ngspice47_cal_meas_rows.log'
    reference = {'path': str(deck), 'sha256': final.digest(deck)}
    binding = {'measurements': {'cal_avg': {'analysis': 'TRAN', 'unit': 'V'}}}
    record = {'native_inputs': {'deck': reference, 'netlist': reference, 'testbench': reference,
                               'bindings': reference}, 'bindings': binding,
              'executions': [{'log': str(transcript), 'log_sha256': final.digest(transcript), 'returncode': 0}],
              'status': 'PASS', 'temperature': {'matched': True}, 'measurements': {'cal_avg': 0.525819}}
    # Calibration owns no D69/model/load identity. This explicit upstream double
    # bounds the test to raw-value parsing and immutable transcript readback.
    monkeypatch.setattr(measured, 'validate_consumed_inputs', lambda *a: (True, 'SOFTWARE parser control'))
    expected = {'netlist': reference, 'testbench': reference, 'bindings': reference,
                'load': reference, 'models': [reference]}
    record['native_inputs']['include:calibration'] = reference
    status, values = final._analog_native_values(tmp_path, record, binding, expected)
    assert status == 'PASS' and values == {'cal_avg': 0.525819}
    record['measurements']['cal_avg'] = 0
    with pytest.raises(final.AdmissionRefusal, match='D70_ANALOG_RAW_MEASUREMENT_MISSING'):
        final._analog_native_values(tmp_path, record, binding, expected)


@pytest.mark.parametrize('upper,expected', [(0.7, 'PASS'), (0.55, 'FAIL')])
def test_minimal_ngspice_native_results_feed_metric_consumer(tmp_path, monkeypatch, upper, expected):
    """Real ngspice acquisition; SOFTWARE D69/model qualification, no IC claim."""
    project, _, _ = case(tmp_path, monkeypatch, upper)
    ctx = context(requires_ir=False, requires_em=False)
    native = final.execute(project, ctx)
    assert native['component_status'] == expected, native
    approved(project, 'final_mission_scenario_coverage', required_items=[{'scenario': 'loaded', 'corner': 'tt'}])
    approved(project, 'final_analog_mission_targets',
             limits={'loaded': {'vout': {'min': 0.5, 'max': upper}}}, units={'loaded': {'vout': 'V'}})
    result = completion(project, ctx, native)
    measured = obligations(result)
    assert measured['final_analog_mission_targets']['status'] == expected, measured
    assert measured['final_mission_scenario_coverage']['status'] == 'PASS'
    assert native['scenarios'][0]['values']['vout'] == pytest.approx(0.6)
    assert result['flow109_acceptance'] == ('FAIL' if expected == 'FAIL' else 'NOT_MEASURED')


def _all_evidence_qualification_case(tmp_path, monkeypatch, damage):
    """SOFTWARE upstream authorities; actual owner, admission and completion readers.

    These synthetic prior rows and qualification references only exercise the
    existing reader contract. They are never native platform/design evidence.
    """
    import shutil
    import flow109_admission as admission
    from test_flow109_final_perc import _canonical_d65
    upper = 0.55 if damage == 'measured_failure' else 0.7
    project, ctx, _, manifest = software_mission(tmp_path, monkeypatch, upper=upper,
                                               requires_ir=False, requires_em=False)
    # Restore the real engineering-launch reader as well as retaining the real
    # strict parser. Only the previously explicit native/upstream doubles remain.
    monkeypatch.setattr(final, 'require_launch_admission', admission.require_launch_admission)
    if damage not in ('absent_runtime', 'measured_failure'):
        runtime, entries = [], []
        evidence = put(project, 'input/software-qualification-reference.json',
                       {'scope': 'SOFTWARE reader contract only; not native qualification'})
        for use in ctx['resolved_row']['tool_uses']:
            binary = Path(shutil.which(use['executable_name'])).resolve()
            identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'],
                'version': 'SOFTWARE_ONLY', 'build_sha256': final.digest(binary),
                'executable': {'path': str(binary), 'sha256': final.digest(binary)},
                'config': manifest['scenarios'][0]['bindings'], 'pdk': manifest['models']['tt'][0],
                'deck': manifest['scenarios'][0]['testbench'], 'corner': 'tt',
                'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps']}}
            entry = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                     'reference_evidence': [evidence]}
            entries.append(entry)
            runtime.append({**identity, 'qualification_sha256': admission.canonical_sha(entry)})
        registry = 'input/software-D70-qualification.json'
        put(project, registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': entries})
        ctx = flow109.execution_context(flow109.resolve_plan(ctx['features']), 'D70', 'D70',
            runtime_tool_uses=runtime, qualification_registry=registry)
    native = final.execute(project, ctx)
    assert native['component_status'] == ('FAIL' if damage == 'measured_failure' else 'PASS'), native
    basis = final._analog_basis(project, manifest['final_parasitics_receipt'])
    basis['filled_def'] = put(project, 'phase3/stage3/pnr/final.def', 'SOFTWARE_ONLY final DEF\n')
    basis['final_gds'] = put(project, 'final.gds', 'SOFTWARE_ONLY final GDS\n')
    d65, _ = _canonical_d65(project, basis['filled_def'])
    document = final._read(final.files._bound(project, d65))
    inputs = document['current_step_declared_producers']['input_identity']['files']
    for view in (basis['final_gds'], basis['simulation_netlists']['tt']):
        inputs[view['path']] = view['sha256']
    document['canonical_receipts'][0]['current_step_declared_producers'] = copy.deepcopy(
        document['current_step_declared_producers'])
    d65 = put(project, d65['path'], document)
    # The actual D65 binding reader also consumes the D69 adopted logical view.
    basis['adopted_views'] = {'netlist': basis['simulation_netlists']['tt']}
    plan = flow109.resolve_plan(ctx['features'])
    selected = {row['id'] for row in plan['rows']}
    for step in [*ctx['resolved_row']['acceptance_deps'], 'D03']:
        if step not in selected:
            continue
        original = flow109.execution_context(plan, step, step)
        flow109.validate_execution_context(original)
        put(project, 'reports/flow109/requests/' + original['context_sha256'] + '.json', original)
        prior = {'step_id': step, 'default_row_status': 'PASS', 'completed': True,
                 'context_sha256': original['context_sha256'], 'scope': 'SOFTWARE_ONLY upstream double'}
        if step == 'D69': prior['receipt'] = manifest['final_parasitics_receipt']
        if step == 'D65': prior['canonical_receipt'] = d65
        put(project, 'reports/flow109/default_rows/' + step + '.json', prior)
    if damage == 'stale_reference':
        (project / 'input/software-qualification-reference.json').write_text('SOFTWARE_ONLY changed reference')
    if damage == 'absent_registry':
        (project / registry).unlink()
    if damage in ('unsupported', 'stale_digest'):
        if damage == 'unsupported': entries[0]['status'] = 'UNSUPPORTED'
        else: entries[0]['reference_evidence'] = [manifest['scenarios'][0]['load']]
        put(project, registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': entries})
    if damage == 'changed_runtime':
        directory = project / 'software-runtime'; directory.mkdir()
        use = ctx['resolved_row']['tool_uses'][0]
        (directory / use['executable_name']).symlink_to(Path(shutil.which('sh')).resolve())
        import os
        monkeypatch.setenv('PATH', str(directory) + os.pathsep + os.environ['PATH'])
    return project, ctx, native


@pytest.mark.parametrize('damage,expected,reason', [
    ('absent_runtime', 'NOT_MEASURED', 'QUALIFICATION_RUNTIME_ABSENT'),
    ('absent_registry', 'NOT_MEASURED', 'QUALIFICATION_INPUT_ABSENT'),
    ('valid', 'PASS', 'QUALIFICATION_BINDINGS_CURRENT'),
    ('stale_reference', 'NOT_MEASURED', 'QUALIFICATION_STALE'),
    ('unsupported', 'NOT_MEASURED', 'QUALIFICATION_UNSUPPORTED'),
    ('stale_digest', 'NOT_MEASURED', 'QUALIFICATION_STALE'),
    ('changed_runtime', 'NOT_MEASURED', 'QUALIFICATION_RUNTIME_UNSUPPORTED'),
    ('measured_failure', 'FAIL', 'D70_MEASURED_METRIC_FAILURE'),
])
def test_existing_completion_requires_current_d70_qualification(tmp_path, monkeypatch, damage, expected, reason):
    project, ctx, native = _all_evidence_qualification_case(tmp_path, monkeypatch, damage)
    record = final._read(final.files._bound(project, native['receipt']))
    assert final._metric_prerequisites(project, ctx, record)['status'] == 'PASS'
    result = completion(project, ctx, native)
    acceptance = result['metric_acceptance']
    put(project, 'QUALIFICATION_COMPLETION_OBSERVATION.json', result)
    if damage in ('absent_runtime', 'valid', 'measured_failure'):
        assert acceptance['prerequisites']['status'] == 'PASS', acceptance['prerequisites']
        assert acceptance['metric_status'] == ('FAIL' if expected == 'FAIL' else 'PASS')
    else:
        assert acceptance['metric_status'] == 'NOT_MEASURED'
    assert result['default_row_status'] == expected, result
    assert result['completed'] is (expected == 'PASS')
    if expected == 'PASS':
        assert result['qualification'] == 'PASS'
        assert acceptance['qualification_admission']['reason'] == reason
    elif damage in ('absent_runtime', 'measured_failure'):
        assert acceptance['reason'] == reason
    else:
        assert {row['reason'] for row in acceptance['obligations']} == {reason}
