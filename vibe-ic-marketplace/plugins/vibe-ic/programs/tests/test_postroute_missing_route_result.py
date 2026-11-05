"""Missing routed inputs are unmeasured at the existing backend API."""
from types import SimpleNamespace
import execution_backend_producers as producer
import phase3_one_shot_runner as runner
import librelane_contract as contract
import librelane_postroute_repair as repair

def setup(monkeypatch, project):
    monkeypatch.delenv('VIBEIC_FLOW109_CONTEXT', raising=False)
    monkeypatch.setattr(producer, '_parameters', lambda *_: (runner, contract, SimpleNamespace(name='neutral'), None))
    # Isolate the already-completed synthesis precondition; no synthesis claim.
    monkeypatch.setattr(producer, '_retained_synth_census', lambda *_: None)
    return {'step_id':'32', 'top':'neutral', 'pdk_root':str(project),
            'image_id':'TEST_ONLY_NO_NATIVE_LAUNCH', 'execution_mode':'default'}

def test_actual_missing_route_returns_unmeasured_without_tool_launch(tmp_path, monkeypatch):
    params = setup(monkeypatch, tmp_path)
    def unexpected(*a, **kw):
        raise AssertionError('no routed database exists for a native repair')
    monkeypatch.setattr(repair, 'run', unexpected)
    assert runner.step_postroute_repair_librelane(tmp_path, 'neutral', SimpleNamespace(name='neutral'), None) is None
    observed = producer.produce_signoff(tmp_path, params)
    assert observed['verdict'] == 'NOT_MEASURED'
    assert 'routed database' in observed['detail']

def test_native_failure_result_stays_failed(tmp_path, monkeypatch):
    params = setup(monkeypatch, tmp_path)
    # Explicit child-result boundary double, not a measured repair failure.
    monkeypatch.setattr(runner, 'step_postroute_repair_librelane',
                        lambda *_: SimpleNamespace(status='FAIL', detail='TEST_ONLY native failure'))
    observed = producer.produce_signoff(tmp_path, params)
    assert observed == {'verdict':'FAIL', 'detail':'TEST_ONLY native failure'}
