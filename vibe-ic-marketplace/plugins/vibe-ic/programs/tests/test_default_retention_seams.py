"""Existing Default calls retain attempts; component PASS never becomes IC PASS."""
import inspect
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_RETENTION_SEAMS_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import execution_policy as policy
import step_preflight as preflight
import step_output_collector as versions


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})


def _saved(project, sid):
    rows = [r for r in versions._read_index(project)['steps'] if r['id'] == sid]
    assert rows, f'no retained invocation for Step {sid}'
    folder = project / 'steps' / rows[-1]['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


def _refusal(project, monkeypatch):
    monkeypatch.setattr(preflight, '_emit_repro_bundle', lambda *args: None)
    def forbidden():
        raise AssertionError('native DRC started without the declared routed DEF')
    def factory(detail, extras):
        return SimpleNamespace(name='drc', status=preflight.REFUSAL_STATUS,
                               detail=detail, extras=extras)
    return preflight.gate(project, 'phase3_one_shot_runner', 'drc', factory, forbidden)


def test_real_preflight_refusal_has_a_version_without_starting_native(tmp_path, monkeypatch):
    result = _refusal(tmp_path, monkeypatch)
    assert result.status == preflight.REFUSAL_STATUS
    _, record = _saved(tmp_path, '31')
    assert record['status'] == 'NOT_MEASURED'
    assert record['result']['producer_started'] is False
    assert record['result']['absent_inputs'] == result.extras['absent_inputs']
    assert any('routed.def' in str(i) for i in record['result']['absent_inputs'])
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '31') is None


def test_refusal_preserves_an_earlier_interrupted_output(tmp_path, monkeypatch):
    partial = tmp_path / 'reports/native.log'
    partial.parent.mkdir()
    previous = versions.begin_step(tmp_path, '1')
    partial.write_bytes(b'partial native evidence before preflight refusal')
    _refusal(tmp_path, monkeypatch)
    folder, record = _saved(tmp_path, '1')
    assert record['status'] == 'INTERRUPTED'
    partial.write_bytes(b'later working bytes')
    assert (folder / 'files/reports/native.log').read_bytes() == b'partial native evidence before preflight refusal'
    assert previous['folder'] == str(folder.relative_to(tmp_path / 'steps'))


def test_leaf_retry_keeps_each_output_and_returns_the_original_result(tmp_path):
    def leaf(project, content, *, status='PASS'):
        path = project / 'reports/native-sdc.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return SimpleNamespace(name='sdc_validation', status=status, detail='actual call',
                               output_files=[str(path)], extras={})
    retained = preflight.retained_step('8')(leaf)
    assert inspect.signature(retained) == inspect.signature(leaf)
    first = retained(tmp_path, b'first output')
    folder, record = _saved(tmp_path, '8')
    assert first.status == record['status'] == 'PASS'
    assert record['result']['step_rows'][0]['outputs'] == first.output_files
    second = retained(tmp_path, b'failed retry evidence', status='FAIL')
    second_folder, second_record = _saved(tmp_path, '8')
    assert second.status == second_record['status'] == 'FAIL'
    assert (folder / 'files/reports/native-sdc.json').read_bytes() == b'first output'
    assert (second_folder / 'files/reports/native-sdc.json').read_bytes() == b'failed retry evidence'
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '8') is None


def test_leaf_exception_keeps_partial_bytes_and_propagates(tmp_path):
    @preflight.retained_step('10')
    def leaf(project):
        path = project / 'reports/native-sta.log'
        path.parent.mkdir()
        path.write_bytes(b'partial native STA')
        raise KeyboardInterrupt('producer interrupted')
    with pytest.raises(KeyboardInterrupt, match='producer interrupted'):
        leaf(tmp_path)
    folder, record = _saved(tmp_path, '10')
    assert record['status'] == 'INTERRUPTED'
    assert (folder / 'files/reports/native-sta.log').read_bytes() == b'partial native STA'


def test_ultra_leaf_keeps_its_existing_dispatch_without_default_history(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'ultra'})
    result = object()
    @preflight.retained_step('8')
    def leaf(project):
        return result
    assert leaf(tmp_path) is result
    assert not (tmp_path / 'steps/index.json').exists()


def test_actual_early_sdc_deferral_is_retained(tmp_path, monkeypatch):
    import design_one_shot_runner as design
    import librelane_contract as ll
    monkeypatch.setattr(policy, '_ordinary_runtime', {'policy': {'mode': 'default'}})
    monkeypatch.setattr(ll, 'selected_mode', lambda *args: 'librelane')
    result = design.step_sdc_validation(tmp_path)
    assert result.status == 'NOT_MEASURED'
    assert result.extras['deferred_until'] == 'post_prelayout'
    _, record = _saved(tmp_path, '8')
    assert record['status'] == 'NOT_MEASURED'
    assert not record['canonical_pass']


def test_actual_analog_fmeda_na_is_retained_without_faking_pass(tmp_path):
    import design_one_shot_runner as design
    result = design.step_fmeda_fault_injection(tmp_path, not_applicable='no digital RTL track')
    assert result.status == 'NOT_APPLICABLE'
    _, record = _saved(tmp_path, 'FS1')
    assert record['status'] == 'NOT_APPLICABLE'
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, 'FS1') is None
