"""Actual attested D10 producer/consumer transport; no native-process doubles."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

import flow109
import flow109_metric_acceptance as metrics
import vibe_ic_one_shot_runner as runner

pytestmark = pytest.mark.skipif(
    not os.environ.get('VIBEIC_LIBRELANE_LOCAL_ATTESTATION')
    or any(not shutil.which(t) for t in ('yosys', 'verilator')),
    reason='actual local image attestation and native frontends required')


@pytest.fixture(scope='module')
def owner_cases(tmp_path_factory):
    cache = {}
    previous = {key: os.environ.get(key) for key in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV)}

    def case(kind):
        if kind in cache:
            return cache[kind]
        project = tmp_path_factory.mktemp('d10-' + kind)
        supplied = os.environ.get('FLOW109_D10_CONTROL_INPUTS')
        if supplied:
            source = Path(supplied) / kind
            for rel in ('phase2/stage1/rtl', 'phase1/generated_docs'):
                shutil.copytree(source / rel, project / rel)
        else:
            rtl = project / 'phase2/stage1/rtl/neutral.v'
            rtl.parent.mkdir(parents=True)
            defect = 'D10_UNDEFINED_MODULE u_missing();' if kind == 'undefined_module' else ''
            rtl.write_text('module neutral(input a,output y);assign y=a;' + defect + 'endmodule\n')
            doc = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
            doc.parent.mkdir(parents=True)
            doc.write_text(json.dumps({'top_module': 'neutral'}))
        # Diagnostic row selection only: never an approved D01 declaration.
        features = next(r['features'] for r in flow109.load_registry()['reference_profiles']
                        if r['name'] == 'Small digital IC without DFT')
        context = flow109.execution_context(flow109.resolve_plan(copy.deepcopy(features)), 'D10', 'D10')
        context_path = project / 'context.json'
        context_path.write_text(json.dumps(context))
        os.environ[flow109.CONTEXT_ENV] = str(context_path)
        attempt = flow109._new_attempt(project, context)
        os.environ[flow109.ATTEMPT_ENV] = str(attempt)
        result = runner._finish_d10_unimplemented_owner(project, run_p0=True)
        value = {'project': project, 'context': context, 'attempt': attempt, 'result': result,
                 'p0': result['evidence']['p0_native']}
        cache[kind] = value
        return value

    yield case
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_failed_native_producer_retains_current_identity(owner_cases):
    c = owner_cases('undefined_module')
    p0 = c['p0']
    assert p0['status'] == 'FAIL', {'actual': p0['status'], 'expected': 'FAIL', 'p0': p0}
    assert all(p0.get(key) for key in ('input_fingerprint', 'tool_sha256', 'producer_source_sha256',
        'runner_source_sha256', 'producer_result', 'image_id', 'cid', 'attestation_sha256'))
    identity = runner._validate_d10_p0_consumer(c['project'], p0)
    assert identity['status'] == 'PASS' and identity['native_failure']['status'] == 'FAIL'
    assert identity['qualification'] == 'NOT_MEASURED'
    observed = metrics.observe_d10_frontend_metrics(c['project'], c['context'], p0)
    assert observed['native_failure']['reason'] == 'D10_NATIVE_UNDEFINED_MODULE'
    assert observed['obligations'][0]['observed_value'] == 1
    assert observed['obligations'][1]['observed_value'] is None
    assert observed['reason'] == 'TOOL_QUALIFICATION_UNPROVEN'
    assert c['result']['verdict'] == c['result']['whole_flow_verdict'] == 'NOT_MEASURED'
    assert 'TOOL_QUALIFICATION_UNPROVEN' in c['result']['detail']
    terminal = json.loads((c['attempt'] / 'result.json').read_text())
    assert terminal['default_row_status'] == 'NOT_MEASURED'
    assert all(row['completed'] is False for row in terminal['components'])
    print(json.dumps({'native': p0, 'consumer': identity, 'metric': observed,
                      'terminal': terminal}, sort_keys=True))


def test_successful_native_observations_keep_qualification_debt(owner_cases):
    c = owner_cases('positive')
    assert c['p0']['status'] == 'PASS'
    identity = runner._validate_d10_p0_consumer(c['project'], c['p0'])
    assert identity['status'] == 'PASS' and 'native_failure' not in identity
    observed = metrics.observe_d10_frontend_metrics(c['project'], c['context'], c['p0'])
    assert [o['observed_value'] for o in observed['obligations']] == [0, 0]
    assert all(o['status'] == 'NOT_MEASURED' for o in observed['obligations'])
    assert observed['qualification'] == c['result']['verdict'] == 'NOT_MEASURED'
    assert not (c['project'] / 'input/feature-decisions.json').exists()


@pytest.mark.parametrize('field', ['tool_sha256', 'input_fingerprint', 'producer_result', 'cid', 'native_failure'])
def test_failed_native_missing_identity_never_becomes_a_measured_defect(owner_cases, field):
    c = owner_cases('undefined_module')
    packet = copy.deepcopy(c['p0'])
    packet.pop(field, None)
    observed = metrics.observe_d10_frontend_metrics(c['project'], c['context'], packet)
    assert observed['status'] == 'NOT_MEASURED' and observed['obligations'] == []
    assert 'native_failure' not in observed


def test_failed_native_stale_input_never_becomes_a_measured_defect(owner_cases):
    c = owner_cases('undefined_module')
    rtl = next((c['project'] / 'phase2/stage1/rtl').glob('*.v'))
    original = rtl.read_bytes()
    diagnostic = c['project'] / c['p0']['producer_result']['path']
    original_diagnostic = diagnostic.read_bytes()
    try:
        rtl.write_bytes(original + b'\n// controlled stale input\n')
        observed = metrics.observe_d10_frontend_metrics(c['project'], c['context'], c['p0'])
        assert observed['status'] == 'NOT_MEASURED' and observed['obligations'] == []
        assert 'native_failure' not in observed
    finally:
        rtl.write_bytes(original)
    assert diagnostic.read_bytes() == original_diagnostic


def test_packet_cannot_self_issue_tool_qualification(owner_cases):
    c = owner_cases('undefined_module')
    packet = copy.deepcopy(c['p0'])
    packet['qualification'] = 'PASS'
    observed = metrics.observe_d10_frontend_metrics(c['project'], c['context'], packet)
    assert observed['status'] == observed['qualification'] == 'NOT_MEASURED'
    assert observed['reason'] == 'TOOL_QUALIFICATION_UNPROVEN'
