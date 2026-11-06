"""The STA and L24 consumers bind the same STAPostPNR scene matrix."""
import json

from _hostpaths import require_repo
from test_f15_step23_gates_read_the_tool_arm import (STA, rebind, run_gate,
                                                      tool_project)


def _six_scenes(project):
    config = project / STA / 'config.json'
    data = json.loads(config.read_text())
    data['STA_CORNERS'] = [c for c in data['STA_CORNERS']
                           if c not in {'max_ff_n40C_5v50', 'min_tt_025C_5v00',
                                        'nom_ss_125C_4v50'}]
    config.write_text(json.dumps(data))
    rebind(project)


def test_sta_record_requires_every_process_rc_combination(tmp_path):
    project = tool_project(tmp_path)
    _six_scenes(project)
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert rc == 1 and report['verdict'] == 'NOT_MEASURED', report
    missing = [r for r in report['corners'] if r['measurement_status'] == 'NOT_MEASURED'
               and not r['reported']]
    assert {(r['process'], r['rc_corner']) for r in missing} == {
        ('ff', 'max'), ('tt', 'min'), ('ss', 'nom')}


def test_sta_record_binds_liberty_header_and_spef_bytes(tmp_path):
    project = tool_project(tmp_path)
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert (rc, report['verdict']) == (0, 'PASS'), report
    assert len(report['corners']) == 9
    for row in report['corners']:
        assert row['measurement_status'] == 'MEASURED'
        assert row['spef_sha256'] and row['liberties'][0]['sha256']
        assert row['liberties'][0]['header_pvt']['nom_voltage'] == row['voltage_v']


def test_wrong_spef_scene_is_not_measured(tmp_path):
    project = tool_project(tmp_path)
    state = project / STA / 'state_out.json'
    data = json.loads(state.read_text())
    data['spef']['max_*'] = data['spef']['nom_*']
    state.write_text(json.dumps(data))
    rebind(project)
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    row = next(r for r in report['corners'] if r['corner'] == 'max_ss_125C_4v50')
    assert rc == 1 and row['measurement_status'] == 'NOT_MEASURED', report
    assert 'spef' in row['scope_gaps'] or 'rc_corner' in row['scope_gaps']


def test_wrong_liberty_header_is_not_measured(tmp_path):
    project = tool_project(tmp_path)
    liberty = (tmp_path / 'pdk_root/p/libs.ref/cells/lib/'
               'cells__ss_125C_4v50.lib')
    liberty.write_text(liberty.read_text().replace('nom_voltage : 4.5',
                                                    'nom_voltage : 5.5'))
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    row = next(r for r in report['corners'] if r['corner'] == 'max_ss_125C_4v50')
    assert rc == 1 and row['measurement_status'] == 'NOT_MEASURED', report
    assert 'liberty_header_pvt' in row['scope_gaps']


def test_native_stapostpnr_ws_reports_supply_historical_scene_rows(tmp_path):
    project = tool_project(tmp_path)
    folder = project / STA
    for corner in json.loads((folder / 'config.json').read_text())['STA_CORNERS']:
        scene = folder / corner
        for file, value in (('ws.max.rpt', 0.2), ('ws.min.rpt', 0.1),
                            ('tns.max.rpt', 0.0), ('tns.min.rpt', 0.0)):
            (scene / file).write_text(f'{corner}: {value}\n')
        (scene / 'vibeic_signoff.rpt').unlink()
    rebind(project)
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert rc == 1 and report['rules_violated'] == ['R5_DRV_UNQUERIED'], report
    assert len(report['corners']) == 9
    assert all(r['measurement_status'] == 'MEASURED' for r in report['corners'])


def test_historical_native_fallback_reads_real_stapostpnr_scene_reports(tmp_path):
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                          'programs', 'tests', 'fixtures', 'librelane_import',
                          '8HD-4', 'runs', 'cmp3', '55-openroad-stapostpnr')
    project = tool_project(tmp_path)
    folder = project / STA
    for corner in json.loads((folder / 'config.json').read_text())['STA_CORNERS']:
        for file in ('ws.max.rpt', 'ws.min.rpt', 'tns.max.rpt', 'tns.min.rpt'):
            (folder / corner / file).write_bytes((source / corner / file).read_bytes())
        (folder / corner / 'vibeic_signoff.rpt').unlink()
    rebind(project)
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    rows = {r['corner']: r for r in report['corners']}
    assert rc == 1 and report['rules_violated'] == ['R5_DRV_UNQUERIED'], report
    assert len(rows) == 9 and all(r['measurement_status'] == 'MEASURED'
                                  for r in rows.values())
    assert rows['max_ss_125C_4v50']['setup_wns_ns'] == 3.0357548445415716
    assert rows['max_ss_125C_4v50']['hold_wns_ns'] == 1.5086778919839563


def test_declared_custom_emitter_cannot_fall_back_when_all_reports_absent(tmp_path):
    project = tool_project(tmp_path)
    folder = project / STA
    config = folder / 'config.json'
    data = json.loads(config.read_text())
    data['STA_EXTRA_CORNER_TCL_FILE'] = str(project / 'custom.tcl')
    config.write_text(json.dumps(data))
    for corner in data['STA_CORNERS']:
        (folder / corner / 'vibeic_signoff.rpt').unlink()
        for file, value in (('ws.max.rpt', 0.2), ('ws.min.rpt', 0.1),
                            ('tns.max.rpt', 0.0), ('tns.min.rpt', 0.0)):
            (folder / corner / file).write_text(f'{corner}: {value}\n')
    rebind(project)
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert rc == 1 and all(r['measurement_status'] == 'NOT_MEASURED'
                           for r in report['corners']), report


def test_unrecorded_liberty_input_digest_is_not_measured(tmp_path):
    project = tool_project(tmp_path)
    receipt = project / STA / 'vibeic_receipt.json'
    data = json.loads(receipt.read_text())
    data['input'].pop('liberty_files')
    receipt.write_text(json.dumps(data))
    rc, report = run_gate('sta_corner_record_completeness_check', project, tmp_path)
    assert rc == 1 and all(r['measurement_status'] == 'NOT_MEASURED'
                           for r in report['corners']), report
