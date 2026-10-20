"""The handoff checker owns its reports, while synthesis owns its netlist."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _flow_yaml
import execution_backend_gates as gates
import execution_policy as policy
import flow_compliance_check as compliance
import flow_declared_producer_run as producers
import step_preflight as preflight
import test_matrix_d5_deps_correct as dependencies
from test_step9_step14_read_the_pnr_netlist import _project, _mapped


REPORTS = [
    'reports/phase2/gates/yosys_hilomap.json',
    'reports/phase2/gates/yosys_script_template.json',
    'reports/phase2/gates/yosys_tiecell_recipe_order.json',
]


def handoff():
    return next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '14')


def test_post_dft_has_no_forward_dependency_on_the_handoff_checker():
    graph = dependencies.derived_dependencies('12')
    assert not any(producer == '14' for producer, _, _ in graph), graph
    assert any(producer == '9' for producer, _, _ in graph), graph


@pytest.mark.parametrize('target', REPORTS)
def test_current_handoff_produces_its_own_report_on_first_execution(tmp_path, target):
    project = _project(tmp_path, mapped_text=_mapped())
    record = producers.run_for_step(project, '14', timeout=30)
    assert (project / target).is_file(), record
    report = json.loads((project / target).read_text())
    assert report, 'the checker must write a substantive report'
    assert target in handoff()['required_outputs']
    assert any(row['target'] == target and row['executed'] for row in record['results'])


def test_retained_handoff_keeps_the_previous_synthesis_input(tmp_path, monkeypatch):
    project = _project(tmp_path, mapped_text=_mapped())
    netlist = project / 'phase2/stage2/synth/netlist.v'
    original = netlist.read_bytes()
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(gates, 'contracts', lambda *a: {'control_fixture': {}})
    monkeypatch.setattr(gates, 'evaluate', lambda project, row: {
        'status': 'PASS', 'ledger': [], 'step': {'id': '14', 'status': 'PASS'}})
    def check(project):
        assert netlist.read_bytes() == original
        return SimpleNamespace(name='handoff', status='PASS', detail='control checker', extras={})
    preflight.retained_call(project, '14', check, project, canonical_acceptance=True)
    assert netlist.read_bytes() == original


def test_handoff_cannot_accept_reports_without_its_synthesis_input(tmp_path):
    project = _project(tmp_path, mapped_text=_mapped())
    for relative in REPORTS + ['reports/analog/stage_analog_compliance.json']:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"verdict":"PASS"}')
    (project / 'phase2/stage2/synth/netlist.v').unlink()
    result = compliance.check_step(project, handoff(), {}, skip_analog=True)
    assert result.status != 'PASS', result


@pytest.mark.parametrize('upstream,missing,expected', [
    ('PASS', '9', 'NOT_MEASURED'),
    ('PASS', '13', 'NOT_MEASURED'),
    ('FAIL', None, 'FAIL'),
])
def test_bounded_handoff_keeps_missing_dependencies_and_real_lec_failure(
        tmp_path, monkeypatch, upstream, missing, expected):
    """Drive the live bounded main dispatch; no dependency PASS is persisted."""
    import ast
    from _runner_ast_fixture import called_main
    import design_one_shot_runner as runner
    sites = preflight.RUNNER_PLANS['design_one_shot_runner'].sites
    main = called_main(ast.parse(Path(runner.__file__).read_text()))
    helpers = {'_site_order', '_before_entry', '_after_exit', '_entry_sentinel', '_exit_sentinel'}
    nodes = []
    for node in main.body:
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            nodes.append(node)
        elif isinstance(node, ast.If) and any(isinstance(n, ast.Name)
                and n.id == 'step_synthesis_handoff' for n in ast.walk(node)):
            nodes.append(node)
    if hasattr(runner, '_current_phase2_consumer'):
        monkeypatch.setattr(runner, '_current_phase2_consumer',
                            lambda p, sid, began: None if sid == missing else {'source_only_dependency': sid})
    def forbidden(*a, **k):
        raise AssertionError('blocked Step14 reached its producer')
    monkeypatch.setattr(producers, 'run_for_step', forbidden)
    plan = [runner.StepResult('lec_equivalence', upstream)]
    env = {'_spf': SimpleNamespace(RUNNER_PLANS=preflight.RUNNER_PLANS,
               gate=lambda p, r, s, refusal, fn, *a, **k: fn(*a, **k)),
           '_preflight_refusal': lambda name: None,
           '_bounded': True, '_entry_site': 'dft_lec_chain',
           '_exit_pruned': runner._exit_pruned_sites(sites, '14'),
           'StepResult': runner.StepResult, 'project': tmp_path, 'plan': plan,
           'args': SimpleNamespace(entry_step='11', exit_step='14'),
           'step_synthesis_handoff': getattr(runner, 'step_synthesis_handoff', forbidden)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 runner.__file__, 'exec'), env)
    assert runner._aggregate_verdict(plan) == expected
    assert not (tmp_path / producers.REPORT_REL).exists()
    if upstream == 'FAIL':
        assert plan[0].status == 'FAIL'


# Public handoff transport controls.  The existing neutral fixture is explicitly
# producer-shaped source data, not a claim that Yosys or an IC run executed.
def _default_handoff_audit(project, monkeypatch):
    import design_one_shot_runner as runner
    import os
    import hashlib

    # This public fixture declares only a digital buffer.  The unchanged
    # analog intent reviewer needs that explicit INPUT, not an absent L5.
    l5 = project / 'phase1/generated_docs/L5_ADI_SPEC.json'
    l5.parent.mkdir(parents=True, exist_ok=True)
    l5.write_text(json.dumps({'no_analog': True,
                             'analog_blocks_detected': False,
                             'analog_blocks': []}) + '\n')
    capture = os.environ.get('R3140_PUBLIC_INPUTS')
    if capture:
        case = os.environ['PYTEST_CURRENT_TEST'].removesuffix(' (call)')
        target = Path(capture) / (hashlib.sha256(case.encode()).hexdigest() + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'test': case, 'files': {
            p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(project.rglob('*')) if p.is_file()}}, sort_keys=True) + '\n')

    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', {
        'project': str(project), 'policy': {'mode': 'default'},
        'parameters': {'skip_analog': True}})
    monkeypatch.setattr(runner, '_finish_selected_interface_currentness',
                        lambda _: runner.StepResult('phase1_currentness', 'NOT_APPLICABLE',
                            declared_by='public control scopes its consumer to Step14'))
    monkeypatch.setattr(runner._pl, 'emit_final_summary', lambda *args: None)
    observed = []

    def audit(actual_project, phase, skip_analog):
        assert actual_project == project and phase == 2 and skip_analog is True
        result = gates.evaluate(project, handoff())
        observed.append(result)
        if capture:
            target.with_suffix('.consumer.json').write_text(json.dumps(result, indent=2) + '\n')
        return runner.StepResult('final_audit', result['status'],
                                 extras={'selected_step14': result},
                                 reason_class=result['step'].get('reason_class', ''),
                                 declared_by=result['step'].get('declared_by', ''))

    monkeypatch.setattr(runner, 'step_final_audit', audit)
    result = runner._audit_after_declared_producers(project, True)
    assert len(observed) == 1
    return result, observed[0]


@pytest.mark.parametrize('prior_role', ['absent', 'audit'])
def test_default_phase2_caller_produces_step14_before_its_consumer(
        tmp_path, monkeypatch, prior_role):
    from test_step14_report_producer_authorship import project_fixture, actual_cli, WRITERS
    import _gate_authorship as authorship

    project, _ = project_fixture(tmp_path)
    if prior_role == 'audit':
        for writer, relative in zip(WRITERS, REPORTS):
            cp, doc = actual_cli(project, writer, project / relative,
                                 authorship.ROLE_AUDIT)
            assert cp.returncode == 0 and doc['invoked_as'] == 'audit'
    original = (project / 'phase2/stage2/synth/netlist.v').read_bytes()
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] == 'PASS', consumer
    receipt = json.loads((project / producers.REPORT_REL).read_text())
    assert receipt['schema'] == 'vibeic/current-step-producer-census/1'
    assert receipt['step_id'] == '14' and receipt['verdict'] == 'PRODUCED'
    assert receipt['executed'] == receipt['declared_clauses'] == 4
    assert all(row['rc'] == 0 and row['authorship'] == 'producer'
               for row in receipt['results'])
    assert all(json.loads((project / r).read_text())['invoked_as'] == 'producer'
               for r in REPORTS)
    assert (project / 'phase2/stage2/synth/netlist.v').read_bytes() == original
    # The existing explicit API retains its input/content-bound reuse after
    # the real caller's first production; it must not rerun unchanged reports.
    reused = producers.run_for_step(project, '14', timeout=30)
    assert reused['verdict'] == 'PRODUCED' and reused['executed'] == 0
    assert reused['already_produced_by_the_run'] == 4
    produced_bytes = {relative: (project / relative).read_bytes() for relative in REPORTS}
    repeated = gates.evaluate(project, handoff())
    assert repeated['status'] == 'PASS', repeated
    assert produced_bytes == {relative: (project / relative).read_bytes()
                              for relative in REPORTS}
    for relative in REPORTS:
        verdict = project / relative.replace('.json', '_verdict.json')
        assert verdict.is_file()
        assert json.loads(verdict.read_text())['invoked_as'] == 'audit'


def test_default_phase2_caller_does_not_create_step14_from_absent_netlist(
        tmp_path, monkeypatch):
    from test_step14_report_producer_authorship import project_fixture
    project, _ = project_fixture(tmp_path)
    (project / 'phase2/stage2/synth/netlist.v').unlink()
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] != 'PASS'
    assert not any((project / r).exists() for r in REPORTS)


def test_default_phase2_caller_keeps_changed_native_input_blocking(
        tmp_path, monkeypatch):
    from test_step14_report_producer_authorship import project_fixture
    project, _ = project_fixture(tmp_path)
    source = project / 'phase2/stage1/rtl/core.v'
    source.write_text(source.read_text() + '// changed input after synthesis\n')
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] == 'FAIL', consumer
    assert (project / REPORTS[0]).is_file(), 'no first-production report exists'
    report = json.loads((project / REPORTS[0]).read_text())
    assert report['verdict'] == 'FAIL'
    assert report['reason_class'] == 'tool_handoff_invalid'
    receipt = json.loads((project / producers.REPORT_REL).read_text())
    assert receipt['step_id'] == '14' and receipt['invalid_results']


def test_default_phase2_caller_does_not_relabel_audit_invocation(
        tmp_path, monkeypatch):
    from test_step14_report_producer_authorship import project_fixture
    import _gate_authorship as authorship
    project, _ = project_fixture(tmp_path)
    monkeypatch.setenv(authorship.ROLE_ENV, authorship.ROLE_AUDIT)
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] != 'PASS'
    assert all((project / r).is_file() and
               json.loads((project / r).read_text())['invoked_as'] == 'audit'
               for r in REPORTS)
    receipt = json.loads((project / producers.REPORT_REL).read_text())
    assert receipt['step_id'] == '14' and receipt['verdict'] == 'INCOMPLETE'


def test_default_phase2_caller_preserves_actual_checker_finding(
        tmp_path, monkeypatch):
    from test_step14_report_producer_authorship import project_fixture, GOOD
    project, _ = project_fixture(tmp_path, recipe=GOOD.replace('setundef -zero\n', ''))
    _default_handoff_audit(project, monkeypatch)
    receipt = json.loads((project / producers.REPORT_REL).read_text())
    assert receipt.get('step_id') == '14', 'selected report producer was not invoked'
    row = next(row for row in receipt['results']
               if row['program'] == 'yosys_tiecell_recipe_order_check')
    assert row['rc'] == 1 and row['enforcement'] == 'advisory'
    report = json.loads((project / row['target']).read_text())
    assert report['verdict'] == 'VIOLATION' and report['violations']


def test_default_phase2_caller_does_not_start_synthesis_for_analog_compliance(
        tmp_path, monkeypatch):
    import design_one_shot_runner as runner
    project = tmp_path / 'analog_only'
    project.mkdir()
    # No digital handoff exists: merely requesting the final audit must not
    # select Step14, even when its analog-compliance clause could run alone.
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(runner, '_finish_selected_interface_currentness',
                        lambda _: runner.StepResult('phase1_currentness', 'NOT_APPLICABLE',
                            declared_by='public control scopes its consumer to Step14'))
    monkeypatch.setattr(runner._pl, 'emit_final_summary', lambda *args: None)
    seen = []
    def audit(*args, **kwargs):
        receipt = json.loads((project / producers.REPORT_REL).read_text())
        seen.append(receipt)
        return runner.StepResult('final_audit', 'NOT_APPLICABLE',
                                 declared_by='public INPUT has no digital synthesis track')
    monkeypatch.setattr(runner, 'step_final_audit', audit)
    result = runner._audit_after_declared_producers(project, True)
    assert result.status == 'NOT_APPLICABLE'
    assert seen[0].get('schema') != 'vibeic/current-step-producer-census/1'
    assert not any((project / r).exists() for r in REPORTS)
    assert not (project / 'phase2/stage2/synth/netlist.v').exists()


def _latest_retained_handoff(project):
    import step_output_collector as versions
    rows = [row for row in versions._read_index(project)['steps']
            if str(row['id']) == '14']
    assert len(rows) == 1, 'the normal Default caller must retain Step14 itself'
    folder = versions._versions_root(project) / rows[0]['folder']
    record = json.loads((folder / 'outputs.json').read_text())
    assert record['capture_errors'] == []
    return folder, record


def test_normal_default_retains_complete_step14_and_unchanged_history(tmp_path, monkeypatch):
    import hashlib
    import step_output_collector as versions
    from test_step14_report_producer_authorship import project_fixture
    project, _ = project_fixture(tmp_path)
    netlist = project / 'phase2/stage2/synth/netlist.v'
    original = netlist.read_bytes()
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] == 'PASS', consumer
    folder, record = _latest_retained_handoff(project)
    assert record['status'] == 'PASS' and record['canonical_pass'] is True
    assert record['inputs']['phase2/stage2/synth/netlist.v'] == hashlib.sha256(original).hexdigest()
    saved_input = next(row for row in record['input_files']
                       if row['rel'] == 'phase2/stage2/synth/netlist.v')
    assert (folder / saved_input['snapshot']).read_bytes() == original
    assert record['result']['producer_return']['rc'] == 0
    assert record['result']['canonical_consumer']['status'] == 'PASS'
    assert len(record['result']['canonical_consumer']['ledger']) > 0
    assert versions.latest_pass(project, '14')['current_inputs'] is True
    before = {path: path.read_bytes() for path in folder.rglob('*') if path.is_file()}
    repeated, again = _default_handoff_audit(project, monkeypatch)
    next_folder, next_record = _latest_retained_handoff(project)
    assert repeated.status == again['status'] == 'PASS'
    assert next_folder != folder and next_record['canonical_pass'] is True
    assert {path: path.read_bytes() for path in before} == before
    assert netlist.read_bytes() == original


@pytest.mark.parametrize('failure_at', ['producer', 'consumer'])
def test_normal_default_retains_real_step14_failure_without_canonical_pass(
        tmp_path, monkeypatch, failure_at):
    import step_output_collector as versions
    from test_step14_report_producer_authorship import project_fixture
    project, _ = project_fixture(tmp_path)
    netlist = project / 'phase2/stage2/synth/netlist.v'
    original = netlist.read_bytes()
    if failure_at == 'producer':
        rtl = project / 'phase2/stage1/rtl/core.v'
        rtl.write_text(rtl.read_text() + '// changed after synthesis\n')
    else:
        produce = producers.run_for_step

        def produce_then_change_native_output(*args, **kwargs):
            census = produce(*args, **kwargs)
            assert census['verdict'] == 'PRODUCED'
            raw = project / 'phase3/librelane/02-yosys-synthesis/core.nl.v'
            raw.write_text(raw.read_text() + '// changed before the consumer\n')
            return census

        monkeypatch.setattr(producers, 'run_for_step', produce_then_change_native_output)
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] == 'FAIL', consumer
    _, record = _latest_retained_handoff(project)
    assert record['status'] == 'FAIL' and record['canonical_pass'] is False
    assert versions.latest_pass(project, '14') is None
    assert record['result']['producer_return']['rc'] == (1 if failure_at == 'producer' else 0)
    complete = record['result']['canonical_consumer']
    if failure_at == 'producer':
        assert complete is None
    else:
        assert complete['status'] == 'FAIL' and complete['ledger']
    assert netlist.read_bytes() == original


@pytest.mark.parametrize('handoff_state, expected', [
    ('complete', 'PASS'), ('producer_failure', 'FAIL'),
    ('consumer_failure', 'FAIL'), ('producer_unmeasured', 'NOT_MEASURED')])
def test_complete_step14_controls_the_real_phase2_audit_return(
        tmp_path, monkeypatch, handoff_state, expected):
    """Real Step14 producer/FCC, with a neutral structural-audit transport.

    The actual step_final_audit wrapper still parses the phase=2 result. Its
    1..6 structural population does not stand in for the separate Step14 row.
    """
    import design_one_shot_runner as runner
    import _gate_authorship as authorship
    from test_step14_report_producer_authorship import project_fixture
    project, _ = project_fixture(tmp_path)
    l5 = project / 'phase1/generated_docs/L5_ADI_SPEC.json'
    l5.write_text(json.dumps({'no_analog': True, 'analog_blocks_detected': False,
                             'analog_blocks': []}) + '\n')
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', {
        'project': str(project), 'policy': {'mode': 'default'},
        'parameters': {'skip_analog': True}})
    monkeypatch.setattr(runner, '_finish_selected_interface_currentness',
                        lambda _: runner.StepResult('phase1_currentness', 'NOT_APPLICABLE',
                            declared_by='neutral INPUT scopes this control to Step14'))
    monkeypatch.setattr(runner._pl, 'emit_final_summary', lambda *args: None)
    audit_calls = []

    def structural_audit_transport(argv, **kwargs):
        assert Path(argv[1]).name == 'flow_compliance_check.py'
        assert argv[argv.index('--phase') + 1] == '2'
        assert '--strict-structural' in argv
        audit_calls.append(argv)
        return (0, 'Overall: PASS\n'
                'STRUCTURAL MEASUREMENT: registered=1 invoked=1 no_verdict=0\n', '')

    monkeypatch.setattr(runner, '_run', structural_audit_transport)
    if handoff_state == 'producer_failure':
        rtl = project / 'phase2/stage1/rtl/core.v'
        rtl.write_text(rtl.read_text() + '// invalid current native input\n')
    elif handoff_state == 'consumer_failure':
        produce = producers.run_for_step

        def produce_then_change_native_output(*args, **kwargs):
            census = produce(*args, **kwargs)
            assert census['verdict'] == 'PRODUCED'
            raw = project / 'phase3/librelane/02-yosys-synthesis/core.nl.v'
            raw.write_text(raw.read_text() + '// changed before full consumer\n')
            return census

        monkeypatch.setattr(producers, 'run_for_step', produce_then_change_native_output)
    elif handoff_state == 'producer_unmeasured':
        monkeypatch.setenv(authorship.ROLE_ENV, authorship.ROLE_AUDIT)
    result = runner._audit_after_declared_producers(project, True)
    _, record = _latest_retained_handoff(project)
    assert len(audit_calls) == 1
    assert result.status == record['status'] == expected
    assert result.extras['step14_handoff']['verdict'] == expected
    assert record['canonical_pass'] is (expected == 'PASS')
    if handoff_state == 'consumer_failure':
        assert record['result']['producer_return']['rc'] == 0
        assert record['result']['canonical_consumer']['status'] == 'FAIL'


def test_real_synthesis_input_change_still_invalidates_retained_producer_reuse(
        tmp_path, monkeypatch):
    from execution_backend_producers import _current_step_producer_authority
    from test_step14_report_producer_authorship import project_fixture
    project, _ = project_fixture(tmp_path)
    result, consumer = _default_handoff_audit(project, monkeypatch)
    assert result.status == consumer['status'] == 'PASS'
    original = json.loads((project / producers.REPORT_REL).read_text())
    source = project / 'phase2/stage1/rtl/core.v'
    source.write_text(source.read_text() + '// real input changed after capture\n')
    changed = producers.run_for_step(project, '14', timeout=30)
    assert changed['input_identity'] != original['input_identity']
    assert changed['executed'] == 4 and changed['already_produced_by_the_run'] == 0
    assert changed['verdict'] == 'INCOMPLETE'
    allowed, _, authority = _current_step_producer_authority(changed, project=project)
    assert allowed is False and authority == 'FAIL'
