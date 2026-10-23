"""Default dispatch controls; mocked native transport is not IC evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import phase3_one_shot_runner as runner
import execution_backend_producers as producers
import execution_backend_worker as worker
import execution_backend_gates as gates
import execution_policy


def _at_speed_condition_project(tmp_path, monkeypatch):
    """Real condition/readers; downstream transport never executes an EDA tool."""
    import _flow_yaml
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    input_doc = docs / 'product.md'
    input_doc.write_text('A small arithmetic core multiplies two numbers.\n')
    layer = tmp_path / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json'
    layer.parent.mkdir(parents=True)
    document = {'doc_id': 'L20', 'applicability': 'APPLICABLE', 'fields': {
        'dft_present': False, 'scan_chains': [], 'bist_mbist': [], 'jtag_tap': None}}
    layer.write_text(json.dumps(document))
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *a: {})
    rows = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    calls = []

    def downstream_transport(project, sid, *, parameters):
        calls.append(sid)
        parameters['resolved_input_manifest'] = {
            'files': {}, 'missing': ['source-control: downstream native input absent']}
        return {}

    monkeypatch.setattr(execution_policy, '_fixed_inputs', downstream_transport)
    return input_doc, layer, document, rows, calls


def test_default_at_speed_design_absence_continues_to_the_next_physical_row(
        tmp_path, monkeypatch):
    import flow_compliance_check as compliance
    import step_output_collector as versions
    _, layer, _, rows, calls = _at_speed_condition_project(tmp_path, monkeypatch)
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='source-control'), '', ['DT2', 'DT3', '24'])
    assert calls == ['24']
    assert [row['status'] for row in result.extras['canonical_steps']] == [
        'NOT_APPLICABLE', 'NOT_APPLICABLE', 'NOT_MEASURED']
    assert result.status == 'NOT_MEASURED' and result.extras['canonical_steps'][-1]['extras']['step_id'] == '24'
    for sid in ('DT2', 'DT3'):
        complete = compliance.check_step(tmp_path, rows[sid], {})
        assert complete.status == 'NOT_APPLICABLE', complete
        assert any('design-declared NOT_APPLICABLE' in reason for reason in complete.reasons)
        assert str(layer.relative_to(tmp_path)) in result.extras['canonical_gate_checks'][sid]['reasons'][0]
        indexed = next(row for row in versions._read_index(tmp_path)['steps']
                       if str(row['id']) == sid)
        saved = json.loads((tmp_path / 'steps' / indexed['folder'] / 'outputs.json').read_text())
        assert saved['status'] == 'NOT_APPLICABLE' and saved['canonical_pass'] is False
        assert versions.latest_pass(tmp_path, sid) is None


@pytest.mark.parametrize('sid', ['DT2', 'DT3'])
@pytest.mark.parametrize('damage', [
    'missing', 'invalid', 'incomplete', 'contradictory', 'input_declares_dft', 'empty_input'])
def test_default_at_speed_unknown_or_asserted_dft_still_stops_on_missing_dependency(
        tmp_path, monkeypatch, sid, damage):
    import flow_compliance_check as compliance
    input_doc, layer, document, rows, calls = _at_speed_condition_project(tmp_path, monkeypatch)
    if damage == 'missing':
        layer.unlink()
    elif damage == 'invalid':
        layer.write_text('{not JSON')
    elif damage == 'incomplete':
        del document['fields']['jtag_tap']
        layer.write_text(json.dumps(document))
    elif damage == 'contradictory':
        document['fields']['scan_chains'] = [{'name': 'chain0', 'length': 8}]
        layer.write_text(json.dumps(document))
    elif damage == 'input_declares_dft':
        input_doc.write_text('The design requires scan insertion.\n')
    else:
        input_doc.unlink()
    assert compliance._l_doc_declares_absence(
        tmp_path, rows[sid]['condition']['l_doc_declares']) is None
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='source-control'), '', [sid, '24'])
    assert result.status == 'NOT_MEASURED'
    assert calls == []
    assert [row['extras']['step_id'] for row in result.extras['canonical_steps']] == [sid]
    assert result.extras['canonical_gate_checks'][sid]['status'] == 'NOT_MEASURED'
    assert 'dependency condition is not ready' in result.detail


@pytest.mark.parametrize('sid', ['DT2', 'DT3'])
def test_default_at_speed_present_dependencies_still_enter_the_actual_producer(
        tmp_path, monkeypatch, sid):
    import flow_compliance_check as compliance
    _, layer, document, rows, calls = _at_speed_condition_project(tmp_path, monkeypatch)
    document['fields']['dft_present'] = True
    layer.write_text(json.dumps(document))
    for pattern in rows[sid]['condition']['files_exist']:
        path = tmp_path / pattern.replace('*', 'unit')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Source-control dependency bytes; no native measurement.\n')
    assert compliance._check_condition(tmp_path, rows[sid]['condition']) is True
    produced = []

    def native_transport(project, step, *args):
        produced.append(step)
        return {'rc': 2, 'reason': 'source-control native transport not measured'}

    monkeypatch.setattr(runner, '_run_at_speed_atpg_producer', native_transport)
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='source-control'), '', [sid, '24'])
    assert produced == [sid] and calls == []
    assert result.status == 'NOT_MEASURED'
    assert [row['extras']['step_id'] for row in result.extras['canonical_steps']] == [sid]


def test_current_flow_declares_the_immutable_cts_handoff_as_a_step19_output():
    """Use the actual front-door declaration reader on the complete source flow."""
    import step_required_inputs_check as inputs
    flow = Path(runner.__file__).parents[1] / 'flow/phase1_phase2_phase3.yaml'
    rows, error = inputs.load_flow(flow)
    assert error is None
    assert len(rows) == 70
    by_id = {str(row['id']): row for row in rows}
    handoff = 'reports/phase3/librelane_cts_handoff.json'
    assert handoff in by_id['19']['required_outputs']
    assert {'from': 19, 'path': handoff} in by_id['20']['required_inputs']
    assert inputs.declaration_defects(rows) == []


def test_current_flow_reader_refuses_the_old_undeclared_cts_handoff_edge():
    import copy
    import step_required_inputs_check as inputs
    flow = Path(runner.__file__).parents[1] / 'flow/phase1_phase2_phase3.yaml'
    rows, error = inputs.load_flow(flow)
    assert error is None
    rows = copy.deepcopy(rows)
    row19 = next(row for row in rows if str(row['id']) == '19')
    handoff = 'reports/phase3/librelane_cts_handoff.json'
    row19['required_outputs'] = [path for path in row19['required_outputs']
                                 if path != handoff]
    defects = inputs.declaration_defects(rows)
    assert len(defects) == 1
    assert defects[0]['where'] == 'step 20 required_inputs[1]'
    assert handoff in defects[0]['defect']
    assert "NOT one of step 19's declared required_outputs" in defects[0]['defect']


def _prebackend_consumer_control(tmp_path, monkeypatch, outcomes, *, mode='default'):
    """Drive actual main/retention; only native transport and gate outcomes are controlled."""
    import design_one_shot_runner as design
    import step_preflight as preflight
    import step_output_collector as versions
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode=mode))
    if mode == 'ultra':
        monkeypatch.setattr(execution_policy, 'bootstrap', lambda *a, **k: None)
        monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(runner, 'run_step11_dft_after_synth', lambda *a: [])
    monkeypatch.setattr(runner, 'run_step13_lec_on_pnr_input', lambda *a: [])
    monkeypatch.setattr(runner, 'run_pre_audit_producers', lambda *a, **k: [])
    monkeypatch.setattr(runner, '_ordinary_phase3_row', lambda *a, **k: None)
    monkeypatch.setattr(runner, '_publish_final_layout_receipts', lambda *a: 0)
    monkeypatch.setattr(runner, '_complete_physical_verification',
                        lambda *a: runner.StepResult('physical_verification', 'NOT_MEASURED', 0,
                                                    'no native physical verification in this control',
                                                    reason_class=runner._V.ReasonClass.NOT_EXECUTED))

    rel = 'phase3/stage3/sta/pre_pnr_timing.rpt'
    output = project / rel
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b'prior prelayout output')
    earlier = versions.begin_step(project, '10')
    prior_record = versions.finish_step(project, earlier, verdict='FAIL', result={
        'canonical_consumer': {'status': 'FAIL', 'step': {'id': '10', 'status': 'FAIL',
                              'reasons': ['previous invocation only']}, 'ledger': []}})
    calls, native_rows = [], []

    def consume(proj, row):
        sid = str(row['id'])
        assert sid in ('7', '8', '10'), sid
        calls.append(('consumer', sid))
        status = outcomes.get(sid, 'PASS')
        return {'status': status, 'step': {'id': sid, 'status': status,
                'reasons': [f'current Step {sid} control: {status}']}, 'ledger': []}

    monkeypatch.setattr(gates, 'evaluate', consume)
    monkeypatch.setattr(gates, 'contracts', lambda *a: {})

    @preflight.retained_steps(('7', '10'), canonical_acceptance=True)
    def prelayout(proj, *args):
        calls.append(('producer', '7/10'))
        output.write_bytes(b'current prelayout output')
        row = runner.StepResult('prelayout_signoff', 'PASS', 0, 'native control completed', [str(output)])
        native_rows.append(row)
        return row

    @preflight.retained_step('8', canonical_acceptance=True)
    def postcheck(proj, *args):
        calls.append(('producer', '8'))
        row = runner.StepResult('sdc_validation', 'PASS', 0, 'native postcheck control completed')
        native_rows.append(row)
        return row

    def next_producer(*args, **kwargs):
        calls.append(('producer', '15'))
        return runner.StepResult('pnr', 'NOT_MEASURED', 0,
            'Step 15 invocation counted; no native PnR executed',
            reason_class=runner._V.ReasonClass.NOT_EXECUTED)

    monkeypatch.setattr(runner, 'step_prelayout_signoff', prelayout)
    monkeypatch.setattr(design, 'step_sdc_validation_post_prelayout', postcheck)
    import librelane_contract
    monkeypatch.setattr(librelane_contract, 'selected_mode',
                        lambda project, step_id: 'dual' if str(step_id) == '8' else 'direct')
    monkeypatch.setattr(runner, '_default_step15_with_backend_receipt', next_producer)
    runner.main()
    count = calls.count(('producer', '15'))
    print(f'prebackend-control mode={mode} outcomes={outcomes} next_producer_invocations={count}')
    assert all(row.status == 'PASS' for row in native_rows), 'preserve original component results'
    assert output.read_bytes() == b'current prelayout output'
    assert (project / 'steps' / prior_record['folder'] / 'outputs.json').is_file()
    return project, calls, versions, rel


@pytest.mark.parametrize('sid', ['7', '8', '10'])
@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_default_main_stops_before_step15_after_complete_prelayout_rejection(
        tmp_path, monkeypatch, sid, status):
    project, calls, versions, rel = _prebackend_consumer_control(
        tmp_path, monkeypatch, {sid: status})
    records = {row['id']: row for row in versions.current_acceptance(project, 0)}
    assert records[sid]['status'] == status
    assert not records[sid]['canonical_pass']
    assert calls.count(('consumer', sid)) == 1, 'never rerun the rejected consumer'
    assert calls.count(('producer', '15')) == 0, 'complete rejection must prevent native Step 15'
    if sid in ('7', '10'):
        assert calls.count(('producer', '8')) == 0, 'reject before the next prebackend producer'
    folder = project / 'steps' / records['10']['folder']
    prior = json.loads((folder / 'before/outputs.json').read_text())['outputs']
    row = next(item for item in prior if item['rel'] == rel)
    assert (folder / 'before' / row['snapshot']).read_bytes() == b'prior prelayout output'


@pytest.mark.parametrize('status', ['PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE'])
def test_default_main_advances_after_accepted_prelayout_despite_prior_failure(
        tmp_path, monkeypatch, status):
    project, calls, versions, _ = _prebackend_consumer_control(
        tmp_path, monkeypatch, {sid: status for sid in ('7', '8', '10')})
    assert calls.count(('producer', '15')) == 1
    assert calls == [('producer', '7/10'), ('consumer', '7'), ('consumer', '10'),
                     ('producer', '8'), ('consumer', '8'), ('producer', '15')]
    assert all(row['status'] == status for row in versions.current_acceptance(project, 0))


@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_default_main_prelayout_rejection_keeps_measured_fail_precedence(
        tmp_path, monkeypatch, status):
    project, calls, _, _ = _prebackend_consumer_control(
        tmp_path, monkeypatch, {'7': status, '10': 'FAIL'})
    assert calls.count(('producer', '15')) == 0
    summary = json.loads(runner._pl.report_path(project, 'phase3_one_shot.json').read_text())
    assert summary['steps_verdict'] == 'FAIL'
    rejection = next(row for row in summary['steps'] if row['name'] == 'canonical_prelayout_acceptance')
    assert rejection['status'] == 'FAIL' and rejection['extras']['step_id'] in ('7', '10')


@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_ultra_keeps_existing_prelayout_component_behavior(tmp_path, monkeypatch, status):
    _, calls, _, _ = _prebackend_consumer_control(
        tmp_path, monkeypatch, {'8': status}, mode='ultra')
    assert calls.count(('producer', '15')) == 1
    assert not any(kind == 'consumer' for kind, _ in calls)


def test_default_floorplan_records_synthesis_under_the_current_sdc_before_native_pnr(tmp_path, monkeypatch):
    import drv_stage_receipts as stages
    from _ppa import timing
    stages.claim(tmp_path)
    pdk = SimpleNamespace(name="unit", liberty="current_core.lib")
    monkeypatch.setattr(producers, "_parameters", lambda *a: (runner, None, pdk, "unit-image"))
    monkeypatch.setattr(runner, "step_prepnr", lambda *a: runner.StepResult("prep", "PASS", 0, ""))
    monkeypatch.setattr(timing, "asic_sdc_for_pnr", lambda *a: {"source": "current step 7"})
    observed = {}

    def publish(current, folder):
        assert current["source"] == "current step 7"
        folder.mkdir(parents=True)
        (folder / "constraint.sdc").write_text("current step 7 deck\n")

    def census(project, **kwargs):
        observed.update(kwargs)
        assert kwargs["sdc"].read_text() == "current step 7 deck\n"
        assert kwargs["netlist"] == runner._pl.synth_dir(tmp_path) / "unit_synth.v"
        assert kwargs["liberties"] == ["current_core.lib"] and kwargs["top"] == "unit"
        return None

    def native(*args, **kwargs):
        assert observed, "floorplan began without synthesis evidence production"
        raise RuntimeError("native floorplan boundary reached")

    monkeypatch.setattr(timing, "publish_pnr_sdc", publish)
    monkeypatch.setattr(stages, "synth_stage_supervised", census)
    monkeypatch.setattr(runner, "_chip_path_requests_pad_ring", lambda *a: True)
    monkeypatch.setattr(runner, "_prepare_librelane_floorplan_for_route", native)
    with pytest.raises(RuntimeError, match="native floorplan boundary reached"):
        producers.produce_pnr(tmp_path, {"step_id": "15", "top": "unit",
            "die_um": "100,100", "util": .2, "pdk_root": str(tmp_path / "pdk"),
            "image_id": "unit-image"})


def test_default_floorplan_closes_pad_record_sdc_cycle_in_one_invocation(
        tmp_path, monkeypatch):
    """A successful pad/floorplan preparation must not require the caller to
    run Step 7 in a second top-level invocation merely because the newly
    written pad record made Step 7's prior input digest stale."""
    from _ppa import timing

    pdk = SimpleNamespace(name='unit', liberty='unit.lib')
    monkeypatch.setattr(producers, '_parameters',
                        lambda *a: (runner, None, pdk, 'unit-image'))
    prep = runner.StepResult(
        'prepnr', 'NOT_MEASURED', 0.0,
        'die 100x100 um; chip top PASS; SDC_SEAM_PENDING: pad record changed',
        extras={
            'chip_top': {'status': 'PASS', 'detail': 'written'},
            'sdc': {'path': None,
                    'basis': 'SDC_SEAM_PENDING: pad record changed'},
            'floorplan': {'die_w': 100, 'die_h': 100},
            'pad_assignment': {'status': 'PASS', 'detail': 'assigned'},
        }, reason_class='upstream_refused')
    monkeypatch.setattr(runner, 'step_prepnr', lambda *a: prep)
    monkeypatch.setattr(runner, '_chip_path_requests_pad_ring', lambda *a: True)
    calls = []

    def author(*args):
        calls.append('step7_author')
        return {'source': 'current pad record'}

    def publish(record, folder):
        calls.append('publish')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'constraint.sdc').write_text('current deck\n')

    seam = tmp_path / 'phase2/stage2/constraints/unit.sdc'
    seam.parent.mkdir(parents=True)
    seam.write_text('current deck\n')
    monkeypatch.setattr(timing, 'asic_sdc_for_pnr', author)
    monkeypatch.setattr(timing, 'publish_pnr_sdc', publish)
    monkeypatch.setattr(runner, '_prepnr_constraint_file',
                        lambda *a: (seam, 'current step-7 SDC'))

    def native(*args, **kwargs):
        calls.append('native')
        return runner.StepResult('pnr', 'PASS', 0.0, 'floorplan complete'), {}

    monkeypatch.setattr(runner, '_prepare_librelane_floorplan_for_route', native)
    monkeypatch.setattr(producers, '_publish_step15_bounded_state', lambda *a: None)
    result = producers.produce_pnr(tmp_path, {
        'step_id': '15', 'top': 'unit', 'die_um': '100,100', 'util': .2})
    assert result['verdict'] == 'PASS'
    assert calls == ['step7_author', 'publish', 'step7_author', 'publish', 'native']
    assert prep.status == 'PASS'
    assert prep.extras['sdc']['path'] == str(seam)


