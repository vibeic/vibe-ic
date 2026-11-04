"""Native Phase2 statuses are not gated by the historical request ledger."""
import json
import sys

import pytest
import design_one_shot_runner as design
import librelane_contract as contract


@pytest.mark.parametrize('status,expected', [('PASS', 0), ('FAIL', 1), ('NOT_MEASURED', 2)])
def test_native_lint_retry_reaches_tool_and_keeps_its_status(tmp_path, monkeypatch, status, expected):
    for key in ('VIBEIC_FLOW109_CONTEXT', 'VIBEIC_FLOW109_ATTEMPT_DIR', 'VIBEIC_RUNNER_CONTEXT'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(design, '_activate_runtime_program_tree', lambda _: None)
    monkeypatch.setattr(design, '_bootstrap_execution_policy', lambda *args, **kwargs: None)
    monkeypatch.setattr(design._runner_lock, 'acquire_or_reenter', lambda *args: object())
    monkeypatch.setattr(design._spf, 'entry_admission', lambda *args: {'admitted': True, 'site': 'rtl_lint_tool'})
    monkeypatch.setattr(contract, 'selected_mode', lambda *args: 'librelane')
    def forbidden(*args, **kwargs):
        pytest.fail('historical request ledger must not block native retry')
    monkeypatch.setattr(design._canonical_admission, 'admit_span', forbidden)
    calls = []
    def lint(*args, **kwargs):
        calls.append(kwargs)
        return design.StepResult('rtl_lint_tool', status, 0.0, 'TEST_ONLY native dispatch outcome',
                                 reason_class='tool_absent' if status == 'NOT_MEASURED' else '')
    monkeypatch.setattr(design, 'step_rtl_lint_tool', lint)
    monkeypatch.setattr(sys, 'argv', ['design_one_shot_runner.py', str(tmp_path),
        '--entry-step', '2', '--exit-step', '2', '--top-name', 'unit', '--execution-mode', 'default'])
    assert design.main() == expected
    assert len(calls) == 1
    report = json.loads((tmp_path / 'reports/orchestrator/phase2_one_shot.json').read_text())
    assert report['verdict'] == status
    assert report['declared_window']['dispatched_step_ids'] == ['2']
