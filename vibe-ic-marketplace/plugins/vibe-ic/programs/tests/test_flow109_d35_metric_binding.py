"""SOURCE ONLY: native receipt validation is an explicit in-memory double.

No native tool, qualification, APPROVED requirement or canonical receipt is
authored by these controls. Disk receipt sentinels are deliberately invalid.
The production completion and metric consumers and legality parser are real.
"""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109
import execution_backend_producers as producer
import librelane_contract as ll
import placement_legality_check as legality
import flow109_metric_acceptance as metrics

REAL_RECEIPT_READER = ll.validate_step_receipt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / 'source-only-project'
    project.mkdir()

    def put(path, value):
        path = project / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, dict) else value)
        return path

    registry = flow109.load_registry()
    features = next(p['features'] for p in registry['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D35', 'D35')
    ctx = put('context.json', context)
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(ctx))
    initial = put('input/state.json', {'source_only': True})
    netlist = put('input/netlist.v', 'module neutral(input a, output y); assign y=a; endmodule\n')
    model = put('input/library.lib', 'SOURCE-ONLY MODEL SENTINEL\n')
    steps = ['OpenROAD.GlobalPlacement', 'OpenROAD.RepairDesignPostGPL',
             'Vibeic.PostGPLFanoutClosure', 'OpenROAD.DetailedPlacement']
    receipts, states, folders, configs = {}, [], {}, {}
    previous = initial
    for index, step in enumerate(steps):
        folder = project / 'native-double' / str(index)
        config = put('phase3/librelane/execution-backend-17-config/' + step + '.json',
                     {'meta': {'step': step}, 'source_only': True})
        state = put(folder / 'state_out.json', {'metrics': {'timing__setup__ws': 1.0}})
        put(folder / 'vibeic_receipt.json', 'SOURCE_ONLY_INVALID_RECEIPT_SENTINEL\n')
        put(folder / 'pdk_root.json', {'mounts_under_it': []})
        log = put(folder / 'invocation.log', 'OpenROAD source-control\n[INFO GPL-0041] Total routing overflow: 0.125\n')
        fp = {'state': sha(previous), 'config': sha(config), 'step': step,
              'state_files': {str(netlist): sha(netlist)},
              'config_files': {str(model): sha(model)}, 'image': 'SOURCE_ONLY_DOUBLE'}
        if step.startswith(ll.PLUGIN_STEP_PREFIX):
            fp['plugin'] = ll._plugin_digests(step)
        receipts[str(folder)] = {'input': fp, 'sha256': {'state_out.json': sha(state), 'invocation.log': sha(log)}}
        states.append({'step': step, 'state': str(state), 'sha256': sha(state)})
        folders[step], configs[step] = folder, config
        previous = state
    source_def = put('native-double/3/placed.def', 'VERSION 5.8 ;\nDESIGN neutral ;\nCOMPONENTS 1 ;\n- u neutral_cell + PLACED ( 0 0 ) N ;\nEND COMPONENTS\nEND DESIGN\n')
    source_odb = put('native-double/3/placed.odb', 'SOURCE_ONLY_ODB_SENTINEL\n')
    final = {'def': str(source_def), 'odb': str(source_odb), 'metrics': {'timing__setup__ws': 1.0}}
    previous.write_text(json.dumps(final))
    states[-1]['sha256'] = sha(previous)
    receipts[str(previous.parent)]['sha256']['state_out.json'] = sha(previous)
    put('reports/phase3/execution-backend-17.json', {'ordered_steps': steps,
        'initial_state': str(initial), 'initial_sha256': sha(initial), 'states': states})
    handoff = {'state': str(previous), 'state_sha256': sha(previous), 'views': {}}
    for view, source, name in [('def', source_def, 'placed.def'), ('odb', source_odb, 'librelane_placed.odb')]:
        dest = put('phase3/stage3/pnr/' + name, source.read_text())
        handoff['views'][view] = {'source': str(source), 'source_sha256': sha(source),
                                'dest': str(dest), 'dest_sha256': sha(dest)}
    put('reports/phase3/librelane_placement_handoff.json', handoff)
    monkeypatch.setattr(ll, 'validate_step_receipt', lambda folder, step: receipts[str(folder)])
    monkeypatch.setattr(legality, '_librelane_placement', lambda project: {
        'bound': True, 'detailed_placement': 'COMPLETED', 'receipt': 'SOURCE_ONLY_DOUBLE',
        'detailed_placement_dir': str(previous.parent)})
    monkeypatch.setattr(producer, '_parameters', lambda *a: (None, ll, None, None))
    monkeypatch.setattr(ll, 'flow_segment', lambda *a, **k: [s for s in steps if s != 'Vibeic.PostGPLFanoutClosure'])
    monkeypatch.setattr(producer, '_state_chain', lambda *a, **k: (ll, configs, folders))
    monkeypatch.setattr(producer, '_handoff', lambda *a, **k: handoff)
    monkeypatch.setattr(producer, '_publish_step17_timing_script', lambda *a, **k: None)
    monkeypatch.setattr(producer, '_logs', lambda *a, **k: None)

    def run():
        result = producer.produce_pnr(project, {'step_id': '17', 'top': 'neutral', 'image_id': 'SOURCE_ONLY_DOUBLE'})
        put('SOURCE_ONLY_OBSERVATION.json', {'scope': 'SOURCE_ONLY_METHOD_DOUBLES_NOT_IC_EVIDENCE', 'result': result})
        return result
    def complete():
        monkeypatch.setattr(producer, '_native_current_step_output_snapshot', lambda *a: {})
        monkeypatch.setattr(producer, '_native_current_step_producer', lambda *a: 'SOURCE_ONLY_DOUBLE')
        monkeypatch.setattr(producer, '_native_current_step_receipt', lambda *a: {'scope': 'SOURCE_ONLY_DOUBLE'})
        monkeypatch.setattr(producer, '_current_step_producer_authority', lambda *a, **k: (True, 'SOURCE_ONLY_DOUBLE', 'PASS'))
        monkeypatch.setattr(producer, '_runner_context', lambda: SimpleNamespace(_DECLARED_SIGNOFF_GATES=[], _PRESTREAM_GATES=[]))
        result = producer.produce(project, {'step_id': '17', 'top': 'neutral',
            'image_id': 'SOURCE_ONLY_DOUBLE', 'stop_on_producer_failure': True})
        put('SOURCE_ONLY_OBSERVATION.json', {'scope': 'SOURCE_ONLY_METHOD_DOUBLES_NOT_IC_EVIDENCE', 'result': result})
        return result
    return SimpleNamespace(project=project, run=run, put=put, netlist=netlist,
                           model=model, state=previous, handoff=handoff,
                           source_def=source_def, receipts=receipts, complete=complete)


