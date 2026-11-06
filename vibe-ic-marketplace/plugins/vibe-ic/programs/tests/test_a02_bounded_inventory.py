"""Actual installed-input inventory controls, not model or design qualification.

The caller supplies a retained export from the attested image. Mutated and
historical copies below are TEST_ONLY consumer inputs, never adopted receipts.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import analog_native_front as front
import execution_analog_pdk_export as export
import pdk_analog_completeness_check as inventory
from declared_pdk_is_the_pdk_used_check import declared_target


@pytest.fixture
def project(tmp_path):
    raw = os.environ.get('A02_INVENTORY_CONTROL_PROJECT')
    if not raw:
        pytest.skip('requires retained actual installed-PDK export and live LOCAL attestation')
    retained = Path(raw)
    target, _ = declared_target(retained)
    assert target
    project = tmp_path / 'neutral'
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L5_ADI_SPEC.json').write_text(json.dumps({'analog_blocks': [{'name': 'neutral', 'type': 'amplifier'}]}))
    (docs / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {'pdk_target': target}}))
    shutil.copytree(retained / export.OUTPUT_BASE, project / export.OUTPUT_BASE)
    return project


def current_receipt(project):
    current = hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest()
    matches = [p for p in (project / export.OUTPUT_BASE).glob('*/_receipt.json')
               if json.loads(p.read_text()).get('helper_sha256') == current]
    assert len(matches) == 1
    return matches[0]


def consume(project):
    calls = []
    def run(program, args, **kwargs):
        calls.append(program)
        assert program == 'pdk_analog_completeness_check.py', 'model launch must not occur'
        done = subprocess.run([sys.executable, str(Path(inventory.__file__)), *args], capture_output=True, text=True)
        return dict(returncode=done.returncode, stdout=done.stdout, stderr=done.stderr)
    result = front.run_step('A02', project, {'name': 'neutral'}, {}, run)
    return result, calls


def check_inventory(project, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['pdk_analog_completeness_check.py', str(project)])
    return inventory.main()


def test_installed_population_reopened_by_actual_inventory(project, monkeypatch):
    assert check_inventory(project, monkeypatch) == 0


def test_actual_a02_stops_at_independent_missing_model_input(project):
    result, calls = consume(project)
    assert result['status'] == 'NOT_MEASURED'
    assert result['detail'].startswith('A02_MODEL_SMOKE_DECKS_ABSENT:')
    assert calls == []


@pytest.mark.parametrize('damage', ['copied_bytes', 'stale_receipt', 'wrong_target'])
def test_invalid_inventory_refuses_before_model_launch(project, monkeypatch, damage):
    receipt_path = current_receipt(project)
    receipt = json.loads(receipt_path.read_text())
    if damage == 'copied_bytes':
        copied = project / receipt['output_root'] / receipt['files'][0]['relative_path']
        copied.write_bytes(copied.read_bytes() + b'\nTEST_ONLY tamper\n')
    elif damage == 'stale_receipt':
        receipt['helper_sha256'] = '0' * 64
        receipt_path.write_text(json.dumps(receipt))
    else:
        path = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
        path.write_text(json.dumps({'fields': {'pdk_target': 'unavailable-neutral-process'}}))
    assert check_inventory(project, monkeypatch) == 1
    result, calls = consume(project)
    assert result['status'] != 'PASS'
    assert result['detail'].startswith('A02_MODEL_SMOKE_DECKS_ABSENT:')
    assert calls == []


@pytest.mark.parametrize('revision', ['source', 'image'])
def test_current_selection_reuses_with_historical_populations(project, monkeypatch, revision):
    original = current_receipt(project)
    receipt = json.loads(original.read_text())
    old = {k: v for k, v in receipt.items() if k not in ('receipt_digest', 'output_root')}
    if revision == 'source':
        old['helper_sha256'] = '0' * 64
    else:
        old['image_id'] = 'sha256:' + '0' * 64
    digest = hashlib.sha256(export._canonical(old)).hexdigest()
    relative = export.OUTPUT_BASE / digest
    directory = project / relative
    shutil.copytree(original.parent, directory)
    old.update(receipt_digest=digest, output_root=relative.as_posix())
    (directory / '_receipt.json').write_bytes(export._canonical(old) + b'\n')
    before = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in directory.rglob('*') if p.is_file()}
    def no_export(*args, **kwargs):
        raise AssertionError('valid current population must be reopened without exporting again')
    monkeypatch.setattr(export, 'export_bounded_pdk', no_export)
    result, calls = consume(project)
    assert result['detail'].startswith('A02_MODEL_SMOKE_DECKS_ABSENT:')
    assert calls == []
    assert check_inventory(project, monkeypatch) == 0
    assert before == {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in directory.rglob('*') if p.is_file()}


def test_missing_model_does_not_export_an_inventory(project, monkeypatch):
    def unexpected_export(*args, **kwargs):
        raise AssertionError('model measurement does not consume an export receipt')
    monkeypatch.setattr(export, 'export_bounded_pdk', unexpected_export)
    result, calls = consume(project)
    assert result['status'] == 'NOT_MEASURED'
    assert result['detail'].startswith('A02_MODEL_SMOKE_DECKS_ABSENT:')
    assert calls == []


def test_rehashed_omitted_required_include_refuses_actual_consumer(project, monkeypatch):
    reference = json.loads(Path(os.environ['A02_OMISSION_CONTROL']).read_text())
    omitted = reference['omitted_required_include']
    original = current_receipt(project)
    receipt = json.loads(original.read_text())
    row = next(row for row in receipt['files'] if row['relative_path'] == omitted['relative_path'])
    assert row == omitted, 'the exact original H1 source artifact must be used'
    positive = check_inventory(project, monkeypatch)
    assert positive == 0
    body = {k: v for k, v in receipt.items() if k not in ('receipt_digest', 'output_root')}
    body['files'] = [item for item in body['files'] if item != row]
    body['total_bytes'] -= row['size']
    digest = hashlib.sha256(export._canonical(body)).hexdigest()
    relative = export.OUTPUT_BASE / digest
    altered = project / relative
    shutil.copytree(original.parent, altered)
    (altered / row['relative_path']).unlink()
    body.update(receipt_digest=digest, output_root=relative.as_posix())
    (altered / '_receipt.json').write_bytes(export._canonical(body) + b'\n')
    shutil.rmtree(original.parent)  # TEST_ONLY copy, not a retained input/output.
    negative = check_inventory(project, monkeypatch)
    result, calls = consume(project)
    (project.parent / 'H1_OBSERVATION.json').write_text(json.dumps({
        'positive_rc': positive, 'negative_rc': negative, 'omitted': row,
        'test_only_recomputed_receipt': True, 'a02': result, 'calls': calls}, indent=2) + '\n')
    assert negative == 1
    assert result['status'] == 'NOT_MEASURED'
    assert result['detail'].startswith('A02_MODEL_SMOKE_DECKS_ABSENT:')
    assert calls == []
