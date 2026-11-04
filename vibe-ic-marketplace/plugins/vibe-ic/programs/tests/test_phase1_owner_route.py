"""Execute the real owner-routing hunk; child results are explicit API doubles.

No checkpoint, extraction, review, metric qualification or native tool replay.
The normal source51 checkpoint remains the independently accepted authority.
"""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import vibe_ic_one_shot_runner as runner
import flow109
import step_preflight
import step_output_collector as versions


@pytest.fixture(autouse=True)
def no_process_dispatch(monkeypatch):
    import subprocess
    def refused(*args, **kwargs):
        raise AssertionError('Route controls must not execute checkpoint/generator/native tools')
    monkeypatch.setattr(subprocess, 'Popen', refused)


def route_statements():
    tree = ast.parse(Path(runner.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_main')
    selected = [n for n in main.body if isinstance(n, ast.If) and any(
        isinstance(x, ast.Constant) and x.value == '--complete-retained-metrics'
        for x in ast.walk(n))]
    # Preserve actual existing dispatch predicates; bodies only observe routes.
    physical = next(n for n in main.body if isinstance(n, ast.If) and
                    isinstance(n.test, ast.Compare) and ast.unparse(n.test) ==
                    "_entry_runner == 'phase3_one_shot_runner'")
    phase2 = next(n for n in main.body if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp)
                  and isinstance(n.test.operand, ast.Name) and n.test.operand.id == 'halted_at')
    def observe(test, name):
        return ast.If(test=test, body=[ast.Expr(ast.Call(ast.Name('later_route', ast.Load()),
            [ast.Constant(name)], [])), ast.Return(ast.Constant(99))], orelse=[])
    return selected + [observe(physical.test, 'phase3'), observe(phase2.test, 'phase2')]


def exercise(tmp_path, monkeypatch, *, first='D01', last='D02', retained=True, result='PASS', route='ic', legacy_retained=None, resume_plan=None):
    manifest = json.loads(Path(os.environ['PHASE1_ROUTE_MANIFEST']).read_text())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), first, last)
    native = context.get('native_entry_step', context.get('entry_step'))
    if first in ('D01', 'D02'):
        native, end = 'D1', 'D1'
    elif first == 'D30':
        native, end = '14', '14'
    else:
        native, end = '15', '15'
    owner = step_preflight.runner_for_step(native)
    path = tmp_path / 'context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    attempt = flow109._new_attempt(tmp_path, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    if retained:
        docs = runner._pl.generated_docs_dir(tmp_path)
        docs.mkdir(parents=True, exist_ok=True)
        (docs / 'L1_PRODUCT.json').write_text('{}')
    monkeypatch.setattr(versions, 'current_acceptance', lambda *_: [
        {'id': 'D1', 'status': 'PASS', 'canonical_pass': retained if legacy_retained is None else legacy_retained,
         'current_inputs': True, 'capture_errors': []}])
    calls = []
    # Route admission already precedes this hunk in the real front door.
    monkeypatch.setattr(runner._delivery_route, 'report_label', lambda *_:
                        {'delivery_route': 'IC', 'deliverable': 'DIE'})
    phase_env = {'existing_parent_context': str(path)}
    def run_phase(label, program, argv, *, env):
        calls.append(('phase1', list(argv)))
        assert env is phase_env
        reuse = retained and (resume_plan or {}).get('selection') != 'explicit_owner_window'
        assert ('--complete-retained-metrics' in argv) is reuse
        if result != 'MISSING':
            status = result if result in ('PASS', 'FAIL', 'NOT_MEASURED') else 'PASS'
            components = []
            selected_rows = context.get('resolved_rows') or [context['resolved_row']]
            for row in selected_rows:
                current = flow109.component_context(context, requested_step=row['id'])
                components.append({'step_id': row['id'], 'context_sha256': current['context_sha256'],
                    'component_status': 'PASS', 'default_row_status': status,
                    'completed': status == 'PASS'})
            finished = flow109._attempt_result({**context, 'resolved_rows': selected_rows}, components)
            if result == 'FOREIGN':
                finished['context_sha256'] = '0' * 64
            (attempt / 'result.json').write_text(json.dumps(finished))
        return 0
    def later_route(name):
        calls.append((name, []))
    published = []
    env = dict(vars(runner), project=tmp_path, _entry_runner=owner,
        args=SimpleNamespace(entry_step=native, exit_step=end, ic_name='neutral',
            route=route, pdk='gf180mcuD', skip_analog=False),
        _phase_env=phase_env, halted_at='', later_route=later_route, _resume_plan=resume_plan,
        _run_phase=run_phase, _phase_runner=lambda _: 'existing-phase1-owner.py',
        _write_runner_summary=lambda path, summary, project: published.append(summary),
        lock=SimpleNamespace(release=lambda: None))
    body = ast.FunctionDef(name='dispatch', args=ast.arguments(posonlyargs=[], args=[],
        kwonlyargs=[], kw_defaults=[], defaults=[]), body=route_statements(), decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[body], type_ignores=[])),
                 runner.__file__, 'exec'), env)
    rc = env['dispatch']()
    return calls, published, rc


