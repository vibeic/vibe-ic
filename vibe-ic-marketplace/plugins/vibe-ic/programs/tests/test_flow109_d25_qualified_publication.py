"""Canonical D25 publication from frozen, actual qualified EQY executions."""
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
import flow109
import flow109_metric_acceptance as metrics
import vibe_ic_one_shot_runner as runner
from test_flow109_d25_publication import tail


pytestmark = pytest.mark.skipif(
    not os.environ.get('FLOW109_D25_QUALIFIED_REFERENCE'),
    reason='frozen qualified native execution required')


@pytest.fixture
def qualified_subject(monkeypatch, request):
    negative = request.node.name == 'test_actual_native_counterexample_publishes_fail'
    kind = 'bad' if negative else 'good'
    reference = Path(os.environ['FLOW109_D25_QUALIFIED_REFERENCE']) / kind
    project = Path('/out/canonical/projects') / kind
    # The genuine native attempt binds this absolute project path. Only an
    # explicitly mounted disposable copy may receive canonical writer output.
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    assert any(fields[4] == str(project) and 'rw' in fields[5].split(',')
               for fields in mounts), project
    for child in project.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(reference, project, dirs_exist_ok=True)
    retained = json.loads((project / 'd25-current-component-context.json').read_text())
    context = flow109.execution_context(
        flow109.resolve_plan(retained['features']), 'D25', 'D25')
    context_path = project / 'd25-publication-control-context.json'
    context_path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    return project, context, attempt


def test_genuine_qualified_pass_publishes_completed_row_only(qualified_subject):
    project, context, attempt = qualified_subject
    accepted = metrics.accept_d25(project, context)
    assert accepted['status'] == accepted['qualification'] == 'PASS', accepted
    assert len(accepted['obligations']) == 3
    assert all(o['status'] == 'PASS' for o in accepted['obligations'])
    assert tail(project) == 0
    row = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert row['default_row_status'] == 'PASS', row
    assert row['completed'] is True
    assert row['metric_acceptance'] == accepted
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['delivery_accepted'] is False
    result_path = attempt / 'result.json'
    before = result_path.read_bytes()
    result = json.loads(before)
    assert result['default_row_status'] == 'PASS'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert runner._finish_d25_selected_owner(project)['verdict'] == 'NOT_MEASURED'
    assert result_path.read_bytes() == before


def test_qualified_row_pass_preserves_failed_parent_window(qualified_subject):
    project, context, attempt = qualified_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    assert tail(project, 'FAIL') == 1
    summary = json.loads(runner._pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
    assert summary['verdict'] == summary['dispatched_verdict'] == 'FAIL'
    assert summary['phases'][0]['verdict'] == 'FAIL'
    assert summary['d25_finalization']['verdict'] == 'NOT_MEASURED'
    assert summary['d25_finalization']['metric_acceptance']['status'] == 'PASS'
    assert 'D25_OWNER_WINDOW_NOT_CURRENT_PASS' in summary['d25_finalization']['detail']
    row = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED' and row['completed'] is False
    assert row['owner_window'] == {'verdict': 'FAIL', 'published_current': True}
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['delivery_accepted'] is False


def test_qualified_native_pass_needs_current_passing_owner(qualified_subject):
    project, context, attempt = qualified_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    result = runner._finish_d25_selected_owner(project)
    assert result['verdict'] == 'NOT_MEASURED'
    assert result['metric_acceptance']['status'] == 'PASS'
    row = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED' and row['completed'] is False
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['delivery_accepted'] is False


@pytest.mark.parametrize('child_verdict,fresh', [('NOT_MEASURED', True), ('PASS', False)])
def test_actual_bounded_tail_refuses_unknown_or_stale_owner(
        qualified_subject, child_verdict, fresh):
    project, context, attempt = qualified_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    assert tail(project, child_verdict, fresh=fresh) == 2
    row = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED' and row['completed'] is False
    assert row['metric_acceptance']['status'] == 'PASS'
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['delivery_accepted'] is False


def test_actual_native_counterexample_publishes_fail(qualified_subject):
    project, context, attempt = qualified_subject
    accepted = metrics.accept_d25(project, context)
    assert accepted['status'] == accepted['component_status'] == 'FAIL', accepted
    assert accepted['reason'] == 'D25_NATIVE_CEX'
    assert runner._finish_d25_selected_owner(project)['verdict'] == 'FAIL'
    row = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert row['default_row_status'] == 'FAIL'
    assert row['completed'] is False
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert row['delivery_accepted'] is False


@pytest.mark.parametrize('damage', ['missing_execution', 'rtl', 'authority'])
def test_qualified_packet_refuses_missing_or_stale_inputs(qualified_subject, damage):
    project, context, attempt = qualified_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    manifest = project / 'input/flow109/D25.json'
    if damage == 'missing_execution':
        (project / 'reports/lec_eqy_execution.json').unlink()
    elif damage == 'authority':
        manifest.write_bytes(manifest.read_bytes() + b'\n ')
    else:
        declaration = json.loads(manifest.read_text())
        path = Path(declaration['rtl'][0]['path'])
        path = path if path.is_absolute() else project / path
        path.write_bytes(path.read_bytes() + b'\n// changed controlled RTL input\n')
    refused = metrics.accept_d25(project, context)
    assert refused['status'] == 'NOT_MEASURED', refused
    assert runner._finish_d25_selected_owner(project)['verdict'] == 'NOT_MEASURED'
    row = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED'
    assert row['completed'] is False
    assert row['delivery_accepted'] is False


def test_actual_consumer_reread_refuses_changed_input_before_publication(qualified_subject):
    project, context, attempt = qualified_subject
    assert metrics.accept_d25(project, context)['status'] == 'PASS'
    observations = []

    def observe_actual_return(frame, event, returned):
        if event != 'return' or frame.f_code is not metrics.accept_d25.__code__:
            return
        observations.append(returned['status'])
        if len(observations) == 1:
            declaration = json.loads((project / 'input/flow109/D25.json').read_text())
            rtl = project / declaration['rtl'][0]['path']
            rtl.write_bytes(rtl.read_bytes() + b'\n// changed between actual reads\n')

    # Keep every source-bound producer/consumer function intact. Only the
    # intervening real file edit is controlled; no verdict is substituted.
    previous = sys.getprofile()
    try:
        sys.setprofile(observe_actual_return)
        observed = runner._finish_d25_selected_owner(project)
    finally:
        sys.setprofile(previous)
    assert observations == ['PASS', 'NOT_MEASURED'], observations
    assert observed['verdict'] == 'NOT_MEASURED'
    assert 'changed during finalization' in observed['detail']
    assert not (attempt / 'result.json').exists()
    assert not (project / 'reports/flow109/default_rows/D25.json').exists()
