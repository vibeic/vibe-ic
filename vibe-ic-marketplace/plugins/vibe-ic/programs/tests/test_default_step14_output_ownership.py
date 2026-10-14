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
