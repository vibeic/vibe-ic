"""Retained STA delivery controls; synthetic owners are not native row evidence.

The SDF and netlist are unchanged checked-in OpenSTA calibration outputs.
Admission/D69 are explicit software doubles and native launch is forbidden.
Export parsing, producer receipts, timing readers and D70 readback are real.
"""
import copy
import json
import shutil

import pytest

import flow109_final_electrical as final
import flow109_final_gls as gls
from _hostpaths import require_repo


def put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return final.files._record(project, path)


def reseal(folder, *, omit=()):
    fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
    paths = [p for p in folder.rglob('*') if p.is_file()
             and p.name != 'vibeic_receipt.json' and str(p.relative_to(folder)) not in omit]
    (folder / 'vibeic_receipt.json').write_text(json.dumps({
        'input': fingerprint,
        'sha256': {str(p.relative_to(folder)): final.digest(p) for p in paths}}))


def case(project, monkeypatch, *, slack=1.0):
    calibration = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                               'programs', 'calibration')
    for name in ('cal_chain.v', 'cal_chain.spef'):
        shutil.copyfile(calibration / name, project / name)
    refs = {name: put(project, name, 'SOFTWARE_ONLY ' + name)
            for name in ('final.odb', 'final.def', 'final.sdc', 'cells.lib')}
    refs['netlist'] = final.files._record(project, project / 'cal_chain.v')
    refs['spef'] = final.files._record(project, project / 'cal_chain.spef')
    basis = {'odb': refs['final.odb'], 'filled_def': refs['final.def'],
             'adopted_views': {'netlist': refs['netlist'], 'sdc': refs['final.sdc']},
             'spefs': {'nom': refs['spef']}, 'final_spefs': {'nom': refs['spef']}}
    d69 = put(project, 'd69.json', {'scope': 'SOFTWARE_ONLY_D69_DOUBLE'})
    folder = project / 'phase3/librelane/retained-sta'
    folder.mkdir(parents=True)
    corner = folder / 'nom_typ'; corner.mkdir()
    shutil.copyfile(calibration / 'cal_include_typ.sdf', corner / 'final.sdf')
    state = {'nl': str(project / refs['netlist']['path']),
             'sdc': str(project / 'final.sdc'), 'def': str(project / 'final.def'),
             'odb': str(project / 'final.odb'),
             'spef': {'nom_*': str(project / 'cal_chain.spef')},
             'sdf': {'nom_typ': str(corner / 'final.sdf')},
             'metrics': {metric + '__corner:nom_typ': slack if name.endswith('_ws') else 0
                         for name, metric in final.signoff.TIMING_METRICS.items()}}
    put(project, str(corner.relative_to(project) / 'sta.log'), 'SOFTWARE_ONLY STA execution\n')
    put(project, str(corner.relative_to(project) / final.signoff.CORNER_REPORT),
        final.signoff.NO_DERATE_MARKER + '\n')
    put(project, str(corner.relative_to(project) / 'unpropagated.rpt'), '')
    config = {'DESIGN_NAME': 'cal_chain', 'STA_CORNERS': ['nom_typ'],
              'meta': {'step': 'OpenROAD.STAPostPNR'},
              'CELL_LIBS': {'nom_*': [str(project / 'cells.lib')]}}
    config_ref = put(project, str(folder.relative_to(project) / 'config.json'), config)
    fingerprint = {'step': 'OpenROAD.STAPostPNR', 'image': 'SOFTWARE_ONLY_PIN',
                   'config': config_ref['sha256'],
                   'state_files': {str(project / ref['path']): ref['sha256']
                                   for key, ref in refs.items() if key != 'cells.lib'},
                   'liberty_files': {str(project / 'cells.lib'): refs['cells.lib']['sha256']}}
    put(project, str(folder.relative_to(project) / 'input_fingerprint.json'), fingerprint)
    put(project, str(folder.relative_to(project) / 'pdk_root.json'), {'path': '/software-only'})
    put(project, str(folder.relative_to(project) / 'invocation.log'), 'SOFTWARE_ONLY retained execution\n')
    state_ref = put(project, str(folder.relative_to(project) / 'state_out.json'), state)
    reseal(folder)
    manifest = {'schema': final.SCHEMA, 'required_corners': ['nom_typ'],
                'final_parasitics_receipt': d69, 'retained_sta_state': state_ref,
                'librelane': {'image': 'SOFTWARE_ONLY_PIN', 'pdk_root': '/software-only', 'pdk': 'neutral'}}
    put(project, final.INPUT, manifest)
    monkeypatch.setattr(final, 'require_launch_admission', lambda *a, **k: None)
    monkeypatch.setattr(final.extract, 'validate_final_parasitics', lambda *a: copy.deepcopy(basis))
    # A real launch here is a loader bug, not an allowed fallback for bad input.
    def no_launch(*a, **k):
        raise AssertionError('UNEXPECTED_NATIVE_LAUNCH')
    monkeypatch.setattr(final.signoff, 'run', no_launch)
    return folder, state, manifest, basis


