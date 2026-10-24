"""Existing typed geometry inputs can co-scale selected output stages only."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3


def circuit():
    return {'block': 'amplifier_bank', 'block_type': 'ota', 'topology': 'two output stages',
        'ports': ['vdd', 'vss', 'input_a', 'input_b', 'output_a', 'output_b'],
        'devices': [
            {'name': 'driver_a', 'role': 'pmos', 'nets': ['output_a', 'input_a', 'vdd', 'vdd'], 'w': 12., 'l': .5},
            {'name': 'load_a', 'role': 'nmos', 'nets': ['output_a', 'bias', 'vss', 'vss'], 'w': 6., 'l': 1.},
            {'name': 'driver_b', 'role': 'pmos', 'nets': ['output_b', 'input_b', 'vdd', 'vdd'], 'w': 12., 'l': .5},
            {'name': 'load_b', 'role': 'nmos', 'nets': ['output_b', 'bias', 'vss', 'vss'], 'w': 6., 'l': 1.},
            {'name': 'bias_device', 'role': 'nmos', 'nets': ['bias', 'bias', 'vss', 'vss'], 'w': 3., 'l': 1.}],
        'knobs': {}, 'knob_sources': {}, 'constants': {}, 'device_param_exprs': []}


PDK = {'model_lib': '/pdk/models.lib', 'typ_section': 'nominal',
       'role_models': {'nmos': 'n_device', 'pmos': 'p_device'},
       'geometry_units': {'nmos': 'metric', 'pmos': 'metric'}}


def rendered(ir):
    return a3.render_netlist(ir, PDK, [], a3._resolve_params(ir, {})[0])


def apply(ir, sizing, exprs=None, minima=None, maxima=None):
    a2.apply_sizing_inputs(sizing, ir['knobs'], ir['knob_sources'], [], ir['devices'],
                           exprs or [], minima or {}, maxima or {})


def test_explicit_wl_coscale_reaches_the_existing_renderer_for_exactly_selected_instances(tmp_path):
    original = circuit()
    sized = copy.deepcopy(original)
    selected = {d['name'] for d in original['devices'] if d['name'] != 'bias_device'}
    path = tmp_path / 'phase3/analog/amplifier_bank/sizing_inputs.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'device_parameters': {
        d['name']: {'w': 2*d['w'], 'l': 2*d['l']} for d in original['devices'] if d['name'] in selected}}))
    sizing = a2.read_sizing_inputs(tmp_path, 'amplifier_bank')
    assert sizing['input_view']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    apply(sized, sizing)
    changed = {a['name'] for a,b in zip(original['devices'], sized['devices']) if a != b}
    assert changed == selected
    for before, after in zip(original['devices'], sized['devices']):
        assert before['nets'] == after['nets']
        assert after['w']/after['l'] == before['w']/before['l']
    before_lines, after_lines = rendered(original).splitlines(), rendered(sized).splitlines()
    assert {a.split()[0][1:] for a,b in zip(before_lines, after_lines) if a != b} == selected
    assert original == circuit()  # Source/default data was not mutated.


def test_absent_explicit_sizing_preserves_the_default_rendering():
    ir = circuit()
    original = rendered(ir)
    apply(ir, {})
    assert rendered(ir) == original


@pytest.mark.parametrize('parameter', ['w', 'l'])
def test_coscale_cannot_override_expression_owned_geometry(parameter):
    ir = circuit()
    with pytest.raises(a2.SizingInputsInvalid, match='expression-owned'):
        apply(ir, {'device_parameters': {'driver_a': {parameter: 2}}},
              [{'device': 'driver_a', 'param': parameter, 'expr': 'declared_knob'}])


def test_explicit_geometry_still_obeys_actual_pdk_bounds():
    with pytest.raises(a2.SizingInputsInvalid, match='exceeds PDK maximum'):
        apply(circuit(), {'device_parameters': {'driver_a': {'l': 3}}}, maxima={'pmos': {'max_length_um': 2}})
