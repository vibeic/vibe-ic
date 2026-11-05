"""Existing Default calls retain attempts; component PASS never becomes IC PASS."""
import json
import os
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_RETENTION_SEAMS_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import execution_policy as policy
import step_output_collector as versions


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})


def _saved(project, sid):
    rows = [r for r in versions._read_index(project)['steps'] if r['id'] == sid]
    assert rows, f'no retained invocation for Step {sid}'
    folder = project / 'steps' / rows[-1]['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())
















def test_actual_analog_fmeda_na_is_retained_without_faking_pass(tmp_path):
    import design_one_shot_runner as design
    result = design.step_fmeda_fault_injection(tmp_path, not_applicable='no digital RTL track')
    assert result.status == 'NOT_APPLICABLE'
    _, record = _saved(tmp_path, 'FS1')
    assert record['status'] == 'NOT_APPLICABLE'
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, 'FS1') is None
