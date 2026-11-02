"""Fixture lineage controls over real subprocess launch and collection code.

These records describe neutral NOT_MEASURED software fixtures, never native PASS.
"""
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest
import benchmark_dispatch as dispatch
import flow109

PROGRAMS = Path(__file__).resolve().parents[1]


def _fixture_launch(tmp_path, *, row='D09', equals=False):
    project = tmp_path / 'project'
    (project / 'input').mkdir(parents=True, exist_ok=True)
    (project / 'input/phase1_prompt.md').write_text('Neutral lineage fixture input.\n')
    features = {name: False for name in
                set(flow109.load_registry()['predicate_names'])
                - set(flow109.load_registry()['predicate_definitions']) - {'always'}}
    features.update(rtl_only=True, has_digital=True)
    selection = flow109.execution_context(flow109.resolve_plan(features), row, row)
    selection_path = tmp_path / 'selection.json'
    selection_path.write_text(json.dumps(selection))
    owner = selection['resolved_row']['profile']['dispatch']
    child = tmp_path / 'phase2_one_shot_runner.py'
    child.write_text('''import json, pathlib, sys
sys.path.insert(0, %r)
import benchmark_dispatch as dispatch
p = pathlib.Path(sys.argv[1])
body = {'project': str(p), 'fixture_control': True, 'verdict': 'NOT_MEASURED',
        'declared_window': {'entry_step': %r, 'exit_step': %r},
        'steps': [{'name': 'rtl_gen', 'status': 'NOT_MEASURED',
                   'reason_class': 'input_absent', 'detail': 'Neutral fixture has no RTL.'}]}
out = p / 'reports/orchestrator/phase2_one_shot.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(dispatch._bind_runner_report(body, p, __file__, out.name)))
raise SystemExit(2)
''' % (str(PROGRAMS), owner['owner_entry_step'], owner['owner_exit_step']))
    runner = tmp_path / 'vibe_ic_one_shot_runner.py'
    runner.write_text('''import pathlib, sys
sys.path.insert(0, %r)
import vibe_ic_one_shot_runner as front
p = pathlib.Path(sys.argv[1])
rc = front._run_phase('Neutral fixture child', pathlib.Path(%r),
    [str(p), '--entry-step', %r, '--exit-step', %r], invocation={})
front._write_runner_summary(p / 'reports/orchestrator/vibe_ic_one_shot.json',
    {'project': str(p), 'fixture_control': True, 'verdict': 'NOT_MEASURED'}, p)
raise SystemExit(rc)
''' % (str(PROGRAMS), str(child), owner['owner_entry_step'], owner['owner_exit_step']))
    argv = [sys.executable, str(runner), str(project)]
    argv += ([f'--entry-step={row}', f'--exit-step={row}'] if equals else
             ['--entry-step', row, '--exit-step', row])
    budget = dispatch._RunnerBudget(1, 1, 0)
    budget._env = {k: v for k, v in os.environ.items() if not k.startswith((
        'VIBEIC_FLOW109', 'VIBEIC_RUNNER_', 'VIBEIC_PARENT_RUNNER_', 'VIBE_IC_RUNNER_LOCK'))}
    budget._env[flow109.CONTEXT_ENV] = str(selection_path)
    process = budget.run(argv)
    assert process.error is None, process.stderr
    assert process.rc == 2
    return project, process, argv


def _documents(project):
    outer_path = project / 'reports/orchestrator/vibe_ic_one_shot.json'
    outer = json.loads(outer_path.read_bytes())
    ref = outer['runner_binding']['child_invocations'][0]
    completion_path = project / ref['path']
    completion = json.loads(completion_path.read_bytes())
    launch_path = project / completion['launch']['path']
    launch = json.loads(launch_path.read_bytes())
    phase2_path = project / 'reports/orchestrator/phase2_one_shot.json'
    phase2 = json.loads(phase2_path.read_bytes())
    return outer_path, outer, completion_path, completion, launch_path, launch, phase2_path, phase2


