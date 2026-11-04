"""Retained dispatch controls, plus explicit neutral native formal regressions."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _delivery_route
import flow109
from test_flow109_selection import profile


@pytest.mark.parametrize('rc,findings,expected', [
    (0, '[]', 'PASS'), (1, '[]', 'FAIL'), (17, '[]', 'FAIL'),
    (0, '[{"severity":"ERROR"}]', 'FAIL'),
    (0, '[{"severity":"ERROR","block_eligible":false}]', 'PASS'),
    (0, None, 'NOT_MEASURED'), (0, '{', 'NOT_MEASURED'),
    (0, '{}', 'NOT_MEASURED'),
])
def test_d11_public_reads_this_lint_result(tmp_path, monkeypatch, rc, findings, expected):
    """Real public/child/producer/finish path; only tool process is SOFTWARE."""
    import design_one_shot_runner as owner
    import librelane_contract as contract
    from test_flow109_selection import _public_d09_entry
    case(tmp_path, 'D11')
    (tmp_path / 'reports/phase2/lint/verilator_lint_gate.json').unlink()
    (tmp_path / 'phase2/stage2/synth/synth_inputs.json').unlink()
    put(tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'neutral'})
    lint = tmp_path / 'reports/phase2/lint/rtl_hygiene.json'
    lint.write_text('[]')  # An earlier clean result must not replace this invocation.
    runner = _public_d09_entry(tmp_path, monkeypatch)
    argv = list(sys.argv)
    for flag in ('--entry-step', '--exit-step'): argv[argv.index(flag) + 1] = 'D11'
    monkeypatch.setattr(sys, 'argv', argv)

    def native(command, **kwargs):
        assert Path(command[1]).name == 'rtl_hygiene_lint.py'
        if findings is not None: lint.write_text(findings)
        return SimpleNamespace(returncode=rc, stdout='SOFTWARE tool boundary', stderr='')

    def child(command, *, env=None, **kwargs):
        with monkeypatch.context() as m:
            for key, value in env.items(): m.setenv(key, value)
            m.setattr(sys, 'argv', command[1:])
            m.setattr(owner, '_activate_runtime_program_tree', lambda *_: None)
            m.setattr(owner, '_bootstrap_execution_policy', lambda *_, **__: None)
            m.setattr(owner, 'step_reused_ip_consume', lambda *_: None)
            m.setattr(owner._spf, 'entry_admission', lambda *_: {'admitted': True, 'site': 'rtl_lint_tool'})
            m.setattr(contract, 'selected_mode', lambda *_: 'librelane')
            m.setattr(owner._pr, 'run', native)
            code = owner.main()
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == (0 if expected == 'PASS' else 1)
    summary = json.loads((tmp_path / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert summary['dispatched_verdict'] == expected, summary
    assert summary['whole_flow_verdict'] == 'NOT_MEASURED'
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    terminal = json.loads((attempt / 'result.json').read_bytes())
    assert terminal['default_row_status'] == expected
    assert terminal['delivery_accepted'] is False
    current = json.loads((tmp_path / 'reports/orchestrator/phase2_one_shot.json').read_bytes())
    assert current['verdict'] == expected


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
        import _chip_synth_read as chip
        harness = project / 'phase2/stage1/formal/formal_neutral.sv'
        harness.parent.mkdir(parents=True)
        harness.write_text('module formal_neutral(input clk); (* anyseq *) wire d; wire q;\n'
                           'neutral dut(.d(d),.q(q)); always @(*) assert(q == d); endmodule\n')
        put(project / 'phase2/stage1/formal/results.json', {
            'chip_read':chip.current_chip_read(project,'neutral'),
            'proof_inputs':{'files':{harness.name:flow109._file_digest(harness)}},
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


@pytest.mark.parametrize('step', ['D09', 'D10'])
@pytest.mark.parametrize('downstream_status', ['PASS', 'NOT_MEASURED'])
def test_retained_frontend_report_is_used_only_by_its_own_row(tmp_path, step, downstream_status):
    args, _ = case(tmp_path, step)
    downstream = tmp_path / 'reports/flow109/default_rows/D10.json'
    prior = {'step_id': 'D10', 'component_status': downstream_status,
             'default_row_status': downstream_status}
    if downstream_status == 'PASS':
        put(tmp_path / 'reports/frontend_native.json', {'passed': True, 'tools': {
            name: {'exit_code': 0} for name in ('Yosys.JsonHeader', 'Verilator.Lint')}})
        put(tmp_path / 'reports/frontend_elaboration.json', {'modules': {'neutral': {
            'ports': {'d': {'direction': 'input', 'bits': [2]},
                      'q': {'direction': 'output', 'bits': [2]}}, 'cells': {}}}})
        prior['p0_native'] = {'producer_result': {'path': 'reports/frontend_native.json'},
            'elaboration_path': 'reports/frontend_elaboration.json', 'top': 'neutral'}
    else:
        prior['reason'] = 'D10_D09_NOT_ACCEPTED'
        (tmp_path / 'phase2/stage2/synth/synth_inputs.json').unlink()
    put(downstream, prior)
    saved = downstream.read_bytes()
    result = flow109.prepare_front_door(args, tmp_path)
    assert result is None, f'{step} must continue to its registered owner'
    assert downstream.read_bytes() == saved
    if step == 'D09':
        assert not (tmp_path / 'reports/flow109/default_rows/D09.json').exists()
    context = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
    assert context['resolved_row']['id'] == step


@pytest.mark.parametrize('step,report', [
    ('D10', 'reports/flow109/default_rows/D10.json'),
    ('D11', 'reports/phase2/lint/verilator_lint_gate.json'),
    ('D19', 'phase2/stage2/constraints/asic_sdc.json'),
    ('D20', 'reports/sdc_validator.json'),
])
@pytest.mark.parametrize('later_synthesis', [False, True])
def test_early_report_cannot_replace_current_registered_owner(
        tmp_path, monkeypatch, step, report, later_synthesis):
    args, _ = case(tmp_path, step)
    put(tmp_path / report, {'verdict': 'PASS', 'default_row_status': 'PASS'})
    saved = (tmp_path / report).read_bytes()
    if not later_synthesis:
        for path in (tmp_path / 'phase2/stage2/synth').iterdir(): path.unlink()
    reads = []
    original = Path.read_text
    def read(path, *a, **kw):
        if path.is_relative_to(tmp_path / 'phase2/stage2/synth'):
            reads.append(str(path))
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'read_text', read)
    result = flow109.prepare_front_door(args, tmp_path)
    assert reads == [], 'early owner dispatch must not read later synthesis'
    assert result is None
    context = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
    dispatch = context['resolved_row']['profile']['dispatch']
    route = json.loads((tmp_path / 'reports/flow109/owner_route.json').read_text())
    assert route['owner_runner'] == dispatch['owner_runner'] == 'design_one_shot_runner'
    assert (args.entry_step, args.exit_step) == (
        dispatch['owner_entry_step'], dispatch['owner_exit_step'])
    assert route['component_status'] == route['flow109_acceptance'] == 'NOT_MEASURED'
    assert route['native_started'] is False
    assert (tmp_path / report).read_bytes() == saved
    if step != 'D10':
        assert not (tmp_path / f'reports/flow109/default_rows/{step}.json').exists()


@pytest.mark.parametrize('step', ['D13', 'D14', 'D22', 'D25', 'D26', 'D30'])
def test_public_frontend_reads_native_reports_without_a_producer_rerun(tmp_path, monkeypatch, step):
    args, _ = case(tmp_path, step)
    monkeypatch.setattr(flow109, 'dft_source_intent', lambda *a: pytest.fail(
        'completed native work must not enter the old DFT receipt wrapper'))
    context=flow109.execution_context(flow109.resolve_plan(profile()),step,step)
    assert flow109._retained_native_result(tmp_path,context)['component_status']=='PASS'
    expected='NOT_MEASURED' if step=='D14' else 'PASS'
    assert flow109.prepare_front_door(args, tmp_path) == (2 if step=='D14' else 0)
    row = json.loads((tmp_path / f'reports/flow109/default_rows/{step}.json').read_text())
    assert row['default_row_status'] == expected
    assert row['native_started'] is False
    assert row['native_measurements']


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_explicit_current_row_rerun_reaches_owner(tmp_path, status):
    args, _ = case(tmp_path, 'D13')
    put(tmp_path / 'reports/phase2/sim/l10_execution.json', {
        'cases': [{'id': 'neutral_case', 'verdict': status, 'sim_executed': True}]})
    args._flow109_resume_plan = {'status': 'READY', 'execution_steps': ['D13']}
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert not (tmp_path / 'reports/flow109/default_rows/D13.json').exists()


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_other_row_rerun_preserves_retained_native_verdict(tmp_path, status):
    args, _ = case(tmp_path, 'D13')
    put(tmp_path / 'reports/phase2/sim/l10_execution.json', {
        'cases': [{'id': 'neutral_case', 'verdict': status, 'sim_executed': True}]})
    args._flow109_resume_plan = {'status': 'READY', 'execution_steps': ['D14']}
    assert flow109.prepare_front_door(args, tmp_path) == (0 if status == 'PASS' else 1)
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D13.json').read_text())
    assert row['default_row_status'] == status


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


@pytest.mark.parametrize('step', ['D13', 'D14', 'D22', 'D25', 'D26', 'D30'])
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
        path=tmp_path / 'phase2/stage1/formal/results.json'
        native=json.loads(path.read_text());native['properties']=[{'task':'safety','status':'FAIL'}]
        put(path,native)
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


def _native_census_case(project, combinational):
    import shutil
    import subprocess
    import _cdc_netlist as native
    source = project / 'phase2/stage1/rtl/unit.v'
    source.parent.mkdir(parents=True)
    header = 'module unit(input clk,rst,d,output reg q,raw'
    body = ('always @(posedge clk) if(rst) begin q<=0;raw<=0;end '
            'else begin q<=d;raw<=q;end assign z=q^raw;' if combinational else
            'always @(posedge clk) begin if(rst) q<=0;else q<=d;raw<=d;end')
    source.write_text(header + (',output z);' if combinational else ');') + body + ' endmodule\n')
    graph = project / native.NETLIST_REL
    graph.parent.mkdir(parents=True)
    run = subprocess.run([shutil.which('yosys'), '-Q', '-T', '-p',
        f'read_verilog {source}; hierarchy -top unit; proc; flatten; write_json {graph}'],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    nl = native.load(graph)
    roles = {row['state']: 'synchronous_reset' for row in native.reset_role_candidates(nl)}
    reset = {}
    assert native.judge(nl, 'reset_dependency', metadata=reset, reset_roles=roles) == []
    domains = {n: {'role': r, 'clock': 'clk'} for n,r in
               [('clk','clock'),('rst','synchronous_reset'),('d','synchronous_data')]}
    items = [{'kind':'state','name':n,'clock':'clk','detail':'1'} for n in ['q','raw']]
    items += [{'kind':'clock','name':'clk','clock':'clk','detail':'rising'},
              {'kind':'reset','name':'rst','clock':'clk','detail':'synchronous_active_high'},
              {'kind':'input','name':'d','clock':'clk','detail':'synchronous_data'}]
    items += [{'kind':'output','name':n,'clock':'clk','detail':'registered'} for n in ['q','raw']]
    if combinational: items.append({'kind':'output','name':'z','clock':'clk','detail':'combinational'})
    expected = {'clock_reset_crossing_census': {'required_items': items}}
    observed = {'subject': {'input': {'rtl_files': [source.relative_to(project).as_posix()]}},
                'reset_analysis': reset, 'roles': roles, 'input_domains': domains}
    return expected, observed


@pytest.mark.parametrize('combinational', [False, True], ids=['partial_reset','combinational_output'])
def test_native_census_accepts_declared_partial_reset_and_combinational_output(tmp_path, combinational):
    import flow109_metric_acceptance as metrics
    source, observed = _native_census_case(tmp_path, combinational)
    assert metrics._d12_census(tmp_path, source, observed) == source['clock_reset_crossing_census']['required_items']


@pytest.mark.parametrize('damage', ['polarity','registered_claim'])
def test_native_census_preserves_reset_polarity_and_registered_output_refusals(tmp_path, damage):
    import flow109_metric_acceptance as metrics
    source, observed = _native_census_case(tmp_path, True)
    items = source['clock_reset_crossing_census']['required_items']
    next(x for x in items if x['kind'] == ('reset' if damage == 'polarity' else 'output')
         and x['name'] == ('rst' if damage == 'polarity' else 'z'))['detail'] = (
             'synchronous_active_low' if damage == 'polarity' else 'registered')
    with pytest.raises(metrics.MetricRefusal, match='D12_CENSUS_MAPPING_UNPROVEN'):
        metrics._d12_census(tmp_path, source, observed)


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


@pytest.mark.parametrize(('step', 'native_step'), [('D13', '4'), ('D14', '5')])
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


def native_formal_case(project, *, status='PASS', later_synthesis=False):
    import formal_property_run as producer
    import _chip_synth_read as chip
    args,rtl=case(project,'D14')
    for path in (project/'phase2/stage2/synth').iterdir(): path.unlink()
    formal=project/'phase2/stage1/formal'
    harness=formal/'formal_neutral.sv'
    if status=='PARTIAL':
        native=json.loads((formal/'results.json').read_text())
        native['properties'][0]['status']='PARTIAL'  # SOFTWARE verdict-selection control only.
        put(formal/'results.json',native)
    else:
        rtl.write_text('module neutral(input clk,input d,output reg q); always @(posedge clk) q <= d; endmodule\n')
        harness.write_text('module formal_neutral(input clk); (* anyseq *) wire d; wire q; reg past_valid=0;\n'
            'neutral dut(.clk(clk),.d(d),.q(q)); always @(posedge clk) begin past_valid<=1;\n'
            'if(past_valid) assert(q == $past(d)); end endmodule\n')
        put(formal/'property_contract.json',{'chip_read_top':'neutral','property_denominator':1,
            'covered_obligations':[{'id':'fixture.capture','property':'capture'}],'unresolved_obligations':[]})
        if status=='FAIL': rtl.write_text(rtl.read_text().replace('q <= d','q <= ~d'))
        native=producer.run(project,harness=harness,rtl=[rtl],top='formal_neutral',
            container=None,timeout=30,mem_limit_kb=4*1024*1024,prove_engines='direct')
        assert native['verdict']==status and native['properties'] and {p['status'] for p in native['properties']}=={status},native
    if later_synthesis:
        put(project/'phase2/stage2/synth/synth_inputs.json',{'rtl_sha256':{rtl.name:flow109._file_digest(rtl)}})
        put(chip.built_record_path(project),chip.current_chip_read(project,'neutral'))
    return args,rtl,formal,native


@pytest.mark.parametrize('caller',['entry','finish'])
@pytest.mark.parametrize('later_synthesis',[False,True])
@pytest.mark.parametrize('status',['PASS','FAIL','PARTIAL'])
def test_current_formal_source_owns_early_proof_without_later_synthesis(tmp_path,monkeypatch,caller,later_synthesis,status):
    import formal_proof_evidence_check as checker
    args,_,formal,native=native_formal_case(tmp_path,status=status,later_synthesis=later_synthesis)
    assert checker.proof_source_staleness(tmp_path,formal,native)==[]
    component='NOT_MEASURED' if status=='PARTIAL' else status
    expected='FAIL' if status=='FAIL' else 'NOT_MEASURED'
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D14','D14')
    retained=flow109._retained_native_result(tmp_path,context)
    assert retained['component_status']==component and retained['reason']=='D14_RETAINED_NATIVE_REPORT',retained
    if caller=='entry':
        assert flow109.prepare_front_door(args,tmp_path)=={'PASS':0,'FAIL':1,'NOT_MEASURED':2}[expected]
    else:
        import vibe_ic_one_shot_runner as runner
        context_path=tmp_path/'context.json';put(context_path,context)
        monkeypatch.setenv(flow109.CONTEXT_ENV,str(context_path))
        monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
        answer=runner._finish_d14_selected_owner(tmp_path,{}, {},published_current=True)
        assert answer['verdict']==expected,answer
    row=json.loads((tmp_path/'reports/flow109/default_rows/D14.json').read_text())
    assert row['default_row_status']==expected and row['reason']=='D14_RETAINED_NATIVE_REPORT',row
    assert row['native_measurements']['tasks'] and row['native_started'] is False
    assert row['completed'] is (expected=='PASS')


@pytest.mark.parametrize('damage',['rtl','harness','missing_chip_read','missing_proof_inputs','define','built_read','synth_inputs'])
def test_retained_formal_rejects_proof_source_or_present_synthesis_drift(tmp_path,damage):
    import _chip_synth_read as chip
    args,rtl,formal,native=native_formal_case(tmp_path,later_synthesis=True)
    if damage in ('rtl','harness'):
        path=rtl if damage=='rtl' else formal/'formal_neutral.sv'
        path.write_text(path.read_text()+'\n// source changed after the native proof\n')
    elif damage=='built_read':
        built=chip.current_chip_read(tmp_path,'neutral');built['top']='other_top'
        put(chip.built_record_path(tmp_path),built)
    elif damage=='synth_inputs':
        put(tmp_path/'phase2/stage2/synth/synth_inputs.json',{'rtl_sha256':{rtl.name:'0'*64}})
    else:
        if damage=='missing_chip_read': native.pop('chip_read')
        elif damage=='missing_proof_inputs': native.pop('proof_inputs')
        else: native['chip_read']['define']['simulation']=not native['chip_read']['define']['simulation']
        put(formal/'results.json',native)
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D14','D14')
    assert flow109._retained_native_result(tmp_path,context) is None, 'stale proof must return to its native producer'
    assert not (tmp_path/'reports/flow109/default_rows/D14.json').exists()


@pytest.mark.parametrize('wrong_dut,publication,expected',[
    (False,'current','PASS'),(True,'current','FAIL'),
    (False,'missing','NOT_MEASURED'),(False,'NOT_MEASURED','NOT_MEASURED'),
    (False,'INCOMPLETE','NOT_MEASURED'),(False,'PARTIAL','NOT_MEASURED'),
    (False,'pending_ai','NOT_MEASURED'),(False,'consumer_block','NOT_MEASURED'),
    (False,'missing_verdict','NOT_MEASURED'),(False,'empty_report','NOT_MEASURED'),
    (False,'UNSUPPORTED_RESULT','NOT_MEASURED')])
def test_d13_without_synthesis_runs_native_functional_owner_and_counts_current_result(tmp_path,monkeypatch,wrong_dut,publication,expected):
    """Actual public transport/native functional step; bootstrap preconditions SOFTWARE.

    The child-process adapter calls the shipped functional producer and normal
    report writer. It does not claim full pipeline or platform qualification.
    """
    import subprocess
    import time
    import ai_signed_judgement as judgement
    import design_one_shot_runner as owner
    from dataclasses import asdict
    from types import SimpleNamespace
    from test_flow109_selection import _public_d09_entry
    case(tmp_path,'D13')
    (tmp_path/'phase2/stage2/synth/synth_inputs.json').unlink()
    rtl=tmp_path/'phase2/stage1/rtl/neutral.v'
    if wrong_dut: rtl.write_text(rtl.read_text().replace('q=d','q=~d'))
    put(tmp_path/'phase1/generated_docs/L10_TEST_CASES.json',{'test_cases':[{'name':'probe','kind':'functional_vector'}]})
    tb=tmp_path/'phase2/stage1/sim/tb/probe.v';tb.parent.mkdir(parents=True)
    tb.write_text('module probe; reg d; wire q; neutral dut(.d(d),.q(q));\n'
        'initial begin d=0; #1; if(q!==d) $fatal(1,"wrong capture");\n'
        'd=1; #1; if(q!==d) $fatal(1,"wrong capture"); $finish; end endmodule\n')
    public=_public_d09_entry(tmp_path,monkeypatch)
    monkeypatch.setattr(public,'_standalone_rtl_provenance',lambda *_:{'ran':True})
    if publication=='consumer_block':
        monkeypatch.setattr(public,'_current_default_acceptance',lambda *_:[{'id':'4','status':'NOT_MEASURED'}])
    argv=[arg for arg in sys.argv if arg not in ('--skip-phase1','--skip-phase3','--skip-analog')]
    for flag in ('--entry-step','--exit-step'): argv[argv.index(flag)+1]='D13'
    monkeypatch.setattr(sys,'argv',argv)
    actual_run=subprocess.run;calls=[]
    def child(command,*,env=None,**kwargs):
        if len(command)<2 or Path(command[1]).name!='phase2_one_shot_runner.py':
            return actual_run(command,env=env,**kwargs)
        assert command[command.index('--entry-step')+1]==command[command.index('--exit-step')+1]=='4'
        with monkeypatch.context() as m:
            for key,value in env.items():m.setenv(key,value)
            m.setattr(sys,'argv',command[1:])
            started=time.time();native=owner.step_l10_unit_tb_run(tmp_path,None)
            assert native.status==('FAIL' if wrong_dut else 'PASS'),native
            assert native.extras['executed']==1 and native.extras['sim_executed']
            calls.append(asdict(native))
            summary={'project':str(tmp_path),'steps':[asdict(native)],
                'verdict':owner._aggregate_verdict([native],project=tmp_path,started_at=started),
                'declared_window':{'entry_step':'4','exit_step':'4','dispatched_step_ids':['4']}}
            if publication=='pending_ai':
                put(tmp_path/'reports/phase2/gates/professional_tb.json',{'dut_kind':'expert_reference'})
                summary['ai_judgements']=judgement.pending(tmp_path,('4',))
                assert summary['ai_judgements']
                judgement.demote_runner_rows(summary['steps'],summary['ai_judgements'])
                summary['verdict']='NOT_MEASURED'
            elif publication in ('NOT_MEASURED','INCOMPLETE','PARTIAL','UNSUPPORTED_RESULT'): summary['verdict']=publication
            elif publication in ('missing_verdict','empty_report'):
                summary.pop('verdict')
                if publication=='empty_report': summary.pop('steps')
            if publication!='missing':
                owner._write_phase2_report(owner._pl.report_path(tmp_path,'phase2_one_shot.json'),summary,tmp_path,
                    invocation_context=owner._runner_invocation_context())
        exit_status=native.status if publication in ('missing_verdict','empty_report','UNSUPPORTED_RESULT') else summary['verdict']
        return SimpleNamespace(returncode=0 if exit_status=='PASS' else 1)
    monkeypatch.setattr(public.subprocess,'run',child)
    rc=public._main()
    assert rc==(0 if expected=='PASS' else 1)
    assert len(calls)==1, 'D13 must reach its current functional producer before synthesis'
    row=json.loads((tmp_path/'reports/flow109/default_rows/D13.json').read_text())
    assert row['default_row_status']==expected and row['completed'] is (expected=='PASS'),row
    assert row['delivery_accepted'] is False and row['whole_flow_acceptance']=='NOT_MEASURED'


@pytest.mark.parametrize('state,expected',[('absent',None),('matching','PASS'),('rtl_drift',None),('digest_drift',None),('malformed','NOT_MEASURED')])
def test_d13_retained_reuse_preserves_present_synthesis_freshness(tmp_path,state,expected):
    _,rtl=case(tmp_path,'D13')
    synth=tmp_path/'phase2/stage2/synth/synth_inputs.json'
    if state=='absent':synth.unlink()
    elif state=='rtl_drift':rtl.write_text(rtl.read_text()+'// source changed\n')
    elif state=='digest_drift':put(synth,{'rtl_sha256':{'neutral.v':'0'*64}})
    elif state=='malformed':synth.write_text('{')
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D13','D13')
    result=flow109._retained_native_result(tmp_path,context)
    assert result is None if expected is None else result['component_status']==expected
