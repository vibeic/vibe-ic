"""Neutral SOFTWARE CONTRACT controls; scalar values confer no ADC qualification."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import analog_declared_pvt as declared
import analog_native_flow as native
import analog_native_sim as sim
import flow109
import flow109_metric_acceptance as metrics
from _analog_producer_fixture import block, make_project
from _hostpaths import require_repo
from test_flow109_a07_a08_bindings import make_case, put, sha


SECTIONS = ['neutral_ss', 'neutral_tt', 'neutral_ff']


def configure(project):
    library = project / 'input/corner-models.lib'
    library.write_text(''.join('.lib ' + s + '\n.param transfer_factor=0.6\n.endl ' + s + '\n' for s in SECTIONS))
    directory = project / 'phase3/analog/unit_alpha'
    (directory / 'unit_alpha.sp').write_text(
        '* neutral source fixture\n.lib "../../../input/corner-models.lib" neutral_tt\n'
        '.subckt unit_alpha p q\ne_transfer q 0 p 0 {transfer_factor}\n.ends unit_alpha\n')
    declaration = put(project, 'input/declared-bench.json', {
        'block': 'unit_alpha', 'ports': ['p', 'q'], 'rails': {'vdd': 'vdd', 'vss': 'vss'},
        'testbench': {'supply_exprs': ['1'], 'conditions': ['neutral control'],
                      'stimulus': ['v_drive p 0 {supply}'], 'cards': [],
                      'control': ['op', 'let observed = v(q)', 'echo "MEAS vout_dc=" $&observed']}})
    put(project, 'input/analog_flow.json', {'blocks': {'unit_alpha': {
        'testbench_inputs': str(declaration.relative_to(project)),
        'pvt': {'kind': 'declared_testbench', 'process_sections': SECTIONS}}}})
    source = project / 'input/pvt-source.txt'
    source.write_text('Neutral source consumer contract. No ADC qualification.\n')
    approval = {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': {
        'path': str(source.relative_to(project)), 'sha256': sha(source)}}
    put(project, 'requirements/base_A7/pvt_load_modes.json', {'schema': metrics.AUTHORITY_SCHEMA,
        'approval': approval, 'required_items': [
            {'block': 'unit_alpha', 'name': declared.corner_label(s, t)} for s in SECTIONS for t in (-40, 27, 125)]})
    put(project, 'requirements/base_A7/prelayout_performance.json', {'schema': metrics.AUTHORITY_SCHEMA,
        'approval': approval, 'limits': {'unit_alpha': {'vout_dc': {'min': .5, 'max': .7}}},
        'units': {'unit_alpha': {'vout_dc': 'V'}}})


@pytest.fixture
def source_case(tmp_path):
    make_project(tmp_path, [block('unit_alpha', 'amplifier', [{'name': 'vout_dc', 'min': 0., 'max': 1., 'unit': 'V'}])])
    (tmp_path / 'phase3/analog/unit_alpha').mkdir()
    (tmp_path / 'input').mkdir(exist_ok=True)
    configure(tmp_path)
    put(tmp_path, 'phase3/analog/unit_alpha/spec.json', {'specs': [{'name': 'vout_dc', 'min': 0., 'max': 1., 'unit': 'V'}]})
    return tmp_path


def source_runner(*, temperature=None, value=.6, missing=False, fault_after=None):
    """Only the producer's subprocess seam is a SOURCE fixture."""
    calls = []
    def run(program, argv, *, cwd, outputs):
        calls.append((program, argv))
        if fault_after is not None and len(calls) > fault_after:
            raise ValueError('source seam later corner exception')
        deck, log = Path(argv[1]), Path(argv[3])
        actual = float(next(line.split()[1] for line in deck.read_text().splitlines() if line.lower().startswith('.temp ')))
        temp = actual if temperature is None else temperature
        log.write_text('Doing analysis at TEMP = ' + str(temp) + '\n' + ('' if missing else 'MEAS vout_dc=' + str(value) + '\n'))
        capture = log.parent / 'executor.log'; capture.write_text('SOURCE subprocess seam\n')
        return {'argv': ['ngspice'] + argv, 'cwd': str(cwd), 'returncode': 0,
                'log': str(capture), 'log_sha256': sha(capture), 'outputs': {str(log): sha(log)},
                'missing_outputs': [], 'native_init': None}
    run.calls = calls
    return run


