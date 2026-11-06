"""R4 source controls. All substituted processes are SOFTWARE_FIXTURE_ONLY."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
import test_default_si_spice_power as fixture

LC, PST, SC = fixture.LC, fixture.PST, fixture.SC
put, write = fixture.put, fixture.write


def correlation_tool(p, folder, lib, monkeypatch, *, mismatch='MISMATCH', companion='nonzero', foreign=None):
    assert fixture.spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    substitute = PST.run_step30
    def run(project, image, root, pdk, **kwargs):
        doc = substitute(project, image, root, pdk, **kwargs)
        state = folder / 'state_out.json'
        inputs = LC.post_pnr_timing_inputs(p, state, 'nom_typ')
        base, changed = (doc['detail']['ngspice'][key] for key in ('base', 'mutated'))
        base.update(inputs=inputs, spef=str(p / inputs['spef']), spef_sha256=inputs['sha256']['spef'])
        for variant, data in (('base', base), ('mutated', changed)):
            row = data['paths'][0]
            sta = 1.0 if variant == 'base' else 1.5
            ratio = {'MISMATCH': 1.15, 'CRITICAL_MISMATCH': 1.3, 'CORRELATED': 1.05}[mismatch]
            row.update(path=1, startpoint='launch', endpoint='capture', sta_ns=sta,
                       spice_ns=sta * ratio, tolerance_pct=10.0, error_pct=(ratio - 1) * 100,
                       tran_step_ns=0.01, verdict=mismatch)
        if companion != 'success':
            changed['paths'][0].update(status='NOT_MEASURED', reason='SOFTWARE_FIXTURE_ONLY companion unavailable')
            if companion == 'nonzero':
                changed['paths'][0]['simulator_execution']['rc'] = 7
            else:
                changed['paths'][0].pop('simulator_execution')
        judgment = PST.judge(base, changed)
        doc.update(sta_state=str(state), sta_state_sha256=LC.digest(state),
                   arms={'ngspice': judgment},
                   **PST.step_verdict({'ngspice': judgment}, {'ngspice': base['paths']}))
        if foreign == 'state':
            doc['sta_state'] = str(p / 'foreign/state_out.json')
        elif foreign == 'state_hash':
            doc['sta_state_sha256'] = '0' * 64
        elif foreign == 'corner':
            doc['corner'] = 'other_corner'
        elif foreign == 'base_inputs':
            base['inputs']['sha256']['sta_netlist'] = '0' * 64
        put(p / 'reports/phase3/spice_path_tool.json', doc)
        return doc
    monkeypatch.setattr(PST, 'run_step30', run)


@pytest.mark.parametrize('mismatch', ['MISMATCH', 'CRITICAL_MISMATCH'])
@pytest.mark.parametrize('companion', ['nonzero', 'unmeasured'])
def test_step30_r4_current_measured_failure_survives_companion_error(tmp_path, monkeypatch, mismatch, companion):
    p, folder, lib = fixture.project(tmp_path)
    correlation_tool(p, folder, lib, monkeypatch, mismatch=mismatch, companion=companion)
    result = SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = SC.run_audit(p)
    assert gate.summary['measurement'] == 'MEASURED', gate.summary
    assert gate.summary.get('verdict') == 'FAIL', gate.summary
    assert gate.summary['current_binding'] == 'CURRENT'
    assert not gate.passed and result['status'] == 'RAN'
    assert gate.summary['arms']['ngspice']['verdict'] == mismatch
    if companion == 'nonzero':
        receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
        assert gate.summary['companion_errors'] == receipt['companion_errors']
        assert gate.summary['companion_errors'][0]['rc'] == 7
        assert gate.summary['companion_errors'][0]['variant'] == 'mutated'
    # The actual ordinary caller must still return FAIL for this measured result.


@pytest.mark.parametrize('foreign', ['state', 'state_hash', 'corner', 'base_inputs'])
def test_step30_r4_foreign_measured_failure_cannot_override_error(tmp_path, monkeypatch, foreign):
    p, folder, lib = fixture.project(tmp_path)
    correlation_tool(p, folder, lib, monkeypatch, foreign=foreign)
    SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = SC.run_audit(p)
    assert gate.summary['current_binding'] == 'REFUSED', gate.summary
    assert gate.summary['measurement'] == 'NOT_MEASURED'
    assert not (p / 'reports/phase3/spice_correlation.current.json').exists()


def test_step30_r4_companion_error_without_measured_failure_is_refused(tmp_path, monkeypatch):
    p, folder, lib = fixture.project(tmp_path)
    correlation_tool(p, folder, lib, monkeypatch, mismatch='CORRELATED')
    SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = SC.run_audit(p)
    assert gate.summary['current_binding'] == 'REFUSED', gate.summary
    assert gate.summary['measurement'] == 'NOT_MEASURED'
    assert not gate.passed


def test_step30_r4_current_failure_cannot_survive_input_byte_drift(tmp_path, monkeypatch):
    p, folder, lib = fixture.project(tmp_path)
    correlation_tool(p, folder, lib, monkeypatch)
    SC.run_installed_pdk_path_correlation(p, str(lib))
    path = p / 'phase3/stage3/extracted/neutral.spef'
    path.write_text(path.read_text() + '\n ')
    gate = SC.run_audit(p)
    assert gate.summary['current_binding'] == 'REFUSED'
    assert gate.summary['measurement'] == 'NOT_MEASURED'


def test_step30_r4_normal_current_correlation_remains_green(tmp_path, monkeypatch):
    p, folder, lib = fixture.project(tmp_path)
    correlation_tool(p, folder, lib, monkeypatch, mismatch='CORRELATED', companion='success')
    gate = SC.run_audit(p)
    assert gate.passed and gate.summary['verdict'] == 'PASS'
    assert gate.summary['current_binding'] == 'CURRENT'


@pytest.mark.parametrize('emits', [False, True], ids=['stale_zero_exit_no_output', 'fresh_export'])
def test_step30_r4_ordinary_extraction_requires_current_cell_export(tmp_path, monkeypatch, emits):
    p, folder, lib = fixture.project(tmp_path)
    netlist = p / 'phase3/stage3/pnr/neutral_pnr.v'
    # Structural instances are separate declared INPUT statements, as in the
    # producer's netlist reader; this fixture must actually select BUF.
    netlist.write_text(netlist.read_text().replace('BUF ', '\nBUF '))
    fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
    fingerprint['state_files'][str(netlist)] = LC.digest(netlist)
    fixture.seal(folder, fingerprint)
    assert fixture.spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    substitute = PST.run_step30
    root = p / 'fixture_pdk/neutral'
    cells = '.subckt BUF A Z VDD VSS\nM1 Z A VSS VSS neutral_model\n.ends\n'
    write(root / 'cells.spice', cells)
    write(root / 'libs.tech/librelane/config.tcl', 'set ::env(MAGICRC) "$::env(PDK_ROOT)/$::env(PDK)/libs.tech/magic/neutral.magicrc"\n')
    write(lib, 'library(neutral_typ) {\n voltage_map(VDD, 1.8);\n voltage_map(VSS, 0);\n operating_conditions(typ) { voltage: 1.8; }\n}\n')
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    data = json.loads(config.read_text())
    data.update(VDD_PIN='VDD', GND_PIN='VSS', CELL_SPICE_MODELS=['/pdk/neutral/cells.spice'],
                CELL_GDS=['/pdk/neutral/cells.gds'])
    write(root / 'cells.gds', 'SOFTWARE_FIXTURE_ONLY declared layout input\n')
    put(config, data);put(folder / 'config.json', data)
    fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
    fingerprint.update(config=LC.digest(config), config_files={'/pdk/neutral/neutral.lib': LC.digest(lib)},
                       liberty_files={'/pdk/neutral/neutral.lib': LC.digest(lib)})
    fixture.seal(folder, fingerprint)
    directory = p / 'phase3/tool_arms/30/ngspice/base'
    stale = cells.replace('M1', '* SOFTWARE_FIXTURE_ONLY STALE_EXPORT\nM1', 1)
    write(directory / 'extract/BUF.spice', stale)
    write(directory / 'extract/BUF.ext', 'SOFTWARE_FIXTURE_ONLY STALE_EXT\n')
    consumed = []
    def magic(image, project, mounts, argv, cwd, **kwargs):
        assert argv[0] == 'magic', 'No native STA/simulator call is authorized by this unit control'
        if emits:
            fresh = cells.replace('M1', '* SOFTWARE_FIXTURE_ONLY FRESH_EXPORT\nM1', 1)
            write(Path(cwd) / 'BUF.spice', fresh)
        return SimpleNamespace(returncode=0, stdout='SOFTWARE_FIXTURE_ONLY Magic zero exit\n', stderr='')
    class AfterExtraction(Exception):
        pass
    def stop_before_models(*args, **kwargs):
        consumed.append((directory / 'cells_folded.spice').read_text())
        raise AfterExtraction
    def run(project, image, root, pdk, **kwargs):
        # Real prepare_arm/extract_cells; remaining transport is the same labelled
        # software producer used by the accepted ordinary current-contract tests.
        try:
            PST.prepare_arm(project, image, folder / 'state_out.json', 'nom_typ',
                            pdk_root=root, pdk=pdk, out_dir=directory)
        except AfterExtraction:
            return substitute(project, image, root, pdk, **kwargs)
        raise AssertionError('The unit control must stop before native model/tool work')
    monkeypatch.setattr(PST, '_docker', magic)
    monkeypatch.setattr(PST, 'model_file', stop_before_models)
    monkeypatch.setattr(PST, 'run_step30', run)
    result = SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = SC.run_audit(p)
    assert result['status'] == ('RAN' if emits else 'ERROR'), result
    assert gate.passed == emits, gate.summary
    assert all('STALE_EXPORT' not in text for text in consumed)
    assert not (directory / 'extract/BUF.ext').exists()
    if emits:
        assert consumed and 'FRESH_EXPORT' in consumed[0]
    else:
        assert not consumed and not (p / 'reports/phase3/spice_correlation.current.json').exists()
        assert 'LL_SPICE_CURRENT_CELL_EXPORT_MISSING' in result['reason']


def test_step30_r4_missing_measured_failure_names_current_base_search(tmp_path, monkeypatch):
    p, folder, lib = fixture.project(tmp_path)
    correlation_tool(p, folder, lib, monkeypatch, mismatch='CORRELATED', companion='nonzero')
    result = SC.run_installed_pdk_path_correlation(p, str(lib))
    gate = SC.run_audit(p)
    assert result['status'] == 'ERROR' and not gate.passed
    assert gate.summary['current_binding'] == 'REFUSED'
    assert gate.summary['measurement'] == 'NOT_MEASURED'
    reason = result['reason']
    assert reason.startswith('CURRENT_STEP30_MEASURED_FAILURE_MISSING'), reason
    assert str(folder / 'state_out.json') in reason, reason
    assert 'tool.detail[ngspice].base.paths' in reason and 'inspected' in reason, reason
