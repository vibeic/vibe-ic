"""Local retained calls can execute canonical consumers in child processes."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import step_output_collector as versions
import step_preflight as preflight
import execution_policy as policy
import execution_backend_gates as gates


CHILD = """
import json, sys
from pathlib import Path
import step_output_collector as versions
p = Path(sys.argv[1])
a = versions.begin_step(p, 'P0')
versions.finish_step(p, a, verdict='FAIL', result={'detail': 'actual failing child'})
"""


def run_child(project):
    subprocess.run([sys.executable, '-c', CHILD, str(project)], check=True)


def record(project, attempt):
    return project / 'steps' / attempt['folder'] / 'outputs.json'


def test_canonical_retained_consumer_child_does_not_finish_live_step7(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    # Exercise the real retained-call seam; the child has its own module state.
    def producer(project):
        run_child(project)
        return 1
    assert preflight.retained_call(tmp_path, '7', producer, tmp_path,
                                   canonical_acceptance=True) == 1
    entries = versions._read_index(tmp_path)['steps']
    parent = next(x for x in entries if x['id'] == '7')
    child = next(x for x in entries if x['id'] == 'P0')
    saved = json.loads((tmp_path / 'steps' / parent['folder'] / 'outputs.json').read_text())
    assert saved['status'] == 'FAIL'
    assert child['status'] == 'FAIL'
    assert not saved['canonical_pass']
    assert not list((tmp_path / 'steps').glob('*/*/*/active_call.json'))


def test_successful_producer_retains_failing_canonical_child_consumer(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    def consumer(project, row):
        run_child(project)
        return {'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'}, 'ledger': []}
    monkeypatch.setattr(gates, 'evaluate', consumer)
    assert preflight.retained_call(tmp_path, '7', lambda project: 0, tmp_path,
                                   canonical_acceptance=True) == 0
    entry = next(x for x in versions._read_index(tmp_path)['steps'] if x['id'] == '7')
    saved = json.loads((tmp_path/'steps'/entry['folder']/'outputs.json').read_text())
    assert saved['status'] == 'FAIL'
    assert saved['result']['rows'][0]['status'] == 'PASS'
    assert not saved['canonical_pass']
    assert versions.latest_pass(tmp_path, '7') is None


def test_pid_reuse_marker_does_not_protect_an_abandoned_journal(tmp_path):
    a = versions.begin_step(tmp_path, '7')
    folder = record(tmp_path, a).parent
    owner = versions._process_identity(__import__('os').getpid())
    assert owner is not None
    owner['start_ticks'] += 1
    (folder/'active_call.json').write_text(json.dumps(owner))
    following = versions.begin_step(tmp_path, '8')
    assert json.loads(record(tmp_path, a).read_text())['status'] == 'INTERRUPTED'
    versions.finish_step(tmp_path, following, verdict='NOT_MEASURED')


def test_exited_owner_is_recovered_with_partial_bytes(tmp_path):
    code = """
import os, sys
from pathlib import Path
import step_output_collector as versions
p = Path(sys.argv[1]); a = versions.begin_step(p, '7')
with versions.active_steps(p, [a]):
    f=p/'reports/partial.log'; f.parent.mkdir(); f.write_bytes(b'partial native output')
    os._exit(0)
"""
    subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True)
    a = versions.begin_step(tmp_path, '8')
    parent = next(x for x in versions._read_index(tmp_path)['steps'] if x['id'] == '7')
    folder = tmp_path / 'steps' / parent['folder']
    assert parent['status'] == 'INTERRUPTED'
    assert (folder / 'files/reports/partial.log').read_bytes() == b'partial native output'
    versions.finish_step(tmp_path, a, verdict='NOT_MEASURED')


def test_unwound_live_owner_is_recovered(tmp_path):
    a = versions.begin_step(tmp_path, '7')
    with pytest.raises(RuntimeError):
        with versions.active_steps(tmp_path, [a]):
            raise RuntimeError('producer aborted')
    following = versions.begin_step(tmp_path, '8')
    assert json.loads(record(tmp_path, a).read_text())['status'] == 'INTERRUPTED'
    versions.finish_step(tmp_path, following, verdict='NOT_MEASURED')


def test_duplicate_finish_still_refused(tmp_path):
    a = versions.begin_step(tmp_path, '7')
    versions.finish_step(tmp_path, a, verdict='FAIL')
    with pytest.raises(ValueError, match='already finished'):
        versions.finish_step(tmp_path, a, verdict='PASS', canonical_pass=True)
    assert json.loads(record(tmp_path, a).read_text())['status'] == 'FAIL'


def test_unavailable_process_identity_refuses_before_producer(tmp_path, monkeypatch):
    a = versions.begin_step(tmp_path, '7')
    monkeypatch.setattr(versions, '_process_identity', lambda pid: None)
    entered = False
    with pytest.raises(OSError, match='process identity'):
        with versions.active_steps(tmp_path, [a]):
            entered = True
    assert not entered
    assert not versions._ACTIVE_LOCAL_CALLS
    assert not record(tmp_path, a).exists()
def test_marker_cleanup_error_does_not_leak_inprocess_active_state(tmp_path, monkeypatch):
    a = versions.begin_step(tmp_path, '7')
    original = Path.unlink
    def refuse_marker(path, **kwargs):
        if path.name == 'active_call.json':
            raise OSError('cleanup failed')
        return original(path, **kwargs)
    monkeypatch.setattr(Path, 'unlink', refuse_marker)
    with pytest.raises(OSError, match='cleanup failed'):
        with versions.active_steps(tmp_path, [a]):
            pass
    assert not versions._ACTIVE_LOCAL_CALLS
    assert not record(tmp_path, a).exists()
    monkeypatch.setattr(Path, 'unlink', original)
    following = versions.begin_step(tmp_path, '8')
    assert json.loads(record(tmp_path, a).read_text())['status'] == 'INTERRUPTED'
    versions.finish_step(tmp_path, following, verdict='NOT_MEASURED')


def test_child_with_unreadable_owner_identity_refuses_recovery(tmp_path):
    a = versions.begin_step(tmp_path, '7')
    code = """
import sys
from pathlib import Path
import step_output_collector as versions
p = Path(sys.argv[1])
versions._process_identity = lambda pid: None
try:
    versions.begin_step(p, 'P0')
except OSError as exc:
    assert 'cannot verify owner' in str(exc)
else:
    raise AssertionError('unverifiable locked parent was recovered')
"""
    with versions.active_steps(tmp_path, [a]):
        subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True)
        assert not record(tmp_path, a).exists()
    versions.finish_step(tmp_path, a, verdict='NOT_MEASURED')
    assert json.loads(record(tmp_path, a).read_text())['status'] == 'NOT_MEASURED'

