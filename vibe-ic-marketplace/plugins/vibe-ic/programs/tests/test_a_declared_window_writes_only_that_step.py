#!/usr/bin/env python3
"""A run that declares a window writes only that window's own work.

R-0924-1, the owner's ask: when a gate is wrong, re-run THAT step -- only it. The window was already honoured for DISPATCH; the FINALIZE
TAIL was not, and no flag reached it.

MEASURED before this change, on a copy of benchmark-data/ic/subservient at main
69abc2734, `design_one_shot_runner . --entry-step 4 --exit-step 4`:
    766 files touched, 432 of them OUTSIDE step 4's own workspace
    23 flow_compliance_check invocations, 3 of them over the WHOLE flow
    reports/final_summary.md republished with a fence reading "Steps: 70 total"
for a run that dispatched one step. The leak is not the window: every
out-of-window dispatch site correctly reports NOT_APPLICABLE and names the flag
that pruned it.

WHAT THESE ARMS PIN. Each one fails if the tail is re-enabled for a bounded run:
the five `emit_final_summary` sites, the whole-flow `final_audit`, the
declared-producer sweep, the two gate-identity sweeps and the whole-tree steps
view. The behavioural arms drive the real narrowing predicates rather than
grepping for them, because a source substring cannot tell you a branch bites.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from _runner_ast_fixture import called_main, live_nodes

PROGRAMS = Path(__file__).resolve().parent.parent
RUNNER = PROGRAMS / "design_one_shot_runner.py"


def _load(name: str):
    # Consumers import the canonical module during execution. Replacing its
    # public name here disconnects their producer from fixtures collected
    # earlier in the same pytest process.
    fixture_name = f"_declared_window_{name}"
    spec = importlib.util.spec_from_file_location(fixture_name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[fixture_name] = mod  # dataclass annotations need this identity
    spec.loader.exec_module(mod)
    return mod


def test_window_fixture_preserves_the_canonical_consumer_module():
    import phase3_one_shot_runner as canonical

    isolated = _load("phase3_one_shot_runner")
    assert isolated is not canonical
    assert sys.modules["phase3_one_shot_runner"] is canonical
    import phase3_one_shot_runner as consumer
    assert consumer is canonical


def _main_node() -> ast.FunctionDef:
    tree = ast.parse(RUNNER.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("design_one_shot_runner.main not found")


def _calls(node: ast.AST):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


@pytest.mark.parametrize('damage,expected', [
    ('current', 'PASS'), ('missing', 'NOT_MEASURED'),
    ('old', 'NOT_MEASURED'), ('source', 'NOT_MEASURED'),
    ('output', 'NOT_MEASURED'), ('unbound', 'NOT_MEASURED'),
    ('partial', 'NOT_MEASURED'), ('failed', 'FAIL'),
])
def test_step4_skeleton_retires_only_for_current_complete_consumer(
        tmp_path, monkeypatch, damage, expected):
    """Source fold control with a mocked consumer, never native qualification.

    The bytes and canonical row are real neutral data; the complete consumer
    is supplied at its existing API boundary to isolate observation lifecycle.
    """
    import hashlib
    import execution_backend_gates as gates
    import execution_backend_worker as worker
    import step_output_collector as versions
    import _flow_yaml
    dsr = _load('design_one_shot_runner')
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '4')
    files = {
        'phase2/stage1/rtl/window_logic.v': 'module window_logic(input a, output y); assign y=a; endmodule\n',
        'phase1/generated_docs/L10_TEST_CASES.json': '{"test_cases": [{"id": "selector", "kind": "functional_vector", "inputs": {"a": 1}, "expected_outputs": {"y": 1}}]}',
        'phase1/generated_docs/L12_BEHAVIORAL_SEQUENCES.json': '{"sequences": [{"id": "selector"}]}',
    }
    for rel, data in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    output_rels = [spec.split(' OR ')[0].replace('**', 'neutral').replace('*', 'neutral')
                   for spec in row['required_outputs']]
    for rel in output_rels:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('source-only consumer boundary fixture\n')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    accepted = {
        'id': '4', 'status': 'PASS', 'canonical_pass': True, 'capture_errors': [],
        'inputs': worker._declared_input_files(tmp_path, row['required_inputs']),
        'outputs': [{'rel': rel, 'sha256': sha(tmp_path / rel)} for rel in output_rels],
        'result': {'canonical_consumer': {
            'status': 'PASS', 'step': {'id': '4', 'status': 'PASS',
                'output_binding': {'n_specs': 3, 'n_satisfied': 3,
                                   'n_step_attributed': 3, 'n_project_glob': 0}},
            'outputs': gates.contracts(tmp_path, row)}},
    }
    if damage == 'source':
        (tmp_path / next(iter(files))).write_text('module changed; endmodule\n')
    elif damage == 'output':
        (tmp_path / output_rels[0]).write_text('changed output\n')
    elif damage == 'unbound':
        accepted['result']['canonical_consumer']['step']['output_binding']['n_step_attributed'] = 0
    elif damage == 'partial':
        accepted['canonical_pass'] = False
    current = [] if damage in ('missing', 'old') else [accepted]
    monkeypatch.setattr(versions, 'current_acceptance', lambda project, began: current)
    skeleton = dsr.StepResult('full_stack_tb_gen', 'NOT_MEASURED',
                              reason_class='no_population')
    oracle = dsr.StepResult('reference_tb', 'PASS', extras={'functional_verified': True})
    plan = [skeleton, oracle]
    if damage == 'failed':
        plan.insert(0, dsr.StepResult('full_stack_tb_gen', 'FAIL', detail='actual mismatch'))
    assert dsr._aggregate_verdict(plan, project=tmp_path, started_at=time.time()-1) == expected
    assert skeleton.status == 'NOT_MEASURED' and skeleton.reason_class == 'no_population'
    # A Step5 population remains owed even with an accepted Step4 consumer.
    assert dsr._aggregate_verdict(plan + [dsr.StepResult(
        'full_stack_functional_tb', 'NOT_MEASURED', reason_class='input_absent')],
        project=tmp_path, started_at=time.time()-1) == ('FAIL' if damage == 'failed' else 'NOT_MEASURED')


@pytest.mark.parametrize('entry,exit_step,expected', [
    ('11', '14', {'11', '12', '13', '14'}),
    ('11', '13', {'11', '12', '13'}),
])
def test_phase2_window_plans_the_requested_handoff(entry, exit_step, expected):
    import step_preflight as spf
    dsr = _load('design_one_shot_runner')
    sites = spf.RUNNER_PLANS['design_one_shot_runner'].sites
    entry_site = spf.site_for_step('design_one_shot_runner', entry)
    names = [n for n, _ in sites]
    sentinels = names[:names.index(entry_site)] + dsr._exit_pruned_sites(sites, exit_step)
    assert dsr.dispatched_step_ids(sites, sentinels) == expected


@pytest.mark.parametrize('entry,exit_step,bounded,expected', [
    ('11', '14', True, ['synthesis_handoff']),
    ('11', '13', True, []),
    (None, None, False, []),  # unbounded retains its established audit-tail owner
])
def test_bounded_handoff_reaches_existing_scoped_producer(
        tmp_path, entry, exit_step, bounded, expected):
    """Actual main dispatch statements; callbacks are source-wiring evidence."""
    from types import SimpleNamespace
    import step_preflight as spf
    dsr = _load('design_one_shot_runner')
    sites = spf.RUNNER_PLANS['design_one_shot_runner'].sites
    seen = []
    helpers = {'_site_order', '_before_entry', '_after_exit', '_entry_sentinel', '_exit_sentinel'}
    nodes = []
    for node in _main_node().body:
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            nodes.append(node)
        elif isinstance(node, ast.If) and any(isinstance(n, ast.Name)
                and n.id == 'step_synthesis_handoff' for n in ast.walk(node)):
            nodes.append(node)
    def handoff(*a, **kw):
        seen.append('synthesis_handoff')
        return dsr.StepResult('synthesis_handoff', 'NOT_MEASURED', reason_class='input_absent')
    env = {'_spf': SimpleNamespace(RUNNER_PLANS=spf.RUNNER_PLANS,
               gate=lambda p, r, s, refusal, fn, *a, **k: fn(*a, **k)),
           '_preflight_refusal': lambda name: None, '_bounded': bounded,
           '_entry_site': spf.site_for_step('design_one_shot_runner', entry) if entry else None,
           '_exit_pruned': dsr._exit_pruned_sites(sites, exit_step) if exit_step else [],
           'args': SimpleNamespace(entry_step=entry, exit_step=exit_step),
           'StepResult': dsr.StepResult, 'step_synthesis_handoff': handoff,
           'project': tmp_path, 'plan': [], '_run_started_at': time.time()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(RUNNER), 'exec'), env)
    assert seen == expected
    if seen:
        assert dsr._aggregate_verdict(env['plan']) == 'NOT_MEASURED'


@pytest.mark.parametrize("entry,exit_site,expected", [
    (None, None, ["asic_sdc", "sdc_validation", "yosys_synth"]),
    ("yosys_synth", None, ["sdc_validation", "yosys_synth"]),
    ("dft_lec_chain", None, []),
    (None, "rtl_validate", []),
    (None, "yosys_synth", ["asic_sdc", "sdc_validation", "yosys_synth"]),
])
def test_resume_does_not_repeat_upstream_synthesis(entry, exit_site, expected):
    """Drive the real dispatch branches; an admitted checkpoint is supplied.

    The tool callbacks stand in for expensive native programs. Only dispatch
    and upstream preservation are under test; no EDA PASS is manufactured.
    """
    from types import SimpleNamespace
    main = _main_node()
    names = {"_site_order", "_before_entry", "_after_exit", "_exit_sentinel"}
    nodes = [n for n in main.body if isinstance(n, ast.FunctionDef)
             and n.name in names]
    for node in main.body:
        if not isinstance(node, ast.If):
            continue
        text = ast.unparse(node)
        if ("_before_entry('asic_sdc'" in text
                or "plan.append(step_sdc_validation(project))" in text
                or "_spf.gate(" in text and "'yosys_synth'" in text):
            nodes.append(node)
    tree = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    sites = (('rtl_gen', ('1',)), ('rtl_validate', ('2', '3')),
             ('sim', ('4',)), ('asic_sdc', ('7',)),
             ('yosys_synth', ('9',)), ('dft_lec_chain', ('11', '12', '13')))
    called = []
    untouched = {"netlist": b"valid checkpoint netlist"}
    def producer(name):
        def run(*_args, **_kwargs):
            called.append(name)
            if name == 'yosys_synth':
                untouched['netlist'] = b'new synthesis output'
            return SimpleNamespace(name=name, status='PASS')
        return run
    env = {
        '_spf': SimpleNamespace(RUNNER_PLANS={
            'design_one_shot_runner': SimpleNamespace(sites=sites)},
            gate=lambda _project, _runner, _site, _refusal, fn, *a, **kw: fn(*a)),
        '_execution': SimpleNamespace(_ordinary_runtime={'policy': {'mode': 'default'}}),
        '_entry_site': entry,
        '_exit_pruned': [name for name, _ in sites][
            [name for name, _ in sites].index(exit_site) + 1:] if exit_site else [],
        'StepResult': lambda name, status, duration, detail, **kw: SimpleNamespace(
            name=name, status=status, detail=detail, **kw),
        'step_asic_sdc': producer('asic_sdc'),
        'step_sdc_validation': producer('sdc_validation'),
        'step_yosys_synth': producer('yosys_synth'),
        '_preflight_refusal': lambda *_: None,
        'args': SimpleNamespace(entry_step='11' if entry else None,
                                exit_step='2' if exit_site else None,
                                top_name='unit_top', container='host', pdk='unit_pdk'),
        'project': Path('/supplied/checkpoint'), 'ic_class': {},
        '_analog_absent': False, '_analog_reason': '', 'plan': [],
    }
    exec(compile(tree, str(RUNNER), 'exec'), env)
    assert called == expected
    if entry == 'dft_lec_chain':
        assert untouched['netlist'] == b'valid checkpoint netlist'
        row = next(r for r in env['plan'] if r.name == 'yosys_synth')
        assert row.status == 'NOT_APPLICABLE'
        assert 'upstream' in row.detail


@pytest.mark.parametrize("window,queried,verdict", [
    (None, ("1", "4", "5"), "NOT_MEASURED"),
    ({"11", "12", "13"}, (), "PASS"),
    ({"4"}, ("4",), "NOT_MEASURED"),
    ({"1", "2", "3"}, ("1",), "NOT_MEASURED"),
])
def test_ai_review_is_required_for_the_dispatched_window(window, queried, verdict):
    """Earlier pending reviews cannot demote a different bounded operation.

    Whole-flow and in-window pending reviews remain mandatory.
    """
    from types import SimpleNamespace
    nodes = []
    for node in _main_node().body:
        text = ast.unparse(node)
        if (isinstance(node, ast.Assign) and text.startswith('_ai_steps =')
                or isinstance(node, ast.If) and '_ai_steps = tuple' in text
                or isinstance(node, ast.Assign) and "summary['ai_judgements'] =" in text
                or isinstance(node, ast.Expr) and '_ai_judgement.demote_runner_rows' in text
                or isinstance(node, ast.If) and text.startswith("if summary['ai_judgements'] and")):
            nodes.append(node)
    seen = []
    def pending(_project, steps):
        seen.append(steps)
        return [{'step_id': s, 'status': 'AWAITING_SIGNED_JUDGEMENT'} for s in steps]
    env = {'project': Path('/supplied/checkpoint'), '_bounded': window is not None,
           '_window_step_ids': lambda: window,
           '_ai_judgement': SimpleNamespace(pending=pending,
               demote_runner_rows=lambda *_: None),
           'summary': {'steps': [], 'verdict': 'PASS'}}
    tree = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(tree, str(RUNNER), 'exec'), env)
    assert seen == [queried]
    assert env['summary']['verdict'] == verdict


def _dotted(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    if isinstance(f, ast.Name):
        return f.id
    return ""


@pytest.mark.parametrize("child_verdict,child_rc,fresh,expected_rc", [
    ("PASS", 0, True, 0),
    ("FAIL", 1, True, 1),
    ("NOT_MEASURED", 1, True, 1),
    ("PASS", 0, False, 1),
    ("PASS", 1, True, 1),
])
def test_frontdoor_checkpoint_rc_answers_for_fresh_dispatched_work(
        tmp_path, child_verdict, child_rc, fresh, expected_rc):
    """Drive the actual front-door return branch, including failure controls."""
    from types import SimpleNamespace
    runner = PROGRAMS / "vibe_ic_one_shot_runner.py"
    main = called_main(ast.parse(runner.read_text()))
    branch = next((n for n in main.body if isinstance(n, ast.If)
                   and ast.unparse(n.test) == "_p3_skip_by_exit and 'phase2' in reports"), None)
    assert branch is not None, "front door still lets whole-flow state fail a checkpoint operation"
    captured = {}
    frontdoor = _load("vibe_ic_one_shot_runner")
    env = {
        '_p3_skip_by_exit': True, 'project': tmp_path,
        'reports': {'phase2': {'declared_window': {
            'entry_step': '11', 'exit_step': '13',
            'dispatched_step_ids': ['11', '12', '13']},
            'verdict': child_verdict, 'ai_judgements': {}}},
        'plan': [('phase1', 'SKIPPED', 0), ('phase2', child_verdict, child_rc),
                 ('analog', 'SKIPPED', 0), ('phase3', 'SKIPPED', 0)],
        '_phase_started': {'phase2': 1.0}, '_roll_up': frontdoor._roll_up,
        '_phase_report_path': lambda *_: tmp_path / 'phase2.json',
        '_pl': SimpleNamespace(published_here=lambda *_: fresh,
                               report_path=lambda *_: tmp_path / 'frontdoor.json'),
        '_delivery_route': SimpleNamespace(report_label=lambda *_: {'route': 'ic'}),
        '_write_runner_summary': lambda _out, summary, _project: captured.update(summary),
        'lock': SimpleNamespace(release=lambda: None),
    }
    function = ast.FunctionDef(name='operation', args=ast.arguments(
        posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=[branch], decorator_list=[])
    tree = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(tree, str(runner), 'exec'), env)
    assert env['operation']() == expected_rc
    assert captured['bounded'] is True
    assert captured['whole_flow_verdict'] == 'NOT_MEASURED'
    assert captured['audit_verdict'] == 'NOT_MEASURED'
    if expected_rc == 0:
        assert captured['dispatched_verdict'] == 'PASS'
        assert captured['verdict'] == 'NOT_MEASURED'
        # The benchmark entry consumer still recognizes canonical entry,
        # while this partial operation cannot become a whole-flow PASS.
        guard = _load('vibe_ic_entry_guard')
        report = tmp_path / 'frontdoor.json'
        report.write_text(json.dumps(captured))
        assert guard._is_orchestrator_report(report, tmp_path)


def _guarded_by_bounded(root: ast.AST, target: str) -> bool:
    """Is EVERY call to `target` inside `root` reached only through a test that
    reads `_bounded`? Walks If nodes rather than trusting indentation."""
    found = [c for c in _calls(root) if _dotted(c) == target]
    if not found:
        return False
    guarded = []
    for node in ast.walk(root):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "_bounded" not in names:
            continue
        for branch in (node.body, node.orelse):
            for stmt in branch:
                guarded.extend(c for c in _calls(stmt) if _dotted(c) == target)
    return all(any(g is c for g in guarded) for c in found)


# --------------------------------------------------------------------------- #
# -2. the window question is asked of what THIS runner can bound
# --------------------------------------------------------------------------- #
def test_an_exit_inside_phase_3_does_not_bound_the_front_door():
    """Review w6wr2g6di MEDIUM 1. `window_is_effective` with runner=None walks
    EVERY plan, and phase 3's site heads are synth 9, pnr 15, gds 37, drc 31,
    lvs 31 -- so `--exit-step 23/31/33` looks like pruning. But the front door
    never forwards a window to phase 3, so phase 3 runs IN FULL and a front door
    that called itself bounded published "dispatched only its declared window"
    for a 70-step run."""
    spf = _load("step_preflight")
    D = "design_one_shot_runner"
    for exit_step in ("23", "31", "33"):
        assert spf.window_is_effective(exit_step=exit_step) is True, (
            f"the runner=None form must still answer for the whole flow "
            f"({exit_step})")
        assert spf.window_is_effective(exit_step=exit_step, runner=D) is False, (
            f"--exit-step {exit_step} prunes no phase-2 site; it must not bound "
            f"a phase-2 dispatch")
    # and the values that DO prune phase 2 still answer yes in both forms
    for exit_step in ("2", "4", "9"):
        assert spf.window_is_effective(exit_step=exit_step, runner=D) is True


def _assert_front_door_window(src):
    main = called_main(ast.parse(src))
    calls = [c for c in live_nodes(main) if isinstance(c, ast.Call)
             if _dotted(c).endswith("window_is_effective")]
    assert calls, "the front door no longer asks the window question at all"
    for c in calls:
        kw = {k.arg for k in c.keywords}
        assert "runner" in kw, (
            f"line {c.lineno}: the front door asks the FLOW-WIDE form; an exit "
            f"inside phase 3's spans would read as pruning while phase 3 runs "
            f"in full")
        runner_kw = next(k for k in c.keywords if k.arg == "runner")
        assert isinstance(runner_kw.value, ast.Constant) and \
            runner_kw.value.value == "design_one_shot_runner", (
            "the front door must scope the question to the phase it can bound")
    # Phase 3 now receives the physical-design cut, but a flag alone cannot
    # make the front door bounded.  The child must have published a fresh
    # bounded report from this invocation before the top-level tail is pruned.
    statements = {ast.unparse(n) for n in live_nodes(main)
                  if isinstance(n, (ast.Assign, ast.AugAssign))}
    assert "p3_args += ['--entry-step', '9', '--exit-step', str(args.exit_step)]" in statements
    assert any(s.startswith('_p3_window_ran = bool(_p3_forward_window and rep.get(\'bounded\')')
               and "rep.get('window_run_id') == window_run_id" in s
               for s in statements)
    assert '_fd_bounded = _fd_bounded or _p3_window_ran or _p3_skip_by_exit' in statements


def test_the_front_door_asks_the_phase2_scoped_question():
    """Phase-2 and Phase-3 windows use their own dispatch signals."""
    _assert_front_door_window((PROGRAMS / "vibe_ic_one_shot_runner.py").read_text())


def test_dispatched_step_ids_come_from_the_runs_own_record(_=None):
    """Review w6wr2g6di MEDIUM 2, DRIVEN.

    The site table says every site upstream of the entry is skipped. The
    dispatch code only asks that for `rtl_gen` and `rtl_validate` -- the only two
    `_before_entry` guards -- so with `--entry-step 9` the `sim` site, which
    guards on `_after_exit` alone, DISPATCHES while the table excludes step 4.
    Quoting the table made `declared_window.dispatched_step_ids` a false
    statement and would have left step 4's steps-view row unrefreshed after
    running it."""
    dsr = _load("design_one_shot_runner")
    spf = _load("step_preflight")
    sites = spf.RUNNER_PLANS["design_one_shot_runner"].sites

    # nothing sentinelled -> everything dispatched
    assert dsr.dispatched_step_ids(sites, set()) == {"1", "2", "3", "4", "7", "9",
                                                    "11", "12", "13", "14"}
    # the --entry-step 9 reality: the run books sentinels for the two guarded
    # sites only, so step 4 IS dispatched and must be reported as dispatched
    ids = dsr.dispatched_step_ids(sites, {"rtl_gen", "rtl_validate"})
    assert "4" in ids, (
        "step 4 ran and was reported out-of-window -- the table's answer, not "
        "the run's")
    assert ids == {"4", "7", "9", "11", "12", "13", "14"}
    # an exit sentinel removes its whole span
    assert dsr.dispatched_step_ids(sites, {"yosys_synth", "dft_lec_chain", "synthesis_handoff"}) == \
        {"1", "2", "3", "4", "7"}
    assert dsr.dispatched_step_ids((), {"anything"}) == set()


def test_the_id_derivation_reads_the_plan_and_not_the_entry_predicate():
    """The closure must feed it the run's sentinels, never `_before_entry`."""
    main = _main_node()
    fn = next((n for n in ast.walk(main) if isinstance(n, ast.FunctionDef)
               and n.name == "_window_step_ids"), None)
    assert fn is not None, "_window_step_ids is gone"
    body = ast.unparse(fn)
    assert "_before_entry" not in body, (
        "the id derivation still asks the site TABLE which sites the entry "
        "precedes; the dispatch code only asks that for two of five sites")
    assert "plan" in body and "declared_by" in body, (
        "the derivation must read the run's own sentinel rows")
    assert "dispatched_step_ids" in body, (
        "it must delegate to the drivable module-level function")


