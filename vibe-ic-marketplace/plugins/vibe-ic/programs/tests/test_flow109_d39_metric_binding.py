"""SOURCE_ONLY post-CTS controls; native receipt and bounds readers are doubles.

The real producer branch, native state readback and metric operator run. No
approved document, native receipt or qualification is authored by these cases.
"""
import hashlib
import json
from types import SimpleNamespace

import pytest

import execution_backend_producers as producer
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as ll


REAL_RECEIPT_READER = ll.validate_step_receipt
DRV = ('design__max_slew_violation__count', 'design__max_cap_violation__count',
       'design__max_fanout_violation__count')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / 'source-only-post-cts'
    project.mkdir()

    def put(relative, body):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body) if isinstance(body, (dict, list)) else body)
        return path

    features = dict(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                         if p['name'] == 'Small digital IC without DFT'))
    context = flow109.execution_context(flow109.resolve_plan(features), 'D39', 'D39')
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(put('context.json', context)))
    model = put('inputs/model.lib', 'SOURCE_ONLY_MODEL_SENTINEL\n')
    netlist = put('inputs/netlist.v', 'module neutral(); endmodule\n')
    sdc = put('inputs/scene.sdc', 'SOURCE_ONLY_CONSTRAINT_SENTINEL\n')
    previous = put('inputs/pre_hold.json', {'nl': str(netlist), 'sdc': str(sdc), 'metrics': {}})
    before = previous
    steps = ['OpenROAD.ResizerTimingPostCTS', 'OpenROAD.STAMidPNR', 'OpenROAD.STAMidPNR']
    corners = ['slow_case', 'fast_case']
    records, configs, states, folders = {}, [], [], []
    accumulated = {key: 0 for key in DRV}
    for index, step in enumerate(steps, 1):
        folder = project / 'phase3/librelane/execution-backend-20' / (
            f'{index:02d}-' + step.lower().replace('.', '-'))
        name = step + (('@' + corners[index - 2]) if index > 1 else '')
        config = put('phase3/librelane/execution-backend-20-config/' + name + '.json',
            {'meta': {'step': step}, 'STA_CORNERS': corners, 'LIB': str(model),
             'PNR_CORNERS': [corners[index - 2]] if index > 1 else corners})
        if index == 1:
            definition = put(folder / 'design.def', 'SOURCE_ONLY_DEF_SENTINEL\n')
            odb = put(folder / 'design.odb', 'SOURCE_ONLY_ODB_SENTINEL\n')
        if index > 1:
            for kind in ['setup', 'hold']:
                accumulated[f'timing__{kind}__ws__corner:{corners[index - 2]}'] = 0.2
        state = put(folder / 'state_out.json', {'def': str(definition), 'odb': str(odb),
            'nl': str(netlist), 'sdc': str(sdc), 'metrics': dict(accumulated)})
        pdk = put(folder / 'pdk_root.json', {'mounts_under_it': []})
        put(folder / 'vibeic_receipt.json', 'SOURCE_ONLY_INVALID_NATIVE_RECEIPT\n')
        log = put(folder / 'invocation.log', 'SOURCE_ONLY_TOOL_METHOD_DOUBLE\n')
        input_state = json.loads(previous.read_text())
        records[str(folder)] = {'input': {'image': 'SOURCE_ONLY_DOUBLE', 'step': step,
            'config': sha(config), 'state': sha(previous),
            'state_files': {str(p): sha(p) for p in ll._walk_paths(
                {k: v for k, v in input_state.items() if k != 'metrics'})},
            'config_files': {str(model): sha(model)}},
            'sha256': {p.name: sha(p) for p in [state, pdk, log] +
                       ([definition, odb] if index == 1 else [])}}
        previous = state
        configs.append(config)
        states.append(state)
        folders.append(folder)
    handoff = {'program': 'execution_backend_producers._cts_split', 'image': 'SOURCE_ONLY_DOUBLE',
        'selected': 'librelane', 'corners': corners, 'steps': steps,
        'chain': {steps[0]: str(folders[0].relative_to(project)),
                  steps[-1]: str(folders[-1].relative_to(project))},
        'measured_state': str(states[-1].relative_to(project)),
        'measured_state_sha256': sha(states[-1]), 'views': {}}
    for view, name in [('def', 'post_hold.def'), ('odb', 'post_hold.odb')]:
        source = folders[0] / ('design.' + view)
        target = put('phase3/stage3/pnr/' + name, source.read_text())
        handoff['views']['post_hold_' + view] = {
            'source': str(source), 'source_sha256': sha(source),
            'dest': str(target.relative_to(project)), 'dest_sha256': sha(target)}
    handoff_path = put('reports/phase3/librelane_cts_hold_handoff.json', handoff)
    put('reports/phase3/pnr/hold_area.json', {
        'sources': {'before': str(before.relative_to(project)),
                    'after': str(states[0].relative_to(project))}})
    monkeypatch.setattr(ll, 'validate_step_receipt', lambda folder, step: records[str(folder)])
    monkeypatch.setattr(producer, '_parameters', lambda *a: (None, ll, None, None))
    component = {'verdict': 'PASS', 'detail': 'SOURCE_ONLY_CTS_SPLIT_METHOD_DOUBLE'}
    monkeypatch.setattr(producer, '_cts_split', lambda *a, **kw: dict(component))

    def update_state(index):
        path = states[index]
        records[str(path.parent)]['sha256']['state_out.json'] = sha(path)
        if index + 1 < len(states):
            records[str(states[index + 1].parent)]['input']['state'] = sha(path)
        if index == len(states) - 1:
            handoff['measured_state_sha256'] = sha(path)
            handoff_path.write_text(json.dumps(handoff))

    def run(complete=False):
        params = {'step_id': '20', 'top': 'neutral', 'image_id': 'SOURCE_ONLY_DOUBLE',
                  'stop_on_producer_failure': True}
        if complete:
            monkeypatch.setattr(producer, '_native_current_step_output_snapshot', lambda *a: {})
            monkeypatch.setattr(producer, '_native_current_step_producer', lambda *a: 'SOURCE_ONLY_DOUBLE')
            monkeypatch.setattr(producer, '_native_current_step_receipt', lambda *a: {'scope': 'SOURCE_ONLY_DOUBLE'})
            monkeypatch.setattr(producer, '_current_step_producer_authority',
                                lambda *a, **kw: (True, '', 'PASS'))
            monkeypatch.setattr(producer, '_runner_context', lambda: SimpleNamespace(
                _DECLARED_SIGNOFF_GATES=[], _PRESTREAM_GATES=[]))
        result = (producer.produce if complete else producer.produce_pnr)(project, params)
        put('SOURCE_ONLY_OBSERVATION.json', {'scope': 'SOURCE_ONLY', 'result': result})
        return result

    return SimpleNamespace(project=project, put=put, run=run, component=component,
        configs=configs, states=states, records=records, model=model, corners=corners,
        handoff=handoff, handoff_path=handoff_path, update_state=update_state)


