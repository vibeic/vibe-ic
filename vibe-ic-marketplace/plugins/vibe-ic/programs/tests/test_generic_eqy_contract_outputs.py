"""Existing LEC gate reopens an operator-selected current generic native proof."""
import json
import os
from pathlib import Path
import pytest
import flow109
import flow109_metric_acceptance as metrics
import librelane_eqy as native
import lec_equivalence_check as checker
from test_flow109_generic_eqy_image import subject

pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_GENERIC_EQY_PROJECT'),
                               reason='current generic native EQY subject required')

@pytest.fixture
def active_subject(subject, tmp_path, monkeypatch):
    project, context = subject
    path = tmp_path / 'context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    return project

def test_generic_eqy_actual_outputs_satisfy_original_step_contract(active_subject, tmp_path):
    import _flow_yaml
    import execution_backend_gates as gates
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '13')
    outputs = gates.contracts(active_subject, row)
    assert len(outputs) == 2
    assert all(outputs.values())
    paths = {name for group in outputs.values() for name in group}
    assert {'reports/lec_eqy.json', 'reports/lec_arms.json'} <= paths
    classic = tmp_path / 'classic_contract'
    (classic / 'reports').mkdir(parents=True)
    for name in ('lec.rpt', 'lec.json'):
        (classic / 'reports' / name).write_text('SOFTWARE contract-presence stand-in; no proof claimed')
    old_outputs = gates.contracts(classic, row)
    assert {name for group in old_outputs.values() for name in group} == {'reports/lec.rpt', 'reports/lec.json'}

def test_existing_lec_gate_delegates_generic_native_result(active_subject, tmp_path):
    observed = checker.audit(active_subject)
    assert observed.passed and observed.equivalent, observed
    assert observed.compared_points > 0
    assert observed.non_equivalent_points == observed.unproven_points == 0
    assert checker.main([str(active_subject), '--json', str(tmp_path / 'gate.json')]) == 0

@pytest.mark.parametrize('verdict', ['FAIL', 'INCONCLUSIVE'])
def test_native_reader_failure_and_undecided_are_never_pass(active_subject, monkeypatch, verdict, tmp_path, capsys):
    """Native reader-verdict doubles, not new measured counterexamples."""
    original = native.judge_eqy
    def controlled(*args, **kwargs):
        result = original(*args, **kwargs)
        result.update(verdict=verdict, explanation='TEST_ONLY reader-verdict propagation')
        return result
    monkeypatch.setattr(native, 'judge_eqy', controlled)
    observed = checker.audit(active_subject)
    assert not observed.passed, observed
    assert observed.not_measured is (verdict == 'INCONCLUSIVE'), observed
    assert checker.main([str(active_subject), '--json', str(tmp_path / 'gate.json')]) == 1
    if verdict == 'INCONCLUSIVE':
        assert 'NOT_MEASURED_NON_WAIVABLE: native LEC' in capsys.readouterr().out
