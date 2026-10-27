"""D10 source-owned observations never manufacture qualification or inventory."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow109
import flow109_metric_acceptance as metric
import vibe_ic_one_shot_runner as runner


def context():
    features = copy.deepcopy(next(row['features'] for row in flow109.load_registry()['reference_profiles']
                                  if row['name'] == 'Small digital IC without DFT'))
    return flow109.execution_context(flow109.resolve_plan(features), 'D10', 'D10')


def p0_fixture(project, monkeypatch, graph):
    elab = project / 'p0-elaboration.json'
    elab.write_text(json.dumps(graph))
    p0 = {'top': 'top', 'elaboration_path': elab.name,
          'elaboration_sha256': hashlib.sha256(elab.read_bytes()).hexdigest()}
    # Isolate graph interpretation here. Separate live controls exercise the
    # P0 consumer identity without this substitution.
    monkeypatch.setattr(runner, '_validate_d10_p0_consumer',
                        lambda *_: {'status':'PASS', 'qualification':'NOT_MEASURED'})
    return p0, elab


def test_no_blackbox_observations_do_not_promote_the_row(tmp_path, monkeypatch):
    p0, _ = p0_fixture(tmp_path, monkeypatch, {'modules': {'top': {'cells': {}}}})
    result = metric.observe_d10_frontend_metrics(tmp_path, context(), p0)
    assert result['status'] == result['qualification'] == 'NOT_MEASURED'
    assert [x['observed_value'] for x in result['obligations']] == [0, 0]
    assert all(x['status'] == 'NOT_MEASURED' for x in result['obligations'])
    assert not (tmp_path / 'adopted/base_04/feature_inventory.json').exists()


def test_blackbox_without_independent_allowlist_is_not_zero(tmp_path, monkeypatch):
    graph = {'modules': {'top': {'cells': {'u': {'type':'opaque'}}},
                         'opaque': {'attributes': {'blackbox': '1'}, 'cells': {}}}}
    p0, _ = p0_fixture(tmp_path, monkeypatch, graph)
    result = metric.observe_d10_frontend_metrics(tmp_path, context(), p0)
    assert result['observed_blackbox_instances'] == ['u']
    assert result['obligations'][1]['observed_value'] is None
    assert result['obligations'][1]['reason'] == 'EXPECTED_BLACKBOX_AUTHORITY_MISSING'
    assert result['status'] == 'NOT_MEASURED'


def test_unresolved_and_stale_elaboration_never_claim_zero(tmp_path, monkeypatch):
    graph = {'modules': {'top': {'cells': {'u': {'type':'missing'}}}}}
    p0, elab = p0_fixture(tmp_path, monkeypatch, graph)
    bad = metric.observe_d10_frontend_metrics(tmp_path, context(), p0)
    assert bad['status'] == 'NOT_MEASURED' and bad['reason'] == 'D10_ELABORATION_UNRESOLVED'
    elab.write_text(elab.read_text() + ' ')
    stale = metric.observe_d10_frontend_metrics(tmp_path, context(), p0)
    assert stale['status'] == 'NOT_MEASURED' and stale['reason'] == 'D10_ELABORATION_STALE'


def test_wrong_producer_identity_refuses_before_any_observation(tmp_path, monkeypatch):
    p0, _ = p0_fixture(tmp_path, monkeypatch, {'modules': {'top': {'cells': {}}}})
    monkeypatch.setattr(runner, '_validate_d10_p0_consumer',
                        lambda *_: (_ for _ in ()).throw(ValueError('P0 wrong argv')))
    result = metric.observe_d10_frontend_metrics(tmp_path, context(), p0)
    assert result['status'] == 'NOT_MEASURED' and result['obligations'] == []
    assert 'wrong argv' in result['detail']
