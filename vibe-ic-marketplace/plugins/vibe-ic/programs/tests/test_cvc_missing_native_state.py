"""Missing LVS input and native result propagation; no CVC execution claimed."""
import json

import pytest
import phase3_one_shot_runner as backend


def test_missing_lvs_report_does_not_start_cvc(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('CVC must not start without its LVS state')
    monkeypatch.setattr(backend, '_native_cvc_category', forbidden)
    result = backend._cvc_from_native_state(tmp_path)
    assert result['verdict'] == 'NOT_MEASURED'
    assert result['native_started'] is False
    assert result['reason'] == 'CVC_NATIVE_INPUT_ABSENT'
    assert result['wall_seconds'] >= 0
    from types import SimpleNamespace
    import _container_exec, _delivery_route, flow109
    from test_flow109_selection import profile
    assert _delivery_route.admit(tmp_path, 'ic') is None
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': profile()}))
    monkeypatch.setattr(_container_exec, 'no_container_route', lambda: True)
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode='default', entry_step='D59',
        exit_step='D59', container='')
    assert flow109.prepare_front_door(args, tmp_path) == 2
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D59.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED' and row['native_started'] is False


@pytest.mark.parametrize('status,total', [('PASS', 0), ('FAIL', 1)])
def test_native_cvc_verdict_is_preserved(tmp_path, monkeypatch, status, total):
    folder = tmp_path / 'native_lvs'
    folder.mkdir()
    config = {'PDK': 'process', 'DESIGN_NAME': 'core',
        'LIB': {'corner': [str(folder / 'cells.lib')]},
        'TECH_LEFS': {'corner': str(folder / 'tech.lef')},
        'CELL_LEFS': [str(folder / 'cells.lef')]}
    for name in ('cells.lib', 'tech.lef', 'cells.lef'):
        (folder / name).write_text('TEST ONLY')
    (folder / 'config.json').write_text(json.dumps(config))
    (folder / 'state_out.json').write_text(json.dumps({
        'spice': str(folder / 'layout.sp'), 'nl': str(folder / 'core.v')}))
    record = backend._pl.reports_phase3_dir(tmp_path) / 'librelane_pv_lvs.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'metrics': {'design__lvs_error__count': {'folder': str(folder)}}}))
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(tmp_path / 'pdk'))
    monkeypatch.setattr(backend, '_native_cvc_category', lambda *a, **kw: {
        'result': status, 'counts': {'Total': total}, 'test_only': True})
    result = backend._cvc_from_native_state(tmp_path)
    assert result['verdict'] == status
    assert result['CVC_total'] == total
