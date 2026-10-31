"""SOURCE_ONLY native-report reader/completion controls, no native row credit.

Real checked-in RDB/log calibration bytes back the parser controls. Synthetic
GDS hash headers test the parser protocol only; they do not claim that these
reports measured that GDS. Completion controls inject at the observation seam,
exercise the actual consumer and never create qualification/native receipts.
"""
import json
import re
import shutil
from pathlib import Path

import pytest
import flow109
import gds_antenna_deck_check as owner
from _hostpaths import require_repo


@pytest.fixture
def native_report(tmp_path, request):
    if not hasattr(owner, '_d43_metric_readback'):
        pytest.skip('metric reader absent on exact main; canonical controls still execute')
    kind = getattr(request, 'param', 'violation')
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'calibration')
    rdb, log = tmp_path / 'native.lyrdb', tmp_path / 'native.log'
    shutil.copyfile(source / ('native_antenna_' + kind + '.lyrdb'), rdb)
    text = (source / ('native_antenna_' + kind + '.log')).read_text()
    gds = tmp_path / 'source_only_protocol_subject.gds'
    gds.write_text('SOURCE_ONLY hash-protocol subject; no geometry/native credit\n')
    log.write_text(owner._BIND_PREFIX + owner._sha(gds) + '\n' + text)
    parent = owner._GENERATOR_RE.search(rdb.read_text()).group(1)
    decks = owner._executed_native_decks(text)
    assert len(decks) == 1, 'actual calibrated report must identify its single source rule file'
    return gds, rdb, log, {'parent': parent, 'rule': next(iter(decks))}


@pytest.mark.parametrize('native_report', ['clean', 'violation'], indirect=True)
def test_actual_calibration_RDB_is_regraded_without_self_approving_population(native_report):
    gds, rdb, log, deck = native_report
    observed = owner._d43_metric_readback(gds, rdb, log, owner._sha(gds), deck)
    assert observed['violations'] == (0 if 'SUCCESS (0' in log.read_text() else 1)
    assert observed['observed_rules']
    assert observed['required_rules'] is None and observed['checked_gate_nets'] is None
    assert observed['population_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['changed_gds', 'changed_parent', 'wrong_rule', 'wrong_tally', 'missing_rdb'])
def test_native_identity_and_completion_damage_refuses(native_report, damage):
    gds, rdb, log, deck = native_report
    original = owner._sha(gds)
    if damage == 'changed_gds':
        gds.write_text('changed source-only subject')
    elif damage == 'changed_parent':
        deck['parent'] += '-foreign'
    elif damage == 'wrong_rule':
        deck['rule'] += '-foreign'
    elif damage == 'wrong_tally':
        log.write_text(re.sub(r'DRC RESULT: FAILURE \(1 violation\(s\)\)',
                             'DRC RESULT: FAILURE (2 violation(s))', log.read_text()))
    else:
        rdb.unlink()
    with pytest.raises(ValueError, match='D43_NATIVE_METRIC_UNBOUND'):
        owner._d43_metric_readback(gds, rdb, log, original, deck)


def context():
    for ref in flow109.load_registry()['reference_profiles']:
        plan = flow109.resolve_plan(ref['features'])
        row = next((r for r in plan['rows'] if r['id'] == 'D43'), None)
        if row and row['profile']['id'] == 'analog_die':
            return flow109.execution_context(plan, 'D43', 'D43')
    raise AssertionError('registered analog D43 profile absent')


def consume(tmp_path, monkeypatch, count, *, component_status='PASS', unavailable=False, prior_metric_fail=False):
    current = context()
    if hasattr(owner, '_d43_metric_observation'):
        def observe(*args):
            if unavailable:
                raise ValueError('SOURCE_ONLY_MISSING_NATIVE_BINDING')
            return {'violations': count, 'observed_rules': ['neutral_rule'],
                    'required_rules': None, 'scope': 'SOURCE_ONLY_FUNCTION_EDGE_CONTROL'}
        monkeypatch.setattr(owner, '_d43_metric_observation', observe)
    component = {'step_id': 'D43', 'context_sha256': current['context_sha256'],
        'component_status': component_status, 'default_row_status': 'NOT_MEASURED',
        'completed': False, 'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}
    if prior_metric_fail:
        component.update(metric_acceptance_status='FAIL', default_row_status='FAIL',
            metric_acceptance={'status': 'FAIL', 'reason': 'SOURCE_ONLY_PRIOR_MEASURED_FAILURE',
                'obligations': [{'id': current['resolved_row']['obligations'][0]['id'], 'status': 'FAIL'}]})
    return flow109._selected_step_result(tmp_path, current, component, adapter=owner)


@pytest.mark.parametrize('count', [1, 7, 17])
def test_actual_completion_consumer_blocks_native_count_without_component_FAIL(tmp_path, monkeypatch, count):
    result = consume(tmp_path, monkeypatch, count)
    assert result['default_row_status'] == 'FAIL', result
    assert result['completed'] is False and result['delivery_accepted'] is False


def test_zero_native_count_cannot_supply_rule_or_gate_population(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, 0)
    assert result['default_row_status'] == 'NOT_MEASURED' and result['completed'] is False
    if hasattr(owner, 'accept_d43'):
        assert result['metric_acceptance']['obligations'][0]['observed_value'] == 0
        assert result['metric_acceptance']['obligations'][1]['status'] == 'NOT_MEASURED'


def test_later_missing_native_basis_preserves_existing_component_FAIL(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, 0, component_status='FAIL', unavailable=True)
    assert result['default_row_status'] == 'FAIL' and result['completed'] is False


def test_reader_refuses_unrecorded_sources_without_creating_qualification(tmp_path):
    if not hasattr(owner, 'accept_d43'):
        pytest.skip('metric reader absent on exact main')
    current = context()
    result = owner.accept_d43(tmp_path, current, {'step_id': 'D43',
        'context_sha256': current['context_sha256'], 'component_status': 'PASS'})
    assert result['status'] == 'NOT_MEASURED'
    assert 'D43_METRIC_SOURCE_CHANGED_OR_UNRECORDED' in result['detail']
    assert not (tmp_path / 'qualifications.json').exists()


def test_prior_metric_FAIL_survives_later_unmeasured_reader(tmp_path, monkeypatch):
    result = consume(tmp_path, monkeypatch, 0, unavailable=True, prior_metric_fail=True)
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False
    if hasattr(owner, 'accept_d43'):
        assert result['metric_acceptance']['metric_status'] == 'FAIL'
        assert result['metric_acceptance']['obligations'][0]['status'] == 'FAIL'
        assert result['metric_acceptance']['prior_failed_obligation_ids']