def test_retained_native_exports_reach_existing_d71_reader_without_relaunch(tmp_path, monkeypatch):
    folder, state, manifest, basis = case(tmp_path, monkeypatch)
    result = final.execute(tmp_path, {'features': {'requires_scan': False}})
    assert result['component_status'] == 'PASS', result
    assert result['native_started'] is False
    assert result['native_reused'] is True
    assert result['retained_sta_state'] == manifest['retained_sta_state']
    assert result['final_sdfs'] == result['sdfs']
    observed = final.validate_final_electrical(tmp_path, result['receipt'])
    assert observed['final_sdfs'] == result['final_sdfs']
    for ref in result['final_sdfs'].values():
        census = gls._sdf_census(final.files._bound(tmp_path, ref), 'cal_chain')
        assert census['cells'] == 3 and census['delay_records'] == 5
    assert result['sdf_provenance']['spef_by_rc_scene'] == basis['final_spefs']
    assert result['sdf_export']['producer'] == 'OpenROAD.STAPostPNR.write_sdf'
    assert result['flow109_acceptance'] == 'NOT_MEASURED'
    assert 'final_sdf_annotation' in result['unmeasured_obligations']


def test_retained_negative_slack_stays_measured_fail(tmp_path, monkeypatch):
    case(tmp_path, monkeypatch, slack=-0.125)
    result = final.execute(tmp_path, {'features': {'requires_scan': False}})
    assert result['component_status'] == 'FAIL', result
    assert result['timing_judgment']['worst_setup']['ws'] == -0.125
    assert final.validate_final_electrical(tmp_path, result['receipt'], require_pass=False)['timing_status'] == 'FAIL'


@pytest.mark.parametrize('slack,status', [(1.0, 'NOT_MEASURED'), (-0.125, 'FAIL')])
def test_retained_scan_coverage_never_launches_or_hides_a_measured_failure(tmp_path, monkeypatch, slack, status):
    case(tmp_path, monkeypatch, slack=slack)
    def no_scan(*a, **k):
        raise AssertionError('UNEXPECTED_SCAN_LAUNCH')
    monkeypatch.setattr(final.signoff, 'run_scan_timing', no_scan)
    result = final.execute(tmp_path, {'features': {'requires_scan': True}})
    assert result['component_status'] == status, result
    assert result['scan_timing_readback']['status'] == 'NOT_MEASURED'
    assert result['native_started'] is False