# --------------------------------------------------------------------------- #
# -1. what a bounded run's rc does NOT decide
# --------------------------------------------------------------------------- #
def test_the_benchmark_scorers_contract_reads_the_report_row_never_rc(tmp_path):
    """A bounded run's rc answers for its declared window only, and the scorer
    never asks it.

    THE RULING THIS PINS (R-0924-1, after the r2 review). Every solve the harness
    dispatches carries a window -- `_solver_argv` sends --exit-step 2/4/9 or
    --entry-step 2, all of which prune real sites -- so on a bounded run a
    whole-flow phase-2 audit FAIL would be a verdict over the ~69 steps that did
    not run. It is booked NOT_APPLICABLE instead, which means rc can differ from
    base for a solve whose ONLY failure was that audit. That is safe for scoring
    for one reason, and this arm is that reason: the scorer's contract reads the
    REPORT ROW, not the exit code.

    MEASURED on a benchmark-shaped solve before and after the change: rc 1 both
    ways, 32 step rows both ways, and the `rtl_gen` row byte-identical."""
    bd = _load("benchmark_dispatch")
    fn = bd._rtl_gen_waive
    args = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    assert args == ("project",), (
        f"the handover contract now takes {args}; if an exit code is ever one of "
        f"them, a bounded run's rc starts deciding a scoring question")

    rep = tmp_path / "reports" / "orchestrator" / "phase2_one_shot.json"
    rep.parent.mkdir(parents=True)

    def write(verdict, rows):
        rep.write_text(json.dumps({"verdict": verdict, "steps": rows}) + "\n")

    waived = [{"name": "rtl_gen", "status": "WAIVED", "detail": "handed over",
               "extras": {"fallback_skill": "rtl-author"}}]
    write("PASS", waived)
    got = fn(tmp_path)
    assert got == {"fallback_skill": "rtl-author", "detail": "handed over"}, got

    # THE ROW DECIDES, NOT THE RUN'S VERDICT. Same row under a FAIL roll-up --
    # which is what a bounded run whose window failed publishes -- same answer.
    write("FAIL", waived)
    assert fn(tmp_path) == got, "the handover moved with the roll-up verdict"
    write("NOT_MEASURED", waived)
    assert fn(tmp_path) == got

    # and no row means no handover, whatever the verdict claims
    write("PASS", [])
    assert fn(tmp_path) is None
    write("PASS", [{"name": "rtl_gen", "status": "WAIVED", "extras": {}}])
    assert fn(tmp_path) is None, (
        "a WAIVED row without fallback_skill is not a handover")


