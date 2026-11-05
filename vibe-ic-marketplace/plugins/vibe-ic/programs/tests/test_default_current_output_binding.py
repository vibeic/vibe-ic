"""A resumed Default consumer reads the current attempt, retaining old proof."""
import json

import pytest

import flow_compliance_check as compliance
import step_output_collector as versions




@pytest.mark.parametrize('present', [True, False])
def test_current_step_binding_replaces_stale_observation_without_rewriting_history(tmp_path, present):
    spec = 'reports/phase3/sta/architectural_residual.json'
    old = versions.begin_step(tmp_path, '23')
    versions.finish_step(tmp_path, old, verdict='FAIL', result={'reason': 'old invocation'})
    old_folder = tmp_path / old['storage_root'] / old['folder']
    old_written = {'id': '23', 'produced': [], 'findings': [
        {'dimension': 'D3', 'spec': spec, 'reason': 'absent'}]}
    (old_folder / 'written.json').write_text(json.dumps(old_written))
    before = {p.name: p.read_bytes() for p in old_folder.iterdir() if p.is_file()}
    current = versions.begin_step(tmp_path, '23')
    target = tmp_path / spec
    if present:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'verdict': 'PASS', 'invoked_as': 'producer'}))
    versions.publish_producer_outputs(tmp_path, current)
    binding = compliance._load_step_binding(tmp_path)
    assert binding['sources']['23'] == 'step_folder'
    observed = binding['rows']['23'][spec]
    assert observed['produced'] == ([spec] if present else [])
    assert observed['not_produced'] == (None if present else 'absent')
    assert versions.latest_pass(tmp_path, '23') is None
    versions.finish_step(tmp_path, current, verdict='FAIL', result={'native': 'NOT_MEASURED'})
    assert versions.latest_pass(tmp_path, '23') is None
    assert all((old_folder / name).read_bytes() == data for name, data in before.items())
    assert (tmp_path / current['storage_root'] / current['folder'] / 'written.json').is_file()
