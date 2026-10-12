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
        producers.produce_pnr(tmp_path, {"step_id": "15", "top": "unit", "die_um": "100,100", "util": .2})


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
    assert producers._predecessor_state(tmp_path, 'post_cts.def') == cts_state
    assert producers._predecessor_state(tmp_path, 'post_hold.def') == hold_state
    cts_def.write_text('changed after its handoff\n')
    with pytest.raises(producers.em.Refusal, match='BACKEND_PREDECESSOR_STATE_UNBOUND'):
        producers._predecessor_state(tmp_path, 'post_cts.def')


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
    assert runner._phase3_window_sites(first, last) == ['default_pnr']


@pytest.mark.parametrize('first,last', [('23', '23'), ('24', '24'),
                                      ('23', '30'), ('22', '24')])
def test_default_signoff_selects_existing_producers_without_enclosing_run(
        first, last, monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    assert runner._phase3_window_sites(first, last) == ['default_backend']


def test_ultra_signoff_retains_its_existing_dispatch(monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    assert runner._phase3_window_sites('23', '24') == ['enclosing_canonicalize']


def test_default_retains_the_existing_individual_layout_release_producers(monkeypatch):
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'default'})
    assert runner._phase3_window_sites('37', '37') == ['gds']
    assert runner._phase3_window_sites('31', '31') == ['drc', 'lvs']
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
    assert captured == ['15', '15.5ic', '16', '17', '18', '19', '20', '21', '22']
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
    # Read the actual shipped YAML order, including the IC finishing row.
    # That row already has a GDS writer owner and is completed at stream-out.
    expected = [sid for sid in runner._phase3_window_steps('23', '35')
                if sid != '26.5ic']
    assert captured == expected == ['23', '24', '25', '26', '27', '28',
                                   '29', '30', '33', '34', '35']
    assert result.status == 'FAIL' and result.detail == 'canonical step 23'


@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_full_default_prestream_stops_on_the_actual_failed_row(
        tmp_path, monkeypatch, status):
    calls = []
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
    result = runner.step_prestream_gate(
        tmp_path, 'unit', SimpleNamespace(name='unit'), '')
    assert calls == [('producer', '23'), ('consumer', '23')]
    assert result.status == status
    assert 'canonical step 23' in result.detail
    receipt = json.loads((tmp_path / 'reports/phase3/prestream_gate.json').read_text())
    assert receipt['verdict'] == status
    assert receipt['layout_digest'] == 'current-layout'
    assert receipt['evidence']['extras']['canonical_steps'][0]['extras']['step_id'] == '23'


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
    pnr = runner._pl.pnr_dir(tmp_path)
    rpt = runner._pl.reports_phase3_dir(tmp_path)
    pnr.mkdir(parents=True)
    rpt.mkdir(parents=True)
    inputs = {
        pnr / 'unit.def': b'CURRENT ROUTED DEF\n',
        pnr / 'routed.def': b'CURRENT ROUTED DEF\n',
        pnr / 'pdn.done': b'ACTUAL STEP 15 PDN\n',
        pnr / 'constraint.sdc': b'CURRENT SDC\n',
        runner._pl.extracted_dir(tmp_path) / 'unit.spef': b'ACTUAL STEP 22 SPEF\n',
        runner._pl.cts_dir(tmp_path) / 'clock_plan.json': b'ACTUAL STEP 16 PLAN\n',
        pnr / 'filled.def': b'ACTUAL STEP 34 FILL\n',
        pnr / 'unit.gds': b'CURRENT STREAM\n',
        runner._pl.constraints_dir(tmp_path) / 'pvt_matrix.json': b'{}\n',
    }
    for path, body in inputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    calls = []

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
        tmp_path, 'unit', SimpleNamespace(name='unit'), '', prepv=prepv)
    assert calls == (['erc'] if prepv else ['lec', 'density', 'aging', 'thermal', 'perc', 'atpg'])
    expected = ('NOT_MEASURED' if prepv else 'FAIL') if failed_evidence else 'PASS'
    assert result.status == expected, result.detail
    for path, body in inputs.items():
        assert path.read_bytes() == body, path
    assert (runner._pl.gds_dir(tmp_path) / 'unit.gds').read_bytes() == inputs[pnr / 'unit.gds']


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
    runner.main()
    assert later == []
    assert 'gds' not in transport.called
    rows = _plan(project)
    assert rows['postroute_repair_librelane']['status'] == 'FAIL'
    assert rows['gds']['status'] == 'NOT_MEASURED'


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

    def program(project, sid):
        calls.append(('producer', sid))
        assert project == tmp_path and sid == '35'
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
    ll = SimpleNamespace(flow_segment=lambda *a: [
        'OpenROAD.GlobalPlacement', 'OpenROAD.RepairDesignPostGPL',
        'OpenROAD.DetailedPlacement'],
        handoff_to_direct=lambda *a: receipt)
    monkeypatch.setattr(producers, '_parameters', lambda *args: (None, ll, None, ''))
    monkeypatch.setattr(producers, '_state_chain', lambda *args:
                        (ll, {}, {'OpenROAD.DetailedPlacement': folder}))
    monkeypatch.setattr(producers, '_logs', lambda *args: None)
    result = producers.produce_pnr(tmp_path, {
        'step_id': '17', 'top': 'unit', 'image_id': 'fixture'})
    assert result['verdict'] == 'PASS'
    assert json.loads(canonical.read_text()) == receipt


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
