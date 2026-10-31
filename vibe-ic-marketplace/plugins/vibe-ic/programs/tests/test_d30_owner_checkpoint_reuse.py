"""Handoff caller controls; real retained checkpoints, no proof/STA dispatch."""
import ast
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from dataclasses import asdict

import pytest
import design_one_shot_runner as runner
import flow109
import step_preflight as preflight


_ACTIVE = False


def no_replay(event, args):
    if not _ACTIVE or event != 'subprocess.Popen':
        return
    argv = list(map(str, args[1]))
    if (Path(argv[0]).name == 'yosys' and argv[1:4] == ['-Q', '-T', '-p']
            and len(argv) == 5 and argv[4].startswith('read_verilog ')
            and argv[4].count(';') == 2 and '; hierarchy -top ' in argv[4]
            and '; write_verilog -noattr ' in argv[4]):
        return  # existing structural normalizer, not synthesis/proof
    raise AssertionError('proof/STA/global-preflight dispatch attempted: ' + str(argv))


sys.addaudithook(no_replay)


@pytest.fixture
def actual(tmp_path, monkeypatch):
    raw = os.environ.get('FLOW109_D30_OWNER_REUSE_PROJECT')
    if not raw:
        pytest.skip('real root-adopted current native37/38 checkpoints required')
    project = Path(raw)
    manifest = json.loads(Path(os.environ['FLOW109_D30_OWNER_REUSE_MANIFEST']).read_text())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'D30', 'D30')
    path = tmp_path / 'context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    import librelane_eqy
    librelane_eqy.d25_sources()
    reached = []

    def producer_boundary(*args, **kwargs):
        assert args[0] == project and args[1] == '14'
        reached.append('existing_handoff_producer')
        raise RuntimeError('SOURCE CONTROL: stop before any producer or carrier write')

    monkeypatch.setattr(runner._spf, 'retained_call', producer_boundary)
    return project, reached


def invoke(project, plan):
    global _ACTIVE
    _ACTIVE = True
    try:
        return runner.step_synthesis_handoff(project, plan=plan)
    finally:
        _ACTIVE = False


def test_actual_handoff_entry_reuses_accepted_native_and_mapped_sdc(actual):
    project, reached = actual
    result = invoke(project, [])
    assert reached == ['existing_handoff_producer'], result
    # The control stops before the producer. No handoff/native PASS fabricated.
    assert result.status == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['native_refusal', 'missing_sdc', 'early_sdc', 'measured_failure'])
def test_handoff_reuse_preserves_known_bad_refusals(actual, monkeypatch, damage):
    project, reached = actual
    plan = []
    if damage == 'native_refusal':
        def refused(*_):
            raise flow109.Flow109Error('FLOW109_D25_PROOF_NOT_ACCEPTED', 'explicit refused native boundary')
        monkeypatch.setattr(flow109, 'dft_preroute_admission', refused)
    elif damage in ('missing_sdc', 'early_sdc'):
        original = runner._current_phase2_consumer
        def current(project, sid, started):
            value = original(project, sid, started)
            if sid != '8':
                return value
            if damage == 'missing_sdc':
                return None
            return {**value, 'result': {**value['result'], 'site': 'step_sdc_validation'}}
        monkeypatch.setattr(runner, '_current_phase2_consumer', current)
    else:
        plan = [runner.StepResult('lec_equivalence', 'FAIL', 0, 'measured failure control')]
    result = invoke(project, plan)
    assert not reached
    assert result.status == 'NOT_MEASURED'


