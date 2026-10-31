"""SOURCE_ONLY D60 reader controls; no stream/qualification receipt fabricated."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import flow109
import analog_hardmacro_gds_emit as owner


@pytest.mark.parametrize('extra_cell', [False, True])
def test_existing_native_hierarchy_reader_uses_independent_source_population(tmp_path, extra_cell):
    if not hasattr(owner, '_d60_metric_readback'):
        pytest.skip('reader absent on exact main')
    tool = shutil.which('klayout');assert tool, 'official EDA image required'
    master, gds, script = tmp_path / 'master.gds', tmp_path / 'stream.gds', tmp_path / 'source_only.py'
    script.write_text('import pya\nl=pya.Layout();l.dbu=0.001\n'
        'm=l.create_cell("neutral_master");m.shapes(l.layer(1,0)).insert(pya.Box(0,0,1000,1000))\n'
        f'l.write({str(master)!r})\nt=l.create_cell("neutral_top");t.insert(pya.CellInstArray(m.cell_index(),pya.Trans()))\n'+
        ('l.create_cell("extra_cell")\n' if extra_cell else '') + f'l.write({str(gds)!r})\n')
    proc = subprocess.run([tool, '-b', '-r', str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = {'top': 'neutral_top', 'cells': {'neutral_top': 'source_top.mag', 'neutral_master': 'source_master.mag'},
            'hierarchy': {'neutral_top': {'neutral_master': 1}, 'neutral_master': {}},
            'instances': {'source_instance': 'neutral_master'}, 'views': {'neutral_master': str(master)}}
    observed = owner._d60_metric_readback(tmp_path, data, gds, {'path': tool})['measurement']
    assert observed['status'] == ('FAIL' if extra_cell else 'PASS'), observed
    if not extra_cell:
        assert observed['cells'] == ['neutral_master', 'neutral_top']
        assert observed['instances'] == {'neutral_master': 1}
    assert not (tmp_path / 'qualifications.json').exists()


def context():
    for ref in flow109.load_registry()['reference_profiles']:
        plan = flow109.resolve_plan(ref['features'])
        row = next((r for r in plan['rows'] if r['id'] == 'D60'), None)
        if row and row['profile']['id'] == 'analog_die':
            return flow109.execution_context(plan, 'D60', 'D60')
    raise AssertionError('registered analog D60 profile absent')


def consume(tmp_path, monkeypatch, measured, *, component_status='PASS', unavailable=False, prior_metric_fail=False):
    current = context()
    if hasattr(owner, '_d60_metric_observation'):
        def reader(*args):
            if unavailable:raise ValueError('SOURCE_ONLY_MISSING_NATIVE_BASIS')
            return {'measurement': measured, 'scope': 'SOURCE_ONLY_FUNCTION_EDGE_CONTROL'}
        monkeypatch.setattr(owner, '_d60_metric_observation', reader)
    component = {'step_id': 'D60', 'context_sha256': current['context_sha256'],
        'component_status': component_status, 'default_row_status': 'NOT_MEASURED', 'completed': False,
        'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
    if prior_metric_fail:
        component.update(metric_acceptance_status='FAIL', default_row_status='FAIL',
            metric_acceptance={'status': 'FAIL', 'reason': 'SOURCE_ONLY_PRIOR_MEASURED_FAILURE',
                'obligations': [{'id': current['resolved_row']['obligations'][0]['id'], 'status': 'FAIL'}]})
    return flow109._selected_step_result(tmp_path, current, component, adapter=owner)


@pytest.mark.parametrize('reason', ['D60_STREAM_TOP_MISMATCH', 'D60_STREAM_HIERARCHY_MISMATCH',
                                  'D60_ADOPTED_VIEW_GEOMETRY_MISMATCH'])
def test_actual_consumer_blocks_failed_native_hierarchy_despite_component_PASS(tmp_path, monkeypatch, reason):
    result = consume(tmp_path, monkeypatch, {'status': 'FAIL', 'reason': reason})
    assert result['default_row_status'] == 'FAIL', result
    assert result['completed'] is False


def test_complete_native_hierarchy_census_does_not_supply_adopted_mapping(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, {'status': 'PASS'})
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    if hasattr(owner, 'accept_d60'):
        assert result['metric_acceptance']['obligations'][1]['observed_value'] == 0
        assert result['metric_acceptance']['obligations'][0]['status'] == 'NOT_MEASURED'


def test_existing_component_FAIL_is_not_erased_by_unavailable_readback(tmp_path, monkeypatch):
    assert consume(tmp_path, monkeypatch, {}, component_status='FAIL', unavailable=True)['default_row_status'] == 'FAIL'


def test_prior_metric_FAIL_survives_later_unmeasured_reader(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, {}, unavailable=True, prior_metric_fail=True)
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False
    if hasattr(owner, 'accept_d60'):
        assert result['metric_acceptance']['metric_status'] == 'FAIL'
        assert result['metric_acceptance']['obligations'][0]['status'] == 'FAIL'
        assert result['metric_acceptance']['prior_failed_obligation_ids']
