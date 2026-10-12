"""Step23 writes current hold/clock verdicts before its independent audit."""
import json

import pytest

import execution_backend_producers as backend
import flow_declared_producer_run as declared
import test_f15_step23_gates_read_the_tool_arm as fixture

REPORTS = {
    'hold_corner_coverage_check': 'reports/phase3/sta/hold_corner_coverage.json',
    'sta_assumed_clock_disclosure_check': 'reports/phase3/sta/assumed_clock_disclosure.json',
    'clock_target_record_agreement_check': 'reports/phase3/clock_target_record_agreement.json',
}


@pytest.mark.parametrize('damage', ['none', 'hold', 'assumed_clock', 'clock_target'])
def test_default_current_step_produces_all_three_reports_and_keeps_failure(tmp_path, damage):
    project = fixture.tool_project(
        tmp_path, hold_inf=('min_ff_n40C_5v50',) if damage == 'hold' else ())
    fixture.gate_inputs(project, assumed=damage == 'assumed_clock', stamp=False)
    if damage == 'clock_target':
        target = project/'reports/phase3/clock_target_provenance.json'
        doc = json.loads(target.read_text())
        doc['period_ns'] = 25.0
        target.write_text(json.dumps(doc))
    # This is the actual per-row backend producer seam, with actual checker
    # subprocesses. Native STA writes are controlled by the shared fixture.
    result = backend._run_current_step_declared_producers(project, '23')
    rows = {row['program']: row for row in result['results']}
    for program, relative in REPORTS.items():
        assert program in rows, f'{program} was left to the auditor instead of the producer'
        row = rows[program]
        assert row['executed'] is True and row['target_exists_after'] is True, row
        assert row['authorship'] == 'producer', row
        assert (project/relative).is_file()
        assert row['target_sha256'] == declared._target_digest(project/relative)
    allowed, reason, verdict = backend._current_step_producer_authority(result, project=project)
    if damage == 'none':
        assert allowed and verdict == 'PASS', (result, reason, verdict)
        assert all(rows[program]['rc'] == 0 for program in REPORTS)
    else:
        failed = {'hold': 'hold_corner_coverage_check',
                  'assumed_clock': 'sta_assumed_clock_disclosure_check',
                  'clock_target': 'clock_target_record_agreement_check'}[damage]
        assert rows[failed]['rc'] == 1, rows[failed]
        assert allowed is False and verdict == 'FAIL', (result, reason, verdict)


@pytest.mark.parametrize('program', sorted(REPORTS))
def test_the_same_checker_called_by_audit_is_not_producer_evidence(tmp_path, monkeypatch, program):
    import importlib
    import _gate_authorship as authorship
    project = fixture.tool_project(tmp_path)
    fixture.gate_inputs(project)
    target = project/REPORTS[program]
    monkeypatch.setenv(authorship.ROLE_ENV, authorship.ROLE_AUDIT)
    assert importlib.import_module(program).main([str(project), '--json', str(target)]) == 0
    assert json.loads(target.read_text())['invoked_as'] == 'audit'
    assert declared._producer_target_has_content(target) is False
