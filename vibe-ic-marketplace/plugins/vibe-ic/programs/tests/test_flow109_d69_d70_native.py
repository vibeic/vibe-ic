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


def _d70_producer_case(tmp_path, monkeypatch, spef_keys, expected, requires_scan, functional):
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
             'spef': {key: str(inputs['nom.spef']) for key in spef_keys}}
    parasitics = {'odb': ref(inputs['filled.odb']), 'filled_def': ref(inputs['filled.def']),
        'adopted_views': {'netlist': ref(inputs['netlist.v']), 'sdc': ref(inputs['constraint.sdc'])},
        'spefs': {'nom': ref(inputs['nom.spef'])},
        'final_spefs': {'nom': ref(inputs['nom.spef'])}}
    monkeypatch.setattr(d70, 'require_launch_admission', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(d70.extract, 'validate_final_parasitics', lambda *_: parasitics)
    monkeypatch.setattr(d70.files, '_bound', lambda project, value: project / value['path'])
    monkeypatch.setattr(d70.signoff, 'run', lambda *_args, **_kwargs: {'sta': sta})
    monkeypatch.setattr(d70.signoff, 'corner_timing', lambda *_: {'tt': {}, 'ss': {}})
    monkeypatch.setattr(d70, '_native_ir_em', lambda *_: {'ir_status': 'PASS', 'em_status': 'PASS'})
    monkeypatch.setattr(d70.signoff, 'judge_timing', lambda *_: {'verdict': functional})
    monkeypatch.setattr(d70.postroute, 'stapostpnr_state', lambda *_: (sta, state))
    monkeypatch.setattr(d70.postroute, 'corner_sdfs',
                        lambda *_: {'ss': inputs['ss.sdf'], 'tt': inputs['tt.sdf']})
    result = d70.execute(tmp_path, {'context_sha256': 'source-control',
                                    'features': {'requires_scan': requires_scan}})
    actual = expected if expected != 'PASS' else (
        'FAIL' if functional == 'FAIL' else 'NOT_MEASURED' if requires_scan else 'PASS')
    assert result['component_status'] == actual
    if expected == 'PASS':
        assert result['required_corners'] == ['tt', 'ss']
        assert list(state['sdf']) == ['ss', 'tt']
        assert result['timing_judgment']['verdict'] == functional
        if requires_scan:
            assert result['scan_timing_coverage']['status'] == 'NOT_MEASURED'
            assert result['scan_timing_coverage']['required_modes'] == ['shift', 'capture']
    else:
        assert result['reason'] == 'D70_FINAL_SPEF_STATE_MISMATCH'


@pytest.mark.parametrize('spef_keys,expected', [
    (('nom',), 'PASS'), (('nom_*',), 'PASS'),
    (('nom', 'nom_*'), 'NOT_MEASURED'), (('max_*',), 'NOT_MEASURED'),
])
def test_d70_producer_accepts_equal_corner_population_in_different_order(
        tmp_path, monkeypatch, spef_keys, expected):
    _d70_producer_case(tmp_path, monkeypatch, spef_keys, expected, False, 'PASS')


@pytest.mark.parametrize('functional,expected', [('PASS', 'NOT_MEASURED'), ('FAIL', 'FAIL')])
def test_d70_scan_modes_missing_cannot_override_functional_timing(tmp_path, monkeypatch, functional, expected):
    _d70_producer_case(tmp_path, monkeypatch, ('nom',), 'PASS', True, functional)


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








def test_d70_record_comparison_refuses_stale_bytes(tmp_path):
    expected = _put_ref(tmp_path, 'basis/final.v', 'current')
    observed = dict(expected)
    observed['sha256'] = '0' * 64
    with pytest.raises(d70.AdmissionRefusal, match='D70_OWNER_STALE'):
        d70._same_record(tmp_path, observed, expected, 'D70_OWNER_STALE', 'netlist')






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


def test_d70_rejects_historical_functional_only_pass_for_scan(tmp_path, monkeypatch):
    ref = _validator_fixture(tmp_path, monkeypatch)
    record = d70._read(None)
    record['execution_context'] = {'features': {'requires_scan': True}}
    with pytest.raises(d70.AdmissionRefusal, match='D70_SCAN_MODES_NOT_ACQUIRED'):
        d70.validate_final_electrical(tmp_path, ref)


_IR_EM = """=== PSM_NET VDD ===
Worstcase IR drop: 2.00e-02 V
Percentage drop  : {pct} %
No J-limit (skipped): {skipped}
Worst utilization  : 93.33 %
Violations         : {violations}
Verdict            : {verdict}
"""


@pytest.mark.parametrize('pct, violations, skipped, verdict, ir, em', [
    ('0.36', 0, 0, 'PASS', 'PASS', 'PASS'),
    ('5.01', 0, 0, 'PASS', 'FAIL', 'PASS'),
    ('0.36', 1, 0, 'FAIL', 'PASS', 'FAIL'),
    ('0.36', 0, 2, 'PASS', 'PASS', 'NOT_MEASURED')])
def test_native_report_decides_ir_and_em(pct, violations, skipped, verdict, ir, em):
    row = d70.judge_ir_em(_IR_EM.format(pct=pct, violations=violations, skipped=skipped, verdict=verdict),
                          ['VDD'])['VDD']
    assert (row['ir_status'], row['em_status']) == (ir, em)


def test_a_net_the_tool_did_not_report_is_not_measured():
    row = d70.judge_ir_em('', ['VSS'])['VSS']
    assert (row['ir_status'], row['em_status']) == ('NOT_MEASURED', 'NOT_MEASURED')


@pytest.mark.parametrize('statuses, verdict', [
    (('PASS', 'PASS', 'PASS'), 'PASS'), (('PASS', 'NOT_MEASURED', 'PASS'), 'NOT_MEASURED'),
    (('PASS', 'FAIL', 'NOT_MEASURED'), 'FAIL')])
def test_step_95_needs_sta_ir_and_em_all_pass(statuses, verdict):
    assert d70._roll_up(statuses) == verdict


@pytest.mark.parametrize('component, valid, row', [
    ('NOT_MEASURED', True, 'NOT_MEASURED'), ('PASS', True, 'PASS'), ('FAIL', True, 'FAIL'), ('PASS', False, 'NOT_MEASURED')])
def test_digital_row_is_the_tools_result_on_current_inputs(tmp_path, monkeypatch, component, valid, row):
    def reopen(*_):
        if not valid:
            raise d70.AdmissionRefusal('D70_FINAL_INPUT_CHANGED', 'changed')
    monkeypatch.setattr(d70, 'accept_metric_obligations', lambda *_: {'status': 'NOT_MEASURED', 'metric_status': 'NOT_MEASURED'})
    monkeypatch.setattr(d70, 'validate_final_electrical', reopen)
    answer = d70.consume_default_row_completion(tmp_path, {'context_sha256': 'x'},
        {'component_status': component, 'receipt': {'path': 'c', 'sha256': 'd'}})
    assert answer['default_row_status'] == row
    assert answer['completed'] is (row == 'PASS')


def test_analog_profile_keeps_its_metric_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(d70, 'accept_metric_obligations', lambda *_: {'status': 'NOT_MEASURED', 'metric_status': 'NOT_MEASURED'})
    answer = d70.consume_default_row_completion(tmp_path, {'context_sha256': 'x'},
        {'component_status': 'PASS', 'profile': 'analog_die', 'receipt': {'path': 'c', 'sha256': 'd'}})
    assert answer['default_row_status'] == 'NOT_MEASURED'
