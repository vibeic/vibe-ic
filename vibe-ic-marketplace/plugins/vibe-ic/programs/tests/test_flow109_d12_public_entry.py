"""D12 actual public route with explicitly isolated upstream admission/child process.

The child invokes the real retained metric/owner/canonical writer in process.
SOFTWARE per-use qualification comes from the adjacent source fixture; these
controls establish routing/publication behavior, not native or product PASS.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import flow109
import benchmark_dispatch as dispatch
import design_one_shot_runner as design
from test_flow109_d12_metric_binding import case, qualified_context
from test_flow109_selection import _public_d09_entry


def setup_public(p, context, monkeypatch, *, named=True):
    runner = _public_d09_entry(p, monkeypatch)
    manifest = p / 'manifest.json'
    body = {'features': context['features']}
    for key in ('runtime_tool_uses', 'qualification_registry'):
        if context.get(key) is not None: body[key] = context[key]
    manifest.write_text(json.dumps(body))
    argv = list(sys.argv)
    for flag in ('--entry-step', '--exit-step'):
        argv[argv.index(flag) + 1] = 'D12' if named else '3'
    monkeypatch.setattr(sys, 'argv', argv)
    return runner


@pytest.mark.parametrize('input_state,expected_rc,expected_status', [
    ('current', 0, 'PASS'), ('unqualified', 1, 'NOT_MEASURED'), ('missing_graph', 1, 'NOT_MEASURED')])
def test_d12_public_named_entry_reaches_actual_owner_once(case, monkeypatch, capsys,
                                                        input_state, expected_rc, expected_status):
    p, context = case
    if input_state == 'unqualified':
        context = flow109.execution_context(flow109.resolve_plan(context['features']), 'D12', 'D12')
    if input_state == 'missing_graph':
        (p / 'reports/phase2/cdc/netlist.json').unlink()
    runner = setup_public(p, context, monkeypatch)
    original = p / 'reports/orchestrator/phase2_one_shot.json'
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(Path('/controls/ORIGINAL_ACCEPTED_D09_PHASE2_REPORT.json').read_bytes())
    before = original.read_bytes()
    issued = []
    def child(command, *, env=None, **_kwargs):
        assert command[command.index('--entry-step') + 1] == '3'
        assert command[command.index('--exit-step') + 1] == '3'
        assert Path(command[1]).name == 'phase2_one_shot_runner.py'
        binding = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        issued.append(binding)
        current = flow109.validate_execution_context(json.loads(Path(env[flow109.CONTEXT_ENV]).read_bytes()))
        return SimpleNamespace(returncode=design._publish_d12_owner(p, current, invocation_context=binding))
    monkeypatch.setattr(runner.subprocess, 'run', child)
    rc = runner._main()
    assert len(issued) == 1, (rc, capsys.readouterr())
    assert rc == expected_rc
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    terminal = json.loads((attempt / 'result.json').read_bytes())
    fresh = json.loads((attempt / 'phase2_one_shot.json').read_bytes())
    assert terminal['default_row_status'] == expected_status, terminal
    assert terminal['components'][0]['completed'] is (expected_status == 'PASS')
    assert fresh['runner_binding']['invocation_id'] == issued[0]['invocation_id']
    assert fresh['runner_binding']['argv'] == issued[0]['argv']
    assert fresh['steps'][0]['extras']['metric_acceptance']['status'] == expected_status
    assert terminal['delivery_accepted'] is False
    summary = json.loads((p / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    phase = next(x for x in summary['phases'] if x['name'] == 'phase2')
    assert phase['verdict'] == expected_status
    assert phase['rc'] == (0 if expected_status == 'PASS' else 2)
    assert summary['whole_flow_verdict'] == 'NOT_MEASURED'
    assert original.read_bytes() == before  # Original D09 owner is retained.


def test_d12_unsupported_legacy_entry_still_refuses(case, monkeypatch, capsys):
    p, context = case
    runner = setup_public(p, context, monkeypatch, named=False)
    issued = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: issued.append(a))
    assert runner._main() == 2
    assert issued == []
    assert "FLOW109_STEP_NOT_SELECTED: 3" in capsys.readouterr().err


def test_d12_foreign_or_stale_context_does_not_select_owner(case, monkeypatch):
    p, context = case
    import vibe_ic_one_shot_runner as runner
    foreign = flow109.execution_context(flow109.resolve_plan(context['features']), 'D11', 'D11')
    cp = p / 'foreign_context.json';cp.write_text(json.dumps(foreign))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(cp))
    assert runner._flow109_selected_row('D12') is False
    changed = dict(context);changed['requested_step'] = 'D11'
    cp.write_text(json.dumps(changed))
    assert runner._flow109_selected_row('D12') is False


def test_d12_public_entry_retains_actual_native_fail_beside_missing_obligations(tmp_path, monkeypatch):
    import shutil
    import _cdc_netlist as native
    import flow109_metric_acceptance as metrics
    p = tmp_path / 'native_case'
    shutil.copytree(Path('/native-reference/fixtures/reset_cycle'), p)
    nl = native.load(p / native.NETLIST_REL)
    clocks = native.clock_domains(nl)
    subject = metrics.d12_subject(p)
    source = {'purpose': metrics.D12_PURPOSE, 'subject': subject,
        'source_refs': [subject['input']['files'][0]],
        'input_domains': {n: {'role': 'clock' if n in clocks else 'asynchronous_data',
                             'clock': n if n in clocks else clocks[0]}
                          for n, (direction, _bits) in nl.ports.items() if direction == 'input'},
        'clock_reset_crossing_census': {'required_items': [
            {'kind': 'state', 'name': 'missing_alias', 'clock': clocks[0], 'detail': '1'}]}}
    sp = p / 'input/flow109/D12/source.json';sp.parent.mkdir(parents=True);sp.write_text(json.dumps(source))
    rp = p / 'requirements/base_06/clock_reset_crossing_census.json';rp.parent.mkdir(parents=True)
    rp.write_text(json.dumps({'schema': metrics.AUTHORITY_SCHEMA, **source['clock_reset_crossing_census'],
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': {'path': str(sp.relative_to(p)), 'sha256': hashlib.sha256(sp.read_bytes()).hexdigest()}}}))
    context = qualified_context(p)  # Explicit SOFTWARE qualification/authority isolation.
    runner = setup_public(p, context, monkeypatch)
    original = p / 'reports/orchestrator/phase2_one_shot.json';original.parent.mkdir(parents=True)
    original.write_bytes(Path('/controls/ORIGINAL_ACCEPTED_D09_PHASE2_REPORT.json').read_bytes())
    before = original.read_bytes();issued = []
    def child(command, *, env=None, **_kwargs):
        issued.append(command)
        current = flow109.validate_execution_context(json.loads(Path(env[flow109.CONTEXT_ENV]).read_bytes()))
        binding = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        return SimpleNamespace(returncode=design._publish_d12_owner(p, current, invocation_context=binding))
    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == 1
    assert len(issued) == 1
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert result['default_row_status'] == 'FAIL'
    metrics_result = result['components'][0]['metric_acceptance']
    assert [r['status'] for r in metrics_result['obligations']] == ['NOT_MEASURED', 'FAIL', 'NOT_MEASURED']
    assert any(f['rule'] == 'CIRCULAR_RESET_DEPENDENCY'
               for f in metrics_result['obligations'][1]['findings'])
    assert original.read_bytes() == before