def bounds_double(case, monkeypatch):
    source = case.put('inputs/requirements.txt', 'SOURCE_ONLY_REQUIREMENTS_METHOD_DOUBLE\n')
    relative = 'requirements/base_26/post_cts_setup_hold_drv.json'
    path = case.put(relative, 'NOT_AN_APPROVED_DOCUMENT\n')
    auth = {'status': 'SOURCE_ONLY_METHOD_DOUBLE', 'path': relative, 'sha256': sha(path),
            'source': {'path': str(source.relative_to(case.project)), 'sha256': sha(source)}}
    limits = {f'timing__{kind}__ws__corner:{corner}': {'min': 0}
              for corner in case.corners for kind in ['setup', 'hold']}
    limits.update({key: {'max': 0} for key in DRV})
    body = {'limits': limits, 'units': {key: 'count' if key in DRV else 'ns' for key in limits}}
    monkeypatch.setattr(metrics, '_approved_document', lambda *a, **kw: (auth, body))
    return body


def timing(result):
    return next(o for o in result.get('metric_acceptance', {}).get('obligations', [])
                if o['id'] == 'base_26.post_cts_setup_hold_drv')


def test_current_native_corner_values_reach_existing_operator(case, monkeypatch):
    bounds_double(case, monkeypatch)
    result = case.run()
    assert result['verdict'] == 'PASS'
    assert timing(result)['status'] == 'PASS', result
    assert len(timing(result)['measurements']) == 7
    assert result['metric_acceptance']['status'] == 'NOT_MEASURED'
    assert result['metric_acceptance']['qualification'] == 'NOT_MEASURED'
    assert result['metric_acceptance']['obligations'][1]['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('field', ['timing__hold__ws__corner:fast_case',
    'timing__setup__ws__corner:fast_case', *DRV])
def test_bad_native_timing_value_blocks_producer(case, monkeypatch, field):
    bounds_double(case, monkeypatch)
    state = json.loads(case.states[-1].read_text())
    state['metrics'][field] = 1 if field in DRV else -0.4
    case.states[-1].write_text(json.dumps(state))
    case.update_state(len(case.states) - 1)
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert timing(result)['status'] == 'FAIL'