# --------------------------------------------------------------------------- #
# 0. the decision itself — DRIVEN, and bound to nothing else
# --------------------------------------------------------------------------- #
def test_declared_window_flags_reports_what_the_operator_typed():
    """The flags are the DISCLOSURE's subject, not the decision's. Whether the
    window prunes anything is a separate question — see
    test_a_flag_that_prunes_nothing_is_not_a_window, which is the property review
    w437hob32 corrected: an earlier version of this arm asserted that any flag
    bounds the run, and that is false for `--exit-step 13` and `--entry-step 1`."""
    dsr = _load("design_one_shot_runner")
    assert dsr.declared_window_flags("4", None) == ("--entry-step 4",)
    assert dsr.declared_window_flags(None, "4") == ("--exit-step 4",)
    assert dsr.declared_window_flags("4", "4") == ("--entry-step 4", "--exit-step 4")
    assert dsr.declared_window_flags(None, None) == ()


def test_a_flag_that_prunes_nothing_is_not_a_window():
    """DRIVEN, review w437hob32 MEDIUM. This runner's last dispatch site heads
    step 11, and the front door forwards --exit-step 13/23/31/33/37 verbatim.
    Such a run dispatches the WHOLE phase exactly as a flagless run does, so its
    whole-flow documents are exactly as true — and treating it as bounded booked
    the phase-2 audit NOT_APPLICABLE, which run_verdict reads as green, so an
    audit FAIL a flagless run would raise DISAPPEARED."""
    dsr = _load("design_one_shot_runner")
    order = ["rtl_gen", "rtl_validate", "sim", "asic_sdc", "yosys_synth", "dft_lec_chain"]
    # nothing pruned, entry at the first site (or absent) -> NOT bounded
    assert dsr.run_is_bounded(None, [], order) is False
    assert dsr.run_is_bounded(None, None, order) is False
    assert dsr.run_is_bounded("rtl_gen", [], order) is False
    # real pruning, or an entry that moved off the first site -> bounded
    assert dsr.run_is_bounded(None, ["dft_lec_chain"], order) is True
    assert dsr.run_is_bounded("sim", [], order) is True
    assert dsr.run_is_bounded("sim", ["yosys_synth"], order) is True


