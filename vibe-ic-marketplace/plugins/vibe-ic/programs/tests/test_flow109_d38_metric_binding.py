"""SOURCE_ONLY CTS binding controls. Native execution/receipt and bounds APIs
are explicit method doubles; no runtime qualification or row PASS is claimed.
The real producer, prelaunch target binding and metric consumer are exercised.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import execution_backend_producers as producer
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as ll
import librelane_cts_hold as ch

TARGETS = 'input/flow109/D34/clock_planning_targets.json'
REQUIREMENT = 'requirements/base_25/clock_skew_insertion_drv.json'
DRV = ('design__max_slew_violation__count', 'design__max_cap_violation__count',
       'design__max_fanout_violation__count')
REAL_RECEIPT = ll.validate_step_receipt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / 'source-only-cts'
    project.mkdir()

    def put(name, data):
        p = project / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data) if isinstance(data, (dict, list)) else data)
        return p

    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D38', 'D38')
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(put('context.json', context)))
    targets = put(TARGETS, {'targets': {'clock_skew_ns': 2.4, 'insertion_delay_ns': 12.0},
        'units': {'clock_skew_ns': 'ns', 'insertion_delay_ns': 'ns'}})
    requirement = put(REQUIREMENT, 'SOURCE_ONLY_NOT_AN_APPROVED_DOCUMENT\n')
    put('phase3/stage3/cts/clock_plan.json', {'clocks': [{'name': 'core_clock'}]})
    auth = {'status': 'SOURCE_ONLY_BOUNDS_METHOD_DOUBLE', 'path': REQUIREMENT,
        'sha256': sha(requirement), 'source': {'path': TARGETS, 'sha256': sha(targets)}}
    body = {'limits': {'clock_skew_ns': {'max': 2.4}, 'insertion_delay_ns': {'max': 12.0},
                      **{key: {'max': 0} for key in DRV}},
            'units': {'clock_skew_ns': 'ns', 'insertion_delay_ns': 'ns',
                      **{key: 'count' for key in DRV}}}
    monkeypatch.setattr(metrics, '_approved_document', lambda *a, **kw: (auth, body))
    model = put('inputs/cells.lib', 'library (neutral) {\n time_unit : "1ns";\n}\n')
    sdc = put('inputs/constraints.sdc', 'create_clock -name core_clock -period 24 [get_ports clock]\n')
    nl = put('inputs/design.v', 'module neutral(); endmodule\n')
    placed = put('phase3/stage3/pnr/placed.def', 'SOURCE_ONLY_PLACED_DEF\n')
    initial = put('inputs/state.json', {'nl': str(nl), 'sdc': str(sdc), 'def': str(placed), 'metrics': {}})
    steps = ['OpenROAD.CTS', 'Vibeic.ClockPathDriveSizing', 'Vibeic.ExternalCaptureLaunchRetap']
    corners = ['slow_case', 'fast_case']
    allsteps = steps + ['OpenROAD.STAMidPNR'] * len(corners)
    states, folders, receipts, configs = [], [], {}, {}
    values = {key: 0 for key in DRV}
    previous = initial
    for index, step in enumerate(allsteps, 1):
        folder = project / 'phase3/librelane/execution-backend-19' / (
            f'{index:02d}-' + step.lower().replace('.', '-'))
        name = step + ('@' + corners[index - 4] if index > 3 else '')
        config = put('phase3/librelane/execution-backend-19-config/' + name + '.json',
            {'meta': {'step': step}, 'STA_CORNERS': corners, 'LIB': str(model),
             'PNR_CORNERS': [corners[index - 4]] if index > 3 else corners})
        if index <= 3:
            definition = put(folder / 'design.def', 'SOURCE_ONLY_CTS_DEF_' + str(index))
            odb = put(folder / 'design.odb', 'SOURCE_ONLY_CTS_ODB_' + str(index))
            configs[step] = config
        else:
            corner = corners[index - 4]
            values.update({f'clock__skew__worst_setup__corner:{corner}': -0.2,
                           f'clock__skew__worst_hold__corner:{corner}': 0.15})
            put(folder / corner / 'clock.rpt', 'Clock: core_clock\nPropagated: yes\n'
                'report_clock_latency\nClock core_clock\nrise -> rise\n    min     max\n'
                '100.000 100.000 source latency\n0.200         network latency r0/CLK\n'
                '        0.300 network latency r1/CLK\n---------------\n'
                '100.200 100.300 latency\n        0.100 skew\n'
                'report_clock_min_period\n')
        state = put(folder / 'state_out.json', {'nl': str(nl), 'sdc': str(sdc),
            'def': str(definition), 'odb': str(odb), 'metrics': dict(values)})
        log = put(folder / 'invocation.log',
            '[INFO] No information on clock propagation in input SDC file-- propagating all clocks.\n')
        pdk = put(folder / 'pdk_root.json', {'mounts_under_it': []})
        put(folder / 'vibeic_receipt.json', 'SOURCE_ONLY_INVALID_NATIVE_RECEIPT\n')
        before = json.loads(previous.read_text())
        fp = {'image': 'SOURCE_ONLY_DOUBLE', 'step': step, 'state': sha(previous),
            'config': sha(config), 'state_files': {str(p): sha(p) for p in ll._walk_paths(
                {k: v for k, v in before.items() if k != 'metrics'})},
            'config_files': {str(model): sha(model)}}
        if step.startswith('Vibeic.'):
            fp['plugin'] = ll._plugin_digests(step)
        hashes = {str(p.relative_to(folder)): sha(p) for p in folder.rglob('*')
                  if p.is_file() and p.name != 'vibeic_receipt.json'}
        receipts[str(folder)] = {'input': fp, 'sha256': hashes}
        previous = state
        states.append(state)
        folders.append(folder)
    cts_report = put(folders[0] / 'cts.rpt', 'Total number of Sinks: 2.\n')
    receipts[str(folders[0])]['sha256']['cts.rpt'] = sha(cts_report)
    configs['OpenROAD.STAMidPNR'] = put('phase3/librelane/execution-backend-19-config/OpenROAD.STAMidPNR.json',
        {'meta': {'step': 'OpenROAD.STAMidPNR'}, 'STA_CORNERS': corners})
    handoff = {'state': str(states[2]), 'state_sha256': sha(states[2]), 'views': {}}
    for view, filename in [('def', 'post_cts.def'), ('odb', 'post_cts.odb')]:
        src = folders[2] / ('design.' + view)
        dst = put('phase3/stage3/pnr/' + filename, src.read_text())
        handoff['views'][view] = {'source': str(src), 'source_sha256': sha(src),
            'dest': str(dst), 'dest_sha256': sha(dst)}
    runner = SimpleNamespace(_resolved_cell_policy=lambda config, *a, **kw: (config, []),
        _parse_def_components=lambda *a: [('r0', 'neutral_ff')],
        _clock_path_drive_sizing_tcl=lambda: 'SOURCE_ONLY_SIZING_BODY\n')
    monkeypatch.setattr(producer, '_parameters', lambda *a: (runner, ll, SimpleNamespace(name='neutral'), None))
    monkeypatch.setattr(producer, '_cts_selected_predecessor', lambda *a: 'placed.def')
    monkeypatch.setattr(producer, '_current_physical_sdc', lambda *a: sdc)
    monkeypatch.setattr(producer, '_handoff', lambda *a, **kw: handoff)
    monkeypatch.setattr(producer, '_logs', lambda *a, **kw: None)
    monkeypatch.setattr(ch, 'signoff_scene_sdc', lambda *a: sdc)
    monkeypatch.setattr(ll, 'resolve_step_configs', lambda *a, **kw: dict(configs))
    monkeypatch.setattr(ll, 'derive_step_config', lambda src, dst, *a, **kw: dst)
    monkeypatch.setattr(ll, 'validate_step_receipt', lambda folder, step: receipts[str(folder)])
    calls, after_native = [], []

    def native(*a, **kw):
        calls.append({'targets_sha256_at_launch': sha(targets) if targets.is_file() else None,
                      'requirements_sha256_at_launch': sha(requirement) if requirement.is_file() else None})
        for action in after_native:
            action()
        return folders

    monkeypatch.setattr(ll, 'run_chain', native)

    def run(complete=False):
        if complete:
            monkeypatch.setattr(producer, '_native_current_step_output_snapshot', lambda *a: {})
            monkeypatch.setattr(producer, '_native_current_step_producer', lambda *a: 'SOURCE_ONLY_DOUBLE')
            monkeypatch.setattr(producer, '_native_current_step_receipt', lambda *a: {'scope': 'SOURCE_ONLY_DOUBLE'})
            monkeypatch.setattr(producer, '_current_step_producer_authority', lambda *a, **kw: (True, '', 'PASS'))
            monkeypatch.setattr(producer, '_runner_context', lambda: SimpleNamespace(
                _DECLARED_SIGNOFF_GATES=[], _PRESTREAM_GATES=[]))
        result = (producer.produce if complete else producer.produce_pnr)(project,
            {'step_id': '19', 'top': 'neutral', 'image_id': 'SOURCE_ONLY_DOUBLE',
             'pdk_root': str(project / 'inputs'), 'state_in': str(initial), 'stop_on_producer_failure': True})
        put('SOURCE_ONLY_OBSERVATION.json', {'result': result, 'native_method_double_calls': calls})
        return result

    def update(index):
        p = states[index]
        receipts[str(p.parent)]['sha256']['state_out.json'] = sha(p)
        if index + 1 < len(states):
            receipts[str(states[index + 1].parent)]['input']['state'] = sha(p)

    return SimpleNamespace(project=project, put=put, targets=targets, requirement=requirement,
        auth=auth, body=body, run=run, calls=calls, states=states, folders=folders,
        receipts=receipts, update=update, context=context, model=model, after_native=after_native)


def metric(result):
    return next(o for o in result.get('metric_acceptance', {}).get('obligations', [])
                if o['id'] == 'base_25.clock_skew_insertion_drv')


def test_native_cts_values_use_exact_prelaunch_targets_without_backward_pass(case):
    result = case.run()
    assert metric(result)['status'] == 'PASS', result
    assert result['metric_acceptance']['status'] == result['metric_acceptance']['qualification'] == 'NOT_MEASURED'
    assert case.calls == [{'targets_sha256_at_launch': sha(case.targets),
                          'requirements_sha256_at_launch': sha(case.requirement)}]
    receipt = json.loads((case.project / 'reports/phase3/librelane_cts_handoff.json').read_text())
    assert receipt['flow109_d38_targets']['targets'] == case.auth['source']
    checks = {x['field']: x for x in metric(result)['measurements']}
    assert checks['clock_skew_ns']['measurement']['value'] == pytest.approx(0.2)
    assert checks['insertion_delay_ns']['measurement']['value'] == pytest.approx(0.3)


@pytest.mark.parametrize('broken', ['missing_target', 'changed_target', 'foreign_source',
    'changed_requirement', 'wrong_limits', 'wrong_units', 'missing_requirement'])
def test_invalid_targets_refuse_before_any_native_execution(case, broken):
    if broken == 'missing_target':
        case.targets.unlink()
    elif broken == 'changed_target':
        case.targets.write_text('{}')
    elif broken == 'foreign_source':
        case.auth['source']['path'] = 'input/foreign.json'
    elif broken == 'changed_requirement':
        case.requirement.write_text('CHANGED')
    elif broken == 'wrong_limits':
        case.body['limits']['clock_skew_ns']['max'] = 2.5
    elif broken == 'wrong_units':
        case.body['units']['insertion_delay_ns'] = 'ps'
    else:
        case.requirement.unlink()
    result = case.run()
    assert result['verdict'] in ('NOT_MEASURED', 'FAIL'), result
    assert case.calls == [], result


@pytest.mark.parametrize('field', ['skew', 'latency', *DRV])
def test_actual_cts_overbound_is_fail_even_with_other_fields_clean(case, field):
    if field == 'latency':
        path = case.folders[-1] / 'fast_case/clock.rpt'
        path.write_text(path.read_text().replace('0.300 network', '12.100 network'))
        case.receipts[str(path.parent.parent)]['sha256']['fast_case/clock.rpt'] = sha(path)
    else:
        state = json.loads(case.states[-1].read_text())
        state['metrics']['clock__skew__worst_setup__corner:fast_case' if field == 'skew' else field] = -2.5 if field == 'skew' else 1
        case.states[-1].write_text(json.dumps(state))
        case.update(len(case.states) - 1)
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert metric(result)['status'] == 'FAIL'


@pytest.mark.parametrize('broken', ['model', 'receipt', 'missing_corner_report', 'ideal_clock'])
def test_missing_or_foreign_native_measurement_cannot_pass(case, monkeypatch, broken):
    if broken == 'model':
        case.model.write_text('CHANGED')
    elif broken == 'receipt':
        monkeypatch.setattr(ll, 'validate_step_receipt', REAL_RECEIPT)
    elif broken == 'missing_corner_report':
        path = case.folders[-1] / 'fast_case/clock.rpt'
        path.unlink()
        del case.receipts[str(case.folders[-1])]['sha256']['fast_case/clock.rpt']
    else:
        for folder in case.folders[3:]:
            log = folder / 'invocation.log'
            log.write_text('No information on clock propagation in input SDC file-- unpropagating all clocks.\n')
            case.receipts[str(folder)]['sha256']['invocation.log'] = sha(log)
    result = case.run()
    assert metric(result)['status'] == 'NOT_MEASURED', result


def test_native_latency_parser_reads_real_checked_in_report_without_source_latency():
    from _hostpaths import require_repo
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
        'fixtures', 'librelane_import', '8HD-9', 'runs', 'cmp3', '12-openroad-staprepnr',
        'nom_ff_n40C_5v50', 'clock.rpt')
    parser = getattr(metrics, '_d38_clock_network_latency', lambda *a: {})
    assert parser(path.read_text(), ['clk']) == {'clk': pytest.approx(0.350133)}


@pytest.mark.parametrize('broken', ['changed', 'missing'])
def test_targets_revalidate_after_native_execution(case, broken):
    case.after_native.append(lambda: case.targets.write_text('{}') if broken == 'changed' else case.targets.unlink())
    result = case.run()
    assert len(case.calls) == 1
    assert metric(result)['status'] == 'NOT_MEASURED', result


def test_measured_overbound_survives_missing_later_latency_report(case):
    state = json.loads(case.states[-1].read_text())
    state['metrics']['clock__skew__worst_setup__corner:fast_case'] = -2.5
    case.states[-1].write_text(json.dumps(state))
    case.update(len(case.states) - 1)
    path = case.folders[-1] / 'fast_case/clock.rpt'
    path.unlink()
    del case.receipts[str(case.folders[-1])]['sha256']['fast_case/clock.rpt']
    result = case.run()
    assert result['verdict'] == 'FAIL', result


def test_changed_target_during_config_preparation_refuses_before_launch(case, monkeypatch):
    resolve = ll.resolve_step_configs

    def mutate(*args, **kwargs):
        result = resolve(*args, **kwargs)
        case.targets.write_text('{}')
        return result

    monkeypatch.setattr(ll, 'resolve_step_configs', mutate)
    with pytest.raises(producer.em.Refusal, match='D38_TARGETS_CHANGED_BEFORE_EXECUTION'):
        case.run()
    assert case.calls == []


def test_reapproved_changed_target_cannot_rebind_an_execution_after_launch(case):
    def resign():
        plan = json.loads(case.targets.read_text())
        plan['targets']['clock_skew_ns'] = 2.5
        case.targets.write_text(json.dumps(plan))
        case.auth['source']['sha256'] = sha(case.targets)
        case.body['limits']['clock_skew_ns']['max'] = 2.5
        case.requirement.write_text('SOURCE_ONLY_NEW_BOUNDS_SENTINEL')
        case.auth['sha256'] = sha(case.requirement)

    case.after_native.append(resign)
    result = case.run()
    assert metric(result)['status'] == 'NOT_MEASURED', result


def test_boolean_limit_never_compares_as_a_numeric_target_before_launch(case):
    plan = json.loads(case.targets.read_text())
    plan['targets']['clock_skew_ns'] = 1.0
    case.targets.write_text(json.dumps(plan))
    case.auth['source']['sha256'] = sha(case.targets)
    case.body['limits']['clock_skew_ns']['max'] = True
    result = case.run()
    assert result['verdict'] == 'NOT_MEASURED', result
    assert case.calls == []


@pytest.mark.parametrize('bad', [False, True])
def test_cts_completion_retains_metric_judgement(case, bad):
    if bad:
        state = json.loads(case.states[-1].read_text())
        state['metrics']['clock__skew__worst_setup__corner:fast_case'] = -2.5
        case.states[-1].write_text(json.dumps(state))
        case.update(len(case.states) - 1)
    result = case.run(complete=True)
    assert result['verdict'] == ('FAIL' if bad else 'PASS'), result
    assert result['canonical_receipts'][0].get('metric_acceptance') == result.get('metric_acceptance') != None


def test_nonobject_limit_refuses_before_native_launch(case):
    case.body['limits']['clock_skew_ns'] = 2.4
    result = case.run()
    assert result['verdict'] == 'NOT_MEASURED', result
    assert case.calls == []


def test_unclosed_clock_report_cannot_supply_insertion_measurement(case):
    p = case.folders[-1] / 'fast_case/clock.rpt'
    p.write_text(p.read_text().replace('report_clock_min_period', 'SOURCE_ONLY_TRUNCATED'))
    case.receipts[str(case.folders[-1])]['sha256']['fast_case/clock.rpt'] = sha(p)
    result = case.run()
    assert metric(result)['status'] == 'NOT_MEASURED', result


def test_measured_drv_failure_survives_missing_later_latency_report(case):
    state = json.loads(case.states[-1].read_text())
    state['metrics'][DRV[0]] = 1
    case.states[-1].write_text(json.dumps(state))
    case.update(len(case.states) - 1)
    path = case.folders[-1] / 'fast_case/clock.rpt'
    path.unlink()
    del case.receipts[str(case.folders[-1])]['sha256']['fast_case/clock.rpt']
    result = case.run()
    assert result['verdict'] == 'FAIL', result


@pytest.mark.parametrize('model,expected', [
    ('library (neutral) { time_unit : "1ns"; }\n', 'PASS'),
    ('library (neutral) { /* format-only comment */ time_unit : "1ns"; }\n', 'PASS'),
    ('library (neutral) { /* time_unit : "1ns"; */ time_unit : "1ps"; }\n', 'NOT_MEASURED'),
])
def test_model_unit_is_a_liberty_attribute_not_a_line_position(case, model, expected):
    case.model.write_text(model)
    for receipt in case.receipts.values():
        receipt['input']['config_files'][str(case.model)] = sha(case.model)
    result = case.run()
    assert metric(result)['status'] == expected, result
