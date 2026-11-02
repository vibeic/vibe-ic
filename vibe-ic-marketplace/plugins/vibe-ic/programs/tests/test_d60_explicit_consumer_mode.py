"""D60 consumer routing follows its invocation, independently of ambient policy."""
from pathlib import Path

import pytest

import execution_backend_producers as producers
import execution_backend_worker as worker
import execution_policy as policy
from test_native_backend_current_receipts import _retained_default_stream


@pytest.mark.parametrize('ambient_mode', ['default', 'ultra'])
def test_default_only_worker_rechecks_tampered_native_proof_under_any_ambient_mode(
        tmp_path, monkeypatch, ambient_mode):
    project, params, first, _ = _retained_default_stream(tmp_path, monkeypatch)
    produced = producers.produce(project, params)
    assert produced['verdict'] == 'PASS', produced
    original_owner = producers._step37_retained_output_sources
    original_owner(project, first['receipt'])
    Path(first['stream_state']).with_name('vibeic_receipt.json').unlink()
    observed = []

    def owner(*args, **kwargs):
        observed.append(args)
        return original_owner(*args, **kwargs)

    monkeypatch.setattr(producers, '_step37_retained_output_sources', owner)
    monkeypatch.setattr(policy, 'request', lambda: {'mode': ambient_mode})
    monkeypatch.setattr(worker, 'evaluate', lambda *_: pytest.fail(
        'consumer reached gates without rejecting the damaged native proof'))
    consumed = worker.execute_current_step(project, step_id='37', producer=produced)
    assert observed == [(project, first['receipt'])]
    assert consumed['verdict'] == 'NOT_MEASURED', consumed
    assert 'native retained stream refused' in consumed['gate_ledger'][0]['reason']


@pytest.mark.parametrize('ambient_mode', ['default', 'ultra'])
def test_unknown_authority_mode_keeps_generic_behavior_under_any_ambient_mode(
        tmp_path, monkeypatch, ambient_mode):
    project, params, first, _ = _retained_default_stream(tmp_path, monkeypatch)
    produced = producers.produce(project, params)
    assert produced['verdict'] == 'PASS', produced
    current = produced['current_step_declared_producers']
    Path(first['stream_state']).with_name('vibeic_receipt.json').unlink()
    monkeypatch.setattr(policy, 'request', lambda: {'mode': ambient_mode})
    monkeypatch.setattr(producers, '_step37_retained_output_sources', lambda *_: pytest.fail(
        'an unknown invocation mode was inferred from ambient policy'))
    assert producers._current_step_producer_authority(current, project=project) == (
        True, '', 'PASS')
