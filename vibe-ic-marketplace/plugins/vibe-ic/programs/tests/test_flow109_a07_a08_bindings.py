"""SOURCE_ONLY native neutral controls; no ADC, PVT population or row qualification.

The scalar fixture runs the existing nominal producer and normal completion.
PVT parser cases explicitly use a partial native-format source fixture: they
exercise refusals, never attest an executed PVT population.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import analog_native_flow as native
import flow109
import flow109_metric_acceptance as metrics
from _analog_producer_fixture import block, make_project
from _hostpaths import require_repo


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(root, relative, body):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def authority(root, metric, *, ceiling=.7):
    source = root / 'input/independent-bound-source.txt'
    source.write_text('Synthetic independent source-control authority; no IC qualification.')
    document = {'schema': metrics.AUTHORITY_SCHEMA, 'approval': {'status': 'APPROVED',
        'authority': 'requirements_owner', 'source_reference': {'path': str(source.relative_to(root)), 'sha256': sha(source)}},
        'limits': {'unit_alpha': {'vout_dc': {'min': .5, 'max': ceiling}}},
        'units': {'unit_alpha': {'vout_dc': 'V'}}}
    if metric == 'early_model_correlation':
        known = put(root, 'input/independent-reference.json', {'measurements': {'unit_alpha': {'vout_dc': .6}},
                                                              'units': {'unit_alpha': {'vout_dc': 'V'}}})
        document['reference'] = {'path': str(known.relative_to(root)), 'sha256': sha(known)}
        document['limits'] = {'unit_alpha': {'vout_dc': {'max': .01}}}
    return put(root, 'requirements/base_A6/' + metric + '.json', document)


def make_case(root, monkeypatch, *, ceiling=.7, missing_correlation=False, extra_point=False, prepare=None):
    image = os.environ.get('VIBEIC_EDA_IMAGE')
    if not image or not shutil.which('ngspice'):
        pytest.skip('actual stated-image ngspice execution environment required')
    make_project(root, [block('unit_alpha', 'amplifier', [{'name': 'vout_dc', 'min': 0., 'max': 1., 'unit': 'V'}])])
    directory = root / 'phase3/analog/unit_alpha'
    directory.mkdir()
    (root / 'input').mkdir(exist_ok=True)
    library = root / 'input/transfer.lib'
    library.write_text('.param transfer_factor=0.6\n')
    (directory / 'unit_alpha.sp').write_text('* neutral delivered linear transfer\n.include ../../../input/transfer.lib\n'
        '.subckt unit_alpha p q\ne_transfer q 0 p 0 {transfer_factor}\n.ends unit_alpha\n')
    (directory / 'tb_unit_alpha.sp').write_text('* neutral native OP control\n.include unit_alpha.sp\n'
        'v_drive p 0 1\nxdut p q unit_alpha\n.control\nop\n'
        'let observed = v(q)\necho "MEAS vout_dc=" $&observed\n.endc\n.end\n')
    put(root, 'phase3/analog/unit_alpha/spec.json', {'specs': [{'name': 'vout_dc', 'min': 0., 'max': 1., 'unit': 'V'}]})
    put(root, 'input/analog_flow.json', {})
    nominal = authority(root, 'nominal_performance', ceiling=ceiling)
    if extra_point:
        d = json.loads(nominal.read_text())
        d['limits']['unit_alpha']['missing_point'] = {'max': 1.}
        d['units']['unit_alpha']['missing_point'] = 'V'
        nominal.write_text(json.dumps(d))
    correlation = authority(root, 'early_model_correlation')
    if missing_correlation:
        correlation.unlink()
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    monkeypatch.setattr(native, 'execute_window', lambda project, context: native.run_window(project,
        SimpleNamespace(entry_step='A07', exit_step='A07', container='', image=image, transport='LOCAL'),
        features={'has_analog': True}))
    profile = next(v for v in flow109.load_registry()['reference_profiles'] if v['name'] == 'Analog model-IP')
    plan = flow109.resolve_plan(profile['features'])
    context = flow109.execution_context(plan, 'A07', 'A07')
    if prepare:
        prepare(root)
    component = native.execute(root, context)
    component['context_sha256'] = context['context_sha256']
    return root, context, component, nominal, correlation, library


@pytest.fixture
def case(tmp_path, monkeypatch):
    return make_case(tmp_path, monkeypatch)


def selected(case):
    root, context, component, *_ = case
    return flow109._selected_step_result(root, context, component, native)


def test_normal_native_value_binding_without_qualification_credit(case):
    root, _, component, *_ = case
    result = selected(case)
    assert component['component_status'] == 'PASS'
    assert result['metric_acceptance_status'] == 'PASS', result
    assert result['metric_acceptance']['native_observation']['unit_alpha']['vout_dc']['value'] == pytest.approx(.6)
    assert result['default_row_status'] == 'NOT_MEASURED' and not result['completed']
    assert not (root / 'qualifications.json').exists()


def test_independent_above_bound_native_value_blocks_normal_completion(tmp_path, monkeypatch):
    case = make_case(tmp_path, monkeypatch, ceiling=.55)
    assert case[2]['component_status'] == 'PASS'  # native source bounds permit .6
    result = selected(case)
    assert result['default_row_status'] == 'FAIL', result
    assert result['metric_acceptance']['metrics']['nominal_performance']['comparisons'][0]['value'] == pytest.approx(.6)
    assert not result['completed']


@pytest.mark.parametrize('gap', ['authority', 'point'])
def test_measured_failure_survives_later_missing_input(tmp_path, monkeypatch, gap):
    case = make_case(tmp_path, monkeypatch, ceiling=.55, missing_correlation=gap == 'authority', extra_point=gap == 'point')
    result = selected(case)
    assert result['default_row_status'] == 'FAIL', result
    assert result['metric_acceptance']['metrics']['nominal_performance']['status'] == 'FAIL'


def test_missing_point_is_not_an_empty_valid_population(tmp_path, monkeypatch):
    result = selected(make_case(tmp_path, monkeypatch, extra_point=True))
    assert result['metric_acceptance_status'] == 'NOT_MEASURED', result
    assert result['default_row_status'] == 'NOT_MEASURED' and not result['completed']


@pytest.mark.parametrize('fault', ['library', 'log', 'bounds', 'method', 'tool', 'report'])
def test_changed_native_consumer_inputs_refuse(case, fault):
    root, _, component, nominal, _, library = case
    if fault == 'library':
        library.write_text('.param transfer_factor=0.8\n')
    elif fault == 'log':
        Path(component['native_results']['steps'][0]['executions'][0]['log']).write_text('MEAS vout_dc=0.6\n')
    elif fault == 'bounds':
        doc = json.loads(nominal.read_text());doc['limits']['unit_alpha']['vout_dc']['max'] = .8;nominal.write_text(json.dumps(doc))
    elif fault == 'method':
        path = root / 'phase3/analog/unit_alpha/tb_unit_alpha.sp';path.write_text(path.read_text().replace('v(q)', 'v(p)'))
    elif fault == 'tool':
        component['a07_invocation']['tools']['ngspice']['sha256'] = '0' * 64
    else:
        component['native_results']['steps'][0]['metrics']['vout_dc'] = .61
    result = selected(case)
    assert result['default_row_status'] == 'NOT_MEASURED' and not result['completed'], result


def test_unchanged_native_receipt_is_reused_without_execution(case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('consumer must not launch native work')
    monkeypatch.setattr(native.NativeCommands, '__call__', forbidden)
    first = selected(case)
    second = selected(case)
    assert first['metric_acceptance'] == second['metric_acceptance']
    assert second['metric_acceptance_status'] == 'PASS'


@pytest.mark.parametrize('value,expected', [(13., 'FAIL'), (14., 'PASS'), (15., 'PASS')])
def test_enob_declared_minimum_is_not_a_reversed_upper_bound(value, expected):
    # SOURCE_ONLY operator control, not a claimed ADC measurement.
    result = metrics._a0708_compare({'unit': {'enob': {'value': value, 'unit': 'bit'}}},
        {'unit': {'enob': {'min': 14.}}}, {'unit': {'enob': 'bit'}})
    assert result[0]['status'] == expected


def test_one_of_128_points_cannot_supply_nominal_enob(tmp_path):
    # Deliberately partial SOURCE_ONLY method fixture: no conversion is run.
    source = put(tmp_path, 'input/settings.json', {'series_length': 128})
    score = put(tmp_path, 'reports/score.json', {'points': [{'path': 'missing'}]})
    invocation = {'inputs': {str(source): sha(source), str(score): sha(score)}, 'tools': {}}
    with pytest.raises(metrics.MetricRefusal, match='A07_COMPLETE_INCREMENTAL_POINT_POPULATION_REQUIRED'):
        metrics._a07_incremental_observation(tmp_path, 'unit', {'measurement_studies': [{
            'kind': 'incremental_capture', 'result': str(score), 'settings': str(source)}]}, invocation)


def test_pvt_native_failure_survives_absent_corner_identity(tmp_path):
    context = {'requested_step': 'A08', 'context_sha256': 'c' * 64, 'resolved_row': {'id': 'A08'}}
    component = {'step_id': 'A08', 'component_status': 'FAIL', 'context_sha256': context['context_sha256'], 'native_results': {}}
    result = flow109._selected_step_result(tmp_path, context, component, native)
    assert result['default_row_status'] == 'FAIL'
    assert not result['completed']


def test_empty_pvt_component_cannot_become_row_pass(tmp_path):
    context = {'requested_step': 'A08', 'context_sha256': 'c' * 64, 'resolved_row': {'id': 'A08'}}
    component = {'step_id': 'A08', 'component_status': 'PASS', 'context_sha256': context['context_sha256'], 'native_results': {}}
    result = flow109._selected_step_result(tmp_path, context, component, native)
    assert result['default_row_status'] == 'NOT_MEASURED' and not result['completed']


def test_real_registry_obligations_are_the_owned_two_consumers():
    # Actual repository artifact, not a parallel registry or an edited row.
    registry = json.loads(require_repo('vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json').read_text())
    rows = {r['position']: r for r in registry['rows']}
    assert [o['metric'] for o in rows[15]['obligations']] == ['nominal_performance', 'early_model_correlation']
    assert [o['metric'] for o in rows[28]['obligations']] == ['pvt_load_modes', 'prelayout_performance']


@pytest.mark.parametrize('missing_nominal', [False, True])
def test_native_correlation_violation_survives_missing_nominal_authority(tmp_path, monkeypatch, missing_nominal):
    original = authority
    def declared(root, metric, **kwargs):
        path = original(root, metric, **kwargs)
        if metric == 'early_model_correlation':
            known = root / 'input/independent-reference.json'
            doc = json.loads(known.read_text())
            doc['measurements']['unit_alpha']['vout_dc'] = .58
            known.write_text(json.dumps(doc))
            req = json.loads(path.read_text())
            req['reference']['sha256'] = sha(known)
            path.write_text(json.dumps(req))
        elif missing_nominal:
            path.unlink()
        return path
    monkeypatch.setattr(__name__ + '.authority', declared)
    result = selected(make_case(tmp_path, monkeypatch))
    assert result['default_row_status'] == 'FAIL', result
    assert result['metric_acceptance']['metrics']['early_model_correlation']['comparisons'][0]['compared_value'] == pytest.approx(.02)


def partial_pvt_source_fixture(case):
    """Explicit SOURCE_ONLY partial PVT report, reusing a real scalar log.

    This constructs producer-format metadata to exercise the consumer refusal;
    it is not a native PVT producer run, qualification, or corner-population claim.
    """
    root, _, nominal, *_ = case
    requirement = put(root, 'requirements/base_A7/pvt_load_modes.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
            'source_reference': {'path': 'input/independent-bound-source.txt', 'sha256': sha(root / 'input/independent-bound-source.txt')}},
        'required_items': [{'block': 'unit_alpha', 'name': 'typical_27c'}, {'block': 'unit_alpha', 'name': 'slow_125c'}]})
    scalar = nominal['native_results']['steps'][0]
    legacy = put(root, 'phase3/analog/unit_alpha/corner_results.json', {
        'source_control_fixture': True, 'corners': [{'name': 'typical_27c', '_provenance': 'real_ngspice',
            'value': .6, 'ngspice_log': scalar['executions'][0]['log']}],
        'total_corners': 2, 'corners_executed': 1, 'full_pvt_sweep_executed': False})
    row = {'step': 'A08', 'block': 'unit_alpha', 'status': 'NOT_MEASURED',
           'producer_context': copy.deepcopy(scalar['producer_context']),
           'input_views': native._input_views(root, 'unit_alpha', 'A08'),
           'output_views': {str(legacy): sha(legacy)}, 'outputs': [str(legacy)],
           'executions': [], 'metrics': {}}
    report = {'attempt': str(root / 'reports/analog_native/source-only-pvt-fixture'),
        'image': nominal['native_results']['image'], 'source_sha256': nominal['native_results']['source_sha256'],
        'steps': [row], 'source_control_fixture': True}
    put(root, 'reports/analog_native/source-only-pvt-fixture/result.json', report)
    component = {'step_id': 'A08', 'component_status': 'NOT_MEASURED', 'native_results': report,
                 'a08_invocation': native._a08_invocation(root)}
    context = {'requested_step': 'A08', 'context_sha256': 'c' * 64, 'resolved_row': {'id': 'A08'}}
    component['context_sha256'] = context['context_sha256']
    return root, context, component, requirement


def test_missing_pvt_corner_is_reported_without_empty_population_credit(case):
    root, context, component, _ = partial_pvt_source_fixture(case)
    result = flow109._selected_step_result(root, context, component, native)
    assert result['default_row_status'] == 'NOT_MEASURED' and not result['completed']
    assert result['metric_acceptance']['metrics']['pvt_load_modes']['missing'] == [('unit_alpha', 'slow_125c')]
    assert result['metric_acceptance']['reason'] == 'A08_PER_CORNER_EXECUTABLE_ARGV_AND_PREEXEC_MODEL_READSET_ABSENT'


def test_source_supply_condition_is_not_an_extra_performance_metric(tmp_path, monkeypatch):
    original = authority
    def declared(root, metric, **kwargs):
        path = root / 'phase3/analog/unit_alpha/spec.json'
        doc = json.loads(path.read_text())
        if not any(v['name'] == 'vdd' for v in doc['specs']):
            doc['specs'].append({'name': 'vdd', 'min': .9, 'max': 1.1, 'unit': 'V'})
        path.write_text(json.dumps(doc))
        return original(root, metric, **kwargs)
    monkeypatch.setattr(__name__ + '.authority', declared)
    result = selected(make_case(tmp_path, monkeypatch))
    assert result['metric_acceptance_status'] == 'PASS', result
    assert result['default_row_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('fault', ['path', 'digest', 'argv', 'bytes'])
def test_nominal_native_log_is_reopened_with_exact_output_identity(case, fault):
    root, _, component, *_ = case
    invocation = component['a07_invocation']
    row = component['native_results']['steps'][0]
    execution = copy.deepcopy(row['executions'][0])
    deck = root / 'phase3/analog/unit_alpha/tb_unit_alpha.sp'
    assert metrics._a0708_transcript(root, [execution], deck, invocation)['vout_dc'] == pytest.approx(.6)
    log = execution['stdout_path']
    if fault == 'path':
        execution['stdout_path'] = str(root / 'unrelated.log')
    elif fault == 'digest':
        execution['outputs'][log] = '0' * 64
    elif fault == 'argv':
        execution['argv'][-1] = str(root / 'unrelated.log')
    else:
        Path(log).write_text('MEAS vout_dc=0.6\n')
    with pytest.raises(metrics.MetricRefusal) as caught:
        metrics._a0708_transcript(root, [execution], deck, invocation)
    assert caught.value.code in ('A0708_NATIVE_EXECUTION_INCOMPLETE', 'A0708_NATIVE_INPUT_CHANGED')


def declared_case(root, monkeypatch):
    def declare(project):
        declaration = put(project, 'input/declared-bench.json', {
            'block': 'unit_alpha', 'ports': ['p', 'q'], 'rails': {'vdd': 'vdd', 'vss': 'vss'},
            'testbench': {'supply_exprs': ['1'], 'conditions': ['neutral control'],
                          'stimulus': ['v_drive p 0 {supply}'], 'cards': [],
                          'control': ['op', 'let observed = v(q)', 'echo "MEAS vout_dc=" $&observed']}})
        put(project, 'input/analog_flow.json', {'blocks': {'unit_alpha': {
            'testbench_inputs': str(declaration.relative_to(project))}}})
    return make_case(root, monkeypatch, prepare=declare)


def test_declared_testbench_row_is_read_from_the_deck_it_ran(tmp_path, monkeypatch):
    case = declared_case(tmp_path, monkeypatch)
    component = case[2]
    assert component['component_status'] == 'PASS', component['native_results']
    assert selected(case)['metric_acceptance_status'] == 'PASS', component['metric_acceptance']
    row = component['native_results']['steps'][-1]
    assert row['native_inputs']['testbench']['path'] != str(tmp_path / 'phase3/analog/unit_alpha/tb_unit_alpha.sp')


@pytest.mark.parametrize('fault, reason', [
    ('edited_deck', 'A0708_NATIVE_INPUT_CHANGED'),
    ('edited_declaration', 'A07_INVOCATION_CHANGED_OR_ABSENT')])
def test_declared_testbench_deck_stays_bound_to_its_declaration(tmp_path, monkeypatch, fault, reason):
    root, context, component, *_ = declared_case(tmp_path, monkeypatch)
    if fault == 'edited_deck':
        deck = Path(component['native_results']['steps'][-1]['native_inputs']['testbench']['path'])
        deck.write_text(deck.read_text() + '* edited\n')
    else:
        declaration = root / 'input/declared-bench.json'
        declaration.write_text(declaration.read_text().replace('neutral control', 'other control'))
    measured = metrics.accept_a07(root, context, component)
    assert measured['status'] == 'NOT_MEASURED' and measured['reason'] == reason, measured
