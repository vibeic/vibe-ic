"""Current generic proof's full native views; no new synthesis or proof."""
import os
import pytest
import flow109_metric_acceptance as metrics
import librelane_eqy as native
import _cdc_netlist as graph
from test_flow109_generic_eqy_image import subject

pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_GENERIC_EQY_PROJECT'),
                               reason='operator-selected current generic proof required')


def test_generic_native_views_supply_complete_change_census(subject):
    observed = metrics.d30_consumed_changes(*subject)
    assert observed['status'] == 'MEASURED', observed
    assert observed['value'] == []
    assert set(observed['population']) == {'gold', 'gate'}
    assert all(side['flop_cells'] > 0 and len(side['clock_domains']) == 1
               for side in observed['population'].values())


@pytest.mark.parametrize('damage', ['FAIL', 'INCONCLUSIVE', 'memory', 'multiple_clocks'])
def test_refused_or_incomplete_native_views_cannot_supply_empty_census(subject, monkeypatch, damage):
    """Explicit reader-result doubles; native files and verdicts stay untouched."""
    if damage in ('FAIL', 'INCONCLUSIVE'):
        original = native.judge_eqy
        def controlled(*args, **kwargs):
            result = original(*args, **kwargs)
            return {**result, 'verdict': damage, 'explanation': 'TEST ONLY'}
        monkeypatch.setattr(native, 'judge_eqy', controlled)
    elif damage == 'memory':
        original = graph.load
        def incomplete(*args, **kwargs):
            result = original(*args, **kwargs)
            result.memories = 1
            return result
        monkeypatch.setattr(graph, 'load', incomplete)
    else:
        monkeypatch.setattr(graph, 'clock_domains', lambda *_: ['first', 'second'])
    assert metrics.d30_consumed_changes(*subject)['status'] == 'NOT_MEASURED'
