"""Public dispatch/source controls; synthetic owner evidence, no native PASS claim."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import flow109
from programs.tests._hostpaths import require_repo
from programs.tests.test_flow109_selection import _public_d09_entry


@pytest.fixture(autouse=True)
def _isolate_sequence_environment(monkeypatch):
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV, flow109.OWNER_LAUNCH_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ''))
        monkeypatch.delenv(name)


def test_shipped_frontend_crossing_is_a_native_owner_sequence():
    registry = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'flow109.json').read_text())
    features = next(p['features'] for p in registry['reference_profiles']
                    if p['name'] == 'RTL-only')
    try:
        observed = flow109.resolve_execution_window(
            flow109.resolve_plan(features), 'D01', 'D13')['dispatch_kind']
    except flow109.Flow109Error as exc:
        observed = exc.code
    assert observed == 'canonical_owner_sequence', observed


def _public_sequence(project, monkeypatch, *, first='D09', last='D10'):
    runner = _public_d09_entry(project, monkeypatch)
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'RTL-only')
    (project / 'manifest.json').write_text(json.dumps({'features': features}))
    (project / 'input/phase1_prompt.md').write_text(
        'Implement a combinational module whose output equals its input; deliver RTL.\n')
    argv = list(sys.argv)
    argv[argv.index('--entry-step') + 1] = first
    argv[argv.index('--exit-step') + 1] = last
    argv[argv.index('--route') + 1] = 'ip'
    argv += ['--delivery-target', 'rtl']
    monkeypatch.setattr(sys, 'argv', argv)
    return runner


def test_public_window_stops_at_failed_first_selected_owner(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch)
    launches = []

    def child(command, **kwargs):
        launches.append((Path(command[1]).name,
                         command[command.index('--entry-step') + 1],
                         command[command.index('--exit-step') + 1]))
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == 2
    assert launches == [('vibe_ic_one_shot_runner.py', 'D09', 'D09')], launches


def test_single_row_owner_closure_stays_source_declared(tmp_path, monkeypatch):
    runner = _public_d09_entry(tmp_path, monkeypatch)
    launches = []

    def child(command, **kwargs):
        launches.append((Path(command[1]).name,
                         command[command.index('--entry-step') + 1],
                         command[command.index('--exit-step') + 1]))
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(runner.subprocess, 'run', child)
    # Preserve the existing owner's failure exit; this is not sequence policy.
    assert runner._main() == 1
    assert launches == [('phase2_one_shot_runner.py', '1', '1')], launches


def _controlled_child(runner, project, monkeypatch, calls, *, stop=None, damage=None,
                      engineering=None, process_rc=None):
    """Double process transport only; use real prepare/finalize/attempt bindings."""
    def child(command, *, env, **kwargs):
        step = command[command.index('--entry-step') + 1]
        calls.append(step)
        with monkeypatch.context() as child_patch:
            for key in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV, flow109.OWNER_LAUNCH_ENV):
                if key in env:
                    child_patch.setenv(key, env[key])
            args = SimpleNamespace(flow='109', flow109_manifest=project / 'manifest.json',
                flow109_plan_only=False, execution_mode='default', entry_step=step,
                exit_step=step, route='ip', delivery_target='rtl')
            assert flow109.prepare_front_door(args, project) is None
            current = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_bytes())
            assert current['requested_step'] == step
            native = current['resolved_row']['profile']['dispatch']['native_step_id']
            state = 'FAIL' if stop == step else 'PASS'
            extra = ({'default_row_status': 'NOT_MEASURED', 'completed': False,
                      'qualification_status': 'NOT_CLAIMED',
                      'engineering_evidence': {'scope': 'existing_native_component_only'}}
                     if step == engineering else {})
            result = flow109.finish_native_window(project, {'steps': [{'status': state,
                'extras': {'step_id': native, 'default_row_status': state,
                           'completed': state == 'PASS', **extra}}]})
            if damage:
                path = Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json'
                if damage == 'identity':
                    result['context_sha256'] = '0' * 64
                elif damage == 'incomplete':
                    result['components'][0]['completed'] = False
                elif damage == 'delivery':
                    result['delivery_accepted'] = True
                path.write_text(json.dumps(result))
            return SimpleNamespace(returncode=process_rc if process_rc is not None
                                   else 1 if state == 'FAIL' else 0)
    monkeypatch.setattr(runner.subprocess, 'run', child)


def test_public_sequence_consumes_distinct_current_owner_results(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch)
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls)
    assert runner._main() == 0
    assert calls == ['D09', 'D10']
    parent = Path(os.environ[flow109.ATTEMPT_ENV])
    result = json.loads((parent / 'result.json').read_bytes())
    assert result['default_row_status'] == 'PASS'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    refs = [item['owner_result']['path'] for item in result['components']]
    assert len(set(refs)) == 2
    assert all(Path(ref).parent.name != parent.name for ref in refs)


@pytest.mark.parametrize('damage', ['identity', 'incomplete', 'delivery'])
def test_malformed_current_owner_result_cannot_start_later_owner(tmp_path, monkeypatch, damage):
    runner = _public_sequence(tmp_path, monkeypatch)
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls, damage=damage)
    assert runner._main() == 2
    assert calls == ['D09']
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['components'][1]['native_started'] is False


def test_actual_failed_native_component_blocks_sequence(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch)
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls, stop='D09')
    assert runner._main() == 1
    assert calls == ['D09']
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert result['component_status'] == 'FAIL'
    assert result['components'][1]['native_started'] is False


def test_real_child_missing_adopted_authority_stops_before_lint(tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch
    runner = _public_sequence(tmp_path, monkeypatch, first='D10', last='D11')
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--rtl-input', 'original'])
    command = [sys.executable, *sys.argv]
    invocation = {'invocation_id': 'neutral-sequence-invocation', 'argv': command,
                  'project': str(tmp_path), 'source': dispatch._runner_source_snapshot(command)}
    monkeypatch.setenv(dispatch._RUNNER_CONTEXT_ENV, json.dumps(invocation))
    assert runner._main() == 2
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert [item['step_id'] for item in result['components']] == ['D10', 'D11']
    assert len(result['owner_launches']) == 1
    assert result['components'][1]['native_started'] is False
    first = result['components'][0]
    assert first['component_status'] == 'NOT_MEASURED'
    assert 'owner_result' in first, first
    assert first['evidence']['input_refusal']['reason'] == 'D10_D09_INPUT_UNAVAILABLE'
    summary = json.loads((tmp_path / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert all(summary['runner_binding'][key] == value for key, value in invocation.items())


def test_explicit_qualification_inventory_cannot_be_dropped_for_sequence(tmp_path, monkeypatch, capsys):
    runner = _public_sequence(tmp_path, monkeypatch)
    manifest = tmp_path / 'manifest.json'
    body = json.loads(manifest.read_bytes())
    body.update(runtime_tool_uses=[], qualification_registry='missing.json')
    manifest.write_text(json.dumps(body))
    calls = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: calls.append(a))
    assert runner._main() == 2
    assert calls == []
    assert 'FLOW109_RTL_SCOPE_CONFLICT' in capsys.readouterr().err


def test_nonrtl_same_owner_window_keeps_its_existing_native_span():
    features = dict(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                         if p['name'] == 'Small digital IC without DFT'))
    features['requires_dft'] = True
    plan = flow109.resolve_plan(features)
    for last in ('D24', 'D25'):
        window = flow109.resolve_execution_window(plan, 'D23', last)
        assert window['dispatch_kind'] == 'canonical_owner_window', window['dispatch_kind']
        assert window['native_entry_step'] == '11'
        assert window['native_exit_step'] == {'D24': '12', 'D25': '13'}[last]


def test_nonrtl_crossing_keeps_named_refusal():
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Digital soft-IP')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_WINDOW_OWNER_CROSSING_UNSUPPORTED'):
        flow109.resolve_execution_window(flow109.resolve_plan(features), 'D01', 'D13')


def test_rtl_feature_alone_does_not_authorize_sequence(tmp_path, monkeypatch, capsys):
    runner = _public_sequence(tmp_path, monkeypatch)
    argv = list(sys.argv)
    at = argv.index('--delivery-target')
    del argv[at:at + 2]
    # Existing owner supplies an ordinary IP route. It cannot manufacture a
    # source-bound RTL invocation merely by choosing the RTL feature profile.
    answer = tmp_path / 'input/step_0_5ic_answers.json'
    body = json.loads(answer.read_bytes())
    body['answers']['deliverable'] = 'HARDMACRO'
    answer.write_text(json.dumps(body))
    monkeypatch.setattr(sys, 'argv', argv)
    launches = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw:
                        launches.append(a) or SimpleNamespace(returncode=2))
    assert runner._main() == 2
    assert launches == []
    assert 'FLOW109_RTL_SCOPE_REQUIRED' in capsys.readouterr().err


@pytest.mark.parametrize('changed', ['source', 'manifest'])
def test_changed_scope_authority_stops_before_first_child(tmp_path, monkeypatch, changed):
    runner = _public_sequence(tmp_path, monkeypatch)
    def change_source(*args, **kwargs):
        if changed == 'source':
            (tmp_path / 'input/phase1_prompt.md').write_text(
                'Implement a different module and deliver RTL.\n')
        else:
            manifest = tmp_path / 'manifest.json'
            body = json.loads(manifest.read_bytes())
            body['request_note'] = 'changed after admission'
            manifest.write_text(json.dumps(body))
        return {'verdict': 'PASS'}
    monkeypatch.setattr(runner, '_capture_container_image', change_source)
    launches = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw:
                        launches.append(a) or SimpleNamespace(returncode=2))
    assert runner._main() == 2
    assert launches == []
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert 'FLOW109_RTL_SCOPE_STALE' in result['components'][0]['reason']
    assert all(item.get('native_started') is False for item in result['components'])


def test_completed_launch_cannot_be_replayed(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch)
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls)
    assert runner._main() == 0
    parent = Path(os.environ[flow109.ATTEMPT_ENV])
    descriptor = next(parent.glob('owner-window-*.json'))
    launch = json.loads(descriptor.read_bytes())
    monkeypatch.setenv(flow109.OWNER_LAUNCH_ENV, str(descriptor))
    with pytest.raises(flow109.Flow109Error, match='FLOW109_OWNER_LAUNCH_INVALID'):
        flow109._owner_attempt(tmp_path, launch['child_context'])


def test_engineering_success_is_not_promoted_to_qualified_completion(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch, first='D10', last='D11')
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--rtl-input', 'original'])
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls, engineering='D11')
    assert runner._main() == 0
    assert calls == ['D10', 'D11']
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert result['component_status'] == 'PASS'
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['components'][-1]['completed'] is False
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


def test_later_staged_owner_requires_current_accepted_author_population(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch, first='D11', last='D12')
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--rtl-input', 'original'])
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls, engineering='D11')
    assert runner._main() == 2
    assert calls == ['D11']
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert result['components'][0]['component_status'] == 'PASS'
    assert result['components'][1]['native_started'] is False
    assert 'D09.json' in result['components'][1]['reason']


def test_nonzero_process_cannot_complete_a_passing_owner_window(tmp_path, monkeypatch):
    runner = _public_sequence(tmp_path, monkeypatch)
    calls = []
    _controlled_child(runner, tmp_path, monkeypatch, calls, process_rc=1)
    assert runner._main() == 2
    assert calls == ['D09']
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    assert result['default_row_status'] == 'NOT_MEASURED'
