"""Reverse controls for the backend consumer's terminal verdict authority."""

import pytest

import execution_backend_consumer as consumer
from programs.tests.test_execution_backend_f3 import finite_backend, observed
from programs.tests import test_execution_modes as H


@pytest.mark.parametrize(
    "consumer_status", ["PASS", "NOT_MEASURED", "MISSING", "NOT_APPLICABLE", "FAIL"]
)
def test_controller_adoption_requires_measured_consumer_pass(
        tmp_path, monkeypatch, consumer_status):
    controller, context, arm = finite_backend(tmp_path)
    root = tmp_path / consumer_status.lower()
    assert controller.run(context, root, "ultra-mode")["candidate_statuses"][arm.arm_id] == "ELIGIBLE"

    monkeypatch.setattr(
        consumer, "evaluate",
        lambda *_args: {"status": consumer_status, "step": {"status": consumer_status}, "ledger": []},
    )
    actual = observed(lambda: controller.adopt(
        context, root, H.choice(context, root, arm.arm_id)))
    expected = "ADOPTED" if consumer_status == "PASS" else (
        "REFUSED:GATE_FAIL" if consumer_status == "FAIL"
        else "REFUSED:BACKEND_CANONICAL_CONSUMER_REFUSED")
    assert actual == expected


@pytest.mark.parametrize('requires_scan,native,expected', [
    (True, 'PASS', 'NOT_MEASURED'),
    (True, 'FAIL', 'FAIL'),
    (False, 'PASS', 'PASS'),
])
def test_d49_missing_scan_modes_cannot_be_functional_pass(
        tmp_path, monkeypatch, requires_scan, native, expected):
    import json
    import flow109
    import flow_compliance_check as fcc
    import execution_backend_gates as gates
    from flow_compliance_check import StepResult
    path = tmp_path / 'context.json'
    path.write_text(json.dumps({'irrelevant': True}))
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(path))
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda _: {
        'resolved_row': {'id': 'D49'}, 'features': {'requires_scan': requires_scan}})
    monkeypatch.setattr(fcc, 'check_step', lambda *_a, **_k: StepResult(
        id='23', name='candidate timing', stage='physical', status=native))
    result = gates.evaluate(tmp_path, {'id': '23'})
    assert result['status'] == expected
    if requires_scan and native == 'PASS':
        assert 'D49_SCAN_MODES_NOT_ACQUIRED' in result['step']['reasons'][0]