def test_backend_consumers_use_the_same_canonical_flow_as_default():
    import _flow_yaml
    from execution_provider_catalog import BACKEND_ROWS
    canonical = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    for sid, backend in BACKEND_ROWS.items():
        assert backend['canonical_row'] == canonical[sid], sid


def test_routing_resolves_flow_gates_before_native_execution(tmp_path, monkeypatch):
    import librelane_contract as ll
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (runner, ll, SimpleNamespace(name='unit'), ''))
    monkeypatch.setattr(ll, 'flow_segment', lambda *args, **kwargs:
                        ['Odb.HeuristicDiodeInsertion', 'OpenROAD.GlobalRouting',
                         'OpenROAD.DetailedRouting', 'Checker.TrDRC',
                         'Odb.ReportDisconnectedPins', 'Checker.DisconnectedPins'])

    def configs(project, image, pdk, ids, **kwargs):
        config_root = project / 'phase3/librelane' / kwargs['folder']
        config_root.mkdir(parents=True)
        (config_root / 'flow_gates.json').write_text(json.dumps({
            'Odb.HeuristicDiodeInsertion': {'RUN_HEURISTIC_DIODE_INSERTION': False}}))
        resolved = {sid: config_root / (sid + '.json') for sid in ids}
        for config in resolved.values():
            config.write_text(json.dumps({'DESIGN_NAME': 'unit'}))
        return resolved

    state = tmp_path / 'current_post_hold_state.json'
    state.write_text('{}')
    monkeypatch.setattr(ll, 'resolve_step_configs', configs)
    monkeypatch.setattr(runner, '_resolved_cell_policy', lambda configs, *args: (configs, {}))
    monkeypatch.setattr(producers, '_predecessor_state', lambda *args: state)

    def native(project, image, chain, **kwargs):
        ids = [sid for sid, config, input_state in chain]
        assert 'Odb.HeuristicDiodeInsertion' not in ids
        assert 'OpenROAD.GlobalRouting' in ids and 'OpenROAD.DetailedRouting' in ids
        assert 'Checker.TrDRC' in ids
        assert 'Odb.ReportDisconnectedPins' not in ids and 'Checker.DisconnectedPins' not in ids
        assert all(input_state == state for sid, config, input_state in chain)
        nvr_config = next(config for sid, config, _ in chain
                          if sid == 'Vibeic.NamedViolationReroute')
        nvr = json.loads(nvr_config.read_text())
        assert nvr['VIBEIC_NVR_DRC_REPORT'].endswith('/02-openroad-detailedrouting/unit.drc')
        assert Path(nvr['VIBEIC_NVR_TCL']).is_file()
        assert nvr['VIBEIC_NVR_REPORT_PATH'].endswith(runner.ROUTER_DRC_REPORT_NAME)
        raise RuntimeError('native boundary reached with resolved flow gates')

    monkeypatch.setattr(ll, 'run_chain', native)
    with pytest.raises(RuntimeError, match='native boundary reached'):
        producers.produce_pnr(tmp_path, {
            'step_id': '21', 'top': 'unit', 'pdk_name': 'unit',
            'image_id': 'unit-image', 'pdk_root': str(tmp_path),
        })


@pytest.mark.parametrize('final_bytes', [b'AFTER REPAIR: 0 violations\n', b''])
@pytest.mark.parametrize('measured', [True, False])
def test_routing_publishes_the_native_report_after_named_violation_repair(
        tmp_path, monkeypatch, final_bytes, measured):
    import librelane_route as route
    drt, nvr = tmp_path / 'detailed_route', tmp_path / 'named_repair'
    drt.mkdir(); nvr.mkdir()
    (drt / 'unit.drc').write_text('BEFORE REPAIR: 5 violations\n')
    final = nvr / 'named_viol_after.drc'
    final.write_bytes(final_bytes)
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (pnr / 'routed.def').write_text(
        'VERSION 5.8 ;\nCOMPONENTS 1 ;\n- u1 unit + PLACED ( 0 0 ) N ;\n'
        'END COMPONENTS\nEND DESIGN\n')
    log = tmp_path / 'routing.log'
    log.write_text('native detailed route and named repair transcript\n')
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (runner, None, None, ''))
    monkeypatch.setattr(route, 'chain_ids', lambda *args, **kwargs: [route.DRT, route.NVR])
    monkeypatch.setattr(producers, '_state_chain', lambda *args, **kwargs:
                        (None, {}, {route.DRT: drt, route.NVR: nvr}))
    monkeypatch.setattr(producers, '_handoff', lambda *args, **kwargs: {})
    monkeypatch.setattr(producers, '_logs', lambda *args, **kwargs: log)

    def receipt(out, routed_def, transcript):
        assert (out / runner.ROUTER_DRC_REPORT_NAME).read_bytes() == final.read_bytes()
        return {'verdict': 'measured'} if measured else None

    monkeypatch.setattr(runner, '_write_router_drc_receipt', receipt)
    monkeypatch.setattr(runner, '_emit_router_drc_report', lambda *args, **kwargs: True)
    monkeypatch.setattr(runner, '_PROV_SINK', tmp_path)
    params = {'step_id': '21', 'top': 'unit', 'image_id': 'unit-image'}
    if measured:
        result = producers.produce_pnr(tmp_path, params)
        assert result['verdict'] == 'PASS'
        import provenance_check
        report = tmp_path / 'provenance_gate.json'
        assert provenance_check.main([
            str(tmp_path), '--output', 'phase3/stage3/pnr/routed.def',
            '--tool', 'openroad', '--require-measured', '--json', str(report)]) == 0
        assert json.loads(report.read_text())['checks'][0]['status'] == 'PASS'
    else:
        with pytest.raises(producers.em.Refusal, match='BACKEND_ROUTER_TERMINAL_UNMEASURED'):
            producers.produce_pnr(tmp_path, params)
        assert not (tmp_path / 'provenance.jsonl').exists()


def test_hold_retry_uses_the_cts_producer_state_after_a_previous_hold_run(tmp_path):
    import hashlib
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    cts = tmp_path / 'native_cts'
    hold = tmp_path / 'native_hold'
    cts.mkdir(); hold.mkdir()
    cts_def, hold_def = cts / 'unit.def', hold / 'unit.def'
    cts_def.write_text('the current CTS checkpoint\n')
    hold_def.write_text('the previous Hold result\n')
    cts_state, hold_state = cts / 'state_out.json', hold / 'state_out.json'
    cts_state.write_text(json.dumps({'def': str(cts_def)}))
    hold_state.write_text(json.dumps({'def': str(hold_def)}))
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    (cts / 'vibeic_receipt.json').write_text(json.dumps({
        'sha256': {'state_out.json': sha(cts_state)}}))
    views = {}
    for label, source in [('cts', cts_def), ('hold', hold_def)]:
        dest = pnr / f'post_{label}.def'
        dest.write_bytes(source.read_bytes())
        views[f'post_{label}_def'] = {
            'dest': str(dest), 'dest_sha256': sha(dest),
            'source': str(source), 'source_sha256': sha(source)}
    receipt = tmp_path / 'reports/phase3/librelane_cts_hold_handoff.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({
        'measured_state': str(hold_state), 'measured_state_sha256': sha(hold_state),
        'views': views}))
    receipt.with_name('librelane_cts_handoff.json').write_text(json.dumps({
        'measured_state': str(cts_state), 'measured_state_sha256': sha(cts_state),
        'views': {'post_cts_def': views['post_cts_def']}}))
    assert producers._predecessor_state(tmp_path, 'post_cts.def') == cts_state
    assert producers._predecessor_state(tmp_path, 'post_hold.def') == hold_state
    cts_def.write_text('changed after its handoff\n')
    with pytest.raises(producers.em.Refusal, match='BACKEND_PREDECESSOR_STATE_UNBOUND'):
        producers._predecessor_state(tmp_path, 'post_cts.def')


