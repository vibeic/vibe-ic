"""Native report dispatch controls; no synthesis, STA or proof is launched."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _delivery_route
import flow109
from test_flow109_selection import profile


def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def case(project, step):
    rtl = project / 'phase2/stage1/rtl/neutral.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module neutral(input d, output q); assign q=d; endmodule\n')
    netlist = project / 'phase2/stage2/synth/neutral.v'
    netlist.parent.mkdir(parents=True)
    netlist.write_text(rtl.read_text())
    put(netlist.parent / 'synth_inputs.json', {
        'rtl_sha256': {'neutral.v': flow109._file_digest(rtl)}})
    if step in ('D11', 'D30'):
        path = ('reports/phase2/lint/verilator_lint_gate.json' if step == 'D11'
                else 'phase3/librelane/02-yosys-synthesis/handoff_netlist_gate.json')
        put(project / path, {'verdict': 'PASS'})
    elif step == 'D13':
        put(project / 'reports/phase2/sim/l10_execution.json', {
            'cases': [{'id': 'neutral_case', 'verdict': 'PASS', 'sim_executed': True}]})
        put(project / 'requirements/base_07/required_function_scenarios.json', {
            'required_items': [{'name': 'neutral_case'}]})
        put(project / 'reports/phase2/coverage/coverage_verilator.json', {
            'scope_files': [str(rtl)], 'totals': {'branch': {'pct': 100, 'total': 2}}})
        put(project / 'requirements/base_07/coverage_targets.json', {
            'limits': {'branch': {'min': 95}}, 'acceptance_applicable': True,
            'reason': 'declared neutral source coverage target'})
    elif step == 'D14':
        put(project / 'phase2/stage1/formal/results.json', {
            'properties': [{'task': 'safety', 'status': 'PASS', 'bound': 'unbounded'}],
            'formal_completion': 'INCOMPLETE', 'unresolved_obligations': ['port name binding']})
        put(project / 'requirements/base_08/proof_partition_coverage.json', {
            'required_items': [{'task': 'safety'}]})
    elif step == 'D22':
        put(project / 'phase3/librelane/02-yosys-synthesis/state_out.json', {
            'metrics': {'design__instance_unmapped__count': 0,
                        'synthesis__check_error__count': 0}})
    elif step == 'D25':
        folder = project / 'native/eqy'
        status = folder / 'scratch/strategies/neutral.q/pdr/status'
        status.parent.mkdir(parents=True)
        status.write_text('PASS\n')
        (folder / 'scratch/partition.list').write_text('neutral neutral.q : q\n')
        ref = lambda p: {'path': p.relative_to(project).as_posix(),
                         'sha256': flow109._file_digest(p)}
        put(project / 'reports/lec_eqy_execution.json', {
            'native_directory': 'native/eqy',
            'subject': {'rtl': [ref(rtl)], 'gate_netlist': ref(netlist)}})
    else:
        sdc = project / 'phase2/stage2/constraints/neutral.sdc'
        sdc.parent.mkdir(parents=True)
        sdc.write_text('create_clock -period 10 [get_ports clk]\n')
        folder = project / 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr'
        put(folder / 'config.json', {'PNR_SDC_FILE': str(sdc)})
        put(folder / 'state_in.json', {'nl': str(netlist)})
        put(folder / 'input_fingerprint.json', {
            'state_files': {str(netlist): flow109._file_digest(netlist)},
            'config_files': {str(sdc): flow109._file_digest(sdc)}})
        put(folder / 'state_out.json', {'metrics': {
            'timing__setup__ws__corner:tt': 1.0,
            'timing__hold__ws__corner:tt': 0.2}})
        corner = folder / 'tt'
        corner.mkdir()
        (corner / 'sta.log').write_text('Native report reader control\n')
        (corner / 'checks.rpt').write_text('check_setup\n')
        put(project / 'requirements/base_13/prelayout_timing_targets.json', {
            'limits': {'setup_ws': {'min': 0}}, 'units': {'setup_ws': 'ns'}})
    assert _delivery_route.admit(project, 'ic') is None
    manifest = project / 'selection.json'
    put(manifest, {'features': profile()})
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode='default',
        entry_step=step, exit_step=step)
    return args, rtl


@pytest.mark.parametrize('step', ['D11', 'D13', 'D14', 'D22', 'D25', 'D26', 'D30'])
def test_public_frontend_reads_native_reports_without_a_producer_rerun(tmp_path, monkeypatch, step):
    args, _ = case(tmp_path, step)
    monkeypatch.setattr(flow109, 'dft_source_intent', lambda *a: pytest.fail(
        'completed native work must not enter the old DFT receipt wrapper'))
    assert flow109.prepare_front_door(args, tmp_path) == 0
    row = json.loads((tmp_path / f'reports/flow109/default_rows/{step}.json').read_text())
    assert row['default_row_status'] == 'PASS'
    assert row['native_started'] is False
    assert row['native_measurements']


@pytest.mark.parametrize('step', ['D22', 'D25', 'D26'])
def test_changed_rtl_returns_to_the_normal_producer(tmp_path, monkeypatch, step):
    args, rtl = case(tmp_path, step)
    rtl.write_text(rtl.read_text().replace('q=d', 'q=~d'))
    def producer(*args):
        raise RuntimeError('normal producer required')
    monkeypatch.setattr(flow109, 'dft_source_intent', producer)
    with pytest.raises(RuntimeError, match='normal producer required'):
        flow109.prepare_front_door(args, tmp_path)
    assert not (tmp_path / f'reports/flow109/default_rows/{step}.json').exists()


@pytest.mark.parametrize('step', ['D11', 'D13', 'D14', 'D22', 'D25', 'D26', 'D30'])
def test_native_report_failure_is_published_with_the_original_limit(tmp_path, monkeypatch, step):
    args, _ = case(tmp_path, step)
    if step in ('D11', 'D30'):
        path = ('reports/phase2/lint/verilator_lint_gate.json' if step == 'D11'
                else 'phase3/librelane/02-yosys-synthesis/handoff_netlist_gate.json')
        put(tmp_path / path, {'verdict': 'FAIL'})
    elif step == 'D13':
        put(tmp_path / 'reports/phase2/sim/l10_execution.json', {
            'cases': [{'id': 'neutral_case', 'verdict': 'FAIL', 'sim_executed': True}]})
    elif step == 'D14':
        put(tmp_path / 'phase2/stage1/formal/results.json', {
            'properties': [{'task': 'safety', 'status': 'FAIL'}]})
    elif step == 'D25':
        (tmp_path / 'native/eqy/scratch/strategies/neutral.q/pdr/status').write_text('FAIL\n')
    else:
        relative = ('phase3/librelane/02-yosys-synthesis/state_out.json' if step == 'D22'
                    else 'phase3/librelane/prelayout/design_sdc/02-openroad-staprepnr/state_out.json')
        path = tmp_path / relative
        state = json.loads(path.read_text())
        state['metrics']['synthesis__check_error__count' if step == 'D22'
                         else 'timing__setup__ws__corner:tt'] = 1 if step == 'D22' else -0.1
        put(path, state)
    monkeypatch.setattr(flow109, 'dft_source_intent', lambda *a: pytest.fail(
        'the native failure must reach the public result'))
    assert flow109.prepare_front_door(args, tmp_path) == 1
    row = json.loads((tmp_path / f'reports/flow109/default_rows/{step}.json').read_text())
    assert row['default_row_status'] == 'FAIL'


@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_d12_uses_existing_role_aware_acceptance(tmp_path, monkeypatch, status):
    import design_one_shot_runner as owner
    import flow109_metric_acceptance as metrics
    import librelane_contract as native
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D12', 'D12')
    for name in ('cdc_reg_crossing', 'cdc_async_input', 'cdc_reset_dep'):
        put(tmp_path / f'reports/phase2/gates/{name}.json', {'passed': False})
    assert flow109._retained_frontend_result(tmp_path, context) is None
    accepted = {'status': status, 'reason': 'current role-aware observation',
                'observed': {'findings': [] if status == 'PASS' else [{'rule': 'blocking finding'}]}}
    monkeypatch.setattr(native, 'local_image_attestation', lambda: {})
    monkeypatch.setattr(metrics, 'accept_d12', lambda project, current: accepted)
    result = owner.step_d12_cdc_rdc(tmp_path, context)
    assert result.status == status
    assert result.extras['metric_acceptance'] == accepted


def test_missing_formal_result_reaches_the_native_producer(tmp_path, monkeypatch):
    import design_one_shot_runner as owner
    import formal_harness_gen as generator
    import formal_property_run as producer
    import p0_tool_frontend_check as frontend
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    monkeypatch.setattr(flow109, '_bound_attempt', lambda *a: attempt)
    monkeypatch.setattr(frontend, '_top', lambda *a: 'neutral')
    monkeypatch.setattr(generator, 'generate', lambda **kw: {
        'verdict': 'EMITTED', 'harness_path': str(tmp_path / 'neutral.sv'),
        'rtl_files': [], 'harness_module': 'neutral'})
    def native(*a, **kw):
        raise RuntimeError('native producer reached')
    def old_reader(*a, **kw):
        raise RuntimeError('read-only path reached before native producer')
    monkeypatch.setattr(producer, 'run', native)
    monkeypatch.setattr(owner, 'step_d14_formal_read', old_reader)
    with pytest.raises(RuntimeError, match='^native producer reached$'):
        owner._publish_d14_owner(tmp_path, {})


def test_missing_lint_result_reaches_the_native_route(tmp_path, monkeypatch):
    import design_one_shot_runner as owner
    import flow109_metric_acceptance as metrics
    import librelane_contract as native
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    selected = tmp_path / 'context.json'
    put(selected, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(selected))
    monkeypatch.setattr(metrics, 'accept_d11', lambda *a: {
        'status': 'NOT_MEASURED', 'component_status': 'NOT_MEASURED', 'reason': 'old qualification'})
    monkeypatch.setattr(metrics, 'd11_fresh_request', lambda *a: False)
    def route(*a):
        raise RuntimeError('native lint route reached')
    monkeypatch.setattr(native, 'selected_mode', route)
    with pytest.raises(RuntimeError, match='^native lint route reached$'):
        owner.step_rtl_lint_tool(tmp_path)
