"""D01 compares source-approved dimensionless quantities without dropping units."""
from copy import deepcopy
import json

import pytest

import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo


def compare(project, quantity, tokens, pointer='/quantity', **extra):
    path = project/'phase1/generated_docs/L5_ADI_SPEC.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'quantity': quantity}))
    expectation = {'id':'quantity', 'layer':'L5_ADI_SPEC', 'field_path':pointer,
                   'expected_tokens':tokens, 'requirement':'Preserve this declared quantity.', **extra}
    original = deepcopy(expectation)
    result = metrics._d0102_compare(project, {'expectations':[expectation]}, {})
    assert expectation == original
    return result


@pytest.mark.parametrize('expected_unit', ['—', '-', ''])
@pytest.mark.parametrize('actual_unit', ['—', '-', '', None])
def test_dimensionless_quantity_is_a_number(tmp_path, expected_unit, actual_unit):
    quantity = {'target':2.0}
    if actual_unit is not None:
        quantity['unit'] = actual_unit
    actual, unresolved, unrouted = compare(tmp_path, quantity, ['2.0',expected_unit])
    assert len(unresolved) == 0
    assert actual == [{'id':'quantity'}]
    assert unrouted == []


@pytest.mark.parametrize('expected_unit', ['—', '-', ''])
@pytest.mark.parametrize('actual_unit', ['V', 'mA', 'MHz'])
def test_dimensionless_requirement_refuses_a_physical_unit(tmp_path, expected_unit, actual_unit):
    actual, unresolved, _ = compare(tmp_path, {'target':2.0,'unit':actual_unit}, ['2.0',expected_unit])
    assert actual == []
    assert len(unresolved) == 1


def test_physical_unit_mismatch_still_fails(tmp_path):
    actual, unresolved, _ = compare(tmp_path, {'target':2.0,'unit':'mA'}, ['2.0','V'])
    assert actual == []
    assert unresolved == []


def test_wrong_dimensionless_number_still_fails(tmp_path):
    actual, _, _ = compare(tmp_path, {'target':3.0,'unit':'—'}, ['2.0','—'])
    assert actual == []


@pytest.mark.parametrize('target,token', [(2, '2.0'), (2.0, '2'), (256, '2.56e2'),
                                          (-2, '-2.0'), (0.5, '.5')])
def test_dimensionless_numbers_compare_by_value(tmp_path, target, token):
    actual, unresolved, unrouted = compare(tmp_path, {'target':target,'unit':'—'}, [token,'—'])
    assert actual == [{'id':'quantity'}]
    assert unresolved == []
    assert unrouted == []


@pytest.mark.parametrize('field', ['name', 'description'])
@pytest.mark.parametrize('expected_unit', ['—', '-', ''])
def test_text_cannot_supply_a_wrong_dimensionless_number(tmp_path, field, expected_unit):
    quantity = {'target':3.0, 'unit':expected_unit, field:'2.0'}
    actual, unresolved, _ = compare(tmp_path, quantity, ['2.0',expected_unit])
    assert actual == []
    assert unresolved == []


@pytest.mark.parametrize('target', [True, False, float('nan'), float('inf'), -float('inf'), '2.0'])
def test_invalid_quantity_values_cannot_match_description(tmp_path, target):
    quantity = {'target':target, 'unit':'', 'description':'2.0'}
    actual, unresolved, _ = compare(tmp_path, quantity, ['2.0',''])
    assert actual == []
    assert len(unresolved) == 1


@pytest.mark.parametrize('field', ['value', 'target', 'typ', 'min', 'max'])
def test_existing_quantity_numeric_fields_are_supported(tmp_path, field):
    actual, unresolved, _ = compare(tmp_path, {field:2, 'unit':''}, ['2.0',''])
    assert actual == [{'id':'quantity'}]
    assert unresolved == []


def test_unitless_quantity_with_numeric_tokens_needs_no_placeholder(tmp_path):
    actual, unresolved, _ = compare(tmp_path, {'target':2, 'unit':''}, ['2.0'])
    assert actual == [{'id':'quantity'}]
    assert unresolved == []


def test_generic_scalar_comparison_is_preserved(tmp_path):
    actual, unresolved, _ = compare(tmp_path, 2.0, ['2.0'])
    assert actual == [{'id':'quantity'}]
    assert unresolved == []


def test_withdrawn_numeric_requirement_is_not_revived(tmp_path):
    actual, unresolved, _ = compare(tmp_path, {'target':2, 'unit':''}, ['2.0',''],
                                  withdrawn='Owner withdrew this requirement.')
    assert actual == []
    assert len(unresolved) == 1


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
