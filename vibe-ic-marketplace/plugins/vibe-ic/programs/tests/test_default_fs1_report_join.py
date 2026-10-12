"""FS1's current producer must finish both reports before the consumer runs."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _flow_yaml
import execution_backend_gates as gates
import execution_policy as policy
from test_fs1_fmeda_producer_is_run_by_the_runner import COUNTER, _project, _runner
from test_fmeda_fault_injection_coverage import _DEC_OK, _ecc_project


REPORTS = (
    'reports/phase2/safety/fmeda_coverage.json',
    'reports/phase2/safety/fmeda_coverage_gate.json',
)


@pytest.mark.parametrize('relative', REPORTS)
def test_fs1_declares_the_report_written_by_its_program(relative):
    row = next(row for row in _flow_yaml.load()['steps'] if row['id'] == 'FS1')
    assert relative in row.get('required_outputs', []), row


def observe_consumer(monkeypatch, project):
    seen = []
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(gates, 'contracts', lambda *args: {'control_fixture': {}})
    def consume(project, row):
        seen.append(tuple((project / relative).is_file() for relative in REPORTS))
        return {'status': 'PASS', 'ledger': [],
                'step': {'id': 'FS1', 'status': 'PASS'}}
    monkeypatch.setattr(gates, 'evaluate', consume)
    return seen


def test_current_fs1_finishes_both_reports_before_consumer(tmp_path, monkeypatch):
    project = _ecc_project(tmp_path, _DEC_OK)
    seen = observe_consumer(monkeypatch, project)
    row = _runner().step_fmeda_fault_injection(project)
    assert seen and all(all(present) for present in seen), seen
    reports = [json.loads((project / relative).read_text()) for relative in REPORTS]
    assert [report['verdict'] for report in reports] == ['PASS'] * 2
    assert row.status == 'PASS', row


def test_failed_independent_report_cannot_reuse_previous_pass(tmp_path, monkeypatch):
    project = _project(tmp_path, {'cnt.v': COUNTER})
    previous = project / REPORTS[1]
    previous.parent.mkdir(parents=True)
    previous.write_text('{"verdict":"PASS","passed":true}\n')
    mod = _runner()
    native = mod._pr.run
    def execute(argv, **kwargs):
        if Path(argv[1]).stem == 'fmeda_coverage_check':
            return SimpleNamespace(returncode=1, stdout='', stderr='current checker failed')
        return native(argv, **kwargs)
    monkeypatch.setattr(mod._pr, 'run', execute)
    observe_consumer(monkeypatch, project)
    row = mod.step_fmeda_fault_injection(project)
    assert row.status in ('FAIL', 'NOT_MEASURED'), row
    assert not previous.exists(), 'a previous report cannot stand in for this invocation'


def test_no_source_remains_unmeasured(tmp_path):
    project = _project(tmp_path, {'notes.txt': 'no RTL source\n'})
    row = _runner().step_fmeda_fault_injection(project)
    assert row.status == 'NOT_MEASURED', row


def test_real_canonical_consumer_accepts_both_native_reports(tmp_path, monkeypatch):
    import step_output_collector as versions
    project = _ecc_project(tmp_path, _DEC_OK)
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    row = _runner().step_fmeda_fault_injection(project)
    accepted = versions.latest_pass(project, 'FS1')
    assert row.status == 'PASS', row
    assert accepted and accepted['canonical_pass'], accepted
    assert accepted['result']['canonical_consumer']['status'] == 'PASS'
    assert {item['rel'] for item in accepted['outputs']} == set(REPORTS)


def test_measured_independent_failure_blocks_the_native_row(tmp_path, monkeypatch):
    project = _ecc_project(tmp_path, _DEC_OK)
    mod = _runner()
    native = mod._pr.run
    def execute(argv, **kwargs):
        if Path(argv[1]).stem == 'fmeda_coverage_check':
            (project / REPORTS[1]).write_text('{"verdict":"FAIL"}\n')
            return SimpleNamespace(returncode=1, stdout='', stderr='coverage failed')
        return native(argv, **kwargs)
    monkeypatch.setattr(mod._pr, 'run', execute)
    seen = observe_consumer(monkeypatch, project)
    row = mod.step_fmeda_fault_injection(project)
    assert row.status == 'FAIL', row
    assert not seen, 'a failed native result must not reach acceptance'
