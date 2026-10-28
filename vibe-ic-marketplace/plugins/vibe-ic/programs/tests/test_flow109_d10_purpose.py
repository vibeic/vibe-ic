"""D10 registration and real native reference facts; never grants qualification."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import p0_tool_frontend_check as frontend
import vibe_ic_one_shot_runner as runner


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return {'path': str(path), 'sha256': sha(path)}


def context(runtime=None, registry=None):
    features = next(r['features'] for r in flow109.load_registry()['reference_profiles']
                    if r['name'] == 'Small digital IC without DFT')
    return flow109.execution_context(flow109.resolve_plan(copy.deepcopy(features)), 'D10', 'D10',
        runtime_tool_uses=runtime, qualification_registry=registry)


def test_registered_d10_uses_match_actual_native_tools():
    uses = context()['resolved_row']['tool_uses']
    assert [(u['use_id'], u['native_steps'], u['executable_name']) for u in uses] == [
        ('flow109.D10.default.yosys', ['Yosys.JsonHeader'], 'yosys'),
        ('flow109.D10.default.verilator', ['Verilator.Lint'], 'verilator')]
    assert all(u['purpose'] == 'D10.default' and u['qualification_required'] for u in uses)


@pytest.fixture(scope='module')
def reference(tmp_path_factory):
    if not os.environ.get('VIBEIC_LIBRELANE_LOCAL_ATTESTATION') or any(
            not shutil.which(t) for t in ('yosys', 'verilator')):
        pytest.skip('actual local attestation and native tools required')
    root = Path(os.environ['FLOW109_D10_REFERENCE_OUTPUT']) if os.environ.get(
        'FLOW109_D10_REFERENCE_OUTPUT') else tmp_path_factory.mktemp('d10-purpose-reference')
    project = root / 'known-blackbox'
    rtl = project / 'phase2/stage1/rtl/reference.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('(* blackbox *) module reference_opaque(input a,output y); endmodule\n'
                   'module reference_top(input a,output y);\n'
                   'reference_opaque u_opaque(.a(a),.y(y)); endmodule\n')
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'reference_top'})
    c = context()
    context_path = project / 'context.json'
    put(context_path, c)
    old = {k: os.environ.get(k) for k in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV)}
    os.environ[flow109.CONTEXT_ENV] = str(context_path)
    attempt = flow109._new_attempt(project, c)
    os.environ[flow109.ATTEMPT_ENV] = str(attempt)
    try:
        p0 = runner._d10_p0_native(project)
        assert p0['status'] == 'PASS', p0
        binding = runner._validate_d10_p0_consumer(project, p0)
        assert binding['status'] == 'PASS', binding
        observed = metrics.observe_d10_frontend_metrics(project, c, p0)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    graph = json.loads((project / p0['elaboration_path']).read_text())
    instances = metrics._d10_blackbox_instances(graph, 'reference_top')
    expected = []  # Test-only oracle. Never an expected-blackbox authority for SPM.
    assert instances == ['u_opaque'], {'actual': instances, 'expected_native_instances': ['u_opaque']}
    assert observed['obligations'][1]['observed_value'] is None
    assert observed['obligations'][1]['reason'] == 'EXPECTED_BLACKBOX_AUTHORITY_MISSING'
    produced = project / p0['producer_result']['path']
    native_result = json.loads(produced.read_text())
    facts = {'kind': 'native test reference, not tool qualification or row acceptance',
        'p0': p0, 'binding': binding, 'metric_observation': observed,
        'test_only_expected_blackboxes': expected, 'observed_blackboxes': instances,
        'unexpected_blackboxes': len(set(instances) - set(expected)),
        'reference_comparison': {'elaboration_errors': 'PASS', 'unexpected_blackboxes': 'FAIL'},
        'native_result': {'path': str(produced), 'sha256': sha(produced)},
        'source_model': {'path': str(rtl), 'sha256': sha(rtl)},
        'prior_references': []}
    prior = os.environ.get('FLOW109_D10_PRIOR_OWNER')
    if prior:
        for kind in ('positive', 'undefined_module'):
            path = next((Path(prior) / 'head-native-artifacts').glob(
                'd10-' + kind + '*/reports/flow109/default_rows/D10.json'))
            old_row = json.loads(path.read_text())
            old_p0 = old_row['evidence']['p0_native']
            assert old_p0['tool_sha256'] == p0['tool_sha256']
            assert old_p0['producer_source_sha256'] == p0['producer_source_sha256']
            facts['prior_references'].append({'control': kind, 'path': str(path),
                'sha256': sha(path), 'native_status': old_p0['status'],
                'metric': old_row['evidence']['native_metric_observation'],
                'binary_and_producer_bytes_unchanged': True})
    fact_ref = put(root / 'native-reference-facts.json', facts)
    records = []
    for use in c['resolved_row']['tool_uses']:
        tool = use['tool_id']
        binary = Path(shutil.which(use['executable_name'])).resolve()
        version = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True).stdout.strip()
        key = 'Yosys.JsonHeader' if tool == 'yosys' else 'Verilator.Lint'
        config = put(root / ('config-' + tool + '.json'), {
            'purpose': use['purpose'], 'native_steps': use['native_steps'],
            'actual_command': native_result['tools'][key]['argv'],
            'producer_source_sha256': p0['producer_source_sha256'],
            'runner_source_sha256': p0['runner_source_sha256'],
            'image_id': p0['image_id'], 'test_model': facts['source_model']})
        identity = {'use_id': use['use_id'], 'tool_id': tool, 'version': version,
            'build_sha256': sha(binary), 'executable': {'path': str(binary), 'sha256': sha(binary)},
            'config': config,
            'pdk': {'applicable': False, 'reason': 'RTL structural purpose consumes no technology models'},
            'deck': {'applicable': False, 'reason': 'Native RTL frontend has no physical rule deck'},
            'corner': {'applicable': False, 'reason': 'No electrical corner is measured by this purpose'},
            'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                'checked_metrics': ['base_04.elaboration_errors', 'base_04.unexpected_blackboxes']
                    if tool == 'yosys' else ['base_04.elaboration_errors'],
                'blackbox_census': 'Yosys native model plus existing Python reader'
                    if tool == 'yosys' else 'not measured by Verilator; composite census uses Yosys',
                'model_identity': {'image_id': p0['image_id'], 'source_model': facts['source_model']}}}
        assert identity['build_sha256'] == p0['tool_sha256'][tool]
        records.append({'use_id': use['use_id'], 'status': 'NOT_MEASURED',
            'identity': identity, 'reference_evidence': [fact_ref]})
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records}
    registry_path = root / 'qualifications.json'
    put(registry_path, registry)
    return {'root': root, 'project': project, 'registry': registry,
            'registry_path': str(registry_path), 'facts': facts}


def runtime(registry):
    return [{**copy.deepcopy(row['identity']), 'qualification_sha256': admission.canonical_sha(row)}
            for row in registry['uses']]


def test_native_blackbox_reference_uses_only_test_expected_set(reference):
    assert reference['facts']['unexpected_blackboxes'] == 1
    assert all(row['status'] == 'NOT_MEASURED' for row in reference['registry']['uses'])
    with pytest.raises(admission.AdmissionRefusal, match='QUALIFICATION_NOT_MEASURED'):
        admission.require_admission(reference['project'], context(
            runtime(reference['registry']), reference['registry_path']))


@pytest.mark.parametrize('damage,reason', [
    ('runtime_missing', 'QUALIFICATION_RUNTIME_ABSENT'),
    ('registry_missing', 'QUALIFICATION_REGISTRY_ABSENT'),
    ('wrong_purpose', 'QUALIFICATION_SCOPE_MISMATCH'),
    ('forged_build', 'QUALIFICATION_BUILD_MISMATCH'),
    ('stale_digest', 'QUALIFICATION_STALE'),
    ('stale_reference', 'QUALIFICATION_STALE'),
])
def test_d10_bad_qualification_claims_refuse(reference, tmp_path, damage, reason):
    claimed = copy.deepcopy(reference['registry'])
    # Deliberately forged attack fixture ONLY. It must refuse and is never
    # exported as the genuine reference registry or credited as qualification.
    for row in claimed['uses']:
        row['status'] = 'QUALIFIED'
    if damage == 'wrong_purpose':
        claimed['uses'][0]['identity']['semantics']['purpose'] = 'D03.technology'
    if damage == 'forged_build':
        claimed['uses'][0]['identity']['build_sha256'] = '0' * 64
    if damage == 'stale_reference':
        claimed['uses'][0]['reference_evidence'][0]['sha256'] = '0' * 64
    identities = runtime(claimed)
    if damage == 'stale_digest':
        identities[0]['qualification_sha256'] = '0' * 64
    path = tmp_path / 'TEST_ONLY_INVALID_CLAIM.json'
    put(path, claimed)
    c = context(None if damage == 'runtime_missing' else identities,
                None if damage == 'registry_missing' else str(path))
    with pytest.raises(admission.AdmissionRefusal) as caught:
        admission.require_admission(reference['project'], c)
    assert caught.value.code == reason, caught.value.report
    put(reference['root'] / ('refusal-' + damage + '.json'), caught.value.report)
    path.unlink()