@pytest.mark.parametrize('broken', ['model', 'state', 'config', 'handoff', 'alias', 'receipt'])
def test_stale_or_unbound_native_inputs_refuse_measurement(case, monkeypatch, broken):
    bounds_double(case, monkeypatch)
    if broken == 'model':
        case.model.write_text('CHANGED\n')
    elif broken == 'state':
        case.states[0].write_text('{}')
    elif broken == 'config':
        case.configs[-1].write_text('{}')
    elif broken == 'handoff':
        case.handoff['measured_state_sha256'] = '0' * 64
        case.handoff_path.write_text(json.dumps(case.handoff))
    elif broken == 'alias':
        (case.project / 'phase3/stage3/pnr/post_hold.def').write_text('CHANGED\n')
    else:
        monkeypatch.setattr(ll, 'validate_step_receipt', REAL_RECEIPT_READER)
    result = case.run()
    assert result.get('metric_acceptance', {}).get('metric_status') == 'NOT_MEASURED', result
    assert not any(o['status'] == 'PASS' for o in result['metric_acceptance']['obligations'])


def test_missing_bounds_never_turns_state_values_into_acceptance(case):
    result = case.run()
    assert timing(result)['status'] == 'NOT_MEASURED'
    assert result['metric_acceptance']['metric_status'] == 'NOT_MEASURED'


def test_native_failure_survives_missing_bounds(case):
    case.component['verdict'] = 'FAIL'
    result = case.run()
    assert result['verdict'] == 'FAIL'
    assert result.get('metric_acceptance', {}).get('status') == 'FAIL', result


def test_measured_failure_survives_later_undeclared_field(case, monkeypatch):
    body = bounds_double(case, monkeypatch)
    body['limits']['timing__setup__ws__corner:slow_case'] = {'min': 1}
    body['limits']['unknown_field'] = {'max': 0}
    body['units']['unknown_field'] = 'ns'
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert timing(result)['status'] == 'FAIL'


@pytest.mark.parametrize('bad', [False, True])
def test_normal_completion_envelope_retains_metric_judgement(case, monkeypatch, bad):
    body = bounds_double(case, monkeypatch)
    if bad:
        body['limits']['timing__setup__ws__corner:slow_case'] = {'min': 1}
    result = case.run(complete=True)
    assert result['verdict'] == ('FAIL' if bad else 'PASS'), result
    envelope = result['canonical_receipts'][0]
    assert envelope.get('metric_acceptance') == result.get('metric_acceptance') != None
    assert timing(result)['status'] == ('FAIL' if bad else 'PASS')


@pytest.mark.parametrize('bad', ['missing_corner', 'partial_bounds', 'boolean_count', 'nan_slack'])
def test_incomplete_or_invalid_numeric_population_is_unmeasured(case, monkeypatch, bad):
    body = bounds_double(case, monkeypatch)
    key = 'timing__hold__ws__corner:fast_case'
    state = json.loads(case.states[-1].read_text())
    if bad == 'missing_corner':
        del state['metrics'][key]
    elif bad == 'partial_bounds':
        del body['limits'][key]
        del body['units'][key]
    elif bad == 'boolean_count':
        state['metrics'][DRV[0]] = False
    else:
        state['metrics'][key] = float('nan')
    case.states[-1].write_text(json.dumps(state))
    case.update_state(len(case.states) - 1)
    result = case.run()
    assert timing(result)['status'] == 'NOT_MEASURED', result
    assert result['metric_acceptance']['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('sid', ['19', '20'])
def test_component_path_without_selected_row_preserves_result(case, monkeypatch, sid):
    monkeypatch.delenv('VIBEIC_FLOW109_CONTEXT')
    result = producer.produce_pnr(case.project, {'step_id': sid, 'top': 'neutral',
        'image_id': 'SOURCE_ONLY_DOUBLE'})
    assert result == case.component


@pytest.mark.parametrize('broken', ['missing', 'malformed', 'stale'])
@pytest.mark.parametrize('native_fail', [False, True])
def test_context_refusal_retains_observed_native_failure(case, broken, native_fail):
    path = case.project / 'context.json'
    if broken == 'missing':
        path.unlink()
    elif broken == 'malformed':
        path.write_text('NOT_JSON')
    else:
        context = json.loads(path.read_text())
        context['context_sha256'] = '0' * 64
        path.write_text(json.dumps(context))
    if native_fail:
        case.component['verdict'] = 'FAIL'
    result = case.run()
    assert result['verdict'] == ('FAIL' if native_fail else 'PASS')
    assert result.get('metric_acceptance', {}).get('status') == (
        'FAIL' if native_fail else 'NOT_MEASURED'), result
