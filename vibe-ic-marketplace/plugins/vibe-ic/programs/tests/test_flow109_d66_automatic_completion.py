"""Focused automatic completion controls. All reliability/qualification fixtures
are synthetic: these tests do not qualify a native reliability method.
"""
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import flow109
import flow109_admission as admission
from test_flow109_d66_completed_evidence import completed_case
from test_flow109_final_perc import _put, _canonical_d65


def context_for(project, qualified=True):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan({**features, 'requires_perc': True})
    if not qualified:
        return flow109.execution_context(plan, 'D66', 'D66')
    uses = flow109.resolve_step(plan, 'D66')['tool_uses']
    records, runtime = [], []
    for index, use in enumerate(uses):
        executable = Path(shutil.which(use.get('executable_name', use['tool_id']))).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        identity = {
            'use_id': use['use_id'], 'tool_id': use['tool_id'], 'version': 'synthetic-control',
            'build_sha256': digest, 'executable': {'path': str(executable), 'sha256': digest},
            'config': _put(project, f'qualification/config{index}.json', {'synthetic': True}),
            'pdk': _put(project, f'qualification/pdk{index}.ref', 'synthetic model identity'),
            'deck': _put(project, f'qualification/deck{index}.ref', 'synthetic rule identity'),
            'corner': 'synthetic-control',
            'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps']},
        }
        record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                  'reference_evidence': [_put(project, f'qualification/reference{index}.json',
                                              {'synthetic_control_only': True})]}
        records.append(record)
        runtime.append({**identity, 'qualification_sha256': admission.canonical_sha(record)})
    _put(project, 'qualification/registry.json', {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records})
    return flow109.execution_context(plan, 'D66', 'D66', runtime_tool_uses=runtime,
                                    qualification_registry='qualification/registry.json')


def case(project, monkeypatch, *, qualified=True, canonical=True, physics=None):
    perc, _ = completed_case(project, monkeypatch, physics)
    manifest = json.loads((project / perc.INPUT).read_text())
    if canonical:
        d65, _ = _canonical_d65(project, manifest['final_subjects']['geometry_def'])
        manifest['d65_component'] = d65
        _put(project, perc.INPUT, manifest)
    context = context_for(project, qualified)
    source = _put(project, 'test-inputs/required-categories.txt', 'synthetic category requirements')
    _put(project, 'requirements/final_perc/final_esd_supply_topology.json', {
        'schema': 'vibeic.flow109.requirement-authority.v1',
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': source},
        'required_items': [{'category': name} for name in (
            'ESD protection presence', 'io_supply_pad_sufficiency',
            'ESD discharge-path topology (connectivity)', 'Native CVC electrical rules')],
    })
    result = perc.execute(project, context)
    return perc, context, result


def consume(project, perc, context, result):
    return flow109._selected_step_result(project, context, result, perc)


def test_automatic_completion_when_all_existing_evidence_passes(tmp_path, monkeypatch):
    perc, context, result = case(tmp_path, monkeypatch)
    assert result['component_status'] == 'PASS', result
    assert admission.require_admission(tmp_path, context)['status'] == 'PASS'
    answer = consume(tmp_path, perc, context, result)
    assert answer['metric_acceptance']['metric_status'] == 'PASS', answer
    assert answer['default_row_status'] == 'PASS' and answer['completed'] is True, answer
    assert answer['qualification']['status'] == 'PASS'
    assert answer['flow109_acceptance'] == 'PASS'
    assert answer['whole_flow_acceptance'] == answer['whole_ic_acceptance'] == 'NOT_MEASURED'
    assert answer['delivery_accepted'] is False


@pytest.mark.parametrize('damage,reason', [
    ('absent', 'QUALIFICATION_RUNTIME_ABSENT'),
    ('registry_missing', 'QUALIFICATION_INPUT_ABSENT'),
    ('stale', 'QUALIFICATION_STALE'),
    ('unsupported', 'QUALIFICATION_UNSUPPORTED'),
])
def test_qualification_is_reopened_and_blocks_completion(tmp_path, monkeypatch, damage, reason):
    perc, context, result = case(tmp_path, monkeypatch, qualified=damage != 'absent')
    assert result['component_status'] == 'PASS'
    if damage == 'registry_missing':
        (tmp_path / 'qualification/registry.json').unlink()
    elif damage == 'stale':
        (tmp_path / 'qualification/reference0.json').write_text('changed')
    elif damage == 'unsupported':
        path = tmp_path / 'qualification/registry.json'
        registry = json.loads(path.read_text()); registry['uses'][0]['status'] = 'UNSUPPORTED'
        path.write_text(json.dumps(registry))
    answer = consume(tmp_path, perc, context, result)
    assert answer['metric_acceptance']['metric_status'] == 'PASS', answer
    assert answer['completed'] is False and answer['default_row_status'] == 'NOT_MEASURED', answer
    assert answer['reason'] == reason, answer


@pytest.mark.parametrize('damage,status,reason', [
    ('legacy_minimal', 'NOT_MEASURED', 'D66_D65_CANONICAL_NOT_ACCEPTED'),
    ('missing', 'NOT_MEASURED', 'D66_REQUIRED_INPUT_ABSENT'),
    ('refused', 'FAIL', 'D66_D65_CANONICAL_FAILED'),
    ('foreign_geometry', 'NOT_MEASURED', 'D66_D65_CANONICAL_FINAL_DEF_MISMATCH'),
])
def test_d65_refusal_prevents_automatic_completion(tmp_path, monkeypatch, damage, status, reason):
    perc, context, result = case(tmp_path, monkeypatch, canonical=damage != 'legacy_minimal')
    assert result['component_status'] == 'PASS'
    if damage != 'legacy_minimal':
        manifest = json.loads((tmp_path / perc.INPUT).read_text())
        path = tmp_path / manifest['d65_component']['path']
        if damage == 'missing':
            path.unlink()
        else:
            d65 = json.loads(path.read_text())
            if damage == 'refused': d65['verdict'] = 'FAIL'
            else: d65['current_step_declared_producers']['input_identity']['files'][
                'phase3/stage3/pnr/routed.def'] = 'f' * 64
            manifest['d65_component'] = _put(tmp_path, manifest['d65_component']['path'], d65)
            _put(tmp_path, perc.INPUT, manifest)
    answer = consume(tmp_path, perc, context, result)
    assert answer['completed'] is False and answer['default_row_status'] == status, answer
    assert reason in (answer.get('reason'), answer['metric_acceptance'].get('reason')), answer


@pytest.mark.parametrize('physics,reason', [
    ('physics_residual', 'D66_DEVICE_PHYSICS_UNSUPPORTED'),
    ('absent_model', 'D66_PAD_LIBRARY_EVIDENCE_INVALID'),
    ('violation', 'D66_AUTOMATED_PERC_FAILED'),
])
def test_real_model_or_physics_blocker_is_not_bypassed(tmp_path, monkeypatch, physics, reason):
    perc, context, result = case(tmp_path, monkeypatch, physics=physics)
    assert result['component_status'] != 'PASS'
    assert admission.require_admission(tmp_path, context)['status'] == 'PASS'
    answer = consume(tmp_path, perc, context, result)
    assert answer['completed'] is False and answer['default_row_status'] == result['component_status'], answer
    assert answer['reason'] == reason, answer
