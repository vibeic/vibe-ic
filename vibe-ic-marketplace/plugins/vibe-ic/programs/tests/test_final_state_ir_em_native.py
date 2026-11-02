"""#62b: neutral native transport controls, not a native signoff claim."""
import hashlib
import json
from pathlib import Path

import pytest

import em_current_density_check as density
import em_peak_current_authority_check as authority
import ir_drop_report_check as ir_gate
import librelane_ir_antenna as ir
import phase3_one_shot_runner as runner
from test_default_step25_em_owner import _current_ir
from test_default_power_density import build


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _final(project, odb, final_def):
    import _prestream_native as native
    (project / 'state_out.json').write_text(json.dumps({
        'odb': str(odb), 'def': str(final_def), 'metrics': {'route__drc_errors_final': 0}}))
    assert native.final_state(project) is not None


def _ir_project(tmp_path, monkeypatch, drop=0.01736, supply=5.0):
    project, pdk, _, assets, instrument = _current_ir(tmp_path, monkeypatch)

    def transport(*args, **kwargs):
        record = instrument(*args, **kwargs)
        state = assets['state']
        state.write_text(json.dumps({'metrics': {
            'design_powergrid__drop__worst__net:PWR': drop}}))
        record['tool_state_sha256'] = _sha(state)
        record['lib_voltage_v'] = supply
        record['cross_check']['per_net_worst_drop_v'] = {'PWR': drop}
        return record

    monkeypatch.setattr(ir, 'run_ir', transport)
    runner._librelane_step24_record(project, 'unit', pdk, 'librelane',
        runner._pl.extracted_dir(project) / 'unit.spef', [])
    runner._step24_adopt_primary(project, None, [])
    report = project / 'reports/phase3/ir_drop_librelane.json'
    doc = json.loads(report.read_text())
    assert doc['adopted'], doc
    doc['source_identity'] = {'historical_source': 'old'}
    report.write_text(json.dumps(doc))
    _final(project, assets['odb'], runner._pl.pnr_dir(project) / 'routed.def')
    return project


@pytest.mark.parametrize('drop,expected', [(0.01736, 'PASS'), (0.25, 'PASS'),
                                         (0.3, 'FAIL'), (0.6, 'FAIL')])
def test_final_ir_uses_original_five_percent_not_writer_ten(tmp_path, monkeypatch, drop, expected):
    project = _ir_project(tmp_path, monkeypatch, drop)
    reports = project / 'reports/phase3'
    producer = json.loads((reports / 'ir_drop.json').read_text())
    assert producer['budget_uv'] == 500000.0
    if drop == 0.3:
        assert producer['verdict'] == 'PASS'  # writer's 10% is not the checker limit
    result = density.validate_primary_ir(project)
    assert result['valid'] is True, result
    assert result['verdict'] == expected, result
    output = reports / 'ir_drop_signoff.json'
    rc = ir_gate._run_and_emit([str(project), '--json', str(output)])
    assert rc == (0 if expected == 'PASS' else 1)
    assert json.loads(output.read_text())['verdict'] == expected


@pytest.mark.parametrize('damage', ['missing', 'unparsable', 'nonzero_rc', 'missing_vdd'])
def test_final_ir_missing_or_failed_native_is_not_measured(tmp_path, monkeypatch, damage):
    project = _ir_project(tmp_path, monkeypatch)
    reports = project / 'reports/phase3'
    path = reports / 'ir_drop.json'
    primary = reports / 'ir_drop_librelane.json'
    doc = json.loads(primary.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'unparsable':
        path.write_text('{')
    elif damage == 'nonzero_rc':
        value = json.loads(path.read_text())
        value['native_rc'] = 1
        path.write_text(json.dumps(value))
        doc['published']['reports/phase3/ir_drop.json'] = _sha(path)
    else:
        doc['record']['lib_voltage_v'] = None
    primary.write_text(json.dumps(doc))
    result = density.validate_primary_ir(project)
    assert result['verdict'] == 'NOT_MEASURED', result
    output = reports / 'ir_drop_signoff.json'
    assert ir_gate._run_and_emit([str(project), '--json', str(output)]) == 2
    assert json.loads(output.read_text())['verdict'] == 'NOT_MEASURED'


def test_nonfinal_ir_retains_source_refusal(tmp_path, monkeypatch):
    project = _ir_project(tmp_path, monkeypatch)
    (project / 'state_out.json').unlink()
    result = density.validate_primary_ir(project)
    assert result['valid'] is False
    assert result['reason'] == 'LibreLane IR primary was not adopted by current source'


@pytest.mark.parametrize('stress,expected', [(False, 'PASS'), (True, 'FAIL')])
@pytest.mark.parametrize('identity', ['stale', 'absent'])
def test_final_em_native_currents_use_pdk_limits(tmp_path, monkeypatch, stress, expected, identity):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True, stress=stress)
    report = project / 'reports/phase3/em_openroad_density.json'
    doc = json.loads(report.read_text())
    assert doc['execution']['native_rc'] == 0
    if identity == 'stale':
        doc['source_identity'] = {'historical_source': 'old'}
    else:
        doc.pop('source_identity')
    report.write_text(json.dumps(doc))
    _final(project, project / 'final.odb', runner._pl.pnr_dir(project) / 'routed.def')
    result = density.validate_native_density(project)
    assert result['valid'] is True, result
    assert result['verdict'] == expected, result
    verdict, result = authority.evaluate(project, None, Path(pdk.tech_lef), 0.1)
    assert verdict == expected, result


@pytest.mark.parametrize('damage', ['missing', 'unparsable', 'nonzero_rc'])
def test_final_em_missing_or_failed_native_is_not_measured(tmp_path, monkeypatch, damage):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True)
    _final(project, project / 'final.odb', runner._pl.pnr_dir(project) / 'routed.def')
    report = project / 'reports/phase3/em_openroad_density.json'
    if damage == 'missing':
        report.unlink()
    elif damage == 'unparsable':
        report.write_text('{')
    else:
        doc = json.loads(report.read_text())
        doc['execution']['native_rc'] = 1
        report.write_text(json.dumps(doc))
    assert density.validate_native_density(project)['verdict'] == 'NOT_MEASURED'
    verdict, result = authority.evaluate(project, None, Path(pdk.tech_lef), 0.1)
    assert verdict == 'NOT_MEASURED', result


def test_nonfinal_em_retains_source_refusal(tmp_path, monkeypatch):
    project, _, _ = build(tmp_path, monkeypatch, direct=True)
    report = project / 'reports/phase3/em_openroad_density.json'
    doc = json.loads(report.read_text())
    doc['source_identity'] = {}
    report.write_text(json.dumps(doc))
    result = density.validate_native_density(project)
    assert result['valid'] is False
    assert result['reason'] == 'native producer/consumer source changed'
