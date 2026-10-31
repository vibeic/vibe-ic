"""Source-only controls over neutral operating-point and connectivity outputs."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from _stated_eda_image import stated_image

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROGRAMS), str(PROGRAMS / 'tests')]
import analog_native_flow as native
import flow109
import flow109_metric_acceptance as metrics
from test_a02_binding_controls import sha, put
from test_analog_native_front import _op_project


@pytest.fixture
def op_case(tmp_path, monkeypatch):
    root, declared, tb = _op_project(tmp_path)
    net = tb.parent / 'cell_alpha.sp'
    model = root / 'input/pdk/models/resistor_alpha.sp'
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text('* synthetic source-control resistor model, no physical qualification\n'
                     '.model resistor_alpha R (RSH=1000)\n')
    net.write_text('* neutral source-controlled resistive stage\n'
                   '.include ../../../input/pdk/models/resistor_alpha.sp\n'
                   '.subckt cell_alpha supply out\n'
                   'r_series_input supply out resistor_alpha w=1u l=1u\n'
                   'r_shunt_output out 0 resistor_alpha w=1u l=1u\n.ends cell_alpha\n')
    source = root / 'input/synthetic-op-requirements.txt'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('Synthetic source-only target. cell_alpha out 0.5 to 0.7 V. No qualification.')
    put(root, 'input/analog_flow.json', {})
    authority = put(root, 'requirements/base_A4/operating_point_targets.json', {
        'schema': metrics.AUTHORITY_SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': {'path': str(source.relative_to(root)), 'sha256': sha(source)}},
        'limits': {'cell_alpha': {'out': {'min': .5, 'max': .7}}},
        'units': {'cell_alpha': {'out': 'V'}}})
    put(root, 'phase3/analog/cell_alpha/netlist_provenance.json', {
        '_provenance': {'producer': 'synthetic_source_control', 'design_content': 'structure_only',
                        'scope': 'neutral fixture declaration, no emitter history or qualification'}})
    image = stated_image()
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    def window(project, context):
        return native.run_window(project, SimpleNamespace(entry_step='A05', exit_step='A05',
            container='', image=image, transport='LOCAL'), features={'has_analog': True})
    monkeypatch.setattr(native, 'execute_window', window)
    context = {'requested_step': 'A05', 'context_sha256': 'c' * 64,
               'resolved_row': {'id': 'A05'}}
    result = native.execute(root, context)
    put(root, 'source-control-component.json', result)
    return root, context, result, authority


def replay(case):
    root, context, result, *_ = case
    return metrics.accept_a05(root, context, result)


def update_bound(case, edit):
    root, _, result, authority = case
    doc = json.loads(authority.read_text())
    edit(doc)
    authority.write_text(json.dumps(doc))
    result['a05_invocation']['inputs'][str(authority)] = sha(authority)


def test_real_op_and_connectivity_metric_positive_without_row_credit(op_case):
    root, context, result, _ = op_case
    assert result['component_status'] == 'PASS', result
    assert result['metric_acceptance_status'] == 'PASS', result
    observed = result['metric_acceptance']['metrics']
    assert observed['netlist_connectivity_errors']['value'] == 0
    assert observed['operating_point_targets']['targets'][0]['value'] == pytest.approx(.6)
    selected = flow109._selected_step_result(root, context, result, native)
    assert selected['metric_acceptance_status'] == 'PASS', selected
    assert selected['default_row_status'] == 'NOT_MEASURED'
    assert not selected['completed']
    assert not (root / 'qualifications.json').exists()


@pytest.mark.parametrize('fault', ['target_violation', 'missing_node', 'wrong_units', 'missing_bounds',
    'missing_capture', 'changed_netlist', 'changed_testbench', 'changed_log', 'changed_tool'])
def test_op_substantive_negative_controls(op_case, fault):
    root, _, result, authority = op_case
    if fault == 'target_violation':
        update_bound(op_case, lambda doc: doc['limits']['cell_alpha']['out'].update(min=0, max=.4))
    elif fault == 'missing_node':
        def edit(doc):
            doc['limits']['cell_alpha']['not_observed'] = {'max': 1}
            doc['units']['cell_alpha']['not_observed'] = 'V'
        update_bound(op_case, edit)
    elif fault == 'wrong_units':
        update_bound(op_case, lambda doc: doc['units']['cell_alpha'].update(out='mV'))
    elif fault == 'missing_bounds':
        authority.unlink()
    elif fault == 'missing_capture':
        result.pop('a05_invocation')
    elif fault == 'changed_netlist':
        (root / 'phase3/analog/cell_alpha/cell_alpha.sp').write_text('changed')
    elif fault == 'changed_testbench':
        (root / 'phase3/analog/cell_alpha/tb_cell_alpha.sp').write_text('changed')
    elif fault == 'changed_log':
        row = result['native_results']['steps'][0]
        ex = next(ex for ex in row['executions'] if ex['program'] == '@ngspice')
        Path(ex['args'][2]).write_text('changed')
    elif fault == 'changed_tool':
        result['a05_invocation']['tools']['ngspice']['sha256'] = '0' * 64
    answer = replay(op_case)
    assert answer['status'] != 'PASS', answer
    if fault == 'target_violation':
        assert answer['status'] == 'FAIL', answer
        assert answer['metrics']['operating_point_targets']['targets'][0]['value'] == pytest.approx(.6)


def test_out_of_bounds_value_survives_missing_second_target(op_case):
    def edit(doc):
        doc['limits']['cell_alpha'].update(out={'max': .4}, missing={'max': 1})
        doc['units']['cell_alpha']['missing'] = 'V'
    update_bound(op_case, edit)
    answer = replay(op_case)
    assert answer['status'] == 'FAIL', answer
    assert [target['status'] for target in answer['metrics']['operating_point_targets']['targets']] == ['FAIL', 'NOT_MEASURED']


def test_native_component_failure_survives_absent_authority(op_case):
    _, _, result, authority = op_case
    result['component_status'] = 'FAIL'
    authority.unlink()
    assert replay(op_case)['status'] == 'FAIL'
