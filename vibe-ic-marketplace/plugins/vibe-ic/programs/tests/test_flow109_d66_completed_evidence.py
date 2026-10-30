"""Actual D66/Step-28 consumer controls; completed producer data are test doubles.

These controls qualify consumption, not a native device-physics method.
"""
from __future__ import annotations

import pytest

from test_flow109_final_perc import _case, _put


def completed_case(project, monkeypatch, damage=None):
    perc, context, subjects, calls, _ = _case(project, monkeypatch, real_consumer=True)
    original = perc.backend_producers.produce

    def produce(project, params):
        result = original(project, params)
        import json
        summary = json.loads((project / perc.OUTPUTS[0]).read_text())
        for row in summary['categories']:
            if row['category'] in perc.REQUIRED_MANUAL:
                row.update(status='AUTOMATED', result='PASS')
            if row['category'] == 'ESD protection presence':
                row['library_errors'] = []
                library = _put(project, 'test-inputs/qualified-library.spice',
                               '* synthetic producer control; not native physics evidence\n')
                row['library_sources'] = [{**library, 'path': str(project / library['path'])}]
        for name in ('ESD discharge-path topology (connectivity)',
                     'Latch-up well-tap presence', 'Latch-up tap spacing (geometry)'):
            summary['categories'].append({'category': name, 'status': 'AUTOMATED', 'result': 'PASS'})
        summary['manual_review_pending'] = []
        summary['geometry_foundry_data_residual'] = ''
        if damage == 'absent_model':
            # Remove the actual selected source: a missing model is not just a label.
            (project / 'test-inputs/qualified-library.spice').unlink()
        elif damage == 'missing_category':
            summary['categories'] = [r for r in summary['categories']
                                     if r['category'] != 'io_supply_pad_sufficiency']
        elif damage == 'violation':
            row = next(r for r in summary['categories'] if r['category'] == 'io_supply_pad_sufficiency')
            row['result'] = 'FAIL'
            summary['automated_failed'] = [row['category']]
            summary['verdict'] = 'PERC_EQUIV_FAIL'
        elif damage == 'physics_residual':
            summary['geometry_foundry_data_residual'] = 'Vhold/SCR model unavailable'
        elif damage == 'unknown_result':
            summary['categories'][1]['result'] = 'SIGNED'
        elif damage == 'duplicate_category':
            summary['categories'].append(dict(summary['categories'][1]))
        elif damage == 'missing_disclosure':
            del summary['geometry_foundry_data_residual']
        elif damage == 'geometry_review':
            summary['categories'][1].update(status='SEMI_AUTOMATED', result='REVIEW')
        elif damage == 'manual_signature':
            summary['categories'][1].update(status='MANUAL_REVIEW', result='MANUAL_REVIEW',
                                            checklist=[{'confirmed': True}])
            summary['manual_review_pending'] = [summary['categories'][1]['category']]
        for name, value in (
                (perc.OUTPUTS[0], summary),
                (perc.OUTPUTS[1], 'OVERALL VERDICT: ' + summary['verdict'] + '\n' +
                 '\n'.join(r['category'] for r in summary['categories'])),
                (perc.OUTPUTS[2], '**Overall verdict:** `' + summary['verdict'] + '`\n' +
                 '\n'.join(r['category'] for r in summary['categories']))):
            _put(project, name, value)
        if damage == 'foreign_geometry':
            (project / subjects['geometry_def']['path']).write_text('foreign final DEF')
        return result

    monkeypatch.setattr(perc.backend_producers, 'produce', produce)
    return perc, context


def test_completed_evidence_reaches_existing_consumer_and_readback(tmp_path, monkeypatch):
    perc, context = completed_case(tmp_path, monkeypatch)
    result = perc.execute(tmp_path, context)
    assert result['consumer_result']['audit']['verdict'] == 'PASS'
    assert result['component_status'] == 'PASS', result
    assert not result['manual_review_pending'] and not result['unsupported_capabilities']
    assert perc.validate_final_perc(tmp_path, result['receipt'])['component_status'] == 'PASS'
    assert result['flow109_acceptance'] == result['whole_ic_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage,status,reason', [
    ('absent_model', 'NOT_MEASURED', 'D66_PAD_LIBRARY_EVIDENCE_INVALID'),
    ('foreign_geometry', 'NOT_MEASURED', 'D66_REQUIRED_INPUT_CHANGED'),
    ('missing_category', 'NOT_MEASURED', 'D66_REQUIRED_REVIEW_CATEGORY_ABSENT'),
    ('violation', 'FAIL', 'D66_AUTOMATED_PERC_FAILED'),
    ('physics_residual', 'NOT_MEASURED', 'D66_DEVICE_PHYSICS_UNSUPPORTED'),
    ('unknown_result', 'NOT_MEASURED', 'D66_REQUIRED_CATEGORY_NOT_MEASURED'),
    ('duplicate_category', 'NOT_MEASURED', 'D66_PERC_RESULT_INVALID'),
    ('missing_disclosure', 'NOT_MEASURED', 'D66_FOUNDRY_CAPABILITY_DISCLOSURE_ABSENT'),
    ('geometry_review', 'NOT_MEASURED', 'D66_REQUIRED_CATEGORY_NOT_MEASURED'),
    ('manual_signature', 'NOT_MEASURED', 'D66_MANUAL_REVIEW_PENDING'),
])
def test_completed_evidence_controls(tmp_path, monkeypatch, damage, status, reason):
    perc, context = completed_case(tmp_path, monkeypatch, damage)
    result = perc.execute(tmp_path, context)
    assert result['component_status'] == status, result
    assert result['reason'] == reason, result