def test_the_flag_level_rule_agrees_with_the_dispatch_level_one():
    """ANTI-DRIFT. `run_is_bounded` asks the run's dispatch signals;
    `step_preflight.window_is_effective` asks the same question of the flags,
    for the front door, which decides before any runner has those signals. Two
    spellings of one rule is how they come to disagree, so this pins them over
    the windows that actually occur — benchmark_dispatch sends --exit-step 2/4/9
    and --entry-step 2; the front door forwards 13/23/31/33/37."""
    dsr = _load("design_one_shot_runner")
    spf = _load("step_preflight")
    RUNNER = "design_one_shot_runner"
    plan = spf.RUNNER_PLANS[RUNNER]
    order = [n for n, _ in plan.sites]
    for exit_step in ("2", "4", "9", "11", "13", "23", "31", "33", "37"):
        pruned = spf.exit_pruned_sites(plan.sites, exit_step) or []
        assert dsr.run_is_bounded(None, pruned, order) == \
            spf.window_is_effective(exit_step=exit_step, runner=RUNNER), exit_step
    for entry_step in ("1", "2", "4", "9"):
        site = spf.site_for_step(RUNNER, entry_step)
        assert dsr.run_is_bounded(site, [], order) == \
            spf.window_is_effective(entry_step=entry_step, runner=RUNNER), entry_step
    assert spf.window_is_effective() is False