@pytest.mark.parametrize('row,equals', [('D09', False), ('D09', True), ('D11', False)])
def test_fixture_real_launch_retains_exact_child_identity_and_accepts_bounded_reports(tmp_path, row, equals):
    project, process, argv = _fixture_launch(tmp_path, row=row, equals=equals)
    outer_path, outer, completion_path, completion, launch_path, launch, _, child = _documents(project)
    assert dispatch._runner_diagnostics(process, argv, project)['status'] == 'REPORTS_AVAILABLE'
    assert dispatch._runner_report_binding_reason(process.invocation, require_phase2=True) is None
    assert launch['child_invocation']['argv'] == child['runner_binding']['argv']
    assert launch['child_invocation']['source'] == child['runner_binding']['source']
    assert child['runner_binding']['parent_invocation'] == launch['parent_invocation']
    assert outer['runner_binding']['invocation_id'] != child['runner_binding']['invocation_id']
    assert launch_path.is_file() and completion_path.is_file() and outer_path.is_file()
    assert not process.invocation['material_after']['output_rtl']
    got = dispatch._collect_runner_result(process, argv, 'neutral', 'fixture', project)
    assert got['ok'] is False and got['reason'].startswith('no RTL at ')


@pytest.mark.parametrize('kind', ['child_source', 'outer_source', 'input_content', 'input_added',
                                 'output_added', 'owner_bytes', 'completion_bytes', 'launch_bytes',
                                 'owner_symlink', 'directory_symlink', 'canonical_symlink',
                                 'owner_fifo', 'completion_fifo', 'launch_fifo'])
def test_fixture_post_launch_drift_cannot_collect(tmp_path, kind):
    project, process, argv = _fixture_launch(tmp_path)
    _, _, completion_path, completion, launch_path, launch, phase2_path, _ = _documents(project)
    owner = project / completion['owner_reports']['phase2_one_shot.json']['path']
    if kind in ('child_source', 'outer_source'):
        path = Path(launch['child_invocation']['argv'][1] if kind == 'child_source' else argv[1])
        path.write_text(path.read_text() + '\n# Fixture source substitution.\n')
    elif kind == 'input_content':
        (project / 'input/phase1_prompt.md').write_text('Replaced fixture input.\n')
    elif kind == 'input_added':
        (project / 'input/extra.txt').write_text('Additional fixture input.\n')
    elif kind == 'output_added':
        path = project / 'phase2/stage1/rtl/extra.v'
        path.parent.mkdir(parents=True)
        path.write_text('// Fixture substitution, not a design answer.\n')
    elif kind.endswith('_fifo'):
        path = {'owner_fifo': owner, 'completion_fifo': completion_path, 'launch_fifo': launch_path}[kind]
        path.unlink()
        os.mkfifo(path)
    elif kind.endswith('_bytes'):
        path = {'owner_bytes': owner, 'completion_bytes': completion_path, 'launch_bytes': launch_path}[kind]
        path.write_text('{}')
    elif kind == 'directory_symlink':
        directory = owner.parent
        moved = directory.with_name(directory.name + '-moved')
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        path = owner if kind == 'owner_symlink' else phase2_path
        moved = tmp_path / 'moved-report.json'
        path.rename(moved)
        path.symlink_to(moved)
    got = dispatch._collect_runner_result(process, argv, 'neutral', 'fixture', project)
    assert got['ok'] is False and 'completion' not in got
    assert got['reason'].startswith('RUNNER_'), got