def test_existing_d71_prepare_consumes_the_export_and_declared_scenario_population(tmp_path, monkeypatch):
    folder, _, _, basis = case(tmp_path, monkeypatch)
    result = final.execute(tmp_path, {'features': {'requires_scan': False}})
    assert result['component_status'] == 'PASS', result
    netlist = basis['adopted_views']['netlist']
    proof = put(tmp_path, 'proof.json', {'verdict': 'PASS', 'declared_partitions': ['cal_chain'],
        'partitions': {'cal_chain': {'status': 'PASS'}}, 'non_equivalent_points': [],
        'unproven_points': [], 'xbits_partitions': []})
    baseline = put(tmp_path, gls.D44_BASELINE, {
        'producer': 'flow109_final_lec', 'mapping': 'same_logical_bytes', 'proof': proof,
        'adopted_netlist': netlist,
        'consumer_netlists': {role: netlist for role in ('sta', 'lvs_reference', 'release')}})
    d44 = put(tmp_path, 'd44.json', {'schema': 'vibeic.flow109.final-lec.v1',
        'component_status': 'PASS', 'common_baseline': baseline, 'proof_receipt': proof})
    monkeypatch.setattr(gls.final_lec, 'validate_common_baseline', lambda *a: {'baseline': baseline})
    geometry = put(tmp_path, 'geometry.json', {'scope': 'SOFTWARE_ONLY final geometry'})
    d69_ref = result['d69_receipt']
    # Write the explicit upstream double before acquisition so the producer's
    # immutable d69 reference stays current; reacquire only this software case.
    d69_ref = put(tmp_path, d69_ref['path'], {'schema': final.extract.SCHEMA, 'step_id': 'D69',
        'producer': 'flow109_final_extract', 'component_status': 'PASS',
        'final_geometry': geometry, 'final_spefs': basis['final_spefs']})
    manifest = final._read(tmp_path / final.INPUT)
    manifest['final_parasitics_receipt'] = d69_ref
    put(tmp_path, final.INPUT, manifest)
    basis.update(final_geometry=geometry)
    result = final.execute(tmp_path, {'features': {'requires_scan': False}})
    assert result['component_status'] == 'PASS', result
    top = json.loads((folder / 'config.json').read_text())['DESIGN_NAME']
    models = []
    for name in sorted(gls.sgs.netlist_used_cells(final.files._bound(tmp_path, netlist).read_text())):
        models.append(put(tmp_path, name + '.v', f'module {name}(input A, output Y); not(Y,A); endmodule\n'))
    scenario_source = put(tmp_path, 'requirements/scenario-source.json',
                          {'scope': 'SOFTWARE_ONLY declared scenario', 'scenarios': ['functional']})
    requirements = put(tmp_path, 'requirements/gls.json', {
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': scenario_source},
        'required_corners': ['nom_typ'], 'required_scenarios': ['functional'],
        'required_timing_behaviors': sorted(gls.SUPPORTED_REQUIRED_BEHAVIORS)})
    bench = put(tmp_path, 'functional.v', f'module final_tb; reg A; wire Y; {top} dut(.A(A),.Y(Y));\n'
        'initial begin $sdf_annotate("@@VIBEIC_SDF_FILE@@", dut);\n'
        '$display("[TB functional] PASS"); $finish; end endmodule\n')
    operation = put(tmp_path, 'operation.json', {'schema': gls.SCHEMA, 'operation': 'Vibeic.GateLevelSim',
        'compile_flags': gls.sgs._IVERILOG_FLAGS, 'runtime_flags': ['-sdf-info']})
    bundle = put(tmp_path, 'models.json', {'models': models, 'model_closure': 'exact'})
    put(tmp_path, gls.INPUT, {'schema': gls.SCHEMA, 'top': top, 'd44_baseline': baseline,
        'd44_component': d44, 'd70_receipt': result['receipt'], 'requirements': requirements,
        'scenarios': {'functional': {'module': 'final_tb', 'testbench': bench}},
        'models': models, 'operation_config': operation, 'model_bundle': bundle})
    prepared = gls.prepare(tmp_path, {'requested_step': 'D71', 'native_step_id': 'flow109.D71',
                                      'runtime_tool_uses': []})
    assert prepared['d70_receipt'] == result['receipt']
    assert [row['id'] for row in prepared['cases']] == ['functional']
    assert prepared['requirements']['required_corners'] == ['nom_typ']
    assert prepared['sdf_census']['nom_typ']['delay_records'] == 5