def _assert_front_door_tail(src):
    """Review w437hob32 MEDIUM: the entry the owner actually uses forwarded the
    window and then ran its own tail unconditionally, so the leak survived and
    the phase-2 report's `not_refreshed_here` was contradicted on disk moments
    later by THIS runner rewriting the file it named."""
    main = called_main(ast.parse(src))
    for target in ("_pl.emit_final_summary", "_pl.emit_steps_view"):
        calls = [c for c in live_nodes(main) if isinstance(c, ast.Call)
                 and _dotted(c) == target]
        assert calls, f"{target} vanished from the front door"
        guarded = []
        for node in live_nodes(main):
            if not isinstance(node, ast.If):
                continue
            if isinstance(node.test, ast.Name) and node.test.id == "_fd_bounded":
                branch = node.orelse
            elif (isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
                  and isinstance(node.test.operand, ast.Name)
                  and node.test.operand.id == "_fd_bounded"):
                branch = node.body
            else:
                continue
            for stmt in branch:
                guarded.extend(c for c in live_nodes(stmt) if isinstance(c, ast.Call)
                               and _dotted(c) == target)
        assert all(any(g is c for g in guarded) for c in calls), (
            f"{target} runs at the front door without consulting _fd_bounded")
    binds = [n for n in live_nodes(main) if isinstance(n, ast.Assign)
             and any(isinstance(tg, ast.Name) and tg.id == "_fd_bounded"
                     for tg in n.targets)]
    assert binds, "_fd_bounded is never computed"
    assert not any(isinstance(b.value, ast.Constant) and b.value.value
                   for b in binds), (
        "_fd_bounded is bound to a truthy literal; the tail is unconditionally "
        "skipped and every arm here still passes")


def test_the_front_door_bounds_its_own_tail():
    _assert_front_door_tail((PROGRAMS / "vibe_ic_one_shot_runner.py").read_text())


@pytest.mark.parametrize("body", [
    "return 0", "return 0\n    return _main()",
    "if False:\n        return _main()\n    return 0",
    "def unused():\n        return _main()\n    return 0",
])
def test_an_uncalled_implementation_cannot_satisfy_front_door_checks(body):
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    lines = src.splitlines(keepends=True)
    lines[main.lineno - 1:main.end_lineno] = [f"def main():\n    {body}\n"]
    changed = ''.join(lines)
    for check in (_assert_front_door_window, _assert_front_door_tail):
        with pytest.raises(AssertionError, match="does not return"):
            check(changed)


@pytest.mark.parametrize("mutation", ["scope", "argv", "guard"])
def test_front_door_checks_reject_scope_argv_and_guard_regressions(mutation):
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    if mutation == "scope":
        old, new = 'runner="design_one_shot_runner"', 'runner="phase3_one_shot_runner"'
        check = _assert_front_door_window
    elif mutation == "argv":
        old, new = 'p3_args += ["--entry-step", "9", "--exit-step", str(args.exit_step)]', 'p3_args += []'
        check = _assert_front_door_window
    else:
        old, new = 'if _fd_bounded:\n        _fd_disclose("emit_final_summary"', 'if not _fd_bounded:\n        _fd_disclose("emit_final_summary"'
        check = _assert_front_door_tail
    assert old in src
    with pytest.raises(AssertionError):
        check(src.replace(old, new))


def test_refresh_only_does_not_rewrite_the_runs_own_report():
    """HIGH, review w437hob32. MEASURED before the fix: a bounded run's report
    carrying 36 step rows, `declared_window` and 5 disclosures was replaced by a
    2-row document. benchmark_dispatch reads that exact file and walks steps[]
    for the rtl_gen WAIVED row's `extras.fallback_skill`, so the erasure also
    destroys the AI-backup handover contract."""
    tree = ast.parse(RUNNER.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_run_refresh_only")
    called = {_dotted(c) for c in _calls(fn)}
    assert "_pl.publish_report_then_steps_view" not in called, (
        "--refresh-only publishes its summary to the RUN's report path, erasing "
        "the verdicts of a run it measured none of")
    # NAMING the run report is fine and wanted -- the refresh PRINTS that it
    # left the file alone. Passing it to anything else is the defect.
    strings = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for call in _calls(fn):
        if _dotted(call) == "print":
            continue
        for arg in ast.walk(call):
            if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    and "phase2_one_shot" in arg.value):
                raise AssertionError(
                    f"--refresh-only passes the run report's name to "
                    f"{_dotted(call)!r} at line {call.lineno}")
    assert any("phase2_one_shot" in s for s in strings), (
        "the refresh should SAY it left the run report alone")
    assert "_pl.emit_steps_view" in called, (
        "the refresh must still rebuild the view, against the report on disk")
    assert any("refresh_only.json" in s for s in strings), (
        "the refresh must publish its own record")


def test_bounded_is_computed_by_that_function_and_never_a_constant():
    """THE ARM THAT BITES THE OBVIOUS MUTATION.

    Every guard in the finalize tail reads `_bounded`. An arm that only checks
    `step_final_audit` sits inside `if _bounded:` stays GREEN when someone
    writes `_bounded = False` and re-enables the whole tail — MEASURED: that
    one-line mutation left 15 of these 16 arms green before this arm existed.
    So the BINDING is pinned too: `_bounded` is assigned exactly once in
    main(), from a call to the drivable decision, never from a literal."""
    main = _main_node()
    binds = [n for n in ast.walk(main)
             if isinstance(n, ast.Assign)
             and any(isinstance(tg, ast.Name) and tg.id == "_bounded"
                     for tg in n.targets)]
    assert len(binds) == 1, (
        f"_bounded is assigned {len(binds)} times in main() "
        f"(lines {[b.lineno for b in binds]}); one guard cannot be reasoned "
        f"about if the flag is rebound")
    value = binds[0].value
    assert not isinstance(value, ast.Constant), (
        f"_bounded is bound to the literal {getattr(value, 'value', '?')!r} at "
        f"line {binds[0].lineno}: the whole finalize tail is re-enabled and "
        f"every structural arm here still passes")
    assert isinstance(value, ast.Call) and _dotted(value) == "run_is_bounded", (
        "_bounded must come from run_is_bounded, the decision a test can drive")
    flags = [n for n in ast.walk(main)
             if isinstance(n, ast.Assign)
             and any(isinstance(tg, ast.Name) and tg.id == "_window_flags"
                     for tg in n.targets)]
    assert len(flags) == 1 and isinstance(flags[0].value, ast.Call), (
        "_window_flags must be computed once, by declared_window_flags")