def _split_cts_owner_control(tmp_path, monkeypatch, *, empty_ancillary_report=False):
    """Actual split producer/handoff/readers; only native writes are replaced."""
    import librelane_contract as ll
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (tmp_path / 'phase3/librelane_switch.json').write_text(json.dumps({
        'steps': {'19': 'librelane', '20': 'librelane'}}))
    body = ('VERSION 5.8 ;\nDESIGN unit ;\nCOMPONENTS 2 ;\n'
            '- u1 clkbuf_8 + PLACED ( 0 0 ) N ;\n'
            '- u2 clkbuf_8 + PLACED ( 1 0 ) N ;\nEND COMPONENTS\nEND DESIGN\n')
    (pnr / 'post_spare.def').write_text(body)
    (pnr / 'constraint.sdc').write_text('create_clock -period 10 [get_ports clk]\n')
    (pnr / 'unit_pnr.v').write_text('module unit(input clk); endmodule\n')
    (pnr / 'post_spare.odb').write_text('SOURCE_CONTROL predecessor ODB\n')
    initial = tmp_path / 'initial-state.json'
    initial.write_text(json.dumps({'def': str(pnr / 'post_spare.def'),
        'odb': str(pnr / 'post_spare.odb'), 'nl': str(pnr / 'unit_pnr.v'),
        'sdc': str(pnr / 'constraint.sdc'),
        'metrics': {'design__instance__area__stdcell': 2}}))
    seen = []

    def resolve(project, image, pdk, ids, *, folder, **kwargs):
        root = project / 'phase3/librelane' / folder
        root.mkdir(parents=True, exist_ok=True)
        result = {}
        for sid in ids:
            path = root / (sid + '.json')
            path.write_text(json.dumps({'meta': {'step': sid}, 'STA_CORNERS': ['nom'],
                                        'MAX_FANOUT_CONSTRAINT': 4}))
            result[sid] = path
        return result

    def native(project, image, chain, *, lane, **kwargs):
        seen.append({'ids': [s for s, _, _ in chain], 'input': chain[0][2]})
        current = json.loads(Path(chain[0][2]).read_text())
        folders = []
        for index, (sid, config, _) in enumerate(chain):
            fingerprint = {'step': sid, 'config': ll.digest(config),
                'state_files': {str(p): ll.digest(p) for p in ll._walk_paths(
                    {k: v for k, v in current.items() if k != 'metrics'})},
                'config_files': {}}
            assert all(Path(p).is_relative_to(project) for p in fingerprint['state_files'])
            folder = project / 'phase3/librelane' / lane / f'{index:02d}-{sid}'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'config.json').write_bytes(config.read_bytes())
            if sid != 'OpenROAD.STAMidPNR':
                for view in ('def', 'odb'):
                    path = folder / ('unit.' + view)
                    path.write_text(body if view == 'def' else lane + ' ODB\n')
                    current[view] = str(path)
            current['metrics'] = {
                'design__instance__area__stdcell': 2,
                'design__instance__count__hold_buffer': int(lane.endswith('20')),
                'vibeic__cts__max_fanout': 3,
                'clock__skew__worst_setup__corner:nom': .1,
                'clock__skew__worst_hold__corner:nom': .1,
                'timing__hold__ws__corner:nom': .3 if lane.endswith('20') else .2}
            (folder / 'state_out.json').write_text(json.dumps(current))
            if sid == 'OpenROAD.STAMidPNR' and empty_ancillary_report:
                # Native transport fixture: no diagnostic entries, not a
                # timing measurement. The real receipt binds these bytes.
                (folder / 'unpropagated.rpt').write_bytes(b'')
            if sid == 'OpenROAD.CTS':
                (folder / 'cts.rpt').write_text('Total number of Clock Roots: 1.\n'
                    'Total number of Buffers Inserted: 2.\nTotal number of Sinks: 9.\n')
                (folder / 'openroad-cts.log').write_text('SOURCE_CONTROL CTS transport\n')
            ll.write_json(folder / 'input_fingerprint.json', fingerprint)
            ll.write_json(folder / 'pdk_root.json', {'source_control': True})
            (folder / 'invocation.log').write_text('SOURCE_CONTROL native writes only\n')
            ll.write_json(folder / 'vibeic_receipt.json', {'input': fingerprint,
                'sha256': {str(p.relative_to(folder)): ll.digest(p)
                           for p in folder.iterdir() if p.is_file()}})
            folders.append(folder)
        return folders

    monkeypatch.setattr(ll, 'resolve_step_configs', resolve)
    monkeypatch.setattr(ll, 'run_chain', native)
    monkeypatch.setattr(runner, '_resolved_cell_policy', lambda configs, *a, **k: (configs, []))
    params = {'step_id': '19', 'top': 'unit', 'image_id': 'SOURCE_CONTROL',
              'pdk_root': str(tmp_path / 'neutral-pdk'), 'state_in': str(initial)}
    producers._cts_split(tmp_path, params, runner, ll, SimpleNamespace(name='neutral'), {})
    cts = tmp_path / 'reports/phase3/librelane_cts_handoff.json'
    assert cts.is_file(), 'Step19 must publish its own immutable CTS handoff'
    return ll, params, cts, seen


def test_split_hold_preserves_cts_output_and_retries_from_the_original_state(tmp_path, monkeypatch):
    import _librelane_cts_hold_evidence as evidence
    import cts_quality_check
    import hold_closure_check
    ll, params, cts, seen = _split_cts_owner_control(tmp_path, monkeypatch)
    original = cts.read_bytes()
    cts_state = producers._predecessor_state(tmp_path, 'post_cts.def')
    params = {**params, 'step_id': '20'}
    params.pop('state_in')
    for _ in range(2):
        producers._cts_split(tmp_path, params, runner, ll, SimpleNamespace(name='neutral'), {})
        assert cts.read_bytes() == original
        assert seen[-1]['input'] == cts_state
        assert 'OpenROAD.CTS' not in seen[-1]['ids']
        assert producers._predecessor_state(tmp_path, 'post_cts.def') == cts_state
        assert producers._predecessor_state(tmp_path, 'post_hold.def') != cts_state
        cts_ev, hold_ev = evidence.evidence(tmp_path, step='19'), evidence.evidence(tmp_path)
        assert cts_ev['problem'] is None and hold_ev['problem'] is None
        assert cts_ev['metrics']['timing__hold__ws__corner:nom'] == .2
        assert hold_ev['metrics']['timing__hold__ws__corner:nom'] == .3
    assert cts_quality_check.main([str(tmp_path), '--json', str(tmp_path / 'cts.json')]) == 0
    assert hold_closure_check.evaluate(tmp_path)[0] == 'PASS'


@pytest.mark.parametrize('changed', ['receipt_missing', 'cts_source', 'cts_state'])
def test_split_hold_refuses_missing_or_changed_original_cts_before_native(tmp_path, monkeypatch, changed):
    ll, params, cts, seen = _split_cts_owner_control(tmp_path, monkeypatch)
    doc = json.loads(cts.read_text())
    if changed == 'receipt_missing':
        cts.unlink()
    elif changed == 'cts_source':
        Path(doc['views']['post_cts_def']['source']).write_text('changed CTS\n')
    else:
        (tmp_path / doc['measured_state']).write_text('{}\n')
    params = {**params, 'step_id': '20'}
    params.pop('state_in')
    reason = ('BACKEND_PRODUCER_INPUT_ABSENT' if changed == 'receipt_missing'
              else 'BACKEND_PREDECESSOR_STATE_UNBOUND')
    with pytest.raises(producers.em.Refusal, match=reason):
        producers._cts_split(tmp_path, params, runner, ll, SimpleNamespace(name='neutral'), {})
    assert len(seen) == 1


@pytest.mark.parametrize('changed', [None, 'missing', 'changed'])
def test_split_hold_issued_manifest_carries_cts_into_an_isolated_project(
        tmp_path, monkeypatch, changed):
    """Software transport control; real resolver, copy, preflight and producer."""
    import shutil
    source = tmp_path / 'original'
    ll, params, cts, seen = _split_cts_owner_control(source, monkeypatch)
    for rel in ('input/step_0_5ic_answers.json', 'input/submission_template/source.json'):
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}\n')
    params = {**params, 'step_id': '20'}
    params.pop('state_in')
    issued = {}
    files = execution_policy._fixed_inputs(
        {'project': source, 'registry': None, 'policy': {'mode': 'default'}},
        '20', parameters=issued)
    manifest = issued['resolved_input_manifest']
    assert manifest['missing'] == []
    assert str(cts.relative_to(source)) in manifest['files']
    document = json.loads(cts.read_text())
    for folder in document['chain'].values():
        native = source / folder
        receipt = ll.validate_step_receipt(native, json.loads(
            (native / 'input_fingerprint.json').read_text())['step'])
        assert {str((native / p).relative_to(source)) for p in receipt['sha256']}.issubset(files)
        assert str((native / 'vibeic_receipt.json').relative_to(source)) in files
    inputs = tmp_path / 'inputs'
    for rel, original in files.items():
        target = inputs / 'project' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    private = tmp_path / 'private'
    worker._copy_input_tree(inputs, private)
    source.rename(tmp_path / 'unavailable-original')
    assert not source.exists(), 'the consumer must not reopen ambient original paths'
    native_rel = Path(document['views']['post_cts_def']['source']).relative_to(source)
    native_def = private / native_rel
    if changed == 'missing':
        native_def.unlink()
    elif changed == 'changed':
        native_def.write_text('changed original CTS view\n')
    missing = worker.resolve_input_contract(private, manifest['declarations'], manifest)
    if changed:
        assert str(native_rel) in missing
        with pytest.raises((producers.em.Refusal, ValueError)):
            producers._predecessor_state(private, 'post_cts.def')
        assert len(seen) == 1
        return
    assert missing == []
    original_receipt = (private / cts.relative_to(source)).read_bytes()
    measured = private / document['measured_state']
    original_state = measured.read_bytes()
    mapped = producers._predecessor_state(private, 'post_cts.def')
    assert mapped != measured
    assert all(p.is_file() and p.is_relative_to(private) for p in ll._walk_paths(
        {k: v for k, v in json.loads(mapped.read_text()).items() if k != 'metrics'}))
    producers._cts_split(private, params, runner, ll, SimpleNamespace(name='neutral'), {})
    assert seen[-1]['input'] == mapped
    assert 'OpenROAD.CTS' not in seen[-1]['ids']
    assert (private / cts.relative_to(source)).read_bytes() == original_receipt
    assert measured.read_bytes() == original_state
    assert worker.resolve_input_contract(private, manifest['declarations'], manifest) == []
    import hold_closure_check
    assert hold_closure_check.evaluate(private)[0] == 'PASS'


@pytest.mark.parametrize('changed', [None, 'missing', 'changed'])
def test_empty_cts_report_is_copied_and_hash_bound_through_hold_transport(
        tmp_path, monkeypatch, changed):
    """Reuse the complete existing transport control with a real empty member."""
    import sys
    original = _split_cts_owner_control

    def with_empty_report(*args):
        result = original(*args, empty_ancillary_report=True)
        ll, _, cts, _ = result
        document = json.loads(cts.read_text())
        folder = cts.parents[2] / document['chain']['OpenROAD.STAMidPNR']
        # cts is <project>/reports/phase3/<name>; its parent chain identifies
        # the original project without retaining an ambient external path.
        report = folder / 'unpropagated.rpt'
        assert report.is_file() and report.stat().st_size == 0
        receipt = ll.validate_step_receipt(folder, 'OpenROAD.STAMidPNR')
        assert receipt['sha256']['unpropagated.rpt'] == ll.digest(report)
        return result

    monkeypatch.setattr(sys.modules[__name__], '_split_cts_owner_control', with_empty_report)
    test_split_hold_issued_manifest_carries_cts_into_an_isolated_project(
        tmp_path, monkeypatch, changed)


def test_an_empty_required_measurement_is_not_just_a_hash_bound_byte_member(tmp_path):
    measurement = tmp_path / 'required_timing.rpt'
    measurement.write_bytes(b'')
    manifest = {'files': {'required_timing.rpt': worker.sha(measurement)}, 'missing': []}
    assert worker.resolve_input_contract(
        tmp_path, ['required_timing.rpt'], manifest) == ['required_timing.rpt']


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_empty_cts_ancillary_member_still_refuses_absence_and_changed_bytes(
        tmp_path, monkeypatch, damage):
    ll, _, cts, seen = _split_cts_owner_control(
        tmp_path, monkeypatch, empty_ancillary_report=True)
    for rel in ('input/step_0_5ic_answers.json', 'input/submission_template/source.json'):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}\n')
    issued = {}
    execution_policy._fixed_inputs(
        {'project': tmp_path, 'policy': {'mode': 'default'}}, '20', parameters=issued)
    manifest = issued['resolved_input_manifest']
    assert manifest['missing'] == []
    document = json.loads(cts.read_text())
    folder = tmp_path / document['chain']['OpenROAD.STAMidPNR']
    report = folder / 'unpropagated.rpt'
    rel = report.relative_to(tmp_path).as_posix()
    assert manifest['files'][rel] == ll.digest(report)
    if damage == 'missing':
        report.unlink()
    else:
        report.write_text('changed native report\n')
    assert rel in worker.resolve_input_contract(
        tmp_path, manifest['declarations'], manifest)
    with pytest.raises(ll.Refusal, match='LL_STEP_OUTPUT_UNBOUND'):
        ll.validate_step_receipt(folder, 'OpenROAD.STAMidPNR')
    assert len(seen) == 1, 'only the Step19 transport ran; no Step20 producer was called'


