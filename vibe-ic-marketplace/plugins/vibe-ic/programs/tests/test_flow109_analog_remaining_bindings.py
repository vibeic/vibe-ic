"""SOURCE_ONLY neutral consumer controls. No native IC, qualification, or row credit."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import analog_native_flow as native
import analog_a2_topology_emit as emitter
import flow109
import flow109_metric_acceptance as metrics
from _analog_producer_fixture import block, make_project
from _stated_eda_image import stated_image
from test_a02_binding_controls import put, sha


def view(root, path):
    return {'path': str(path.relative_to(root)), 'sha256': sha(path)}


def source_authority(root, path, body):
    source = root / 'input/authority-source-control.txt'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('Neutral source-only allocation and calibration control. No native qualification.')
    return put(root, path, {'schema': metrics.AUTHORITY_SCHEMA, 'approval': {
        'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': view(root, source)}, **body})


def run_row(root, step, monkeypatch):
    image = stated_image()
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    monkeypatch.setattr(native, 'execute_window', lambda project, context: native.run_window(project,
        SimpleNamespace(entry_step=step, exit_step=step, container='', image=image, transport='LOCAL'),
        features={'has_analog': True}))
    context = {'requested_step': step, 'context_sha256': 'c' * 64, 'resolved_row': {'id': step}}
    component = native.execute(root, context)
    return context, component


@pytest.mark.parametrize('native_state', ['PASS', 'NOT_MEASURED', 'FAIL'])
def test_selected_testability_cannot_invent_missing_producer_or_bypass(native_state, tmp_path):
    context = {'requested_step': 'A03', 'context_sha256': 'c' * 64, 'resolved_row': {'id': 'A03'}}
    component = {'step_id': 'A03', 'component_status': native_state,
                 'native_results': {'features': {'analog_trim': False}, 'steps': []}}
    result = flow109._selected_step_result(tmp_path, context, component, native)
    assert result['default_row_status'] == ('FAIL' if native_state == 'FAIL' else 'NOT_MEASURED')
    assert not result['completed']
    assert result['reason'] == 'A03_APPLICABLE_NATIVE_TESTABILITY_PRODUCER_ABSENT'


@pytest.fixture
def topology_case(tmp_path, monkeypatch):
    root = tmp_path
    entry = block('keeper_alpha', 'pull', [{'name': 'Reff', 'target': 50000.0, 'unit': 'Ohm'}])
    make_project(root, [entry])
    spec = put(root, 'phase3/analog/keeper_alpha/spec.json', {'block': 'keeper_alpha', 'block_type': 'pull',
        'specs': [{'name': 'Reff', 'target': 50000.0, 'unit': 'Ohm'}]})
    model = root / 'input/pdk/spice/open_models.lib'
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(''.join(f'.lib {corner}\n.model open_core nmos level=1 vto=0.5 kp=100u\n'
        '.subckt open_nmos_dev d g s b w=1u l=1u\nmcore d g s b open_core w={w} l={l}\n'
        f'.ends open_nmos_dev\n.endl {corner}\n' for corner in ['ss', 'tt', 'ff']))
    put(root, 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {'pdk_target': 'sky130'}})
    put(root, 'input/analog_flow.json', {})
    declared = put(root, 'input/flow109/A04-allocations.json', {
        'schema': 'vibeic.flow109.analog-topology.v1', 'approval': {
            'status': 'APPROVED', 'authority': 'analog_design_authority',
            'source_reference': 'synthetic source allocation only'}, 'blocks': [{
                'block': 'keeper_alpha', 'block_type': 'pull', 'spec': view(root, spec),
                'selected_topology': emitter.LIBRARY['pull']['topology'], 'required_device_roles': ['nmos'],
                'topology_constraints': ['one source-declared NMOS role'],
                'budgets': {kind: {'status': 'BOUND', 'limit': 1.0, 'unit': unit}
                            for kind, unit in [('gain', 'V/V'), ('noise', 'mV_rms'), ('power', 'mW')]}}]})
    put(root, 'input/flow109/A04.json', {'requirements': view(root, declared)})
    topology_authority = source_authority(root, 'requirements/base_A3/topology_constraints.json', {
        'required_items': [{'block': 'keeper_alpha', 'kind': 'device_role', 'value': 'nmos'}]})
    budget_authority = source_authority(root, 'requirements/base_A3/allocated_gain_noise_power_budgets.json', {
        'limits': {'keeper_alpha': {kind: {'max': 2.0} for kind in ['gain', 'noise', 'power']}},
        'units': {'keeper_alpha': {'gain': 'V/V', 'noise': 'mV_rms', 'power': 'mW'}}})
    result = emitter.emit_for_block(root, entry, 'sky130')
    assert result['action'] == 'emitted', result
    return root, declared, topology_authority, budget_authority, monkeypatch


def test_native_topology_and_source_allocations_pass_without_row_credit(topology_case):
    root, _, _, _, monkeypatch = topology_case
    context, result = run_row(root, 'A04', monkeypatch)
    assert result['component_status'] == 'PASS', result
    assert result['metric_acceptance_status'] == 'PASS', result
    completed = flow109._selected_step_result(root, context, result, native)
    assert completed['default_row_status'] == 'NOT_MEASURED'
    assert not (root / 'qualifications.json').exists()


@pytest.mark.parametrize('fault', ['budget_violation', 'missing_constraint', 'missing_bounds', 'changed_inputs'])
def test_topology_substantive_negatives(topology_case, fault):
    root, declared, topology_authority, budget_authority, monkeypatch = topology_case
    if fault == 'budget_violation':
        doc = json.loads(declared.read_text())
        doc['blocks'][0]['budgets']['power']['limit'] = 3.0
        declared.write_text(json.dumps(doc))
        put(root, 'input/flow109/A04.json', {'requirements': view(root, declared)})
    elif fault == 'missing_constraint':
        doc = json.loads(topology_authority.read_text())
        doc['required_items'][0]['value'] = 'pmos'
        topology_authority.write_text(json.dumps(doc))
    elif fault == 'missing_bounds':
        budget_authority.unlink()
    context, result = run_row(root, 'A04', monkeypatch)
    if fault == 'changed_inputs':
        declared.write_text('{}')
    measured = metrics.accept_a04(root, context, result)
    assert measured['status'] == ('FAIL' if fault in ['budget_violation', 'missing_constraint'] else 'NOT_MEASURED'), measured


@pytest.fixture
def calibration_case(tmp_path, monkeypatch, request):
    root = tmp_path
    make_project(root, [block('stage', 'opamp', [{'name': 'gain', 'target': 80.0, 'unit': 'dB'}])])
    directory = root / 'phase3/analog/stage'
    directory.mkdir(exist_ok=True)
    net = directory / 'stage.sp'
    net.write_text('* neutral known linear transfer for measurement-method source controls\n'
                   '.subckt stage in out\ne_gain out 0 in 0 10000\n.ends stage\n')
    template = directory / 'tb_stage.sp'
    template.write_text('* neutral source-control stimulus\n.include stage.sp\nv_input in 0 dc 0 ac 1\n'
                        'xdut in out stage\n.end\n')
    put(root, 'phase3/analog/stage/spec.json', {'block': 'stage', 'block_type': 'opamp',
        'specs': [{'name': 'gain', 'min': 0.0, 'max': 100.0, 'unit': 'dB'}]})
    source = root / 'input/source-control.txt'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('Source-only known method test, independently declared ideal transfer 10000 gives 80dB.')
    binary = str(Path(shutil.which('ngspice')).resolve())
    bindings = put(root, 'input/method.json', {'source': {'path': str(source), 'sha256': sha(source)},
        'analysis': {'kind': 'AC', 'temperature_c': 27, 'sweep': 'lin', 'points': 1, 'start_hz': 1000, 'stop_hz': 1000},
        'execution': {'ngspice_bin': binary}, 'measurements': {
            'gain': {'analysis': 'AC', 'expression': 'vdb(out)', 'frequency_hz': 'last', 'unit': 'dB', 'spec_key': 'gain'}}})
    if getattr(request, 'param', None) == 'wrong_unit':
        document = json.loads(bindings.read_text())
        document['measurements']['gain']['unit'] = 'mV'
        bindings.write_text(json.dumps(document))
    known = put(root, 'input/independent-known.json', {'measurements': {'stage': {'gain': 80.0}},
                                                    'units': {'stage': {'gain': 'dB'}}})
    authority = source_authority(root, 'requirements/base_A5/known_stimulus_calibration.json', {
        'reference': view(root, known), 'limits': {'ideal_model_sqnr_error_db': {'max': 1.0}},
        'units': {'ideal_model_sqnr_error_db': 'dB'}})
    destination = root / 'reports/method-control'
    destination.mkdir(parents=True)
    runner = native.NativeCommands(root, destination, '', stated_image())
    result_path = destination / 'result.json'
    result = runner('analog_bound_measurements.py', [str(root), '--netlist', str(net), '--testbench', str(template),
        '--bindings', str(bindings), '--out', str(destination), '--container', '', '--image', stated_image()],
        outputs=[str(result_path)])
    assert result['returncode'] == 0, result
    put(root, 'input/analog_flow.json', {'blocks': {'stage': {'measurement_studies': [{
        'testbench': str(template.relative_to(root)), 'bindings': str(bindings.relative_to(root)),
        'result': str(result_path.relative_to(root))}]}}})
    return root, known, authority, result_path, bindings, monkeypatch


@pytest.mark.parametrize('signed_error,expected', [(0.0, 'PASS'), (.5, 'PASS'), (-.5, 'PASS'), (2.0, 'FAIL'), (-2.0, 'FAIL')])
def test_actual_native_method_calibration_uses_absolute_error(calibration_case, signed_error, expected):
    root, known, authority, _, _, monkeypatch = calibration_case
    doc = json.loads(known.read_text())
    doc['measurements']['stage']['gain'] = 80.0 - signed_error
    known.write_text(json.dumps(doc))
    requirement = json.loads(authority.read_text())
    requirement['reference'] = view(root, known)
    authority.write_text(json.dumps(requirement))
    context, result = run_row(root, 'A06', monkeypatch)
    measured = result['metric_acceptance']
    assert measured['status'] == expected, measured
    comparison = measured['metrics']['known_stimulus_calibration']['comparisons'][0]
    assert comparison['signed_delta_db'] == pytest.approx(signed_error)
    assert comparison['absolute_error_db'] == pytest.approx(abs(signed_error))
    completed = flow109._selected_step_result(root, context, result, native)
    assert completed['default_row_status'] == ('FAIL' if expected == 'FAIL' else 'NOT_MEASURED')
    assert not completed['completed']
    assert not (root / 'qualifications.json').exists()


@pytest.mark.parametrize('fault', ['missing_known', 'missing_authority', 'changed_native_log', 'changed_binding', 'changed_tool'])
def test_calibration_missing_or_tampered_inputs_cannot_pass(calibration_case, fault):
    root, known, authority, result_path, bindings, monkeypatch = calibration_case
    context, result = run_row(root, 'A06', monkeypatch)
    if fault == 'missing_known':
        known.unlink()
    elif fault == 'missing_authority':
        authority.unlink()
    elif fault == 'changed_native_log':
        record = json.loads(result_path.read_text())
        Path(record['executions'][0]['log']).write_text('tampered')
    elif fault == 'changed_binding':
        bindings.write_text('{}')
    else:
        result['a06_invocation']['tools']['ngspice']['sha256'] = '0' * 64
    assert metrics.accept_a06(root, context, result)['status'] == 'NOT_MEASURED'


def test_measured_constraint_failure_survives_missing_budget_authority(topology_case):
    root, _, topology_authority, budget_authority, monkeypatch = topology_case
    document = json.loads(topology_authority.read_text())
    document['required_items'][0]['value'] = 'pmos'
    topology_authority.write_text(json.dumps(document))
    budget_authority.unlink()
    context, component = run_row(root, 'A04', monkeypatch)
    result = flow109._selected_step_result(root, context, component, native)
    assert result['default_row_status'] == 'FAIL', result
    assert result['metric_acceptance']['metrics']['topology_constraints']['missing']
    assert not result['completed']


@pytest.mark.parametrize('calibration_case', ['wrong_unit'], indirect=True)
def test_measured_unit_failure_survives_missing_calibration_authority(calibration_case):
    root, _, authority, _, _, monkeypatch = calibration_case
    authority.unlink()
    context, component = run_row(root, 'A06', monkeypatch)
    result = flow109._selected_step_result(root, context, component, native)
    assert result['default_row_status'] == 'FAIL', result
    assert result['metric_acceptance']['metrics']['unit_mismatches']['value'] == 1
    assert not result['completed']


def test_trim_false_cannot_skip_measurement_bench_calibration(calibration_case):
    root, _, authority, _, _, monkeypatch = calibration_case
    config = root / 'input/analog_flow.json'
    document = json.loads(config.read_text())
    document['features'] = {'analog_trim': False, 'analog_testability': False}
    config.write_text(json.dumps(document))
    authority.unlink()
    context, component = run_row(root, 'A06', monkeypatch)
    result = flow109._selected_step_result(root, context, component, native)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['metric_acceptance_status'] == 'NOT_MEASURED'
    assert not result['completed']