# --------------------------------------------------------------------------- #
# 1. the five report-card sites
# --------------------------------------------------------------------------- #
def test_no_site_in_main_calls_emit_final_summary_directly():
    """Every site goes through the bounded-aware helper.

    `emit_final_summary` runs final_report_generate.py, which defaults to
    run_audit=True: each call costs a whole-flow `flow_compliance_check
    --strict`. Five call sites were unconditional, and a bounded run reached
    two of them."""
    main = _main_node()
    helper = next((n for n in ast.walk(main)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_emit_final_summary_or_disclose"), None)
    assert helper is not None, "the bounded-aware helper is gone"
    inside_helper = {id(c) for c in _calls(helper)}
    direct = [c for c in _calls(main)
              if _dotted(c) == "_pl.emit_final_summary"
              and id(c) not in inside_helper]
    assert direct == [], (
        f"{len(direct)} site(s) in main() still call _pl.emit_final_summary "
        f"directly (lines {[c.lineno for c in direct]}); a bounded run reaches "
        f"them and pays for a whole-flow audit it did not ask for")
    routed = [c for c in _calls(main)
              if _dotted(c) == "_emit_final_summary_or_disclose"]
    assert len(routed) == 5, (
        f"expected the 5 known call sites to be routed, found {len(routed)}")


def test_the_helper_refuses_to_write_the_report_card_when_bounded():
    """Driven, not read: the helper returns False and discloses, and the
    document is not written."""
    helper = next((n for n in ast.walk(_main_node())
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_emit_final_summary_or_disclose"), None)
    assert helper is not None, "the bounded-aware helper is gone"
    body = ast.unparse(helper)
    assert "_bounded" in body, (
        "the helper does not consult the window at all")
    assert "_disclose_whole_flow_skip" in body, (
        "the helper skips the report card without disclosing that it did")
    assert "return False" in body, (
        "the bounded branch must report that no summary was written, so the "
        "run's own `final summary:` line cannot claim one")


# --------------------------------------------------------------------------- #
# 2. the whole-flow audit, the producer sweep
# --------------------------------------------------------------------------- #
def test_the_whole_flow_final_audit_is_guarded_by_the_window():
    """A whole-flow verdict over a tree 69 of whose 70 steps did not run is the
    PREVIOUS run's state re-attributed to this one."""
    assert _guarded_by_bounded(_main_node(), "_audit_after_declared_producers"), (
        "the whole-flow audit is reachable without consulting _bounded")


def test_the_declared_producer_sweep_is_guarded_by_the_window():
    """Every path from main to the all-step producer sweep is bounded."""
    tree = ast.parse(RUNNER.read_text())
    helper = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "_audit_after_declared_producers"), None)
    assert helper is not None, "the declared-producer audit helper was not found"
    assert "flow_declared_producer_run.py" in ast.dump(helper), (
        "the bounded guard no longer encloses the declared-producer sweep")

    def own_calls(fn):
        # ast.walk(main) also enters nested function definitions that main may
        # never call. Count their calls only through the call graph below.
        class Calls(ast.NodeVisitor):
            def __init__(self):
                self.found = []

            def visit_FunctionDef(self, node):
                pass

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                self.found.append(node)
                self.generic_visit(node)

        visitor = Calls()
        for stmt in fn.body:
            visitor.visit(stmt)
        return visitor.found

    def runs_sweep(call):
        return any(isinstance(n, ast.Constant)
                   and n.value == "flow_declared_producer_run.py"
                   for n in ast.walk(call))

    functions = {fn.name: fn for fn in ast.walk(tree)
                 if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    reaches_sweep = {name for name, fn in functions.items()
                     if any(runs_sweep(c) for c in own_calls(fn))}
    while True:
        callers = {name for name, fn in functions.items()
                   if any(_dotted(c) in reaches_sweep for c in own_calls(fn))}
        expanded = reaches_sweep | callers
        if expanded == reaches_sweep:
            break
        reaches_sweep = expanded

    main = functions["main"]
    sweep_calls = [c for c in own_calls(main)
                   if runs_sweep(c) or _dotted(c) in reaches_sweep]
    assert sweep_calls, "the declared-producer sweep call was not found in main()"
    guarded = set()
    for node in ast.walk(main):
        if not isinstance(node, ast.If):
            continue
        if "_bounded" not in {n.id for n in ast.walk(node.test)
                              if isinstance(n, ast.Name)}:
            continue
        for stmt in (*node.body, *node.orelse):
            # Keep the same branch rule as the original universal guard.
            visitor = ast.Module(body=[stmt], type_ignores=[])
            guarded.update(id(c) for c in own_calls(visitor))
    unguarded = [c.lineno for c in sweep_calls if id(c) not in guarded]
    assert not unguarded, (
        f"the declared-producer sweep runs without consulting _bounded "
        f"at main() line(s) {unguarded}")


def test_the_narrowed_refreshes_are_disclosed_as_narrowed_not_as_skipped():
    """A narrowing is not a skip. The gate-identity sweep and the steps view
    still RUN on a bounded run, over this run's own work, and a reader told
    only about the skips would read their smaller output as a loss."""
    main = _main_node()
    narrowed = set()
    for c in _calls(main):
        if _dotted(c) != "_disclose_narrowed_refresh":
            continue
        assert c.args and isinstance(c.args[0], ast.Constant)
        narrowed.add(c.args[0].value)
    assert narrowed == {"stamp_gate_reports", "steps_view"}, narrowed
    src = RUNNER.read_text()
    assert '"kind": "narrowed"' in src and '"kind": "skipped"' in src, (
        "the two kinds must be distinguishable in the record")


def test_the_run_report_carries_the_window_and_the_disclosures():
    """The report is where a reader learns what this run did NOT do."""
    src = RUNNER.read_text()
    for key in ('"declared_window"', '"bounded_disclosures"',
                '"not_refreshed_here"', '"dispatched_step_ids"'):
        assert key in src, f"the run report does not carry {key}"
    assert "_pl.published_here(project / _rel, _run_started_at)" in src, (
        "staleness of the whole-flow documents is decided by something other "
        "than the one owner of that question")


def test_the_disclosed_refresh_names_are_exactly_the_approved_set():
    """The operator is owed a disclosure per refresh, by name."""
    main = _main_node()
    names = set()
    for c in _calls(main):
        if _dotted(c) != "_disclose_whole_flow_skip":
            continue
        assert c.args and isinstance(c.args[0], ast.Constant), (
            "a disclosure whose name is computed cannot be audited")
        names.add(c.args[0].value)
    assert names == {"emit_final_summary", "final_audit",
                     "flow_declared_producer_run"}, names


# --------------------------------------------------------------------------- #
# 3. the narrowed gate-identity sweeps — DRIVEN
# --------------------------------------------------------------------------- #
def test_the_stamp_sweep_skips_a_gate_json_this_run_did_not_write(tmp_path):
    """`written_after` narrows the sweep to the jsons THIS invocation wrote.

    The unnarrowed sweep re-dates every gate json in the tree, including ones a
    bounded run has no business rewriting."""
    dsr = _load("design_one_shot_runner")
    gates = tmp_path / "reports" / "phase2" / "gates"
    gates.mkdir(parents=True)
    old = gates / "some_gate.json"
    old.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    stale = time.time() - 10_000
    os.utime(old, (stale, stale))

    skipped = dsr._stamp_gate_report_dirs(tmp_path, written_after=time.time())
    assert skipped == [], (
        f"a bounded sweep stamped {skipped}, a file written before the run")

    swept = dsr._stamp_gate_report_dirs(tmp_path, written_after=None)
    assert [Path(s).name for s in swept] == ["some_gate.json"], (
        f"the unnarrowed sweep must still stamp everything; got {swept}")


def test_the_stamp_sweep_still_stamps_what_this_run_did_write(tmp_path):
    """The narrowing must not turn the sweep off — a fresh json is stamped."""
    dsr = _load("design_one_shot_runner")
    gates = tmp_path / "reports" / "phase2" / "gates"
    gates.mkdir(parents=True)
    started = time.time()
    fresh = gates / "fresh_gate.json"
    fresh.write_text(json.dumps({"verdict": "PASS"}) + "\n")

    swept = dsr._stamp_gate_report_dirs(tmp_path, written_after=started)
    assert [Path(s).name for s in swept] == ["fresh_gate.json"], (
        f"a gate json this run wrote must still be stamped; got {swept}")


# --------------------------------------------------------------------------- #
# 4. the bounded steps view — DRIVEN
# --------------------------------------------------------------------------- #
def test_a_bounded_steps_view_carries_the_rows_it_did_not_refresh(tmp_path):
    """"The step's own row only" must not mean "delete the rest of the view".

    A partial index that dropped the other rows would also arm
    `_prune_stale_folders` to delete their folders — a bounded refresh turning
    into a deletion of the whole tree."""
    soc = _load("step_output_collector")
    steps_root = tmp_path / "steps"
    prior = steps_root / "phase1" / "stage_phase1" / "9_older_step"
    prior.mkdir(parents=True)
    (prior / "outputs.json").write_text("{}\n")
    steps_root.mkdir(parents=True, exist_ok=True)
    (steps_root / "index.json").write_text(json.dumps({"steps": [
        {"id": "9", "name": "older step", "status": "PASS", "phase": "phase1",
         "stage": "stage_phase1", "folder": "phase1/stage_phase1/9_older_step",
         "n_outputs": 0}]}) + "\n")

    res = soc.materialize(tmp_path, only_steps={"4"})
    idx = json.loads((steps_root / "index.json").read_text())
    ids = {r["id"]: r for r in idx["steps"]}

    assert "9" in ids, (
        "the row this call did not refresh was dropped; a reader of steps/ "
        "after a bounded run is owed the tree they had before it")
    assert ids["9"].get("refreshed_here") is False, (
        "a carried row must say it was not refreshed here")
    assert prior.is_dir(), "a bounded refresh DELETED an out-of-window folder"
    assert res["bounded_to"] == ["4"]
    assert idx["not_refreshed_here"] == ["9"]


def test_a_whole_flow_steps_view_is_byte_identical_to_before(tmp_path):
    """only_steps=None must keep the unbounded payload exactly as it was: no
    `refreshed_here`, no `bounded_to`, and pruning still armed."""
    soc = _load("step_output_collector")
    res = soc.materialize(tmp_path)
    idx = json.loads((tmp_path / "steps" / "index.json").read_text())
    assert set(idx.keys()) == {"steps"}, (
        f"the whole-flow index grew keys: {sorted(idx.keys())}")
    assert all("refreshed_here" not in r for r in idx["steps"])
    assert "bounded_to" not in res and "n_not_refreshed" not in res


def test_only_steps_naming_nothing_is_refused():
    """An empty window is a typo, not a request to refresh zero steps."""
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "step_output_collector.py"),
         str(PROGRAMS), "--only-steps", " , "],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, (r.returncode, r.stdout[-400:], r.stderr[-400:])
    assert "names no step id" in r.stderr


# --------------------------------------------------------------------------- #
# 5. ONE staleness rule, and the refresh the operator can ask for
# --------------------------------------------------------------------------- #
def test_published_here_has_one_owner_and_the_front_door_asks_it():
    """#2572/#2575's freshness predicate, asked by both readers.

    The bounded run needs it for arbitrary paths; the front door needs it for a
    phase report. Two implementations is how two staleness rules come to
    disagree about one file."""
    pl = _load("_path_layout")
    assert callable(pl.published_here) and hasattr(pl, "FRESHNESS_TOLERANCE_S")
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "_pl.published_here(" in src, (
        "the front door stopped asking the owner and grew its own copy")
    fn = src.index("def _published_here")
    body = src[fn:src.index("\ndef ", fn + 10)]
    assert "st_mtime" not in body, (
        "the phase-report reader re-implements the mtime comparison instead of "
        "delegating to the owner")


def test_published_here_fails_closed(tmp_path):
    pl = _load("_path_layout")
    started = time.time()
    f = tmp_path / "doc.md"
    f.write_text("x")
    assert pl.published_here(f, started) is True
    old = started - 10_000
    os.utime(f, (old, old))
    assert pl.published_here(f, started) is False
    assert pl.published_here(tmp_path / "absent.md", started) is False
    assert pl.published_here(tmp_path, started) is False   # a directory


def test_refresh_only_refuses_a_window(tmp_path):
    """A refresh of the whole flow has no window."""
    r = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path),
         "--refresh-only", "--exit-step", "4"],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, (r.returncode, r.stdout[-500:])
    assert "has no window" in r.stderr


