"""D54 routing controls over the existing A14 format, not native qualification."""
import json
from types import SimpleNamespace

import pytest

import _path_layout as layout
import analog_native_flow as native
import flow109
import step_output_collector as versions
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
        bdir = layout.analog_dir(project) / name
        put(bdir / 'spec.json', block['spec'])
        put(bdir / (name + '.gds'), {'layout': 'original'})
        put(bdir / 'native/A13.json', {'extraction': 'original'})
        put(bdir / 'native/extracted.spice', {'pex': 'original'})
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
    publish_current_a14(project)
    return project


def save(project, report):
    put(project / 'reports/analog_native/status.json', report)
    put(__import__('pathlib').Path(report['attempt']) / 'result.json', report)


def publish_current_a14(project):
    """Use the real collector with a synthetic canonical A14 catalog row.

    Native-result/current-input protocol controls, not native qualification.
    Only the row catalog is supplied; latest_pass and its hashing are real.
    """
    from unittest.mock import patch
    inputs = {}
    for name in ('unit_a', 'unit_b'):
        inputs.update({str(__import__('pathlib').Path(p).relative_to(project)): h
                       for p, h in native._input_views(project, name, 'A14').items()})
        bdir = layout.analog_dir(project) / name
        for path in (bdir / (name + '.gds'), bdir / 'native/A13.json',
                     bdir / 'native/extracted.spice'):
            inputs[str(path.relative_to(project))] = native._sha(path)
    row = ('A14', 'Analog post-layout performance', 'PASS', 'phase3', 'stage4', [])
    with patch.object(versions, '_iter_step_records', lambda _: iter([row])):
        attempt = versions.begin_step(project, 'A14', inputs)
        versions.finish_step(project, attempt, verdict='PASS', canonical_pass=True)
    assert versions.latest_pass(project, 'A14')['current_inputs'] is True


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


def test_original_l5_label_alias_keeps_native_numeric_limits(carrier):
    l5 = layout.generated_docs_dir(carrier) / 'L5_ADI_SPEC.json'
    doc = json.loads(l5.read_text())
    doc['analog_blocks'][0]['spec']['specs'][0]['name'] = 'Output voltage'
    put(l5, doc)
    report = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    for row in report['steps']:
        row['input_views'] = native._input_views(carrier, row['block'], 'A14')
    save(carrier, report)
    publish_current_a14(carrier)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0


@pytest.mark.parametrize('physical', ['layout', 'extraction', 'pex'])
def test_stale_a14_physical_result_never_passes(carrier, physical):
    """Reviewer HIGH: A14's old input_views omit physical extraction inputs."""
    bdir = layout.analog_dir(carrier) / 'unit_b'
    path = {'layout': bdir / 'unit_b.gds', 'extraction': bdir / 'native/A13.json',
            'pex': bdir / 'native/extracted.spice'}[physical]
    original = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    assert versions.latest_pass(carrier, 'A14')['canonical_pass'] is True
    put(path, {'physical': 'changed after A14 PASS'})
    # The old guard still agrees with every saved native input_view, while
    # the flow's existing resolved input manifest detects stale physical bytes.
    for row in original['steps']:
        assert all(row['input_views'].get(p) == h for p, h in
                   native._input_views(carrier, row['block'], 'A14').items())
    assert versions.latest_pass(carrier, 'A14')['current_inputs'] is False
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert rc == 2


@pytest.mark.parametrize('case', ['missing', 'not_canonical', 'capture_error'])
def test_a14_requires_existing_current_canonical_result(carrier, case):
    root = versions._versions_root(carrier)
    pointer = json.loads((root / 'latest_pass.json').read_text())['steps']['A14']
    if case == 'missing':
        (root / 'latest_pass.json').unlink()
    else:
        record_path = root / pointer['folder'] / 'outputs.json'
        record = json.loads(record_path.read_text())
        if case == 'not_canonical':
            record['canonical_pass'] = False
        else:
            record['capture_errors'] = ['native output capture incomplete']
        put(record_path, record)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert rc == 2
