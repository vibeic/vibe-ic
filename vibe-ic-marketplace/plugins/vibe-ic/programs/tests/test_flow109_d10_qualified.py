"""Actual D10 consumer decisions using independently reviewed native records."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

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


@pytest.fixture(scope='module')
def bound_row(tmp_path_factory):
    """Explicit software upstream/owner fixtures; native tools are never doubled.

    This is no D01/D09/product qualification. Expected interfaces are authored
    from the neutral source before P0, never copied from its measured graph.
    """
    import _cdc_netlist as native
    import _path_layout as layout
    from programs.tests.test_flow109_selection import _publish_dft_intent
    project = tmp_path_factory.mktemp('d10-bound-row')
    _publish_dft_intent(project, {'requires_scan': False,
                               'reason': 'neutral control has no scan requirement'})
    rtl = project / 'phase2/stage1/rtl/leaf.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module leaf_top #(parameter WIDTH=2) '
                   '(input [WIDTH-1:0] a, output [WIDTH-1:0] y); assign y=a; endmodule\n')
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'leaf_top'})
    # An explicitly scoped upstream fixture exercises only D10 consumption.
    put(project / 'reports/flow109/default_rows/D09.json', {
        'step_id': 'D09', 'completed': True, 'component_status': 'PASS',
        'default_row_status': 'PASS', 'fixture_scope': 'SOFTWARE_UPSTREAM_PRECONDITION_ONLY',
        'evidence': {'rtl_inventory': [{'path': 'leaf.v',
            'sha256': hashlib.sha256(rtl.read_bytes()).hexdigest()}]}})
    subject = metrics.d10_adopted_rtl(project)
    subject['rtl_inputs'] = native.source_binding(project, 'leaf_top')['files']
    reference = {'top': 'leaf_top', 'modules': {'leaf_top': {
        'ports': {n: {'direction': direction, 'width': 2, 'signed': 0}
                  for n, direction in [('a', 'input'), ('y', 'output')]},
        'parameter_defaults': {'WIDTH': '0' * 30 + '10'}}},
        'instances': {}, 'blackbox_instances': []}
    source = project / 'input/flow109/D10_source_authority.json'
    source_ref = put(source, {'fixture_scope': 'SOFTWARE_OWNER_PRECONDITION_NOT_PRODUCT_ADOPTION',
                             'feature_inventory': {'reference': reference, 'reference_identity': subject}})
    source_ref['path'] = str(source.relative_to(project))
    adopted = project / 'adopted/base_04/feature_inventory.json'
    put(adopted, {'schema': 'vibeic.flow109.adopted-reference.v1',
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': source_ref},
        'reference': reference, 'reference_identity': subject})
    registry_path = os.environ['FLOW109_D10_APPROVED_REGISTRY']
    registry = json.loads(Path(registry_path).read_text())
    c = context(registry, registry_path)
    manifest = project / 'selection.json'
    put(manifest, {key: c[key] for key in ('features', 'runtime_tool_uses', 'qualification_registry')})
    return {'project': project, 'context': c, 'manifest': manifest, 'adopted': adopted,
            'source': source, 'reference': reference, 'layout': layout}


def test_d10_canonical_selected_owner_publishes_complete_row(bound_row, monkeypatch):
    c = bound_row
    project = c['project']
    # Select the actual canonical owner context and immutable attempt. No D01
    # qualification is manufactured to make a whole front-door fixture pass.
    path = project / 'context.json'
    put(path, c['context'])
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    attempt = flow109._new_attempt(project, c['context'])
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    result = runner._finish_d10_unimplemented_owner(project, run_p0=True)
    assert result['verdict'] == 'PASS', result
    row = json.loads((project / 'reports/flow109/default_rows/D10.json').read_text())
    assert row['default_row_status'] == 'PASS' and row['completed'] is True
    acceptance = row['metric_acceptance']
    assert [r['status'] for r in acceptance['obligations']] == ['PASS'] * 3
    assert acceptance['dft_port_consistency']['reason'] == 'SCAN_NOT_REQUIRED'
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and not row['delivery_accepted']
    p0 = row['evidence']['p0_native']
    assert p0['status'] == 'PASS'
    assert acceptance['obligations'][2]['observed_value'] == c['reference']
    c['p0'] = p0


def test_d10_public_dispatch_calls_only_selected_owner(bound_row, monkeypatch):
    """Routing-only control: no native/admission/row qualification is claimed."""
    c = bound_row
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(c['project']), '--flow', '109',
        '--flow109-manifest', str(c['manifest']), '--entry-step', 'D10', '--exit-step', 'D10',
        '--route', 'ic', '--skip-phase1', '--skip-phase3', '--skip-analog', '--no-dashboard'])
    # Upstream D01 provenance is a separate software precondition for this
    # branch-only test. Never present its terminal NOT_MEASURED as native PASS.
    monkeypatch.setattr(runner, '_standalone_rtl_provenance', lambda *_: {'ran': True})
    seen = []
    monkeypatch.setattr(runner, '_finish_d10_unimplemented_owner',
        lambda *_a, **kw: seen.append(kw) or {'verdict': 'NOT_MEASURED'})
    def no_generator(*args, **kwargs):
        raise AssertionError('D10 must not invoke the Phase2 RTL generator or snapshot owner')
    monkeypatch.setattr(runner, '_run_phase', no_generator)
    assert runner._main() == 2
    assert seen == [{'run_p0': True, 'input_refusal': None}]


@pytest.mark.parametrize('damage', ['absent', 'forged_payload', 'stale_source', 'wrong_owner',
                                  'changed_rtl', 'changed_tool', 'old_launch'])
def test_d10_row_refuses_independent_binding_damage(bound_row, damage):
    c = bound_row
    assert 'p0' in c, 'run the explicit canonical positive prerequisite first'
    adopted, source = c['adopted'].read_bytes(), c['source'].read_bytes()
    rtl = c['project'] / 'phase2/stage1/rtl/leaf.v'
    original_rtl = rtl.read_bytes()
    p0 = copy.deepcopy(c['p0'])
    try:
        if damage == 'absent':
            c['adopted'].unlink()
        elif damage in ('forged_payload', 'wrong_owner'):
            doc = json.loads(adopted)
            if damage == 'forged_payload':
                doc['reference']['modules']['leaf_top']['ports']['a']['width'] = 1
            else:
                doc['approval']['authority'] = 'caller'
            put(c['adopted'], doc)
        elif damage == 'stale_source':
            c['source'].write_bytes(source + b'\n')
        elif damage == 'changed_rtl':
            rtl.write_bytes(original_rtl + b'\n// changed actual subject\n')
        elif damage == 'changed_tool':
            p0['tool_sha256']['yosys'] = '0' * 64
        elif damage == 'old_launch':
            p0['cid'] = '0' * 64
        result = metrics.accept_d10(c['project'], c['context'], p0)
        assert result['status'] == 'NOT_MEASURED', result
        assert result['obligations'][-1]['status'] == 'NOT_MEASURED'
    finally:
        c['adopted'].write_bytes(adopted)
        c['source'].write_bytes(source)
        rtl.write_bytes(original_rtl)


def test_d10_independent_feature_mismatch_is_fail(bound_row):
    c = bound_row
    original = c['source'].read_bytes(), c['adopted'].read_bytes()
    try:
        source = json.loads(original[0])
        # A distinct independently supplied expectation is intentionally wrong;
        # the checker must compare it rather than overwrite it with measurement.
        source['feature_inventory']['reference']['modules']['leaf_top']['ports']['a']['width'] = 1
        put(c['source'], source)
        adopted = json.loads(original[1])
        adopted['reference'] = source['feature_inventory']['reference']
        adopted['approval']['source_reference']['sha256'] = hashlib.sha256(c['source'].read_bytes()).hexdigest()
        put(c['adopted'], adopted)
        result = metrics.accept_d10(c['project'], c['context'], c['p0'])
        assert result['status'] == 'FAIL', result
        assert result['obligations'][-1]['status'] == 'FAIL'
    finally:
        c['source'].write_bytes(original[0]); c['adopted'].write_bytes(original[1])


def test_d10_qualified_defect_stays_fail_without_adopted_inventory(cases):
    c = cases('undefined_module')
    result = metrics.accept_d10(c['project'], c['context'], c['p0'])
    assert result['native_metric_observation']['qualification'] == 'PASS'
    assert result['obligations'][0]['status'] == result['status'] == 'FAIL'
    assert result['obligations'][-1]['status'] == 'NOT_MEASURED'
