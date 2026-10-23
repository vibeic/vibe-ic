"""Legacy qualified A01 component controls; fixture qualification is not IC signoff.

The shipped emitter/checker run as real Python subprocesses. No analog circuit
simulator, ADC project, oracle, or old PASS is used by these controls.
Canonical native dispatch is covered separately by test_analog_native_flow.py.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

import flow109
import flow109_admission as admission
import flow109_analog as analog
from _analog_producer_fixture import block, make_project
from _flow109_legacy_component_fixture import legacy_component_registry, run_legacy_component


def _artifact(project, name, text):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _case(project, *, specs=True):
    make_project(project, [block('regulator_alpha', 'ldo',
        [{'name': 'Vout', 'target': 1.8, 'unit': 'V'}] if specs else None)])
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Analog model-IP')
    plan = flow109.resolve_plan(features)
    use = flow109.resolve_step(plan, 'A01')['tool_uses'][0]
    binary = Path(shutil.which('python3')).resolve()
    exe = {'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    not_applicable = {'applicable': False, 'reason': 'structured spec binding does not load device decks'}
    identity = {'use_id': use['use_id'], 'tool_id': 'python3', 'version': sys.version,
                'build_sha256': exe['sha256'], 'executable': exe,
                'config': _artifact(project, 'input/a01-control.json', '{"operation":"structured-spec-binding"}'),
                'pdk': not_applicable, 'deck': not_applicable, 'corner': 'not-applicable',
                'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                              'operation_sources': analog.operation_sources()}}
    reference = _artifact(project, 'input/qualification-control.json',
                          '{"scope":"developer contract control; not native tool qualification"}')
    record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
              'reference_evidence': [reference]}
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [record]}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    manifest = {'features': features, 'qualification_registry': 'qualifications.json',
                'runtime_tool_uses': [{**identity, 'qualification_sha256': admission.canonical_sha(record)}]}
    (project / 'manifest.json').write_text(json.dumps(manifest))
    return manifest, registry


def _run(project):
    return run_legacy_component(project, 'A01', audit_launches=True)


def _save(project, manifest, registry):
    record = registry['uses'][0]
    manifest['runtime_tool_uses'][0] = {
        **record['identity'], 'qualification_sha256': admission.canonical_sha(record)}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    (project / 'manifest.json').write_text(json.dumps(manifest))


def test_actual_a01_front_door_runs_emitter_and_gate_without_claiming_metric_pass(tmp_path):
    _case(tmp_path)
    old = tmp_path / 'reports/analog_one_shot.json'
    old.parent.mkdir()
    old.write_text('{"legacy_status":"PASS","do_not_reinterpret":true}\n')
    before = old.read_bytes()
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A01.json').read_text())
    assert report['component_status'] == 'PASS'
    assert report['flow109_acceptance'] == 'NOT_MEASURED'
    assert report['metric_acceptance_status'] == 'NOT_MEASURED'
    assert report['unimplemented_obligations'] == []
    assert [Path(e['argv'][1]).name for e in report['executions']] == [
        'analog_a1_spec_emit.py', 'analog_a1_spec_extract_check.py']
    assert all(e['returncode'] == 0 for e in report['executions'])
    assert report['blocks'][0]['gate']['verdict'] == 'PASS'
    spec = json.loads((tmp_path / 'phase3/analog/regulator_alpha/spec.json').read_text())
    assert spec['specs'][0]['target'] == 1.8 and spec['specs'][0]['unit'] == 'V'
    assert spec['_provenance']['input']['sha256'] == report['inputs']['phase1/generated_docs/L5_ADI_SPEC.json']
    assert report['source_sha256'] == analog.operation_sources()
    assert old.read_bytes() == before
    launches = (tmp_path / 'launches.jsonl').read_text()
    assert 'analog_a1_spec_emit.py' in launches and 'analog_a1_spec_extract_check.py' in launches
    assert all(tool not in launches for tool in ('ngspice', 'analog_a2_topology_emit.py', 'analog_real_corner_sweep.py'))
    assert not list(tmp_path.rglob('corner_results.json'))


@pytest.mark.parametrize('damage', ['unsupported', 'source', 'reference', 'config', 'runtime_binary'])
def test_qualification_refuses_before_any_actual_native_launch(tmp_path, damage):
    manifest, registry = _case(tmp_path)
    if damage == 'unsupported':
        registry['uses'][0]['status'] = 'UNSUPPORTED'
    elif damage == 'source':
        registry['uses'][0]['identity']['semantics']['operation_sources']['programs/analog_a1_spec_emit.py'] = '0' * 64
    elif damage == 'reference':
        (tmp_path / 'input/qualification-control.json').unlink()
    elif damage == 'config':
        (tmp_path / 'input/a01-control.json').write_text('changed')
    else:
        registry['uses'][0]['identity']['executable']['path'] = '/not/the/runtime/python3'
    _save(tmp_path, manifest, registry)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'REFUSED' in result.stderr
    assert not (tmp_path / 'launches.jsonl').exists()
    assert not (tmp_path / 'reports/flow109/attempts').exists()
    assert not (tmp_path / 'phase3/analog/regulator_alpha/spec.json').exists()


def test_missing_spec_remains_unmeasured_even_when_legacy_gate_returns_vacuous_or_waived(tmp_path):
    _case(tmp_path, specs=False)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A01.json').read_text())
    assert report['component_status'] == 'NOT_MEASURED'
    assert report['blocks'][0]['gate']['verdict'] == 'WAIVED'
    assert report['executions'][0]['returncode'] == 2
    assert report['flow109_acceptance'] == 'NOT_MEASURED'
    assert not (tmp_path / 'phase3/analog/regulator_alpha/spec.json').exists()


def test_actual_launch_seam_rechecks_qualification_after_initial_admission(tmp_path, monkeypatch):
    manifest, registry = _case(tmp_path)
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'A01', 'A01',
        runtime_tool_uses=manifest['runtime_tool_uses'], qualification_registry='qualifications.json')
    original = analog._blocks

    def invalidate_after_initial_admission(project):
        names = original(project)
        registry['uses'][0]['status'] = 'UNSUPPORTED'
        (project / 'qualifications.json').write_text(json.dumps(registry))
        return names

    monkeypatch.setattr(analog, '_blocks', invalidate_after_initial_admission)
    with pytest.raises(admission.AdmissionRefusal, match='QUALIFICATION_UNSUPPORTED'):
        analog.execute(tmp_path, context)
    assert not list(tmp_path.rglob('producer.json'))
    assert not list(tmp_path.rglob('producer.log'))
    assert not (tmp_path / 'phase3/analog/regulator_alpha/spec.json').exists()


def test_unbound_preexisting_spec_is_preserved_and_not_adopted_as_fresh_production(tmp_path):
    _case(tmp_path)
    spec = tmp_path / 'phase3/analog/regulator_alpha/spec.json'
    spec.parent.mkdir()
    spec.write_text('{"Vout":99,"owner":"human"}')
    before = spec.read_bytes()
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A01.json').read_text())
    assert report['blocks'][0]['gate']['verdict'] == 'PASS'
    assert report['blocks'][0]['current_emission'] is False
    assert report['component_status'] == 'NOT_MEASURED'
    assert spec.read_bytes() == before


def test_measured_gate_failure_is_not_demoted_to_unmeasured(tmp_path):
    _case(tmp_path)
    spec = tmp_path / 'phase3/analog/regulator_alpha/spec.json'
    spec.parent.mkdir()
    spec.write_text('{"Vout":1.8,"_provenance":{"fields_defaulted":["Vout"]}}')
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A01.json').read_text())
    assert report['component_status'] == 'FAIL'
    assert report['blocks'][0]['gate']['verdict'] == 'FAIL'


@pytest.mark.parametrize('damage', ['missing', 'empty', 'duplicate', 'path_escape'])
def test_invalid_block_population_cannot_vacuously_pass(tmp_path, damage):
    _case(tmp_path)
    path = tmp_path / 'phase3/analog/analog_block_list.json'
    data = json.loads(path.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'empty':
        path.write_text('{"blocks":[]}')
    elif damage == 'duplicate':
        data['blocks'].append(copy.deepcopy(data['blocks'][0]))
        path.write_text(json.dumps(data))
    else:
        data['blocks'][0]['name'] = '../outside'
        path.write_text(json.dumps(data))
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (tmp_path / 'launches.jsonl').exists()
    assert not (tmp_path / 'reports/flow109/attempts').exists()