@pytest.mark.parametrize('damage,reason', [
    ('foreign_state', 'D70_RETAINED_STA_FOREIGN'),
    ('missing_reference', 'FILL_STREAM_INPUT_UNBOUND'),
    ('stale_state', 'FILL_STREAM_INPUT_CHANGED'),
    ('foreign_netlist', 'D70_RETAINED_STA_BASIS_MISMATCH'),
    ('prefill_odb', 'D70_RETAINED_STA_BASIS_MISMATCH'),
    ('foreign_rc', 'D70_RETAINED_STA_BASIS_MISMATCH'),
    ('stale_sdf', 'LL_STEP_OUTPUT_UNBOUND'),
    ('wrong_top', 'LL_STAPOSTPNR_SDF_INVALID'),
    ('missing_delay', 'LL_STAPOSTPNR_SDF_INVALID'),
    ('unbound_timing', 'D70_RETAINED_STA_EVIDENCE_UNBOUND'),
    ('wrong_library', 'D70_NATIVE_LIBRARY_OR_CONFIG_CHANGED'),
    ('wrong_image', 'D70_NATIVE_CONFIG_CHANGED'),
    ('missing_corner', 'D70_NATIVE_CONFIG_CHANGED'),
])
def test_invalid_retained_delivery_refuses_without_falling_back(tmp_path, monkeypatch, damage, reason):
    folder, state, manifest, _ = case(tmp_path, monkeypatch)
    if damage == 'foreign_state':
        foreign = tmp_path.parent / (tmp_path.name + '-foreign')
        foreign.mkdir(); path = foreign / 'state_out.json'; path.write_text('{}')
        manifest['retained_sta_state'] = final.files._record(tmp_path, path)
    elif damage == 'missing_reference':
        manifest['retained_sta_state'] = None
    elif damage == 'stale_state':
        (folder / 'state_out.json').write_text('{}')
    elif damage in ('foreign_netlist', 'prefill_odb', 'foreign_rc'):
        ref = put(tmp_path, 'foreign.input', 'SOFTWARE_ONLY foreign basis')
        if damage == 'foreign_netlist':
            state['nl'] = str(tmp_path / ref['path'])
        elif damage == 'prefill_odb':
            state['odb'] = str(tmp_path / ref['path'])
        else:
            state['spef'] = {'nom_*': str(tmp_path / ref['path'])}
        manifest['retained_sta_state'] = put(tmp_path, str(folder.relative_to(tmp_path) / 'state_out.json'), state)
        reseal(folder)
    elif damage in ('stale_sdf', 'wrong_top', 'missing_delay'):
        path = folder / 'nom_typ/final.sdf'
        text = path.read_text()
        if damage == 'wrong_top':
            text = text.replace('(DESIGN "cal_chain")', '(DESIGN "foreign")')
        elif damage == 'missing_delay':
            text = text.replace('INTERCONNECT', 'ABSENT').replace('IOPATH', 'ABSENT')
        else:
            text += '\n'
        path.write_text(text)
        if damage != 'stale_sdf':
            reseal(folder)
    elif damage == 'unbound_timing':
        reseal(folder, omit=('nom_typ/' + final.signoff.CORNER_REPORT,))
    elif damage == 'wrong_library':
        (tmp_path / 'cells.lib').write_text('changed')
    elif damage == 'wrong_image':
        manifest['librelane']['image'] = 'FOREIGN_IMAGE'
    elif damage == 'missing_corner':
        manifest['required_corners'] = ['nom_typ', 'absent']
    put(tmp_path, final.INPUT, manifest)
    result = final.execute(tmp_path, {'features': {'requires_scan': False}})
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['reason'] == reason, result
    assert result['native_started'] is False
    assert not (tmp_path / final.postroute.STEP23_RECORD).exists()


@pytest.mark.parametrize('damage', ['manifest', 'producer_receipt', 'sdf'])
def test_retained_delivery_readback_reopens_original_inputs(tmp_path, monkeypatch, damage):
    folder, _, _, _ = case(tmp_path, monkeypatch)
    result = final.execute(tmp_path, {'features': {'requires_scan': False}})
    assert result['component_status'] == 'PASS', result
    path = {'manifest': tmp_path / final.INPUT,
            'producer_receipt': folder / 'vibeic_receipt.json',
            'sdf': folder / 'nom_typ/final.sdf'}[damage]
    path.write_text(path.read_text() + '\n')
    with pytest.raises((final.AdmissionRefusal, final.Refusal)):
        final.validate_final_electrical(tmp_path, result['receipt'])
