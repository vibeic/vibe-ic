"""Actual public owner routing; stop before Phase1/native process dispatch.

The normal existing source fixture supplies the declaration prerequisites.
Runtime/image admission and the later Phase1 decision are source-control doubles;
these tests make no native LEC or whole-flow acceptance claim.
"""
import json
import sys

import pytest

from programs.tests.test_flow109_selection import _public_d09_entry, _publish_dft_intent


class ReachedPhase1Decision(Exception):
    pass


def _stop_after_owner_routing(runner, monkeypatch):
    def reached(*args, **kwargs):
        raise ReachedPhase1Decision
    monkeypatch.setattr(runner, '_phase1_decision', reached)


def test_registered_d25_span_reaches_existing_chain_route(tmp_path, monkeypatch):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    _publish_dft_intent(tmp_path, {'requires_scan': False,
        'reason': 'Neutral source control retains functional LEC without scan.'})
    monkeypatch.setattr(sys, 'argv', ['D25' if value == 'D09' else value for value in sys.argv])
    _stop_after_owner_routing(runner, monkeypatch)
    with pytest.raises(ReachedPhase1Decision):
        runner._main()


@pytest.mark.parametrize('exit_step', ['D23', 'D24', 'D25'])
def test_step11_owner_preserves_exact_registered_window(
        tmp_path, monkeypatch, capsys, exit_step):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    manifest = tmp_path / 'manifest.json'
    body = json.loads(manifest.read_text())
    body['features']['requires_dft'] = True
    manifest.write_text(json.dumps(body))
    _publish_dft_intent(tmp_path, {'requires_scan': False,
        'reason': 'Source-only control of the registered non-scan Step11 window.'})
    argv = list(sys.argv)
    argv[argv.index('--entry-step') + 1] = 'D23'
    argv[argv.index('--exit-step') + 1] = exit_step
    monkeypatch.setattr(sys, 'argv', argv)
    _stop_after_owner_routing(runner, monkeypatch)
    if exit_step == 'D23':
        with pytest.raises(ReachedPhase1Decision):
            runner._main()
    else:
        assert runner._main() == 2
        assert 'Default Step11 DFT owner needs --exit-step 11' in capsys.readouterr().err


def test_d22_cross_owner_window_still_refuses_before_producer(tmp_path, monkeypatch, capsys):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    _publish_dft_intent(tmp_path, {'requires_scan': False,
        'reason': 'Neutral source control retains functional LEC without scan.'})
    argv = list(sys.argv)
    argv[argv.index('--entry-step') + 1] = 'D22'
    argv[argv.index('--exit-step') + 1] = 'D25'
    monkeypatch.setattr(sys, 'argv', argv)
    assert runner._main() == 2
    assert 'FLOW109_WINDOW_DISPATCH_UNSUPPORTED' in capsys.readouterr().err
