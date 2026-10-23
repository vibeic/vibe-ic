from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_native_physical as physical


def native_case(tmp_path, value=1.0, gate_limit=1.6, body_limit=1.6):
    wrapper, parameters = tmp_path / 'wrapper.lib', tmp_path / 'parameters.lib'
    wrapper.write_text('.subckt wrapped d g s b\n.include "parameters.lib"\n'
                       'Ndevice d g s b intrinsic w=1u l=0.2u\n.ends wrapped\n')
    parameters.write_text('.model intrinsic psp103va\n' + '\n'.join(
        f'+ V{key.upper()}_MAX={gate_limit if key in ("gs", "gd", "gb", "ds") else body_limit}'
        for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb')) + '\n')
    views = {str(path): {'path': str(path), 'sha256': physical._sha(path)} for path in (wrapper, parameters)}
    device = {'instance': 'measured_device', 'model': 'wrapped', 'role': 'nmos',
              'pairs_v': {key: value for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb')}}
    case = {'name': 'accepted-native-op', 'status': 'PASS', 'mos_stress': {
        'status': 'PASS', 'devices': [device], 'source_models': {'wrapped': {'role': 'nmos'}}}}
    return {'native_inputs': views, 'cases': [case]}, wrapper, parameters


@pytest.mark.parametrize('value,expected', [(1.6, 'PASS'), (1.60001, 'FAIL')])
def test_native_mos_stress_uses_exact_consumed_pdk_limits(tmp_path, value, expected):
    measured, _, _ = native_case(tmp_path, value)
    result = physical._mission_from_native_interconnect(measured)
    assert result['status'] == expected
    assert result['cases'][0]['terminal_pairs'] == 6
    assert result['cases'][0]['limits']['wrapped'] == {key: 1.6 for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb')}


def test_hv_gate_rating_does_not_override_body_junction_rating(tmp_path):
    measured, _, _ = native_case(tmp_path, 1.7, gate_limit=3, body_limit=1.6)
    result = physical._mission_from_native_interconnect(measured)
    assert result['status'] == 'FAIL'
    assert {row['pair'] for row in result['cases'][0]['violations']} == {'db', 'sb'}


@pytest.mark.parametrize('fault', ['changed_model', 'missing_pair', 'unknown_model', 'missing_limit', 'wrong_terminals'])
def test_missing_or_stale_native_model_evidence_is_not_a_stress_pass(tmp_path, fault):
    measured, wrapper, parameters = native_case(tmp_path)
    if fault == 'changed_model':
        parameters.write_text(parameters.read_text() + '* changed\n')
    elif fault == 'missing_pair':
        measured['cases'][0]['mos_stress']['devices'][0]['pairs_v'].pop('gb')
    elif fault == 'unknown_model':
        measured['cases'][0]['mos_stress']['source_models'] = {'unknown': {}}
    elif fault == 'missing_limit':
        parameters.write_text(parameters.read_text().replace('VSB_MAX', 'OTHER'))
        measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    else:
        wrapper.write_text(wrapper.read_text().replace('wrapped d g s b', 'wrapped g d s b'))
        measured['native_inputs'][str(wrapper)]['sha256'] = physical._sha(wrapper)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'NOT_MEASURED'


def test_unrelated_model_cannot_supply_the_wrappers_missing_limit(tmp_path):
    measured, _, parameters = native_case(tmp_path)
    parameters.write_text(parameters.read_text().replace('VSB_MAX=1.6', 'OTHER=1.6') +
                          '.model unrelated psp103va VSB_MAX=99\n')
    measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('prefix', ['* COMMENT ONLY: ', '; ', '$ ', '// ', '.param unrelated=0 ', ' '])
def test_commented_or_different_card_ratings_cannot_supply_missing_model_bounds(tmp_path, prefix):
    measured, _, parameters = native_case(tmp_path)
    fake = ' '.join(f'V{key.upper()}_MAX=9' for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb'))
    parameters.write_text('.model intrinsic psp103va\n' + prefix + fake + '\n')
    measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('delimiter', [';', '$ ', '//'])
def test_inline_comment_cannot_supply_an_active_continuation_rating(tmp_path, delimiter):
    measured, _, parameters = native_case(tmp_path)
    parameters.write_text(parameters.read_text().replace('+ VSB_MAX=1.6',
        '+ unused=0 ' + delimiter + ' VSB_MAX=9'))
    measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('surround', ['note="{}"', "note='{}'", 'note=({})', 'note="{}'])
def test_rating_names_inside_another_parameter_value_are_not_active_assignments(tmp_path, surround):
    measured, _, parameters = native_case(tmp_path)
    fake = ' '.join(f'V{key.upper()}_MAX=9' for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb'))
    parameters.write_text('.model intrinsic psp103va ' + surround.format(fake) + '\n')
    measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('quote', ["'", '"'])
def test_actual_quoted_literal_rating_assignments_remain_usable(tmp_path, quote):
    measured, _, parameters = native_case(tmp_path)
    parameters.write_text(parameters.read_text().replace('=1.6', '=' + quote + '1.6' + quote))
    measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'PASS'


@pytest.mark.parametrize('delimiter', ['* ignored ', '; ', '$ ', '// '])
def test_commented_alternative_preserves_active_lower_rating_and_its_failure(tmp_path, delimiter):
    measured, _, parameters = native_case(tmp_path, 1.7)
    fake = ' '.join(f'V{key.upper()}_MAX=9' for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb'))
    parameters.write_text(parameters.read_text() + delimiter + fake + '\n')
    measured['native_inputs'][str(parameters)]['sha256'] = physical._sha(parameters)
    assert physical._mission_from_native_interconnect(measured)['status'] == 'FAIL'


def test_voltage_stress_remains_independent_of_em_verdict(tmp_path):
    measured, _, _ = native_case(tmp_path)
    measured['status'] = measured['cases'][0]['status'] = 'FAIL'
    assert physical._mission_from_native_interconnect(measured)['status'] == 'PASS'


def test_actual_overstress_remains_failure_before_another_missing_case(tmp_path):
    measured, _, _ = native_case(tmp_path, 2.0)
    measured['cases'].append({})
    assert physical._mission_from_native_interconnect(measured)['status'] == 'FAIL'


@pytest.mark.parametrize('value,expected', [(1.1, 'PASS'), (1.4, 'NOT_MEASURED'), (1.7, 'FAIL')])
def test_unselected_intrinsic_branch_bounds_do_not_invent_a_violation(tmp_path, value, expected):
    measured, wrapper, parameters = native_case(tmp_path, value)
    wrapper.write_text(wrapper.read_text().replace('.ends wrapped',
        'Nother d g s b second_variant w=1u l=0.2u\n.ends wrapped'))
    parameters.write_text(parameters.read_text() + '.model second_variant psp103va\n+ ' +
        ' '.join(f'V{key.upper()}_MAX=1.3' for key in ('gs', 'gd', 'gb', 'ds', 'db', 'sb')) + '\n')
    for path in (wrapper, parameters):
        measured['native_inputs'][str(path)]['sha256'] = physical._sha(path)
    assert physical._mission_from_native_interconnect(measured)['status'] == expected