def bounds_double(case, monkeypatch, *, setup_min=0, congestion_max=1):
    """Only requirements-reader method doubles; no approved document is made."""
    source = case.put('input/source-only-bounds.txt', 'SYNTHETIC REQUIREMENTS READER DOUBLE\n')
    bodies = {}
    for name, field, bound, unit in [
        ('pre_cts_setup_drv_targets', 'timing__setup__ws', {'min': setup_min}, 'ns'),
        ('congestion_targets', 'route.congestion.overflow.total', {'max': congestion_max}, '1')]:
        relative = f'requirements/base_23/{name}.json'
        sentinel = case.put(relative, 'SOURCE_ONLY_NOT_AN_APPROVED_DOCUMENT\n')
        bodies[relative] = ({'status': 'SOURCE_ONLY_METHOD_DOUBLE', 'path': relative,
            'sha256': sha(sentinel), 'source': {'path': str(source.relative_to(case.project)), 'sha256': sha(source)}},
            {'limits': {field: bound}, 'units': {field: unit}})
    monkeypatch.setattr(metrics, '_approved_document', lambda project, relative, **kwargs: bodies[relative])


def test_declared_bounds_consume_real_native_state_and_log_readers(case, monkeypatch):
    bounds_double(case, monkeypatch)
    result = case.run()
    assert result['verdict'] == 'PASS'
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('metric_status') == 'PASS', result
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['obligations'][2]['measurements'][0]['measurement']['value'] == 0.125