def test_rcx_publishes_its_current_native_spefs_for_the_existing_provenance_consumer(
        tmp_path, monkeypatch):
    import provenance_check
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (runner, None, None, ''))
    monkeypatch.setattr(runner, '_PROV_SINK', tmp_path)
    handed = {}

    def rcx(project, top, pdk, nominal, corner_dir, receipt, *, refresh):
        assert refresh is True
        paths = [nominal] + [corner_dir / f'{top}.{corner}.spef'
                             for corner in ('min', 'nom', 'max')]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "unit"\n'
                            '*D_NET net1 0.1\n*CAP\n1 net1:1 0.1\n*END\n')
        handed.update(zip(('min', 'nom', 'max'), paths[1:]))

    monkeypatch.setattr(runner, '_librelane_rcx_publish', rcx)
    monkeypatch.setattr(runner, '_librelane_handed_spefs', lambda *args: handed)
    result = producers.produce_signoff(tmp_path, {
        'step_id': '22', 'top': 'unit', 'image_id': 'fixture',
        'pdk_root': str(tmp_path)})
    assert result['verdict'] == 'PASS'
    for path in [tmp_path / 'phase3/stage3/extracted/unit.spef', *handed.values()]:
        report = tmp_path / 'provenance_gate.json'
        assert provenance_check.main([
            str(tmp_path), '--output', str(path.relative_to(tmp_path)),
            '--tool', 'openroad', '--require-measured', '--json', str(report)]) == 0
        assert json.loads(report.read_text())['checks'][0]['status'] == 'PASS'


@pytest.mark.parametrize('code,expected', [
    ('LL_STEP_FAILED', 'FAIL'), ('LL_FLOW_GATES_UNRESOLVED', 'NOT_MEASURED')])
def test_native_tool_refusal_is_recorded_at_the_actual_default_row(
        tmp_path, monkeypatch, code, expected):
    import librelane_contract as ll
    calls = install_transport(monkeypatch, tmp_path)

    def refused(project, params):
        calls.append(('producer', params['step_id']))
        raise ll.Refusal(code, 'routing native invocation log')

    monkeypatch.setattr(producers, 'produce', refused)
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '',
        ['21', '22'], die_um='auto', util=0.4)
    assert result.status == expected
    assert calls == [('producer', '21')]
    assert 'canonical step 21' in result.detail and code in result.detail
    saved = json.loads((tmp_path / 'reports/phase3/default_steps/21/backend_result.json').read_text())
    assert saved['verdict'] == expected and not saved['outputs']


@pytest.mark.parametrize('first,last', [('15', '15'), ('15', '16'),
                                      ('17', '17'), ('19', '22')])
def test_default_partial_pnr_selects_rows_without_enclosing_run(first, last, monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    ids = runner._phase3_window_steps(first, last)
    assert runner._phase3_window_sites(first, last) == (
        ['default_backend'] if '32' in ids else ['default_pnr'])
    if last == '22':
        assert ids.index('21') < ids.index('32') < ids.index('22')


@pytest.mark.parametrize('first,last', [('23', '23'), ('24', '24'),
                                      ('23', '30'), ('22', '24')])
def test_default_signoff_selects_existing_producers_without_enclosing_run(
        first, last, monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    assert runner._phase3_window_sites(first, last) == ['default_backend']


def test_ultra_signoff_retains_its_existing_dispatch(monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    assert runner._phase3_window_sites('23', '24') == ['enclosing_phase3']
    assert {'DT2', 'DT3'}.issubset(runner._phase3_window_steps('23', '24'))


def _full_gds_lvs_transport(monkeypatch, project, pdk, selected, case, calls=None):
    """Neutral config/process I/O; real bridge, chain, publisher and consumers."""
    import librelane_contract as lc
    import librelane_pv_signoff as pv
    import shutil
    from test_lvs_report_check import _PRIMARY_MATCH
    original_run = lc.run_container

    def configs(root, image, name, steps, **kwargs):
        assert root == project and steps == list(pv.LVS_CHAIN)
        assert kwargs['overlay']['MAGIC_EXT_USE_GDS'][0] is True
        assert kwargs['overlay']['MAGIC_EXT_ABSTRACT'][0] is False
        result = {}
        active_case = case() if callable(case) else case
        for step in steps:
            path = project / 'phase3/librelane/31-lvs-config' / (step + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'meta': {'step': step},
                'DESIGN_NAME': selected['design'], 'TECH_LEFS': {'nom_*': pdk.tech_lef},
                'MAGIC_EXT_USE_GDS': True, 'MAGIC_EXT_ABSTRACT': False,
                'SOURCE_CONTROL_COMPARE_CASE': active_case, 'CELL_LEFS': [pdk.cell_lef]}))
            views = {'step': step,
                'inputs': ['gds', 'def'] if step == pv.LVS_CHAIN[0] else ['spice', 'pnl'],
                'outputs': ['spice'] if step == pv.LVS_CHAIN[0] else []}
            lc.views_path(path).write_text(json.dumps(views))
            result[step] = path
        return result

    def process(argv, **kwargs):
        if '--id' not in argv:
            return original_run(argv, **kwargs)
        step = argv[argv.index('--id') + 1]
        if step not in pv.LVS_CHAIN:
            return original_run(argv, **kwargs)
        active_case = case() if callable(case) else case
        folder = Path(argv[argv.index('-o') + 1])
        incoming = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        if calls is not None:
            calls.append({'native_step': step, 'folder': str(folder),
                          'input_state': incoming, 'command': __import__('shlex').join(argv)})
        assert Path(incoming['gds']).read_bytes() == selected['gds'].read_bytes()
        shutil.copyfile(argv[argv.index('-c') + 1], folder / 'config.json')
        (folder / 'state_in.json').write_text(json.dumps(incoming))
        outgoing = dict(incoming, metrics=dict(incoming.get('metrics') or {}))
        outgoing['metrics'].update({key: int(active_case == 'lvs_error' and step == 'Netgen.LVS')
                                   for key in pv.PRODUCED[step]})
        if step == 'Magic.SpiceExtraction':
            spice = folder / 'layout.spice'
            spice.write_text(f".subckt {selected['design']} a y VDD VSS\nRsignal a y 1\n.ends\n")
            outgoing['spice'] = str(spice)
            if active_case != 'missing_feedback':
                feedback = ('box 0 0 10 10\nfeedback add "Illegal overlap between a and b" pale\n'
                            if active_case == 'illegal_overlap' else '')
                (folder / 'feedback.txt').write_text(feedback)
        else:
            report = folder / 'reports/lvs.netgen.rpt'
            report.parent.mkdir(parents=True, exist_ok=True)
            text = _PRIMARY_MATCH.replace('user_project_wrapper', selected['design'])
            if active_case == 'lvs_error':
                text = text.replace('Final result: Circuits match uniquely.',
                                    'Netlists do not match.\nFinal result: Top level cell failed pin matching.')
            report.write_text(text)
        (folder / 'state_out.json').write_text(json.dumps(outgoing))
        return SimpleNamespace(returncode=0, stdout='SOURCE_CONTROL LibreLane process leaf\n', stderr='')

    monkeypatch.setattr(pv, 'resolve_step_configs', configs)
    monkeypatch.setattr(lc, 'run_container', process)
    monkeypatch.setattr(lc, 'image_capability', lambda *a, **k: None)


@pytest.mark.parametrize('case', ['current', 'missing_fullgds', 'lvs_error',
                                 'missing_lvs_inputs', 'wrong_lvs_inputs_hash',
                                 'missing_feedback', 'illegal_overlap'])
def test_default_retains_the_existing_individual_layout_release_producers(tmp_path, monkeypatch, case):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    assert runner._phase3_window_sites('37', '37') == ['default_backend']
    from execution_provider_catalog import BACKEND_ROWS
    assert '37' in BACKEND_ROWS
    assert runner._phase3_window_sites('31', '31') == ['default_backend']
    import test_default_step31_owner as current31
    import librelane_contract as lc
    import _physical_current as physical
    # Reuse the finished-stream owners, not the older bare-GDS fixture. Only
    # expensive native process leaves are neutral; all current readers remain.
    identity = lc.local_image_attestation()
    image = SimpleNamespace(image=identity['image'],
        receipt=Path(identity['attestation_path']), readonly_attestation=True)
    project, pdk, selected, calls, attempt = current31._checkpoint31_fixture(
        tmp_path, monkeypatch, image)
    attempt['first'] = False
    _full_gds_lvs_transport(monkeypatch, project, pdk, selected, case)
    if case in ('missing_lvs_inputs', 'wrong_lvs_inputs_hash'):
        original_writer = runner._write_lvs_verdict

        def corrupt_after_compare(*args, **kwargs):
            result = original_writer(*args, **kwargs)
            path = project / 'reports/phase3/lvs_inputs.json'
            assert path.is_file(), 'the actual producer must publish compare inputs'
            if case == 'missing_lvs_inputs':
                path.unlink()
            else:
                value = json.loads(path.read_text())
                value['schematic_netlist']['sha256'] = '0' * 64
                path.write_text(json.dumps(value))
            return result

        monkeypatch.setattr(runner, '_write_lvs_verdict', corrupt_after_compare)
    if case == 'missing_fullgds':
        selected['gds'].unlink()
    retained_channels = {}
    if case == 'current':
        import magic_illegal_overlap_check as overlap
        for name in (*overlap.FEEDBACK_NAMES, *overlap.TRANSCRIPT_NAMES):
            previous = project / overlap.EXTRACTED_REL / name
            previous.parent.mkdir(parents=True, exist_ok=True)
            payload = f'Prior invocation only: {name}\nIllegal overlap between old and old\n'.encode()
            previous.write_bytes(payload)
            retained_channels[name] = payload
    before = {role: selected[role].read_bytes() for role in ('def', 'netlist', 'sdc', 'gds')
              if selected[role].is_file()}
    rc, record, retained, row, connectivity = current31._public_native31_window(
        project, pdk, monkeypatch, case='current', native_processes=calls)
    if case != 'current':
        assert rc != 0 and not record['canonical_pass'] and retained is None, record
        if case == 'lvs_error':
            assert record['result']['producer_verdict'] == 'FAIL', record
        return
    assert rc == 0, record
    assert record['canonical_pass'] and record['result']['producer_verdict'] == 'PASS'
    assert record['result']['canonical_step_result']['status'] == 'PASS'
    assert retained and retained['current_inputs']
    assert len(row['required_outputs']) == 13
    assert all((project / name).is_file() for name in row['required_outputs'])
    assert physical.read_direct_half(project, 'drc')['verdict'] == 'CURRENT'
    import librelane_signoff_evidence as native_evidence
    assert native_evidence.obligation(project, 'lvs')['verdict'] == 'PASS'
    drv = json.loads((project / 'reports/phase3/sta/drv_signoff.json').read_text())
    assert drv['verdict'] == 'PASS' and drv['capture_point'] == 'post_stream', drv
    inputs = project / 'reports/phase3/lvs_inputs.json'
    verdict = json.loads((project / 'reports/phase3/lvs_verdict.json').read_text())
    assert verdict['lvs_inputs']['sha256'] == current31.sha(inputs)
    bound = json.loads(inputs.read_text())
    for role, field in (('def', 'layout_def'), ('netlist', 'schematic_netlist'),
                        ('gds', 'layout_gds')):
        assert bound[field]['sha256'] == current31.sha(selected[role])
    assert connectivity['rc'] == 0, connectivity
    for name, payload in retained_channels.items():
        copies = list((project / 'reports/phase3').glob(
            f'librelane_lvs_reference_*/prior_extraction_channels/{name}'))
        assert len(copies) == 1 and copies[0].read_bytes() == payload
    assert all(selected[role].read_bytes() == payload for role, payload in before.items())
    assert runner._phase3_window_sites('37.3', '37.3') == ['default_backend']
    # The legacy individual XOR site belongs to the explicit Ultra context.
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    assert runner._phase3_window_sites('37.3', '37.3') == ['gds_xor']


def test_default_signoff_window_runs_only_current_row_and_consumer(tmp_path, monkeypatch):
    calls = install_transport(monkeypatch, tmp_path)
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(runner, '_phase3_window_enclosing', lambda *args, **kwargs:
                        pytest.fail('Default launched an enclosing signoff session'))
    monkeypatch.setattr(runner, '_phase3_window_clone', lambda *args:
                        pytest.fail('Default copied its local project'))
    monkeypatch.setattr(runner, '_phase3_window_full_gate_audit', lambda *args:
                        pytest.fail('Default repeated its current consumer'))
    args = SimpleNamespace(entry_step='23', exit_step='23', container='',
                           die_um='auto', util=0.4)
    selected = runner._phase3_window_sites('23', '23')
    assert runner._run_phase3_window(tmp_path, 'unit', SimpleNamespace(name='unit'),
                                    args, selected) == 0
    assert calls == [('producer', '23'), ('consumer', '23')]
    receipt = json.loads((tmp_path / 'reports/phase3/default_steps/23/backend_result.json').read_text())
    assert receipt['step_id'] == '23' and receipt['verdict'] == 'PASS'


def test_default_sta_publishes_the_selected_tool_without_a_second_sta(tmp_path, monkeypatch):
    import librelane_signoff as signoff
    pdk = SimpleNamespace(name='unit')
    requirements = tmp_path / 'input/docs/requirements.md'
    requirements.parent.mkdir(parents=True)
    requirements.write_text('No power network requirement is stated.\n')
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (runner, None, pdk, ''))
    monkeypatch.setattr(runner, '_emit_spef_sta', lambda *args:
                        pytest.fail('Default launched a second STA producer'))
    monkeypatch.setattr(runner, '_PROV_SINK', tmp_path)
    spef = tmp_path / 'phase3/stage3/extracted/unit.spef'
    spef.parent.mkdir(parents=True)
    spef.write_text('native parasitics\n')
    monkeypatch.setattr(runner, '_librelane_handed_spefs', lambda *args: {'nom': spef})
    sta = tmp_path / 'native_sta'
    scene = sta / 'nom_tt'
    scene.mkdir(parents=True)
    native = scene / signoff.CORNER_REPORT
    native.write_text('STA_BASIS: POST_ROUTE_SPEF\nworst slack 4.00\n')
    (sta / 'state_out.json').write_text('{}')
    calls = []

    def selected(project, top, pdk, m22, m23, corner_dir, ocv, notes, failures,
                 written, **kwargs):
        calls.append(kwargs)
        report = project / 'reports/phase3/sta_postpnr_signoff.json'
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({'sta_state': str(sta / 'state_out.json'),
                                      'sta_state_sha256': signoff.digest(sta / 'state_out.json'),
                                      'corners': {'nom_tt': {}},
                                      'judgment': {'verdict': 'PASS'}}))
        written.append(str(report))

    monkeypatch.setattr(runner, '_librelane_signoff_record', selected)
    result = producers.produce_signoff(tmp_path, {
        'step_id': '23', 'top': 'unit', 'pdk_root': str(tmp_path),
        'image_id': 'unit-image', 'execution_mode': 'default'})
    assert result['verdict'] == 'PASS'
    assert calls == [{'qualify': False}]
    for rel in ('phase3/stage3/sta/post_route_timing.rpt',
                'reports/phase3/sta_spef_based.rpt'):
        assert native.read_text() in (tmp_path / rel).read_text()


