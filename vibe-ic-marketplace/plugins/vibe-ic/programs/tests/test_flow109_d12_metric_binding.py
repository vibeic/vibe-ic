"""D12 consumer controls. Real retained graphs + exact root requirements.

Per-use executable/qualification records below are SOFTWARE fixtures isolating
normal admission/metric behavior. They grant no native or product credit.
No Yosys/model/formal execution is launched by this module.
"""
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
import _cdc_netlist as native
import design_one_shot_runner as owner

REF = Path(os.environ.get('FLOW109_D12_REFERENCE', '/reference'))
NATIVE = Path('/native-reference')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + '\n')
    return {'path': str(path), 'sha256': sha(path)}


def context():
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
        if p['name'] == 'Small digital IC without DFT'))
    return flow109.execution_context(flow109.resolve_plan(features), 'D12', 'D12')


def qualified_context(p):
    """Explicit software isolation of unassigned root per-use qualification."""
    cfg = p / 'input/qualification/D12/config.json'
    put(cfg, {'purpose': metrics.D12_PURPOSE, 'native_steps': list(metrics.D12_STEPS),
              'model_sources': metrics.d12_model_sources()})
    proof = p / 'input/qualification/D12/SOFTWARE_ONLY.json'
    put(proof, {'scope': 'SOFTWARE_FIXTURE_NOT_NATIVE_QUALIFICATION'})
    executable = Path(shutil.which('python3')).resolve()
    identity = {'use_id': 'flow109.D12.default.python3', 'tool_id': 'python3',
        'version': sys.version, 'build_sha256': sha(executable),
        'executable': {'path': str(executable), 'sha256': sha(executable)},
        'config': {'path': str(cfg.relative_to(p)), 'sha256': sha(cfg)},
        'pdk': {'applicable': False, 'reason': 'decoded RTL structural reader'},
        'deck': {'applicable': False, 'reason': 'no physical deck'},
        'corner': 'STRUCTURAL', 'semantics': {'purpose': 'D12.default', 'native_steps': list(metrics.D12_STEPS)}}
    entry = {'use_id': identity['use_id'], 'status': 'QUALIFIED', 'identity': identity,
             'reference_evidence': [{'path': str(proof.relative_to(p)), 'sha256': sha(proof)}]}
    registry = p / 'input/qualification/D12/registry.json'
    put(registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [entry]})
    base = context()
    return flow109.execution_context(flow109.resolve_plan(base['features']), 'D12', 'D12',
        runtime_tool_uses=[{**identity, 'qualification_sha256': admission.canonical_sha(entry)}],
        qualification_registry=str(registry.relative_to(p)))


@pytest.fixture
def case(tmp_path):
    p = tmp_path / 'project'
    shutil.copytree(REF, p)
    return p, qualified_context(p)


def test_d12_complete_root_bound_population_and_source_alias(case):
    p, c = case
    r = metrics.accept_d12(p, c)
    assert r['status'] == 'PASS', r
    assert [o['status'] for o in r['obligations']] == ['PASS'] * 3
    assert r['observed']['population']['source_q_bits_examined'] == 66
    assert len(r['obligations'][0]['observed_value']) == 14
    assert r['observed']['producer']['source_root'] != str(p)  # Original launch is preserved.
    assert r['subject']['roles']['sha256'] == sha(p / 'reports/audit/ai_judgements/3.json')


@pytest.mark.parametrize('changed', ['rtl', 'graph', 'role', 'source_doc', 'model_config', 'missing_port', 'alias'])
def test_d12_currentness_and_authority_refusals(case, changed):
    p, c = case
    source = p / 'input/flow109/D12/source.json'
    if changed in ('missing_port', 'alias'):
        body = json.loads(source.read_bytes())
        if changed == 'missing_port':
            body['input_domains'].pop('scan_in')
        else:
            body['state_aliases'] = {'pr': 'not_a_native_alias'}
        put(source, body)
        # SOFTWARE negative copies rebind authority to expose the actual
        # consuming-layer refusal, not merely a missing source hash.
        for name in ('clock_reset_crossing_census', 'cdc_protocol_results'):
            path = p / ('requirements/base_06/' + name + '.json')
            doc = json.loads(path.read_bytes()); ref = {'path': str(source.relative_to(p)), 'sha256': sha(source)}
            doc['approval']['source_reference'] = ref
            if 'validated_absence' in doc: doc['validated_absence']['source_reference'] = ref
            put(path, doc)
    else:
        path = {'rtl': p / 'phase2/stage1/rtl/spm.v', 'graph': p / native.NETLIST_REL,
                'role': p / 'reports/audit/ai_judgements/3.json',
                'source_doc': p / 'input/docs/L3_external_interface.md',
                'model_config': p / 'input/qualification/D12/config.json'}[changed]
        path.write_text(path.read_text() + '\n ')
    r = metrics.accept_d12(p, c)
    assert r['status'] == 'NOT_MEASURED', r
    if changed == 'alias':
        assert r['obligations'][0]['reason'] == 'D12_STATE_ALIAS_UNPROVEN'
    elif changed == 'missing_port':
        assert r['reason'] == 'D12_INPUT_DOMAINS_INCOMPLETE'


