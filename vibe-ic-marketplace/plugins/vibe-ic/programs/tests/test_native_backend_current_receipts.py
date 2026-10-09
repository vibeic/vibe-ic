"""Native Default producer/consumer boundaries for backend rows 18--20."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_backend_producers as producers  # noqa: E402
import execution_backend_worker as worker  # noqa: E402
from execution_provider_catalog import BACKEND_SITES  # noqa: E402


def _write(project: Path, relative: str, text: str) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _native_outputs(project: Path, step: str) -> None:
    if step == "18":
        _write(project, "phase3/stage3/pnr/spare_cells.json",
               json.dumps({"spare_count": 4, "target_density": 0.01}))
        _write(project, "reports/spare_cell_coverage.json",
               json.dumps({"verdict": "PASS", "spare_count": 4}))
    elif step == "19":
        _write(project, "phase3/stage3/pnr/post_cts.def",
               "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
        _write(project, "phase3/stage3/cts/clock_tree.rpt",
               "clock latency 1.0 skew 0.1 buffers 2\n")
    else:
        _write(project, "phase3/stage3/pnr/post_hold.def",
               "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")


def _manifest(project: Path, relative: str) -> dict:
    path = project / relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"declarations": [{"from": "external", "path": relative}],
            "files": {relative: digest}, "missing": []}


def _registry_outputs(project: Path, step: str) -> list[str]:
    from execution_adapters_backend import ROWS
    paths = []
    for spec in ROWS[step]['canonical_row']['required_outputs']:
        raw = str(spec).split(' OR ')[0]
        if '*' in raw:
            raw = raw.replace('*', 'fixture')
        path = _write(project, raw, '{}\n' if raw.endswith('.json') else 'fixture\n')
        paths.append(str(path.relative_to(project)))
    return paths


def test_native_rows_create_current_receipt_after_producer(tmp_path, monkeypatch):
    for step, predecessor in (("18", "placed.def"),
                              ("19", "placed.def"),
                              ("20", "post_cts.def")):
        project = tmp_path / step
        _write(project, f"phase3/stage3/pnr/{predecessor}", "input\n")
        events = []

        def native(current_project, _params, *, _events=events, _step=step):
            _events.append("producer")
            _native_outputs(current_project, _step)
            return {"verdict": "PASS", "detail": "native fixture"}

        monkeypatch.setattr(producers, "produce_pnr", native)
        result = producers.produce(
            project, {"step_id": step,
                      "resolved_input_manifest": _manifest(
                          project, f"phase3/stage3/pnr/{predecessor}")})
        current = result["current_step_declared_producers"]
        assert events == ["producer"]
        assert current["schema"] == "vibeic/native-current-step-receipt/1"
        assert current["verdict"] == "PRODUCED"
        assert current["step_id"] == step
        assert producers._current_step_producer_authority(
            current, project=project) == (True, "", "PASS")


def test_native_receipt_mutation_blocks_consumer(tmp_path, monkeypatch):
    project = tmp_path / "project"
    predecessor = "phase3/stage3/pnr/placed.def"
    _write(project, predecessor, "input\n")
    events = []

    def native(current_project, _params):
        events.append("producer")
        _native_outputs(current_project, "18")
        return {"verdict": "PASS", "detail": "native fixture"}

    monkeypatch.setattr(producers, "produce_pnr", native)
    result = producers.produce(
        project, {"step_id": "18",
                  "resolved_input_manifest": _manifest(project, predecessor)})
    current = result["current_step_declared_producers"]
    output = project / "phase3/stage3/pnr/spare_cells.json"
    output.write_text(output.read_text() + "mutated\n")
    assert producers._current_step_producer_authority(
        current, project=project) == (
            False, "native current producer output changed: "
            "phase3/stage3/pnr/spare_cells.json", "NOT_MEASURED")


def test_worker_calls_consumer_only_after_native_receipt(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs" / "project"
    predecessor = inputs / "phase3/stage3/pnr/placed.def"
    predecessor.parent.mkdir(parents=True)
    predecessor.write_text("input\n")
    outputs = tmp_path / "outputs"
    events = []

    def native(project, _params):
        events.append("producer")
        _native_outputs(project, "18")
        return {"verdict": "PASS", "detail": "native fixture"}

    monkeypatch.setattr(producers, "produce_pnr", native)
    monkeypatch.setattr(worker, "evaluate",
                        lambda _project, _row: events.append("consumer") or
                        {"status": "PASS", "ledger": []})
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [], "source_sha": "fixture"}))
    result = worker.execute(inputs.parent, outputs, step_id="18", params={})
    assert events == ["producer", "consumer"]
    assert result["verdict"] == "PASS"
    assert result["canonical_receipts"][0]["schema"] == \
        "vibeic/backend-producer-receipt/1"


def test_registry_rows_create_receipts_from_catalog_sites(tmp_path, monkeypatch):
    for step in ('27', '32'):
        project = tmp_path / step
        input_path = _write(project, 'inputs/current.txt', 'current\n')
        outputs = _registry_outputs(project, step)

        def native(current_project, _params, _outputs=outputs):
            for raw in _outputs:
                _write(current_project, raw,
                       '{"fresh": 1}\n' if raw.endswith('.json') else 'fresh\n')
            return {'verdict': 'PASS', 'detail': 'registry fixture'}

        monkeypatch.setattr(producers, 'produce_signoff', native)
        result = producers.produce(
            project, {'step_id': step,
                      'resolved_input_manifest': _manifest(
                          project, str(input_path.relative_to(project)))})
        current = result['current_step_declared_producers']
        assert result['verdict'] == 'PASS'
        assert current['verdict'] == 'PRODUCED'
        assert current['producer'] == list(BACKEND_SITES[step])
        assert set(current['preexisting_outputs']) == set(outputs)
        assert producers._current_step_producer_authority(
            current, project=project) == (True, '', 'PASS')


def test_registry_receipt_rejects_unchanged_preexisting_output(tmp_path, monkeypatch):
    project = tmp_path / 'stale'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    _registry_outputs(project, '27')

    monkeypatch.setattr(producers, 'produce_signoff',
                        lambda _project, _params: {'verdict': 'PASS'})
    result = producers.produce(
        project, {'step_id': '27',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'NOT_MEASURED'
    assert current['reason'].startswith('NATIVE_CURRENT_OUTPUT_UNCHANGED:')


def test_registry_receipt_rejects_missing_output(tmp_path, monkeypatch):
    project = tmp_path / 'missing'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    monkeypatch.setattr(producers, 'produce_signoff',
                        lambda _project, _params: {'verdict': 'PASS'})
    result = producers.produce(
        project, {'step_id': '32',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'NOT_MEASURED'
    assert current['reason'].startswith('NATIVE_CURRENT_OUTPUT_CONTRACT_UNAVAILABLE:')


def test_registry_receipt_rejects_parent_symlink(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (project / 'reports').symlink_to(outside, target_is_directory=True)
    outputs = _registry_outputs(project, '27')

    def native(current_project, _params):
        for raw in outputs:
            _write(current_project, raw, 'fresh\n')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(producers, 'produce_signoff', native)
    result = producers.produce(
        project, {'step_id': '27',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    current = result['current_step_declared_producers']
    assert current['verdict'] == 'NOT_MEASURED'
    assert current['consumer_allowed'] is False
    assert current['reason'].startswith('NATIVE_CURRENT_OUTPUT_PATH_UNSAFE:')


def test_registry_receipt_and_authority_reject_symlinked_project_root(
        tmp_path, monkeypatch):
    target = tmp_path / 'target'
    input_path = _write(target, 'inputs/current.txt', 'current\n')
    project = tmp_path / 'project'
    project.symlink_to(target, target_is_directory=True)
    outputs = _registry_outputs(target, '27')

    def native(current_project, _params):
        for raw in outputs:
            _write(current_project, raw, 'fresh\n')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(producers, 'produce_signoff', native)
    result = producers.produce(
        project, {'step_id': '27',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(target)))})
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'NOT_MEASURED'
    assert current['reason'].startswith('NATIVE_CURRENT_INPUT_PATH_UNSAFE:')
    assert producers._current_step_producer_authority(
        current, project=project) == (
            False, current['reason'], 'NOT_MEASURED')


def test_registry_measured_fail_survives_missing_outputs(tmp_path, monkeypatch):
    project = tmp_path / 'fail'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    monkeypatch.setattr(producers, 'produce_signoff',
                        lambda _project, _params: {
                            'verdict': 'FAIL', 'detail': 'native failure'})
    result = producers.produce(
        project, {'step_id': '32',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    assert result['verdict'] == 'FAIL'


def test_registry_receipt_rejects_wrong_identity_and_mutated_input(tmp_path, monkeypatch):
    project = tmp_path / 'mutation'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    outputs = _registry_outputs(project, '32')

    def native(current_project, _params):
        for raw in outputs:
            _write(current_project, raw, 'fresh\n')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(producers, 'produce_signoff', native)
    current = producers.produce(
        project, {'step_id': '32',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})[
                          'current_step_declared_producers']
    wrong = dict(current, producer=['wrong-site'])
    assert producers._current_step_producer_authority(
        wrong, project=project) == (
            False, 'native current producer identity is invalid', 'NOT_MEASURED')
    input_path.write_text('mutated\n')
    assert producers._current_step_producer_authority(
        current, project=project) == (
            False, 'native current producer input changed: inputs/current.txt',
            'NOT_MEASURED')


def test_worker_does_not_promote_entire_tree_to_producer_inputs(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    _write(inputs, 'unrelated.txt', 'must not enter receipt\n')
    outputs = tmp_path / 'outputs'
    seen = {}

    def fake_produce(_project, params):
        seen['files'] = params['resolved_input_manifest']['files']
        return {'verdict': 'NOT_MEASURED', 'current_step_declared_producers': None}

    monkeypatch.setattr(worker, 'produce', fake_produce)
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING',
                       json.dumps({'required_gates': []}))
    worker.execute(inputs.parent, outputs, step_id='32', params={})
    assert seen['files'] == {}


def test_worker_publication_rejects_parent_symlink(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs' / 'project'
    predecessor = inputs / 'phase3/stage3/pnr/placed.def'
    predecessor.parent.mkdir(parents=True)
    predecessor.write_text('input\n')
    outputs = tmp_path / 'outputs'
    outside = tmp_path / 'outside'
    outside.mkdir()
    outputs.mkdir(parents=True)
    (outputs / 'reports').symlink_to(outside, target_is_directory=True)

    def native(project, _params):
        _native_outputs(project, '18')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(worker, 'produce', native)
    monkeypatch.setattr(worker, 'evaluate',
                        lambda _project, _row: {'status': 'PASS', 'ledger': []})
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING', json.dumps({
        'required_gates': [], 'source_sha': 'fixture'}))
    with pytest.raises(worker.em.Refusal, match='OUTPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert not list(outside.iterdir())


def test_worker_publication_rejects_symlinked_output_root(tmp_path):
    inputs = tmp_path / 'inputs' / 'project'
    predecessor = inputs / 'phase3/stage3/pnr/placed.def'
    predecessor.parent.mkdir(parents=True)
    predecessor.write_text('input\n')
    output_target = tmp_path / 'output-target'
    output_target.mkdir()
    outputs = tmp_path / 'outputs'
    outputs.symlink_to(output_target, target_is_directory=True)

    with pytest.raises(worker.em.Refusal, match='OUTPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert not (output_target / 'backend_result.json').exists()


def test_worker_rejects_symlinked_input_bundle_root(tmp_path):
    input_target = tmp_path / 'input-target'
    input_target.mkdir()
    inputs = tmp_path / 'inputs'
    inputs.symlink_to(input_target, target_is_directory=True)
    outputs = tmp_path / 'outputs'

    with pytest.raises(worker.em.Refusal, match='INPUT_OUTSIDE_ROOT'):
        worker.execute(inputs, outputs, step_id='18', params={})
    assert not outputs.exists()


def test_worker_rejects_nested_input_file_symlink_before_copy(tmp_path):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    outside = tmp_path / 'outside.txt'
    outside.write_text('must not be copied\n')
    (inputs / 'alias.txt').symlink_to(outside)
    outputs = tmp_path / 'outputs'

    with pytest.raises(worker.em.Refusal, match='INPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert not (outputs / 'project' / 'alias.txt').exists()


def test_worker_rejects_nested_input_directory_symlink_before_copy(tmp_path):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('must not be copied\n')
    (inputs / 'alias').symlink_to(outside, target_is_directory=True)
    outputs = tmp_path / 'outputs'

    with pytest.raises(worker.em.Refusal, match='INPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert not (outputs / 'project' / 'alias' / 'secret.txt').exists()


def test_worker_rejects_symlink_race_between_input_census_and_copy(
        tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    (inputs / 'ordinary.txt').write_text('ordinary\n')
    outside = tmp_path / 'outside'
    outside.mkdir()
    secret = outside / 'SECRET'
    secret.write_text('must not be copied\n')
    outputs = tmp_path / 'outputs'
    original_census = worker._reject_input_tree_symlinks
    injected = []

    def census_then_race(root):
        original_census(root)
        if root == inputs.parent and not injected:
            (inputs / 'raced-link').symlink_to(outside, target_is_directory=True)
            injected.append(True)

    monkeypatch.setattr(worker, '_reject_input_tree_symlinks', census_then_race)
    with pytest.raises(worker.em.Refusal, match='INPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert injected == [True]
    assert secret.read_text() == 'must not be copied\n'
    assert not outputs.exists()


def test_worker_rejects_symlink_race_during_descriptor_open(
        tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    ordinary = inputs / 'ordinary.txt'
    ordinary.write_text('ordinary\n')
    outside = tmp_path / 'outside'
    outside.mkdir()
    secret = outside / 'SECRET'
    secret.write_text('must not be copied\n')
    outputs = tmp_path / 'outputs'
    real_open = worker.os.open
    raced = []

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        if path == 'ordinary.txt' and not raced:
            ordinary.unlink()
            ordinary.symlink_to(secret)
            raced.append(True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(worker.os, 'open', racing_open)
    with pytest.raises(worker.em.Refusal, match='INPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert raced == [True]
    assert secret.read_text() == 'must not be copied\n'
    assert not outputs.exists()


@pytest.mark.parametrize('destination', ['directory', 'symlink'])
def test_worker_rejects_preexisting_project_destination(tmp_path, destination):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    (inputs / 'ordinary.txt').write_text('ordinary\n')
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    project = outputs / 'project'
    if destination == 'directory':
        project.mkdir()
        marker = project / 'marker.txt'
    else:
        outside = tmp_path / 'outside'
        outside.mkdir()
        marker = outside / 'marker.txt'
        project.symlink_to(outside, target_is_directory=True)
    marker.write_text('preserve\n')

    with pytest.raises(worker.em.Refusal, match='OUTPUT_OUTSIDE_ROOT'):
        worker.execute(inputs.parent, outputs, step_id='18', params={})
    assert marker.read_text() == 'preserve\n'