def test_refresh_only_dispatches_no_step():
    """It restates what is on disk; it must not be able to produce design
    evidence."""
    src = RUNNER.read_text()
    fn = src.index("def _run_refresh_only")
    body = src[fn:src.index("\ndef main(", fn)]
    for forbidden in ("step_rtl_gen", "step_yosys_synth", "step_verilator_coverage",
                      "step_dft_lec_chain", "step_sim"):
        assert forbidden not in body, (
            f"--refresh-only dispatches {forbidden}; it must refresh documents "
            f"only")
    assert '"dispatched_steps": []' in body


@pytest.mark.parametrize("entry,exit_step,expected", [
    ("7", "9", []),
    ("9", "9", []),
    ("2", "2", ["crosslayer", "lint", "pad_budget", "arith_decl", "frontend"]),
    ("4", "4", ["reference", "functional", "arith_decl", "coverage", "frontend"]),
    (None, None, ["crosslayer", "lint", "pad_budget", "reference", "functional", "qsf", "fpga_sdc", "arith_decl", "coverage", "frontend"]),
    ("1", "13", ["crosslayer", "lint", "pad_budget", "reference", "functional", "qsf", "fpga_sdc", "arith_decl", "coverage", "frontend"]),
])
def test_main_dispatch_respects_selected_frontend_ownership(
        tmp_path, entry, exit_step, expected, board_requested=False):
    """Execute the actual main call sites, with failing upstream callbacks.

    Native tools are replaced here; the real window predicates, dispatched
    statements, result objects and aggregate consumer are retained. The normal
    public-input CLI separately measures native execution of the fixed window.
    """
    from types import SimpleNamespace
    import step_preflight as spf

    dsr = _load("design_one_shot_runner")
    sites = spf.RUNNER_PLANS['design_one_shot_runner'].sites
    entry_site = spf.site_for_step('design_one_shot_runner', entry) if entry else None
    pruned = dsr._exit_pruned_sites(sites, exit_step) if exit_step else []
    called = []

    def producer(name):
        def run(*_args, **_kwargs):
            called.append(name)
            # A selected failing producer must survive the aggregate. A tool
            # outside the window must never get the chance to fail this run.
            return dsr.StepResult(name, 'FAIL', 0.0, 'measured callback failure')
        return run

    callbacks = {
        'step_rtl_lint_tool': 'lint', 'step_reference_tb': 'reference',
        'step_step4_functional_evidence': 'functional',
        'step_qsf_gen': 'qsf', 'step_sdc_gen': 'fpga_sdc',
        'step_verilator_coverage': 'coverage', '_complete_phase2_frontend': 'frontend',
        'step_otp_image_check': 'otp', 'step_fpga_compile': 'compile',
        'step_fpga_burn': 'burn', 'step_usb_hid_tester_verify': 'board_test',
        'step_crosslayer_rewrite_fidelity': 'crosslayer',
        'step_slot_pad_budget': 'pad_budget', 'step_arith_declaration_emit': 'arith_decl',
    }
    helper_names = {'_site_order', '_before_entry', '_after_exit',
                    '_exit_sentinel', '_entry_sentinel', '_window_step_ids', '_step_requested'}
    nodes = []
    for node in _main_node().body:
        if isinstance(node, ast.FunctionDef):
            if node.name in helper_names:
                nodes.append(node)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in (
                    'rtl_repair_retry', 'last_rtl_hash',
                    'rtl_repair_remediation_attempted', '_early_declaration') for t in targets):
                nodes.append(node)
                continue
        names = {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)}
        if names.intersection(callbacks):
            nodes.append(node)
    assert nodes, 'main has no executable dispatch statements'
    plan = []
    env = {
        **{name: producer(label) for name, label in callbacks.items()},
        '_spf': spf, '_entry_site': entry_site, '_exit_pruned': pruned,
        '_bounded': dsr.run_is_bounded(entry_site, pruned, [n for n, _ in sites]),
        'dispatched_step_ids': dsr.dispatched_step_ids,
        '_window_flags': dsr.declared_window_flags(entry, exit_step),
        'StepResult': dsr.StepResult, 'project': tmp_path, 'plan': plan,
        '_sim_rows': [], '_adopted_step4_producer': lambda *args: None,
        'args': SimpleNamespace(entry_step=entry, exit_step=exit_step,
                                top_name='unit_top', container='LOCAL', pdk='unit_pdk',
                                skip_hardware=not board_requested, max_rtl_repair_retries=0),
        'ic_class': {}, '_rtl_dir_sha256': lambda *_: 'unchanged input',
        '_rtl_gen_handoff': lambda *_: {}, 'declaration_before_step4': lambda *_: {},
        '_disclose_whole_flow_skip': lambda *args: 'outside declared ownership',
        '_disclose_runs_anyway': lambda *_: None,
        '_V': dsr._V,
        '_refuse_a_disagreeing_declaration': dsr._refuse_a_disagreeing_declaration,
    }
    # The fixture executes supplementary call sites only. Stage the canonical
    # site-head sentinels from the real helpers first; those earlier site heads
    # are outside this extraction and the report now reads their actual rows.
    helpers = [n for n in nodes if isinstance(n, ast.FunctionDef)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=helpers, type_ignores=[])),
                 str(RUNNER), 'exec'), env)
    for site, _ in sites:
        if env['_before_entry'](site, entry_site):
            plan.append(env['_entry_sentinel'](site))
        elif env['_after_exit'](site):
            plan.append(env['_exit_sentinel'](site))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(RUNNER), 'exec'), env)
    assert called == expected
    assert dsr._aggregate_verdict(plan) == ('FAIL' if expected else 'NOT_MEASURED')
    if entry in ('7', '9'):
        assert env['_window_step_ids']().isdisjoint({'2', '3', '4', '6'})
        assert all(row.status == 'NOT_APPLICABLE' for row in plan)


