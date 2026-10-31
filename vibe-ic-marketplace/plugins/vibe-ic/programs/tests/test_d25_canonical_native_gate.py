"""Canonical gate binds the adopted native consumer, without legacy rewriting."""
import json
import os
from pathlib import Path
import sys

import pytest
import flow109
import lec_equivalence_check as gate


_ACTIVE = False


def _no_tools(event, args):
    if _ACTIVE and event == 'subprocess.Popen':
        raise AssertionError('native proof replay attempted: ' + str(args[1]))


sys.addaudithook(_no_tools)


@pytest.fixture
def actual_subject(tmp_path, monkeypatch):
    raw = os.environ.get('FLOW109_D25_CANONICAL_GATE_PROJECT')
    if not raw:
        pytest.skip('actual independently adopted native subject required')
    project = Path(raw)
    manifest = json.loads(Path(os.environ['FLOW109_D25_CANONICAL_GATE_MANIFEST']).read_text())
    context = flow109.execution_context(flow109.resolve_plan(manifest['features']), 'D25', 'D25')
    path = tmp_path / 'actual-context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    import librelane_eqy
    librelane_eqy.d25_sources()  # preload installed package before subprocess observer
    return project


def observed_audit(project):
    global _ACTIVE
    _ACTIVE = True
    try:
        return gate.audit(project)
    finally:
        _ACTIVE = False


def test_actual_adopted_native_gate_reuses_complete_proof(actual_subject):
    legacy = {name: (actual_subject / name).read_bytes()
              for name in ('reports/lec.json', 'reports/lec.rpt', 'reports/lec_eqy_execution.json')}
    result = observed_audit(actual_subject)
    assert result.passed is True, result
    assert result.evidence_source == 'adopted_native_eqy'
    accepted = result.summary['metric_acceptance']
    assert accepted['status'] == accepted['qualification'] == 'PASS'
    assert len(accepted['obligations']) == 3
    assert all(o['status'] == 'PASS' for o in accepted['obligations'])
    assert accepted['native_execution']['proof']['partitions'] == {
        'spm.c.0': {'pdr': 'PASS', 'sat': 'UNKNOWN'}}
    assert result.summary['subject_binding']['state'] == 'MATCH'
    assert {name: (actual_subject / name).read_bytes() for name in legacy} == legacy


def test_actual_native_gate_refuses_foreign_delivered_subject(actual_subject, tmp_path, monkeypatch):
    import lec_gate_netlist_select as selector
    foreign = tmp_path / 'foreign.v'
    foreign.write_text('module foreign; endmodule\n')
    monkeypatch.setattr(selector, 'pnr_consumed_netlist', lambda *_: (foreign, 'foreign actual consumer input', False))
    result = observed_audit(actual_subject)
    assert result.passed is False
    assert any(f.rule == 'LEC_SUBJECT_UNBOUND' for f in result.findings)


@pytest.mark.parametrize('status', ['NOT_MEASURED', 'FAIL'])
def test_native_refusal_never_falls_back_to_legacy(tmp_path, monkeypatch, status):
    """Explicit consumer boundary double; no native qualification is asserted."""
    import flow109_metric_acceptance as metrics
    p = tmp_path / 'input/flow109/D25.json'
    p.parent.mkdir(parents=True)
    p.write_text('{}')
    context = tmp_path / 'context.json'
    context.write_text('{}')
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context))
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda _: {})
    monkeypatch.setattr(flow109, 'component_context', lambda *_, **__: {'resolved_row': {'id': 'D25'}})
    monkeypatch.setattr(metrics, 'accept_d25', lambda *_: {
        'status': status, 'reason': 'EXPLICIT_UNQUALIFIED_BOUNDARY_DOUBLE', 'obligations': []})
    result = observed_audit(tmp_path)
    assert result.passed is False and result.inconclusive is False
    assert result.not_measured is (status == 'NOT_MEASURED')
    assert result.findings[0].rule == 'EXPLICIT_UNQUALIFIED_BOUNDARY_DOUBLE'


def test_partial_named_input_cannot_use_legacy_gate(tmp_path, monkeypatch):
    p = tmp_path / 'reports/lec_eqy_execution.json'
    p.parent.mkdir(parents=True)
    p.write_text('{}')
    monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
    result = observed_audit(tmp_path)
    assert result.passed is False
    assert any(f.rule == 'D25_NATIVE_INPUT_UNBOUND' for f in result.findings)


def test_native_gate_source_change_reopens_only_once(tmp_path, monkeypatch):
    # Existing actual admission control: changed consumed gate bytes reopen;
    # unchanged/restored duplicates and missing/foreign source still refuse.
    from test_canonical_run_admission import test_native_handoff_resolver_source_reopens_only_once
    test_native_handoff_resolver_source_reopens_only_once(
        tmp_path, monkeypatch, 'lec_equivalence_check.py',
        'res = AuditResult()', 'res = AuditResult(passed=True)')
