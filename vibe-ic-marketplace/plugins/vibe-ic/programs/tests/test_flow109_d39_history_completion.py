"""SOURCE_ONLY history/completion controls, never runtime qualification.

Native receipt/bounds methods are explicit doubles. Reuse the existing window
unit fixture for admission; its unit-window artifacts are not platform evidence.
The real producer entry, history parser/reader, worker/version and finalizer run.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as producer
import execution_backend_worker as worker
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import librelane_contract as ll
import step_output_collector as versions
import test_flow109_d39_metric_binding as old
import test_flow109_window_continuation as windows
from test_flow109_d39_metric_binding import case as original_case

REAL_SPLIT = producer._cts_split
HEADER = 'Iter | Removed | Resized | Inserted | Cloned | Pin | Area | WNS | TNS'
HOLD = 'Iteration | Resized | Buffers | Cloned Gates | Area | WNS | TNS | Endpoint'


def trace(stagnant=1):
    lines = [HEADER, '0A | 0 | 0 | 0 | 0 | 0 | 0 | -1 | -1']
    for number in range(1, stagnant + 2):
        lines.append(f'{number}A | 0 | 1 | 0 | 0 | 0 | 0 | -1 | -1')
    lines.extend(['final | 0 | 1 | 0 | 0 | 0 | 0 | -1 | -1', HOLD,
        '[DEBUG RSZ repair_hold] pass 1 hold slack -0.2 setup slack 0.3',
        '[DEBUG RSZ repair_hold] inserted 2',
        '[DEBUG RSZ repair_hold] pass 4 hold slack -0.1 setup slack 0.2',
        '[DEBUG RSZ repair_hold] inserted 0',
        'final | 0 | 2 | 0 | 0 | -0.1 | -1 | pin'])
    return '\n'.join(lines) + '\n'


def parse(text):
    reader = getattr(producer, '_d39_parse_repair_history', None)
    return reader(text) if reader else {'status': 'NOT_MEASURED'}


@pytest.fixture
def case(original_case, monkeypatch):
    c = original_case
    timing_body = old.bounds_double(c, monkeypatch)
    timing_reader = metrics._approved_document
    relative = 'requirements/base_26/repair_stagnation_iterations.json'
    path = c.put(relative, 'SOURCE_ONLY_BOUNDS_METHOD_DOUBLE_NOT_AUTHORITY\n')
    source = c.put('inputs/history-requirements.txt', 'SOURCE_ONLY_HISTORY_REQUIREMENT\n')
    auth = {'status': 'SOURCE_ONLY_METHOD_DOUBLE', 'path': relative, 'sha256': old.sha(path),
        'source': {'path': str(source.relative_to(c.project)), 'sha256': old.sha(source)}}
    history_body = {'limits': {'max': 1}, 'units': 'count'}

    def bounds(project, name, **kwargs):
        if name == relative:
            return auth, history_body
        return timing_reader(project, name, **kwargs)

    monkeypatch.setattr(metrics, '_approved_document', bounds)
    c.bounds, c.timing_body, c.history_body = bounds, timing_body, history_body
    folder = c.states[0].parent
    log = folder / 'invocation.log'
    before = c.project / json.loads((c.project / 'reports/phase3/pnr/hold_area.json').read_text())['sources']['before']
    c.records[str(folder)]['input']['openroad_init'] = ['set_debug_level RSZ repair_hold 1']

    def capture(text=None):
        log.write_text(trace() if text is None else text)
        c.records[str(folder)]['sha256']['invocation.log'] = old.sha(log)
        capture_method = getattr(producer, '_d39_capture_repair_history', None)
        if capture_method:
            reference = capture_method(c.project, folder, before, c.configs[0])
        else:
            # Baseline receives the same caller data. It has no history consumer.
            p = c.put('reports/phase3/pnr/post_cts_repair_history.json', {'scope': 'SOURCE_ONLY_INPUT', 'sources': {},
                'observation': {'status': 'MEASURED', 'value': 1, 'unit': 'count'}})
            reference = {'path': str(p.relative_to(c.project)), 'sha256': old.sha(p)}
        c.handoff['repair_history'] = reference
        c.handoff_path.write_text(json.dumps(c.handoff))
        return c.project / reference['path']

    c.capture, c.log, c.before = capture, log, before
    c.history_path = capture()
    return c


def metric(c):
    return c.run()['metric_acceptance']


def test_dense_native_move_history_uses_counters_and_count_unit():
    observed = parse(trace(2))
    assert observed['status'] == 'MEASURED', observed
    assert (observed['value'], observed['unit']) == (2, 'count')
    assert observed['phases']['hold']['rows'][1]['native_pass'] == 4


def test_explicit_native_no_violations_is_zero_history():
    observed = parse('[INFO RSZ-0098] No setup violations found\n[INFO RSZ-0033] No hold violations found.\n')
    assert observed['status'] == 'MEASURED', observed
    assert observed['value'] == 0


@pytest.mark.parametrize('damage', ['sparse', 'truncated', 'continued_after_stop', 'changed_final'])
def test_incomplete_native_history_never_becomes_zero(damage):
    text = trace()
    if damage == 'sparse':
        text = text.replace('1A | 0 | 1 | 0 | 0 | 0 | 0 | -1 | -1\n', '')
    elif damage == 'truncated':
        text = text.rsplit('final', 1)[0]
    elif damage == 'changed_final':
        text = text.replace('final | 0 | 1', 'final | 0 | 9')
    else:
        text = text.replace('final | 0 | 2', '[DEBUG RSZ repair_hold] pass 5 hold slack -0.1 setup slack 0.2\n[DEBUG RSZ repair_hold] inserted 1\nfinal | 0 | 2')
    assert parse(text)['status'] == 'NOT_MEASURED'


def test_retained_real_truncated_resizer_log_is_unmeasured():
    path = Path(__file__).parent / 'fixtures/librelane_import/8HD-4/runs/cmp3/37-openroad-resizertimingpostcts/openroad-resizertimingpostcts.log'
    # Controls may be mounted apart; fixture stays in the exact read-only source.
    if not path.exists():
        path = Path('/src/vibe-ic-marketplace/plugins/vibe-ic/programs/tests') / path.relative_to(Path(__file__).parent)
    assert parse(path.read_text())['status'] == 'NOT_MEASURED'


def test_both_actual_obligations_pass_metrics_but_stock_qualification_is_ni(case):
    result = metric(case)
    assert [o['status'] for o in result['obligations']] == ['PASS', 'PASS'], result
    assert result['metric_status'] == 'PASS'
    assert result['status'] == result['qualification'] == 'NOT_MEASURED'


def test_actual_history_over_bound_fails_producer_without_timing_offset(case):
    case.capture(trace(2))
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert result['metric_acceptance']['obligations'][0]['status'] == 'PASS'
    assert result['metric_acceptance']['obligations'][1]['measurement']['value'] == 2


@pytest.mark.parametrize('damage', ['missing', 'log_changed', 'foreign', 'forged_value', 'units'])
def test_history_identity_and_units_refuse(case, damage):
    if damage == 'missing':
        case.history_path.unlink()
    elif damage == 'log_changed':
        case.log.write_text('CHANGED')
    elif damage == 'units':
        case.history_body['units'] = 'ns'
    else:
        body = json.loads(case.history_path.read_text())
        if damage == 'foreign':
            body['sources'] = {}
        else:
            body['observation']['value'] = 0
        case.history_path.write_text(json.dumps(body))
        case.handoff['repair_history']['sha256'] = old.sha(case.history_path)
        case.handoff_path.write_text(json.dumps(case.handoff))
    assert metric(case)['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('first_fail', ['timing', 'history'])
def test_bound_fail_survives_other_obligation_late_missing_bounds(case, monkeypatch, first_fail):
    if first_fail == 'history':
        case.capture(trace(2))
        missing = 'post_cts_setup_hold_drv'
    else:
        state = json.loads(case.states[-1].read_text())
        state['metrics'][old.DRV[0]] = 1
        case.states[-1].write_text(json.dumps(state))
        case.update_state(len(case.states) - 1)
        missing = 'repair_stagnation_iterations'
    def bounds(project, relative, **kwargs):
        if missing in relative:
            raise metrics.MetricRefusal('SOURCE_ONLY_MISSING_BOUNDS', relative)
        return case.bounds(project, relative, **kwargs)
    monkeypatch.setattr(metrics, '_approved_document', bounds)
    assert case.run()['verdict'] == 'FAIL'


def test_existing_cts_split_attaches_current_history_and_telemetry(case, monkeypatch):
    import librelane_cts_hold as ch
    scene = case.put('inputs/physical.sdc', 'SOURCE_ONLY_SCENE')
    monkeypatch.setattr(ch, 'signoff_scene_sdc', lambda *a: scene)
    monkeypatch.setattr(producer, '_current_physical_sdc', lambda *a: scene)
    monkeypatch.setattr(producer, '_cts_selected_predecessor', lambda *a: 'post_cts.def')
    monkeypatch.setattr(producer, '_logs', lambda *a: None)
    monkeypatch.setattr(producer, '_handoff', lambda *a: {'views': {
        k.removeprefix('post_hold_'): {**v, 'dest': str(case.project / v['dest'])}
        for k, v in case.handoff['views'].items()}})
    case.put('reports/phase3/librelane_cts_handoff.json', {'views': {}, 'chain': {}})
    template = case.put('phase3/librelane/execution-backend-20-config/OpenROAD.STAMidPNR.json',
        {'STA_CORNERS': case.corners})
    monkeypatch.setattr(ll, 'resolve_step_configs', lambda *a, **kw: {
        'OpenROAD.ResizerTimingPostCTS': case.configs[0], 'OpenROAD.STAMidPNR': template})
    monkeypatch.setattr(ll, 'derive_step_config', lambda src, dst, updates: dst)
    calls = []
    def run_chain(*args, **kwargs):
        calls.append(kwargs)
        return [s.parent for s in case.states]
    monkeypatch.setattr(ll, 'run_chain', run_chain)
    runner = SimpleNamespace(_resolved_cell_policy=lambda configs, *a, **kw: (configs, []))
    REAL_SPLIT(case.project, {'step_id': '20', 'image_id': 'SOURCE_ONLY_DOUBLE',
        'pdk_root': str(case.project), 'state_in': str(case.before)}, runner, ll,
        SimpleNamespace(name='SOURCE_ONLY_PDK'), {})
    handoff = json.loads(case.handoff_path.read_text())
    assert 'repair_history' in handoff, handoff
    assert calls[0]['openroad_init'] == ['set_debug_level RSZ repair_hold 1']
    assert json.loads((case.project / handoff['repair_history']['path']).read_text())['observation']['value'] == 1


@pytest.fixture
def scene(case, monkeypatch):
    project = case.project
    features = json.loads((project / 'context.json').read_text())['features']
    monkeypatch.setattr(windows, '_profile', lambda: copy.deepcopy(features))
    plan, context, _ = windows._window_fixture(project, monkeypatch, 'D39', 'D39')
    request = case.put('reports/flow109/requests/' + context['context_sha256'] + '.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(project, context)))
    native = context['native_step_id']
    for spec in worker.ROWS[native]['canonical_row']['required_outputs']:
        if not any(project.glob(spec)):
            assert '*' not in spec and ' OR ' not in spec
            case.put(spec, 'SOURCE_ONLY_GATE_METHOD_DOUBLE')
    inputs = {str(request.relative_to(project)): old.sha(request)}
    attempt = versions.begin_step(project, native, inputs=inputs)
    actual_owner = metrics.accept_d39
    def prior(*args):
        result = actual_owner(*args)
        # Deliberately claimed prior PASS is never current owner authority.
        result.update(status='PASS', metric_status='PASS', qualification='PASS', delivery_blocked=False,
                      scope='SOURCE_ONLY_PRIOR_NESTED_PASS_METHOD_DOUBLE')
        return result
    monkeypatch.setattr(metrics, 'accept_d39', prior)
    produced = case.run(complete=True)
    monkeypatch.setattr(metrics, 'accept_d39', actual_owner)
    monkeypatch.setattr(worker, '_current_step_producer_authority', lambda *a, **kw: (True, 'SOURCE_ONLY', 'PASS'))
    monkeypatch.setattr(worker, 'evaluate', lambda *a: {'status': 'PASS', 'step': {'id': native, 'status': 'PASS'}, 'ledger': []})
    backend = worker.execute_current_step(project, step_id=native, producer=produced)
    assert backend['verdict'] == 'PASS', backend
    receipt = case.put('reports/phase3/default_steps/' + native + '/backend_result.json', backend)
    version = versions.finish_step(project, attempt, verdict=backend['verdict'], result=backend, canonical_pass=True)
    selected = {r['id'] for r in plan['rows']}
    dependencies = (set(context['resolved_row']['acceptance_deps']) |
        {d['step'] for d in context['resolved_row']['data_deps']}) & selected
    for dep in dependencies:
        original = flow109.execution_context(plan, dep, dep)
        case.put('reports/flow109/requests/' + original['context_sha256'] + '.json', original)
        case.put('reports/flow109/default_rows/' + dep + '.json', {
            'step_id': dep, 'default_row_status': 'PASS', 'completed': True,
            'context_sha256': original['context_sha256'], 'scope': 'SOURCE_ONLY_DEPENDENCY_FIXTURE'})
    report = {'bounded': True, 'steps': [{'extras': {'canonical_steps': [{
        'status': 'PASS', 'detail': 'SOURCE_ONLY_WORKER_METHODS',
        'extras': {'step_id': native, 'output_version': version['folder']}}]}}]}
    def consume():
        result = flow109.finish_native_window(project, report)
        case.put('SOURCE_ONLY_HISTORY_COMPLETION.json', result)
        return result
    return SimpleNamespace(case=case, project=project, context=context, plan=plan,
        receipt=receipt, consume=consume, dependencies=dependencies)


def test_existing_finalizer_reuses_valid_admission_and_fresh_actual_values(scene):
    result = scene.consume()
    assert result['default_row_status'] == 'PASS', result
    assert result['components'][0]['metric_acceptance']['obligations'][1]['measurement']['value'] == 1
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False


def test_existing_finalizer_stock_missing_qualification_remains_ni(scene):
    (scene.project / 'qualifications.json').unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['components'][0]['metric_acceptance']['metric_status'] == 'PASS'


@pytest.mark.parametrize('late_ni', ['missing_qualification', 'missing_dependency', 'missing_version'])
def test_existing_finalizer_fresh_history_fail_survives_late_ni(scene, late_ni):
    scene.case.history_body['limits']['max'] = 0
    if late_ni == 'missing_qualification':
        (scene.project / 'qualifications.json').unlink()
    elif late_ni == 'missing_dependency':
        dep = sorted(scene.dependencies)[0]
        (scene.project / 'reports/flow109/default_rows' / (dep + '.json')).unlink()
    else:
        for p in versions._versions_root(scene.project).glob('**/outputs.json'):
            p.unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'FAIL', result
    assert result['components'][0]['metric_acceptance']['obligations'][1]['status'] == 'FAIL'


@pytest.mark.parametrize('damage', ['forged_receipt', 'foreign_context', 'missing_dependency'])
def test_existing_finalizer_rejects_stale_or_foreign_prior_pass(scene, damage, monkeypatch):
    if damage == 'forged_receipt':
        body = json.loads(scene.receipt.read_text())
        body['source_sha'] = 'FORGED'
        scene.receipt.write_text(json.dumps(body))
    elif damage == 'missing_dependency':
        dep = sorted(scene.dependencies)[0]
        (scene.project / 'reports/flow109/default_rows' / (dep + '.json')).unlink()
    else:
        other = scene.case.put('other-qualification.json', (scene.project / 'qualifications.json').read_text())
        context = flow109.execution_context(scene.plan, 'D39', 'D39',
            runtime_tool_uses=scene.context['runtime_tool_uses'], qualification_registry=other.name)
        path = scene.case.put('reports/flow109/requests/' + context['context_sha256'] + '.json', context)
        monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
        monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(scene.project, context)))
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert 'reason' in result['components'][0]


def test_history_copy_at_foreign_path_cannot_replace_native_producer_output(case):
    copied = case.put('reports/other-repair-history.json', case.history_path.read_text())
    case.handoff['repair_history'] = {'path': str(copied.relative_to(case.project)), 'sha256': old.sha(copied)}
    case.handoff_path.write_text(json.dumps(case.handoff))
    assert metric(case)['metric_status'] == 'NOT_MEASURED'
