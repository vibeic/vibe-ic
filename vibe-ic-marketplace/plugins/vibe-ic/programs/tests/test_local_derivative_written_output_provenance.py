"""Actual derivative writes must reach the existing per-path provenance gate.

The neutral fixture makes fresh local Git upstream pulls through the ordinary
producer and consumer. Its challenge receipts are source-contract fixture data;
these controls are not a new proof of any benchmark RTL.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_reused_ip_local_derivative import _fixture, _apply, _h
import design_one_shot_runner as runner
import ip_catalog_pull as pull


def _gate(project, name):
    output = project / ('provenance-' + name + '.json')
    result = subprocess.run([
        sys.executable, str(Path(pull.__file__).with_name('provenance_output_hash_completeness_check.py')),
        str(project), '--json', str(output)], capture_output=True, text=True)
    return result, json.loads(output.read_text())


def test_actual_derivative_write_supersedes_only_replaced_output(tmp_path, monkeypatch):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    old_ledger = (project / 'provenance.jsonl').read_bytes()
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    result, report = _gate(project, 'after-write')
    assert result.returncode == 0, result.stdout + result.stderr
    assert report['verdict'] == 'PASS'
    assert report['outcome_census']['superseded'] == 1
    assert (project / 'provenance.jsonl').read_bytes().startswith(old_ledger)
    event = json.loads((project / 'provenance.jsonl').read_text().splitlines()[-1])
    assert event['exit_code'] == 0
    assert event['outputs'] == {
        'phase2/stage1/rtl/leaf.v': 'sha256:' + _h(project / 'phase2/stage1/rtl/leaf.v'),
        'phase2/stage1/rtl/SOURCE_MANIFEST.json': 'sha256:' + _h(project / 'phase2/stage1/rtl/SOURCE_MANIFEST.json'),
    }
    assert 'phase2/stage1/rtl/helper.v' not in event['outputs']
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['ip_fetch']['reuse_kind'] == 'LOCAL_DERIVATIVE'


@pytest.mark.parametrize('mutation', ['adapted_bytes', 'event_digest'])
def test_written_derivative_or_event_drift_still_refuses(tmp_path, monkeypatch, mutation):
    project, match, ref, _ = _fixture(tmp_path, monkeypatch)
    assert _apply(project, match, ref)['status'] == pull.PIN_VERIFIED
    if mutation == 'adapted_bytes':
        (project / 'phase2/stage1/rtl/leaf.v').write_text('module leaf; wire changed; endmodule\n')
    else:
        entries = [json.loads(line) for line in (project / 'provenance.jsonl').read_text().splitlines()]
        entries[-1]['outputs']['phase2/stage1/rtl/leaf.v'] = 'sha256:' + '0' * 64
        (project / 'provenance.jsonl').write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
    result, report = _gate(project, mutation)
    assert result.returncode == 1, result.stdout + result.stderr
    assert report['verdict'] == 'FAIL'
    assert any(row['rule'] == 'PROVENANCE_HASH_MISMATCH' and 'leaf.v' in row['detail'] for row in report['findings'])
    result = runner.step_rtl_gen(project, 'processor_cpu')
    assert result.status == 'FAIL', result.detail
