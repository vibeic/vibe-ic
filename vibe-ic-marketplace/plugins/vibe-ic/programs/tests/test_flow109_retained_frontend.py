"""Native report dispatch controls; no synthesis, STA or proof is launched."""
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import _delivery_route
import flow109
from test_flow109_selection import profile


def hygiene_owner(project, monkeypatch, native_status='PASS'):
    """Actual owner/report writers; only native process output is SOFTWARE."""
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as owner
    import _path_layout as layout
    case(project, 'D11')
    (project / 'reports/phase2/lint/verilator_lint_gate.json').unlink()
    (project / 'phase2/stage2/synth/synth_inputs.json').unlink()
    put(project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'neutral'})
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    selected = project / 'selected.json'; put(selected, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(selected))
    attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    monkeypatch.setattr(layout, '_RTL_INPUT', (None, 'structured'))

    def software_native(command, **kwargs):
        lint = project / 'reports/phase2/lint'
        work = Path(tempfile.mkdtemp(prefix='native-elaboration-SOFTWARE-', dir=lint))
        rtl = project / 'phase2/stage1/rtl/neutral.v'
        graph = work / 'design.json'; put(graph, {'modules': {'neutral': {}}})
        (work / 'native.log').write_text('SOFTWARE boundary; no native execution\n')
        native = {'top': 'neutral', 'files': [str(rtl)], 'defines': [], 'parameters': [],
            'include_dirs': [str(rtl.parent)], 'backend': 'SOFTWARE', 'image': None,
            'input_sha256': {str(rtl): flow109._file_digest(rtl)},
            'native_returncode': 7 if native_status == 'NATIVE_FAIL' else 0 if native_status != 'NOT_MEASURED' else None,
            'transport_returncode': 7 if native_status == 'NATIVE_FAIL' else 0 if native_status != 'NOT_MEASURED' else None,
            'status': 'MEASURED' if native_status in ('PASS', 'FAIL') else 'NOT_MEASURED',
            'native_json_sha256': flow109._file_digest(graph)}
        put(work / 'context.json', native)
        put(lint / 'rtl_hygiene.json', [] if native_status != 'FAIL' else
            [{'severity': 'ERROR', 'rule': 'SOFTWARE-finding'}])
        return SimpleNamespace(returncode=0 if native_status == 'PASS' else 1,
            stdout='SOFTWARE native process boundary', stderr='')

    monkeypatch.setattr(owner._pr, 'run', software_native)
    row = owner._step_rtl_hygiene_native(project)
    row.extras['context_sha256'] = context['context_sha256']
    argv = [sys.executable, str(Path(owner.__file__).with_name('phase2_one_shot_runner.py')),
            str(project), '--entry-step', '2', '--exit-step', '2']
    invocation = {'invocation_id': 'SOFTWARE-current-owner', 'argv': argv,
        'project': str(project), 'source': dispatch._runner_source_snapshot(argv)}
    summary = {'project': str(project), 'verdict': row.status,
        'steps': [asdict(owner.StepResult('rtl_gen', 'NOT_APPLICABLE', 0,
            'supplied RTL', declared_by='--entry-step 2')), asdict(row)],
        'declared_window': {'entry_step': '2', 'exit_step': '2', 'dispatched_step_ids': ['2']}}
    path = attempt / 'phase2_one_shot.json'
    owner._write_phase2_report(path, summary, project, invocation_context=invocation)
    return context, path, invocation


@pytest.mark.parametrize('native_status,status', [('PASS','PASS'), ('FAIL','FAIL'),
    ('NATIVE_FAIL','FAIL'), ('NOT_MEASURED','NOT_MEASURED')])
def test_d11_current_hygiene_owner_without_synthesis(tmp_path, monkeypatch, native_status, status):
    import vibe_ic_one_shot_runner as runner
    _, path, invocation = hygiene_owner(tmp_path, monkeypatch, native_status)
    result = runner._finish_d11_selected_owner(tmp_path, json.loads(path.read_bytes()),
        invocation, published_current=True)
    assert result['verdict'] == status, result
    assert result['whole_flow_verdict'] == 'NOT_MEASURED'


@pytest.mark.parametrize('mutation', ['not_published', 'wrong_invocation', 'context_changed',
    'output_changed', 'source_changed', 'context_missing', 'empty_population', 'unrelated_row'])
def test_d11_current_hygiene_owner_refuses_stale_evidence(tmp_path, monkeypatch, mutation):
    import vibe_ic_one_shot_runner as runner
    _, path, invocation = hygiene_owner(tmp_path, monkeypatch)
    report = json.loads(path.read_bytes())
    row = report['steps'][-1]
    if mutation == 'wrong_invocation': invocation = {**invocation, 'invocation_id': 'foreign'}
    elif mutation == 'context_changed':
        context = Path(next(p for p in row['output_files'] if p.endswith('context.json')))
        put(context, {**json.loads(context.read_bytes()), 'image': 'foreign-image'})
    elif mutation == 'output_changed':
        put(tmp_path / 'reports/phase2/lint/rtl_hygiene.json', [{'severity': 'ERROR'}])
    elif mutation == 'source_changed':
        (tmp_path / 'phase2/stage1/rtl/neutral.v').write_text('module changed; endmodule\n')
    elif mutation == 'context_missing':
        Path(next(p for p in row['output_files'] if p.endswith('context.json'))).unlink()
    elif mutation == 'empty_population': row['extras']['native_context']['files'] = []
    elif mutation == 'unrelated_row': row['extras']['step_id'] = '4'
    if mutation in ('empty_population', 'unrelated_row'): put(path, report)
    result = runner._finish_d11_selected_owner(tmp_path, report, invocation,
        published_current=mutation != 'not_published')
    assert result['verdict'] == 'NOT_MEASURED', result


