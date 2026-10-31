"""Legacy qualified A04 source-authority and retained-reader controls.

Canonical native dispatch is covered separately by test_analog_native_flow.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

import analog_a2_topology_emit as a2
import flow109
import flow109_admission as admission
import flow109_analog_a04 as analog
from _analog_producer_fixture import block, make_project
from _flow109_legacy_component_fixture import legacy_component_registry, run_legacy_component


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _case(project):
    make_project(project, [block('keeper_alpha', 'pull', [
        {'name': 'Reff', 'target': 50000.0, 'unit': 'Ohm'}])])
    spec = _put(project, 'phase3/analog/keeper_alpha/spec.json', {
        'block': 'keeper_alpha', 'block_type': 'pull',
        'specs': [{'name': 'Reff', 'target': 50000.0, 'unit': 'Ohm'}]})
    model_text = '* neutral open-device model\n'
    for corner in ('ss', 'tt', 'ff'):
        model_text += (f'.lib {corner}\n'
                       '.model open_core nmos level=1 vto=0.5 kp=100u\n'
                       '.subckt open_nmos_dev d g s b w=1u l=1u\n'
                       'mcore d g s b open_core w={w} l={l}\n'
                       '.ends open_nmos_dev\n'
                       f'.endl {corner}\n')
    model = _put(project, 'input/pdk/spice/open_models.lib', model_text)
    _put(project, 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
         {'fields': {'pdk_target': 'sky130'}})
    pdk = _put(project, 'input/flow109/A04-pdk.json', {
        'schema': analog.SCHEMA, 'family': 'sky130',
        'typed_models': [{'device': 'open_nmos_dev', 'corner': 'tt', 'model': model}]})
    topology = a2.LIBRARY['pull']['topology']
    requirements = _put(project, 'input/flow109/A04-requirements.json', {
        'schema': analog.SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'analog_design_authority',
                     'source_reference': 'neutral open-device control'},
        'blocks': [{'block': 'keeper_alpha', 'block_type': 'pull', 'spec': spec,
                    'selected_topology': topology, 'required_device_roles': ['nmos'],
                    'topology_constraints': ['single NMOS pull device; body at vss'],
                    'budgets': {
                        'gain': {'status': 'BOUND', 'limit': 1.0, 'unit': 'V/V'},
                        'noise': {'status': 'BOUND', 'limit': 1.0, 'unit': 'mV_rms'},
                        'power': {'status': 'BOUND', 'limit': 1.0, 'unit': 'mW'}}}]})
    a02_input = _put(project, 'input/flow109/A02-control.json', {'scope': 'neutral open model'})
    a02 = _put(project, 'reports/flow109/components/A02.json', {
        'schema': 'vibeic.flow109.analog-model-qualification.v1', 'step_id': 'A02',
        'component_status': 'PASS', 'flow109_acceptance': 'NOT_MEASURED',
        'inputs': {str((project / a02_input['path']).resolve()): a02_input['sha256'],
                   str((project / model['path']).resolve()): model['sha256']},
        'smokes': [{'device': 'open_nmos_dev', 'corner': 'tt', 'model': model}],
        'consumer': {'verdict': 'PASS'}})
    config = _put(project, analog.INPUT, {
        'schema': analog.SCHEMA, 'basis': 'source_bound_expert_topology',
        'pdk': pdk, 'requirements': requirements, 'a02_receipt': a02})
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Analog model-IP')
    use = flow109.resolve_step(flow109.resolve_plan(features), 'A04')['tool_uses'][0]
    binary = Path(shutil.which('python3')).resolve()
    exe = {'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    identity = {'use_id': use['use_id'], 'tool_id': 'python3', 'version': sys.version,
                'build_sha256': exe['sha256'], 'executable': exe,
                'config': config, 'pdk': pdk, 'deck': requirements, 'corner': ['tt'],
                'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                              'operation_sources': analog.operation_sources()}}
    evidence = _put(project, 'input/flow109/A04-reference.json',
                    {'scope': 'developer component control; not design signoff'})
    record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
              'reference_evidence': [evidence]}
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [record]}
    manifest = {'features': features, 'qualification_registry': 'qualifications.json',
                'runtime_tool_uses': [{**identity,
                    'qualification_sha256': admission.canonical_sha(record)}]}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    (project / 'manifest.json').write_text(json.dumps(manifest))
    return requirements, a02, registry, manifest


def _run(project):
    return run_legacy_component(project, 'A04')


def test_a04_emits_exact_expert_selected_topology_and_keeps_acceptance_unmeasured(tmp_path):
    _case(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A04.json').read_text())
    assert report['component_status'] == 'PASS'
    assert report['flow109_acceptance'] == 'NOT_MEASURED'
    assert report['blocks'][0]['producer']['records'][0]['action'] == 'emitted'
    assert report['blocks'][0]['consumer']['verdict'] == 'PASS'
    assert set(report['gate_layers'].values()) == {'NOT_MEASURED'}
    assert (tmp_path / analog.FREEZE).is_file()


@pytest.mark.parametrize('damage', ['topology', 'budget', 'a02', 'source'])
def test_a04_refuses_wrong_authority_or_stale_upstream_before_false_pass(tmp_path, damage):
    requirements, a02, registry, manifest = _case(tmp_path)
    if damage in ('topology', 'budget'):
        path = tmp_path / requirements['path']
        body = json.loads(path.read_text())
        if damage == 'topology':
            body['blocks'][0]['selected_topology'] = 'invented nearest topology'
        else:
            body['blocks'][0]['budgets']['power']['limit'] = 0
        path.write_text(json.dumps(body))
        requirements['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        registry['uses'][0]['identity']['deck'] = requirements
    elif damage == 'a02':
        (tmp_path / a02['path']).write_text('{}')
    else:
        registry['uses'][0]['identity']['semantics']['operation_sources'] = {}
    record = registry['uses'][0]
    manifest['runtime_tool_uses'][0] = {**record['identity'],
        'qualification_sha256': admission.canonical_sha(record)}
    (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (tmp_path / analog.FREEZE).exists()


def _numeric_spec_input(project, specs):
    """Parser-only authority fixture; never an IC approval or qualification."""
    spec = _put(project, 'phase3/analog/neutral_alpha/spec.json', {
        'block': 'neutral_alpha', 'block_type': 'pull', 'specs': specs})
    requirements = _put(project, 'input/flow109/numeric-spec-requirements.json', {
        'schema': analog.SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'analog_design_authority',
                     'source_reference': 'neutral parser control; not IC authority'},
        'blocks': [{'block': 'neutral_alpha', 'block_type': 'pull', 'spec': spec,
                    'selected_topology': a2.LIBRARY['pull']['topology'],
                    'required_device_roles': ['nmos'],
                    'topology_constraints': ['neutral parser control only'],
                    'budgets': {
                        'gain': {'status': 'BOUND', 'limit': 1.0, 'unit': 'V/V'},
                        'noise': {'status': 'BOUND', 'limit': 1.0, 'unit': 'mV_rms'},
                        'power': {'status': 'BOUND', 'limit': 1.0, 'unit': 'mW'}}}]})
    return {'requirements': requirements}


def _numeric_spec_observed(project, manifest):
    try:
        analog._approved_requirements(project, manifest)
    except admission.AdmissionRefusal as exc:
        return exc.code
    return 'ACCEPTED'


@pytest.mark.parametrize('field', ['target', 'min', 'max', 'typ', 'value'])
def test_a04_numeric_spec_accepts_normal_a1_bound_without_rewriting(tmp_path, field):
    import analog_a1_spec_emit as spec_producer
    import analog_a1_spec_extract_check as spec_reader
    row = spec_producer._spec_entry('gain', {
        'bound': field, 'value': 2.0, 'unit': 'V/V', 'raw': {'name': 'gain'}}, {})
    manifest = _numeric_spec_input(tmp_path, [row])
    path = tmp_path / 'phase3/analog/neutral_alpha/spec.json'
    before = path.read_bytes()
    assert spec_reader._check_block(tmp_path, 'neutral_alpha')[0] == 'PASS'
    observed = _numeric_spec_observed(tmp_path, manifest)
    assert observed == 'ACCEPTED'
    assert path.read_bytes() == before
    assert (field == 'target') == ('target' in row)


def test_a04_numeric_spec_preserves_range_and_units(tmp_path):
    row = {'name': 'reference', 'min': 0.8, 'max': 1.2, 'unit': 'V'}
    manifest = _numeric_spec_input(tmp_path, [row])
    path = tmp_path / 'phase3/analog/neutral_alpha/spec.json'
    before = path.read_bytes()
    observed = _numeric_spec_observed(tmp_path, manifest)
    assert observed == 'ACCEPTED'
    assert path.read_bytes() == before
    assert json.loads(before)['specs'] == [row]
    assert 'target' not in row


def test_a04_numeric_spec_consumes_retained_in_repo_spec_shape(tmp_path):
    from _hostpaths import require_repo
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                        'tests', 'fixtures', 'a8_native_rc_wrapper', 'spec.json')
    specs = json.loads(path.read_text())['specs']
    assert any('target' not in row and ('min' in row or 'max' in row) for row in specs)
    manifest = _numeric_spec_input(tmp_path, specs)
    observed = _numeric_spec_observed(tmp_path, manifest)
    assert observed == 'ACCEPTED'


@pytest.mark.parametrize('row', [
    {'name': 'gain', 'unit': 'V/V'},
    {'name': 'gain', 'target': True, 'unit': 'V/V'},
    {'name': 'gain', 'min': True, 'unit': 'V/V'},
    {'name': 'gain', 'max': '2.0', 'unit': 'V/V'},
    {'name': 'gain', 'target': True, 'min': 1.0, 'unit': 'V/V'},
])
def test_a04_numeric_spec_rejects_missing_or_invalid_numeric_value(tmp_path, row):
    observed = _numeric_spec_observed(tmp_path, _numeric_spec_input(tmp_path, [row]))
    assert observed == 'A04_ANALOG_SPEC_UNBOUND'


@pytest.mark.parametrize('damage,expected', [
    ('approval', 'A04_REQUIREMENTS_NOT_APPROVED'),
    ('provenance', 'A04_REQUIREMENTS_NOT_APPROVED'),
    ('budget', 'A04_BUDGET_UNBOUND'),
    ('stale', 'A04_STALE_OR_MISSING_INPUT'),
])
def test_a04_numeric_spec_keeps_authority_budget_and_hash_refusals(tmp_path, damage, expected):
    manifest = _numeric_spec_input(tmp_path, [{'name': 'gain', 'target': 2.0, 'unit': 'V/V'}])
    record = manifest['requirements']
    path = tmp_path / record['path']
    body = json.loads(path.read_text())
    if damage == 'approval':
        body['approval']['status'] = 'PENDING'
    elif damage == 'provenance':
        body['approval'].pop('source_reference')
    elif damage == 'budget':
        body['blocks'][0]['budgets']['power'] = {'status': 'UNBOUND', 'limit': None, 'unit': None}
    else:
        (tmp_path / body['blocks'][0]['spec']['path']).write_text('{}')
    if damage != 'stale':
        path.write_text(json.dumps(body))
        record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    observed = _numeric_spec_observed(tmp_path, manifest)
    assert observed == expected
