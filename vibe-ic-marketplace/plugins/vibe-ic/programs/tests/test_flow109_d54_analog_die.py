"""D54 routing controls over the existing A14 format, not native qualification."""
import json
from types import SimpleNamespace

import pytest

import _path_layout as layout
import analog_native_flow as native
import flow109
from programs.tests._hostpaths import require_repo


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def features(analog=True):
    registry = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'flow109.json').read_text())
    label = 'Analog IC external trim' if analog else 'Digital IC'
    candidates = [p for p in registry['reference_profiles'] if label in p['name']]
    if not analog:
        candidates = [p for p in registry['reference_profiles']
                      if p['features']['has_digital'] and p['features']['ic']]
    return {**candidates[0]['features'], 'requires_spice': True}


@pytest.fixture
def carrier(tmp_path):
    project = tmp_path / 'design'
    import _delivery_route
    _delivery_route.admit(project, 'ic')
    blocks = [{'name': n, 'type': 'voltage_reference',
               'spec': {'specs': [{'name': 'vout', 'min': 1.1, 'max': 1.3}]}}
              for n in ('unit_a', 'unit_b')]
    put(layout.generated_docs_dir(project) / 'L5_ADI_SPEC.json', {'analog_blocks': blocks})
    put(project / 'manifest.json', {'features': features()})
    attempt = project / 'reports/analog_native/run-control'
    rows = []
    for block in blocks:
        name = block['name']
        put(layout.analog_dir(project) / name / 'spec.json', block['spec'])
        metrics = {'pre': {'measurements': {'vout': 1.2}},
                   'corners': [{'style': 'native_rc', 'measurements': {'vout': 1.21},
                                'missing': [], 'violations': []}],
                   'specs': [{'name': 'vout@native_rc', 'metric': 'vout',
                              'pre_value': 1.2, 'post_value': 1.21,
                              'delta_pct': 100 * .01 / 1.2}]}
        output = put(attempt / 'A14' / name / 'result.json',
                     {'status': 'PASS', 'metrics': metrics})
        rows.append({'step': 'A14', 'block': name, 'status': 'PASS', 'metrics': metrics,
                     'input_views': native._input_views(project, name, 'A14'),
                     'output_views': {str(output): native._sha(output)}})
    report = {'attempt': str(attempt), 'steps': rows}
    save(project, report)
    return project


def save(project, report):
    put(project / 'reports/analog_native/status.json', report)
    put(__import__('pathlib').Path(report['attempt']) / 'result.json', report)


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project / 'manifest.json',
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D54', exit_step='D54')
    rc = flow109.prepare_front_door(args, project)
    path = project / 'reports/flow109/default_rows/D54.json'
    # Base uses the real digital backend route; no manufactured base verdict.
    result = json.loads(path.read_text()) if path.exists() else {'default_row_status': 'NOT_MEASURED'}
    return rc, result


def test_all_macro_a14_results_pass_through_front_door(carrier):
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0
    assert result['digital_path']['status'] == 'NOT_APPLICABLE'
    assert result['digital_path']['native_steps'] == [
        'OpenSTA.WritePathSpice', 'Magic.ExtractCells', 'Ngspice.PathCorrelation']
    assert len(result['blocks']) == 2
    assert result['blocks'][0]['metrics']['specs'][0]['delta_pct'] == pytest.approx(100 * .01 / 1.2)
    assert result['native_started'] is False
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('case,expected,rc_expected', [
    ('miss', 'FAIL', 1), ('missing', 'NOT_MEASURED', 2),
    ('unmeasured', 'NOT_MEASURED', 2), ('stale', 'NOT_MEASURED', 2),
    ('weakened', 'NOT_MEASURED', 2), ('no_delta', 'NOT_MEASURED', 2)])
def test_one_macro_cannot_be_hidden(carrier, case, expected, rc_expected):
    report = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    row = report['steps'][1]
    if case == 'miss':
        row['status'] = 'FAIL'
        row['metrics']['corners'][0]['violations'] = ['vout']
    elif case == 'missing':
        report['steps'].pop()
    elif case == 'unmeasured':
        row['status'] = 'NOT_MEASURED'
    elif case == 'stale':
        put(layout.analog_dir(carrier) / 'unit_b/spec.json', {'specs': []})
    elif case == 'weakened':
        put(layout.analog_dir(carrier) / 'unit_b/spec.json',
            {'specs': [{'name': 'vout', 'min': 0, 'max': 5}]})
        row['input_views'] = native._input_views(carrier, 'unit_b', 'A14')
    else:
        row['metrics']['specs'] = []
    save(carrier, report)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == expected, result
    assert rc == rc_expected


def test_declared_digital_design_keeps_default_profile():
    row = flow109.resolve_step(flow109.resolve_plan(features(False)), 'D54')
    assert row['selected_profile'] == 'default'
    assert row['profile']['dispatch']['native_step_id'] == '30'
    assert row['profile']['native_steps'] == [
        'OpenSTA.WritePathSpice', 'Magic.ExtractCells', 'Ngspice.PathCorrelation']


def test_synthesized_top_cannot_use_analog_acceptance(carrier):
    p = layout.synth_dir(carrier) / 'unit_synth.v'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('module unit; endmodule\n')
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['digital_path']['status'] == 'NOT_MEASURED'
    assert result['reason'] == 'D54_MACRO_ONLY_TOP_CONFLICT'
    assert rc == 2
