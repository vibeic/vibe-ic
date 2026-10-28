"""D25 canonical publication with real retained native evidence, no proof doubles."""
import ast
import copy
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import flow109
import flow109_metric_acceptance as metrics
import vibe_ic_one_shot_runner as runner

pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_D25_RETAINED'),
                                reason='retained actual native model required')


@pytest.fixture
def subject(tmp_path, monkeypatch, request):
    root = Path(os.environ.get('FLOW109_D25_CONTROL_OUTPUT', str(tmp_path)))
    project = root / request.node.name.replace('/', '_')
    retained = Path(os.environ['FLOW109_D25_RETAINED'])
    if request.node.name == 'test_real_unproved_negative_never_claims_a_counterexample':
        # Reuse the genuine prior controlled native invocation. It recorded
        # unproved points and no CEX, so it cannot satisfy a measured-FAIL arm.
        shutil.copytree(os.environ['FLOW109_D25_UNPROVED'], project)
    else:
        shutil.copytree(retained, project)
    features = json.loads((retained / 'flow109-manifest.json').read_text())
    if 'features' in features:
        features = features['features']
    context = flow109.execution_context(flow109.resolve_plan(features), 'D25', 'D25')
    path = project / 'd25-test-context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    return project, context, attempt


def tail(project, child_verdict='PASS'):
    """Execute the actual bounded tail AST; no child/native return is mocked.

    The wrapper envelope is test scaffolding. All LEC substance is consumed
    independently from the copied, real producer packet by the selected owner.
    """
    code = Path(runner.__file__).read_text()
    main = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == '_main')
    block = next(n for n in main.body if isinstance(n, ast.If)
                 and ast.unparse(n.test) == "_p3_skip_by_exit and 'phase2' in reports")
    function = ast.FunctionDef(name='bounded_tail', args=ast.arguments(posonlyargs=[], args=[],
        kwonlyargs=[], kw_defaults=[], defaults=[]), body=[block], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    window = {'declared_window': {'entry_step': '11', 'exit_step': '13'}}
    report = runner._phase_report_path(project, 'phase2_one_shot.json')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(window))
    namespace = {**vars(runner), 'project': project, '_p3_skip_by_exit': True,
        'reports': {'phase2': window}, '_phase_started': {'phase2': 0},
        'plan': [('phase2', child_verdict, 1 if child_verdict == 'FAIL' else 0)],
        'halted_at': 'phase2' if child_verdict == 'FAIL' else '', 'advisories': [],
        '_phase1_checkpoint_review': None, '_fd_disclosures': [],
        'lock': SimpleNamespace(release=lambda: None)}
    exec(compile(module, str(runner.__file__), 'exec'), namespace)
    return namespace['bounded_tail']()


