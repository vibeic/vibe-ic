from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_native_physical as physical


def _case(power_min=1.19, ground_max=0.005, status='PASS'):
    return {'status': status, 'name': 'native-static', 'receipt': 'accepted-op.json',
            'rail_roles': {'vdd': 'supply', 'vss': 'return'},
            'feed_voltages': {'supply': 1.2, 'return': 0},
            'pg_voltage_ranges': {
                'supply': {'min_v': power_min, 'max_v': 1.2, 'sampled_endpoints': 40},
                'return': {'min_v': 0, 'max_v': ground_max, 'sampled_endpoints': 30}}}


@pytest.mark.parametrize('power,ground,expected,millivolts', [
    (1.19, 0.005, 'PASS', 15), (1.08, 0, 'FAIL', 120),
    (1.14, 0.07, 'FAIL', 130)])
def test_native_ir_sums_independent_rail_extrema_under_existing_strict_budget(
        tmp_path, power, ground, expected, millivolts):
    result = physical._ir_from_native_interconnect({'cases': [_case(power, ground)]}, {}, tmp_path)
    assert result['status'] == expected
    measurement = result['cases'][0]['measurement']
    assert measurement['max_drop_mv'] == millivolts
    assert 'existing ir_drop_budget_check default' in measurement['budget_source']
    assert result['cases'][0]['gate']['budget_pct'] == 10


@pytest.mark.parametrize('fault', ['missing_feed', 'missing_ground', 'nonfinite', 'empty_endpoints'])
def test_missing_native_rail_evidence_cannot_create_an_ir_pass(tmp_path, fault):
    case = _case()
    if fault == 'missing_feed':
        case['feed_voltages'].pop('supply')
    elif fault == 'missing_ground':
        case['rail_roles'].pop('vss')
    elif fault == 'nonfinite':
        case['pg_voltage_ranges']['supply']['min_v'] = float('nan')
    else:
        case['pg_voltage_ranges']['supply']['sampled_endpoints'] = 0
    assert physical._ir_from_native_interconnect({'cases': [case]}, {}, tmp_path)['status'] == 'NOT_MEASURED'


def test_real_ir_violation_remains_failure_when_another_case_is_unmeasured(tmp_path):
    result = physical._ir_from_native_interconnect({'cases': [_case(1.0), {}]}, {}, tmp_path)
    assert result['status'] == 'FAIL'


def test_ir_is_independent_of_current_density_verdict_and_honors_explicit_budget(tmp_path):
    measured = {'status': 'FAIL', 'cases': [_case(status='FAIL')]}
    assert physical._ir_from_native_interconnect(measured, {}, tmp_path)['status'] == 'PASS'
    assert physical._ir_from_native_interconnect(measured, {'arguments': {'budget_pct': 1}}, tmp_path)['status'] == 'FAIL'
    assert physical._ir_from_native_interconnect(measured, {'arguments': {'vdd': 2}}, tmp_path)['status'] == 'NOT_MEASURED'


def test_a16_reuses_one_native_current_read_for_em_and_ir(tmp_path, monkeypatch):
    import analog_native_em as em
    calls = []
    def measured(*args, **kwargs):
        calls.append(args)
        return {'status': 'FAIL', 'cases': [_case(status='FAIL')], 'outputs': [], 'native_inputs': {}}
    monkeypatch.setattr(em, 'run', measured)
    result = physical._reliability(tmp_path, 'unit', '', '', '', {
        'em': {'cases': [{'receipt': 'actual-native-op'}]}, 'ir': {'from_em': True},
        '_features': {'requires_thermal': False, 'requires_aging': False}})
    assert len(calls) == 1
    assert result['metrics']['em']['status'] == 'FAIL'
    assert result['metrics']['ir']['status'] == 'PASS'
    assert result['status'] == 'FAIL'


def test_plain_and_lossless_gzip_native_voltages_preserve_17p45_percent_ir_failure(tmp_path):
    import gzip
    import hashlib
    import numpy as np
    from analog_native_waveform import NativeRaw
    plain=tmp_path/'op.raw'
    original=(b'Title: native IR capture\nPlotname: Operating Point\nFlags: real\nNo. Variables: 3\n'
              b'No. Points: 1\nVariables:\n0 v(feed) voltage\n1 v(far) voltage\n2 v(return) voltage\nBinary:\n'
              +np.array([1.2,.9906,0],dtype='<f8').tobytes())
    plain.write_bytes(original);stored=tmp_path/'op.raw.gz';stored.write_bytes(gzip.compress(original))
    readers=[NativeRaw(plain),NativeRaw(stored,expected_raw_sha256=hashlib.sha256(original).hexdigest(),
                                      expected_raw_bytes=len(original))]
    results=[]
    for raw in readers:
        volts=raw.row();case=_case(volts['far'],volts['return'])
        case['feed_voltages']['supply']=volts['feed']
        results.append(physical._ir_from_native_interconnect({'cases':[case]}, {}, tmp_path))
    assert results[0]['status']==results[1]['status']=='FAIL'
    assert results[0]['cases'][0]['measurement']==results[1]['cases'][0]['measurement']
    assert results[0]['cases'][0]['status']==results[1]['cases'][0]['status']=='FAIL'
    assert results[1]['cases'][0]['measurement']['max_drop_mv']==pytest.approx(209.4)
    assert results[1]['cases'][0]['gate']['budget_pct']==10
