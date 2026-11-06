"""Real bounded D67 ngspice/normal-consumer controls; no IC/PDK qualification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import flow109_package_electrical as d67
from programs.tests._hostpaths import require_repo


def _put(project, path, value):
    target = project / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return d67._record(project, target)


def _case(project, *, make_context=True):
    project.mkdir(parents=True, exist_ok=True)
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'flow109_d67')
    owner = d67._record(project, fixture / 'authority.md')
    model = d67._record(project, fixture / 'package.sp')
    # Read an existing neutral interface; do not create or edit RTL/DEF/GDS.
    netlist = d67._record(project, require_repo('vibe-ic-marketplace', 'plugins',
        'vibe-ic', 'programs', 'tests', 'fixtures', 'flow109_final_lec', 'rtl.v'))
    approval = {'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
                'source_reference': owner}
    case = {'id': 'nominal_step', 'corner': 'nominal', 'mission_mode': 'step',
            'model': model, 'subckt': 'neutral_package',
            'port_map': {'drive': {'model_port': 'die', 'design_port': 'y'},
                         'observe': {'model_port': 'board', 'external_port': 'board_y'},
                         'return': {'model_port': 'ref', 'design_port': 'a'}},
            'mission': {'waveform': 'ideal_voltage_ramp_hold',
                        'initial_voltage_v': 0.0, 'voltage_v': 1.0, 'temperature_c': 25.0,
                        'rise_s': 1e-9, 'step_s': 1e-10,
                        'stop_s': 1e-7, 'sample_s': 9e-8},
            'limits': {'Rseries': {'min': 9.0, 'max': 11.0},
                       'Lseries': {'min': 0.9e-9, 'max': 1.1e-9},
                       'Cload': {'min': 1.9e-12, 'max': 2.1e-12},
                       'voltage_at_sample': {'min': 0.99, 'max': 1.01},
                       'maximum_voltage': {'max': 1.1},
                       'source_current_at_sample': {'min': -1e-8, 'max': 1e-8}},
            'units': {'Rseries': 'ohm', 'Lseries': 'H', 'Cload': 'F',
                      'voltage_at_sample': 'V', 'maximum_voltage': 'V',
                      'source_current_at_sample': 'A'}}
    requirements = {'approval': approval, 'top': 'proof_alpha', 'netlist': netlist,
                    'scope': {'basis': 'provided_lumped_rlc', 'thermal_required': False,
                              'full_wave_required': False, 'other_signal_requirements': []},
                    'cases': [case]}
    reference = {'approval': approval,
        'reference': {'top': requirements['top'], 'netlist': netlist,
            'models': [{key: case[key] for key in
                        ('id', 'corner', 'mission_mode', 'subckt', 'model', 'port_map')}]},
        'reference_identity': {key: {'source': owner} for key in
            ('producer', 'checker', 'tool_execution', 'consumed_inputs',
             'requirements', 'configuration')}}
    reference['reference']['models'][0]['ports'] = ['die', 'board', 'ref']
    _bind(project, requirements, reference)
    return {}, requirements, reference


def _bind(project, requirements, reference):
    bounds = _put(project, d67.BOUNDS, requirements)
    adopted = _put(project, d67.PORTS, reference)


def _native(project, context):
    report = d67.execute(project, context)
    # Receipts stay on disk for the sealed carrier packet.
    _put(project, 'observed-result.json', report)
    return report












@pytest.mark.parametrize('requirement', ['thermal', 'full_wave', 'eye', 'unknown_model'])
def test_required_unsupported_scope_stays_required(tmp_path, requirement):
    project = tmp_path / 'case'
    context, req, ref = _case(project)
    if requirement == 'thermal': req['scope']['thermal_required'] = True
    elif requirement == 'full_wave': req['scope']['full_wave_required'] = True
    elif requirement == 'eye': req['scope']['other_signal_requirements'] = ['eye_mask']
    else: req['scope']['basis'] = 'ibis_without_qualified_derivation'
    _bind(project, req, ref)
    report = _native(project, context)
    assert report['component_status'] == 'NOT_MEASURED'
    assert report['reason'] == 'D67_REQUIRED_SCOPE_UNSUPPORTED'
    assert report['native_started'] is False


def test_actual_model_port_order_must_match_adopted_reference(tmp_path):
    project = tmp_path / 'case'
    context, req, ref = _case(project)
    original = Path(req['cases'][0]['model']['path']).read_text()
    changed = _put(project, 'input/reordered.sp', original.replace(
        'neutral_package die board ref', 'neutral_package board die ref'))
    req['cases'][0]['model'] = changed
    ref['reference']['models'][0]['model'] = changed
    _bind(project, req, ref)
    report = _native(project, context)
    assert report['component_status'] == 'FAIL'
    assert report['reason'] == 'D67_PORT_IDENTITY_MISMATCH'
    assert report['native_started'] is False




def test_native_bounds_failure_and_actual_source_restoration(tmp_path):
    project = tmp_path / 'case'
    context, req, ref = _case(project)
    source = Path(req['cases'][0]['model']['path']).read_text()
    local = _put(project, 'input/model.sp', source)
    req['cases'][0]['model'] = local
    ref['reference']['models'][0]['model'] = local
    _bind(project, req, ref)
    positive = _native(project, context)
    assert positive['component_status'] == 'PASS', positive
    altered = _put(project, 'input/model.sp', source.replace('Rseries die neck 10', 'Rseries die neck 100'))
    req['cases'][0]['model'] = altered
    ref['reference']['models'][0]['model'] = altered
    _bind(project, req, ref)
    negative = _native(project, context)
    assert negative['native_started'] is True and negative['native'][0]['returncode'] == 0
    assert negative['component_status'] == 'FAIL'
    failed = negative['metrics']['package_rc_thermal_validity']['checks']
    assert any(c['metric'] == 'Rseries' and c['value'] == 100 and c['status'] == 'FAIL' for c in failed)
    restored = _put(project, 'input/model.sp', source)
    req['cases'][0]['model'] = restored
    ref['reference']['models'][0]['model'] = restored
    _bind(project, req, ref)
    assert _native(project, context)['component_status'] == 'PASS'




@pytest.mark.parametrize('kind', ['C_only', 'include', 'nonfinite'])
def test_unprovided_package_rl_or_model_scope_never_defaults_zero(tmp_path, kind):
    project = tmp_path / 'case'
    context, req, ref = _case(project)
    source = Path(req['cases'][0]['model']['path']).read_text()
    if kind == 'C_only':
        source = source.replace('Rseries die neck 10\nLseries neck board 1n\n', 'Cinterface die board 2p\n')
    elif kind == 'include': source = source.replace('Rseries die neck 10', '.include absent.sp')
    else: source = source.replace('Rseries die neck 10', 'Rseries die neck NaN')
    model = _put(project, 'input/unsupported.sp', source)
    req['cases'][0]['model'] = model
    ref['reference']['models'][0]['model'] = model
    _bind(project, req, ref)
    report = _native(project, context)
    assert report['component_status'] == 'NOT_MEASURED'
    assert report['native_started'] is False


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 'unknown'])
def test_invalid_declared_bounds_refuse_before_native(tmp_path, value):
    project = tmp_path / 'case'
    context, req, ref = _case(project)
    req['cases'][0]['limits']['voltage_at_sample']['max'] = value
    _bind(project, req, ref)
    report = _native(project, context)
    assert report['component_status'] == 'NOT_MEASURED'
    assert report['reason'] == 'D67_INVALID_NUMBER'
    assert report['native_started'] is False




@pytest.mark.parametrize('card', [
    'not Rseries die neck 10', 'Rseries die neck 10 not measured',
    'Rseries die neck no10', 'Rseries die neck 10unknown',
    'Rseries die neck 1_0', "Rseries die neck '10'",
    '.include absent.sp', '.param resistance=10',
])
def test_structured_model_reader_refuses_prose_and_undeclared_cards(tmp_path, card):
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                          'tests', 'fixtures', 'flow109_d67', 'package.sp').read_text()
    model = tmp_path / 'provided.sp'
    model.write_text(source.replace('Rseries die neck 10', card))
    with pytest.raises(d67.PackageError, match='D67_MODEL_'):
        d67._model(model, {'subckt': 'neutral_package'})


def test_formal_spice_net_named_not_still_runs_and_obeys_bounds(tmp_path):
    project = tmp_path / 'case'
    context, req, ref = _case(project)
    source = Path(req['cases'][0]['model']['path']).read_text()
    model = _put(project, 'input/formal_not.sp', source.replace('neck', 'not'))
    req['cases'][0]['model'] = model
    ref['reference']['models'][0]['model'] = model
    _bind(project, req, ref)
    report = _native(project, context)
    assert report['component_status'] == 'PASS', report
    assert report['native'][0]['returncode'] == 0
    checks = report['metrics']['package_rc_thermal_validity']['checks']
    assert any(c['metric'] == 'Rseries' and c['value'] == 10.0 and c['status'] == 'PASS' for c in checks)