def produce(root, runner):
    return sim.run_step('A08', root, {'name': 'unit_alpha'}, {'config': native._read(root / 'input/analog_flow.json', {}),
        'previous_results': {'A07': {'unit_alpha': {'status': 'PASS'}}}}, runner)


def test_wrong_actual_native_temperature_cannot_pass(source_case):
    result = produce(source_case, source_runner(temperature=27))
    assert result['status'] == 'NOT_MEASURED', result


def test_neutral_source_nine_corners(source_case):
    runner = source_runner()
    result = produce(source_case, runner)
    assert result['status'] == 'PASS', result
    assert len(runner.calls) == result['metrics']['corners_executed'] == 9
    assert {(c['process'], c['temperature_c']) for c in result['metrics']['corners']} == set(declared.coordinates({'process_sections': SECTIONS}))


@pytest.mark.parametrize('markers, expected', [('', False), ('27', False), ('-40', True),
    ('-40\nDoing analysis at TEMP = -40', True), ('-40\nDoing analysis at TEMP = 27', False), ('nan', False), ('inf', False)])
def test_actual_temperature_markers(markers, expected):
    assert declared.temperature_matches('Doing analysis at TEMP = ' + markers if markers else '', -40) is expected


@pytest.mark.parametrize('fault', ['empty', 'absent', 'nan', 'infinity', 'bool', 'reversed', 'missing_value'])
def test_source_incomplete_or_invalid_limits_cannot_pass(source_case, fault):
    root = source_case
    path = root / 'phase3/analog/unit_alpha/spec.json'
    doc = json.loads(path.read_text())
    if fault == 'empty': doc['specs'] = []
    elif fault == 'absent': doc['specs'][0].pop('min'); doc['specs'][0].pop('max')
    elif fault != 'missing_value':
        doc['specs'][0]['min'] = {'nan': float('nan'), 'infinity': float('inf'), 'bool': True, 'reversed': 2.}[fault]
    path.write_text(json.dumps(doc))
    result = produce(root, source_runner(missing=fault == 'missing_value'))
    assert result['status'] == 'NOT_MEASURED', result


@pytest.mark.parametrize('fault', ['missing_peer', 'later_exception'])
def test_source_measured_breach_survives_partial_population(source_case, fault):
    if fault == 'missing_peer':
        path = source_case / 'phase3/analog/unit_alpha/spec.json'
        doc = json.loads(path.read_text()); doc['specs'].append({'name': 'psrr', 'min': 20., 'unit': 'dB'})
        path.write_text(json.dumps(doc))
    result = produce(source_case, source_runner(value=2., fault_after=1 if fault == 'later_exception' else None))
    assert result['status'] == 'FAIL', result
    assert result['metrics']['corners'][0]['status'] == 'FAIL'
    assert result['metrics']['corners_executed'] == (1 if fault == 'later_exception' else 9)


@pytest.mark.parametrize('metric', ['enob', 'snr', 'sinad', 'sndr'])
def test_scalar_dynamic_echo_does_not_supply_sampled_method(source_case, metric):
    put(source_case, 'phase3/analog/unit_alpha/spec.json', {'specs': [{'name': metric, 'min': 1., 'unit': 'dB'}]})
    runner = source_runner()
    result = produce(source_case, runner)
    assert result['status'] == 'NOT_MEASURED'
    assert 'COMPLETE_SAMPLED_DYNAMIC_METHOD_REQUIRED' in result['detail']
    assert runner.calls == []


@pytest.mark.parametrize('fault', ['section', 'no_card', 'duplicate_card', 'ss_source', 'space_path', 'model_changes'])
def test_source_process_and_model_closure(source_case, fault):
    root = source_case; dut = root / 'phase3/analog/unit_alpha/unit_alpha.sp'
    library = root / 'input/corner-models.lib'
    if fault == 'section': library.write_text(library.read_text().replace('neutral_ff', 'other_ff'))
    elif fault == 'no_card': dut.write_text(dut.read_text().replace('.lib "../../../input/corner-models.lib" neutral_tt', ''))
    elif fault == 'duplicate_card': dut.write_text(dut.read_text() + '.lib "../../../input/corner-models.lib" neutral_tt\n')
    elif fault == 'ss_source': dut.write_text(dut.read_text().replace('neutral_tt', 'neutral_ss'))
    elif fault == 'space_path':
        library.rename(root / 'input/corner models.lib'); dut.write_text(dut.read_text().replace('corner-models.lib', 'corner models.lib'))
    runner = source_runner()
    def run(*args, **kwargs):
        result = runner(*args, **kwargs)
        if fault == 'model_changes': library.write_text(library.read_text() + '* mutation during native execution\n')
        return result
    result = produce(root, run)
    assert result['status'] == ('PASS' if fault == 'space_path' else 'NOT_MEASURED'), result
    if fault in ('section', 'no_card', 'duplicate_card', 'ss_source'): assert runner.calls == []