def install_transport(monkeypatch, project, *, failed_step=None):
    calls = []
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *args: {})
    monkeypatch.setattr(worker, 'resolve_input_contract', lambda *args: [])

    def producer(project_, params):
        sid = params['step_id']
        calls.append(('producer', sid))
        return {'verdict': 'PASS', 'detail': 'offline dispatch transport'}

    def consumer(project_, *, step_id, producer):
        calls.append(('consumer', step_id))
        return {'step_id': step_id,
                'verdict': 'FAIL' if step_id == failed_step else 'PASS',
                'detail': 'offline consumer transport', 'outputs': {}}

    def monolithic(*args, **kwargs):
        pytest.fail('Default reached the enclosing PnR session')

    monkeypatch.setattr(producers, 'produce', producer)
    monkeypatch.setattr(worker, 'execute_current_step', consumer)
    monkeypatch.setattr(runner, 'step_pnr', monolithic)
    return calls


def test_resume_at_cts_does_not_execute_prior_rows_and_stops_on_failure(tmp_path, monkeypatch):
    calls = install_transport(monkeypatch, tmp_path, failed_step='19')
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '',
        ['19', '20', '21', '22'], die_um='auto', util=0.4)
    assert calls == [('producer', '19'), ('consumer', '19')]
    assert result.status == 'FAIL'
    assert 'canonical step 19' in result.detail
    saved = json.loads((tmp_path / 'reports/phase3/default_steps/19/backend_result.json').read_text())
    assert saved['step_id'] == '19' and saved['verdict'] == 'FAIL'
    assert not (tmp_path / 'reports/phase3/default_steps/20').exists()
    import step_output_collector as versions
    index = json.loads((tmp_path / 'steps/index.json').read_text())
    version = next(row for row in index['steps'] if row['id'] == '19')
    retained = tmp_path / 'steps' / version['folder']
    assert json.loads((retained / 'outputs.json').read_text())['result'] == saved
    assert versions.latest_pass(tmp_path, '19') is None


def test_missing_cts_inputs_stop_before_any_native_tool(tmp_path, monkeypatch):
    calls = install_transport(monkeypatch, tmp_path)
    monkeypatch.setattr(worker, 'resolve_input_contract',
                        lambda *args: ['placed.def', 'clock_plan.json'])
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '',
        ['19'], die_um='auto', util=0.4)
    assert calls == []
    assert result.status == 'NOT_MEASURED'
    assert 'placed.def' in result.detail and 'clock_plan.json' in result.detail


def test_floorplan_window_finishes_before_placement(tmp_path, monkeypatch):
    calls = install_transport(monkeypatch, tmp_path)

    def clock(project, output, *args, **kwargs):
        calls.append(('producer', '16'))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"clocks": [{"name": "clk", "period_ns": 10}]}')
        return str(output)

    def clock_gate(project, row):
        calls.append(('consumer', str(row['id'])))
        return {'status': 'PASS', 'ledger': []}

    monkeypatch.setattr(runner, 'emit_clock_plan', clock)
    monkeypatch.setattr(gates, 'evaluate', clock_gate)
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '',
        ['15', '16'], die_um='auto', util=0.4)
    assert calls == [('producer', '15'), ('consumer', '15'),
                     ('producer', '16'), ('consumer', '16')]
    assert result.status == 'PASS'
    assert [row['extras']['step_id'] for row in result.extras['canonical_steps']] == ['15', '16']
    import step_output_collector as versions
    clock = versions.latest_pass(tmp_path, '16')
    assert clock['result']['verdict'] == 'PASS' and clock['canonical_pass']
    archive = tmp_path / 'steps' / clock['folder'] / 'clock_plan.json'
    assert archive.read_bytes() == (runner._pl.cts_dir(tmp_path) / 'clock_plan.json').read_bytes()


def test_single_default_driver_routes_the_full_existing_pnr_order(tmp_path, monkeypatch):
    captured = []

    def drive(project, top, pdk, container, step_ids, **kwargs):
        captured.extend(step_ids)
        return runner.StepResult('pnr', 'FAIL', 0, 'canonical step 19')

    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(runner, '_default_pnr_rows', drive)
    result = runner._default_step15_with_backend_receipt(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '', 'auto', 0.4)
    assert captured == ['15', '15.5ic', '16', '17', '18', '19', '20', '21']
    assert result.status == 'FAIL' and result.detail == 'canonical step 19'


