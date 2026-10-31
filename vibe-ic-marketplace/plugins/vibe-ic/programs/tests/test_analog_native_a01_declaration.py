"""A01 must check the declaration it actually extracted, without vacuous credit."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import analog_native_flow as native


@pytest.fixture
def canonical_a01(tmp_path):
    """SYNTHETIC qualification/dependencies; real Python producer/checker, no IC proof."""
    from types import SimpleNamespace
    from test_flow109_metric_acceptance import _approved_case
    import flow109
    import librelane_contract as contract
    manifest, _ = _approved_case(tmp_path)
    # Include a neutral DUT identity without running any circuit simulator.
    dut = tmp_path / 'phase3/analog/regulator_alpha/regulator_alpha.sp'
    dut.parent.mkdir(parents=True, exist_ok=True)
    dut.write_text('* synthetic source identity, never simulated\n')
    for step in ('D01', 'D02'):
        path = tmp_path / f'reports/flow109/default_rows/{step}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'step_id': step, 'default_row_status': 'PASS',
                                    'completed': True, 'scope': 'SYNTHETIC source control'}))
    report = native.run_window(tmp_path, SimpleNamespace(
        entry_step='A01', exit_step='A01', container='', transport='HOST',
        image=contract.resolve_image(tmp_path, record=False)), features=manifest['features'])
    assert report['window_verdict'] == 'PASS', report
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'A01', 'A01',
        runtime_tool_uses=manifest['runtime_tool_uses'], qualification_registry='qualifications.json')
    assert context['resolved_row']['profile']['dispatch']['adapter'] == 'analog_native_flow'
    component = {'step_id': 'A01', 'context_sha256': context['context_sha256'],
                 'component_status': 'PASS', 'native_results': report,
                 'flow109_acceptance': 'NOT_MEASURED'}
    return tmp_path, context, component


def test_canonical_a01_normal_owner_completes_only_current_declared_metrics(canonical_a01):
    import flow109
    project, context, component = canonical_a01
    row = flow109._selected_step_result(project, context, component, native)
    assert row['default_row_status'] == 'PASS' and row['completed'] is True, row
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and not row['delivery_accepted']
    assert [m['status'] for m in row['metric_acceptance']['obligations']] == ['PASS', 'PASS']


@pytest.mark.parametrize('damage', ['missing_D01', 'missing_qualification', 'stale_DUT',
    'missing_block', 'forged_PASS', 'missing_spec_field', 'foreign_authority', 'unattributed_source',
    'declared_population_gap', 'missing_declaration'])
def test_canonical_a01_normal_owner_refuses_incomplete_or_foreign_evidence(canonical_a01, damage):
    import flow109
    project, context, component = canonical_a01
    report = component['native_results']
    if damage == 'missing_D01':
        (project / 'reports/flow109/default_rows/D01.json').unlink()
    elif damage == 'missing_qualification':
        (project / 'qualifications.json').unlink()
    elif damage == 'stale_DUT':
        (project / 'phase3/analog/regulator_alpha/regulator_alpha.sp').write_text('* changed source\n')
    elif damage == 'missing_block':
        report['steps'] = []
    elif damage == 'missing_declaration':
        (project / 'phase3/analog/analog_block_list.json').unlink()
    elif damage == 'forged_PASS':
        report['steps'][0]['executions'] = []
    elif damage in ('missing_spec_field', 'unattributed_source'):
        path = project / 'phase3/analog/regulator_alpha/spec.json'
        body = json.loads(path.read_text())
        if damage == 'missing_spec_field':
            body['specs'] = []
        else:
            body['_provenance']['ai_handoff'] = {'reason': 'unattributed required source fields'}
        path.write_text(json.dumps(body))
        report['steps'][0]['output_views'][str(path)] = native._sha(path)
    elif damage == 'declared_population_gap':
        path = project / 'requirements/base_A1/required_measurements.json'
        body = json.loads(path.read_text())
        body['required_items'].append({'block': 'regulator_alpha', 'name': 'dropout'})
        path.write_text(json.dumps(body))
    else:
        path = project / 'requirements/base_A1/required_measurements.json'
        body = json.loads(path.read_text())
        foreign = project / 'unconsumed-foreign-requirements.md'
        foreign.write_text('foreign source, not consumed by the producer\n')
        body['approval']['source_reference'] = {'path': foreign.name, 'sha256': native._sha(foreign)}
        path.write_text(json.dumps(body))
    # Keep altered synthetic records internally consistent to exercise the
    # real semantic/readset guards, rather than only a record-copy mismatch.
    (Path(report['attempt']) / 'result.json').write_text(json.dumps(report))
    row = flow109._selected_step_result(project, context, component, native)
    assert row['default_row_status'] in ('FAIL', 'NOT_MEASURED') and not row['completed'], row
    if damage == 'declared_population_gap':
        assert row['default_row_status'] == 'FAIL', row
    if damage == 'missing_declaration':
        assert not (project / 'phase3/analog/analog_block_list.json').exists(), row
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and not row['delivery_accepted']


def _project(tmp_path):
    path = tmp_path / 'phase1/generated_docs/L5_ADI_SPEC.json'
    path.parent.mkdir(parents=True)
    blocks = [
        {'name': 'converter', 'type': 'delta_sigma', 'count': 6, 'multiplicity': 6,
         'spec': {'specs': [{'name': 'fclk', 'target': 1.0, 'unit': 'MHz'}]},
         'evidence': 'input/docs/spec.md:2'},
        {'name': 'regulator', 'type': 'ldo', 'count': 1, 'multiplicity': 1,
         'spec': {'specs': [{'name': 'Vout', 'target': 1.2, 'unit': 'V'}]},
         'evidence': 'input/docs/spec.md:3'}]
    path.write_text(json.dumps({'analog_blocks': blocks}))
    return path, blocks


def _run(root, *extra):
    cp = subprocess.run([sys.executable, str(native.HERE / 'analog_one_shot_runner.py'),
                         str(root), '--flow', '109', '--entry-step', 'A01',
                         '--exit-step', 'A01', '--container', '', *extra],
                        capture_output=True, text=True)
    report = root / 'reports/analog_native/status.json'
    observed = {'rc': cp.returncode, 'stdout': cp.stdout, 'stderr': cp.stderr,
                'report': json.loads(report.read_text()) if report.is_file() else None}
    (root / 'OBSERVATION.json').write_text(json.dumps(observed, indent=2))
    return observed


def _list(root, blocks, phase='phase3', **metadata):
    path = root / phase / 'analog/analog_block_list.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'blocks': blocks, 'block_count': len(blocks), **metadata}))
    return path


def test_l5_fallback_reaches_nonvacuous_actual_a01_checker(tmp_path):
    l5, blocks = _project(tmp_path)
    observed = _run(tmp_path)
    assert (observed['rc'], observed['report']['window_verdict']) == (0, 'PASS'), observed
    declaration = json.loads((tmp_path / 'phase3/analog/analog_block_list.json').read_text())
    assert declaration['blocks'] == blocks
    assert declaration['block_count'] == 2
    assert declaration['_provenance']['input'] == {
        'path': 'phase1/generated_docs/L5_ADI_SPEC.json',
        'sha256': hashlib.sha256(l5.read_bytes()).hexdigest()}
    assert [r['status'] for r in observed['report']['steps']] == ['PASS', 'PASS']
    for row in observed['report']['steps']:
        assert [e['returncode'] for e in row['executions']] == [0, 0]
        assert 'VACUOUS_PASS' not in row['executions'][-1]['stdout']
        assert 'PASS' in row['executions'][-1]['stdout']


def test_subset_keeps_full_declared_population(tmp_path):
    _, blocks = _project(tmp_path)
    observed = _run(tmp_path, '--blocks', 'regulator')
    assert (observed['rc'], observed['report']['window_verdict']) == (0, 'PASS'), observed
    declaration = json.loads((tmp_path / 'phase3/analog/analog_block_list.json').read_text())
    assert declaration['blocks'] == blocks and declaration['block_count'] == 2
    assert [r['block'] for r in observed['report']['steps']] == ['regulator']


@pytest.mark.parametrize('phase', ['phase1', 'phase3'])
def test_existing_canonical_authority_is_used_without_rewrite(tmp_path, phase):
    _, blocks = _project(tmp_path)
    path = _list(tmp_path, blocks, phase, authority='existing declared input')
    original = path.read_bytes()
    observed = _run(tmp_path)
    assert (observed['rc'], observed['report']['window_verdict']) == (0, 'PASS'), observed
    assert path.read_bytes() == original
    if phase == 'phase1':
        assert not (tmp_path / 'phase3/analog/analog_block_list.json').exists()


@pytest.mark.parametrize('fault', ['malformed', 'wrong_shape', 'wrong_count', 'stale',
                                 'conflicting_roots', 'conflicting_l5', 'conflicting_spec', 'missing_source',
                                 'malformed_source'])
def test_invalid_declaration_is_not_replaced_or_accepted(tmp_path, fault):
    l5, blocks = _project(tmp_path)
    path = None
    if fault in ('missing_source', 'malformed_source'):
        l5.unlink() if fault == 'missing_source' else l5.write_text('[]')
    else:
        path = _list(tmp_path, blocks)
        if fault == 'malformed':
            path.write_text('{')
        elif fault == 'wrong_shape':
            path.write_text('{"blocks": [null]}')
        elif fault == 'wrong_count':
            body = json.loads(path.read_text()); body['block_count'] = 99
            path.write_text(json.dumps(body))
        elif fault == 'stale':
            body = json.loads(path.read_text()); body['_provenance'] = {
                'input': {'path': 'phase1/generated_docs/L5_ADI_SPEC.json', 'sha256': 'a' * 64}}
            path.write_text(json.dumps(body))
        elif fault == 'conflicting_roots':
            _list(tmp_path, blocks[:1], 'phase1')
        elif fault == 'conflicting_spec':
            body = json.loads(path.read_text()); body['blocks'][0]['spec']['specs'][0]['target'] = 2.0
            path.write_text(json.dumps(body))
        else:
            body = json.loads(path.read_text()); body['blocks'][0]['count'] = 3
            path.write_text(json.dumps(body))
    original = path.read_bytes() if path else None
    observed = _run(tmp_path)
    assert observed['rc'] == 2, observed
    assert observed['report'] is None, observed
    if path:
        assert path.read_bytes() == original
    assert not list((tmp_path / 'phase3/analog').glob('*/spec.json'))


@pytest.mark.parametrize('alias,expected_rc', [('ldo', 0), ('opamp', 2)])
def test_actual_producer_type_alias_is_bound_before_extraction(tmp_path, alias, expected_rc):
    # Exact independent TEST_ONLY CLI carrier; no model or IC qualification.
    l5 = {'analog_blocks': [{'name': 'regulator', 'type': 'ldo', 'count': 1,
        'multiplicity': 1, 'spec': {'specs': [
            {'name': 'Vout', 'target': 1.2, 'unit': 'V'}]},
        'evidence': 'TEST_ONLY declared L5 numeric input'}]}
    source = tmp_path / 'phase1/generated_docs/L5_ADI_SPEC.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(l5, indent=2) + '\n')
    block = dict(l5['analog_blocks'][0])
    block.pop('type')
    block['block_type'] = alias
    declaration = _list(tmp_path, [block])
    original = declaration.read_bytes()
    observed = _run(tmp_path)
    assert observed['rc'] == expected_rc, observed
    assert declaration.read_bytes() == original
    spec = tmp_path / 'phase3/analog/regulator/spec.json'
    if expected_rc == 0:
        assert observed['report']['window_verdict'] == 'PASS'
        assert json.loads(spec.read_text())['block_type'] == 'ldo'
        assert 'VACUOUS_PASS' not in observed['report']['steps'][0]['executions'][-1]['stdout']
    else:
        assert observed['report'] is None
        assert 'conflicting analog block declarations' in observed['stderr']
        assert not spec.exists()
