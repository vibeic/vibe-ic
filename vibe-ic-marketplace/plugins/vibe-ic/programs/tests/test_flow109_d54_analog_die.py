"""D54 routing controls over the existing A14 format, not native qualification."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _path_layout as layout
import analog_native_flow as native
import analog_native_physical as physical
import analog_a7_post_layout_emit as a7
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
def carrier(tmp_path, monkeypatch):
    project = tmp_path / 'design'
    import _delivery_route
    _delivery_route.admit(project, 'ic')
    blocks = [{'name': n, 'type': 'voltage_reference',
               'spec': {'specs': [{'name': 'vout', 'min': 1.1, 'max': 1.3}]}}
              for n in ('unit_a', 'unit_b')]
    put(layout.generated_docs_dir(project) / 'L5_ADI_SPEC.json', {'analog_blocks': blocks})
    put(project / 'manifest.json', {'features': features()})
    results = {}
    for block in blocks:
        name = block['name']
        bdir, work = physical._paths(project, name)
        put(bdir / 'spec.json', block['spec'])
        put(bdir / (name + '.gds'), {'layout': 'original'})
        net = bdir / (name + '.sp')
        net.write_text(f'.subckt {name} a b vss\nR0 a b 1000\n.ends {name}\n')
        extracted = work / 'extracted.spice'
        extracted.parent.mkdir(parents=True)
        extracted.write_text(net.read_text().replace('1000', '1001'))
        put(work / 'A13.json', {'status': 'PASS', 'metrics': {
            'layout_sha256': native._sha(bdir / (name + '.gds')),
            'netlist_sha256': native._sha(net),
            'corners': [{'style': 'ngspice', 'extracted_netlist': str(extracted),
                         'sha256': native._sha(extracted)}]}})
        post_net = work / (name + '_post_ngspice.sp')
        body, _ = a7.post_layout_netlist(name, a7.subckt_ports(net.read_text(), name),
                                       extracted.read_text(), [])
        post_net.write_text(body)
        post_tb = work / ('tb_' + name + '_post_ngspice.sp')
        post_tb.write_text('.include ' + post_net.name + '\n.end\n')
        log = post_tb.with_suffix('.ngspice.log')
        log.write_text('MEAS vout=1.21\n')
        metrics = {'pre': {'measurements': {'vout': 1.2}},
                   'corners': [{'style': 'ngspice', 'measurements': {'vout': 1.21},
                                'post_netlist': str(post_net.relative_to(project)),
                                'post_netlist_sha256': native._sha(post_net),
                                'post_testbench': str(post_tb.relative_to(project)),
                                'post_testbench_sha256': native._sha(post_tb),
                                'missing': [], 'violations': []}],
                   'specs': [{'name': 'vout@ngspice', 'metric': 'vout',
                              'pre_value': 1.2, 'post_value': 1.21,
                              'delta_pct': 100 * .01 / 1.2}]}
        # Ordinary _resim publishes TB/log outputs; its POST netlist hash is
        # carried by the native corner, outside output_views.
        results[name] = {'status': 'PASS', 'metrics': metrics,
                         'outputs': [str(post_tb), str(log)]}
    monkeypatch.setattr(native, '_dispatch',
        lambda step, project, block, options, runner: results[block['name']])
    args = SimpleNamespace(entry_step='A14', exit_step='A14', pdk='',
                           flow109_manifest=project / 'manifest.json')
    report = native.run_window(project, args, features=features())
    assert report['window_verdict'] == 'PASS'
    assert versions.latest_pass(project, 'A14') is None
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
        for path in (bdir / (name + '.gds'), physical._paths(project, name)[1] / 'A13.json',
                     physical._paths(project, name)[1] / 'extracted.spice'):
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
    # Refresh run_window's derived block-list view with the same L5 facts.
    put(layout.analog_dir(carrier) / 'analog_block_list.json',
        {'blocks': doc['analog_blocks'], 'block_count': len(doc['analog_blocks'])})
    report = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    for row in report['steps']:
        row['input_views'] = native._input_views(carrier, row['block'], 'A14')
    save(carrier, report)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0


@pytest.mark.parametrize('changed', ['layout', 'extraction', 'pex', 'post_netlist'])
@pytest.mark.parametrize('collector', [False, True])
def test_stale_a14_physical_result_never_passes(carrier, changed, collector):
    """A passing unchanged native result must refuse changed physical bytes."""
    if collector:
        publish_current_a14(carrier)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0
    bdir, work = physical._paths(carrier, 'unit_b')
    path = {'layout': bdir / 'unit_b.gds', 'extraction': work / 'A13.json',
            'pex': work / 'extracted.spice',
            'post_netlist': work / 'unit_b_post_ngspice.sp'}[changed]
    original = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    path.write_text(path.read_text() + '\n* changed after A14 PASS\n')
    for row in original['steps']:
        assert all(row['input_views'].get(p) == h for p, h in
                   native._input_views(carrier, row['block'], 'A14').items())
    # The reviewer's replay keeps a current collector pointer while mutating
    # the actual POST netlist. The native corner hash must catch that change.
    if collector and changed == 'post_netlist':
        assert versions.latest_pass(carrier, 'A14')['current_inputs'] is True
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert rc == 2


@pytest.mark.parametrize('case', ['missing', 'not_canonical', 'capture_error'])
def test_native_pass_does_not_require_collector_pointer(carrier, case):
    publish_current_a14(carrier)
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
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0


@pytest.mark.parametrize('missing', ['post_netlist', 'post_netlist_sha256'])
def test_missing_native_corner_binding_is_not_measured(carrier, missing):
    report = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    report['steps'][1]['metrics']['corners'][0].pop(missing)
    save(carrier, report)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert rc == 2


def test_native_fail_is_preserved_without_collector_even_with_missing_physical_inputs(carrier):
    report = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    report['steps'][1]['status'] = 'FAIL'
    save(carrier, report)
    (physical._paths(carrier, 'unit_b')[1] / 'unit_b_post_ngspice.sp').unlink()
    assert versions.latest_pass(carrier, 'A14') is None
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'FAIL', result
    assert rc == 1


@pytest.mark.parametrize('sidecar', [False, True])
def test_macro_only_synth_wrapper_keeps_analog_acceptance(carrier, sidecar):
    put(layout.generated_docs_dir(carrier) / 'L9_INTEGRATION_SPEC.json',
        {'top_module': 'wrapper', 'macros': {'unit_a': {}},
         'instances': [{'name': 'wrapped', 'master': 'unit_a'}]})
    netlist = layout.synth_dir(carrier) / 'wrapper.v'
    netlist.parent.mkdir(parents=True, exist_ok=True)
    netlist.write_text('module wrapper(input a, output b);\n'
                       'unit_a wrapped (.a(a), .b(b));\nendmodule\n')
    if sidecar:
        put(layout.synth_dir(carrier) / layout.SYNTH_INPUTS_SIDECAR, {})
    # Documents added after publication must be reflected in the native
    # block readset; no collector catalog or pointer is manufactured.
    report = json.loads((carrier / 'reports/analog_native/status.json').read_text())
    for row in report['steps']:
        row['input_views'] = native._input_views(carrier, row['block'], 'A14')
    save(carrier, report)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0
    assert result['digital_path']['status'] == 'NOT_APPLICABLE'


def test_new_a13_extraction_cannot_reuse_old_post_netlist(carrier):
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'PASS', result
    assert rc == 0
    _, work = physical._paths(carrier, 'unit_b')
    extracted = work / 'extracted.spice'
    extracted.write_text(extracted.read_text().replace('1001', '1002'))
    record = json.loads((work / 'A13.json').read_text())
    record['metrics']['corners'][0]['sha256'] = native._sha(extracted)
    put(work / 'A13.json', record)
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['blocks'][1]['reason'] == 'D54_A14_POST_NETLIST_DIFFERS_FROM_CURRENT_A13'
    assert rc == 2


@pytest.mark.parametrize('logic', ['cell', 'expression'])
def test_synthesized_logic_alongside_macro_refuses_analog_acceptance(carrier, logic):
    netlist = layout.synth_dir(carrier) / 'wrapper.v'
    netlist.parent.mkdir(parents=True, exist_ok=True)
    extra = ('logic_cell buf0 (.a(a), .b(b));' if logic == 'cell'
             else 'assign b = ~a;')
    netlist.write_text('module wrapper(input a, output b);\n'
                       'unit_a wrapped (.a(a), .b(b));\n' + extra + '\nendmodule\n')
    rc, result = invoke(carrier)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D54_MACRO_ONLY_TOP_CONFLICT'
    assert rc == 2


@pytest.mark.parametrize('post,expected,rc_expected', [(1.21, 'PASS', 0), (.8, 'FAIL', 1)])
def test_real_a14_producer_and_publisher_need_no_collector(carrier, monkeypatch, post, expected, rc_expected):
    """Exercise _resim + run_window; only native SPICE execution is supplied."""
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    for name in ('unit_a', 'unit_b'):
        bdir, _ = physical._paths(carrier, name)
        (bdir / ('tb_' + name + '.sp')).write_text(
            f'.include {name}.sp\nX1 a b 0 {name}\n.control\nop\n'
            'echo "MEAS vout=" $&v(b)\n.endc\n.end\n')
    monkeypatch.setattr(physical, '_pre_layout_measurements',
                        lambda *a: ({'vout': 1.2}, {'source': 'A07'}))
    monkeypatch.setattr(dr, 'resolve_host_root', lambda *a: str(carrier))
    monkeypatch.setattr(ars, '_container_path', lambda c, root, p: str(p))
    monkeypatch.setattr(ars, '_run_ngspice',
                        lambda *a, **k: (True, {'vout': post}, 'MEAS vout=' + str(post), {}))
    monkeypatch.setattr(native, '_dispatch', lambda step, project, block, options, runner:
                        physical._resim(project, block['name'], '', '', '', {}))
    args = SimpleNamespace(entry_step='A14', exit_step='A14', pdk='',
                           flow109_manifest=carrier / 'manifest.json')
    report = native.run_window(carrier, args, features=features())
    assert report['window_verdict'] == expected, report
    assert versions.latest_pass(carrier, 'A14') is None
    assert all(row['metrics']['corners'][0].get('post_netlist_sha256') for row in report['steps'])
    rc, result = invoke(carrier)
    assert result['default_row_status'] == expected, result
    assert rc == rc_expected
