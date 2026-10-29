"""Real no-skip public/child report route; native/upstream SOFTWARE isolation only.

No tool/model/native proof executes. Actual lint/metric/report binding,
freshness, finalization and canonical writers remain untouched.
"""
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import flow109
import benchmark_dispatch as dispatch
import design_one_shot_runner as design
import librelane_contract as contract
from test_flow109_d11_metric_binding import case, reseal_software_native_failure
from test_flow109_selection import _public_d09_entry


@pytest.mark.parametrize('report_state,expected', [
    ('current', 'PASS'), ('missing', 'NOT_MEASURED'), ('stale', 'NOT_MEASURED'),
    ('wrong_invocation', 'NOT_MEASURED'), ('native_failure', 'FAIL')])
def test_d11_no_skip_public_and_real_child_preserve_original_report(case, monkeypatch, report_state, expected):
    p, context = case['project'], case['context']
    if report_state == 'native_failure':
        reseal_software_native_failure(case, 'design__lint_timing_construct__count')
        context = case['context']  # The synthetic control's normal qualification digest changed.
    runner = _public_d09_entry(p, monkeypatch)
    manifest = p / 'manifest.json'
    manifest.write_text(json.dumps({k: context[k] for k in
        ('features', 'runtime_tool_uses', 'qualification_registry')}))
    argv = [a for a in sys.argv if a not in ('--skip-phase1', '--skip-phase3', '--skip-analog')]
    for flag in ('--entry-step', '--exit-step'):argv[argv.index(flag) + 1] = 'D11'
    monkeypatch.setattr(sys, 'argv', argv)
    assert not set(argv).intersection({'--skip-phase1', '--skip-phase3', '--skip-analog'})
    original = p / 'reports/orchestrator/phase2_one_shot.json'
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path('/controls/ORIGINAL_ACCEPTED_D09_PHASE2_REPORT.json'), original)
    before = original.read_bytes(), original.stat().st_mtime_ns
    issued = []

    def child(command, *, env=None, **_kwargs):
        assert command[command.index('--entry-step') + 1] == '2'
        assert command[command.index('--exit-step') + 1] == '2'
        binding = json.loads(env[dispatch._RUNNER_CONTEXT_ENV]);issued.append(binding)
        # Only upstream runtime/staging/span admission is isolated. The real
        # main() native-Step-2 branch invokes the real retained lint consumer
        # and the real normal report writer at its selected path.
        with monkeypatch.context() as m:
            for key, value in env.items():m.setenv(key, value)
            m.setattr(sys, 'argv', command[1:])
            m.setattr(design, '_activate_runtime_program_tree', lambda _p: None)
            m.setattr(design, '_bootstrap_execution_policy', lambda *_a, **_k: None)
            m.setattr(design, 'step_reused_ip_consume', lambda *_a: None)
            m.setattr(design._spf, 'entry_admission', lambda *_a: {'admitted': True, 'site': 'rtl_lint_tool'})
            m.setattr(contract, 'selected_mode', lambda *_a: 'librelane')
            rc = design.main()
        # This catches the original write collision as a VALUE failure on
        # base, before any assertion about newly selected output existence.
        protected_report_unchanged = (original.read_bytes(), original.stat().st_mtime_ns) == before
        assert protected_report_unchanged is True
        report = Path(env[flow109.ATTEMPT_ENV]) / 'phase2_one_shot.json'
        if report_state == 'missing':report.unlink()
        elif report_state == 'stale':os.utime(report, ns=(before[1], before[1]))
        elif report_state == 'wrong_invocation':
            doc = json.loads(report.read_bytes());doc['runner_binding']['invocation_id'] = 'foreign'
            report.write_text(json.dumps(doc))
        return SimpleNamespace(returncode=rc)

    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == (0 if expected == 'PASS' else 1)
    assert len(issued) == 1
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    result = json.loads((attempt / 'result.json').read_bytes())
    summary = json.loads((p / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert summary['bounded'] is True
    assert summary['dispatched_verdict'] == expected, summary
    assert result['default_row_status'] == expected, result
    assert result['components'][0]['completed'] is (expected == 'PASS')
    assert result['components'][0]['flow109_acceptance'] == expected
    assert result['flow109_acceptance'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert summary['whole_flow_verdict'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before


def test_d11_current_execution_refuses_wrong_report_path(case, monkeypatch):
    import flow109_metric_acceptance as metrics
    from test_flow109_d11_metric_binding import software_fresh_owner
    report, invocation = software_fresh_owner(case, monkeypatch)
    p, context = case['project'], case['context']
    current = Path(os.environ[flow109.ATTEMPT_ENV]) / 'phase2_one_shot.json'
    assert metrics.d11_current_execution(p, context, report, invocation,
        published_current=True, report_path=current) is not None
    foreign = p / 'reports/orchestrator/phase2_one_shot.json'
    foreign.parent.mkdir(parents=True, exist_ok=True);foreign.write_bytes(current.read_bytes())
    assert metrics.d11_current_execution(p, context, report, invocation,
        published_current=True, report_path=foreign) is None


def test_d11_real_child_completed_attempt_keeps_result_and_owner_immutable(case, monkeypatch, capsys):
    test_d11_no_skip_public_and_real_child_preserve_original_report(case, monkeypatch, 'current', 'PASS')
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    paths = [attempt / 'result.json', attempt / 'phase2_one_shot.json',
             case['project'] / 'reports/orchestrator/phase2_one_shot.json']
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    report = json.loads(paths[1].read_bytes());binding = report['runner_binding']
    invocation = {k: binding[k] for k in ('invocation_id', 'argv', 'project', 'source')}
    with monkeypatch.context() as m:
        m.setenv(dispatch._RUNNER_CONTEXT_ENV, json.dumps(invocation))
        m.setattr(sys, 'argv', binding['argv'][1:])
        m.setattr(design, '_activate_runtime_program_tree', lambda _p: None)
        m.setattr(design, '_bootstrap_execution_policy', lambda *_a, **_k: None)
        m.setattr(design, 'step_reused_ip_consume', lambda *_a: None)
        m.setattr(design._spf, 'entry_admission', lambda *_a: {'admitted': True, 'site': 'rtl_lint_tool'})
        m.setattr(contract, 'selected_mode', lambda *_a: 'librelane')
        rc = design.main()
    unchanged = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before
    assert unchanged is True
    assert rc == 2
    assert 'D11_ATTEMPT_ALREADY_COMPLETED' in capsys.readouterr().err
