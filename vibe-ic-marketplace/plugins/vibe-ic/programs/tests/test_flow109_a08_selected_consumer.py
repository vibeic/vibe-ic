"""Named A08 consumer controls; retained native bytes are never ADC/PVT PASS.

Complete-population cases below are SOFTWARE CONTRACT controls at the observation
seam. The retained-point cases use the harvested producer/collector unchanged,
with a one-context manifest fixture, and must remain NOT_MEASURED.
"""
import json

import pytest

import analog_native_flow as native
from _hostpaths import require_repo












@pytest.fixture(autouse=True)
def forbid_native_launch(monkeypatch):
    def forbidden(*_a, **_kw):
        pytest.fail('consumer controls cannot launch native analyses')
    import analog_incremental_capture as capture
    monkeypatch.setattr(native.NativeCommands, '__call__', forbidden)
    monkeypatch.setattr(capture, 'main', forbidden)
    monkeypatch.setattr(capture, 'series_main', forbidden)






















def test_owned_registry_artifact_still_selects_position28():
    registry = json.loads(require_repo('vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json').read_text())
    row = next(value for value in registry['rows'] if value['position'] == 28)
    assert row['profiles'][0]['dispatch']['native_step_id'] == 'flow109.A08'
    assert [v['metric'] for v in row['obligations']] == ['pvt_load_modes', 'prelayout_performance']
