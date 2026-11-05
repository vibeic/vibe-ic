"""Public adapter controls; no timing or GLS execution is claimed."""
import json
from types import SimpleNamespace

import pytest
import _container_exec
import _delivery_route
import flow109
import librelane_postroute
from test_flow109_selection import profile


@pytest.fixture
def selected(tmp_path, monkeypatch):
    assert _delivery_route.admit(tmp_path, 'ic') is None
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': profile()}))
    monkeypatch.setattr(_container_exec, 'no_container_route', lambda: True)
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(tmp_path / 'pdk'))
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode='default', entry_step='D53',
        exit_step='D53', container='', top_name='core', pdk='declared_pdk')
    return tmp_path, args


def test_missing_native_timing_state_is_unmeasured(selected):
    project, args = selected
    # Real missing-input reader; it refuses before invoking any native tool.
    assert flow109.prepare_front_door(args, project) == 2
    row = json.loads((project / 'reports/flow109/default_rows/D53.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED'
    assert row['completed'] is False and row['native_started'] is False
    assert row['native_result']['reason'] == 'LL_STAPOSTPNR_STATE_ABSENT'


@pytest.mark.parametrize('status,code', [('PASS', 0), ('FAIL', 1), ('NOT_MEASURED', 2)])
def test_completed_native_verdict_is_preserved(selected, monkeypatch, status, code):
    project, args = selected
    monkeypatch.setattr(librelane_postroute, 'gate_level_sim',
        lambda *_: {'verdict': status, 'wall_seconds': 0, 'test_only': True})
    assert flow109.prepare_front_door(args, project) == code
    row = json.loads((project / 'reports/flow109/default_rows/D53.json').read_text())
    assert row['default_row_status'] == status
    assert row['completed'] is (status == 'PASS')
