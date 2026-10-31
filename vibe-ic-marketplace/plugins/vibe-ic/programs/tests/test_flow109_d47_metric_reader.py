"""SOURCE_ONLY D47 native-output audit and actual completion-seam controls.

No native extraction, approved reference, qualified corner mapping or canonical
receipt is manufactured. The existing source audit parses neutral SPICE, and
the completion controls inject those observations at the reader seam.
"""
import json
from pathlib import Path

import pytest
import flow109
import magic_extract_spice_emit as owner
from _hostpaths import require_repo


@pytest.fixture
def extraction(tmp_path):
    logical = tmp_path / 'logical.spice'
    source = '.subckt neutral_top a z\nXone a z neutral_device\n.ends neutral_top\n'
    logical.write_text(source)
    spice = tmp_path / 'candidate.spice'
    spice.write_text(source.replace('.ends', 'C1 a z 1f\n.ends'))
    data = {'top': 'neutral_top', 'ports': ['a', 'z'], 'logical': str(logical),
            'summed_models': [], 'require_resistance': False, 'options': {'extresist': False}}
    return data, spice, tmp_path / 'neutral_top.res.ext'


def values(extraction):
    if not hasattr(owner, '_d47_metric_values'):
        pytest.skip('D47 metric reader absent on exact main; canonical controls still execute')
    return owner._d47_metric_values(*extraction)


def test_existing_audit_discloses_C_ONLY_without_corner_or_complete_net_credit(extraction):
    observed = values(extraction)
    assert observed['status'] == 'PASS', observed
    assert observed['extraction_depth'] == 'C_ONLY'
    assert observed['audit']['summary']['capacitors'] == 1
    assert observed['required_logical_ports'] == ['a', 'z']
    assert observed['required_nets_and_corners'] is None
    assert observed['si_applicability'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['no_parasitics', 'wrong_ports', 'wrong_device', 'required_R_absent', 'missing_spice'])
def test_real_native_output_audit_rejects_substantive_bad_values(extraction, damage):
    data, spice, _ = extraction
    if damage == 'no_parasitics':
        spice.write_text(spice.read_text().replace('C1 a z 1f\n', ''))
    elif damage == 'wrong_ports':
        spice.write_text(spice.read_text().replace('.subckt neutral_top a z', '.subckt neutral_top a other'))
    elif damage == 'wrong_device':
        spice.write_text(spice.read_text().replace('neutral_device', 'foreign_device'))
    elif damage == 'required_R_absent':
        data['require_resistance'] = True
    else:
        spice.unlink()
    observed = values(extraction)
    assert observed['status'] == 'FAIL', observed


def context():
    registry = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'flow109.json')
    for ref in json.loads(registry.read_text())['reference_profiles']:
        plan = flow109.resolve_plan(ref['features'])
        row = next((r for r in plan['rows'] if r['id'] == 'D47'), None)
        if row and row['profile']['id'] == 'analog_die':
            return flow109.execution_context(plan, 'D47', 'D47')
    raise AssertionError('registered analog D47 profile absent')


def consume(tmp_path, monkeypatch, observed, *, component_status='PASS', unavailable=False, prior_metric_fail=False):
    current = context()
    if hasattr(owner, '_d47_metric_observation'):
        def reader(*args):
            if unavailable:
                raise ValueError('SOURCE_ONLY_MISSING_NATIVE_BASIS')
            return observed
        monkeypatch.setattr(owner, '_d47_metric_observation', reader)
    component = {'step_id': 'D47', 'context_sha256': current['context_sha256'],
        'component_status': component_status, 'default_row_status': 'NOT_MEASURED', 'completed': False,
        'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
    if prior_metric_fail:
        component.update(metric_acceptance_status='FAIL', default_row_status='FAIL',
            metric_acceptance={'status': 'FAIL', 'reason': 'SOURCE_ONLY_PRIOR_MEASURED_FAILURE',
                'obligations': [{'id': current['resolved_row']['obligations'][0]['id'], 'status': 'FAIL'}]})
    return flow109._selected_step_result(tmp_path, current, component, adapter=owner)


@pytest.mark.parametrize('reason', ['NO_PARASITICS', 'RESISTANCE_REQUIRED_BUT_ABSENT',
                                  'D47_SOURCE_DEVICE_INVENTORY_MISMATCH'])
def test_actual_consumer_blocks_failed_audit_even_with_component_PASS(tmp_path, monkeypatch, reason):
    result = consume(tmp_path, monkeypatch,
        {'status': 'FAIL', 'reason': reason, 'extraction_depth': 'C_ONLY'})
    assert result['default_row_status'] == 'FAIL', result
    assert result['completed'] is False and result['delivery_accepted'] is False


def test_audit_PASS_never_implies_full_RC_corner_or_SI_applicability(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, {'status': 'PASS', 'reason': 'SOURCE_ONLY',
                                          'extraction_depth': 'C_ONLY'})
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    if hasattr(owner, 'accept_d47'):
        assert result['metric_acceptance']['obligations'][0]['extraction_depth'] == 'C_ONLY'
        assert all(o['status'] == 'NOT_MEASURED' for o in result['metric_acceptance']['obligations'])


def test_existing_component_FAIL_survives_later_unmeasured_input(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, {}, component_status='FAIL', unavailable=True)
    assert result['default_row_status'] == 'FAIL' and result['completed'] is False


def test_unrecorded_source_is_not_retroactively_qualified(tmp_path):
    if not hasattr(owner, 'accept_d47'):
        pytest.skip('D47 metric reader absent on exact main')
    current = context()
    result = owner.accept_d47(tmp_path, current, {'step_id': 'D47',
        'context_sha256': current['context_sha256'], 'component_status': 'PASS'})
    assert result['status'] == 'NOT_MEASURED'
    assert 'D47_METRIC_SOURCE_CHANGED_OR_UNRECORDED' in result['detail']
    assert not (tmp_path / 'qualifications.json').exists()


def test_prior_metric_FAIL_survives_later_unmeasured_reader(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, {}, unavailable=True, prior_metric_fail=True)
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False
    if hasattr(owner, 'accept_d47'):
        assert result['metric_acceptance']['metric_status'] == 'FAIL'
        assert result['metric_acceptance']['obligations'][0]['status'] == 'FAIL'
        assert result['metric_acceptance']['prior_failed_obligation_ids']
