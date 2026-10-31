"""SOURCE_ONLY finishing metric/parser controls, never native geometry acceptance."""
import shutil
from pathlib import Path

import pytest
import flow109
import flow109_final_geometry as owner
from _hostpaths import require_repo


@pytest.mark.parametrize('kind,count', [('clean', 0), ('violation', 1)])
def test_native_report_parser_counts_actual_checked_in_RDB_items(tmp_path, kind, count):
    """Antenna calibration RDBs exercise only generic RDB item parsing, not XOR semantics."""
    if not hasattr(owner, '_d64_metric_counts'):
        pytest.skip('reader absent on exact main')
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'calibration',
                          'native_antenna_' + kind + '.lyrdb')
    report = tmp_path / 'source_only_format.lyrdb';shutil.copyfile(source, report)
    ref = owner.stream._record(tmp_path, report)
    result = owner._d64_metric_counts(tmp_path, {'report': ref, 'design_pair_count': 1})
    assert result['unexplained_stream_xor'] == count and result['design_pair_count'] == 1
    assert not (tmp_path / 'qualifications.json').exists()


@pytest.mark.parametrize('pairs', [0, -1, True, None])
def test_empty_or_untyped_design_pair_population_cannot_self_approve(tmp_path, pairs):
    if not hasattr(owner, '_d64_metric_counts'):
        pytest.skip('reader absent on exact main')
    with pytest.raises(owner.AdmissionRefusal, match='D64_METRIC_PAIR_POPULATION_UNMEASURED'):
        owner._d64_metric_counts(tmp_path, {'design_pair_count': pairs})


def context():
    for ref in flow109.load_registry()['reference_profiles']:
        plan = flow109.resolve_plan(ref['features'])
        row = next((r for r in plan['rows'] if r['id'] == 'D64'), None)
        if row and row['profile']['id'] == 'digital_odb':
            return flow109.execution_context(plan, 'D64', 'D64')
    raise AssertionError('registered digital D64 profile absent')


def consume(tmp_path, monkeypatch, count, *, component_status='PASS', unavailable=False, prior_metric_fail=False):
    current = context()
    if hasattr(owner, '_d64_metric_observation'):
        def reader(*args):
            if unavailable:raise owner.AdmissionRefusal('SOURCE_ONLY_NATIVE_BASIS_ABSENT', 'control')
            return {'unexplained_stream_xor': count, 'design_pair_count': 1,
                    'scope': 'SOURCE_ONLY_FUNCTION_EDGE_CONTROL'}
        monkeypatch.setattr(owner, '_d64_metric_observation', reader)
    component = {'step_id': 'D64', 'context_sha256': current['context_sha256'],
        'component_status': component_status, 'default_row_status': 'NOT_MEASURED', 'completed': False,
        'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
    if prior_metric_fail:
        component.update(metric_acceptance_status='FAIL', default_row_status='FAIL',
            metric_acceptance={'status': 'FAIL', 'reason': 'SOURCE_ONLY_PRIOR_MEASURED_FAILURE',
                'obligations': [{'id': current['resolved_row']['obligations'][0]['id'], 'status': 'FAIL'}]})
    return flow109._selected_step_result(tmp_path, current, component, adapter=owner)


@pytest.mark.parametrize('count', [1, 2, 5])
def test_actual_consumer_blocks_nonzero_native_XOR_without_component_FAIL(tmp_path, monkeypatch, count):
    result = consume(tmp_path, monkeypatch, count)
    assert result['default_row_status'] == 'FAIL', result
    assert result['completed'] is False and result['delivery_accepted'] is False


def test_zero_XOR_count_cannot_supply_allowed_change_reference(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, 0)
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    if hasattr(owner, 'accept_d64'):
        assert result['metric_acceptance']['obligations'][0]['observed_value'] == 0
        assert result['metric_acceptance']['obligations'][1]['status'] == 'NOT_MEASURED'


def test_existing_component_FAIL_survives_later_missing_geometry(tmp_path, monkeypatch):
    assert consume(tmp_path, monkeypatch, 0, component_status='FAIL', unavailable=True)['default_row_status'] == 'FAIL'


def test_prior_metric_FAIL_survives_later_unmeasured_reader(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, 0, unavailable=True, prior_metric_fail=True)
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False
    if hasattr(owner, 'accept_d64'):
        assert result['metric_acceptance']['metric_status'] == 'FAIL'
        assert result['metric_acceptance']['obligations'][0]['status'] == 'FAIL'
        assert result['metric_acceptance']['prior_failed_obligation_ids']