def _rewrite(path, document):
    path.write_text(json.dumps(document))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind', [
    'wrong_parent', 'stale_child', 'unrelated_child', 'wrong_project', 'wrong_argv',
    'wrong_consumer', 'wrong_producer', 'wrong_material', 'wrong_report',
    'wrong_selection', 'wrong_owner_window', 'wrong_declared_window', 'outside_time',
    'report_swap', 'absolute_path', 'escape_path', 'foreign_path', 'missing_completion',
    'duplicate_completion', 'swapped_launch', 'child_source_after', 'outer_identity',
])
def test_fixture_rehashed_lineage_does_not_authorize_an_unrelated_subject(tmp_path, kind):
    project, process, _ = _fixture_launch(tmp_path)
    receipt = copy.deepcopy(process.invocation)
    outer_path, outer, completion_path, completion, launch_path, launch, phase2_path, phase2 = _documents(project)
    binding = phase2['runner_binding']
    if kind == 'wrong_parent':
        binding['parent_invocation']['invocation_id'] = '0' * 32
    elif kind in ('stale_child', 'unrelated_child'):
        binding['invocation_id'] = '1' * 32
    elif kind == 'wrong_project':
        binding['project'] = str(tmp_path / 'other-project')
    elif kind == 'wrong_argv':
        binding['argv'].append('--fixture-wrong-argument')
    elif kind == 'wrong_consumer':
        binding['source']['consumer']['sha256'] = '0' * 64
    elif kind == 'wrong_producer':
        binding['producer']['sha256'] = '0' * 64
    elif kind == 'wrong_material':
        binding['material']['input'] = {}
    elif kind == 'wrong_report':
        binding['report_name'] = 'phase3_one_shot.json'
    elif kind == 'wrong_selection':
        launch['selection'] = flow109.execution_context(flow109.resolve_plan(
            launch['selection']['features']), 'D11', 'D11')
    elif kind == 'wrong_owner_window':
        child = launch['child_invocation']
        child['argv'][child['argv'].index('--exit-step') + 1] = '2'
        child['source'] = dispatch._runner_source_snapshot(child['argv'])
        completion['child_invocation'] = copy.deepcopy(child)
        completion['source_after'] = child['source']
        binding.update(copy.deepcopy(child))
    elif kind == 'wrong_declared_window':
        phase2['declared_window']['exit_step'] = '2'
    elif kind == 'outside_time':
        launch['started_ns'] = receipt['started_ns'] - 1
    elif kind == 'child_source_after':
        completion['source_after']['runner']['sha256'] = '0' * 64
    elif kind == 'outer_identity':
        outer['runner_binding']['invocation_id'] = '0' * 32
    owner_ref = completion['owner_reports']['phase2_one_shot.json']
    owner_path = project / owner_ref['path']
    _rewrite(phase2_path, phase2)
    owner_ref['sha256'] = _rewrite(owner_path, phase2)
    completion['reports_after']['phase2_one_shot.json'] = dispatch._runner_report_snapshot(project)['phase2_one_shot.json']
    if kind == 'report_swap':
        owner_ref['sha256'] = _rewrite(owner_path, {'fixture_control': 'unrelated child bytes'})
    elif kind in ('absolute_path', 'escape_path', 'foreign_path'):
        owner_ref['path'] = {'absolute_path': str(owner_path), 'escape_path': '../outside.json',
                             'foreign_path': 'reports/orchestrator/phase2_one_shot.json'}[kind]
    completion['launch']['sha256'] = _rewrite(launch_path, launch)
    if kind == 'swapped_launch':
        completion['launch']['path'] = completion_path.relative_to(project).as_posix()
    outer['runner_binding']['child_invocations'][0]['sha256'] = _rewrite(completion_path, completion)
    if kind == 'missing_completion':
        outer['runner_binding']['child_invocations'] = []
    elif kind == 'duplicate_completion':
        outer['runner_binding']['child_invocations'] *= 2
    _rewrite(outer_path, outer)
    receipt['reports_after'] = dispatch._runner_report_snapshot(project)
    assert dispatch._runner_report_binding_reason(receipt, require_phase2=True).startswith('RUNNER_REPORT_UNBOUND:')


def test_fixture_earlier_real_child_from_same_project_cannot_replace_current_report(tmp_path):
    project, previous, _ = _fixture_launch(tmp_path)
    report = project / 'reports/orchestrator/phase2_one_shot.json'
    previous_report = report.read_bytes()
    project, current, argv = _fixture_launch(tmp_path)
    assert previous.invocation_id != current.invocation_id
    report.write_bytes(previous_report)
    receipt = copy.deepcopy(current.invocation)
    receipt['reports_after'] = dispatch._runner_report_snapshot(project)
    receipt_path = Path(current.receipt_path)
    digest = _rewrite(receipt_path, receipt)
    substituted = replace(current, invocation=receipt, receipt_sha256=digest)
    got = dispatch._collect_runner_result(substituted, argv, 'neutral', 'fixture', project)
    assert got['ok'] is False and 'completion' not in got
    assert got['runner_diagnostics']['reason_class'] == 'RUNNER_REPORT_NOT_FRESH'
