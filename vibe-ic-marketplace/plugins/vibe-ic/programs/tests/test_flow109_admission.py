"""Admission contract controls; synthetic references are NOT native qualification."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import flow109
import flow109_admission as admission


def artifact(project, name, content):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture_context(project, monkeypatch, step="D38"):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    if step == "D48":
        features = {**features, "requires_si": True}
    plan = flow109.resolve_plan(features)
    use = flow109.resolve_step(plan, step)['tool_uses'][0]
    exe = artifact(project, 'unit-openroad', 'unit test executable identity, not a real tool')
    exe['path'] = str(project / exe['path'])
    monkeypatch.setattr(admission.shutil, 'which', lambda name: exe['path'] if name == use.get('executable_name', use['tool_id']) else None)
    identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'], 'version': 'unit-control',
                'build_sha256': exe['sha256'], 'executable': exe,
                'config': artifact(project, 'config.json', '{}'),
                'pdk': artifact(project, 'pdk.ref', 'unit PDK'),
                'deck': artifact(project, 'deck.ref', 'unit deck'), 'corner': 'unit-corner',
                'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps']}}
    record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
              'reference_evidence': [artifact(project, 'reference.json', '{"unit_control":true}') ]}
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [record]}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    context = flow109.execution_context(plan, step, step,
        runtime_tool_uses=[{**identity, 'qualification_sha256': admission.canonical_sha(record)}],
        qualification_registry='qualifications.json')
    return context, registry


def rebind(context):
    context['context_sha256'] = flow109.digest({k:v for k,v in context.items() if k != 'context_sha256'})


def test_current_per_use_contract_accepts_without_mutating_evidence(tmp_path, monkeypatch):
    context, _ = fixture_context(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = admission.require_admission(tmp_path, context)
    assert result['status'] == 'PASS' and result['native_started'] is False
    assert all(p.read_bytes() == data for p,data in before.items())


@pytest.mark.parametrize('field', ['version','build_sha256','config','pdk','deck','corner','semantics','tool_id'])
def test_runtime_identity_change_refuses(tmp_path, monkeypatch, field):
    context, _ = fixture_context(tmp_path, monkeypatch)
    context['runtime_tool_uses'][0][field] = 'changed'
    rebind(context)
    with pytest.raises(admission.AdmissionRefusal, match='IDENTITY_MISMATCH'):
        admission.require_admission(tmp_path, context)


@pytest.mark.parametrize('status', ['UNSUPPORTED', 'STALE', 'FAIL', 'NOT_MEASURED'])
def test_unqualified_use_refuses(tmp_path, monkeypatch, status):
    context, registry = fixture_context(tmp_path, monkeypatch)
    registry['uses'][0]['status'] = status
    (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    with pytest.raises(admission.AdmissionRefusal, match='QUALIFICATION_' + status):
        admission.require_admission(tmp_path, context)


@pytest.mark.parametrize('name', ['config.json','pdk.ref','deck.ref','reference.json','unit-openroad'])
@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_evidence_missing_or_stale_refuses(tmp_path, monkeypatch, name, damage):
    context, _ = fixture_context(tmp_path, monkeypatch)
    path = tmp_path / name
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text('changed')
    with pytest.raises(admission.AdmissionRefusal):
        admission.require_admission(tmp_path, context)


def test_unrelated_qualification_does_not_invalidate_current_use(tmp_path, monkeypatch):
    context, registry = fixture_context(tmp_path, monkeypatch)
    registry['uses'].append({'use_id': 'another-step', 'status': 'FAIL'})
    (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    assert admission.require_admission(tmp_path, context)['status'] == 'PASS'


def test_scope_cannot_qualify_cts_with_version_probe(tmp_path, monkeypatch):
    context, registry = fixture_context(tmp_path, monkeypatch)
    registry['uses'][0]['identity']['semantics']['native_steps'] = ['--version']
    context['runtime_tool_uses'][0]['semantics']['native_steps'] = ['--version']
    context['runtime_tool_uses'][0]['qualification_sha256'] = admission.canonical_sha(registry['uses'][0])
    rebind(context)
    (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    with pytest.raises(admission.AdmissionRefusal, match='SCOPE_MISMATCH'):
        admission.require_admission(tmp_path, context)


def test_legacy_launch_has_no_new_requirement(tmp_path, monkeypatch):
    monkeypatch.delenv('VIBEIC_FLOW109_CONTEXT', raising=False)
    assert admission.require_launch_admission(tmp_path, '19', {}) is None


@pytest.mark.parametrize('step', ['D45', 'D69', 'D70', 'D71'])
def test_registered_default_native_owner_does_not_claim_generic_qualification(tmp_path, step):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), step, step)
    result = admission.require_launch_admission(tmp_path, 'flow109.' + step,
                                                {'flow109_context': context})
    assert result['admitted'] is True
    assert result['status'] == 'NOT_APPLICABLE'
    assert result['qualification_status'] == 'NOT_CLAIMED'
    assert result['flow109_acceptance'] == 'NOT_MEASURED'


def test_registered_default_backend_owner_uses_existing_native_admission(
        tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, 'ic') is None
    # prepare_front_door installs these directly.  Record their absent state
    # with monkeypatch so this test cannot leave D31 authority in a later
    # ordinary producer running in the same pytest worker.
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ''))
        monkeypatch.delenv(name)
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(features)
    context = flow109.execution_context(plan, 'D31', 'D31')
    dispatch = flow109.source_owned_native_dispatch(context['resolved_row'])
    assert dispatch['kind'] == 'canonical_backend_window'
    assert dispatch['native_step_id'] == '15'
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': plan['features']}))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D31', exit_step='D31')
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ('15', '15')
    recorded = json.loads(
        (tmp_path / 'reports/flow109/admission.json').read_text())
    assert recorded['qualification_status'] == 'NOT_CLAIMED'
    result = admission.require_launch_admission(
        tmp_path, '15', {'flow109_context': context})
    assert result['admitted'] is True
    assert result['status'] == 'NOT_APPLICABLE'
    assert result['qualification_status'] == 'NOT_CLAIMED'
    assert result['acceptance_scope'] == 'existing_native_component_only'
    assert result['flow109_acceptance'] == 'NOT_MEASURED'


def test_explicit_backend_qualification_claim_stays_strict(tmp_path):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(
        flow109.resolve_plan(features), 'D31', 'D31',
        runtime_tool_uses=[], qualification_registry='missing.json')
    with pytest.raises(admission.AdmissionRefusal,
                       match='QUALIFICATION_RUNTIME_ABSENT'):
        admission.require_launch_admission(
            tmp_path, '15', {'flow109_context': context})


@pytest.mark.parametrize('step', ['D45', 'D69', 'D70', 'D71'])
def test_caller_cannot_forge_registered_native_owner(tmp_path, step):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), step, step)
    context['resolved_row']['profile']['dispatch']['adapter'] = 'caller_plugin'
    rebind(context)
    with pytest.raises(admission.AdmissionRefusal, match='FLOW109_CONTEXT_INVALID'):
        admission.require_launch_admission(tmp_path, 'flow109.' + step,
                                           {'flow109_context': context})


@pytest.mark.parametrize('step', ['D69', 'D70', 'D71'])
def test_final_native_explicit_qualification_claim_stays_strict(tmp_path, step):
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(
        flow109.resolve_plan(features), step, step, runtime_tool_uses=[],
        qualification_registry='missing-qualifications.json')
    with pytest.raises(admission.AdmissionRefusal,
                       match='QUALIFICATION_RUNTIME_ABSENT'):
        admission.require_launch_admission(
            tmp_path, 'flow109.' + step, {'flow109_context': context})


def test_worker_refuses_before_native_producer(tmp_path, monkeypatch):
    import execution_backend_worker as worker
    inputs = tmp_path / 'inputs'
    project = inputs / 'project'
    project.mkdir(parents=True)
    context, _ = fixture_context(project, monkeypatch)
    context['runtime_tool_uses'][0]['corner'] = 'unsupported-corner'
    rebind(context)
    calls = []
    monkeypatch.setattr(worker, 'produce', lambda *a: calls.append('native'))
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING', json.dumps({'required_gates': []}))
    result = worker.execute(inputs, tmp_path / 'outputs', step_id='19', params={
        'flow109_context': context,
        'resolved_input_manifest': {'declarations': [], 'files': {}, 'missing': []}})
    assert not calls
    assert result['flow109_admission']['native_started'] is False
    assert result['flow109_admission']['reason'] == 'QUALIFICATION_IDENTITY_MISMATCH'
    assert result['verdict'] != 'PASS'


def test_direct_default_refuses_before_input_refresh_and_native(tmp_path, monkeypatch):
    import phase3_one_shot_runner as runner
    import execution_policy
    import flow_compliance_check as compliance
    context, _ = fixture_context(tmp_path, monkeypatch)
    context['runtime_tool_uses'][0]['corner'] = 'unsupported-corner'
    rebind(context)
    path = tmp_path / 'context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(path))
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *a: {})
    monkeypatch.setattr(compliance, '_check_condition', lambda *a: True)
    calls = []
    monkeypatch.setattr(execution_policy, '_fixed_inputs', lambda *a,**kw: calls.append('input-binding'))
    result = runner._default_pnr_rows(tmp_path, 'unit', SimpleNamespace(name='unit'), '', ['19'])
    assert result.status == 'NOT_MEASURED'
    assert calls == []
    assert 'QUALIFICATION_IDENTITY_MISMATCH' in result.detail


@pytest.mark.parametrize('damage', ['unsupported', 'corner', 'deck'])
def test_real_worker_process_refuses_without_launching_native(tmp_path, monkeypatch, damage):
    """Actual worker process, no producer/evaluator mocks; not positive qualification."""
    import subprocess
    import sys
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING', json.dumps({'required_gates': []}))
    inputs = tmp_path / 'inputs'
    project = inputs / 'project'
    project.mkdir(parents=True)
    context, registry = fixture_context(project, monkeypatch)
    if damage == 'unsupported':
        registry['uses'][0]['status'] = 'UNSUPPORTED'
        (project / 'qualifications.json').write_text(json.dumps(registry))
    elif damage == 'corner':
        context['runtime_tool_uses'][0]['corner'] = 'unsupported-corner'
        rebind(context)
    else:
        (project / 'deck.ref').write_text('unqualified changed deck')
    context_path = tmp_path / 'context.json'
    context_path.write_text(json.dumps(context))
    output = tmp_path / 'outputs'
    audit = tmp_path / 'process-launches.jsonl'
    script = tmp_path / 'actual-worker.py'
    script.write_text('''import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
def audit(event, args):
    if event == 'subprocess.Popen':
        with open(sys.argv[5], 'a') as out:
            out.write(json.dumps(str(args)) + '\\n')
sys.addaudithook(audit)
import execution_backend_worker as worker
context = json.loads(Path(sys.argv[4]).read_text())
worker.execute(Path(sys.argv[2]), Path(sys.argv[3]), step_id='19', params={
    'flow109_context': context,
    'resolved_input_manifest': {'declarations': [], 'files': {}, 'missing': []}})
''')
    completed = subprocess.run([sys.executable, str(script), str(Path(__file__).resolve().parents[1]),
        str(inputs), str(output), str(context_path), str(audit)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    result = json.loads((output / 'backend_result.json').read_text())
    assert result['flow109_admission']['native_started'] is False
    assert result['verdict'] == 'NOT_MEASURED'
    assert result['native_receipts'] == []
    assert not audit.exists(), audit.read_text() if audit.exists() else ''


def test_worker_current_unit_contract_reaches_producer(tmp_path, monkeypatch):
    """Positive launch-seam control only; synthetic registry is not qualification."""
    import execution_backend_worker as worker
    inputs = tmp_path / 'inputs'
    project = inputs / 'project'
    project.mkdir(parents=True)
    context, _ = fixture_context(project, monkeypatch)
    calls = []
    def produce(*args):
        calls.append('producer')
        return {'verdict': 'NOT_MEASURED', 'detail': 'unit transport, no native measurement'}
    monkeypatch.setattr(worker, 'produce', produce)
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING', json.dumps({'required_gates': []}))
    result = worker.execute(inputs, tmp_path / 'outputs', step_id='19', params={
        'flow109_context': context,
        'resolved_input_manifest': {'declarations': [], 'files': {}, 'missing': []}})
    assert calls == ['producer']
    assert result['flow109_admission']['status'] == 'PASS'
    assert result['verdict'] == 'NOT_MEASURED'


def test_standalone_sta_uses_source_owned_executable_alias(tmp_path, monkeypatch):
    context, _ = fixture_context(tmp_path, monkeypatch, step='D48')
    assert context['resolved_row']['tool_uses'][0]['tool_id'] == 'opensta'
    assert context['resolved_row']['tool_uses'][0]['executable_name'] == 'sta'
    assert admission.require_admission(tmp_path, context)['status'] == 'PASS'
