"""Native step results remain usable without flow admission or hash receipts."""
import json
from pathlib import Path
import subprocess

import pytest
import librelane_contract as native


def test_chain_carries_native_state_and_preserves_tool_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(native, 'image_capability', lambda *args: {})
    initial = tmp_path / 'initial.json'
    initial.write_text(json.dumps({'metrics': {}}))
    configs = [tmp_path / 'first.json', tmp_path / 'second.json']
    for config in configs:
        config.write_text('{}')
    observed = []

    def tool(argv, **kwargs):
        state = Path(argv[argv.index('-i') + 1])
        destination = Path(argv[argv.index('-o') + 1])
        prior = json.loads(state.read_text())
        observed.append(prior['metrics'])
        destination.joinpath('state_out.json').write_text(json.dumps({
            'metrics': {'native_count': prior['metrics'].get('native_count', 0) + 1}}))
        return subprocess.CompletedProcess(argv, 0, 'native tool output', '')

    monkeypatch.setattr(native, 'run_container', tool)
    folders = native.run_chain(tmp_path, 'tools', [
        ('Native.First', configs[0], initial),
        ('Native.Second', configs[1], initial)])
    assert observed == [{}, {'native_count': 1}]
    assert json.loads((folders[-1] / 'state_out.json').read_text())['metrics'] == {'native_count': 2}
    assert (folders[-1] / 'invocation.log').read_text() == 'native tool output\n'
    assert not list(tmp_path.rglob('vibeic_receipt.json'))
    assert not list(tmp_path.rglob('input_fingerprint.json'))


@pytest.mark.parametrize('code, output', [(7, True), (0, False)])
def test_chain_does_not_accept_failed_or_unreported_native_results(tmp_path, monkeypatch, code, output):
    monkeypatch.setattr(native, 'image_capability', lambda *args: {})
    initial, config = tmp_path / 'state.json', tmp_path / 'config.json'
    initial.write_text('{}')
    config.write_text('{}')

    def tool(argv, **kwargs):
        destination = Path(argv[argv.index('-o') + 1])
        if output:
            (destination / 'state_out.json').write_text('{}')
        return subprocess.CompletedProcess(argv, code, '', 'native failure')

    monkeypatch.setattr(native, 'run_container', tool)
    with pytest.raises(native.Refusal, match=f'LL_STEP_FAILED: Native.Step: rc={code}'):
        native.run_chain(tmp_path, 'tools', [('Native.Step', config, initial)])


def test_native_metric_limits_are_unchanged_by_report_metadata(tmp_path):
    (tmp_path / 'state_out.json').write_text(json.dumps({'metrics': {'violations': 2}}))
    result = native.judge_step(tmp_path, ['violations'], tmp_path / 'result.json',
                               limits={'violations': {'max': 1}})
    assert result['verdict'] == 'FAIL'
    assert result['metrics']['violations'] == {'status': 'FAIL', 'value': 2}
    assert 'sha256' not in result
