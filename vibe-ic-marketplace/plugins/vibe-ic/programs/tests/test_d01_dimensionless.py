"""D01 compares source-approved dimensionless quantities without dropping units."""
from copy import deepcopy
import json

import pytest

import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo


def compare(project, quantity, tokens, pointer='/quantity'):
    path = project/'phase1/generated_docs/L5_ADI_SPEC.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'quantity': quantity}))
    expectation = {'id':'quantity', 'layer':'L5_ADI_SPEC', 'field_path':pointer,
                   'expected_tokens':tokens, 'requirement':'Preserve this declared quantity.'}
    original = deepcopy(expectation)
    result = metrics._d0102_compare(project, {'expectations':[expectation]}, {})
    assert expectation == original
    return result


@pytest.mark.parametrize('expected_unit', ['—', '-'])
@pytest.mark.parametrize('actual_unit', ['—', '-', None])
def test_dimensionless_quantity_is_a_number(tmp_path, expected_unit, actual_unit):
    quantity = {'target':2.0}
    if actual_unit is not None:
        quantity['unit'] = actual_unit
    actual, unresolved, unrouted = compare(tmp_path, quantity, ['2.0',expected_unit])
    assert len(unresolved) == 0
    assert actual == [{'id':'quantity'}]
    assert unrouted == []


@pytest.mark.parametrize('actual_unit', ['V', 'mA', 'MHz'])
def test_dimensionless_requirement_refuses_a_physical_unit(tmp_path, actual_unit):
    actual, unresolved, _ = compare(tmp_path, {'target':2.0,'unit':actual_unit}, ['2.0','—'])
    assert actual == []
    assert len(unresolved) == 1


def test_physical_unit_mismatch_still_fails(tmp_path):
    actual, unresolved, _ = compare(tmp_path, {'target':2.0,'unit':'mA'}, ['2.0','V'])
    assert actual == []
    assert unresolved == []


def test_wrong_dimensionless_number_still_fails(tmp_path):
    actual, _, _ = compare(tmp_path, {'target':3.0,'unit':'—'}, ['2.0','—'])
    assert actual == []


def test_missing_quantity_path_still_refuses(tmp_path):
    actual, unresolved, _ = compare(tmp_path, {'target':2.0,'unit':'—'}, ['2.0','—'], '/absent')
    assert actual == []
    assert len(unresolved) == 1


@pytest.mark.parametrize('index', [1, 2])
def test_checked_in_spec_quantity_reaches_d01(tmp_path, index):
    source = require_repo('vibe-ic-marketplace','plugins','vibe-ic','programs','tests','fixtures',
                          'stage_analog_on_pass_review','accept_adc_conv','phase1','generated_docs','L5_ADI_SPEC.json')
    quantity = json.loads(source.read_text())['analog_blocks'][0]['spec']['specs'][index]
    actual, unresolved, _ = compare(tmp_path, quantity, [str(quantity['target']),quantity['unit']])
    assert len(unresolved) == 0
    assert actual == [{'id':'quantity'}]