def test_full_default_prestream_uses_the_existing_canonical_row_driver(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(runner, '_ordinary_phase3_row', lambda *args: None)

    def drive(project, top, pdk, container, step_ids, **kwargs):
        assert project == tmp_path
        assert kwargs['report_name'] == 'prestream_evidence'
        captured.extend(step_ids)
        return runner.StepResult('prestream_evidence', 'FAIL', 0, 'canonical step 23')

    monkeypatch.setattr(runner, '_default_pnr_rows', drive)

    def old_enclosing_path(*args, **kwargs):
        pytest.fail('Default reached the old enclosing signoff producer')

    monkeypatch.setattr(runner._pl, 'sta_dir', old_enclosing_path)
    result = runner.step_canonicalize_artefacts(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '', prestream=True)
    # The complete electrical stage follows repair -> final extraction ->
    # STA. Finishing/fill/final DFM belong after stream-out, not here.
    import _flow_yaml
    expected = list(_flow_yaml.ordered_step_ids(
        execution_stages=(5,), execution_tracks=('default',)))
    assert captured == expected == ['32', '22', '23', 'DT2', 'DT3', '24',
                                   '25', '26', '27', '28', '29', '30', '33']
    assert result.status == 'FAIL' and result.detail == 'canonical step 23'


@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_full_default_prestream_stops_on_the_actual_failed_row(
        tmp_path, monkeypatch, status):
    calls = []
    from _ppa import timing
    monkeypatch.setattr(timing, 'asic_sdc_for_pnr', lambda *_: {
        'text': 'create_clock -period 25 [get_ports clk]\n',
        'path': 'phase2/stage2/constraints/unit.asic.sdc',
        'step7_sha256': 'neutral-step7', 'deck_sha256': 'neutral-deck',
        'regenerated': None, 'derivation': None})
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(runner, '_ordinary_phase3_row', lambda *args: None)
    monkeypatch.setattr(runner, '_backend_parameter_values',
                        lambda *args: {'image_id': 'fixture', 'pdk_root': str(tmp_path)})
    monkeypatch.setattr(worker, 'resolve_input_contract', lambda *args: [])
    monkeypatch.setattr(runner, '_dedupe_shipped_netlist_ports', lambda *args: {})
    monkeypatch.setattr(runner, '_layout_basis', lambda *args: ('current-layout', ''))
    monkeypatch.setattr(runner, '_canonicalize_postpnr_prerequisites', lambda *args: None)

    def native(project, params):
        calls.append(('producer', params['step_id']))
        assert project == tmp_path and params['execution_mode'] == 'default'
        return {'verdict': status, 'detail': 'actual selected-tool refusal'}

    def consume(project, *, step_id, producer):
        calls.append(('consumer', step_id))
        return dict(producer, outputs={}, canonical_step_result={
            'status': status, 'reasons': ['actual selected-tool refusal']})

    monkeypatch.setattr(producers, 'produce', native)
    monkeypatch.setattr(worker, 'execute_current_step', consume)

    def forbidden(*args, **kwargs):
        pytest.fail('a later producer ran after the Default row stopped')

    monkeypatch.setattr(runner, '_canonicalize_postpnr_prerequisites', forbidden)
    monkeypatch.setattr(runner._pl, 'sta_dir', forbidden)
    monkeypatch.setattr(runner._pr, 'run', forbidden)
    # The pre-stream gate now only reads due route evidence. Execute the
    # actual electrical row owner first; a failing first row must prevent all
    # later rows and the pre-stream gate itself, for FAIL and NM alike.
    result = runner.step_canonicalize_artefacts(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '', prestream=True)
    assert calls == [('producer', '32'), ('consumer', '32')]
    assert result.status == status
    assert 'canonical step 32' in result.detail
    receipt = json.loads((tmp_path / 'reports/phase3/default_steps/32/backend_result.json').read_text())
    assert receipt['verdict'] == status
    assert receipt['canonical_step_result']['status'] == status
    assert result.extras['canonical_steps'][0]['extras']['step_id'] == '32'
    assert not (tmp_path / 'reports/phase3/prestream_gate.json').exists()


@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_full_default_main_stops_before_streaming_after_prestream_refusal(
        tmp_path, monkeypatch, status):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, _plan, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    transport = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='default'))

    def failed_gate(proj, top, pdk, container):
        digest, error = runner._layout_basis(proj, top, pdk, container)
        assert not error
        return runner.StepResult('prestream_gate', status, 0,
            'canonical step 23: selected STA refused',
            extras={'layout_digest': digest, 'failed_gates': ['default_step_23']},
            reason_class=runner._V.ReasonClass.INPUT_ABSENT if status == 'NOT_MEASURED' else '')

    monkeypatch.setattr(runner, 'step_prestream_gate', failed_gate)
    assert runner.main() != 0
    assert 'pnr' in transport.called
    assert 'gds' not in transport.called
    assert 'lvs' not in transport.called
    rows = _plan(project)
    assert rows['prestream_gate']['status'] == status
    for name in ('gds', 'drc', 'lvs', 'canonicalize_artefacts'):
        assert rows[name]['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('prepv', [True, False])
@pytest.mark.parametrize('failed_evidence', [False, True])
def test_default_poststream_keeps_completed_rows_and_runs_final_evidence(
        tmp_path, monkeypatch, prepv, failed_evidence):
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='default'))
    project, top, pdk = tmp_path, 'unit', SimpleNamespace(name='unit')
    if prepv:
        from test_default_stream_epoch_order import _transport
        import librelane_fill_dfm as fill
        import librelane_contract as ll
        import metal_fill_density_check as density
        import step_output_collector as versions
        project, pdk, native_calls, _ = _transport(tmp_path, monkeypatch)
        top = 'top'
        promotion = fill.default_stream(project, top, pdk, '')
        assert versions.latest_pass(project, '26.5ic')['current_inputs']
        completed_native_calls = list(native_calls)
    pnr = runner._pl.pnr_dir(project)
    rpt = runner._pl.reports_phase3_dir(project)
    pnr.mkdir(parents=True, exist_ok=True)
    rpt.mkdir(parents=True, exist_ok=True)
    inputs = ({path: path.read_bytes() for path in (
        pnr / 'top.def', pnr / 'routed.def', pnr / 'filled.def', pnr / 'top.gds')}
        if prepv else {
        pnr / 'unit.def': b'CURRENT ROUTED DEF\n',
        pnr / 'routed.def': b'CURRENT ROUTED DEF\n',
        pnr / 'pdn.done': b'ACTUAL STEP 15 PDN\n',
        pnr / 'constraint.sdc': b'CURRENT SDC\n',
        runner._pl.extracted_dir(tmp_path) / 'unit.spef': b'ACTUAL STEP 22 SPEF\n',
        runner._pl.cts_dir(tmp_path) / 'clock_plan.json': b'ACTUAL STEP 16 PLAN\n',
        pnr / 'filled.def': b'ACTUAL STEP 34 FILL\n',
        pnr / 'unit.gds': b'CURRENT STREAM\n',
        runner._pl.constraints_dir(tmp_path) / 'pvt_matrix.json': b'{}\n',
    })
    if prepv:
        # Keep every original retained-input category under the byte guard,
        # including the prior clock/PDN/extraction/constraint artefacts.
        for path, body in {
            pnr / 'pdn.done': b'ACTUAL STEP 15 PDN\n',
            pnr / 'constraint.sdc': b'CURRENT SDC\n',
            runner._pl.extracted_dir(project) / f'{top}.spef': b'ACTUAL STEP 22 SPEF\n',
            runner._pl.cts_dir(project) / 'clock_plan.json': b'ACTUAL STEP 16 PLAN\n',
            runner._pl.constraints_dir(project) / 'pvt_matrix.json': b'{}\n',
        }.items():
            inputs[path] = path.read_bytes() if path.is_file() else body
    for path, body in inputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    calls = []
    if prepv:
        if failed_evidence:
            # Change the actual bound finishing proof, not the row result.
            report = Path(promotion['finishing_report'])
            report.write_text(report.read_text() + '\n')

        def read_completed(proj, selected_top, selected_pdk, container, step_ids, **kwargs):
            # This unit transport models no new tool/consumer execution. Its
            # acceptance is obtained from the real completed finishing version
            # and existing stream/fill readers, never a mocked scientific PASS.
            assert proj == project and selected_top == top
            assert step_ids == ['26.5ic', '34']
            assert kwargs['report_name'] == 'prefill_evidence'
            calls.append('26.5ic')
            try:
                fill.validate_default_stream(proj)
                retained = versions.latest_pass(proj, '26.5ic')
                assert retained and retained['current_inputs']
            except (ll.Refusal, OSError, ValueError) as exc:
                return runner.StepResult('prefill_evidence', 'NOT_MEASURED', 0, str(exc),
                    reason_class=runner._V.ReasonClass.INPUT_ABSENT)
            calls.append('34')
            findings, _ = density.tool_arm_findings(proj)
            return runner.StepResult('prefill_evidence', 'FAIL' if findings else 'PASS',
                                     0, repr(findings))
        monkeypatch.setattr(runner, '_default_pnr_rows', read_completed)

    def repeated(*a, **k):
        pytest.fail('post-stream restarted a completed canonical row')

    for name in ('_librelane_signoff_modes', '_librelane_rcx_publish',
                 '_librelane_signoff_record', '_emit_metal_fill',
                 'emit_clock_plan', '_step29_tool_arm', '_step30_tool_arm',
                 '_step33_tool_arm'):
        monkeypatch.setattr(runner, name, repeated)

    def erc(project, top, pdk, container, out, notes):
        calls.append('erc')
        if prepv and failed_evidence:
            return False
        out.write_text('CURRENT ERC\n')
        return True

    def lec(project, top, pdk, container, out, report, notes):
        calls.append('lec')
        out.write_text(json.dumps({
            'verdict': 'NON_EQUIVALENT' if failed_evidence else 'PROVEN_EQUIVALENT',
            'total_points': 1, 'proven_points': 0 if failed_evidence else 1,
            'unproven_points': 0, 'non_equivalent_points': int(failed_evidence),
            'equivalent': not failed_evidence,
        }))
        return 'NON_EQUIVALENT' if failed_evidence else 'PROVEN_EQUIVALENT'

    def final_report(name):
        def emit(project, top, pdk, container, out, *args):
            calls.append(name)
            target = args[0] if name == 'aging' else out
            target.write_text('{"verdict":"PASS"}\n')
            return True
        return emit

    monkeypatch.setattr(runner, '_emit_erc_report', erc)
    monkeypatch.setattr(runner, '_emit_lec_post_layout', lec)
    for name, emitter in (('density', '_emit_metal_density_report'),
                          ('aging', '_emit_aging_sta_report'),
                          ('thermal', '_emit_thermal_screen')):
        monkeypatch.setattr(runner, emitter, final_report(name))
    monkeypatch.setattr(runner, '_emit_perc_equivalent',
                        lambda *a: calls.append('perc') or True)
    monkeypatch.setattr(runner, 'run_at_speed_atpg_producers',
                        lambda *a: calls.append('atpg'))
    result = runner.step_canonicalize_artefacts(
        project, top, pdk, '', prepv=prepv)
    assert calls == ((['26.5ic'] if failed_evidence else ['26.5ic', '34'])
                     if prepv else ['lec', 'density', 'aging', 'thermal', 'perc', 'atpg'])
    if prepv:
        assert native_calls == completed_native_calls, 'readback must not restart the completed stream/seal/fill'
    expected = ('NOT_MEASURED' if prepv else 'FAIL') if failed_evidence else 'PASS'
    assert result.status == expected, result.detail
    for path, body in inputs.items():
        assert path.read_bytes() == body, path
    assert (runner._pl.gds_dir(project) / f'{top}.gds').read_bytes() == inputs[pnr / f'{top}.gds']


def test_default_main_runs_final_readers_sequentially(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    transport = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='default'))
    native_gds = runner.step_gds

    def stream(*args, **kwargs):
        result = native_gds(*args, **kwargs)
        (runner._pl.pnr_dir(project) / 'filled.def').write_text('CURRENT FILLED LAYOUT\n')
        return result

    def concurrent(*args, **kwargs):
        pytest.fail('single-machine Default started a concurrent executor')

    monkeypatch.setattr(runner, 'step_gds', stream)
    monkeypatch.setattr(runner, 'ThreadPoolExecutor', concurrent)
    runner.main()
    assert transport.called.index('drc') < transport.called.index('lvs')


def test_default_main_stops_release_producers_after_final_evidence_failure(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, _plan, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    transport = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='default'))

    def canonical(proj, top, pdk, container, **kwargs):
        if kwargs.get('prepv'):
            (runner._pl.pnr_dir(proj) / 'filled.def').write_text('CURRENT FILLED LAYOUT\n')
            alias = runner._pl.gds_dir(proj) / f'{top}.gds'
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.write_bytes((runner._pl.pnr_dir(proj) / f'{top}.gds').read_bytes())
            return runner.StepResult('prefill_evidence', 'PASS', 0, 'current final stream')
        return runner.StepResult('canonicalize_artefacts', 'FAIL', 0,
                                 'post-layout LEC NON_EQUIVALENT')

    releases = []
    monkeypatch.setattr(runner, 'step_canonicalize_artefacts', canonical)
    monkeypatch.setattr(runner, 'run_pre_audit_producers',
                        lambda *a, **k: releases.append(k) or [])
    assert runner.main() != 0
    assert 'gds' in transport.called and 'lvs' in transport.called
    assert _plan(project)['canonicalize_artefacts']['status'] == 'FAIL'
    assert releases == []


def test_default_fill_and_dfm_use_the_existing_row_driver(monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    assert runner._phase3_window_sites('34', '35') == ['default_backend']


def test_default_main_stops_after_failed_repair_even_when_a_route_remains(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, _plan, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    transport = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='default'))
    monkeypatch.setattr(runner, '_librelane_postroute_repair_mode', lambda *a: 'librelane')
    monkeypatch.setattr(runner, 'step_postroute_repair_librelane', lambda *a:
                        runner.StepResult('postroute_repair_librelane', 'FAIL', 0,
                                          'selected repair measured a remaining violation'))
    # Native transport supplied a retained, usable route. Its presence does
    # not make the producer's measured quality failure a PASS.
    monkeypatch.setattr(runner, '_step32_stream_refusal', lambda *a: '')
    later = []
    original_gate = runner.step_prestream_gate

    def subsequent_gate(*args, **kwargs):
        later.append('prestream')
        return original_gate(*args, **kwargs)

    monkeypatch.setattr(runner, 'step_prestream_gate', subsequent_gate)
    assert runner.main() != 0
    assert later == []
    assert 'gds' not in transport.called
    rows = _plan(project)
    assert rows['routed_electrical']['status'] == 'FAIL'
    assert 'selected repair measured a remaining violation' in rows['routed_electrical']['detail']
    # Default aborts before stream dispatch. An unexecuted site has no result
    # row; the measured repair FAIL remains the run's evidence.
    assert 'gds' not in rows


def test_default_main_preserves_completed_inputs_before_repair(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='default'))
    monkeypatch.setattr(runner, '_librelane_postroute_repair_mode', lambda *a: 'librelane')
    pnr = runner._pl.pnr_dir(project)
    pdn = pnr / 'pdn.done'
    pdn.write_text('{"state":"native-step15-checkpoint"}\n')
    sdc = pnr / 'constraint.sdc'
    before = {p: p.read_bytes() for p in (pdn, sdc)}

    def repair(*args):
        assert {p: p.read_bytes() for p in before} == before
        return runner.StepResult('postroute_repair_librelane', 'FAIL', 0,
                                 'retained route failed its native repair check')

    def legacy_rewriter(*args):
        pytest.fail('Default re-entered the legacy publisher for completed rows')

    monkeypatch.setattr(runner, 'step_postroute_repair_librelane', repair)
    monkeypatch.setattr(runner, '_canonicalize_postpnr_prerequisites', legacy_rewriter)
    runner.main()
    assert {p: p.read_bytes() for p in before} == before


def test_default_dfm_produces_its_report_before_its_canonical_consumer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *args: {})
    monkeypatch.setattr(worker, 'resolve_input_contract', lambda *args: [])
    report = tmp_path / 'reports/phase3/dfm_screen.json'

    def program(project, sid, manifest):
        calls.append(('producer', sid))
        assert project == tmp_path and sid == '35'
        assert isinstance(manifest, dict)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text('{"verdict":"PASS"}\n')
        return {'verdict': 'PRODUCED'}

    def consumer(project, row):
        calls.append(('consumer', str(row['id'])))
        assert report.is_file()
        return {'status': 'PASS', 'ledger': []}

    monkeypatch.setattr(producers, '_run_current_step_declared_producers', program)
    monkeypatch.setattr(producers, '_current_step_producer_authority',
                        lambda *args, **kwargs: (True, '', 'PASS'))
    monkeypatch.setattr(gates, 'evaluate', consumer)
    result = runner._default_pnr_rows(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '', ['35'])
    assert result.status == 'PASS'
    assert calls == [('producer', '35'), ('consumer', '35')]


@pytest.mark.parametrize('mode,extra_sta', [('default', False), ('ultra', True)])
def test_default_power_uses_its_current_power_producer_without_restarting_sta(
        tmp_path, monkeypatch, mode, extra_sta):
    calls = []
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (runner, None, SimpleNamespace(name='unit'), ''))
    monkeypatch.setattr(runner, '_librelane_signoff_record',
                        lambda *args, **kwargs: calls.append('sta'))
    monkeypatch.setattr(runner, '_step33_tool_arm',
                        lambda *args, **kwargs: calls.append('power'))
    result = producers.produce_signoff(tmp_path, {
        'step_id': '33', 'top': 'unit', 'image_id': 'fixture',
        'pdk_root': str(tmp_path), 'execution_mode': mode})
    assert calls == (['sta', 'power'] if extra_sta else ['power'])
    assert result['verdict'] == 'PASS'


def test_default_native_refusal_does_not_run_report_producers(tmp_path, monkeypatch):
    monkeypatch.setattr(producers, 'produce_pnr', lambda *args:
                        {'verdict': 'NOT_MEASURED', 'detail': 'SDC_SEAM_PENDING'})
    monkeypatch.setattr(producers, '_run_current_step_declared_producers',
                        lambda *args: pytest.fail('reports ran after native refusal'))
    result = producers.produce(tmp_path, {
        'step_id': '15', 'stop_on_producer_failure': True})
    assert result == {'verdict': 'NOT_MEASURED', 'detail': 'SDC_SEAM_PENDING'}


