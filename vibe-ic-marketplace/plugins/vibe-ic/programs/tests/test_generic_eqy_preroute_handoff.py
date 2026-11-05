"""Existing handoff reopens the current generic EQY proof without legacy files."""
import json
import os
from pathlib import Path
import pytest
import flow109
import librelane_eqy as native
from test_flow109_generic_eqy_image import subject

pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_GENERIC_EQY_PROJECT'),
                               reason='operator-selected current generic proof required')

def test_current_generic_eqy_proof_reaches_preroute_admission(subject):
    project, context = subject
    context = flow109.execution_context(flow109.resolve_plan(context['features']), 'D30', 'D30')
    before = {p: p.read_bytes() for p in [project / 'reports/lec_eqy.json',
                                        project / 'reports/lec_arms.json']}
    result = flow109.dft_preroute_admission(project, context)
    assert result['functional_equivalence']['path'] == 'reports/lec_eqy.json'
    assert result['normalized_preroute_chain']['reason'] == 'D30_DELIVERY_ARTIFACT_UNBOUND'
    assert all(p.read_bytes() == value for p, value in before.items())

@pytest.mark.parametrize('verdict', ['FAIL', 'INCONCLUSIVE'])
def test_generic_eqy_refusal_cannot_fall_back_to_legacy_handoff(subject, monkeypatch, verdict):
    """Native reader-verdict doubles; no new measured counterexample claimed."""
    project, context = subject
    context = flow109.execution_context(flow109.resolve_plan(context['features']), 'D30', 'D30')
    original = native.judge_eqy
    def controlled(*args, **kwargs):
        observed = original(*args, **kwargs)
        observed.update(verdict=verdict, explanation='TEST_ONLY reader-verdict propagation')
        return observed
    monkeypatch.setattr(native, 'judge_eqy', controlled)
    with pytest.raises(flow109.Flow109Error, match='FLOW109_D25_PROOF_NOT_ACCEPTED'):
        flow109.dft_preroute_admission(project, context)
