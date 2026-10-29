"""Actual no-skip D12 public cutoff/freshness; upstream/child OS isolation only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys

import pytest
import flow109
import benchmark_dispatch as dispatch
import design_one_shot_runner as design
from test_flow109_d12_metric_binding import case
from test_flow109_d12_public_entry import setup_public


@pytest.mark.parametrize('report_state,expected_rc,expected', [
    ('current', 0, 'PASS'), ('missing', 1, 'NOT_MEASURED'), ('stale', 1, 'NOT_MEASURED')])
def test_d12_no_skip_public_uses_current_attempt_freshness(case, monkeypatch, report_state, expected_rc, expected):
    p, context = case
    runner = setup_public(p, context, monkeypatch)
    # Actual E public flags contain NONE of these. Retain named entry/exit;
    # production's own bounded cut, publication and freshness must execute.
    monkeypatch.setattr(sys, 'argv', [a for a in sys.argv if a not in
        ('--skip-phase1', '--skip-phase3', '--skip-analog')])
    assert not set(sys.argv).intersection({'--skip-phase1', '--skip-phase3', '--skip-analog'})
    original = p / 'reports/orchestrator/phase2_one_shot.json';original.parent.mkdir(parents=True, exist_ok=True)
    source = Path('/controls/ORIGINAL_ACCEPTED_D09_PHASE2_REPORT.json')
    shutil.copy2(source, original)
    before = (original.read_bytes(), original.stat().st_mtime_ns)
    assert not runner._pl.published_here(original, __import__('time').time())
    issued = []
    def child(command, *, env=None, **_kwargs):
        assert command[command.index('--entry-step') + 1] == '3'
        assert command[command.index('--exit-step') + 1] == '3'
        binding = json.loads(env[dispatch._RUNNER_CONTEXT_ENV]);issued.append(binding)
        current = flow109.validate_execution_context(json.loads(Path(env[flow109.CONTEXT_ENV]).read_bytes()))
        rc = design._publish_d12_owner(p, current, invocation_context=binding)
        attempt = Path(env[flow109.ATTEMPT_ENV]);report = attempt / 'phase2_one_shot.json'
        if report_state == 'missing':report.unlink()
        elif report_state == 'stale':os.utime(report, ns=(before[1], before[1]))
        return SimpleNamespace(returncode=rc)
    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == expected_rc
    assert len(issued) == 1
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    result = json.loads((attempt / 'result.json').read_bytes())
    summary = json.loads((p / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert summary['bounded'] is True
    assert summary['dispatched_verdict'] == expected, summary
    assert summary['whole_flow_verdict'] == 'NOT_MEASURED'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    if report_state == 'current':
        assert result['components'][0]['flow109_acceptance'] == 'PASS'
        assert result['flow109_acceptance'] == 'NOT_MEASURED', result  # Aggregate scope remains unmeasured.
    else:
        assert 'Phase-2 child did not publish a fresh window report' in summary['verdict_reasons']
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before


def test_d12_no_skip_public_preserves_genuine_native_failure(tmp_path, monkeypatch):
    import test_flow109_d12_public_entry as existing
    real_setup = existing.setup_public
    def no_skip(*args, **kwargs):
        runner = real_setup(*args, **kwargs)
        monkeypatch.setattr(sys, 'argv', [a for a in sys.argv if a not in
            ('--skip-phase1', '--skip-phase3', '--skip-analog')])
        return runner
    monkeypatch.setattr(existing, 'setup_public', no_skip)
    existing.test_d12_public_entry_retains_actual_native_fail_beside_missing_obligations(tmp_path, monkeypatch)
    p = tmp_path / 'native_case'
    summary = json.loads((p / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert summary['bounded'] is True
    assert summary['dispatched_verdict'] == 'FAIL'
    assert summary['whole_flow_verdict'] == 'NOT_MEASURED'