def test_metric_bindings_consume_completed_categories(tmp_path, monkeypatch):
    perc, context = completed_case(tmp_path, monkeypatch)
    result = perc.execute(tmp_path, context)
    assert result['component_status'] == 'PASS', result
    measured = perc.metric_measurements(tmp_path, result['receipt'])
    topology = measured['final_perc.final_esd_supply_topology']
    latchup = measured['final_perc.final_perc_latchup_errors']
    assert topology['status'] == latchup['status'] == 'MEASURED'
    assert {'category': 'ESD protection presence'} in topology['value']
    assert latchup['value'] == 0 and latchup['unit'] == 'count'
    # Retained carrier CVC HI-Z failures do not become invented latch-up counts.
    failed_project = tmp_path / 'electrical-failure'
    perc, context, _, _, _ = _case(failed_project, monkeypatch, native_cvc_fail=True,
                                  real_consumer=True)
    failed = perc.execute(failed_project, context)
    assert failed['component_status'] == 'FAIL'
    assert all(row['status'] == 'NOT_MEASURED' and 'value' not in row
               for row in perc.metric_measurements(failed_project, failed['receipt']).values())


def test_metric_bindings_do_not_turn_residual_into_zero(tmp_path, monkeypatch):
    perc, context = completed_case(tmp_path, monkeypatch, 'physics_residual')
    result = perc.execute(tmp_path, context)
    assert result['reason'] == 'D66_DEVICE_PHYSICS_UNSUPPORTED', result
    measured = perc.metric_measurements(tmp_path, result['receipt'])
    assert all(row['status'] == 'NOT_MEASURED' and 'value' not in row
               for row in measured.values())


@pytest.mark.parametrize('signals,expected', [(1, 'NOT_MEASURED'), (2, 'FAIL')])
def test_existing_supply_producer_completed_category_is_consumed(tmp_path, monkeypatch, signals, expected):
    import json
    import perc_corpus_sweep as supply
    perc, context, _, _, _ = _case(tmp_path, monkeypatch, real_consumer=True)
    original = perc.backend_producers.produce
    classes = {'sig': 'PAD INPUT', 'hi': 'PAD POWER', 'lo': 'PAD POWER'}
    components = [(f's{i}', 'sig') for i in range(signals)] + [('hp', 'hi'), ('lp', 'lo')]
    roles = {m: {'H': ('INOUT', 'POWER'), 'L': ('INOUT', 'GROUND')} for m in classes}
    declaration = {'domains': [{'power_net': 'upper', 'ground_net': 'lower',
                               'max_signal_pads_per_power_pad': 1,
                               'max_signal_pads_per_ground_pad': 1}]}
    limit = _put(tmp_path, 'test-inputs/supply-limits.json', declaration)
    library = {'classes': classes, 'pin_roles': roles, 'bond_pins': {'hi': ['H'], 'lo': ['L']},
               'limits': [{'declaration': declaration, 'source': limit}], 'errors': []}
    text = ('SPECIALNETS 2 ;\n- upper ' + ' '.join(f'( {i} H )' for i, _ in components) +
            ' ;\n- lower ' + ' '.join(f'( {i} L )' for i, _ in components) + ' ;\nEND SPECIALNETS\n')
    produced = supply.io_supply_pad_sufficiency(components, text, library)
    assert produced['status'] == 'AUTOMATED'
    assert produced['result'] == ('PASS' if signals == 1 else 'FAIL')

    def publish(project, params):
        result = original(project, params)
        summary = json.loads((project / perc.OUTPUTS[0]).read_text())
        summary['categories'] = [produced if r['category'] == produced['category'] else r
                                 for r in summary['categories']]
        summary['manual_review_pending'].remove(produced['category'])
        if produced['result'] == 'FAIL':
            summary['automated_failed'] = [produced['category']]
            summary['verdict'] = 'PERC_EQUIV_FAIL'
        _put(project, perc.OUTPUTS[0], summary)
        names = '\n'.join(r['category'] for r in summary['categories'])
        _put(project, perc.OUTPUTS[1], 'OVERALL VERDICT: ' + summary['verdict'] + '\n' + names)
        _put(project, perc.OUTPUTS[2], '**Overall verdict:** `' + summary['verdict'] + '`\n' + names)
        return result

    monkeypatch.setattr(perc.backend_producers, 'produce', publish)
    result = perc.execute(tmp_path, context)
    assert result['component_status'] == expected, result
    assert result['reason'] == ('D66_MANUAL_REVIEW_PENDING' if signals == 1
                               else 'D66_AUTOMATED_PERC_FAILED'), result
    assert produced['category'] not in result['manual_review_pending']
    assert result['consumer_result']['audit']['verdict'] == ('PASS_WITH_OPEN_ITEMS' if signals == 1 else 'FAIL')