def test_nominal_precondition_blocks_native(source_case):
    runner = source_runner()
    result = sim.run_step('A08', source_case, {'name': 'unit_alpha'}, {'config': native._read(source_case / 'input/analog_flow.json', {})}, runner)
    assert result['status'] == 'NOT_MEASURED' and not runner.calls


def test_unselected_second_process_card_cannot_claim_full_pvt(source_case):
    library = source_case / 'input/second-models.lib'
    library.write_text('.lib companion_tt\n.param companion_factor=0.1\n.endl companion_tt\n')
    dut = source_case / 'phase3/analog/unit_alpha/unit_alpha.sp'
    dut.write_text(dut.read_text() + '.lib "../../../input/second-models.lib" companion_tt\n')
    runner = source_runner()
    result = produce(source_case, runner)
    assert result['status'] == 'NOT_MEASURED', result
    assert runner.calls == []


def test_unrepresentable_config_limit_is_unmeasured(source_case):
    path = source_case / 'input/analog_flow.json'
    config = json.loads(path.read_text())
    config['blocks']['unit_alpha']['limits'] = {'vout_dc': {'max': 10 ** 1000}}
    path.write_text(json.dumps(config))
    result = produce(source_case, source_runner())
    assert result['status'] == 'NOT_MEASURED', result


@pytest.mark.parametrize('sections', [None, [], {}, 'neutral_tt'])
def test_invalid_process_population_refuses_before_launch(source_case, monkeypatch, sections):
    path = source_case / 'input/analog_flow.json'
    config = json.loads(path.read_text())
    config['blocks']['unit_alpha']['pvt']['process_sections'] = sections
    path.write_text(json.dumps(config))
    image = os.environ['VIBEIC_EDA_IMAGE']
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    native._a08_invocation(source_case)
    runner = source_runner()
    assert produce(source_case, runner)['status'] == 'NOT_MEASURED'
    assert runner.calls == []


def test_malformed_sidecar_keeps_named_metric_refusal(source_case):
    put(source_case, 'phase3/analog/unit_alpha/pvt_inputs.json', [])
    with pytest.raises(metrics.MetricRefusal) as refused:
        metrics._a08_selected(source_case, 'unit_alpha')
    assert refused.value.code == 'A08_PVT_INPUTS_INVALID'


def actual_run(tmp_path, monkeypatch, before_a08=None):
    def prepare(project):
        configure(project)
        if before_a08:
            before_a08(project)
    root, _, nominal, *_ = make_case(tmp_path, monkeypatch, prepare=prepare)
    assert nominal['component_status'] == 'PASS', nominal
    image = os.environ['VIBEIC_EDA_IMAGE']
    monkeypatch.setattr(native, 'execute_window', lambda project, context: native.run_window(project,
        SimpleNamespace(entry_step='A08', exit_step='A08', container='', image=image, transport='LOCAL'), features={'has_analog': True}))
    profile = next(v for v in flow109.load_registry()['reference_profiles'] if v['name'] == 'Analog model-IP')
    context = flow109.execution_context(flow109.resolve_plan(profile['features']), 'A08', 'A08')
    component = native.execute(root, context); component['context_sha256'] = context['context_sha256']
    return root, context, component


@pytest.fixture
def actual_case(tmp_path, monkeypatch):
    return actual_run(tmp_path, monkeypatch)


def accept(case):
    return metrics.accept_a08(*case)


