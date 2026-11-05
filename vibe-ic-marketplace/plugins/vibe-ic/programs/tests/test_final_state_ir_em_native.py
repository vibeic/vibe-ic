"""#62b: neutral native transport controls, not a native signoff claim."""
import json
from pathlib import Path

import pytest

import em_current_density_check as density
import em_peak_current_authority_check as authority
import phase3_one_shot_runner as runner
from test_default_power_density import build




def _final(project, odb, final_def):
    import _prestream_native as native
    (project / 'state_out.json').write_text(json.dumps({
        'odb': str(odb), 'def': str(final_def), 'metrics': {'route__drc_errors_final': 0}}))
    assert native.final_state(project) is not None












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
