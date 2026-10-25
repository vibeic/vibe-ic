"""Text generation repairs retain evidence without inventing source RTL."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_dispatch as dispatch
import benchmark_io_adapter as bio


def staged(tmp_path, context=None):
    project = tmp_path / 'project'
    prompt = 'Module name: cedar_pulse\nRegister a pulse after three accepted samples.\n'
    bio.stage('cvdp', {'id': 'unit', 'record': {'input': {
        'prompt': prompt, 'context': context or {}}}}, project)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    public = bio.public_original_input(project, 'unit', prompt_hash)
    task = {
        'id': 'unit', 'project': str(project), 'prompt_sha256': prompt_hash,
        'rtl_sha256': 'a' * 64, 'public_original_input': public,
        'program_routing': {'nature': 'spec_generation'},
        'program_verification': {'runner_invocation': {'argv': [
            'python3', 'vibe_ic_one_shot_runner.py', str(project),
            '--rtl-input', 'original', '--entry-step', '1', '--exit-step', '2']}}}
    record = {
        'schema': 'vibeic.benchmark.ai_repair_record.v1', 'id': 'unit',
        'prompt_sha256': prompt_hash, 'parent_rtl_sha256': 'a' * 64,
        'repaired_rtl_sha256': 'b' * 64, 'challenge_sha256': 'c' * 64,
        'author': {'kind': 'AI', 'model': 'test-actor'}, 'oracle_accessed': False,
        'rationale': 'Restore the sampled register behavior required by the original prompt and verified immutable challenge.'}
    path = tmp_path / 'repair.json'
    path.write_text(json.dumps(record))
    return task, record, path


def validate(task, path):
    return dispatch._validate_repair_record(path, task, 'b' * 64, {'sha256': 'c' * 64})


def test_text_generation_record_consumes_original_manifest_and_repair_bindings(tmp_path):
    task, record, path = staged(tmp_path)
    assert task['public_original_input']['status'] == 'NOT_PROVIDED'
    got, reasons = validate(task, path)
    assert not reasons
    assert got['parent_rtl_sha256'] == task['rtl_sha256']
    assert 'repair_contract' not in got
    # A text-only repair may not invent source preservation declarations.
    record['repair_contract'] = {'schema': 'vibeic.source_bounded_completion.v1'}
    path.write_text(json.dumps(record))
    assert 'cannot declare supplied RTL' in ' '.join(validate(task, path)[1])


@pytest.mark.parametrize('field', [
    'prompt_sha256', 'parent_rtl_sha256', 'repaired_rtl_sha256', 'challenge_sha256'])
def test_text_generation_rejects_every_stale_repair_binding(tmp_path, field):
    task, record, path = staged(tmp_path)
    record[field] = 'd' * 64
    path.write_text(json.dumps(record))
    assert field in ' '.join(validate(task, path)[1])


def test_supplied_source_and_other_routes_still_require_source_contract(tmp_path):
    task, record, path = staged(tmp_path, {'cedar.sv': 'module cedar; endmodule\n'})
    assert task['public_original_input']['status'] == 'PRESENT'
    assert 'lacks repair_contract' in ' '.join(validate(task, path)[1])
    # Removing the task's source claim cannot drop the real staged source.
    task['public_original_input'] = {**task['public_original_input'],
                                     'status': 'NOT_PROVIDED', 'files': []}
    assert 'PUBLIC_INPUT_HANDOFF_INVALID' in ' '.join(validate(task, path)[1])
    other, _, other_path = staged(tmp_path / 'other')
    other['program_routing']['nature'] = 'rtl_repair'
    assert 'source-bounded repair requires' in ' '.join(validate(other, other_path)[1])
    other['program_routing']['nature'] = 'spec_generation'
    other['program_verification']['runner_invocation']['argv'] = ['python3', 'runner.py']
    assert 'source-bounded repair requires' in ' '.join(validate(other, other_path)[1])