def test_bounded_tail_publishes_current_d25_without_promoting_component_pass(subject):
    project, context, attempt = subject
    rc = tail(project)
    # Parent returned zero and emitted no public D25 receipt: a substantive
    # wrong consumer/public verdict, not a symbol-presence assertion.
    assert rc == 2, {'actual': rc, 'expected': 2}
    published = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert published['component_status'] == 'PASS', published
    assert published['default_row_status'] == 'NOT_MEASURED'
    assert published['completed'] is False and published['delivery_accepted'] is False
    acceptance = published['metric_acceptance']
    assert acceptance['qualification'] == 'NOT_MEASURED'
    assert acceptance['native_tool'] == 'yosys equiv_make+equiv_simple+equiv_induct'
    assert acceptance['qualification_detail']['required_native_steps'] == ['Yosys.EQY']
    assert [o['operator'] for o in acceptance['obligations']] == [
        'covers_all', 'eq', 'matches_adopted_reference']
    assert acceptance['obligations'][1]['observed_value'] == 0
    assert all(o['status'] == 'NOT_MEASURED' for o in acceptance['obligations'])
    result = json.loads((attempt / 'result.json').read_text())
    assert result['default_row_status'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    before = (attempt / 'result.json').read_bytes()
    assert runner._finish_d25_selected_owner(project)['verdict'] == 'NOT_MEASURED'
    assert (attempt / 'result.json').read_bytes() == before


def test_failed_window_survives_valid_unqualified_d25_finalization(subject):
    project, context, attempt = subject
    rc = tail(project, 'FAIL')
    assert rc == 1, {'actual': rc, 'expected': 1}
    summary = json.loads(runner._pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
    assert summary['verdict'] == summary['dispatched_verdict'] == 'FAIL'
    assert summary['phases'][0]['verdict'] == 'FAIL'
    assert summary['d25_finalization']['verdict'] == 'NOT_MEASURED'
    published = json.loads((project / 'reports/flow109/default_rows/D25.json').read_text())
    assert published['component_status'] == 'PASS'
    assert published['default_row_status'] == 'NOT_MEASURED'
    assert published['metric_acceptance']['qualification'] == 'NOT_MEASURED'
    assert published['whole_flow_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage,reason', [
    ('missing', 'D25_NATIVE_EVIDENCE_ABSENT'),
    ('rtl', 'D25_NATIVE_INPUT_STALE'),
    ('netlist', 'D25_NATIVE_INPUT_STALE'),
    ('assumption', 'D25_NATIVE_ASSUMPTIONS_STALE'),
    ('producer', 'D25_NATIVE_PRODUCER_PURPOSE_MISMATCH'),
    ('purpose', 'D25_NATIVE_PRODUCER_PURPOSE_MISMATCH'),
])
def test_actual_consumer_refuses_missing_stale_and_foreign_native_packet(subject, damage, reason):
    project, context, attempt = subject
    report = project / 'reports/lec.json'
    doc = json.loads(report.read_text())
    if damage == 'missing':
        report.unlink()
    elif damage in ('rtl', 'netlist'):
        key = doc['proof_identity']['gold_rtl'][0] if damage == 'rtl' else doc['proof_identity']['gate_netlist']
        path = project / key['path']
        path.write_bytes(path.read_bytes() + b'\n// changed actual controlled input\n')
    else:
        # Deliberately invalid negative copies; never published producer facts.
        if damage == 'assumption':
            doc['proof_identity']['gold_defines'] = '-DUNAPPROVED_TEST_ASSUMPTION'
        elif damage == 'producer':
            doc['program'] = 'unrelated_producer'
        else:
            doc['tool'] = 'Yosys.EQY'
        report.write_text(json.dumps(doc))
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == observed['component_status'] == 'NOT_MEASURED', observed
    assert observed['reason'] == reason, observed
    finalized = runner._finish_d25_selected_owner(project)
    assert finalized['verdict'] == 'NOT_MEASURED'
    assert json.loads((attempt / 'result.json').read_text())['default_row_status'] == 'NOT_MEASURED'


def test_real_unproved_negative_never_claims_a_counterexample(subject):
    project, context, attempt = subject
    doc = json.loads((project / 'reports/lec.json').read_text())
    assert doc['inconclusive'] is True and doc['non_equivalent_points'] == 0
    observed = metrics.accept_d25(project, context)
    assert observed['component_status'] == observed['status'] == 'NOT_MEASURED', observed
    assert observed['native_consumer']['unproven_points'] > 0
    assert observed['native_consumer']['not_measured'] is True
    assert all(o['status'] == 'NOT_MEASURED' for o in observed['obligations'])
    assert runner._finish_d25_selected_owner(project)['verdict'] == 'NOT_MEASURED'
    result = json.loads((attempt / 'result.json').read_text())
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert all(c['completed'] is False for c in result['components'])
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


def test_existing_source_guard_on_changed_production_files(tmp_path):
    import source_chip_agnostic_check as guard
    programs = Path(runner.__file__).parent
    for name in ('vibe_ic_one_shot_runner.py', 'flow109_metric_acceptance.py'):
        target = tmp_path / 'programs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(programs / name, target)
    verdict, findings = guard.audit(tmp_path)
    assert verdict == 'PASS', (verdict, findings)
