"""SOURCE_ONLY row61 producer/reader/finalizer controls, not native qualification.

Native receipt and requirements methods are explicit doubles; on-disk native
receipts/authority files are invalid sentinels. Real handoff/log/DRC producers,
operators, worker, version collector and finalizer run. Existing unit-window
admission fixtures measure source behavior only. No DUT tool window runs.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as producer
import execution_backend_worker as worker
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as ll
import librelane_route as route
import phase3_one_shot_runner as runner
import step_output_collector as versions
import test_flow109_window_continuation as windows

REAL_RECEIPT = ll.validate_step_receipt
REAL_AUTHORITY = metrics._approved_authority
CORE = ['OpenROAD.GlobalRouting', 'OpenROAD.RepairAntennas', route.DRT, route.NVR, 'OpenROAD.FillInsertion']
KEY = 'vibeic__route__named_reroute__markers_after'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def definition(*, missing=None, extra=False):
    names = ['sig_a', 'sig_b'] + (['sig_extra'] if extra else [])
    rows = [f'- {name} ( PIN {name} ) ( leaf {name} )' + (
        ' + ROUTED Layer1 ( 0 0 ) ( 20 0 )' if name != missing else '') + ' ;' for name in names]
    return ('VERSION 5.8 ;\nDESIGN neutral_route ;\nUNITS DISTANCE MICRONS 1000 ;\n'
            + f'NETS {len(rows)} ;\n' + '\n'.join(rows) + '\nEND NETS\nEND DESIGN\n')


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    project = tmp_path / 'source-only-route'
    project.mkdir()
    def put(relative, body):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body) if isinstance(body, (dict, list)) else body)
        return path
    features = dict(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                        if p['name'] == 'Small digital IC without DFT'))
    context = flow109.execution_context(flow109.resolve_plan(features), 'D40', 'D40')
    context_path = put('context.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    model = put('inputs/model.lib', 'SOURCE_ONLY_MODEL_SENTINEL\n')
    tech = put('inputs/technology.lef', 'SOURCE_ONLY_TECH_SENTINEL\n')
    sdc = put('inputs/physical.sdc', 'SOURCE_ONLY_FULL_CONSTRAINT_SENTINEL\n')
    extra_sdc = put('inputs/extra.sdc', 'SOURCE_ONLY_ADDITIONAL_CONSTRAINT_SENTINEL\n')
    source = put('inputs/adopted-net-population.txt', 'SOURCE_ONLY_INDEPENDENT_NET_SET_SENTINEL\n')
    authority_path = put('requirements/base_27/routed_net_coverage.json', 'NOT_AN_APPROVED_DOCUMENT\n')
    required = [{'net': 'sig_a'}, {'net': 'sig_b'}]
    # API double only: the actual authority reader refuses the sentinel file.
    authority = {'status': 'APPROVED', 'scope': 'SOURCE_ONLY_REQUIREMENTS_METHOD_DOUBLE',
        'required_items': required, 'validated_absence': False,
        'path': str(authority_path.relative_to(project)), 'sha256': sha(authority_path),
        'source': {'path': str(source.relative_to(project)), 'sha256': sha(source)}}
    monkeypatch.setattr(metrics, '_approved_authority', lambda *a: (authority, {'required_items': required}))
    records, configs, states, folders = {}, {}, {}, {}
    chain_path = project / 'reports/phase3/execution-backend-21.json'
    params = {'step_id': '21', 'top': 'neutral_route', 'image_id': 'SOURCE_ONLY_NATIVE_METHOD_DOUBLE',
              'pdk_name': 'SOURCE_ONLY_PDK', 'pdk_root': str(project), 'stop_on_producer_failure': True}

    def build(*, missing=None, extra=False, count=0, raw_report=None):
        records.clear(); configs.clear(); states.clear(); folders.clear()
        netlist = put('inputs/pre_route.v', 'module neutral_route(input sig_a, input sig_b); endmodule\n')
        before_def = put('inputs/pre_route.def', definition())
        before_odb = put('inputs/pre_route.odb', 'SOURCE_ONLY_ODB_INPUT\n')
        before = put('inputs/pre_route_state.json', {'nl': str(netlist), 'def': str(before_def),
            'odb': str(before_odb), 'sdc': str(sdc), 'extra_constraints': str(extra_sdc), 'metrics': {}})
        previous = before
        refs = []
        put('phase3/librelane/execution-backend-21-config/flow_gates.json', {})
        drc_text = raw_report if raw_report is not None else ''.join(
            'violation type: Short\nsrcs: sig_a sig_b\nlayer: Layer1\nbbox = ( 0, 0 ) - ( 1, 1 )\n' for _ in range(count))
        for index, step in enumerate(CORE, 1):
            folder = project / 'phase3/librelane/execution-backend-21' / (f'{index:02d}-' + step.lower().replace('.', '-'))
            config = {'meta': {'step': step}, 'LIB': str(model), 'TECH_LEF': str(tech),
                      'PNR_SDC_FILE': str(sdc), 'STA_CORNERS': ['source_corner']}
            if step == route.NVR:
                config.update(VIBEIC_NVR_TCL=str(put('inputs/named-reroute.tcl', 'SOURCE_ONLY_TCL_SENTINEL\n')),
                    VIBEIC_NVR_DRC_REPORT=str(folders[route.DRT] / 'neutral_route.drc'))
                if getattr(request, 'param', None) == 'native_output':
                    config['VIBEIC_NVR_REPORT_PATH'] = str(project / 'phase3/librelane/execution-backend-21-config/nvr/execution-backend-21' / runner.ROUTER_DRC_REPORT_NAME)
            suffix = '@execution-backend-21' if step == route.NVR else ''
            cfg = put('phase3/librelane/execution-backend-21-config/' + step + suffix + '.json', config)
            views = {view: str(put(folder / ('neutral_route.' + ext), body)) for view, ext, body in [
                ('def', 'def', definition(missing=missing, extra=extra)),
                ('odb', 'odb', 'SOURCE_ONLY_ODB_' + step + '\n'),
                ('nl', 'v', netlist.read_text())]}
            native_metrics = {KEY: count} if step in [route.NVR, CORE[-1]] else {}
            state = put(folder / 'state_out.json', {**views, 'sdc': str(sdc),
                'extra_constraints': str(extra_sdc), 'metrics': native_metrics})
            text = ('[INFO DRT-0199] Number of violations = ' + str(count) + '.\n'
                    '[INFO DRT-0198] Complete detail routing.\n') if step == route.DRT else 'SOURCE_ONLY_NATIVE_EXECUTION_METHOD_DOUBLE\n'
            log = put(folder / 'invocation.log', text)
            pdk = put(folder / 'pdk_root.json', {'mounts_under_it': []})
            input_state = json.loads(previous.read_text())
            fp = {'image': params['image_id'], 'step': step, 'state': sha(previous), 'config': sha(cfg),
                'state_files': {str(p): sha(p) for p in ll._walk_paths({k: v for k, v in input_state.items() if k != 'metrics'})},
                'config_files': ll.config_file_hashes(config, [])}
            if step.startswith(ll.PLUGIN_STEP_PREFIX):
                fp['plugin'] = ll._plugin_digests(step)
            fp_path = put(folder / 'input_fingerprint.json', fp)
            extra_files = []
            if step == route.DRT:
                extra_files.append(put(folder / 'neutral_route.drc', drc_text))
            if step == route.NVR:
                # Native contract binds the marker count in state_out; this
                # raw report is corroborated with that count, never self-proven.
                put(folder / 'named_viol_after.drc', drc_text)
                if 'VIBEIC_NVR_REPORT_PATH' in config:
                    put(config['VIBEIC_NVR_REPORT_PATH'], drc_text)
            put(folder / 'vibeic_receipt.json', {'scope': 'SOURCE_ONLY_INVALID_NATIVE_RECEIPT'})
            records[str(folder)] = {'input': fp, 'sha256': {p.name: sha(p) for p in
                [state, log, pdk, fp_path, *map(Path, views.values()), *extra_files]}}
            refs.append({'step': step, 'state': str(state), 'sha256': sha(state),
                         'config': str(cfg.relative_to(project)), 'config_sha256': sha(cfg)})
            configs[step], states[step], folders[step] = cfg, state, folder
            previous = state
        put(chain_path, {'ordered_steps': CORE, 'initial_state': str(before), 'initial_sha256': sha(before), 'states': refs})
        return before

    before = build()
    monkeypatch.setattr(ll, 'validate_step_receipt', lambda folder, step: records[str(folder)])
    monkeypatch.setattr(producer, '_parameters', lambda *a: (runner, ll, None, ''))
    monkeypatch.setattr(route, 'chain_ids', lambda *a, **kw: list(CORE))
    monkeypatch.setattr(producer, '_state_chain', lambda *a, **kw: (ll, configs, folders))
    monkeypatch.setattr(runner, '_PROV_SINK', project)

    def run(complete=False):
        if complete:
            monkeypatch.setattr(producer, '_native_current_step_output_snapshot', lambda *a: {})
            monkeypatch.setattr(producer, '_native_current_step_producer', lambda *a: 'SOURCE_ONLY_DOUBLE')
            monkeypatch.setattr(producer, '_native_current_step_receipt', lambda *a: {'scope': 'SOURCE_ONLY_DOUBLE'})
            monkeypatch.setattr(producer, '_current_step_producer_authority', lambda *a, **kw: (True, '', 'PASS'))
            monkeypatch.setattr(producer, '_runner_context', lambda: SimpleNamespace(_DECLARED_SIGNOFF_GATES=[], _PRESTREAM_GATES=[]))
        result = (producer.produce if complete else producer.produce_pnr)(project, params)
        put('SOURCE_ONLY_ROUTE_OBSERVATION.json', result)
        return result

    def observe():
        owner = getattr(metrics, 'accept_d40', None)
        if owner is None:
            return {'row_id': 'D40', 'status': 'NOT_MEASURED', 'metric_status': 'NOT_MEASURED', 'obligations': []}
        return owner(project, json.loads(Path(__import__('os').environ[flow109.CONTEXT_ENV]).read_text()),
                     {'native_image': params['image_id'], 'verdict': 'PASS'})
    return SimpleNamespace(project=project, put=put, params=params, model=model, tech=tech, sdc=sdc,
        extra_sdc=extra_sdc, before=before, source=source, authority=authority, required=required,
        records=records, configs=configs, states=states, folders=folders, chain_path=chain_path,
        build=build, run=run, observe=observe)


def acceptance(result):
    return result.get('metric_acceptance', {'metric_status': 'NOT_MEASURED', 'status': 'NOT_MEASURED', 'obligations': [
        {'id': 'base_27.routed_net_coverage', 'status': 'NOT_MEASURED'},
        {'id': 'base_27.routing_drc_errors', 'status': 'NOT_MEASURED'}]})


def test_existing_producer_reads_every_net_and_native_drc_value(case):
    case.build(extra=True)
    result = case.run()
    observed = acceptance(result)
    assert observed['metric_status'] == 'PASS', result
    assert observed['status'] == observed['qualification'] == 'NOT_MEASURED'
    assert observed['obligations'][0]['observed_population'] == [
        {'net': name, 'routed': True} for name in ['sig_a', 'sig_b', 'sig_extra']]
    assert observed['obligations'][1]['measurement']['value'] == 0


def test_required_unrouted_net_fails_and_survives_completion_envelope(case):
    case.build(missing='sig_b')
    result = case.run(complete=True)
    assert result['verdict'] == 'FAIL', result
    assert result['canonical_receipts'][0]['metric_acceptance']['obligations'][0]['status'] == 'FAIL'


def test_positive_router_count_is_blocking_even_when_required_set_is_missing(case, monkeypatch):
    case.build(count=2)
    monkeypatch.setattr(metrics, '_approved_authority', REAL_AUTHORITY)
    result = case.run(complete=True)
    assert result['verdict'] == 'FAIL', result
    observed = acceptance(result)
    assert observed['obligations'][0]['status'] == 'NOT_MEASURED'
    assert observed['obligations'][1]['measurement']['value'] == 2
    assert result['canonical_receipts'][0]['metric_acceptance']['status'] == 'FAIL'


def test_retained_raw_native_marker_report_yields_actual_positive_count(case):
    from _hostpaths import repo_path
    p = repo_path('vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/drt_residual_types/routed_router_ns_metal.drc.rpt')
    raw = p.read_text()
    count = raw.count('violation type:')
    assert count > 0
    case.build(count=count, raw_report=raw)
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert acceptance(result)['obligations'][1]['measurement']['value'] == count


def test_missing_independent_required_set_cannot_self_certify_from_def(case, monkeypatch):
    monkeypatch.setattr(metrics, '_approved_authority', REAL_AUTHORITY)
    observed = acceptance(case.run())
    assert observed['metric_status'] == 'NOT_MEASURED'
    assert observed.get('obligations', [{}, {}])[1].get('status') == 'PASS'


@pytest.mark.parametrize('value', [None, '0', False, 0.0])
def test_absent_or_unsupported_native_metric_is_never_zero(case, value):
    for step in [route.NVR, CORE[-1]]:
        path = case.states[step]
        state = json.loads(path.read_text())
        if value is None:
            state['metrics'].pop(KEY)
        else:
            state['metrics'][KEY] = value
        path.write_text(json.dumps(state))
        case.records[str(path.parent)]['sha256']['state_out.json'] = sha(path)
    # Keep the native input chain current, so the metric type is the refusal.
    chain = json.loads(case.chain_path.read_text())
    for i, row in enumerate(chain['states']):
        path = Path(row['state']); row['sha256'] = sha(path)
        if i + 1 < len(chain['states']):
            folder = str(Path(chain['states'][i + 1]['state']).parent)
            case.records[folder]['input']['state'] = sha(path)
    case.chain_path.write_text(json.dumps(chain))
    observed = acceptance(case.run())
    assert observed['metric_status'] == 'NOT_MEASURED'
    assert observed.get('obligations', [{}, {}])[1].get('status') == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['model', 'config', 'state_population', 'config_population', 'source', 'receipt'])
def test_stale_or_partial_actual_input_population_refuses(case, monkeypatch, damage):
    if damage == 'model':
        case.model.write_text('CHANGED')
    elif damage == 'config':
        case.configs[CORE[0]].write_text('{}')
    elif damage == 'source':
        case.source.write_text('CHANGED')
    elif damage == 'receipt':
        monkeypatch.setattr(ll, 'validate_step_receipt', REAL_RECEIPT)
    elif damage == 'state_population':
        case.records[str(case.folders[CORE[0]])]['input']['state_files'].pop(str(case.extra_sdc))
    else:
        case.records[str(case.folders[CORE[0]])]['input']['config_files'].pop(str(case.tech))
    observed = acceptance(case.run())
    assert observed['metric_status'] == 'NOT_MEASURED'
    assert all(o['status'] != 'FAIL' for o in observed['obligations'])


@pytest.mark.parametrize('damage', ['log', 'native_log', 'report', 'native_report', 'receipt', 'unsupported_report'])
def test_current_report_and_log_identity_is_required(case, damage):
    case.run()
    pnr = case.project / 'phase3/stage3/pnr'
    if damage == 'log':
        (pnr / 'openroad.log').write_text('STALE_COUNT_ZERO')
    elif damage == 'native_log':
        (case.folders[route.DRT] / 'invocation.log').unlink()
    elif damage == 'report':
        (pnr / runner.ROUTER_DRC_REPORT_NAME).write_text('STALE_REPORT')
    elif damage == 'native_report':
        (case.folders[route.NVR] / 'named_viol_after.drc').unlink()
    elif damage == 'receipt':
        (pnr / runner.ROUTER_DRC_RECEIPT_NAME).unlink()
    else:
        (case.folders[route.NVR] / 'named_viol_after.drc').write_text('UNSUPPORTED_FORMAT')
        (pnr / runner.ROUTER_DRC_REPORT_NAME).write_text('UNSUPPORTED_FORMAT')
    observed = case.observe()
    assert observed['metric_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['duplicate', 'truncated', 'declared_count'])
def test_incomplete_def_population_is_unmeasured(case, damage):
    text = definition()
    if damage == 'duplicate':
        text = text.replace('sig_b', 'sig_a')
    elif damage == 'truncated':
        text = text.replace('END NETS', '')
    else:
        text = text.replace('NETS 2', 'NETS 9')
    for step in CORE:
        path = case.folders[step] / 'neutral_route.def'
        path.write_text(text)
        case.records[str(case.folders[step])]['sha256'][path.name] = sha(path)
    for step in CORE[1:]:
        fp = case.records[str(case.folders[step])]['input']
        for path in list(fp['state_files']):
            fp['state_files'][path] = sha(Path(path))
    observed = acceptance(case.run())
    assert observed['metric_status'] == 'NOT_MEASURED'
    assert observed.get('obligations', [{}, {}])[0].get('status') == 'NOT_MEASURED'


@pytest.fixture
def scene(case, monkeypatch):
    project = case.project
    features = json.loads((project / 'context.json').read_text())['features']
    monkeypatch.setattr(windows, '_profile', lambda: copy.deepcopy(features))
    plan, context, _ = windows._window_fixture(project, monkeypatch, 'D40', 'D40')
    request = case.put('reports/flow109/requests/' + context['context_sha256'] + '.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(project, context)))
    native = context['native_step_id']
    for spec in worker.ROWS[native]['canonical_row']['required_outputs']:
        if not any(project.glob(spec)):
            assert '*' not in spec and ' OR ' not in spec
            case.put(spec, 'SOURCE_ONLY_GATE_METHOD_DOUBLE')
    inputs = {str(request.relative_to(project)): sha(request)}
    attempt = versions.begin_step(project, native, inputs=inputs)
    produced = case.run(complete=True)
    # Claimed nested PASS is a fixture, not current owner authority. It lets
    # the baseline's existing worker/version path reach the same finalizer.
    if 'metric_acceptance' not in produced:
        claimed = {'row_id': 'D40', 'status': 'PASS', 'metric_status': 'PASS', 'qualification': 'PASS',
            'scope': 'SOURCE_ONLY_PRIOR_CLAIM_FIXTURE_NOT_NATIVE_EVIDENCE', 'obligations': [{
            'id': 'base_27.routed_net_coverage', 'status': 'PASS', 'measurement': {
                'identity': {'configuration': {'context_sha256': context['context_sha256']}}}}]}
        produced['metric_acceptance'] = claimed
        produced['canonical_receipts'][0]['metric_acceptance'] = claimed
    monkeypatch.setattr(worker, '_current_step_producer_authority', lambda *a, **kw: (True, 'SOURCE_ONLY', 'PASS'))
    monkeypatch.setattr(worker, 'evaluate', lambda *a: {'status': 'PASS', 'step': {'id': native, 'status': 'PASS'}, 'ledger': []})
    backend = worker.execute_current_step(project, step_id=native, producer=produced)
    assert backend['verdict'] == 'PASS', backend
    receipt = case.put('reports/phase3/default_steps/' + native + '/backend_result.json', backend)
    version = versions.finish_step(project, attempt, verdict='PASS', result=backend, canonical_pass=True)
    selected = {r['id'] for r in plan['rows']}
    dependencies = (set(context['resolved_row']['acceptance_deps']) |
                    {d['step'] for d in context['resolved_row']['data_deps']}) & selected
    for dep in dependencies:
        original = flow109.execution_context(plan, dep, dep)
        case.put('reports/flow109/requests/' + original['context_sha256'] + '.json', original)
        case.put('reports/flow109/default_rows/' + dep + '.json', {'step_id': dep,
            'default_row_status': 'PASS', 'completed': True, 'context_sha256': original['context_sha256'],
            'scope': 'SOURCE_ONLY_DEPENDENCY_UNIT_FIXTURE'})
    report = {'bounded': True, 'steps': [{'extras': {'canonical_steps': [{
        'status': 'PASS', 'detail': 'SOURCE_ONLY_WORKER_METHODS',
        'extras': {'step_id': native, 'output_version': version['folder']}}]}}]}
    def consume():
        result = flow109.finish_native_window(project, report)
        case.put('SOURCE_ONLY_ROUTE_COMPLETION.json', result)
        return result
    return SimpleNamespace(case=case, project=project, context=context, plan=plan,
        receipt=receipt, consume=consume, dependencies=dependencies, report=report)


def test_normal_finalizer_reuses_valid_admission_and_fresh_route_values(scene):
    result = scene.consume()
    assert result['default_row_status'] == 'PASS', result
    assert result['components'][0]['metric_acceptance']['metric_status'] == 'PASS'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False


def test_normal_finalizer_missing_qualification_never_promotes_nested_pass(scene):
    (scene.project / 'qualifications.json').unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['components'][0].get('metric_acceptance', {}).get('metric_status') == 'PASS'


@pytest.mark.parametrize('late_ni', ['qualification', 'dependency'])
def test_normal_finalizer_bound_coverage_fail_survives_late_ni(scene, late_ni):
    scene.case.required.append({'net': 'independent_missing_net'})
    if late_ni == 'qualification':
        (scene.project / 'qualifications.json').unlink()
    else:
        dep = sorted(scene.dependencies)[0]
        (scene.project / 'reports/flow109/default_rows' / (dep + '.json')).unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'FAIL', result
    assert result['components'][0]['metric_acceptance']['obligations'][0]['status'] == 'FAIL'


@pytest.mark.parametrize('damage', ['receipt', 'version', 'dependency'])
def test_normal_finalizer_foreign_or_stale_prior_pass_is_ni(scene, damage):
    if damage == 'receipt':
        body = json.loads(scene.receipt.read_text()); body['source_sha'] = 'FOREIGN'
        scene.receipt.write_text(json.dumps(body))
    elif damage == 'version':
        for p in versions._versions_root(scene.project).glob('**/outputs.json'):
            p.unlink()
    else:
        dep = sorted(scene.dependencies)[0]
        (scene.project / 'reports/flow109/default_rows' / (dep + '.json')).unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert 'reason' in result['components'][0]


def test_real_strict_timing_derived_config_reaches_complete_route_readback(case, monkeypatch):
    import sys
    stage = 'OpenROAD.ResizerTimingPostGRT'
    monkeypatch.setattr(sys.modules[__name__], 'CORE', [CORE[0], stage, *CORE[1:]])
    case.build()
    resolved = route.bind_strict_timing_corners(case.configs)
    case.configs[stage] = resolved[stage]
    record = case.records[str(case.folders[stage])]
    record['input']['config'] = sha(resolved[stage])
    fp = case.folders[stage] / 'input_fingerprint.json'
    fp.write_text(json.dumps(record['input']))
    record['sha256'][fp.name] = sha(fp)
    result = case.run(complete=True)
    observed = acceptance(result)
    assert observed['metric_status'] == 'PASS', result
    chain = json.loads(case.chain_path.read_text())
    selected = next(r for r in chain['states'] if r['step'] == stage)
    assert selected['config'].endswith('@strict-native.json')
    assert selected['config_sha256'] == record['input']['config']
    drc_identity = observed['obligations'][1]['measurement']['identity']
    assert 'phase3/stage3/pnr/routed_router.drc.rpt' in drc_identity['consumed_inputs']
    assert result['canonical_receipts'][0]['metric_acceptance']['metric_status'] == 'PASS'


@pytest.mark.parametrize('damage', ['path', 'hash', 'missing_config'])
def test_actual_derived_config_reference_cannot_be_substituted(case, damage):
    case.run()
    chain = json.loads(case.chain_path.read_text())
    selected = chain['states'][0]
    if damage == 'path':
        copied = case.put('other-config.json', case.configs[CORE[0]].read_text())
        selected['config'] = str(copied.relative_to(case.project))
    elif damage == 'hash':
        selected['config_sha256'] = '0' * 64
    else:
        selected.pop('config')
    case.chain_path.write_text(json.dumps(chain))
    assert case.observe()['metric_status'] == 'NOT_MEASURED'


def working_output(case, retained_old=False):
    folder = case.folders[route.NVR]
    cfg = case.configs[route.NVR]
    body = json.loads(cfg.read_text())
    target = case.project / 'phase3/librelane/execution-backend-21-config/nvr/execution-backend-21' / runner.ROUTER_DRC_REPORT_NAME
    body['VIBEIC_NVR_REPORT_PATH'] = str(target)
    cfg.write_text(json.dumps(body))
    target.parent.mkdir(parents=True, exist_ok=True)
    if retained_old:
        target.write_text('PRIOR_WORKING_OUTPUT_REPLACED_BY_NATIVE_COPY\n')
    record = case.records[str(folder)]
    record['input']['config'] = sha(cfg)
    record['input']['config_files'] = ll.config_file_hashes(body, [])
    fp = folder / 'input_fingerprint.json'
    fp.write_text(json.dumps(record['input']))
    record['sha256'][fp.name] = sha(fp)
    # The real native plugin copies its bound DRT report to this output path
    # before repair, then publishes the completed report and marker metric.
    target.write_bytes((folder / 'named_viol_after.drc').read_bytes())
    return target


@pytest.mark.parametrize('retained_old', [False, True])
def test_native_nvr_working_report_is_output_not_a_stale_input(case, retained_old):
    working_output(case, retained_old)
    result = case.run(complete=True)
    assert acceptance(result)['metric_status'] == 'PASS', result
    assert result['canonical_receipts'][0]['metric_acceptance']['metric_status'] == 'PASS'


@pytest.mark.parametrize('damage', ['foreign_path', 'changed_output', 'missing_constraint_input'])
def test_working_output_classification_keeps_input_and_report_guards(case, damage):
    target = working_output(case)
    if damage == 'missing_constraint_input':
        case.records[str(case.folders[route.NVR])]['input']['config_files'].pop(str(case.sdc))
        assert acceptance(case.run())['metric_status'] == 'NOT_MEASURED'
        return
    case.run()
    if damage == 'changed_output':
        target.write_text('FOREIGN_OUTPUT')
    else:
        cfg = case.configs[route.NVR]
        body = json.loads(cfg.read_text())
        body['VIBEIC_NVR_REPORT_PATH'] = str(case.put('other-working-output.drc', ''))
        cfg.write_text(json.dumps(body))
        record = case.records[str(case.folders[route.NVR])]
        record['input']['config'] = sha(cfg)
        record['input']['config_files'] = ll.config_file_hashes(body, [])
        chain = json.loads(case.chain_path.read_text())
        ref = next(r for r in chain['states'] if r['step'] == route.NVR)
        ref['config_sha256'] = sha(cfg)
        case.chain_path.write_text(json.dumps(chain))
    assert case.observe()['metric_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('case', ['native_output'], indirect=True)
def test_normal_finalizer_accounts_for_actual_native_working_output(scene):
    result = scene.consume()
    assert result['default_row_status'] == 'PASS', result
    observed = result['components'][0]['metric_acceptance']
    assert observed['metric_status'] == observed['qualification'] == 'PASS'
    report = 'phase3/librelane/execution-backend-21-config/nvr/execution-backend-21/' + runner.ROUTER_DRC_REPORT_NAME
    assert report in observed['readset']
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
