"""Reopen an operator-selected current native proof; no tool rerun or approval."""
import copy
import json
import os
from pathlib import Path

import pytest
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as contract

pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_GENERIC_EQY_PROJECT'),
                               reason='current generic native EQY subject required')

@pytest.fixture
def subject():
    project = Path(os.environ['FLOW109_GENERIC_EQY_PROJECT'])
    manifest = json.loads((project / 'input/flow109-manifest.json').read_text())
    plan = flow109.resolve_plan(manifest['features'])
    context = flow109.component_context(flow109.execution_context(plan, 'D25', 'D25'),
                                        requested_step='D25')
    return project, context

def test_current_native_eqy_producer_image_is_read(subject):
    observed = metrics.accept_d25(*subject)
    assert observed['status'] == observed['component_status'] == 'PASS', json.dumps(observed)
    assert observed['delivery_blocked'] is False
    assert observed['native_assumptions']['script'] and observed['native_assumptions']['config']
    assert observed['native_consumer']['non_equivalent_points'] == []
    assert observed['native_consumer']['unproven_points'] == []
    assert observed['qualification'] == 'NOT_MEASURED'

@pytest.mark.parametrize('image', ['foreign-image', None])
def test_different_or_absent_launch_image_remains_refused(subject, monkeypatch, image):
    original = contract.local_image_attestation
    def changed(*args, **kwargs):
        launch = copy.deepcopy(original(*args, **kwargs))
        launch['image'] = image
        return launch
    monkeypatch.setattr(contract, 'local_image_attestation', changed)
    observed = metrics.accept_d25(*subject)
    assert observed['status'] == 'NOT_MEASURED', json.dumps(observed)
    assert observed['reason'] == 'D25_NATIVE_EXECUTION_UNBOUND', json.dumps(observed)


def test_generic_native_failure_cannot_be_qualified_into_pass(subject, monkeypatch):
    """Reader-verdict boundary double; no new native counterexample is claimed."""
    import librelane_eqy as native
    original = native.judge_eqy
    def failed(*args, **kwargs):
        observed = original(*args, **kwargs)
        observed.update(verdict='FAIL', explanation='TEST_ONLY native-verdict propagation control')
        return observed
    monkeypatch.setattr(native, 'judge_eqy', failed)
    observed = metrics.accept_d25(*subject)
    assert observed['status'] == observed['component_status'] == 'FAIL', json.dumps(observed)
    assert observed['delivery_blocked'] is True
    assert observed['qualification'] == 'NOT_MEASURED'