def test_d11_source_owned_structured_current_publication(tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as owner
    import benchmark_io_adapter as adapter
    _, path, invocation = hygiene_owner(tmp_path, monkeypatch)
    report = json.loads(path.read_bytes())
    parent_argv = [sys.executable, str(Path(owner.__file__).with_name('vibe_ic_one_shot_runner.py')),
        str(tmp_path), '--entry-step', 'D11', '--exit-step', 'D13']
    parent = {'invocation_id': 'SOFTWARE-parent', 'argv': parent_argv,
        'project': str(tmp_path), 'source': dispatch._runner_source_snapshot(parent_argv)}
    monkeypatch.setenv(dispatch._RUNNER_PARENT_CONTEXT_ENV, json.dumps(parent))
    observed = 'PUBLISHED'
    try:
        owner._write_phase2_report(path, report, tmp_path, invocation_context=invocation,
            publish_current=True)
    except ValueError as exc:
        observed = str(exc)
    assert observed == 'PUBLISHED'
    current = json.loads((tmp_path / 'reports/orchestrator/phase2_one_shot.json').read_bytes())
    assert current['runner_binding']['invocation_id'] == parent['invocation_id']
    assert current['runner_binding']['owner_report']['sha256'] == flow109._file_digest(path)
    dispatch._runner_owner_report_current(tmp_path, current['runner_binding'], {
        **parent, 'source_before': parent['source'],
        'material_after': dispatch._runner_material_snapshot(tmp_path)})
    assert adapter._rtl_gen_verdict(tmp_path)['status'] == 'NOT_APPLICABLE'


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_d11_public_hygiene_child_publishes_and_finishes(tmp_path, monkeypatch, status):
    import os
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as owner
    import librelane_contract as contract
    from test_flow109_selection import _public_d09_entry
    hygiene_owner(tmp_path, monkeypatch, status)
    runner = _public_d09_entry(tmp_path, monkeypatch)
    argv = list(sys.argv)
    for flag in ('--entry-step', '--exit-step'): argv[argv.index(flag) + 1] = 'D11'
    monkeypatch.setattr(sys, 'argv', argv)
    children = []

    def child(command, *, env=None, **kwargs):
        children.append(command)
        with monkeypatch.context() as m:
            for key, value in env.items(): m.setenv(key, value)
            m.setattr(sys, 'argv', command[1:])
            m.setattr(owner, '_activate_runtime_program_tree', lambda *_: None)
            m.setattr(owner, '_bootstrap_execution_policy', lambda *_, **__: None)
            m.setattr(owner, 'step_reused_ip_consume', lambda *_: None)
            m.setattr(owner._spf, 'entry_admission', lambda *_: {'admitted': True, 'site': 'rtl_lint_tool'})
            m.setattr(contract, 'selected_mode', lambda *_: 'librelane')
            rc = owner.main()
        return SimpleNamespace(returncode=rc)

    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == (0 if status == 'PASS' else 1)
    summary = json.loads((tmp_path / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert summary['dispatched_verdict'] == status, summary
    assert summary['whole_flow_verdict'] == 'NOT_MEASURED'
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    terminal = json.loads((attempt / 'result.json').read_bytes())
    assert terminal['default_row_status'] == status
    assert terminal['delivery_accepted'] is False
    current = json.loads((tmp_path / 'reports/orchestrator/phase2_one_shot.json').read_bytes())
    assert current['verdict'] == status
    assert current['runner_binding']['argv'] == children[0]


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
    assert flow109._retained_native_result(tmp_path, context) is None
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


@pytest.mark.parametrize(('step', 'native_step'), [('D11', '2'), ('D13', '4'), ('D14', '5')])
@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_completed_native_owner_uses_the_single_reader(tmp_path, monkeypatch, step, native_step, status):
    import vibe_ic_one_shot_runner as runner
    context = flow109.execution_context(flow109.resolve_plan(profile()), step, step)
    path = tmp_path / 'context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    seen = []
    def read(project, current):
        assert project == tmp_path and current == context
        return {'component_status': status, 'reason': 'native report read'}
    def finish(project, result):
        seen.append(result['steps'][0])
        return {'default_row_status': status}
    monkeypatch.setattr(flow109, '_retained_native_result', read)
    monkeypatch.setattr(flow109, 'finish_native_window', finish)
    result = getattr(runner, f'_finish_{step.lower()}_selected_owner')(
        tmp_path, {}, {}, published_current=True)
    assert result['verdict'] == status
    assert seen == [{'status': status, 'extras': {
        'component_status': status, 'reason': 'native report read', 'step_id': native_step}}]
