"""Native early CDC ownership without qualification or role-approval receipts."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import cdc_async_input_check as asynchronous
import clock_domain_reg_crossing_check as crossing
import design_one_shot_runner as design
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as contract
import reset_dependency_check as reset
import _cdc_netlist as native
from test_flow109_d09_owned_metrics import populate
from test_flow109_selection import _public_d09_entry


def audits(monkeypatch, damage=None):
    calls = []
    for name, module in [('crossing', crossing), ('async_input', asynchronous), ('reset_dep', reset)]:
        findings = []
        summary = {'netlist_read': damage != 'missing',
                   'reg_crossing_population': {'status': 'MEASURED'},
                   'reset_dependency_analysis': {'cycle_detection_complete': damage != 'unresolved'}}
        if damage in ('cycle', 'mixed') and name == 'reset_dep':
            findings.append(module.Finding('CIRCULAR_RESET_DEPENDENCY', 'ERROR', 'TEST_ONLY reset cycle'))
        if damage in ('unresolved', 'mixed') and name == 'reset_dep':
            findings.append(module.Finding('RESET_ROLE_UNRESOLVED', 'ERROR', 'TEST_ONLY ambiguous role'))
        report = module.AuditResult(program=name, passed=not findings, findings=findings, summary=summary)
        def audit(*args, _report=report, _name=name, **kwargs):
            calls.append(_name)
            assert kwargs['front_end'] == 'netlist'
            return _report
        monkeypatch.setattr(module, 'audit', audit)
    monkeypatch.setattr(contract, 'local_image_attestation',
                        lambda *args: pytest.fail('native analyses do not need image receipts'))
    return calls


def test_public_cdc_runs_real_owner_path_without_receipt_admission(tmp_path, monkeypatch):
    populate(tmp_path)
    runner = _public_d09_entry(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['D12' if a == 'D09' else a for a in sys.argv] + ['--execution-mode', 'default'])
    calls = audits(monkeypatch)
    monkeypatch.setattr(metrics, 'd12_subject', lambda *_: pytest.fail('receipt gate precedes native analysis'))
    monkeypatch.setattr(metrics, 'accept_d12', lambda *_: pytest.fail('legacy authority is not a native outcome'))
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{}')
    monkeypatch.setattr(native, 'load', lambda *_: object())
    monkeypatch.setattr(native, 'require_binding', lambda *_: {})
    def child(command, *, env=None, **kwargs):
        with monkeypatch.context() as m:
            for key, value in env.items(): m.setenv(key, value)
            m.setattr(sys, 'argv', command[1:])
            m.setattr(design, '_activate_runtime_program_tree', lambda *_: None)
            m.setattr(design, '_bootstrap_execution_policy', lambda *a, **k: None)
            rc = design.main()
        return SimpleNamespace(returncode=rc)
    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == 0
    assert calls == ['crossing', 'async_input', 'reset_dep']
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D12.json').read_text())
    assert row['default_row_status'] == 'PASS'
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and not row['delivery_accepted']
    assert not (tmp_path / 'reports/audit/ai_judgements/3.json').exists()


@pytest.mark.parametrize('damage,expected', [
    ('cycle', 'FAIL'), ('mixed', 'FAIL'), ('unresolved', 'NOT_MEASURED'), ('missing', 'NOT_MEASURED')])
def test_native_cdc_preserves_violations_and_incomplete_analysis(tmp_path, monkeypatch, damage, expected):
    calls = audits(monkeypatch, damage)
    row = design.step_d12_cdc_rdc(tmp_path, {'context_sha256': 'TEST_ONLY context'})
    assert row.status == expected
    assert len(calls) == 3
    reports = [json.loads(Path(path).read_text()) for path in row.output_files]
    if damage in ('cycle', 'mixed'):
        assert any(f['rule'] == 'CIRCULAR_RESET_DEPENDENCY' for r in reports for f in r['findings'])