@pytest.mark.parametrize('entry,expected', [('14', 0), ('11', 1)])
def test_actual_main_prunes_proof_chain_before_handoff_entry(tmp_path, entry, expected):
    """Execute real main dispatch AST; chain callback only observes dispatch."""
    tree = ast.parse(Path(runner.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    helpers = {'_site_order', '_before_entry', '_after_exit', '_entry_sentinel', '_exit_sentinel'}
    nodes = [n for n in main.body if isinstance(n, ast.FunctionDef) and n.name in helpers]
    nodes += [next(n for n in main.body if isinstance(n, ast.If) and any(
        isinstance(x, ast.Name) and x.id == 'step_dft_lec_chain' for x in ast.walk(n)))]
    seen = []
    def chain(*args, **kwargs):
        seen.append('proof_chain')
        return [runner.StepResult('lec_equivalence', 'NOT_MEASURED', 0, 'dispatch boundary double',
                                  reason_class='input_absent')]
    sites = preflight.RUNNER_PLANS['design_one_shot_runner'].sites
    env = {'_spf': SimpleNamespace(RUNNER_PLANS=preflight.RUNNER_PLANS,
               gate=lambda p, r, s, refusal, fn, *a, **kw: fn(*a, **kw)),
           '_preflight_refusal': lambda _: None, 'step_dft_lec_chain': chain,
           '_entry_site': preflight.site_for_step('design_one_shot_runner', entry),
           '_exit_pruned': runner._exit_pruned_sites(sites, '14'),
           'StepResult': runner.StepResult, 'args': SimpleNamespace(entry_step=entry,
               exit_step='14', top_name='neutral', container='', skip_phase3=False,
               lec_max_completed_rungs=None, phase3_rederives_top_with_ic_name=None),
           '_analog_absent': False, '_analog_reason': '', 'ic_class': 'neutral',
           'project': tmp_path, 'plan': [], '_run_started_at': 0}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 runner.__file__, 'exec'), env)
    assert len(seen) == expected


@pytest.mark.parametrize('writer,expected', [('PASS', 'PASS'), ('FAIL', 'FAIL'),
    ('NOT_MEASURED', 'NOT_MEASURED'), ('ABSENT', 'NOT_MEASURED'), ('FOREIGN', 'NOT_MEASURED')])
def test_real_main_exit_forwards_fresh_delivery_to_only_canonical_writer(
        tmp_path, monkeypatch, writer, expected):
    """Actual main statements with explicit writer API doubles, not row credit."""
    tree = ast.parse(Path(runner.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    nodes = []
    selected = False
    for node in main.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
                and t.id == '_owner_context' for t in node.targets):
            nodes.append(node)
            selected = True
        elif selected and isinstance(node, ast.If) and any(isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == 'finish_native_window'
                for n in ast.walk(node)):
            nodes.append(node)
            break
    context = tmp_path / 'context.json'
    context.write_text('{}')
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context))
    owner = {'requested_step': 'D30', 'context_sha256': 'c' * 64}
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda _: owner)
    receipt = {'path': 'reports/flow109/attempts/control/d30_delivery.json', 'sha256': 'a' * 64}
    row = runner.StepResult('synthesis_handoff', 'PASS', 0, 'explicit fresh-owner boundary double',
                            extras={'d30_delivery_receipt': receipt})
    seen = []
    def finish(project, report, output):
        seen.append(report)
        own = next(r for r in report['steps'] if r['name'] == 'synthesis_handoff')
        assert own['extras']['step_id'] == '14'
        assert own['extras']['d30_delivery_receipt'] == receipt
        assert own['extras']['context_sha256'] == owner['context_sha256']
        if writer == 'ABSENT':
            return None
        status = 'PASS' if writer == 'FOREIGN' else writer
        return {'schema': 'vibeic.flow109.window-attempt-result.v1',
            'default_row_status': status, 'whole_flow_acceptance': 'NOT_MEASURED',
            'delivery_accepted': False, 'components': [{
                'step_id': 'D25' if writer == 'FOREIGN' else 'D30',
                'context_sha256': owner['context_sha256'],
                'default_row_status': status, 'completed': status == 'PASS'}]}
    monkeypatch.setattr(flow109, 'finish_native_window', finish)
    env = {'os': os, 'Path': Path, 'json': json, 'asdict': asdict, '_bounded': True,
           'project': tmp_path, 'out': tmp_path / 'owner.json', 'plan': [row], 'summary': {},
           '_run_started_at': 0, '_dispatch_invocation_context': None,
           '_aggregate_verdict': lambda plan, **_: plan[-1].status,
           '_write_phase2_report': lambda *a, **kw: None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 runner.__file__, 'exec'), env)
    assert len(seen) == 1
    assert row.status == expected
    assert row.extras['completed'] is (expected == 'PASS')
