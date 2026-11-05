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
