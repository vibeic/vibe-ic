"""A reader consumes retained E native reset controls; no simulator is launched."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
import _l10_execution as cases
import arith_oracle_tb_gen as arithmetic
import flow109_metric_acceptance as metrics


CASES = [
    ('test_reset_required_values_act0/good', 'PASS'),
    ('test_reset_wrong_value_actual_0/wrong', 'FAIL'),
    ('test_reset_omitted_required_mo0/good', 'NOT_MEASURED'),
]
pytestmark = pytest.mark.skipif(
    not Path('/evidence/native-temp').is_dir() or not Path('/e-producer/arith_oracle_tb_gen.py').is_file(),
    reason='NOT_MEASURED: retained native reset packet/dependency unavailable; SKIP is not qualification')


def native_case(relative):
    expected = Path('/e-producer/arith_oracle_tb_gen.py')
    assert Path(arithmetic.__file__).read_bytes() == expected.read_bytes(), 'exact reviewed E dependency must be consumed'
    project = Path('/evidence/native-temp') / relative
    assert project.is_dir(), 'retained native packet is required; absence is not a passing control'
    record = cases.load_record(project, project / 'phase1/generated_docs/L10_TEST_CASES.json')
    assert record['available'] and not record['malformed']
    row = record['rows']['reset']
    plan = row['arithmetic_scenario']['plan']
    declared = {'top': plan['spec']['top'], 'width': plan['spec']['width'],
        'operator': plan['spec']['operator'],
        'integer_encoding': 'signed_2c' if plan['spec'].get('signed') else 'unsigned',
        **{k: plan['framing'][k] for k in ('bit_order', 'latency', 'latency_origin',
            'transaction_rearm', 'rearm_reset_cycles', 'parallel_hold')}}
    required = {'scenario': 'reset_situations', 'minimum_transactions': 1,
        'reset_observation': plan['reset_observation']}
    execution = {'artifacts': [{'path': str(p.relative_to(project)),
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(project.rglob('*')) if p.is_file()]}
    return project, record, required, execution, declared


@pytest.mark.parametrize('relative,expected', CASES)
def test_d13_retained_native_reset_result(relative, expected):
    project, record, required, execution, declared = native_case(relative)
    result = metrics._d13_scenario(project, 'reset', required, record, execution, declared)
    assert result['status'] == expected, result
    if expected == 'PASS':
        observed = result['measured']['reset_observations']
        assert all(r['samples'] == result['measured']['held_edges'] > 0 for r in observed)
        assert sum(r['mismatches'] for r in observed) == 0
    elif expected == 'FAIL':
        assert result['errors'] > 0
        assert result['measured']['complete'] is True


@pytest.mark.parametrize('relative,expected', CASES)
def test_d13_explicit_case_record_reuses_retained_outcome(tmp_path, relative, expected):
    project, record, required, execution, declared = native_case(relative)
    # Copy only the immutable record bytes for the added explicit-path reader.
    # TB/plan/transcript/source remain the exact readonly native packet.
    explicit = tmp_path / 'separate-l10.json'
    explicit.write_bytes(Path(record['path']).read_bytes())
    current = cases.load_record(project, project/'phase1/generated_docs/L10_TEST_CASES.json', path=explicit)
    assert current['path'] == str(explicit)
    assert current['rows'] == record['rows']
    result = metrics._d13_scenario(project, 'reset', required, current, execution, declared)
    assert result['status'] == expected, result


@pytest.mark.parametrize('change', ['order', 'one_point', 'omit', 'zero', 'stale_input'])
def test_d13_reset_reader_refuses_partial_or_changed_population(change):
    project, record, required, execution, declared = native_case(CASES[0][0])
    record = copy.deepcopy(record)
    observations = record['rows']['reset']['arithmetic_scenario']['reset_observations']
    if change == 'order':
        required['reset_observation'] = copy.deepcopy(required['reset_observation'])
        required['reset_observation']['required_observations'].reverse()
    elif change == 'one_point':observations[0]['samples'] = 1
    elif change == 'omit':observations.pop()
    elif change == 'zero':observations[0]['samples'] = 0
    else:
        tb = Path(record['rows']['reset']['tb_file']).relative_to(project).as_posix()
        next(r for r in execution['artifacts'] if r['path'] == tb)['sha256'] = '0' * 64
        with pytest.raises(metrics.MetricRefusal, match='D13_INPUT_STALE'):
            metrics._d13_scenario(project, 'reset', required, record, execution, declared)
        return
    result = metrics._d13_scenario(project, 'reset', required, record, execution, declared)
    assert result['status'] == 'NOT_MEASURED', result
