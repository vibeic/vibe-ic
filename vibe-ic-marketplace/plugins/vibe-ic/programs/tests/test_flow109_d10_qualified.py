"""Actual D10 consumer decisions using independently reviewed native records."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import vibe_ic_one_shot_runner as runner

pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_D10_APPROVED_REGISTRY')
    or not os.environ.get('VIBEIC_LIBRELANE_LOCAL_ATTESTATION'),
    reason='independently reviewed registry and actual local native launch required')


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def context(registry, path, *, missing_runtime=False):
    features = next(r['features'] for r in flow109.load_registry()['reference_profiles']
                    if r['name'] == 'Small digital IC without DFT')
    runtime = [{**copy.deepcopy(r['identity']), 'qualification_sha256': admission.canonical_sha(r)}
               for r in registry['uses']]
    return flow109.execution_context(flow109.resolve_plan(copy.deepcopy(features)), 'D10', 'D10',
        runtime_tool_uses=None if missing_runtime else runtime, qualification_registry=path)


@pytest.fixture(scope='module')
def cases():
    root = Path(os.environ['FLOW109_D10_QUALIFIED_OUTPUT'])
    approved_path = os.environ['FLOW109_D10_APPROVED_REGISTRY']
    approved = json.loads(Path(approved_path).read_text())
    inputs = json.loads(Path(os.environ['FLOW109_D10_QUALIFIED_INPUTS']).read_text())
    old = {k: os.environ.get(k) for k in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV)}
    cache = {}

    def case(kind):
        if kind in cache:
            return cache[kind]
        project = root / kind
        source = Path(inputs[kind])
        for rel in ('phase2/stage1/rtl', 'phase1/generated_docs'):
            shutil.copytree(source / rel, project / rel)
        c = context(approved, approved_path)
        ctx = project / 'context.json'
        put(ctx, c)
        os.environ[flow109.CONTEXT_ENV] = str(ctx)
        attempt = flow109._new_attempt(project, c)
        os.environ[flow109.ATTEMPT_ENV] = str(attempt)
        result = runner._finish_d10_unimplemented_owner(project, run_p0=True)
        put(project / 'consumer-result.json', result)
        cache[kind] = {'project': project, 'context': c, 'result': result,
            'p0': result['evidence']['p0_native'], 'attempt': attempt,
            'root': root, 'approved': approved, 'approved_path': approved_path}
        return cache[kind]
    yield case
    for key, value in old.items():
        os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)


@pytest.mark.parametrize('kind', ['positive', 'undefined_module', 'known_blackbox'])
def test_current_native_qualified_metrics_and_terminal(cases, kind):
    c = cases(kind)
    result = c['result']
    observed = result['evidence']['native_metric_observation']
    assert observed['qualification'] == 'PASS', observed
    assert observed['qualification_admission']['status'] == 'PASS'
    first, second = observed['obligations']
    assert first['status'] == ('FAIL' if kind == 'undefined_module' else 'PASS')
    assert first['observed_value'] == (1 if kind == 'undefined_module' else 0)
    assert second['status'] == ('PASS' if kind == 'positive' else 'NOT_MEASURED')
    assert second['observed_value'] == (0 if kind == 'positive' else None)
    assert result['verdict'] == ('FAIL' if kind == 'undefined_module' else 'NOT_MEASURED')
    assert result['whole_flow_verdict'] == 'NOT_MEASURED'
    terminal = json.loads((c['attempt'] / 'result.json').read_text())
    assert terminal['default_row_status'] == result['verdict']
    assert all(row['completed'] is False for row in terminal['components'])
    assert not (c['project'] / 'input/feature-decisions.json').exists()
    if kind == 'known_blackbox':
        assert observed['observed_blackbox_instances'] == ['u_opaque']
        assert second['reason'] == 'EXPECTED_BLACKBOX_AUTHORITY_MISSING'


@pytest.mark.parametrize('damage,reason', [
    ('runtime_missing', 'QUALIFICATION_RUNTIME_ABSENT'),
    ('registry_missing', 'QUALIFICATION_REGISTRY_ABSENT'),
    ('stale_digest', 'QUALIFICATION_STALE'),
    ('forged_build', 'QUALIFICATION_BUILD_MISMATCH'),
    ('wrong_purpose', 'QUALIFICATION_SCOPE_MISMATCH'),
    ('wrong_metrics', 'D10_QUALIFICATION_SCOPE_MISMATCH'),
    ('wrong_image', 'D10_QUALIFICATION_IMAGE_MISMATCH'),
    ('stale_model_input', 'QUALIFICATION_STALE'),
    ('wrong_config', 'D10_QUALIFICATION_CONFIG_MISMATCH'),
])
def test_actual_consumer_refuses_damaged_qualification(cases, tmp_path, damage, reason):
    c = cases('undefined_module')
    # Copies are intentionally invalid negative claims, never approved authority.
    registry = copy.deepcopy(c['approved'])
    identity = registry['uses'][0]['identity']
    if damage == 'forged_build':
        identity['build_sha256'] = '0' * 64
    if damage == 'wrong_purpose':
        identity['semantics']['purpose'] = 'D03.technology'
    if damage == 'wrong_metrics':
        identity['semantics']['checked_metrics'] = ['base_04.unexpected_blackboxes']
    if damage == 'wrong_image':
        identity['semantics']['model_identity']['image_id'] = 'sha256:' + '0' * 64
    if damage in ('stale_model_input', 'wrong_config'):
        config = json.loads(Path(identity['config']['path']).read_text())
        if damage == 'stale_model_input':
            original = identity['semantics']['model_identity']['source_model']
            model = tmp_path / 'damaged-reference.v'
            model.write_bytes(Path(original['path']).read_bytes() + b'\n// invalidated model input\n')
            bad_model = {'path': str(model), 'sha256': original['sha256']}
            identity['semantics']['model_identity']['source_model'] = bad_model
            config['test_model'] = bad_model
        else:
            config['actual_command'][4] = config['actual_command'][4].replace(
                'read_slang --single-unit', 'read_slang --allow-unknown-modules --single-unit')
        identity['config'] = put(tmp_path / 'INVALID-config.json', config)
    path = tmp_path / 'INVALID-qualification-claim.json'
    put(path, registry)
    ctx = context(registry, None if damage == 'registry_missing' else str(path),
                  missing_runtime=damage == 'runtime_missing')
    if damage == 'stale_digest':
        ctx['runtime_tool_uses'][0]['qualification_sha256'] = '0' * 64
        # Use the normal context constructor to bind the deliberately stale identity.
        ctx = flow109.execution_context(flow109.resolve_plan(ctx['features']), 'D10', 'D10',
            runtime_tool_uses=ctx['runtime_tool_uses'], qualification_registry=str(path))
    observed = metrics.observe_d10_frontend_metrics(c['project'], ctx, c['p0'])
    assert observed['qualification'] == observed['status'] == 'NOT_MEASURED', observed
    assert observed['qualification_refusal']['reason'] == reason, observed
    assert all(o['status'] == 'NOT_MEASURED' for o in observed['obligations'])
    put(c['root'] / ('refusal-' + damage + '.json'), observed)
    path.unlink()


@pytest.mark.parametrize('damage', ['missing_identity', 'stale_current_input', 'scalar_qualification'])
def test_actual_consumer_never_borrows_native_or_packet_authority(cases, damage):
    c = cases('undefined_module')
    packet = copy.deepcopy(c['p0'])
    ctx = c['context']
    rtl = next((c['project'] / 'phase2/stage1/rtl').glob('*.v'))
    original = rtl.read_bytes()
    if damage == 'missing_identity':
        packet.pop('tool_sha256')
    if damage == 'stale_current_input':
        rtl.write_bytes(original + b'\n// stale actual subject\n')
    if damage == 'scalar_qualification':
        packet['qualification'] = 'QUALIFIED'
        ctx = context(c['approved'], c['approved_path'], missing_runtime=True)
    try:
        observed = metrics.observe_d10_frontend_metrics(c['project'], ctx, packet)
    finally:
        rtl.write_bytes(original)
    assert observed['qualification'] == observed['status'] == 'NOT_MEASURED', observed
    assert all(o['status'] == 'NOT_MEASURED' for o in observed['obligations'])
    if damage != 'scalar_qualification':
        assert observed['obligations'] == [] and 'native_failure' not in observed
    put(c['root'] / ('refusal-' + damage + '.json'), observed)
