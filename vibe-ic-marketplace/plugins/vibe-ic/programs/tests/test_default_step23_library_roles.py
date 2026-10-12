"""The core PVT axis and auxiliary Liberty bindings have different subjects.

Native file writes are controlled by the existing receipt-bound tool fixture;
the actual Step23 consumer judges every scene. This is not IC acceptance.
"""
import json

import pytest

import librelane_signoff as signoff
import test_f15_step23_gates_read_the_tool_arm as fixture


@pytest.mark.parametrize('damage', ['none', 'pad_bytes', 'extra_bytes',
                                    'cell_header', 'cell_absent', 'pad_process'])
def test_auxiliary_models_do_not_redefine_the_core_pvt_axis(tmp_path, damage):
    project = fixture.gate_inputs(fixture.tool_project(tmp_path))
    folder = project / fixture.STA
    config_path = folder / 'config.json'
    config = json.loads(config_path.read_text())
    pad = '/pdk/p/libs.ref/io/lib/io__tt_025C_5v00_3v30.lib'
    stub = '/pdk/p/libs.ref/io/lib/analog_stubs.lib'
    pad_host = fixture._write(tmp_path / 'pdk_root/p/libs.ref/io/lib/io__tt_025C_5v00_3v30.lib',
        'library (io) {\n nom_process : 1 ;\n nom_voltage : 3.3 ;\n'
        ' nom_temperature : 100 ;\n}\n')
    stub_host = fixture._write(tmp_path / 'pdk_root/p/libs.ref/io/lib/analog_stubs.lib',
                               'library (stubs) { cell (unused) { area : 0 ; } }\n')
    # Each TT scene loads the same two auxiliary models, alongside its core
    # library. Multi-supply filenames and a no-PVT stub are real PDK shapes.
    if damage == 'pad_process':
        changed = pad.replace('__tt_', '__ss_')
        changed_host = pad_host.with_name(changed.rsplit('/', 1)[1])
        changed_host.write_bytes(pad_host.read_bytes())
        pad, pad_host = changed, changed_host
    config['PAD_LIBS'] = {'*_tt_025C_5v00': [pad]}
    config['EXTRA_LIBS'] = [stub]
    receipt_path = folder / 'vibeic_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['input']['liberty_files'].update({pad: fixture._sha(pad_host),
                                             stub: fixture._sha(stub_host)})
    for corner in fixture.CORNERS:
        log = folder / corner / 'sta.log'
        text = log.read_text()
        extra = [stub] + ([pad] if '_tt_' in corner else [])
        if damage == 'cell_absent':
            text = '\n'.join(line for line in text.splitlines()
                             if not line.startswith('Reading cell library')) + '\n'
        log.write_text(text + ''.join(
            f"Reading cell library for the '{corner}' corner at '{lib}'\n" for lib in extra))
    if damage == 'cell_absent':
        config['CELL_LIBS'] = {}
    if damage == 'cell_header':
        lib = fixture.CELL_LIBS['*_tt_025C_5v00'][0]
        host = tmp_path / 'pdk_root' / lib.lstrip('/').removeprefix('pdk/')
        host.write_text(host.read_text().replace('nom_temperature : 25', 'nom_temperature : 100'))
        receipt['input']['liberty_files'][lib] = fixture._sha(host)
    config_path.write_text(json.dumps(config))
    receipt_path.write_text(json.dumps(receipt))
    fixture.rebind(project)
    if damage in ('pad_bytes', 'extra_bytes'):
        target = pad_host if damage == 'pad_bytes' else stub_host
        target.write_text(target.read_text() + '// bytes changed after native run\n')
    rc, report = fixture.run_gate('sta_corner_record_completeness_check', project, tmp_path)
    if damage == 'none':
        assert (rc, report['verdict']) == (0, 'PASS'), report
        tt = next(row for row in report['corners'] if row['corner'] == 'nom_tt_025C_5v00')
        assert tt['voltage_v'] == 5.0 and tt['temperature_c'] == 25.0
        views = {item['path']: item for item in tt['liberties']}
        assert views[pad]['role'] == 'PAD_LIBS'
        assert views[pad]['header_pvt']['nom_voltage'] == 3.3
        assert views[stub]['role'] == 'EXTRA_LIBS'
        assert views[stub]['header_pvt'] is None
        assert views[stub]['filename_pvt_gaps']
    else:
        assert (rc, report['verdict']) == (1, 'FAIL' if damage == 'cell_absent' else 'NOT_MEASURED'), report
        assert 'R1_INCOMPLETE_CORNER_RECORD' in report['rules_violated']
        if damage == 'cell_absent':
            assert 'R4_MULTI_CORNER_CLAIM_UNSUPPORTED' in report['rules_violated']
