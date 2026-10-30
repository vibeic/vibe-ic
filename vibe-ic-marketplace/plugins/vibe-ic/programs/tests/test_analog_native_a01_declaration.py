"""A01 must check the declaration it actually extracted, without vacuous credit."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import analog_native_flow as native


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