def test_main_window_omits_board_dispatch_even_when_hardware_is_requested(tmp_path):
    test_main_dispatch_respects_selected_frontend_ownership(
        tmp_path, '7', '9', [], board_requested=True)


@pytest.mark.parametrize("entry,exit_step,expected", [
    ("4", "9", ["reference", "functional", "qsf", "fpga_sdc", "arith_decl", "coverage", "frontend"]),
    ("4", "sim", ["reference", "functional", "arith_decl", "coverage", "frontend"]),
])
def test_declared_numeric_gap_retains_fpga_preparation(tmp_path, entry, exit_step, expected):
    test_main_dispatch_respects_selected_frontend_ownership(
        tmp_path, entry, exit_step, expected)


@pytest.mark.parametrize("entry,exit_step,expected", [
    ("4", "9", ["reference", "functional", "qsf", "fpga_sdc", "otp", "board_test", "arith_decl", "coverage", "frontend"]),
    ("4", "4", ["reference", "functional", "arith_decl", "coverage", "frontend"]),
    ("7", "9", []),
])
def test_declared_numeric_gap_honors_hardware_request(tmp_path, entry, exit_step, expected):
    test_main_dispatch_respects_selected_frontend_ownership(
        tmp_path, entry, exit_step, expected, board_requested=True)


def test_recorded_window_does_not_hide_an_accidental_dispatch():
    """A missing sentinel is observable even when the requested entry is later."""
    from types import SimpleNamespace
    import step_preflight as spf
    dsr = _load("design_one_shot_runner")
    fn = next(n for n in ast.walk(_main_node()) if isinstance(n, ast.FunctionDef)
              and n.name == '_window_step_ids')
    env = {'_spf': spf, 'dispatched_step_ids': dsr.dispatched_step_ids,
           'plan': [dsr.StepResult('rtl_gen', 'NOT_APPLICABLE', 0, '', declared_by='--entry-step 9'),
                    dsr.StepResult('rtl_validate', 'NOT_APPLICABLE', 0, '', declared_by='--entry-step 9')],
           '_entry_site': 'yosys_synth', '_before_entry': lambda *_: True,
           '_after_exit': lambda *_: False}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 str(RUNNER), 'exec'), env)
    assert env['_window_step_ids']() == {'4', '7', '9', '11', '12', '13', '14'}


@pytest.mark.parametrize("entry,exit_step,selected", [
    (None, "D1", False),
    ("7", "9", False),
    ("1", "1", True),
    (None, None, True),
])
def test_real_rtl_alias_leaves_follow_their_owned_dispatch_span(
        tmp_path, entry, exit_step, selected):
    """Actual main statements/predicates and both real absent-RTL readers.

    Only these owning dispatch statements are extracted; no alias leaf is
    mocked and no signed checkpoint, full main/frontdoor or IC run is claimed.
    """
    from dataclasses import asdict
    from types import SimpleNamespace
    import step_preflight as spf

    dsr = _load("design_one_shot_runner")
    sites = spf.RUNNER_PLANS['design_one_shot_runner'].sites
    entry_site = spf.site_for_step('design_one_shot_runner', entry) if entry else None
    pruned = dsr._exit_pruned_sites(sites, exit_step) if exit_step else []
    targets = {'step_leaf_typo_aliases', 'step_reset_clock_variant_aliases'}
    helpers = {'_site_order', '_before_entry', '_after_exit',
               '_exit_sentinel', '_entry_sentinel'}
    nodes = []
    for node in _main_node().body:
        if isinstance(node, ast.FunctionDef):
            if node.name in helpers:
                nodes.append(node)
            continue
        calls = {n.func.id for n in ast.walk(node)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        if calls & targets:
            nodes.append(node)
    assert sum(not isinstance(n, ast.FunctionDef) for n in nodes) == 2
    plan = []
    env = {'_spf': spf, '_entry_site': entry_site, '_exit_pruned': pruned,
           'StepResult': dsr.StepResult, 'project': tmp_path, 'plan': plan,
           'args': SimpleNamespace(entry_step=entry, exit_step=exit_step,
                                   top_name='unit_top'),
           'step_leaf_typo_aliases': dsr.step_leaf_typo_aliases,
           'step_reset_clock_variant_aliases': dsr.step_reset_clock_variant_aliases}
    assert not dsr._pl.rtl_dir(tmp_path).is_dir()
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(RUNNER), 'exec'), env)
    observation = {'scope': 'Actual extracted main alias dispatch, real window predicates and real no-RTL leaves; not full main or signed-D1/frontdoor replay',
                   'entry': entry, 'exit_step': exit_step,
                   'rows': [asdict(row) for row in plan]}
    (tmp_path / 'REAL_ALIAS_WINDOW_OBSERVATION.json').write_text(
        json.dumps(observation, indent=2) + '\n')
    assert [row.name for row in plan] == ['leaf_typo_aliases', 'reset_clock_variant_aliases']
    assert [row.status for row in plan] == [
        'NOT_MEASURED' if selected else 'NOT_APPLICABLE'] * 2, observation
    if selected:
        assert all(row.reason_class == dsr._V.ReasonClass.INPUT_ABSENT for row in plan)
        assert all(row.detail == 'no rtl/ directory yet' for row in plan)
        assert dsr._aggregate_verdict(plan) == 'NOT_MEASURED'
    else:
        assert all(row.declared_by == (
            '--exit-step D1' if exit_step == 'D1' else '--entry-step 7') for row in plan)
    # A measured failure still outranks any unmeasured or out-of-window rows.
    fail = dsr.StepResult('measured_control', 'FAIL', 0.0, 'measured software failure')
    assert dsr._aggregate_verdict([fail, *plan]) == 'FAIL'
    assert not dsr._pl.rtl_dir(tmp_path).exists()
