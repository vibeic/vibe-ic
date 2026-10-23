"""Current Default native STA owns capture; retained candidates stay immutable."""
import hashlib
import json
from pathlib import Path
import pytest
import drv_capture_plan as capture
import execution_policy
import librelane_contract


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('damage', [None, 'state', 'input', 'missing_fingerprint', 'receipt'])
def test_default_prefers_bound_current_state_over_retained_repair(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    current = tmp_path / 'phase3/librelane/23/01-openroad-stapostpnr/state_out.json'
    old = tmp_path / 'phase3/librelane/32-cand01/04-openroad-stapostpnr/state_out.json'
    material = tmp_path / 'phase3/stage3/pnr/routed.def'
    input_hash = put(material, {'layout': 'current'})
    sha = put(current, {'def': str(material), 'owner': 'current'})
    old_sha = put(old, {'owner': 'retained'})
    put(tmp_path / 'reports/phase3/sta_postpnr_signoff.json',
        {'sta_state': str(current), 'sta_state_sha256': sha})
    final = {'sta_state': str(old), 'sta_state_sha256': old_sha}
    put(tmp_path / 'reports/phase3/librelane_postroute_repair.json', {'final': final})
    def native_receipt(folder, step):
        assert folder == current.parent and step == 'OpenROAD.STAPostPNR'
        if damage == 'receipt':
            raise ValueError('native receipt changed')
        return {'input': {'state_files': {} if damage == 'missing_fingerprint' else {str(material): input_hash}}}
    monkeypatch.setattr(librelane_contract, 'validate_step_receipt', native_receipt)
    if damage == 'state':
        current.write_text('{}')
    if damage == 'input':
        material.write_text('changed')
    if damage:
        with pytest.raises(ValueError):
            capture._state(tmp_path)
    else:
        state, path = capture._state(tmp_path)
        assert state['owner'] == 'current' and path == current
    # An explicit candidate capture must still use its own measured state.
    state, path = capture._state(tmp_path, {'final': final})
    assert state['owner'] == 'retained' and path == old


@pytest.mark.parametrize('fault', [None, 'report_changed', 'extra_changed', 'report_mismatch'])
def test_default_current_selection_uses_native_ocv_recipe(tmp_path, monkeypatch, fault):
    import test_drv_signoff_judge as controls
    original = capture.build
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    def default_build(project, *, final_state=None):
        put(project / 'reports/phase3/sta_postpnr_signoff.json', final_state['final'])
        # This fixture supplies the native boundary; all OCV source and
        # applied-report verification below still runs in the actual builder.
        monkeypatch.setattr(librelane_contract, 'validate_step_receipt',
            lambda folder, step: json.loads((folder / 'vibeic_receipt.json').read_text()))
        return original(project)
    monkeypatch.setattr(capture, 'build', default_build)
    controls.test_current_sta_applied_ocv_reaches_the_real_capture_script(tmp_path, monkeypatch, fault)