def test_actual_neutral_pvt_reaches_existing_consumer(actual_case, monkeypatch):
    registry = json.loads(require_repo('vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json').read_text())
    assert next(v for v in registry['rows'] if v['position'] == 28)['profiles'][0]['dispatch']['native_step_id'] == 'flow109.A08'
    def forbidden(*args, **kwargs):
        raise AssertionError('consumer must not write or launch')
    monkeypatch.setattr(native.NativeCommands, '__call__', forbidden)
    with monkeypatch.context() as reader:
        reader.setattr(Path, 'write_text', forbidden)
        reader.setattr(Path, 'mkdir', forbidden)
        result = accept(actual_case)
    assert result['status'] == 'PASS', result
    assert len(result['native_observation']['unit_alpha']['corners']) == 9
    # This source test executes the real registry-owned front door; completion
    # still requires the independent tool qualification population.
    selected = flow109._selected_step_result(*actual_case, native)
    assert selected['metric_acceptance_status'] == 'PASS'
    assert selected['completed'] is False
    invocation = actual_case[2]['a08_invocation']
    assert str(Path(declared.__file__).resolve()) in invocation['sources']
    assert invocation['inputs'][str(actual_case[0] / 'input/corner-models.lib')] == sha(actual_case[0] / 'input/corner-models.lib')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'extra', 'coordinate', 'value', 'deck', 'model', 'log', 'argv', 'readset', 'temperature', 'startup', 'stage', 'kind', 'count', 'required'])
def test_actual_consumer_rejects_tampered_population_and_identity(actual_case, fault):
    root, context, component = actual_case
    row = component['native_results']['steps'][-1]
    corners = row['metrics']['corners']
    c = corners[0]
    if fault == 'missing': corners.pop()
    elif fault == 'duplicate': corners.append(copy.deepcopy(c))
    elif fault == 'extra': corners.append({**copy.deepcopy(c), 'name': 'extra_27'})
    elif fault == 'coordinate': c['temperature_c'] = 27
    elif fault == 'value': c['measurements']['vout_dc'] = .61
    elif fault == 'deck':
        p = Path(c['deck']); p.write_text(p.read_text() + '* changed\n'); row['output_views'][str(p)] = sha(p)
    elif fault == 'model':
        p = root / 'input/corner-models.lib'; p.write_text(p.read_text() + '* changed\n')
    elif fault == 'log': Path(c['execution']['stdout_path']).write_text('MEAS vout_dc=0.6\n')
    elif fault == 'argv': c['execution']['argv'][2] = corners[1]['deck']
    elif fault == 'temperature':
        p = Path(c['execution']['stdout_path'])
        p.write_text(p.read_text().replace('TEMP = -40.000000', 'TEMP = 27.000000'))
        c['execution']['outputs'][str(p)] = sha(p); row['output_views'][str(p)] = sha(p)
    elif fault == 'startup': c['execution']['native_init'] = {'path': 'foreign-init', 'sha256': '0' * 64}
    elif fault == 'stage': row['metrics']['stage'] = 'POST'
    elif fault == 'kind': row['metrics']['kind'] = 'other'
    elif fault == 'count': row['metrics']['corners_executed'] = 8
    elif fault == 'required': row['metrics']['required'] = []
    else:
        row['native_inputs'] = {k: v for k, v in row['native_inputs'].items() if 'corner-models.lib' not in v['path']}
    put(root, str(Path(component['native_results']['attempt']).relative_to(root) / 'result.json'), component['native_results'])
    result = accept(actual_case)
    assert result['status'] == 'NOT_MEASURED', result


