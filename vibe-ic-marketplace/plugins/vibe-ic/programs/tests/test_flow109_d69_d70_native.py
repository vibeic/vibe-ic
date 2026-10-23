"""Opt-in native Default control. Inputs are copied real SPM/GF180 artefacts."""
from __future__ import annotations

import json
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
    parasitics = {'odb': ref(inputs['filled.odb']),
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