@pytest.mark.parametrize('change', ['missing', 'unvalidated', 'nonempty', 'foreign_source'])
def test_d12_protocol_absence_is_independent_obligation(case, change):
    p, c = case
    path = p / 'requirements/base_06/cdc_protocol_results.json'
    if change == 'missing': path.unlink()
    else:
        body = json.loads(path.read_bytes())
        if change == 'unvalidated': body.pop('validated_absence')
        elif change == 'nonempty': body['required_items'] = [{'name': 'fifo', 'from_clock': 'a', 'to_clock': 'b'}]
        else: body['approval']['source_reference']['sha256'] = '0' * 64
        put(path, body)
    r = metrics.accept_d12(p, c)
    assert r['status'] == 'NOT_MEASURED', r
    assert [o['status'] for o in r['obligations'][:2]] == ['PASS', 'PASS']
    assert r['obligations'][2]['status'] == 'NOT_MEASURED'


def test_d12_no_qualification_is_not_a_population_pass(case):
    p, _c = case
    r = metrics.accept_d12(p, context())
    assert r['status'] == 'NOT_MEASURED' and r['reason'] == 'QUALIFICATION_RUNTIME_ABSENT', r


def test_d12_omitted_source_state_refuses_even_with_resealed_software_authority(case):
    p, c = case
    sp = p / 'input/flow109/D12/source.json'
    source = json.loads(sp.read_bytes())
    source['clock_reset_crossing_census']['required_items'] = [r for r in
        source['clock_reset_crossing_census']['required_items'] if r['name'] != 'c']
    put(sp, source)
    for name in ('clock_reset_crossing_census', 'cdc_protocol_results'):
        path = p / ('requirements/base_06/' + name + '.json')
        body = json.loads(path.read_bytes())
        body['required_items'] = source[name]['required_items']
        reference = {'path': str(sp.relative_to(p)), 'sha256': sha(sp)}
        body['approval']['source_reference'] = reference
        if 'validated_absence' in body: body['validated_absence']['source_reference'] = reference
        put(path, body)
    result = metrics.accept_d12(p, c)
    assert result['status'] == 'NOT_MEASURED', result
    assert result['obligations'][0]['reason'] == 'D12_CENSUS_INCOMPLETE'


def test_d12_actual_owner_and_canonical_writer(case, monkeypatch):
    p, c = case
    destination = p / 'reports/flow109'
    destination.mkdir(exist_ok=True)
    cp = destination / 'context.json'; put(cp, c)
    attempt = flow109._new_attempt(p, c)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(cp))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    assert owner._publish_d12_owner(p, c) == 0
    result = json.loads((attempt / 'result.json').read_bytes())
    assert result['default_row_status'] == 'PASS', result
    assert result['components'][0]['completed'] is True
    assert result['delivery_accepted'] is False


def test_d12_owner_publication_rereads_changed_actual_source(case, monkeypatch):
    p, c = case
    cp = p / 'reports/flow109/context.json'; put(cp, c)
    attempt = flow109._new_attempt(p, c)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(cp))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    seen = []
    def observe(frame, event, value):
        if event == 'return' and frame.f_code is metrics.accept_d12.__code__:
            seen.append(value['status'])
            if len(seen) == 1 and value['status'] == 'PASS':
                rtl = p / 'phase2/stage1/rtl/spm.v'
                rtl.write_text(rtl.read_text() + '\n// actual source changed after first consumer\n')
    sys.setprofile(observe)
    try:
        assert owner._publish_d12_owner(p, c) == 2
    finally:
        sys.setprofile(None)
    assert seen == ['PASS', 'NOT_MEASURED']
    result = json.loads((attempt / 'result.json').read_bytes())
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['components'][0]['completed'] is False