@pytest.mark.parametrize('gap', ['peer', 'corner', 'performance_authority', 'population_authority'])
def test_actual_trusted_breach_survives_gaps(tmp_path, monkeypatch, gap):
    def prepare(root):
        doc = {'specs': [{'name': 'vout_dc', 'min': .7, 'max': 1., 'unit': 'V'}]}
        if gap == 'peer': doc['specs'].append({'name': 'psrr', 'min': 20., 'unit': 'dB'})
        put(root, 'phase3/analog/unit_alpha/a08-spec.json', doc)
        config_path = root / 'input/analog_flow.json'
        config = json.loads(config_path.read_text())
        config['blocks']['unit_alpha']['steps'] = {'A08': {'spec': 'phase3/analog/unit_alpha/a08-spec.json'}}
        config_path.write_text(json.dumps(config))
        if gap.endswith('_authority'):
            (root / ('requirements/base_A7/prelayout_performance.json' if gap == 'performance_authority'
                     else 'requirements/base_A7/pvt_load_modes.json')).unlink()
    case = actual_run(tmp_path, monkeypatch, prepare)
    root, context, component = case
    row = component['native_results']['steps'][-1]
    # SOURCE metadata mutation proves the consumer derives FAIL from bytes,
    # rather than copying either the producer's or component's status.
    component['component_status'] = 'PASS'; row['status'] = 'PASS'
    if gap == 'corner': row['metrics']['corners'].pop()
    for c in row['metrics']['corners']: c['status'] = 'PASS'
    put(root, str(Path(component['native_results']['attempt']).relative_to(root) / 'result.json'), component['native_results'])
    result = accept(case)
    assert result['status'] == 'FAIL', result
    assert result['native_observation']['unit_alpha']['corners'][0]['status'] == 'FAIL'


def test_a08_only_sidecar_inputs_are_prebound(source_case, monkeypatch):
    root = source_case
    config_path = root / 'input/analog_flow.json'
    config = json.loads(config_path.read_text())
    selected = config['blocks']['unit_alpha']
    alternate = root / 'external-source'
    alternate.mkdir()
    original = root / 'phase3/analog/unit_alpha'
    dut = alternate / 'alternate.sp'
    dut.write_text((original / 'unit_alpha.sp').read_text().replace('../../../input/', '../input/'))
    spec = put(root, 'external-source/spec.json', json.loads((original / 'spec.json').read_text()))
    bench = alternate / 'declared.json'; bench.write_bytes((root / selected['testbench_inputs']).read_bytes())
    put(root, 'phase3/analog/unit_alpha/pvt_inputs.json', {**selected,
        'netlist': str(dut.relative_to(root)), 'spec': str(spec.relative_to(root)),
        'testbench_inputs': str(bench.relative_to(root))})
    config['blocks']['unit_alpha'] = {}; config_path.write_text(json.dumps(config))
    views = native._input_views(root, 'unit_alpha', 'A08')
    assert all(views[str(p)] == sha(p) for p in (dut, spec, bench, root / 'input/corner-models.lib'))
    runner = source_runner()
    result = produce(root, runner)
    assert result['status'] == 'PASS', result
    assert sim._selected_config(root, {'config': config}, {'name': 'unit_alpha'}, 'A08') == metrics._a08_selected(root, 'unit_alpha')


def test_runtime_startup_selection_ignores_canonical_cwd_override(source_case, tmp_path, monkeypatch):
    import analog_pdk_availability as availability
    family = 'process_alpha'
    put(source_case, 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {'pdk_target': family}})
    runtime = tmp_path / 'runtime-pdks'
    init = runtime / family / 'libs.tech/ngspice/.spiceinit'
    init.parent.mkdir(parents=True); init.write_text('* neutral runtime startup\n')
    canonical = source_case / 'phase3/analog/unit_alpha/.spiceinit'
    canonical.write_text('* canonical working directory startup\n')
    monkeypatch.setattr(availability, 'local_pdks_root', lambda *args: str(runtime))
    monkeypatch.setattr(availability, 'resolve_pdk', lambda *args, **kwargs: {
        'available': True, 'source': 'container_installed', 'pdk_root': str(init.parents[2]), 'matched_dir': family})
    assert native._local_ngspice_startup(source_case, canonical.parent, 'SOURCE')[1]['path'] == str(canonical)
    assert native._local_ngspice_startup(source_case, None, 'SOURCE')[1]['path'] == str(init)
    image = os.environ['VIBEIC_EDA_IMAGE']
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    invocation = native._a08_invocation(source_case)
    assert invocation['inputs'][str(init)] == sha(init)
    assert str(canonical) not in invocation['inputs']


@pytest.mark.parametrize('future', ['invalid_json', 'unavailable_inputs'])
def test_future_pvt_sidecar_does_not_change_nominal_readset(source_case, monkeypatch, future):
    root = source_case
    before = native._input_views(root, 'unit_alpha', 'A07')
    path = root / 'phase3/analog/unit_alpha/pvt_inputs.json'
    if future == 'invalid_json': path.write_text('{invalid')
    else: path.write_text(json.dumps({'netlist': 'unavailable/future.sp', 'spec': 'unavailable/spec.json',
                                    'testbench_inputs': 'unavailable/bench.json'}))
    assert native._input_views(root, 'unit_alpha', 'A07') == before
    image = os.environ['VIBEIC_EDA_IMAGE']
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    assert native._a07_invocation(root) is not None
    if future == 'invalid_json':
        assert native._a08_invocation(root) is None
        runner = source_runner()
        assert produce(root, runner)['status'] == 'NOT_MEASURED'
        assert runner.calls == []


