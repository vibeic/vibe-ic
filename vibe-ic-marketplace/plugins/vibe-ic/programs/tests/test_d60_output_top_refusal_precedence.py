import pytest

import execution_policy
import flow_compliance_check as fcc


GDS = 'phase3/stage4/gds/*.gds'


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    (tmp_path / 'proof.txt').write_text('synthetic independent evidence\n')
    sibling = tmp_path / 'phase3/stage4/gds/physical_cell.gds'
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b'synthetic file-presence fixture\n')
    return tmp_path


def _row(outputs, gate=None):
    row = {'id': 37, 'name': 'output refusal fixture', 'stage': 'stage4',
           'required_outputs': outputs}
    if gate is not None:
        row['gate'] = gate
    return row


@pytest.mark.parametrize('bound', [False, True])
def test_missing_top_does_not_hide_independent_gate_failure(project, monkeypatch, bound):
    if bound:
        monkeypatch.setattr(execution_policy, '_ordinary_runtime', {
            'project': project, 'policy': {'mode': 'default'},
            'parameters': {'top': 'logical'}})
        (project / 'phase3/stage4/gds/logical.gds').write_bytes(
            b'synthetic file-presence fixture\n')
    result = fcc.check_step(project, _row(
        [GDS, 'proof.txt'], {'files_exist': ['missing.txt']}), {})
    assert result.status == 'FAIL', result
    assert any('missing.txt' in reason for reason in result.reasons)


@pytest.mark.parametrize('other,expected', [('missing.txt', 'FAIL'),
                                           ('proof.txt', 'NOT_MEASURED')])
@pytest.mark.parametrize('unknown_first', [False, True])
def test_all_of_preserves_independent_failure(project, other, expected, unknown_first):
    leaves = [{'files_exist': [GDS]}, {'files_exist': [other]}]
    if not unknown_first:
        leaves.reverse()
    result = fcc.check_step(project, _row(['proof.txt'], {'all_of': leaves}), {})
    assert result.status == expected, result
    if expected == 'FAIL':
        assert any('missing.txt' in reason for reason in result.reasons)
    else:
        assert any('OUTPUT_TOP_UNBOUND' in reason for reason in result.reasons)


@pytest.mark.parametrize('other,expected', [('missing.txt', 'NOT_MEASURED'),
                                           ('proof.txt', 'PASS')])
@pytest.mark.parametrize('unknown_first', [False, True])
def test_list_any_of_requires_a_decisive_pass(project, other, expected, unknown_first):
    leaves = [{'files_exist': [GDS]}, {'files_exist': [other]}]
    if not unknown_first:
        leaves.reverse()
    result = fcc.check_step(project, _row(['proof.txt'], {'any_of': leaves}), {})
    assert result.status == expected, result


@pytest.mark.parametrize('other,expected', [('missing.txt', 'NOT_MEASURED'),
                                           ('proof.txt', 'PASS')])
@pytest.mark.parametrize('or_entry', [False, True])
def test_files_exist_any_of_keeps_unknown_and_pass(project, other, expected, or_entry):
    patterns = [f'{GDS} OR {other}'] if or_entry else [GDS, other]
    result = fcc.check_step(project, _row(
        ['proof.txt'], {'files_exist': patterns, 'any_of': True}), {})
    assert result.status == expected, result


@pytest.mark.parametrize('other,expected', [('missing.txt', 'FAIL'),
                                           ('proof.txt', 'NOT_MEASURED')])
def test_files_exist_all_of_retains_definite_failure(project, other, expected):
    result = fcc.check_step(project, _row(
        ['proof.txt'], {'files_exist': [GDS, other]}), {})
    assert result.status == expected, result


@pytest.mark.parametrize('gate', [None, {'files_exist': ['proof.txt']}])
@pytest.mark.parametrize('outputs', [[GDS], [GDS, 'proof.txt']])
def test_unknown_output_is_unmeasured_without_crediting_sibling(project, gate, outputs):
    result = fcc.check_step(project, _row(outputs, gate), {})
    assert result.status == 'NOT_MEASURED', result
    assert 'phase3/stage4/gds/physical_cell.gds' not in result.evidence
    assert result.output_binding['n_unresolved'] == 1
    entry = next(item for item in result.output_binding['specs'] if item['spec'] == GDS)
    assert entry['satisfied'] is None
    assert entry['mode'] == 'unresolved'
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in result.reasons)
    assert not any('required_outputs missing' in reason for reason in result.reasons)


def test_unknown_output_does_not_hide_definitely_missing_output(project):
    result = fcc.check_step(project, _row([GDS, 'missing.txt']), {})
    assert result.status == 'FAIL', result
    assert any('missing.txt' in reason for reason in result.reasons)


def test_all_failed_any_of_remains_failure(project):
    result = fcc.check_step(project, _row(['proof.txt'], {'any_of': [
        {'files_exist': ['missing.txt']}, {'files_exist': ['other-missing.txt']}]}), {})
    assert result.status == 'FAIL', result


def test_conflicting_explicit_top_still_raises(project, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', {
        'project': project, 'parameters': {'top': 'logical'}})
    with pytest.raises(ValueError, match='OUTPUT_TOP_CONFLICT'):
        fcc.check_step(project, _row([GDS]), {}, parameters={'top': 'physical_cell'})
