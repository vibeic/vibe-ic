"""Public Phase2 retries reach the child and preserve its native outcome."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import benchmark_dispatch as dispatch
import design_one_shot_runner as design
import flow109
from test_flow109_d09_owned_metrics import populate
from test_flow109_selection import _public_d09_entry


@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_public_native_retry_uses_new_attempt_and_child_status(tmp_path, monkeypatch, status):
    populate(tmp_path)
    runner = _public_d09_entry(tmp_path, monkeypatch)
    argv = ['D11' if item == 'D09' else item for item in sys.argv]
    argv += ['--execution-mode', 'default']
    def forbidden(*args, **kwargs):
        pytest.fail('public native dispatch must not ask the historical admission ledger')
    monkeypatch.setattr(runner._canonical_admission, 'admit_span', forbidden)
    monkeypatch.setattr(runner._canonical_admission, 'child_env', forbidden)
    calls = []
    def child(command, *, env=None, **kwargs):
        calls.append(command)
        assert command[command.index('--entry-step') + 1] == '2'
        assert command[command.index('--exit-step') + 1] == '2'
        context = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        report = {'project': str(tmp_path), 'verdict': status,
                  'declared_window': {'entry_step': '2', 'exit_step': '2', 'dispatched_step_ids': ['2']},
                  'steps': [{'name': 'rtl_lint_tool', 'status': status, 'detail': 'TEST_ONLY child native outcome', 'extras': {}}]}
        path = Path(env[flow109.ATTEMPT_ENV]) / 'phase2_one_shot.json'
        design._write_phase2_report(path, report, tmp_path,
                                   invocation_context=context, publish_current=True)
        return SimpleNamespace(returncode=0 if status == 'PASS' else 1)
    monkeypatch.setattr(runner.subprocess, 'run', child)
    results = []
    for _ in range(2):
        monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
        monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
        monkeypatch.setattr(sys, 'argv', list(argv))
        assert runner._main() == (0 if status == 'PASS' else 1)
        path = Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json'
        result = json.loads(path.read_text())
        assert result['default_row_status'] == status
        assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
        assert result['delivery_accepted'] is False
        results.append(path)
    assert len(calls) == 2 and results[0] != results[1]
    assert all(json.loads(path.read_text())['default_row_status'] == status for path in results)
