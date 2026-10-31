"""Explicit readonly source control; historical input view is TEST_ONLY, not adoption."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.environ['VIBEIC_D13_READSET_PROGRAMS'])
import flow109_metric_acceptance as metrics
import _l10_execution as cases


@pytest.fixture
def inputs():
    data = json.loads(Path(os.environ['VIBEIC_D13_READSET_INPUT']).read_text())
    project = Path(data['project'])
    source = json.loads(Path(data['source']['path']).read_text())
    snapshot = Path(data['original_source_snapshot']['path'])
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == data['original_source_snapshot']['sha256']
    owner = json.loads((project / source['execution']['original_owner']['path']).read_text())
    return project, source, snapshot, owner


def historical_input_lookup(monkeypatch, project, snapshot):
    original = metrics._d13_file
    expected = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    def read(p, record, **kwargs):
        if p == project and record == {'path': 'input/flow109/D13/source.json', 'sha256': expected}:
            return snapshot
        return original(p, record, **kwargs)
    monkeypatch.setattr(metrics, '_d13_file', read)


def test_project_all_normal_captured_inputs_without_mutating_adoption(inputs, monkeypatch):
    project, source, snapshot, _ = inputs
    historical_input_lookup(monkeypatch, project, snapshot)
    original = copy.deepcopy(source['execution'])
    observed = metrics._d13_execution(project, source)
    refs = {r['path']: r['sha256'] for r in observed['artifacts']}
    required = 'phase1/generated_docs/L10_TEST_CASES.json'
    assert required in refs, 'normal collector L10 input was omitted from effective readset'
    assert refs[required] == source['subject']['documents'][0]['sha256']
    assert refs['phase2/stage1/rtl/spm.v'] == source['subject']['rtl']['source_files'][0]['sha256']
    assert refs['input/flow109/D13/source.json'] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert source['execution'] == original
    assert observed['parent_exit_code'] == 1


def test_post_run_adoption_payload_is_not_silently_accepted_as_original_input(inputs):
    project, source, _, _ = inputs
    with pytest.raises(metrics.MetricRefusal, match='D13_INPUT_STALE.*source.json'):
        metrics._d13_execution(project, source)


def test_conflicting_adopted_input_hash_is_not_overwritten(inputs, monkeypatch):
    project, source, snapshot, owner = inputs
    historical_input_lookup(monkeypatch, project, snapshot)
    reference = copy.deepcopy(source['execution'])
    reference['artifacts'].append({'path': 'phase1/generated_docs/L10_TEST_CASES.json', 'sha256': '0' * 64})
    with pytest.raises(metrics.MetricRefusal, match='D13_NATIVE_INPUT_CONFLICT'):
        metrics._d13_retained_input_readset(project, reference, owner)


def test_changed_captured_original_input_still_refuses(inputs, monkeypatch):
    project, source, snapshot, owner = inputs
    historical_input_lookup(monkeypatch, project, snapshot)
    owner = copy.deepcopy(owner)
    owner['inputs']['phase1/generated_docs/L12_BEHAVIORAL_SEQUENCES.json'] = '0' * 64
    with pytest.raises(metrics.MetricRefusal, match='D13_INPUT_STALE.*L12'):
        metrics._d13_retained_input_readset(project, source['execution'], owner)


def test_existing_reset_reader_accepts_exact_original_input_view(inputs, monkeypatch):
    project, _, snapshot, _ = inputs
    original = Path.read_bytes
    raw = snapshot.read_bytes()
    def read(path):
        return raw if path == project / 'input/flow109/D13/source.json' else original(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    record = cases.load_record(project, project / 'phase1/generated_docs/L10_TEST_CASES.json')
    state, reason = cases.scenario_case_state('reset', record)
    assert state == 'PASS', reason