@pytest.mark.parametrize('bad', ['setup', 'congestion'])
def test_native_value_misses_declared_bound_blocks(case, monkeypatch, bad):
    bounds_double(case, monkeypatch, setup_min=2 if bad == 'setup' else 0,
                  congestion_max=0 if bad == 'congestion' else 1)
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert result['metric_acceptance']['metric_status'] == 'FAIL'


def test_measured_target_failure_survives_later_missing_authority(case, monkeypatch):
    bounds_double(case, monkeypatch, setup_min=2)
    (case.project / 'requirements/base_23/congestion_targets.json').unlink()
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert result['metric_acceptance']['obligations'][1]['status'] == 'FAIL'
    assert result['metric_acceptance']['obligations'][2]['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('bad', [False, True])
def test_real_completion_preserves_metrics_in_worker_consumed_envelope(case, monkeypatch, bad):
    bounds_double(case, monkeypatch, setup_min=2 if bad else 0)
    result = case.complete()
    assert result['verdict'] == ('FAIL' if bad else 'PASS'), result
    assert result['canonical_receipts'][0].get('metric_acceptance') == result.get('metric_acceptance') != None
    assert result['canonical_receipts'][0]['metric_acceptance']['metric_status'] == ('FAIL' if bad else 'PASS')


def test_legal_native_readback_retains_missing_bounds(case):
    result = case.run()
    assert result['verdict'] == 'PASS'
    measured = result.get('metric_acceptance', {})
    assert measured.get('status') == 'NOT_MEASURED', result
    assert measured['obligations'][0]['status'] == 'PASS', measured
    assert all(o['status'] == 'NOT_MEASURED' for o in measured['obligations'][1:])
    assert measured['qualification'] == 'NOT_MEASURED'


def test_unplaced_native_geometry_blocks_even_with_missing_bounds(case):
    # Change the native output coherently, so a hash mismatch is not the cause.
    text = case.source_def.read_text().replace('+ PLACED ( 0 0 ) N', '+ UNPLACED')
    case.source_def.write_text(text)
    dest = case.project / 'phase3/stage3/pnr/placed.def'
    dest.write_text(text)
    case.handoff['views']['def'].update(source_sha256=sha(case.source_def), dest_sha256=sha(dest))
    case.put('reports/phase3/librelane_placement_handoff.json', case.handoff)
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert result['metric_acceptance']['metric_status'] == 'FAIL'
    assert result['metric_acceptance']['obligations'][0]['measurement']['status'] == 'FAIL'


@pytest.mark.parametrize('damage', ['netlist', 'model', 'state', 'config', 'alias'])
def test_changed_consumed_bytes_are_refused(case, damage):
    path = {'netlist': case.netlist, 'model': case.model, 'state': case.state,
            'config': case.project / 'phase3/librelane/execution-backend-17-config/OpenROAD.DetailedPlacement.json',
            'alias': case.project / 'phase3/stage3/pnr/placed.def'}[damage]
    path.write_text(path.read_text() + '\nCHANGED\n')
    result = case.run()
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('status') == 'NOT_MEASURED', result
    assert accepted['reason'] in ('D35_INPUT_CHANGED', 'D35_MODEL_CHANGED')


def test_real_native_receipt_reader_rejects_source_only_sentinel(case, monkeypatch):
    monkeypatch.setattr(ll, 'validate_step_receipt', REAL_RECEIPT_READER)
    result = case.run()
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('status') == 'NOT_MEASURED', result
    assert accepted['reason'] == 'LL_STEP_OUTPUT_UNBOUND'


def test_changed_consumed_native_plugin_source_is_refused(case):
    for receipt in case.receipts.values():
        if receipt['input']['step'].startswith(ll.PLUGIN_STEP_PREFIX):
            receipt['input']['plugin'] = {'SOURCE_ONLY_TAMPERED_PLUGIN': '0' * 64}
    result = case.run()
    accepted = result.get('metric_acceptance', {})
    assert accepted.get('status') == 'NOT_MEASURED', result
    assert accepted['reason'] == 'D35_PRODUCER_SOURCE_CHANGED'


def test_no_context_preserves_ordinary_component_behavior(case, monkeypatch):
    monkeypatch.delenv('VIBEIC_FLOW109_CONTEXT')
    result = case.run()
    assert result['verdict'] == 'PASS'
    assert 'metric_acceptance' not in result