def test_d12_applicability_does_not_add_lint_or_power_intent():
    c = context(); row = c['resolved_row']
    assert 'D11' not in row['acceptance_deps']
    assert c['features']['has_power_intent'] is False
    assert row['profile']['dispatch']['owner_entry_step'] == row['profile']['dispatch']['owner_exit_step'] == '3'
    assert 'D05' not in {x['id'] for x in flow109.resolve_plan(c['features'])['rows']}


@pytest.mark.parametrize('case_name,rule', [('reset_cycle', 'CIRCULAR_RESET_DEPENDENCY'),
                                         ('async_unsync', 'ASYNC_INPUT_NO_SYNC')])
def test_d12_genuine_native_failure_survives_unmeasured_census_protocol(tmp_path, case_name, rule):
    p = tmp_path / 'native-control'
    shutil.copytree(NATIVE / 'fixtures' / case_name, p)
    subject = metrics.d12_subject(p)
    nl = native.load(p / native.NETLIST_REL)
    domains = native.clock_domains(nl)
    source = {'purpose': metrics.D12_PURPOSE, 'subject': subject,
        'source_refs': [{'path': subject['input']['files'][0]['path'], 'sha256': subject['input']['files'][0]['sha256']}],
        'input_domains': {n: {'role': 'clock' if n in domains else 'asynchronous_data',
                             'clock': n if n in domains else domains[0]}
                          for n, (d, _b) in nl.ports.items() if d == 'input'},
        'clock_reset_crossing_census': {'required_items': [{'kind': 'state', 'name': 'missing_alias', 'clock': domains[0], 'detail': '1'}]}}
    sp = p / 'input/flow109/D12/source.json'; put(sp, source)
    put(p / 'requirements/base_06/clock_reset_crossing_census.json', {
        'schema': metrics.AUTHORITY_SCHEMA, **source['clock_reset_crossing_census'],
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': {'path': str(sp.relative_to(p)), 'sha256': sha(sp)}}})
    c = qualified_context(p)
    r = metrics.accept_d12(p, c)
    assert r['status'] == 'FAIL', r
    assert [o['status'] for o in r['obligations']] == ['NOT_MEASURED', 'FAIL', 'NOT_MEASURED']
    assert any(x['rule'] == rule for x in r['obligations'][1]['findings'])


@pytest.mark.parametrize('change', ['zero_state', 'unknown_cell', 'undriven', 'ambiguous_driver'])
def test_d12_incomplete_graph_is_not_empty_pass(case, change):
    p, c = case
    graph = p / native.NETLIST_REL
    body = json.loads(graph.read_bytes()); mod = body['modules']['spm']
    if change == 'zero_state':
        mod['cells'] = {n: cell for n, cell in mod['cells'].items() if cell['type'] != '$dff'}
    elif change == 'unknown_cell':
        mod['cells']['unmodeled_storage'] = {'type': '$unknown_storage', 'port_directions': {}, 'connections': {}}
    elif change == 'undriven':
        next(cell for cell in mod['cells'].values() if cell['type'] == '$dff')['connections']['D'][0] = 999999
    else:
        name = next(n for n, cell in mod['cells'].items() if cell['type'] == '$dff')
        mod['cells']['second_driver'] = copy.deepcopy(mod['cells'][name])
    put(graph, body)
    # Explicit SOFTWARE malformed producer/authority records expose decoder
    # completeness, independently of the earlier output-hash refusal.
    manifest = p / native.NETLIST_MANIFEST_REL
    rec = json.loads(manifest.read_bytes()); rec['sha256']['netlist.json'] = sha(graph); put(manifest, rec)
    sp = p / 'input/flow109/D12/source.json'; source = json.loads(sp.read_bytes())
    source['subject'] = metrics.d12_subject(p); put(sp, source)
    for name in ('clock_reset_crossing_census', 'cdc_protocol_results'):
        path = p / ('requirements/base_06/' + name + '.json'); doc = json.loads(path.read_bytes())
        ref = {'path': str(sp.relative_to(p)), 'sha256': sha(sp)}
        doc['approval']['source_reference'] = ref
        if 'validated_absence' in doc: doc['validated_absence']['source_reference'] = ref
        put(path, doc)
    result = metrics.accept_d12(p, c)
    assert result['status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D12_GRAPH_INCOMPLETE', result
