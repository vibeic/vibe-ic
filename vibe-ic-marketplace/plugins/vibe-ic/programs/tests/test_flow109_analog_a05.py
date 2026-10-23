"""Legacy qualified A05 netlist/checker/ngspice controls on a tiny circuit.

Canonical native dispatch is covered separately by test_analog_native_flow.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import flow109
import flow109_admission as admission
import flow109_analog_a05 as analog
import test_flow109_analog_a04 as a04_test
from flow109_admission import AdmissionRefusal
from _flow109_legacy_component_fixture import legacy_component_registry, run_legacy_component


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _case(project):
    _requirements, a02, _registry, _manifest = a04_test._case(project)
    a04_result = a04_test._run(project)
    assert a04_result.returncode == 0, a04_result.stdout + a04_result.stderr
    a04_receipt = {'path': 'reports/flow109/components/A04.json',
                   'sha256': hashlib.sha256(
                       (project / 'reports/flow109/components/A04.json').read_bytes()).hexdigest()}
    ir_path = project / 'phase3/analog/keeper_alpha/topology.json'
    ir = json.loads(ir_path.read_text())
    sizes = [{key: device[key] for key in ('name', 'role', 'w', 'l', 'm') if key in device}
             for device in ir['devices']]
    spec = {'path': 'phase3/analog/keeper_alpha/spec.json',
            'sha256': hashlib.sha256(
                (project / 'phase3/analog/keeper_alpha/spec.json').read_bytes()).hexdigest()}
    pdk = _put(project, 'input/flow109/A05-pdk.json', {
        'schema': analog.SCHEMA, 'family': 'sky130',
        'model_dependency_policy': 'self_contained_local'})
    requirements = _put(project, 'input/flow109/A05-requirements.json', {
        'schema': analog.SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'analog_design_authority',
                     'source_reference': 'neutral open-device OP control'},
        'blocks': [{'block': 'keeper_alpha', 'spec': spec, 'corner': 'tt',
                    'required_analysis': 'op', 'device_sizes': sizes,
                    'operating_point_targets': {
                        'vout': {'min': 0.01, 'max': 1.8, 'unit': 'V'},
                        'reff': {'min': 1.0, 'max': 1.0e9, 'unit': 'Ohm'}}}]})
    config = _put(project, analog.INPUT, {
        'schema': analog.SCHEMA, 'basis': 'expert_sizing_native_operating_point',
        'pdk': pdk, 'requirements': requirements,
        'a02_receipt': a02, 'a04_receipt': a04_receipt})
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Analog model-IP')
    uses = flow109.resolve_step(flow109.resolve_plan(features), 'A05')['tool_uses']
    identities = []
    records = []
    evidence = _put(project, 'input/flow109/A05-reference.json',
                    {'scope': 'developer native OP control; not PDK or benchmark signoff'})
    for use in uses:
        found = shutil.which(use['executable_name'])
        if not found:
            pytest.skip('A05 native controls require ' + use['executable_name'])
        binary = Path(found).resolve()
        version = subprocess.run([binary, '--version' if use['tool_id'] == 'python3' else '-v'],
                                 capture_output=True, text=True).stdout.strip()
        exe = {'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
        identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'], 'version': version,
                    'build_sha256': exe['sha256'], 'executable': exe,
                    'config': config, 'pdk': pdk, 'deck': requirements, 'corner': ['tt'],
                    'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                                  'operation_sources': analog.operation_sources()}}
        record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                  'reference_evidence': [evidence]}
        identities.append({**identity, 'qualification_sha256': admission.canonical_sha(record)})
        records.append(record)
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records}
    manifest = {'features': features, 'qualification_registry': 'qualifications.json',
                'runtime_tool_uses': identities}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    (project / 'manifest.json').write_text(json.dumps(manifest))
    return requirements, a02, a04_receipt, registry, manifest


def _run(project):
    return run_legacy_component(project, 'A05')


def _resign(project, registry, manifest):
    manifest['runtime_tool_uses'] = [
        {**record['identity'], 'qualification_sha256': admission.canonical_sha(record)}
        for record in registry['uses']]
    (project / 'qualifications.json').write_text(json.dumps(registry))
    (project / 'manifest.json').write_text(json.dumps(manifest))


def _rebind_requirements(project, requirements, registry):
    config_path = project / analog.INPUT
    config = json.loads(config_path.read_text())
    config['requirements'] = requirements
    config_path.write_text(json.dumps(config))
    config_record = {'path': analog.INPUT,
                     'sha256': hashlib.sha256(config_path.read_bytes()).hexdigest()}
    for record in registry['uses']:
        record['identity']['deck'] = requirements
        record['identity']['config'] = config_record


def test_a05_emits_substantive_netlist_and_native_ngspice_op(tmp_path):
    _case(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A05.json').read_text())
    assert report['component_status'] == 'PASS'
    assert report['flow109_acceptance'] == 'NOT_MEASURED'
    block = report['blocks'][0]
    assert block['producer']['records'][0]['action'] == 'emitted'
    assert block['consumer']['verdict'] in ('PASS', 'PASS_STRUCTURE_ONLY')
    native = block['native_operating_point']
    assert native['returncode'] == 0 and native['verdict'] == 'PASS'
    assert set(native['measurements']) >= {'vout', 'reff'}
    assert native['executed_inputs'] and (tmp_path / analog.FREEZE).is_file()
    assert set(report['gate_layers'].values()) == {'NOT_MEASURED'}


@pytest.mark.parametrize('damage', ['sizing', 'model', 'corner', 'threshold', 'source'])
def test_a05_refuses_bad_sizing_model_corner_threshold_or_source(tmp_path, damage):
    requirements, _a02, _a04, registry, manifest = _case(tmp_path)
    req_path = tmp_path / requirements['path']
    body = json.loads(req_path.read_text())
    if damage == 'sizing':
        body['blocks'][0]['device_sizes'][0]['w'] *= 2
    elif damage == 'corner':
        body['blocks'][0]['corner'] = 'ff'
    elif damage == 'threshold':
        body['blocks'][0]['operating_point_targets']['vout']['min'] = 0
    elif damage == 'model':
        model = tmp_path / 'input/pdk/spice/open_models.lib'
        model.write_text(model.read_text().replace('.subckt open_nmos_dev',
                                                    '.subckt broken_nmos_dev'))
    else:
        registry['uses'][0]['identity']['semantics']['operation_sources'] = {}
    if damage in ('sizing', 'corner', 'threshold'):
        req_path.write_text(json.dumps(body))
        requirements['sha256'] = hashlib.sha256(req_path.read_bytes()).hexdigest()
        _rebind_requirements(tmp_path, requirements, registry)
        if damage == 'corner':
            for record in registry['uses']:
                record['identity']['corner'] = ['ff']
    _resign(tmp_path, registry, manifest)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (tmp_path / analog.FREEZE).exists()


def test_a05_native_threshold_failure_is_fail_not_exit_zero_pass(tmp_path):
    requirements, _a02, _a04, registry, manifest = _case(tmp_path)
    req_path = tmp_path / requirements['path']
    body = json.loads(req_path.read_text())
    body['blocks'][0]['operating_point_targets']['vout'] = {
        'min': 1.7, 'max': 1.8, 'unit': 'V'}
    req_path.write_text(json.dumps(body))
    requirements['sha256'] = hashlib.sha256(req_path.read_bytes()).hexdigest()
    _rebind_requirements(tmp_path, requirements, registry)
    _resign(tmp_path, registry, manifest)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A05.json').read_text())
    assert report['component_status'] == 'FAIL'
    assert report['blocks'][0]['native_operating_point']['returncode'] == 0
    assert report['blocks'][0]['native_operating_point']['failures']


def test_bad_emitted_netlist_is_owned_by_retained_reader_then_restores_green(tmp_path, monkeypatch):
    _requirements, _a02, _a04, _registry, manifest = _case(tmp_path)
    plan = flow109.resolve_plan(manifest['features'])
    context = flow109.execution_context(
        plan, 'A05', 'A05', runtime_tool_uses=manifest['runtime_tool_uses'],
        qualification_registry='qualifications.json')
    original = analog._python
    damaged = []

    def corrupt_after_emission(project, context, prepared, argv, log):
        result = original(project, context, prepared, argv, log)
        if str(analog.PRODUCER) in argv and not damaged:
            netlist = project / 'phase3/analog/keeper_alpha/keeper_alpha.sp'
            netlist.write_text(netlist.read_text().replace('.ends keeper_alpha',
                                                            '* removed ends'))
            damaged.append(True)
        return result

    monkeypatch.setattr(analog, '_python', corrupt_after_emission)
    with pytest.raises(AdmissionRefusal, match='A05_SUBSTANTIVE_NETLIST_ABSENT'):
        analog.execute(tmp_path, context)
    assert damaged
    monkeypatch.setattr(analog, '_python', original)
    restored = _run(tmp_path)
    assert restored.returncode == 0, restored.stdout + restored.stderr


def test_a05_reuses_a02_bound_transitive_multi_library_closure(tmp_path):
    mos_root = tmp_path / 'input/pdk/models/cornerMOS.lib'
    mos_child = tmp_path / 'input/pdk/models/mos.mod'
    cap_root = tmp_path / 'input/pdk/models/cornerCAP.lib'
    cap_child = tmp_path / 'input/pdk/models/cap.mod'
    for path, text in (
        (mos_root, '.lib mos_tt\n.include mos.mod\n.endl mos_tt\n'),
        (mos_child, '.model open_n nmos level=1\n'),
        (cap_root, '.lib cap_typ\n.include cap.mod\n.endl cap_typ\n'),
        (cap_child, '.subckt open_cap p n\nc1 p n 1p\n.ends open_cap\n'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def rec(path):
        return {'path': str(path.relative_to(tmp_path)),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    sp = tmp_path / 'phase3/analog/block/block.sp'
    tb = tmp_path / 'phase3/analog/block/tb_block.sp'
    sp.parent.mkdir(parents=True)
    sp.write_text('.lib ../../../input/pdk/models/cornerMOS.lib mos_tt\n'
                  '.lib ../../../input/pdk/models/cornerCAP.lib cap_typ\n')
    tb.write_text('op\n')
    models = {
        (str(mos_root), 'mos_tt'): {
            'record': rec(mos_root), 'path': mos_root, 'device': 'open_n',
            'closure': [(mos_root, rec(mos_root)), (mos_child, rec(mos_child))],
        },
        (str(cap_root), 'cap_typ'): {
            'record': rec(cap_root), 'path': cap_root, 'device': 'open_cap',
            'closure': [(cap_root, rec(cap_root)), (cap_child, rec(cap_child))],
        },
    }
    resolved = analog._model_loads(
        tmp_path, sp, tb, {'mos_tt', 'cap_typ'}, models)
    assert resolved == sorted([mos_root, mos_child, cap_root, cap_child])
    with pytest.raises(AdmissionRefusal, match='A05_MODEL_CORNER_MISMATCH'):
        analog._model_loads(tmp_path, sp, tb, {'mos_tt'}, models)