@pytest.mark.parametrize('result,expected_rc', [('PASS', 0), ('FAIL', 1),
    ('NOT_MEASURED', 2), ('FOREIGN', 2), ('MISSING', 2)])
def test_phase1_retained_window_stops_before_wrong_phase(tmp_path, monkeypatch, result, expected_rc):
    calls, published, rc = exercise(tmp_path, monkeypatch, result=result)
    assert [x[0] for x in calls] == ['phase1'], calls
    assert rc == expected_rc
    status = result if result in ('PASS', 'FAIL', 'NOT_MEASURED') else 'NOT_MEASURED'
    assert published[0]['dispatched_verdict'] == status
    assert published[0]['whole_flow_verdict'] == 'NOT_MEASURED'


@pytest.mark.parametrize('row', ['D01', 'D02'])
def test_single_phase1_owner_uses_same_retained_consumer(tmp_path, monkeypatch, row):
    calls, _, rc = exercise(tmp_path, monkeypatch, first=row, last=row)
    assert [x[0] for x in calls] == ['phase1'] and rc == 0
    assert '--complete-retained-metrics' in calls[0][1]


def test_unretained_phase1_still_routes_to_original_owner(tmp_path, monkeypatch):
    calls, _, rc = exercise(tmp_path, monkeypatch, retained=False)
    assert [x[0] for x in calls] == ['phase1'] and rc == 0
    assert '--complete-retained-metrics' not in calls[0][1]


def test_explicit_phase1_rerun_reenters_extraction_with_retained_documents(tmp_path, monkeypatch):
    calls, published, rc = exercise(tmp_path, monkeypatch, first='D01', last='D01',
                                  resume_plan={'selection': 'explicit_owner_window'})
    assert [x[0] for x in calls] == ['phase1'] and rc == 0
    assert '--complete-retained-metrics' not in calls[0][1]
    assert published[0]['phase1_retained_metrics'] is False


def test_existing_documents_do_not_need_legacy_phase1_approval(tmp_path, monkeypatch):
    calls, _, rc = exercise(tmp_path, monkeypatch, legacy_retained=False)
    assert rc == 0
    assert '--complete-retained-metrics' in calls[0][1]


@pytest.mark.parametrize('row,expected', [('D30', 'phase2'), ('D31', 'phase3')])
def test_actual_other_owner_predicates_remain_dispatched(tmp_path, monkeypatch, row, expected):
    calls, published, rc = exercise(tmp_path, monkeypatch, first=row, last=row)
    assert [x[0] for x in calls] == [expected]
    assert not published and rc == 99


def test_project_admitted_route_may_omit_cli_override(tmp_path, monkeypatch):
    calls, _, rc = exercise(tmp_path, monkeypatch, route=None)
    assert [x[0] for x in calls] == ['phase1'] and rc == 0
    assert '--route' not in calls[0][1] and None not in calls[0][1]
    assert '--complete-retained-metrics' in calls[0][1]


@pytest.mark.parametrize('explicit', [False, True])
def test_public_phase1_resume_survives_actual_row_driver(tmp_path, monkeypatch, explicit):
    import sys
    manifest = tmp_path / 'manifest.json'
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Digital hard-IP')
    manifest.write_text(json.dumps({'features': features}))
    source = tmp_path / 'input'
    source.mkdir()
    (source / 'step_0_5ic_answers.json').write_text(json.dumps({
        'answers': {'deliverable': 'HARDMACRO'}, 'answer_provenance': {
            'deliverable': {'answered_by': 'owner', 'citation': 'Deliver an IP hard macro.'}}}))
    docs = runner._pl.generated_docs_dir(tmp_path)
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text('{}')
    argv = ['runner', str(tmp_path), '--route', 'ip', '--flow109-manifest', str(manifest),
            '--no-dashboard']
    if explicit:
        request = tmp_path / 'resume.json'
        request.write_text(json.dumps({'schema': 'vibeic/minimal-resume-request/1',
            'consumer_step': 'D01', 'explicit_rerun_steps': ['D01'], 'reason': 'Updated design input.'}))
        argv += ['--resume-request', str(request)]
    else:
        argv += ['--entry-step', 'D01', '--exit-step', 'D01']
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(runner, '_activate_runtime_program_tree', lambda *_: None)
    monkeypatch.setattr(runner, '_line_buffer_own_stream', lambda: None)
    calls = []
    class NativeBoundary(Exception):
        pass
    def native(label, program, args, **kwargs):
        calls.append(args)
        raise NativeBoundary
    monkeypatch.setattr(runner, '_run_phase', native)
    with pytest.raises(NativeBoundary):
        runner._main()
    assert len(calls) == 1
    assert ('--complete-retained-metrics' in calls[0]) is not explicit
