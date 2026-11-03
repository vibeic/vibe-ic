"""Synthetic glue controls; these do not qualify an EDA tool or a chip."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import librelane_pv_signoff as pv


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))


@pytest.mark.parametrize('case', ['clean', 'magic_error', 'klayout_error', 'density_error',
                                  'density_missing', 'changed_gds', 'missing', 'truncated', 'other_input'])
def test_final_pv_reuses_completed_native_reports(tmp_path, monkeypatch, case):
    import _native_erc
    import librelane_contract as contract
    import librelane_fill_dfm as fill
    import librelane_postroute as postroute
    import phase3_one_shot_runner as runner
    gds = tmp_path / 'phase3/stage4/gds/design.gds'
    put(gds, 'native GDS view')
    folder = tmp_path / 'phase3/native-sta'
    config = {'PDK': 'neutral', 'PDK_ROOT': str(tmp_path), 'DESIGN_NAME': 'design',
              'DEFAULT_CORNER': 'tt', 'TECH_LEFS': ['tech'], 'CELL_LEFS': ['cells'], 'LIB': ['lib']}
    put(folder / 'config.json', config)
    state = {key: str(tmp_path / (key + '.native')) for key in ('def', 'nl', 'sdc')}
    for path in state.values():
        put(Path(path), 'native view')
    put(tmp_path / 'reports/phase3/fill_librelane.json', {
        'default_stream': {'canonical': str(gds)}, 'gds': {'librelane': {}}})
    reports = tmp_path / 'reports/phase3'
    put(reports / 'drc_signoff_magic.rpt', 'magic DRC\nlayout sha256: ' + pv.digest(gds) +
        '\ntotal violations: ' + ('1' if case == 'magic_error' else '0') + '\n')
    put(reports / 'drc_signoff.rpt', '<report-database><items>' +
        ('<item><category>neutral.rule</category></item>' if case == 'klayout_error' else '') +
        '</items></report-database>')
    put(reports / 'drc_signoff.log', 'Input file: ' + str(gds if case != 'other_input' else tmp_path/'other.gds'))
    if case == 'changed_gds':
        gds.write_text('changed native GDS view')
    elif case == 'missing':
        (reports / 'drc_signoff.rpt').unlink()
    elif case == 'truncated':
        (reports / 'drc_signoff.rpt').write_text('<report-database><items>')
    calls = []
    def native(*args, **kwargs):
        calls.append(args[4])
        return {'verdict': 'PASS', 'metrics': {}}
    monkeypatch.setattr(pv, 'run_half', native)
    monkeypatch.setattr(postroute, 'stapostpnr_state', lambda p: (folder, state))
    monkeypatch.setattr(contract, 'resolve_image', lambda p: 'image')
    monkeypatch.setattr(contract, 'pdk_root_resolution', lambda *a, **k: {'path': str(tmp_path)})
    monkeypatch.setattr(contract, 'resolve_state_pdk_asset', lambda *a, **k: gds)
    monkeypatch.setattr(runner, 'PdkConfig', lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(fill, 'validate_density_result', lambda *a, **k: {
        'value': 'NOT_MEASURED' if case == 'density_missing' else int(case == 'density_error'),
        'status': 'MEASURED'})
    def erc(project, top, cfg, text, report, notes, **kwargs):
        put(report.with_suffix('.json'), {'verdict': 'PASS'})
        return True
    monkeypatch.setattr(_native_erc, 'emit', erc)
    result = pv.execute(tmp_path, {'context_sha256': 'context'})
    fresh = case in ('changed_gds', 'missing', 'truncated', 'other_input')
    assert ('drc' in calls) is fresh
    assert result['default_row_status'] == (
        'FAIL' if case in ('magic_error', 'klayout_error', 'density_error') else
        'NOT_MEASURED' if case == 'density_missing' else 'PASS')
    if not fresh:
        assert len(result['drc']['native_reports']) == 2
