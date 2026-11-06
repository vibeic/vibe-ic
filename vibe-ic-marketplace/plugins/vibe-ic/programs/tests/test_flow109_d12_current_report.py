"""Actual no-skip D12 public cutoff/freshness; upstream/child OS isolation only."""
import json
import sys





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
