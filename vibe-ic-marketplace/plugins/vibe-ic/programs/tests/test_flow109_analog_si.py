"""D48 native neutral RC method controls. These do not qualify physical SI."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

import analog_bound_measurements as measured
import flow109
import si_crosstalk_check as si


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def ref(path, project):
    return {'path': str(path.relative_to(project)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def carrier(tmp_path):
    if not shutil.which('ngspice'):
        if os.environ.get('D48_NATIVE_REQUIRED'):
            pytest.fail('required native ngspice unavailable')
        pytest.skip('native method requires ngspice')
    project = tmp_path / 'project'
    model = put(project / 'input/circuit/coupling.sp', 'Cc aggressor victim 1p\n')
    netlist = put(project / 'input/circuit/unit.sp',
                  '* neutral coupled RC method, no extracted geometry\n'
                  'Rv victim 0 1k\nCg victim 0 1p\n.include "coupling.sp"\n')
    bench = put(project / 'input/circuit/tb.sp',
                '* neutral driven aggressor, quiet victim\n.include "unit.sp"\n'
                'Va aggressor 0 PWL(0 0 1n 0 2n 1 5n 1)\n.end\n')
    registry = flow109.load_registry()
    features = {**next(p['features'] for p in registry['reference_profiles']
                       if p['name'] == 'Analog IC external trim'), 'requires_si': True}
    put(project / 'manifest.json', json.dumps({'features': features}))
    put(project / 'input/step_0_5ic_answers.json', json.dumps({
        'answers': {'deliverable': 'DIE'}, 'answer_provenance': {'deliverable': {
            'answered_by': 'owner', 'citation': 'Developer neutral IC method control'}}}))
    data = {'netlist': ref(netlist, project), 'testbench': ref(bench, project),
            'coupling_model': ref(model, project),
            'analysis': {'kind': 'TRAN', 'step_s': 1e-11, 'start_s': 0,
                         'stop_s': 5e-9, 'temperature_c': 25},
            'windows': [{'id': 'declared_transition', 'aggressor': 'v(aggressor)',
                         'victim': 'v(victim)', 'baseline_v': 0,
                         'from_s': 0, 'to_s': 4e-9,
                         'max_noise_v': 0.45, 'min_aggressor_swing_v': 0.9}]}
    put(project / 'input/flow109/D48.json', json.dumps(data))
    return project


def change(project, edit):
    path = project / 'input/flow109/D48.json'
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project / 'manifest.json',
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D48', exit_step='D48')
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project / 'reports/flow109/components/D48.json').read_text())
    except flow109.Flow109Error as exc:
        rc, result = 2, {'component_status': 'NOT_MEASURED', 'reason': str(exc),
                         'native_started': False}
    put(project.parent / 'observed.json', json.dumps({'rc': rc, 'component': result}, indent=2))
    return rc, result


def test_native_coupled_rc_matches_independent_response_without_row_pass(carrier):
    rc, result = invoke(carrier)
    assert result['component_status'] == 'PASS', result
    observed = result['windows'][0]
    # KCL gives (Cg+Cc)dv/dt + v/R = Cc*dVa/dt during the linear ramp.
    expected_peak = 1000 * 1e-12 / 1e-9 * (1 - math.exp(-1e-9 / (1000 * 2e-12)))
    assert observed['peak_noise_v'] == pytest.approx(expected_peak, rel=5e-4)
    assert observed['aggressor_swing_v'] == pytest.approx(1, rel=1e-5)
    assert result['native']['executions'][0]['returncode'] == 0
    assert result['native_started'] is True and rc == 2
    assert result['completed'] is False and result['qualification'] == 'NOT_CLAIMED'
    assert result['default_row_status'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['required_population_status'] == result['timing_window_status'] == 'NOT_MEASURED'
    assert result['timing_window_signoff'] is False
    assert si.declares_si_signoff('', result) is False
    for item in result['outputs']:
        assert hashlib.sha256((carrier / item['path']).read_bytes()).hexdigest() == item['sha256']


def test_actual_excessive_coupling_noise_blocks_ordinary_dispatch(carrier):
    model = carrier / 'input/circuit/coupling.sp'
    model.write_text('Cc aggressor victim 9p\n')
    change(carrier, lambda d: d.update(coupling_model=ref(model, carrier)))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    expected = 9 * (1 - math.exp(-0.1))
    assert result['windows'][0]['peak_noise_v'] == pytest.approx(expected, rel=5e-4)
    assert result['native']['executions'][0]['returncode'] == 0
    assert result['reason'] == 'D48_NOISE_LIMIT_EXCEEDED'
    assert rc == 1 and result['default_row_status'] == 'FAIL'


@pytest.mark.parametrize('kind', ['missing', 'changed', 'unused'])
def test_coupling_model_must_be_current_and_executed(carrier, kind):
    model = carrier / 'input/circuit/coupling.sp'
    if kind == 'missing':
        model.unlink()
    elif kind == 'changed':
        model.write_text('Cc aggressor victim 9p\n')
    else:
        unused = put(carrier / 'input/circuit/unused.sp', 'Cc a b 1p\n')
        change(carrier, lambda d: d.update(coupling_model=ref(unused, carrier)))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'].startswith('D48_') and result['native_started'] is False
    assert rc == 2


@pytest.mark.parametrize('key', ['max_noise_v', 'min_aggressor_swing_v', 'from_s', 'to_s', 'baseline_v'])
def test_missing_limits_or_window_refuses_before_native(carrier, key):
    change(carrier, lambda d: d['windows'][0].pop(key))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'].startswith('D48_') and result['native_started'] is False
    assert rc == 2


def test_quiet_aggressor_does_not_establish_coupling_method(carrier):
    bench = carrier / 'input/circuit/tb.sp'
    bench.write_text('* no switching\n.include "unit.sp"\nVa aggressor 0 0\n.end\n')
    change(carrier, lambda d: d.update(testbench=ref(bench, carrier)))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D48_AGGRESSOR_NOT_EXERCISED'
    assert result['native']['executions'][0]['returncode'] == 0 and rc == 2


@pytest.mark.parametrize('kind', ['truncated', 'unexecuted', 'changed_model', 'missing_closure'])
def test_software_only_corrupt_producer_edge_cannot_supply_native_credit(carrier, monkeypatch, kind):
    original = measured.run_measurements

    def corrupt(*args, **kwargs):
        if kind == 'truncated':
            bindings = copy.deepcopy(args[3])
            bindings['analysis']['stop_s'] = 4.5e-9
            args = (*args[:3], bindings, *args[4:])
        native = original(*args, **kwargs)
        assert native['status'] == 'PASS', native
        if kind == 'unexecuted':
            native['executions'] = []
        elif kind == 'changed_model':
            model = carrier / 'input/circuit/coupling.sp'
            shutil.copyfile(model, model.with_suffix('.executed.sp'))
            model.write_text('Cc aggressor victim 9p\n')
        elif kind == 'missing_closure':
            native['native_inputs'] = {k: v for k, v in native['native_inputs'].items()
                                       if not k.startswith('include:')}
        return native

    monkeypatch.setattr(measured, 'run_measurements', corrupt)
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'].startswith('D48_') and rc == 2
    assert result['native_started'] is True
    if kind == 'truncated':
        assert 'D48_NATIVE_CAPTURE_INTERVAL_INCOMPLETE' in result['reason']


def test_registered_owner_is_specific_and_preserves_digital_route():
    registry = flow109.load_registry()
    analog = {**next(p['features'] for p in registry['reference_profiles']
                     if p['name'] == 'Analog IC external trim'), 'requires_si': True}
    row = flow109.resolve_step(flow109.resolve_plan(analog), 'D48')
    assert flow109.source_owned_native_dispatch(row)['adapter'] == 'si_crosstalk_check'
    for field, value in [('id', 'D57'), ('profile', {**row['profile'], 'id': 'assembly'})]:
        foreign = copy.deepcopy(row)
        foreign[field] = value
        assert flow109.source_owned_native_dispatch(foreign) is None
    claimed = flow109.execution_context(flow109.resolve_plan(analog), 'D48', 'D48',
        runtime_tool_uses=[], qualification_registry='missing.json')
    assert flow109.source_owned_native_admission(claimed) is None
    digital = {**next(p['features'] for p in registry['reference_profiles']
                      if p['name'] == 'Small digital IC without DFT'), 'requires_si': True}
    default = flow109.source_owned_native_dispatch(
        flow109.resolve_step(flow109.resolve_plan(digital), 'D48'))
    assert default['kind'] == 'canonical_backend_window'
    assert si.declares_si_signoff('capacitive advisory screen') is False
    assert si.declares_si_signoff('timing-window SI analysis') is True
