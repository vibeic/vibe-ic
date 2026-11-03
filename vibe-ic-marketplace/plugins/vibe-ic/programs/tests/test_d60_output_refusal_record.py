import json
from pathlib import Path

import pytest

import _path_layout
import execution_modes
import execution_policy
import flow_compliance_check as fcc
import release_docs_check as release


GDS = 'phase3/stage4/gds/*.gds'


def test_unbound_output_is_recorded_and_attributed_without_selecting_a_gds(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    row = {'id': '37', 'name': 'gds', 'stage': 'stage4', 'required_outputs': [GDS]}
    result = fcc.check_step(tmp_path, row, {})
    assert result.status == 'NOT_MEASURED'
    fcc._emit_step_output_record(tmp_path, row, result)
    record = json.loads(_path_layout.step_output_record_path(tmp_path, '37').read_text())
    assert record['unresolved'] == [GDS]
    assert record['missing'] == [] and record['unusable'] == []
    assert release.upstream_blockage_is_about(tmp_path, '37', 'phase3/stage4/gds/chip.gds')[0]
    assert not release.upstream_blockage_is_about(tmp_path, '37', 'reports/unrelated.json')[0]


@pytest.mark.parametrize('status,reason', [('PASS', 'OUTPUT_TOP_UNBOUND'),
                                          ('FAIL', 'independent failure')])
def test_unbound_resolution_alone_does_not_forge_an_upstream_reason(tmp_path, monkeypatch, status, reason):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    result = type('Result', (), {'status': status, 'reasons': [reason]})()
    fcc._emit_step_output_record(tmp_path, {'id': '37', 'required_outputs': [GDS]}, result)
    assert not release.upstream_blockage_is_about(tmp_path, '37', 'phase3/stage4/gds/chip.gds')[0]


def test_fixed_inputs_refuses_unbound_top_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    runtime = {'project': tmp_path, 'parameters': {}, 'policy': {}}
    with pytest.raises(execution_modes.Refusal) as caught:
        execution_policy._fixed_inputs(runtime, '38')
    assert caught.value.code == 'OUTPUT_TOP_UNBOUND'


def test_fixed_inputs_binds_the_requested_top(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    owned = tmp_path / 'phase3/stage4/gds/chip.gds'
    sibling = owned.with_name('other.gds')
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b'owned')
    sibling.write_bytes(b'other')
    runtime = {'project': tmp_path, 'parameters': {'top': 'chip'}, 'policy': {}}
    inputs = execution_policy._fixed_inputs(runtime, '38')
    assert inputs['phase3/stage4/gds/chip.gds'] == owned
    assert 'phase3/stage4/gds/other.gds' not in inputs


def test_unreadable_glob_keeps_output_record_best_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    row = {'id': '37', 'name': 'gds', 'stage': 'stage4', 'required_outputs': [GDS]}
    result = fcc.check_step(tmp_path, row, {})
    monkeypatch.setattr(Path, 'glob', lambda *args: (_ for _ in ()).throw(OSError('unreadable')))
    fcc._emit_step_output_record(tmp_path, row, result)
    assert release.upstream_blockage_is_about(tmp_path, '37', 'phase3/stage4/gds/chip.gds')[0]


def test_release_docs_remain_unmeasured_for_an_unbound_upstream(tmp_path, monkeypatch):
    import test_a_producers_stated_refusal_is_not_a_documentation_defect as fixture

    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    fixture._blocked_upstream(tmp_path)
    fixture._step_status(tmp_path, '37', 'NOT_MEASURED')
    row = {'id': '37', 'name': 'gds', 'stage': 'stage4', 'required_outputs': [GDS]}
    result = fcc.check_step(tmp_path, row, {})
    assert result.status == 'NOT_MEASURED'
    fcc._emit_step_output_record(tmp_path, row, result)
    audit = release.run_audit(tmp_path, 'ic')
    assert audit.verdict_tier == 'NOT_MEASURED'
    assert audit.summary['upstream_blockage']['zzdie']['blocked'] is True


@pytest.mark.parametrize('invocation', [None, '', 'earlier', 'current'])
def test_unresolved_output_requires_the_current_invocation(tmp_path, monkeypatch, invocation):
    import test_a_producers_stated_refusal_is_not_a_documentation_defect as fixture

    monkeypatch.setenv('VIBEIC_FCC_INVOCATION', 'current')
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    fixture._blocked_upstream(tmp_path)
    fixture._step_status(tmp_path, '37', 'NOT_MEASURED')
    row = {'id': '37', 'required_outputs': [GDS]}
    result = fcc.check_step(tmp_path, row, {})
    fcc._emit_step_output_record(tmp_path, row, result)
    path = _path_layout.step_output_record_path(tmp_path, '37')
    record = json.loads(path.read_text())
    record.pop('invocation')
    if invocation is not None:
        record['invocation'] = invocation
    path.write_text(json.dumps(record))

    assert release.upstream_blockage_is_about(
        tmp_path, '37', 'phase3/stage4/gds/chip.gds')[0] == (invocation == 'current')
    assert release.run_audit(tmp_path, 'ic').verdict_tier == (
        'NOT_MEASURED' if invocation == 'current' else 'FAIL')
