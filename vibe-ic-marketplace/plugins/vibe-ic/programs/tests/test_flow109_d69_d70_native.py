"""Opt-in native Default control. Inputs are copied real SPM/GF180 artefacts."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

import librelane_signoff as signoff
import flow109_final_extract as d69
import flow109_final_electrical as d70
from spef_extraction_check import scan_spef


def _validator_fixture(tmp_path, monkeypatch, *, required=('tt', 'ss'), state_order=('ss', 'tt')):
    folder = tmp_path / 'sta'; folder.mkdir()
    (folder / 'state_out.json').write_text('{}')
    receipt_ref = {'path': 'component.json', 'sha256': 'r' * 64}
    state_record = {'path': 'sta/state_out.json', 'sha256': 's' * 64}
    netlist = {'path': 'netlist.v', 'sha256': 'n' * 64}
    sdc = {'path': 'constraint.sdc', 'sha256': 'c' * 64}
    final_spefs = {'rc_tt': {'path': 'tt.spef', 'sha256': 't' * 64}}
    sdf_records = {corner: {'path': f'{corner}.sdf', 'sha256': corner * 32}
                   for corner in state_order}
    state = {'sdf': {corner: f'/native/{corner}.sdf' for corner in state_order}}
    judgment = {'verdict': 'PASS'}; sources = {'source': 'unchanged'}
    record = {
        'schema': d70.SCHEMA, 'component_status': 'PASS', 'execution_context': {},
        'operation_sources': sources, 'producer': 'flow109_final_electrical',
        'sdf_role': 'final', 'd69_receipt': receipt_ref,
        'final_parasitics_receipt': receipt_ref, 'final_sdfs': sdf_records,
        'sdfs': sdf_records, 'required_corners': list(required), 'netlist': netlist,
        'sdc': sdc, 'sta_state': state_record, 'timing_judgment': judgment,
        'sdf_provenance': {'basis': 'D69_final_parasitics', 'd69_receipt': receipt_ref,
                           'sta_state': state_record, 'declared_corners': list(required),
                           'spef_by_rc_scene': final_spefs}}
    monkeypatch.setattr(d70.files, '_bound', lambda *_: tmp_path / 'component.json')
    monkeypatch.setattr(d70, '_read', lambda *_: record)
    monkeypatch.setattr(d70, 'require_launch_admission', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(d70, 'operation_sources', lambda: sources)
    monkeypatch.setattr(d70.extract, 'validate_final_parasitics', lambda *_: {
        'adopted_views': {'netlist': netlist, 'sdc': sdc}, 'final_spefs': final_spefs})
    monkeypatch.setattr(d70.postroute, 'stapostpnr_state', lambda *_: (folder, state))
    monkeypatch.setattr(d70.signoff, 'corner_timing', lambda *_: {c: {} for c in state_order})
    monkeypatch.setattr(d70.signoff, 'judge_timing', lambda *_: judgment)
    monkeypatch.setattr(d70.postroute, 'corner_sdfs',
                        lambda *_: {c: Path(f'/native/{c}.sdf') for c in state_order})
    def record_for(_project, path):
        if str(path).endswith('state_out.json'):
            return state_record
        return sdf_records[Path(path).stem]
    monkeypatch.setattr(d70.files, '_record', record_for)
    return receipt_ref


def _put_ref(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value))
    else:
        path.write_text(str(value))
    return {'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _owner_binding_fixture(tmp_path, monkeypatch, *, ir_verdict='PASS'):
    d70_ref = _put_ref(tmp_path, 'reports/flow109/D70/current/component.json', {
        'schema': d70.SCHEMA, 'component_status': 'PASS',
        'execution_context': {'features': {'requires_ir': True, 'requires_em': True}},
        'final_parasitics_receipt': {'path': 'd69.json', 'sha256': 'd' * 64},
        'netlist': {'path': 'final.v', 'sha256': 'n' * 64}})
    manifest = {'schema': d70.OWNER_INPUT_SCHEMA, 'd70_component': d70_ref,
                'd55_activity_component': {'path': 'd55.json', 'sha256': '5' * 64},
                'd55_activity_freeze': {'path': 'freeze.json', 'sha256': 'f' * 64},
                'd56_power_component': {'path': 'd56.json', 'sha256': '6' * 64},
                'd57_ir_component': {'path': 'd57.json', 'sha256': '7' * 64}}
    _put_ref(tmp_path, d70.OWNER_INPUT, manifest)
    monkeypatch.setattr(d70, 'validate_final_electrical', lambda *_: {})
    monkeypatch.setattr(d70.extract, 'validate_final_parasitics', lambda *_: {})
    monkeypatch.setattr(d70, '_activity_binding', lambda *_: {'scope': 'D55 current'})
    monkeypatch.setattr(d70, '_power_binding', lambda *_: {
        'verdict': 'PASS', 'scope': 'vectorless static STAPostPNR power'})
    monkeypatch.setattr(d70, '_ir_binding', lambda *_: {
        'verdict': ir_verdict, 'scope': 'static IR only'})
    return d70_ref


def test_native_failure_precedence_is_not_relabelled_unmeasured():
    assert d69._native_refusal_status('LL_STEP_FAILED') == 'FAIL'
    assert d70._native_refusal_status('LL_STEP_FAILED') == 'FAIL'
    assert d69._native_refusal_status('LL_LOCAL_IMAGE_UNATTESTED') == 'NOT_MEASURED'
    assert d70._native_refusal_status('LL_DIRECT_SPEF_MISSING') == 'NOT_MEASURED'


def test_d70_refuses_an_empty_declared_corner_population_before_native(tmp_path, monkeypatch):
    manifest = tmp_path / d70.INPUT
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'schema': d70.SCHEMA,
                                    'final_parasitics_receipt': {'path': 'unused',
                                                                 'sha256': '0' * 64}}))
    monkeypatch.setattr(d70, 'require_launch_admission', lambda *args, **kwargs: None)
    result = d70.execute(tmp_path, {'context_sha256': 'source-control'})
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['reason'] == 'D70_REQUIRED_CORNERS_ABSENT'
    assert result['native_started'] is False


def test_d70_producer_accepts_equal_corner_population_in_different_order(tmp_path, monkeypatch):
    def ref(path):
        return {'path': str(path.relative_to(tmp_path)), 'sha256': '0' * 64}

    inputs = {name: tmp_path / name for name in (
        'filled.odb', 'filled.def', 'netlist.v', 'constraint.sdc', 'nom.spef',
        'tt.sdf', 'ss.sdf')}
    for path in inputs.values():
        path.write_text(path.name)
    manifest = tmp_path / d70.INPUT; manifest.parent.mkdir(parents=True)
    d69_receipt = ref(tmp_path / 'd69.json')
    manifest.write_text(json.dumps({'schema': d70.SCHEMA,
        'required_corners': ['tt', 'ss'], 'final_parasitics_receipt': d69_receipt,
        'librelane': {'image': 'pinned', 'pdk_root': '/pdk', 'pdk': 'gf180mcuD'}}))
    (tmp_path / 'd69.json').write_text(json.dumps({'d62_receipt': ref(tmp_path / 'd62.json')}))
    (tmp_path / 'd62.json').write_text(json.dumps({'outputs': {'filled.def': ref(inputs['filled.def'])}}))
    sta = tmp_path / 'sta'; sta.mkdir(); (sta / 'state_out.json').write_text('{}')
    state = {'sdf': {'ss': str(inputs['ss.sdf']), 'tt': str(inputs['tt.sdf'])},
             'nl': str(inputs['netlist.v']), 'sdc': str(inputs['constraint.sdc']),
             'spef': {'nom': str(inputs['nom.spef'])}}
    parasitics = {'odb': ref(inputs['filled.odb']), 'filled_def': ref(inputs['filled.def']),
        'adopted_views': {'netlist': ref(inputs['netlist.v']), 'sdc': ref(inputs['constraint.sdc'])},
        'spefs': {'nom': ref(inputs['nom.spef'])},
        'final_spefs': {'nom': ref(inputs['nom.spef'])}}
    monkeypatch.setattr(d70, 'require_launch_admission', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(d70.extract, 'validate_final_parasitics', lambda *_: parasitics)
    monkeypatch.setattr(d70.files, '_bound', lambda project, value: project / value['path'])
    monkeypatch.setattr(d70.signoff, 'run', lambda *_args, **_kwargs: {'sta': sta})
    monkeypatch.setattr(d70.signoff, 'corner_timing', lambda *_: {'tt': {}, 'ss': {}})
    monkeypatch.setattr(d70.signoff, 'judge_timing', lambda *_: {'verdict': 'PASS'})
    monkeypatch.setattr(d70.postroute, 'stapostpnr_state', lambda *_: (sta, state))
    monkeypatch.setattr(d70.postroute, 'corner_sdfs',
                        lambda *_: {'ss': inputs['ss.sdf'], 'tt': inputs['tt.sdf']})
    result = d70.execute(tmp_path, {'context_sha256': 'source-control'})
    assert result['component_status'] == 'PASS'
    assert result['required_corners'] == ['tt', 'ss']
    assert list(state['sdf']) == ['ss', 'tt']


def test_d70_validator_accepts_equal_corner_population_in_different_order(tmp_path, monkeypatch):
    receipt = _validator_fixture(tmp_path, monkeypatch)
    accepted = d70.validate_final_electrical(tmp_path, receipt)
    assert accepted['required_corners'] == ['tt', 'ss']
    assert set(accepted['sdfs']) == {'tt', 'ss'}


@pytest.mark.parametrize(('required', 'state_order', 'reason'), (
    (('tt', 'tt'), ('tt',), 'D70_REQUIRED_CORNERS_ABSENT'),
    (('tt', 'ss'), ('tt',), 'D70_FINAL_OUTPUT_BINDING_MISMATCH'),
))
def test_d70_validator_refuses_duplicate_or_missing_corner_population(
        tmp_path, monkeypatch, required, state_order, reason):
    receipt = _validator_fixture(tmp_path, monkeypatch,
                                 required=required, state_order=state_order)
    with pytest.raises(d70.AdmissionRefusal, match=reason):
        d70.validate_final_electrical(tmp_path, receipt)


def test_d70_owner_binding_keeps_dynamic_and_em_unmeasured(tmp_path, monkeypatch):
    receipt = _owner_binding_fixture(tmp_path, monkeypatch)
    result = d70.bind_power_ir_owners(tmp_path, receipt)
    assert result['binding_status'] == 'CURRENT'
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['static_power_status'] == 'MEASURED'
    assert result['static_ir_status'] == 'PASS'
    assert result['dynamic_power_status'] == 'NOT_MEASURED'
    assert result['dynamic_ir_status'] == 'NOT_MEASURED'
    assert result['signal_em_status'] == 'NOT_MEASURED'
    assert result['whole_ic_acceptance'] == 'NOT_MEASURED'


def test_d70_owner_binding_preserves_measured_static_ir_fail(tmp_path, monkeypatch):
    receipt = _owner_binding_fixture(tmp_path, monkeypatch, ir_verdict='FAIL')
    result = d70.bind_power_ir_owners(tmp_path, receipt)
    assert result['binding_status'] == 'CURRENT'
    assert result['component_status'] == 'FAIL'
    assert result['reason'] == 'D70_APPLICABLE_OWNER_MEASURED_FAIL'


def test_d70_owner_binding_refuses_missing_input(tmp_path, monkeypatch):
    component = _put_ref(tmp_path, 'component.json', {})
    monkeypatch.setattr(d70, 'validate_final_electrical', lambda *_: {})
    result = d70.bind_power_ir_owners(tmp_path, component)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['reason'] == 'D70_REQUIRED_INPUT_ABSENT'


def test_d70_record_comparison_refuses_stale_bytes(tmp_path):
    expected = _put_ref(tmp_path, 'basis/final.v', 'current')
    observed = dict(expected)
    observed['sha256'] = '0' * 64
    with pytest.raises(d70.AdmissionRefusal, match='D70_OWNER_STALE'):
        d70._same_record(tmp_path, observed, expected, 'D70_OWNER_STALE', 'netlist')


def test_d70_ir_refuses_bridge_odb_instead_of_final_odb(tmp_path, monkeypatch):
    final_odb = _put_ref(tmp_path, 'final/chip.odb', 'final odb')
    bridge_odb = _put_ref(tmp_path, 'phase3/librelane/24/bridge.odb', 'bridge odb')
    final_def = _put_ref(tmp_path, 'final/chip.def', 'final def')
    netlist = _put_ref(tmp_path, 'final/chip.v', 'module chip; endmodule')
    sdc = _put_ref(tmp_path, 'final/chip.sdc', 'create_clock')
    spef = _put_ref(tmp_path, 'final/chip.spef', '*SPEF')
    component = _put_ref(tmp_path, 'reports/flow109/components/D57.json', {
        'schema': 'vibeic/backend-result/2', 'step_id': '24', 'verdict': 'PASS'})
    _put_ref(tmp_path, 'reports/phase3/ir_drop_librelane.json', {
        'inputs': {'def': final_def, 'netlist': netlist, 'sdc': sdc, 'spef': spef},
        'native_basis': {'odb': {'path': str((tmp_path / bridge_odb['path']).resolve()),
                                 'sha256': bridge_odb['sha256']}}})
    import em_current_density_check as current_ir
    monkeypatch.setattr(current_ir, 'validate_primary_ir',
                        lambda *_: {'valid': True, 'verdict': 'PASS'})
    parasitics = {'filled_def': final_def, 'odb': final_odb,
                  'adopted_views': {'netlist': netlist, 'sdc': sdc},
                  'final_spefs': {'nom_*': spef}}
    with pytest.raises(d70.AdmissionRefusal, match='D70_D57_FINAL_ODB_NOT_CONSUMED'):
        d70._ir_binding(tmp_path, parasitics, {'d57_ir_component': component})


def test_d70_ir_accepts_only_selected_current_native_odb(tmp_path, monkeypatch):
    final_odb = _put_ref(tmp_path, 'final/chip.odb', 'final odb')
    final_def = _put_ref(tmp_path, 'final/chip.def', 'final def')
    netlist = _put_ref(tmp_path, 'final/chip.v', 'module chip; endmodule')
    sdc = _put_ref(tmp_path, 'final/chip.sdc', 'create_clock')
    spef = _put_ref(tmp_path, 'final/chip.spef', '*SPEF')
    component = _put_ref(tmp_path, 'reports/flow109/components/D57.json', {
        'schema': 'vibeic/backend-result/2', 'step_id': '24', 'verdict': 'PASS'})
    selected = {'odb': final_odb, 'def': final_def, 'netlist': netlist,
                'sdc': sdc, 'spef': spef}
    _put_ref(tmp_path, 'reports/phase3/ir_drop_librelane.json', {
        # The old issuer paths deliberately differ: current mode must use the
        # producer's selected native state, never this legacy request surface.
        'inputs': {'def': {'path': 'old.def', 'sha256': '0' * 64}},
        'record': {'input_mode': 'current_stapostpnr_odb',
                   'selected_inputs': selected}})
    import em_current_density_check as current_ir
    monkeypatch.setattr(current_ir, 'validate_primary_ir',
                        lambda *_: {'valid': True, 'verdict': 'PASS'})
    parasitics = {'filled_def': final_def, 'odb': final_odb,
                  'adopted_views': {'netlist': netlist, 'sdc': sdc},
                  'final_spefs': {'nom_*': spef}}
    result = d70._ir_binding(tmp_path, parasitics, {'d57_ir_component': component})
    assert result['verdict'] == 'PASS'
    assert result['scope'] == 'static IR only'


def test_final_filled_odb_runs_rcx_then_all_declared_stapostpnr_corners():
    control_path = Path('/tmp/vibeic-d69d70-native-control.json')
    if not control_path.is_file():
        pytest.skip('place the bounded native-control manifest in /tmp')
    control = json.loads(control_path.read_text())
    project = Path(control['project']).resolve()
    pnr = project / 'phase3/stage3/pnr'
    image = control['image']
    pdk_root = Path(control['pdk_root']).resolve()
    result = signoff.run(project, image, pdk_root, 'gf180mcuD',
        routed_def=pnr / 'filled.def', routed_odb=pnr / 'filled.odb',
        netlist=pnr / 'spm_pnr.v', sdc=pnr / 'constraint.sdc',
        extract=True, time=True, lane='flow109-d69-d70-native')
    binding = signoff.bind_rcx_spefs(result['rcx'], result['rcx'] / 'state_in.json')
    scans = {corner: scan_spef(path) for corner, path in result['spef'].items()}
    assert binding['route_sha256']['odb']
    assert all(f['has_header'] and f['has_design'] and f['d_nets'] > 0 for f in scans.values())
    corners = signoff.corner_timing(result['sta'])
    declared = json.loads(result['configs']['OpenROAD.STAPostPNR'].read_text())['STA_CORNERS']
    state = json.loads((result['sta'] / 'state_out.json').read_text())
    assert set(corners) == set(declared)
    assert set(state.get('sdf') or {}) == set(declared)
    summary = {'scope': 'developer native control, not product qualification',
               'rcx': str(result['rcx']), 'sta': str(result['sta']),
               'spef_scan': scans, 'declared_corners': declared,
               'timing_judgment': signoff.judge_timing(corners),
               'odb_sha256': binding['route_sha256']['odb']}
    (project / 'd69-d70-native-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