def test_default_pad_ring_consumes_the_floorplan_native_ring(tmp_path, monkeypatch):
    state = tmp_path / 'phase3/librelane/current-floorplan/06-openroad-padring/state_out.json'
    state.parent.mkdir(parents=True)
    state.write_text('{}')
    handoff = tmp_path / 'reports/phase3/librelane_padring_handoff.json'
    handoff.parent.mkdir(parents=True)
    handoff.write_text(json.dumps({'state': str(state)}))
    bound = {'record': {'handoff_views': {'def': {
        'source': str(state.parent.parent / '11-openroad-generatepdn/chip.def')}}}}
    calls = []

    def ring(project, container, pdk, **kwargs):
        calls.append(kwargs.get('librelane_state'))
        return runner.StepResult('pad_ring_gen', 'PASS', detail='native ring checked')

    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (SimpleNamespace(step_pad_ring_gen=ring), None, None, ''))
    monkeypatch.setattr(producers, '_read_step15_bounded_state', lambda *args: bound)
    result = producers.produce_pnr(tmp_path, {'step_id': '15.5ic', 'top': 'unit'})
    assert result['verdict'] == 'PASS'
    assert calls == [state]


def test_default_pad_ring_rejects_another_floorplan_native_ring(tmp_path, monkeypatch):
    state = tmp_path / 'phase3/librelane/old-floorplan/06-openroad-padring/state_out.json'
    state.parent.mkdir(parents=True)
    state.write_text('{}')
    handoff = tmp_path / 'reports/phase3/librelane_padring_handoff.json'
    handoff.parent.mkdir(parents=True)
    handoff.write_text(json.dumps({'state': str(state)}))
    bound = {'record': {'handoff_views': {'def': {
        'source': str(tmp_path / 'phase3/librelane/current-floorplan/11-openroad-generatepdn/chip.def')}}}}
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (SimpleNamespace(step_pad_ring_gen=lambda *a, **k:
                         pytest.fail('a different native ring reached the producer')),
                         None, None, ''))
    monkeypatch.setattr(producers, '_read_step15_bounded_state', lambda *args: bound)
    with pytest.raises(producers.em.Refusal, match='BACKEND_PADRING_STATE_CHANGED'):
        producers.produce_pnr(tmp_path, {'step_id': '15.5ic', 'top': 'unit'})


def test_pad_ring_native_report_still_runs_the_independent_gate(tmp_path, monkeypatch):
    calls = []
    state = tmp_path / 'native/state_out.json'
    for raw in ('phase3/stage3/pnr/padring.def', 'reports/phase3/padring.json',
                'reports/phase3/pad_assignment.json'):
        path = tmp_path / raw
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(runner._pr, 'run', run)
    result = runner.step_pad_ring_gen(tmp_path, librelane_state=state)
    assert result.status == 'PASS'
    assert [call[1].rsplit('/', 1)[-1] for call in calls] == [
        'pad_assignment_gen.py', 'pad_ring_gen.py', 'pad_ring_check.py']
    assert calls[1][-2:] == ['--librelane-state', str(state)]
    assert '--librelane-state' not in calls[2]


def test_default_placement_publishes_its_native_handoff_for_the_consumer(tmp_path, monkeypatch):
    canonical = tmp_path / 'reports/phase3/librelane_placement_handoff.json'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('{"state": "prior-placement"}')
    folder = tmp_path / 'native/current-placement'
    receipt = {'state': str(folder / 'state_out.json'),
               'views': {'def': {'dest_sha256': 'current-placed-def'}}}
    # The selected native chain also owns its post-GPL timing subject.
    # Bind its real fixture bytes through the unchanged publication validator.
    import hashlib
    folder.mkdir(parents=True)
    config = folder / 'config.json'
    config.write_text('{"scope":"neutral selected native transport"}\n')
    subject = folder / 'pnr_postgpl_timing.tcl'
    subject.write_text('puts "neutral selected post-GPL subject"\n')
    commands = folder / 'COMMANDS'
    commands.write_text('openroad ' + str(subject) + '\n')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    script_record = folder / 'pnr_postgpl_timing.json'
    script_record.write_text(json.dumps({
        'script': subject.name, 'sha256': digest(subject),
        'commands_sha256': digest(commands)}))
    ll = SimpleNamespace(flow_segment=lambda *a: [
        'OpenROAD.GlobalPlacement', 'OpenROAD.RepairDesignPostGPL',
        'OpenROAD.DetailedPlacement'],
        handoff_to_direct=lambda *a: receipt,
        validate_step_receipt=lambda *a: {
            'input': {'image': 'fixture', 'config': digest(config)},
            'sha256': {script_record.name: digest(script_record)}})
    monkeypatch.setattr(producers, '_parameters', lambda *args: (None, ll, None, ''))
    monkeypatch.setattr(producers, '_state_chain', lambda *args:
                        (ll, {'Vibeic.PostGPLFanoutClosure': config},
                         {'OpenROAD.DetailedPlacement': folder,
                          'Vibeic.PostGPLFanoutClosure': folder}))
    monkeypatch.setattr(producers, '_logs', lambda *args: None)
    result = producers.produce_pnr(tmp_path, {
        'step_id': '17', 'top': 'unit', 'image_id': 'fixture'})
    assert result['verdict'] == 'PASS'
    assert json.loads(canonical.read_text()) == receipt
    assert (tmp_path / producers.PNR / subject.name).read_bytes() == subject.read_bytes()


@pytest.mark.parametrize('role', ['producer', 'audit'])
def test_placement_report_identifies_the_actual_writer_for_the_consumer(
        tmp_path, monkeypatch, role):
    import placement_legality_check as placement
    import flow_declared_producer_run as declared
    import _gate_authorship as authorship

    monkeypatch.setenv(authorship.ROLE_ENV, role)
    output = tmp_path / 'placement.json'
    summary = {'placed_def': 'phase3/stage3/pnr/placed.def',
               'declared_components': 1, 'parsed_components': 1,
               'placed': 1, 'unplaced': 0, 'density_pct': None,
               'density_source': None}
    placement._emit(SimpleNamespace(json=str(output)), tmp_path,
                    'PASS', summary, [], None)
    document = json.loads(output.read_text())
    assert document['program'] == 'placement_legality_check'
    assert authorship.role_of(document) == role
    assert declared._producer_target_has_content(output) is (role == 'producer')


def test_spare_checkpoint_is_an_explicit_cts_input():
    import _flow_yaml
    rows = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    checkpoint = 'phase3/stage3/pnr/post_spare.def'
    assert checkpoint in rows['18']['required_outputs']
    assert {'from': 18, 'path': checkpoint} in rows['19']['required_inputs']


def test_spare_producer_preserves_placement_and_uses_its_native_state(tmp_path, monkeypatch):
    import hashlib
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    placed = pnr / 'placed.def'
    placed.write_text('current legal placement\n')
    state = tmp_path / 'native/placement/state_out.json'
    state.parent.mkdir(parents=True)
    state.write_text('{}')
    rpt = tmp_path / 'reports/phase3'
    rpt.mkdir(parents=True)
    (rpt / 'librelane_placement_handoff.json').write_text(json.dumps({
        'state': str(state), 'state_sha256': hashlib.sha256(state.read_bytes()).hexdigest(),
        'views': {'def': {'dest': str(placed),
                         'dest_sha256': hashlib.sha256(placed.read_bytes()).hexdigest()}}}))
    folder = tmp_path / 'native/spares'
    folder.mkdir(parents=True)
    (folder / 'spare_cells.json').write_text('{"count": 6}')
    captured = {}

    def chain(project, params, ids, predecessor, overlay):
        captured.update(params=params, overlay=overlay)
        return ll, {}, {'Vibeic.InsertSpareCells': folder}

    def handoff(native, destinations, receipt):
        for dest in destinations.values():
            dest.write_text('current placement with spares\n')
        return {'state': str(native), 'views': {}}

    ll = SimpleNamespace(handoff_to_direct=handoff)
    r = SimpleNamespace(_emit_spare_cell_coverage=lambda *a: None)
    monkeypatch.setattr(producers, '_parameters', lambda *a: (r, ll, None, ''))
    monkeypatch.setattr(producers, '_state_chain', chain)
    monkeypatch.setattr(producers, '_logs', lambda *a: None)
    result = producers.produce_pnr(tmp_path, {
        'step_id': '18', 'top': 'unit', 'spare_density': 0.05})
    assert result['verdict'] == 'PASS'
    assert placed.read_text() == 'current legal placement\n'
    assert (pnr / 'post_spare.def').read_text() == 'current placement with spares\n'
    assert captured['params']['state_in'] == str(state)
    assert captured['overlay']['VIBEIC_SPARE_DENSITY'][0] == 0.05
    assert (rpt / 'librelane_spare_handoff.json').is_file()


def test_stopped_default_window_does_not_audit_old_or_unexecuted_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, '_default_pnr_rows', lambda *args, **kwargs:
        runner.StepResult('pnr', 'NOT_MEASURED', detail='current input missing',
                          reason_class=runner._V.ReasonClass.INPUT_ABSENT,
                          extras={'canonical_gate_checks': {}}))
    monkeypatch.setattr(runner, '_phase3_window_full_gate_audit', lambda *args:
                        pytest.fail('Default repeated the gate or audited old outputs'))
    args = SimpleNamespace(entry_step='19', exit_step='20', container='',
                           die_um='auto', util=0.4)
    assert runner._run_phase3_window(tmp_path, 'unit', SimpleNamespace(name='unit'),
                                      args, ['default_pnr']) == 1
    saved = list((tmp_path / 'reports/audit/windows').glob('*/phase23_completion_audit.json'))
    assert len(saved) == 1
    report = json.loads(saved[0].read_text())
    assert report['verdict'] == 'NOT_MEASURED'
    assert report['declared_gate_checks']['20']['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('case', ['default', 'caller_false', 'caller_true',
                                  'tool_failure', 'missing_stage'])
def test_default_route_supplies_required_post_grt_policy_to_native_chain(
        tmp_path, monkeypatch, case):
    """Real producer/state-chain/gate filtering; only native I/O is modeled."""
    import drv_signoff_judge as drv
    import librelane_contract as ll
    import librelane_route as route

    segment = ['Odb.HeuristicDiodeInsertion', 'OpenROAD.GlobalRouting',
               route.POST_GRT_REPAIR, 'OpenROAD.ResizerTimingPostGRT', route.DRT]
    if case == 'missing_stage':
        segment.remove(route.POST_GRT_REPAIR)
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (runner, ll, SimpleNamespace(name='unit'), ''))
    monkeypatch.setattr(ll, 'flow_segment', lambda *args, **kwargs: list(segment))
    monkeypatch.setattr(runner, '_resolved_cell_policy',
                        lambda configs, *args: (configs, {}))
    state = tmp_path / 'current_post_hold_state.json'
    state.write_text('{}')
    monkeypatch.setattr(producers, '_predecessor_state', lambda *args: state)
    observed = {}

    def resolve(project, image, pdk, ids, **kwargs):
        # Model the native resolver's default false and explicit overlay.
        overlay = kwargs.get('overlay') or {}
        observed['overlay'] = dict(overlay)
        root = project / 'phase3/librelane' / kwargs['folder']
        root.mkdir(parents=True)
        gates = {
            route.POST_GRT_REPAIR: {'RUN_POST_GRT_DESIGN_REPAIR':
                overlay.get('RUN_POST_GRT_DESIGN_REPAIR', (False, 'image default'))[0]},
            'Odb.HeuristicDiodeInsertion': {'RUN_HEURISTIC_DIODE_INSERTION': False},
            'OpenROAD.ResizerTimingPostGRT': {'RUN_POST_GRT_RESIZER_TIMING': False}}
        (root / 'flow_gates.json').write_text(json.dumps(gates))
        configs = {sid: root / (sid + '.json') for sid in ids}
        for config in configs.values():
            config.write_text(json.dumps({'DESIGN_NAME': 'unit'}))
        return configs

    monkeypatch.setattr(ll, 'resolve_step_configs', resolve)

    class AtNativeChain(RuntimeError):
        pass

    def native(project, image, chain, **kwargs):
        observed['ordered_steps'] = [sid for sid, _, _ in chain]
        observed['input_states'] = [str(value) for _, _, value in chain]
        root = project / 'phase3/librelane/execution-backend-21-config'
        observed['flow_gates'] = json.loads((root / 'flow_gates.json').read_text())
        if case == 'tool_failure':
            raise ll.Refusal('LL_STEP_FAILED', 'SOURCE_CONTROL native tool failed')
        raise AtNativeChain('SOURCE_CONTROL native boundary reached')

    monkeypatch.setattr(ll, 'run_chain', native)
    caller = ({'RUN_POST_GRT_DESIGN_REPAIR': (
                  case == 'caller_true', 'explicit neutral caller')}
              if case in ('caller_false', 'caller_true') else {})
    params = {'step_id': '21', 'top': 'unit', 'pdk_name': 'unit',
              'image_id': 'unit-image', 'pdk_root': str(tmp_path), 'overlay': caller}
    if case == 'tool_failure':
        with pytest.raises(ll.Refusal, match='LL_STEP_FAILED'):
            producers.produce_pnr(tmp_path, params)
        observed['outcome'] = 'REFUSED'
    else:
        with pytest.raises(AtNativeChain, match='native boundary reached'):
            producers.produce_pnr(tmp_path, params)
        observed['outcome'] = 'NATIVE_CHAIN_SUBMITTED'
    (tmp_path / 'default21-policy.observation.json').write_text(
        json.dumps(observed, indent=2) + '\n')

    ids = observed['ordered_steps']
    expected = case not in ('caller_false', 'missing_stage')
    assert (route.POST_GRT_REPAIR in ids) is expected, observed
    assert 'Odb.HeuristicDiodeInsertion' not in ids, observed
    assert 'OpenROAD.ResizerTimingPostGRT' not in ids, observed
    assert observed['input_states'] == [str(state)] * len(ids), observed
    if caller:
        assert observed['overlay']['RUN_POST_GRT_DESIGN_REPAIR'] == \
            caller['RUN_POST_GRT_DESIGN_REPAIR']
    elif case != 'missing_stage':
        assert observed['overlay']['RUN_POST_GRT_DESIGN_REPAIR'] == \
            route.POST_GRT_DESIGN_REPAIR['RUN_POST_GRT_DESIGN_REPAIR']
    if expected:
        assert ids.index(route.POST_GRT_REPAIR) < ids.index(route.DRT), observed
    else:
        judged = drv.judge({'identity': {}, 'frozen': {}, 'current': {},
                            'stages': [], 'pins': {}, 'scenes': []})
        assert judged['verdict'] == 'FAIL'
        assert 'post_grt_repair: required stage absent' in judged['failures']


