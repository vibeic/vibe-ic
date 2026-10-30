"""Bounded neutral native controls. No ADC geometry or row qualification.

The installed public two-conductor IHP generator supplies unchanged geometry.
The logical source declares both conductors, with no required-net exclusions.
The separately retained public DEF control remains RED for its absent sub! net.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import flow109
import flow109_density_fill as fill
import flow109_final_extract as extract
from programs.tests._hostpaths import require_repo


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def features():
    return copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                              if p['name'] == 'Analog IC external trim'))


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project / 'manifest.json',
        flow109_plan_only=False, execution_mode='default', entry_step='D69', exit_step='D69')
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project / 'reports/flow109/components/D69.json').read_text())
    except flow109.Flow109Error as exc:
        rc, result = 2, dict(component_status='NOT_MEASURED', native_started=False, reason=exc.code)
    put(project / ('observed-' + str(len(list(project.glob('observed-*')))) + '.json'),
        {'rc': rc, 'component': result})
    return rc, result


@pytest.fixture
def carrier(tmp_path):
    source = os.environ.get('D69_NATIVE_METHOD_DIR')
    pdk = os.environ.get('D69_NATIVE_PDK')
    if not source or not pdk:
        pytest.skip('explicit installed neutral method and declared PDK required')
    source = Path(source)
    project = tmp_path / 'neutral'
    inputs = project / 'input'; inputs.mkdir(parents=True)
    subprocess.run(['python3', '-B', str(source / 'make_ihp_fill_control.py')],
        env={**os.environ, 'MODE': 'floating', 'OUT': str(inputs / 'neutral.gds')}, check=True)
    put(inputs / 'project.json', {'pdk': pdk})
    logical = inputs / 'logical.spice'
    logical.write_text('.subckt control A B\n.ends control\n')
    put(project / 'manifest.json', {'features': features()})
    import _delivery_route
    assert _delivery_route.admit(project, 'ic') is None
    cfg = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                 'programs/metal_fill/fill_config.example.json').read_text())
    cfg.update(window_um=100.0, fill_datatype=22)
    cfg['layers'] = [dict(name='neutral_fill', layer=[10, 0], target=0.1, max=0.95,
                          space=5.0, width=5.0, fill_datatype=22)]
    put(inputs / 'rules.json', cfg)
    invocation = dict(schema=fill.SCHEMA, cell='control',
        input_gds=fill._record(project, inputs / 'neutral.gds'),
        rules=fill._record(project, inputs / 'rules.json'))
    put(project / fill.INPUT, invocation)
    plan = flow109.resolve_plan(features())
    context = flow109.execution_context(plan, 'D62', 'D62')
    produced = fill.execute(project, context)
    assert produced['component_status'] == 'PASS', produced
    launch = inputs / 'fill-launch.json'
    shutil.copyfile(os.environ['VIBEIC_LIBRELANE_LOCAL_ATTESTATION'], launch)
    tech = Path(os.environ['PDK_ROOT']) / pdk / 'libs.tech/magic' / (pdk + '.fill-aware.tech')
    manifest = dict(schema=extract.SCHEMA, top='control',
        final_gds=produced['outputs']['filled.gds'], fill_receipt=produced['receipt'],
        fill_launch=fill._record(project, launch), logical_netlist=fill._record(project, logical),
        rc_model=fill._record(project, tech),
        corners={'min': 'ngspice(hrlc)', 'nom': 'ngspice()', 'max': 'ngspice(hrhc)'},
        require_resistance=False)
    put(project / extract.INPUT, manifest)
    put(project / 'CONTROL_SCOPE.json', dict(scope='NEUTRAL_METHOD_NOT_ADC',
        generator=str(source / 'make_ihp_fill_control.py'),
        generator_sha256=extract._sha(source / 'make_ihp_fill_control.py'),
        logical_census_basis='both physical conductor terminals A B in the public generator',
        required_net_exclusions=[], source_fixture_sha256=extract._sha(inputs / 'neutral.gds')))
    return project


def update(project, change):
    path = project / extract.INPUT
    data = json.loads(path.read_text()); change(data); put(path, data)


def test_only_registered_analog_d69_can_use_final_owner():
    plan = flow109.resolve_plan(features())
    row = flow109.resolve_step(plan, 'D69')
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch is not None, row
    assert dispatch['adapter'] == 'flow109_final_extract'
    assert dispatch['component_scope'] == 'native_analog_final_gds_capacitance_component'
    for kind in ('assembly', 'other'):
        foreign = copy.deepcopy(row); foreign['profile']['id'] = kind
        assert flow109.source_owned_native_dispatch(foreign) is None
    foreign = copy.deepcopy(row); foreign['id'] = 'D68'
    assert flow109.source_owned_native_dispatch(foreign) is None
    context = flow109.execution_context(plan, 'D69', 'D69', runtime_tool_uses=[],
                                       qualification_registry='missing.json')
    assert flow109.source_owned_native_admission(context) is None


def test_ordinary_analog_entry_reaches_named_missing_input_without_native(tmp_path):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, 'ic') is None
    put(tmp_path / 'manifest.json', {'features': features()})
    rc, result = invoke(tmp_path)
    assert result['reason'] == 'D69_REQUIRED_INPUT_ABSENT', result
    assert result['component_status'] == 'NOT_MEASURED' and result['native_started'] is False
    assert rc == 2


def test_native_final_gds_is_reduced_and_reopened_without_rc_or_row_credit(carrier):
    rc, result = invoke(carrier)
    assert result['component_status'] == 'PASS', result
    assert result['native_started'] is True and len(result['executions']) == 6
    assert result['extraction_depth'] == 'C_ONLY'
    assert result['required_nets'] == ['a', 'b']
    assert rc == 2 and result['default_row_status'] == 'NOT_MEASURED'
    assert result['flow109_acceptance'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    current = extract.validate_final_parasitics(carrier, result['receipt'])
    assert current['final_gds'] == result['final_gds']
    assert current['final_geometry'] == current['final_gds'] and 'odb' not in current
    assert set(current['final_spefs']) == {'min', 'nom', 'max'}
    assert current['extraction_depth'] == 'C_ONLY'
    assert current['fill_sensitive_parasitics']['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['gds', 'fill_input', 'launch', 'corner', 'model'])
def test_missing_stale_or_unbound_inputs_refuse_before_native(carrier, damage):
    manifest = json.loads((carrier / extract.INPUT).read_text())
    if damage == 'gds':
        path = carrier / manifest['final_gds']['path']; path.write_bytes(path.read_bytes() + b'changed')
    elif damage == 'fill_input':
        path = carrier / 'input/rules.json'; path.write_text(path.read_text() + '\n')
    elif damage == 'launch':
        (carrier / manifest['fill_launch']['path']).unlink()
    elif damage == 'corner':
        update(carrier, lambda d: d['corners'].update(nom='unsupported_native_style'))
    else:
        update(carrier, lambda d: d['rc_model'].update(sha256='0' * 64))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['native_started'] is False and rc == 2


def test_rebound_gds_cannot_replace_fill_output(carrier):
    manifest = json.loads((carrier / extract.INPUT).read_text())
    other = carrier / 'input/other.gds'
    subprocess.run(['python3', '-B', str(Path(os.environ['D69_NATIVE_METHOD_DIR']) / 'make_ihp_fill_control.py')],
        env={**os.environ, 'MODE': 'omit', 'OUT': str(other)}, check=True)
    assert extract._sha(other) != manifest['final_gds']['sha256']
    update(carrier, lambda d: d.update(final_gds=fill._record(carrier, other)))
    _, result = invoke(carrier)
    assert result['reason'] == 'D69_FINAL_GEOMETRY_MISMATCH', result
    assert result['native_started'] is False


def test_native_fill_sensitive_model_has_an_actual_insensitive_negative(carrier):
    _, measured = invoke(carrier)
    assert measured['component_status'] == 'PASS', measured
    manifest = json.loads((carrier / extract.INPUT).read_text())
    stock = Path(manifest['rc_model']['path']).with_name(os.environ['D69_NATIVE_PDK'] + '.tech')
    update(carrier, lambda d: d.update(rc_model=fill._record(carrier, stock)))
    _, insensitive = invoke(carrier)
    assert insensitive['component_status'] == 'PASS', insensitive
    def coupling(record, corner):
        value = 0.0
        for line in (carrier / record['final_spefs'][corner]['path']).read_text().splitlines():
            fields = line.split()
            if len(fields) == 4 and fields[0].isdigit():
                value += float(fields[3])
        return value
    rows = {}
    for corner in measured['corners']:
        positive, negative = coupling(measured, corner), coupling(insensitive, corner)
        rows[corner] = {'fill_aware_coupling': positive, 'stock_coupling': negative}
        assert positive > 0.0 and negative == 0.0, rows
    put(carrier / 'native-fill-sensitivity.json', dict(scope='NEUTRAL_METHOD_ONLY',
        positive='installed fill-aware model', negative='installed stock model', corners=rows,
        final_geometry_correlation='NOT_MEASURED', whole_row_acceptance='NOT_MEASURED'))
    assert measured['fill_sensitive_parasitics']['status'] == insensitive['fill_sensitive_parasitics']['status'] == 'NOT_MEASURED'


def test_native_C_only_refuses_a_resistance_requirement(carrier):
    update(carrier, lambda d: d.update(require_resistance=True))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    assert result['extraction_depth'] == 'C_ONLY'
    assert result['reason'] == 'D69_RESISTANCE_NOT_MEASURED'
    assert result['native_started'] is True and rc == 1


def test_actual_native_missing_required_net_is_never_filtered(carrier):
    logical = carrier / 'input/logical.spice'
    logical.write_text('.subckt control A B required_missing\n.ends control\n')
    update(carrier, lambda d: d.update(logical_netlist=fill._record(carrier, logical)))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    assert result['reason'] == 'D69_NATIVE_REQUIRED_NET_ABSENT'
    assert 'required_missing' in result['detail'] and result['native_started'] is True
    assert rc == 1


@pytest.mark.parametrize('damage', ['geometry', 'corner', 'model', 'output', 'launch', 'fill_claim'])
def test_consumer_reopens_original_native_bindings(carrier, damage):
    _, result = invoke(carrier)
    assert result['component_status'] == 'PASS', result
    manifest = json.loads((carrier / extract.INPUT).read_text())
    receipt_ref = result['receipt']
    if damage == 'geometry':
        path = carrier / manifest['final_gds']['path']; path.write_bytes(path.read_bytes() + b'changed')
    elif damage == 'corner':
        update(carrier, lambda d: d['corners'].update(nom='ngspice(hrhc)'))
    elif damage == 'model':
        model = Path(manifest['rc_model']['path']).with_name(os.environ['D69_NATIVE_PDK'] + '.tech')
        update(carrier, lambda d: d.update(rc_model=fill._record(carrier, model)))
    elif damage == 'output':
        (carrier / result['final_spefs']['nom']['path']).write_text('changed')
    elif damage == 'launch':
        path = carrier / result['original_launch']['path']; path.write_text('{}')
    else:
        path = carrier / result['receipt']['path']
        record = json.loads(path.read_text()); record['fill_sensitive_parasitics']['status'] = 'PASS'
        put(path, record); receipt_ref = fill._record(carrier, path)
    with pytest.raises((extract.AdmissionRefusal, extract.Refusal)):
        extract.validate_final_parasitics(carrier, receipt_ref)
