"""SOURCE_ONLY spare-reader controls; native receipt validator is a method double.

No native execution, approved requirement or qualification is authored.
The real coverage/DEF parser, metric consumer and producer branch execute.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109
import execution_backend_producers as producer
import flow109_metric_acceptance as metrics
import librelane_contract as ll

REAL_RECEIPT_READER = ll.validate_step_receipt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / 'source-only-spares'
    project.mkdir()
    def put(path, value):
        path = project / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value)
        return path
    features = dict(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                         if p['name'] == 'Small digital IC without DFT'))
    features['requires_spares'] = True
    context = flow109.execution_context(flow109.resolve_plan(features), 'D37', 'D37')
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(put('context.json', context)))
    step = 'Vibeic.InsertSpareCells'
    folder = project / 'native-double'
    initial = put('input/state.json', {'source_only': True})
    config = put('phase3/librelane/execution-backend-18-config/' + step + '.json', {'meta': {'step': step}})
    model = put('input/model.lef', 'SOURCE_ONLY_MODEL_SENTINEL\n')
    odb = put(folder / 'post_spare.odb', 'SOURCE_ONLY_ODB_SENTINEL\n')
    definition = 'VERSION 5.8 ;\nDESIGN neutral ;\nCOMPONENTS 4 ;\n- s0 neutral_master + FIXED ( 0 0 ) N ;\n- s1 neutral_master + FIXED ( 100 100 ) N ;\n- d0 neutral_tielo + PLACED ( 0 0 ) N ;\n- d1 neutral_tielo + PLACED ( 100 100 ) N ;\nEND COMPONENTS\nNETS 2 ;\n- low0 ( s0 A ) ( s0 CLK ) ( d0 Y ) ;\n- low1 ( s1 A ) ( s1 CLK ) ( d1 Y ) ;\nEND NETS\nEND DESIGN\n'
    definition = put(folder / 'post_spare.def', definition)
    state = put(folder / 'state_out.json', {'def': str(definition), 'odb': str(odb)})
    inputs = [{'inst': 's'+str(i), 'pin': pin, 'use': 'CLOCK' if pin == 'CLK' else 'SIGNAL',
               'net': 'low'+str(i)} for i in range(2) for pin in ['A', 'CLK']]
    plan = {'count': 2, 'placed_cells_est': 100, 'actual_density': 0.02, 'tied_off': True,
            'instances': [{'name': 's0', 'cell': 'neutral_master', 'llx': 0, 'lly': 0},
                          {'name': 's1', 'cell': 'neutral_master', 'llx': 100, 'lly': 100}],
            'tie_off': {'inputs': inputs, 'measured': True},
            'measured': {'inserted': 2, 'placed_cells': 100, 'tieoff_inputs': inputs,
                         'pg_unconnected': 0}}
    native_plan = put(folder / 'spare_cells.json', plan)
    sentinel = put(folder / 'vibeic_receipt.json', 'SOURCE_ONLY_INVALID_NATIVE_RECEIPT\n')
    pdk = put(folder / 'pdk_root.json', {'mounts_under_it': []})
    receipt = {'input': {'image': 'SOURCE_ONLY_DOUBLE', 'step': step, 'state': sha(initial),
        'config': sha(config), 'state_files': {str(initial): sha(initial)},
        'config_files': {str(model): sha(model)}, 'plugin': ll._plugin_digests(step)},
        'sha256': {'state_out.json': sha(state), 'spare_cells.json': sha(native_plan),
                   'post_spare.def': sha(definition), 'post_spare.odb': sha(odb), 'pdk_root.json': sha(pdk)}}
    put('reports/phase3/execution-backend-18.json', {'ordered_steps': [step],
        'initial_state': str(initial), 'initial_sha256': sha(initial),
        'states': [{'step': step, 'state': str(state), 'sha256': sha(state)}]})
    handoff = {'state': str(state), 'state_sha256': sha(state), 'views': {}}
    for view, source, name in [('def', definition, 'post_spare.def'), ('odb', odb, 'post_spare.odb')]:
        dest = put('phase3/stage3/pnr/' + name, source.read_text())
        handoff['views'][view] = {'source': str(source), 'source_sha256': sha(source),
                                'dest': str(dest), 'dest_sha256': sha(dest)}
    put('reports/phase3/librelane_spare_handoff.json', handoff)
    put('phase3/stage3/pnr/spare_cells.json', plan)
    monkeypatch.setattr(ll, 'validate_step_receipt', lambda *a: receipt)
    runner = SimpleNamespace(_emit_spare_cell_coverage=lambda *a: None)
    monkeypatch.setattr(producer, '_parameters', lambda *a: (runner, ll, None, None))
    monkeypatch.setattr(producer, '_predecessor_state', lambda *a: initial)
    monkeypatch.setattr(producer, '_state_chain', lambda *a, **k: (ll, {step: config}, {step: folder}))
    monkeypatch.setattr(producer, '_handoff', lambda *a, **k: handoff)
    monkeypatch.setattr(producer, '_logs', lambda *a, **k: None)

    def update_plan():
        native_plan.write_text(json.dumps(plan))
        receipt['sha256']['spare_cells.json'] = sha(native_plan)
    def run():
        result = producer.produce_pnr(project, {'step_id': '18', 'top': 'neutral', 'image_id': 'SOURCE_ONLY_DOUBLE'})
        put('SOURCE_ONLY_OBSERVATION.json', {'scope': 'SOURCE_ONLY_NOT_IC_EVIDENCE', 'result': result})
        return result
    def complete():
        monkeypatch.setattr(producer, '_native_current_step_output_snapshot', lambda *a: {})
        monkeypatch.setattr(producer, '_native_current_step_producer', lambda *a: 'SOURCE_ONLY_DOUBLE')
        monkeypatch.setattr(producer, '_native_current_step_receipt', lambda *a: {'scope': 'SOURCE_ONLY_DOUBLE'})
        monkeypatch.setattr(producer, '_current_step_producer_authority', lambda *a, **k: (True, 'SOURCE_ONLY_DOUBLE', 'PASS'))
        monkeypatch.setattr(producer, '_runner_context', lambda: SimpleNamespace(_DECLARED_SIGNOFF_GATES=[], _PRESTREAM_GATES=[]))
        result = producer.produce(project, {'step_id': '18', 'top': 'neutral',
            'image_id': 'SOURCE_ONLY_DOUBLE', 'stop_on_producer_failure': True})
        put('SOURCE_ONLY_OBSERVATION.json', {'scope': 'SOURCE_ONLY_NOT_IC_EVIDENCE', 'result': result})
        return result
    return SimpleNamespace(project=project, plan=plan, run=run, update_plan=update_plan,
        receipt=receipt, model=model, definition=definition, handoff=handoff, put=put, complete=complete)


def bounds_double(case, monkeypatch, *, density=0.02):
    source = case.put('input/requirements-sentinel.txt', 'SOURCE_ONLY_REQUIREMENTS_METHOD_DOUBLE\n')
    relative = 'requirements/base_24/required_spare_distribution.json'
    sentinel = case.put(relative, 'NOT_AN_APPROVED_DOCUMENT\n')
    auth = {'status': 'SOURCE_ONLY_METHOD_DOUBLE', 'path': relative, 'sha256': sha(sentinel),
            'source': {'path': str(source.relative_to(case.project)), 'sha256': sha(source)}}
    body = {'limits': {'actual_density': {'min': density}, 'distribution_fraction': {'min': 0.5}},
            'units': {'actual_density': 'ratio', 'distribution_fraction': 'ratio'}}
    monkeypatch.setattr(metrics, '_approved_document', lambda *a, **k: (auth, body))


def test_native_spares_reuse_existing_coverage_and_def_consumers(case, monkeypatch):
    bounds_double(case, monkeypatch)
    result = case.run()
    assert result['verdict'] == 'PASS'
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('metric_status') == 'PASS', result
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'


def test_missing_distribution_authority_is_unmeasured(case):
    result = case.run()
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('metric_status') == 'NOT_MEASURED', result
    assert accepted['obligations'][0]['status'] == 'PASS'


@pytest.mark.parametrize('bad', [False, True])
def test_d37_real_completion_envelope_retains_metrics(case, monkeypatch, bad):
    bounds_double(case, monkeypatch, density=0.03 if bad else 0.02)
    result = case.complete()
    assert result['verdict'] == ('FAIL' if bad else 'PASS'), result
    assert result['canonical_receipts'][0].get('metric_acceptance') == result.get('metric_acceptance') != None
    assert result['canonical_receipts'][0]['metric_acceptance']['metric_status'] == ('FAIL' if bad else 'PASS')


@pytest.mark.parametrize('bad', ['floating_clock', 'supply', 'clustered', 'low_density', 'zero_spares'])
def test_actual_native_spare_failure_survives_missing_bounds(case, bad):
    if bad == 'floating_clock':
        case.plan['measured']['tieoff_inputs'][1]['net'] = None
        case.plan['tie_off']['inputs'][1]['net'] = None
        case.plan['tied_off'] = False
    elif bad == 'supply':
        case.plan['measured']['pg_unconnected'] = 1
    elif bad == 'clustered':
        case.plan['instances'][1].update(llx=0, lly=0)
    elif bad == 'low_density':
        case.plan['measured']['placed_cells'] = 1000
        case.plan['placed_cells_est'] = 1000
        case.plan['actual_density'] = 0.002
    else:
        case.plan['measured']['inserted'] = 0
        case.plan['count'] = 0
        case.plan['actual_density'] = 0
    case.update_plan()
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert result['metric_acceptance']['metric_status'] == 'FAIL'


def test_declared_native_distribution_bound_blocks(case, monkeypatch):
    bounds_double(case, monkeypatch, density=0.03)
    result = case.run()
    assert result['verdict'] == 'FAIL', result


@pytest.mark.parametrize('bad', ['source', 'model', 'alias', 'plan_count'])
def test_stale_or_incoherent_native_evidence_refuses(case, bad):
    if bad == 'source':
        case.receipt['input']['plugin'] = {'SOURCE_ONLY_TAMPERED': '0' * 64}
    elif bad == 'model':
        case.model.write_text('CHANGED\n')
    elif bad == 'alias':
        (case.project / 'phase3/stage3/pnr/post_spare.def').write_text('CHANGED\n')
    else:
        case.plan['count'] = 1
        case.update_plan()
    result = case.run()
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('metric_status') == 'NOT_MEASURED', result
    assert accepted['reason'] in ('D37_PRODUCER_CHANGED', 'D37_INPUT_CHANGED', 'D37_NATIVE_CENSUS_INCOMPLETE')


def test_real_receipt_reader_refuses_the_invalid_source_only_sentinel(case, monkeypatch):
    monkeypatch.setattr(ll, 'validate_step_receipt', REAL_RECEIPT_READER)
    result = case.run()
    assert result.get('metric_acceptance', {}).get('reason') == 'LL_STEP_OUTPUT_UNBOUND', result