@pytest.mark.parametrize('fault', ['none', 'declared_corner', 'declared_block', 'incremental_fail'])
def test_mixed_population_uses_existing_consumer(source_case, monkeypatch, fault):
    """SOURCE composition fixture; only the other block's costly collector is isolated."""
    root = source_case; image = os.environ['VIBEIC_EDA_IMAGE']
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    make_project(root, [block('unit_alpha', 'amplifier'), block('converter_beta', 'data_converter')])
    bdir = root / 'phase3/analog/converter_beta'; bdir.mkdir()
    (bdir / 'converter_beta.sp').write_text('* SOFTWARE composition DUT\n')
    (bdir / 'tb_converter_beta.sp').write_text('* SOFTWARE composition bench\n')
    put(root, 'phase3/analog/converter_beta/spec.json', {'specs': [{'name': 'enob', 'min': 14., 'unit': 'bit'}]})
    config_path = root / 'input/analog_flow.json'
    config = json.loads(config_path.read_text()); config['blocks']['converter_beta'] = {'pvt': {'kind': 'incremental_capture'}}
    config_path.write_text(json.dumps(config))
    population = root / 'requirements/base_A7/pvt_load_modes.json'
    doc = json.loads(population.read_text())
    names = [declared.corner_label(s, t) for s, t in declared.coordinates({'process_sections': SECTIONS})]
    doc['required_items'] += [{'block': 'converter_beta', 'name': label} for label in names]
    population.write_text(json.dumps(doc))
    performance = root / 'requirements/base_A7/prelayout_performance.json'
    doc = json.loads(performance.read_text()); doc['limits']['converter_beta'] = {'enob': {'min': 14.}}
    doc['units']['converter_beta'] = {'enob': 'bit'}; performance.write_text(json.dumps(doc))
    row = produce(root, source_runner())
    row.update(step='A08', block='unit_alpha', input_views=native._input_views(root, 'unit_alpha', 'A08'),
        output_views=native._output_views(row), producer_context={'image': image, 'driver_sha256': sha(native.__file__)})
    row['input_views'].update({v['path']: v['sha256'] for v in row['native_inputs'].values()})
    other = {'step': 'A08', 'block': 'converter_beta', 'status': 'PASS', 'metrics': {}, 'outputs': [], 'output_views': {},
        'input_views': native._input_views(root, 'converter_beta', 'A08'), 'producer_context': row['producer_context']}
    report = {'attempt': str(root / 'reports/analog_native/mixed-software'), 'image': image,
        'source_sha256': sha(native.__file__), 'steps': [row, other]}
    if fault == 'declared_corner': row['metrics']['corners'].pop()
    if fault == 'declared_block': report['steps'].remove(row)
    put(root, 'reports/analog_native/mixed-software/result.json', report)
    component = {'native_results': report, 'component_status': 'PASS', 'a08_invocation': native._a08_invocation(root)}
    original = metrics._a08_incremental_observation
    def observe(project, selected_row, invocation):
        if selected_row['block'] == 'unit_alpha': return original(project, selected_row, invocation)
        return {'status': 'FAIL' if fault == 'incremental_fail' else 'PASS', 'required': ['enob'], 'units': {'enob': 'bit'}, 'gaps': [],
            'corners': [{'name': label, 'status': 'PASS', 'complete': True,
                'observations': {'enob': {'value': 13. if fault == 'incremental_fail' else 14.5, 'unit': 'bit'}}} for label in names]}
    monkeypatch.setattr(metrics, '_a08_incremental_observation', observe)
    result = metrics.accept_a08(root, {}, component)
    assert result['status'] == {'none': 'PASS', 'declared_corner': 'NOT_MEASURED',
                              'declared_block': 'NOT_MEASURED', 'incremental_fail': 'FAIL'}[fault], result