@pytest.mark.parametrize('refuse', [False, True])
def test_step32_refreshes_sdc_before_input_binding_without_upstream_rerun(
        tmp_path, monkeypatch, refuse):
    """Exercise the real front door, publisher and retained output history.

    The canonical author is the controlled edge; binding observes actual new
    bytes. A refusal must stop before binding or any native producer.
    """
    import hashlib
    from _ppa import timing
    from test_backend_input_contract_sdc import _project
    project = _project(tmp_path)
    pnr = project / 'phase3/stage3/pnr'
    protected = [project / 'phase2/stage2/synth/netlist.v',
                 pnr / 'routed.def', pnr / 'unit_pnr.v']
    protected[1].write_text('retained routed DEF\n')
    protected[2].write_text('retained routed netlist\n')
    before = {path: path.read_bytes() for path in protected}
    provenance = pnr / 'constraint_sdc_provenance.json'
    provenance.write_text('{"old_provenance":true}\n')
    constraints = project / 'phase2/stage2/constraints'
    old = {path.relative_to(project): path.read_bytes() for path in (
        pnr / 'constraint.sdc', provenance, constraints / 'spm.asic.sdc',
        constraints / timing.ASIC_SDC_RECORD)}
    deck = 'create_clock -period 24 [get_ports clk]\nset_max_transition 3 [current_design]\n'
    calls = []
    def derive(rt, root, top, pdk, container):
        calls.append('canonical_sdc')
        assert root == project and top == 'unit'
        # The canonical author can refresh its own files before it discovers
        # an invalid physical derivation; the earlier evidence must survive.
        (constraints / 'spm.asic.sdc').write_text(deck)
        if refuse:
            raise ValueError('physical SDC source refused')
        return {'text': deck, 'path': 'phase2/stage2/constraints/spm.asic.sdc',
                'step7_sha256': hashlib.sha256(deck.encode()).hexdigest(),
                'deck_sha256': hashlib.sha256(deck.encode()).hexdigest(),
                'regenerated': 'source changed', 'derivation': None}
    receipt_path = project / 'reports/phase3/default_steps/32/backend_result.json'
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text('{"verdict":"PASS","old_result":true}')
    monkeypatch.setattr(timing, 'asic_sdc_for_pnr', derive)
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *_: {})
    def bind(context, sid, *, parameters):
        calls.append('bind')
        assert sid == '32' and (pnr / 'constraint.sdc').read_text() == deck
        assert json.loads(provenance.read_text())['deck_sha256'] == hashlib.sha256(deck.encode()).hexdigest()
        # Stop at the actual input binding boundary: no native tool needed to
        # prove that it receives the current deck rather than the retained one.
        parameters['resolved_input_manifest'] = {'files': {}, 'missing': ['controlled native boundary']}
    monkeypatch.setattr(execution_policy, '_fixed_inputs', bind)
    monkeypatch.setattr(producers, 'produce', lambda *_a, **_k: pytest.fail('native producer unexpectedly started'))
    result = runner._default_pnr_rows(project, 'unit', SimpleNamespace(name='unit'), '', ['32'])
    assert result.status == 'NOT_MEASURED'
    assert calls == (['canonical_sdc'] if refuse else ['canonical_sdc', 'bind'])
    assert {path: path.read_bytes() for path in protected} == before
    archives = list((project / 'reports/phase3/sdc_resume_history').iterdir())
    assert len(archives) == 1
    assert {rel: (archives[0] / rel).read_bytes() for rel in old} == old
    if refuse:
        assert 'physical SDC source refused' in result.detail
        receipt = json.loads(receipt_path.read_text())
        assert receipt['verdict'] == 'NOT_MEASURED' and receipt['native_started'] is False
        assert 'old_result' not in receipt and receipt['outputs'] == {}
        assert (pnr / 'constraint.sdc').read_bytes() == old[Path('phase3/stage3/pnr/constraint.sdc')]
        assert provenance.read_bytes() == old[Path('phase3/stage3/pnr/constraint_sdc_provenance.json')]


@pytest.mark.parametrize("exceptional_exit", [False, True])
def test_inprocess_main_restores_runtime_guard_before_other_consumers(
        tmp_path, exceptional_exit):
    """Real main keeps its guard active, then releases test-owned process state."""
    import os
    import sys
    import runtime_program_tree as runtime_tree
    # Load the fixture module before snapshotting the invocation boundary.
    import test_phase3_postpnr_disclosure_and_gds_guard as fixture_module
    original_drive = fixture_module._drive
    names = ("PROGRAMS_DIR", "_RUNTIME_PROGRAM_TREE", "__file__")
    before = {name: getattr(runner, name) for name in names}
    calls = {name: getattr(runner._pr, name) for name in ("run", "run_best_effort")}
    paths = []
    env_names = (runtime_tree.ENV_ROOT, runtime_tree.ENV_MANIFEST,
                 "PYTHONDONTWRITEBYTECODE", "EDA_CONTAINER")
    environment = {name: os.environ.get(name) for name in env_names}
    bytecode = sys.dont_write_bytecode

    class EndInvocation(Exception):
        pass

    try:
        with pytest.MonkeyPatch.context() as patches:
            def capture_invocation_boundary(*args, **kwargs):
                # Project preparation imports helpers; _drive owns main's scope.
                paths[:] = sys.path
                return original_drive(*args, **kwargs)
            patches.setattr(fixture_module, "_drive", capture_invocation_boundary)
            _prebackend_consumer_control(tmp_path, patches, {"7": "FAIL"})
            assert runner._RUNTIME_PROGRAM_TREE is not None
            assert runner.PROGRAMS_DIR != before["PROGRAMS_DIR"]
            with pytest.raises(runtime_tree.RuntimeTreeError,
                               match="LIVE_PLUGIN_PATH_AFTER_RETENTION"):
                runner._verify_runtime_command([sys.executable, before["__file__"]])
            if exceptional_exit:
                raise EndInvocation()
    except EndInvocation:
        assert exceptional_exit

    assert {name: getattr(runner, name) for name in names} == before
    assert all(getattr(runner._pr, name) is original for name, original in calls.items())
    assert paths and sys.path == paths
    assert sys.dont_write_bytecode == bytecode
    assert {name: os.environ.get(name) for name in env_names} == environment
    consumer = runner._pr.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", before["__file__"]],
        capture_output=True, text=True)
    assert consumer.returncode == 0
    assert consumer.stdout.strip() == before["__file__"]


def _retained_step17_control(tmp_path, monkeypatch):
    import flow109_clock_plan as clock_adapter

    project = tmp_path
    placed = project / 'phase3/stage3/pnr/placed.def'
    handoff = project / 'reports/phase3/librelane_placement_handoff.json'
    backend = project / 'reports/phase3/default_steps/17/backend_result.json'
    for path, body in ((placed, 'VERSION 5.8 ;\nDESIGN unit ;\nEND DESIGN\n'),
                       (handoff, '{"native":"detailed-placement"}\n')):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    output_hash = runner._sha256_file(placed)
    result = {
        'schema': 'vibeic/backend-result/2', 'step_id': '17', 'verdict': 'PASS',
        'producer_verdict': 'PASS',
        'gates': {'backend_canonical': 'PASS', 'backend_native_substance': 'PASS'},
        'missing_outputs': [],
        'outputs': {'phase3/stage3/pnr/placed.def': output_hash},
    }
    backend.parent.mkdir(parents=True, exist_ok=True)
    backend.write_text(json.dumps(result))
    request = project / 'reports/flow109/D34/attempt/step17_reuse_request.json'
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({
        'schema': 'vibeic.flow109.step17-reuse-request.v1',
        'source_census_count': 7, 'source_census_sha256': 'source-census',
        'pdk': 'unit-pdk',
        'retained_step_folder': 'phase3/stage3/17_old',
        'backend_result_sha256': runner._sha256_file(backend),
        'placed_def_sha256': output_hash,
        'native_handoff_sha256': runner._sha256_file(handoff),
    }))
    monkeypatch.setenv(clock_adapter.STEP17_REUSE_ENV, str(request))
    retained = {
        'folder': 'phase3/stage3/17_old', 'current_inputs': True,
        'canonical_pass': True, 'status': 'PASS',
        'inputs': {'input/a': 'input-hash'}, 'result': result,
    }
    versions = SimpleNamespace(
        latest_pass=lambda *_: retained,
        publish_producer_outputs=lambda *_: {'published': True})
    producer_api = SimpleNamespace(
        _run_current_step_declared_producers=lambda *_: {'verdict': 'PRODUCED'},
        _current_step_producer_authority=lambda *_a, **_k: (True, '', 'PASS'))
    worker_api = SimpleNamespace(execute_current_step=lambda *_a, **_k: {
        'verdict': 'PASS', 'outputs': result['outputs']})
    return project, placed, versions, producer_api, worker_api


def test_retained_step17_reuses_exact_native_bytes_and_runs_current_consumer(
        tmp_path, monkeypatch):
    project, _, versions, producer_api, worker_api = _retained_step17_control(
        tmp_path, monkeypatch)
    receipt = runner._reuse_current_default_step17(
        project, SimpleNamespace(name='unit-pdk'),
        {'files': {'input/a': 'input-hash'}}, {}, {},
        versions, producer_api, worker_api)
    assert receipt['verdict'] == 'PASS'
    assert receipt['retained_native_producer'] is True
    assert receipt['retained_source_census_sha256'] == 'source-census'


def test_retained_step17_refuses_changed_native_output_before_consumer(
        tmp_path, monkeypatch):
    project, placed, versions, producer_api, _ = _retained_step17_control(
        tmp_path, monkeypatch)
    placed.write_text('VERSION 5.8 ;\nDESIGN changed ;\nEND DESIGN\n')
    worker_api = SimpleNamespace(execute_current_step=lambda *_a, **_k:
                                 pytest.fail('consumer reached changed native output'))
    with pytest.raises(ValueError, match='D35_RETAINED_IDENTITY_CHANGED'):
        runner._reuse_current_default_step17(
            project, SimpleNamespace(name='unit-pdk'),
            {'files': {'input/a': 'input-hash'}}, {}, {},
            versions, producer_api, worker_api)


def test_retained_step17_refuses_cross_pdk_reuse_before_consumer(
        tmp_path, monkeypatch):
    project, _, versions, producer_api, _ = _retained_step17_control(
        tmp_path, monkeypatch)
    worker_api = SimpleNamespace(execute_current_step=lambda *_a, **_k:
                                 pytest.fail('consumer reached cross-PDK output'))
    with pytest.raises(ValueError, match='D35_RETAINED_REQUEST_INVALID'):
        runner._reuse_current_default_step17(
            project, SimpleNamespace(name='different-pdk'),
            {'files': {'input/a': 'input-hash'}}, {}, {},
            versions, producer_api, worker_api)
