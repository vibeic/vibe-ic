"""Step 8 waits for its tool producer, then consumes current evidence directly."""
import ast
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
import design_one_shot_runner as D
import execution_policy as E
import librelane_contract as LC
import librelane_prelayout as LP
import phase3_one_shot_runner as P
import vibe_ic_one_shot_runner as V


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def _prelayout_request_project(root, switch):
    put(root / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {
        'clock_domains': [{'role': 'primary', 'source_pin': 'neutral_clk', 'period_ns': 20}]})
    put(root / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'neutral_core'})
    put(root / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {})
    put(root / 'input/submission_template/tapeout_declaration.json', {})
    (root / 'phase3').mkdir(exist_ok=True)
    if switch is not None:
        put(root / 'phase3/librelane_switch.json', switch)
    return root / 'phase3/prelayout.json'


@pytest.mark.parametrize('switch', [None, {}, {'steps': {'8': 'librelane'}}],
                         ids=['no_switch', 'empty_switch', 'other_switch'])
def test_prelayout_io_absence_preserves_core_config(tmp_path, switch):
    output = _prelayout_request_project(tmp_path, switch)
    config = LP.emit_prelayout_config(tmp_path, 'neutral_pdk', 'neutral_core', None, [], output)
    assert config == {'CLOCK_PERIOD': 20, 'CLOCK_PORT': 'neutral_clk',
                      'DESIGN_NAME': 'neutral_core', 'PDK': 'neutral_pdk', 'VERILOG_FILES': []}
    assert json.loads(output.read_text()) == config
    assert not any(name.startswith('PAD_') for name in config)


@pytest.mark.parametrize('section', [
    {'PAD_LIBS': {'*_tt_025C_1v80': ['/pdk/neutral/io_tt.lib']}},
    {'PAD_LIBS': 123}, {'UNSUPPORTED': True}, {}, None, [], False, 0, '',
], ids=['typed_request', 'invalid_pad_type', 'unknown_key', 'empty_object',
        'null', 'list', 'boolean', 'number', 'empty_string'])
def test_prelayout_io_present_request_has_named_refusal(tmp_path, section):
    output = _prelayout_request_project(tmp_path, {'prelayout_io': section})
    try:
        LP.emit_prelayout_config(tmp_path, 'neutral_pdk', 'neutral_core', None, [], output)
    except LC.Refusal as exc:
        observed = exc.code
        assert 'prelayout_io' in str(exc) and 'core' in str(exc)
    else:
        observed = 'CONFIG_EMITTED_WITHOUT_REQUEST_DIAGNOSTIC'
    assert observed == 'LL_PRELAYOUT_IO_UNSUPPORTED'
    assert not output.exists()
    assert not output.with_suffix('.provenance.json').exists()


@pytest.mark.parametrize('mode', ['dual', 'librelane'])
def test_tool_step8_defers_before_synth_without_frontend_dispatch(tmp_path, monkeypatch, mode):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': mode}})
    put(tmp_path / 'phase2/stage2/constraints/neutral.asic.sdc',
        'create_clock -name clk -period 10 [get_ports clk]\n'
        'set_input_delay 1 -clock clk [get_ports d]\n'
        'set_output_delay 1 -clock clk [get_ports q]\n')
    put(tmp_path / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clock_domains': [{'name': 'clk', 'source_pin': 'clk', 'period_ns': 10}]})
    calls = []
    monkeypatch.setattr(E, '_ordinary_runtime', {
        'project': tmp_path.resolve(), 'policy': {'mode': 'default'}, 'parameters': {}})
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *a, **k:
                        calls.append(a) or {'status': 'ADOPTED'})
    row = D.step_sdc_validation(tmp_path)
    assert row.status == 'PASS', row.detail
    assert 'no mapped-path claim' in row.detail
    assert row.extras['early_preflight'] is True
    assert row.extras['deferred_until'] == 'post_prelayout'
    assert not (tmp_path / 'phase2/stage2/synth').exists()
    assert not (tmp_path / 'phase3/librelane/prelayout').exists()
    assert not calls


@pytest.mark.parametrize('mutation', ['missing_sdc', 'unjustified_exception'])
def test_tool_step8_early_preflight_refuses_missing_or_unjustified_constraints(
        tmp_path, monkeypatch, mutation):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'dual'}})
    put(tmp_path / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clock_domains': [{'name': 'clk', 'source_pin': 'clk', 'period_ns': 10}]})
    if mutation == 'unjustified_exception':
        put(tmp_path / 'phase2/stage2/constraints/neutral.asic.sdc',
            'create_clock -name clk -period 10 [get_ports clk]\n'
            'set_input_delay 1 -clock clk [get_ports d]\n'
            'set_output_delay 1 -clock clk [get_ports q]\n'
            'set_false_path -from [get_clocks clk] -to [get_clocks foreign]\n')
    monkeypatch.setattr(E, '_ordinary_runtime', {
        'project': tmp_path.resolve(), 'policy': {'mode': 'default'}, 'parameters': {}})
    row = D.step_sdc_validation(tmp_path)
    assert row.status == 'FAIL'
    assert row.extras['early_preflight'] is True


@pytest.mark.parametrize('case', ['valid', 'missing_sdc', 'unjustified_exception'])
def test_public_d20_owner_entry_runs_only_early_preflight(
        tmp_path, monkeypatch, case):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'dual'}})
    put(tmp_path / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {
        'clock_domains': [{'name': 'clk', 'source_pin': 'clk', 'period_ns': 10}]})
    if case != 'missing_sdc':
        text = ('create_clock -name clk -period 10 [get_ports clk]\n'
                'set_input_delay 1 -clock clk [get_ports d]\n'
                'set_output_delay 1 -clock clk [get_ports q]\n')
        if case == 'unjustified_exception':
            text += 'set_false_path -from [get_clocks clk] -to [get_clocks foreign]\n'
        put(tmp_path / 'phase2/stage2/constraints/neutral.asic.sdc', text)
    put(tmp_path / 'phase2/stage1/rtl/neutral.v',
        'module neutral(input clk, d, output q); assign q=d; endmodule\n')
    monkeypatch.setattr(E, '_ordinary_runtime', {
        'project': tmp_path.resolve(), 'policy': {'mode': 'default'}, 'parameters': {}})
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *_a, **_k:
                        pytest.fail('D20 early entry dispatched a frontend worker'))
    finished = []
    import flow109
    monkeypatch.setattr(flow109, 'finish_native_window', lambda project, report:
                        finished.append((project, report)) or None)
    result = V._complete_step8_early_preflight(tmp_path)
    expected = 'PASS' if case == 'valid' else 'FAIL'
    assert result['verdict'] == expected, result
    assert result['early_preflight'] is True
    assert result['mapped_path_claimed'] is False
    assert result['frontend_dispatched'] is False
    assert ('no mapped-path claim' in result['detail']) == (case == 'valid')
    assert finished[0][1]['steps'][0]['extras']['step_id'] == '8'
    assert finished[0][1]['steps'][0]['extras']['completed'] is (case == 'valid')


def test_public_step8_branch_selects_early_not_postprelayout_consumer():
    tree = ast.parse(Path(V.__file__).read_text())
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == '_main')
    branch = next(node for node in ast.walk(main) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Name)
                  and node.test.id == '_sdc_early_entry')
    calls = {node.func.id for node in ast.walk(branch)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert '_complete_step8_early_preflight' in calls
    assert '_complete_step8_postcheck' not in calls
    source = ast.unparse(main)
    assert "VIBEIC_FLOW109_CONTEXT" in source
    assert '_sdc_early_entry = ' in source and 'and _flow109_owner_entry' in source
    assert '_sdc_postcheck_entry = ' in source and 'not _flow109_owner_entry' in source


def test_flow109_d20_d26_split_keeps_stable_obligations():
    rows = {row['id']: row for row in json.loads(
        (Path(D.__file__).parents[1] / 'flow/flow109.json').read_text())['rows']}
    d20, d26 = rows['D20'], rows['D26']
    assert d20['profiles'][0]['native_steps'] == []
    assert 'early preflight' in d20['profiles'][0]['dispatch']['consumer']
    assert d26['profiles'][0]['native_steps'] == [
        'OpenROAD.CheckSDCFiles', 'OpenROAD.STAPrePNR']
    assert 'step_sdc_validation_post_prelayout' in d26['profiles'][0]['dispatch']['consumer']
    assert [item['id'] for item in d20['obligations']] == [
        'base_11.invalid_timing_exceptions', 'base_11.cdc_exception_reconciliation']
    assert 'base_11.unconstrained_required_paths' in {
        item['id'] for item in d26['obligations']}


def test_direct_step8_keeps_existing_worker(tmp_path, monkeypatch):
    # This is the standalone legacy worker case. Default's runtime-bound
    # direct consumer has separate assertions below.
    monkeypatch.setattr(E, '_ordinary_runtime', None)
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'direct'}})
    calls = []
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *a, **k:
                        calls.append(a) or {'status': 'ADOPTED'})
    assert D.step_sdc_validation(tmp_path).status == 'PASS'
    assert calls == [(tmp_path, '8')]


@pytest.mark.parametrize('present', [True, False])
def test_default_direct_step8_runs_canonical_checks_without_controller(tmp_path, monkeypatch, present):
    if present:
        project(tmp_path)
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'direct'}})
    # Use the ordinary constructor: retained acceptance also binds this
    # runtime to its project and reads its declared parameters.
    monkeypatch.setattr(E, '_ordinary_runtime', None)
    runtime = E.bootstrap(tmp_path)
    assert runtime['project'] == tmp_path.resolve()
    assert runtime['policy']['mode'] == 'default'
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *_a, **_k:
                        pytest.fail('Default direct Step 8 dispatched a Controller'))
    row = D.step_sdc_validation(tmp_path)
    assert row.status == ('PASS' if present else 'FAIL'), row.detail
    report = tmp_path / 'reports/phase2/sdc_check.json'
    assert report.is_file()
    assert str(report) in row.output_files
    assert 'deferred_until' not in row.extras


def test_default_direct_step8_replaces_stale_output_with_current_observation(tmp_path, monkeypatch):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'direct'}})
    put(tmp_path / 'reports/phase2/sdc_check.json', {'stale': 'PASS'})
    monkeypatch.setattr(E, '_ordinary_runtime', {'policy': {'mode': 'default'}})
    row = D.step_sdc_validation(tmp_path)
    assert row.status == 'FAIL'
    report = tmp_path / 'reports/phase2/sdc_check.json'
    assert json.loads(report.read_text()).get('stale') is None
    assert str(report) in row.output_files


def project(tmp_path):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'dual'}})
    deck = put(tmp_path / 'phase3/stage3/pnr/constraint.sdc',
               'create_clock -name clk -period 10 [get_ports clk]\n'
               'set_input_delay 1 -clock clk [get_ports d]\n'
               'set_output_delay 1 -clock clk [get_ports q]\n')
    put(tmp_path / 'phase2/stage2/constraints/top.asic.sdc', deck.read_text())
    put(tmp_path / 'phase2/stage2/constraints/pvt_matrix.json', {
        'corners': [
            {'name': 'ss', 'label': 'SS'},
            {'name': 'tt', 'label': 'TT'},
        ],
        'primary_corner': 'TT',
        'multi_corner': True,
    })
    nl = put(tmp_path / 'phase2/stage2/synth/top_synth.v',
             'module top(input clk, d, output q); assign q=d; endmodule\n')
    put(tmp_path / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clocks': {'clk': {'period_ns': 10}}})
    put(tmp_path / 'phase2/stage1/rtl/top.v', nl.read_text())
    folder = tmp_path / 'phase3/librelane/prelayout/design_sdc'
    corner = folder / 'tt'
    corner.mkdir(parents=True)
    # The existing calibration corpus backs the actual OpenSTA grammar.
    cal = Path(LP.__file__).parent / 'calibration'
    shutil.copyfile(cal / 'sta_prepnr_linked_clean_negative.log', corner / 'sta.log')
    shutil.copyfile(cal / 'sta_prepnr_check_setup_clean_negative.rpt', corner / 'checks.rpt')
    put(folder / 'state_out.json', {'nl': str(nl)})
    gate = tmp_path / 'phase3/librelane/prelayout/gates/step8_sdc_opensta.json'
    result = LP.judge_sdc(folder, {'PNR_SDC_FILE': str(deck)}, deck, gate)
    assert result['verdict'] == 'PASS'
    return gate, deck, nl


def test_postcheck_pass_preserves_deferred_history_and_binds_current_inputs(tmp_path, monkeypatch):
    gate, deck, nl = project(tmp_path)
    early = D.step_sdc_validation(tmp_path)
    report = put(tmp_path / 'reports/orchestrator/phase2_one_shot.json',
                 {'project': str(tmp_path), 'steps': [asdict(early)], 'verdict': 'NOT_MEASURED'})
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *a, **k:
                        pytest.fail('postcheck must not redispatch frontend Step 8'))
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'PASS', row.detail
    doc = json.loads(Path(row.output_files[0]).read_text())
    assert len(doc['invocation_id']) == 32
    assert [x['rc'] for x in doc['records']] == [0, 0]
    pvt = tmp_path / 'phase2/stage2/constraints/pvt_matrix.json'
    assert doc['schema'] == 'sdc-post-prelayout/2'
    for name, path in [('opensta_gate', gate), ('pnr_sdc', deck),
                       ('mapped_netlist', nl), ('pvt_matrix', pvt)]:
        assert doc['binding']['inputs'][name]['sha256'] == LC.digest(path)
    history = json.loads(report.read_text())
    assert [x['status'] for x in history['steps']] == ['NOT_MEASURED', 'PASS']
    assert history['verdict'] == 'PASS'
    assert early.status == 'NOT_MEASURED'
    assert D._aggregate_verdict([early, row]) == 'PASS'
    gate.write_text(gate.read_text() + '\n')
    assert D._aggregate_verdict([early, row]) == 'NOT_MEASURED'


@pytest.mark.parametrize('changed', ['gate', 'deck', 'netlist', 'pvt'])
def test_mutation_during_consumers_refuses_current_postcheck(tmp_path, monkeypatch, changed):
    gate, deck, netlist = project(tmp_path)
    paths = {'gate': gate, 'deck': deck, 'netlist': netlist,
             'pvt': tmp_path / 'phase2/stage2/constraints/pvt_matrix.json'}
    original = D.subprocess.run
    calls = []

    def mutate(argv, **kwargs):
        result = original(argv, **kwargs)
        calls.append(argv)
        paths[changed].write_text(paths[changed].read_text() + '\n')
        return result

    monkeypatch.setattr(D.subprocess, 'run', mutate)
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'NOT_MEASURED'
    assert 'CHANGED' in row.detail or 'STALE' in row.detail
    assert len(calls) == 1
    assert not (tmp_path / 'reports/phase2/sdc_check.json').exists()


def test_pvt_mutation_after_receipt_demotes_current_verdict(tmp_path):
    """A changed Step-7 PVT census cannot leave Step 8 current/PASS."""
    project(tmp_path)
    early = D.step_sdc_validation(tmp_path)
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'PASS', row.detail
    pvt = tmp_path / 'phase2/stage2/constraints/pvt_matrix.json'
    pvt.write_text('{"corners":[{"name":"ff","label":"FF"}],\n'
                   '"primary_corner":"FF"}\n')
    assert D._aggregate_verdict([early, row]) == 'NOT_MEASURED'


def test_legacy_step8_receipt_schema_is_not_current(tmp_path):
    """An old /1 receipt cannot be replayed as a current PASS."""
    project(tmp_path)
    early = D.step_sdc_validation(tmp_path)
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'PASS', row.detail
    receipt = Path(row.output_files[0])
    doc = json.loads(receipt.read_text())
    doc['schema'] = 'sdc-post-prelayout/1'
    receipt.write_text(json.dumps(doc) + '\n')
    row.extras['receipt_sha256'] = LC.digest(receipt)
    assert D._aggregate_verdict([early, row]) == 'NOT_MEASURED'


def test_malformed_step8_receipt_binding_is_not_current(tmp_path):
    """A truthy non-object binding is refused instead of crashing roll-up."""
    project(tmp_path)
    early = D.step_sdc_validation(tmp_path)
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'PASS', row.detail
    receipt = Path(row.output_files[0])
    doc = json.loads(receipt.read_text())
    doc['binding'] = 'malformed'
    receipt.write_text(json.dumps(doc) + '\n')
    row.extras['receipt_sha256'] = LC.digest(receipt)
    assert D._aggregate_verdict([early, row]) == 'NOT_MEASURED'


def test_stale_netlist_bound_gate_is_not_reused(tmp_path):
    gate, deck, nl = project(tmp_path)
    nl.write_text(nl.read_text() + '// later netlist\n')
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'NOT_MEASURED'
    assert 'GATE_STALE' in row.detail
    assert json.loads(Path(row.output_files[0]).read_text())['records'] == []


@pytest.mark.parametrize('late_state', [
    'missing_netlist', 'missing_sta_gate', 'unmeasured_sta', 'unconstrained_endpoint'])
def test_postcheck_refuses_incomplete_or_red_mapped_evidence(tmp_path, late_state):
    gate, _deck, netlist = project(tmp_path)
    if late_state == 'missing_netlist':
        netlist.unlink()
    elif late_state == 'missing_sta_gate':
        gate.unlink()
    else:
        doc = json.loads(gate.read_text())
        doc['verdict'] = ('NOT_MEASURED' if late_state == 'unmeasured_sta' else 'FAIL')
        doc['findings'] = (["LL_STA_NO_CORNER: STAPrePNR wrote no corner directory"]
                           if late_state == 'unmeasured_sta' else
                           ["tt: check_setup {'unconstrained_endpoints': 1}"])
        gate.write_text(json.dumps(doc))
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status != 'PASS'
    assert row.status == ('NOT_MEASURED' if late_state in (
        'missing_netlist', 'missing_sta_gate') else 'FAIL')


@pytest.mark.parametrize('late_status', [
    None, 'NOT_MEASURED', 'PASS_WITH_WAIVERS', 'early_only'])
def test_d30_refuses_absent_deferred_advisory_or_early_only_d26(
        tmp_path, monkeypatch, late_status):
    plan = [D.StepResult('yosys_synth', 'PASS', 0, 'mapped')]
    if late_status is not None:
        plan.append(D.StepResult(
            'sdc_validation', 'PASS' if late_status == 'early_only' else late_status,
            0, 'bounded late state', extras={
                'early_preflight': late_status == 'early_only',
                'deferred_until': 'post_prelayout'},
            reason_class=('upstream_refused' if late_status == 'NOT_MEASURED' else '')))
    monkeypatch.setattr(D, '_current_phase2_consumer', lambda *_: pytest.fail(
        'D30 must refuse before consulting retained consumers'))
    row = D.step_synthesis_handoff(tmp_path, plan=plan)
    assert row.status == 'NOT_MEASURED'
    assert 'D26 mapped SDC acceptance' in row.detail


@pytest.mark.parametrize('missing_sid', ['8', '10'])
def test_d30_requires_current_d26_sdc_and_sta_consumers(tmp_path, monkeypatch, missing_sid):
    late = D.StepResult('sdc_validation', 'PASS', 0, 'mapped closure',
                        extras={'post_prelayout': True})
    calls = []

    def current(_project, sid, _started):
        calls.append(sid)
        return None if sid == missing_sid else {'status': 'PASS'}

    monkeypatch.setattr(D, '_current_phase2_consumer', current)
    row = D.step_synthesis_handoff(tmp_path, plan=[late])
    assert row.status == 'NOT_MEASURED'
    assert f'Step{missing_sid} acceptance' in row.detail
    assert calls[-1] == missing_sid


def test_postcheck_is_wired_only_after_passing_prelayout(tmp_path, monkeypatch):
    tree = ast.parse(Path(P.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    # Execute the contiguous real main call sites. The current guard also
    # requires canonical acceptance; matching a literal one-clause If would
    # reject that stricter behavior without checking the ordering invariant.
    body = next(n.body for n in ast.walk(main) if isinstance(n, ast.If) and any(
        isinstance(s, ast.Assign) and isinstance(s.value, ast.Call) and
        isinstance(s.value.func, ast.Name) and s.value.func.id == 'step_prelayout_signoff'
        for s in n.body))
    start = next(i for i, s in enumerate(body) if isinstance(s, ast.Assign) and
                 any(isinstance(t, ast.Name) and t.id == '_prelayout_started' for t in s.targets))
    end = next(i for i, s in enumerate(body) if isinstance(s, ast.If) and any(
        isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and
        c.func.id == 'step_sdc_validation_post_prelayout' for c in ast.walk(s)))
    code = compile(ast.Module(body=body[start:end + 1], type_ignores=[]),
                   '<actual-phase3-prelayout-handoff>', 'exec')
    for status, rejected, mode in [
            ('PASS', False, 'dual'), ('PASS', False, 'librelane'),
            ('FAIL', False, 'dual'), ('NOT_MEASURED', False, 'dual'),
            ('PASS', True, 'dual'), ('PASS', False, 'direct')]:
        calls = []
        producer = P.StepResult('prelayout_signoff', status, 0, 'neutral producer',
                               reason_class='tool_absent' if status == 'NOT_MEASURED' else '')
        rejection = P.StepResult('canonical_consumer', 'FAIL', 0, 'neutral rejection') if rejected else None
        postcheck = D.StepResult('sdc_validation', 'PASS', 0, 'neutral consumer')
        plan = []

        def prelayout(current, top, pdk, container):
            assert current == tmp_path and top == 'top' and not plan
            calls.append('producer')
            return producer

        def acceptance(current, started):
            assert current == tmp_path and plan[0] is producer
            calls.append('acceptance')
            return rejection

        def post(current, top):
            assert current == tmp_path and top == 'top'
            assert producer.status == 'PASS' and rejection is None
            assert plan == [producer]
            calls.append('postcheck')
            return postcheck

        monkeypatch.setattr(P, 'step_prelayout_signoff', prelayout)
        monkeypatch.setattr(P, '_default_prelayout_rejection', acceptance)
        monkeypatch.setattr(D, 'step_sdc_validation_post_prelayout', post)
        monkeypatch.setattr(LC, 'selected_mode', lambda *_: mode)
        env = dict(vars(P), project=tmp_path, effective_top='top', pdk=object(),
                   args=SimpleNamespace(container='unused'), plan=plan)
        exec(code, env)
        runs = status == 'PASS' and not rejected and mode in ('dual', 'librelane')
        assert calls == (['producer', 'acceptance', 'postcheck', 'acceptance']
                         if runs else ['producer', 'acceptance'])
        assert plan == ([producer, postcheck] if runs else [producer])


@pytest.mark.parametrize('producer_status', ['PASS', 'FAIL', 'NOT_MEASURED'])
@pytest.mark.parametrize('synth_status', ['PASS', 'NOT_MEASURED'])
def test_phase2_finishes_deferred_step8_before_its_audit(
        tmp_path, monkeypatch, producer_status, synth_status):
    # A Phase-2 audit reads the real Step-8 gate before Phase 3 can start.
    # Tool file writes are substituted; the Step-8 consumers remain real.
    import sdc_syntax_check as syntax
    gate, _deck, _netlist = project(tmp_path)
    gate.unlink()
    assert not syntax.audit(str(tmp_path)).passed
    early = D.step_sdc_validation(tmp_path)
    synth = D.StepResult('yosys_synth', synth_status, 0, 'mapped producer',
                         output_files=[str(_netlist)], extras={'synth_top': 'top'},
                         reason_class='inconclusive' if synth_status == 'NOT_MEASURED' else '')
    plan = [early, synth]
    calls = []

    def native(current, top, pdk, container):
        calls.append(('native', current, top))
        if producer_status == 'PASS':
            LP.judge_sdc(current / 'phase3/librelane/prelayout/design_sdc',
                         {'PNR_SDC_FILE': str(_deck)}, _deck, gate)
        return D.StepResult('prelayout_signoff', producer_status, 0, 'tool edge',
                            reason_class='tool_absent' if producer_status == 'NOT_MEASURED' else '')

    monkeypatch.setattr(P, 'step_prelayout_signoff', native)
    monkeypatch.setattr(D, '_phase2_pdk_config', lambda *_: object())
    tree = ast.parse(Path(D.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    blocks = [n for n in main.body if isinstance(n, ast.If) and
              any(isinstance(call, ast.Call) and
                  isinstance(call.func, ast.Name) and
                  call.func.id == 'step_sdc_validation_post_prelayout'
                  for call in ast.walk(n))]
    assert len(blocks) == 1, 'Phase 2 audits Step 8 before its native producer runs'
    block = blocks[0]
    audit = next(n for n in ast.walk(main) if isinstance(n, ast.Call) and
                 isinstance(n.func, ast.Name) and n.func.id == '_audit_after_declared_producers')
    assert synth is plan[-1]
    synth_audit = next(n for n in ast.walk(main) if isinstance(n, ast.Call) and
                       isinstance(n.func, ast.Name) and n.func.id == 'step_synth_log_audit')
    assert synth_audit.lineno < block.lineno
    assert block.lineno < audit.lineno
    env = dict(vars(D), project=tmp_path, plan=plan, _synth_row=synth,
               args=SimpleNamespace(pdk='gf180mcuD', container='unused'),
               _execution=SimpleNamespace(_ordinary_runtime={'policy': {'mode': 'default'}}))
    exec(compile(ast.Module(body=[block], type_ignores=[]), '<phase2-handoff>', 'exec'), env)
    assert calls == [('native', tmp_path, 'top')]
    if producer_status == 'PASS':
        assert plan[-1].name == 'sdc_validation'
        assert plan[-1].status == 'PASS', plan[-1].detail
        assert syntax.audit(str(tmp_path)).passed
        assert D._aggregate_verdict(plan) == synth_status
    else:
        assert not gate.exists()
        assert not syntax.audit(str(tmp_path)).passed
        assert D._aggregate_verdict(plan) == producer_status


@pytest.mark.parametrize('mode,synth_status', [('default', 'NOT_APPLICABLE'), ('ultra', 'PASS')])
def test_phase2_handoff_preserves_checkpoint_and_ultra_paths(tmp_path, monkeypatch, mode, synth_status):
    tree = ast.parse(Path(D.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    block = next(n for n in main.body if isinstance(n, ast.If) and
                 any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and
                     c.func.id == 'step_sdc_validation_post_prelayout' for c in ast.walk(n)))
    synth = D.StepResult('yosys_synth', synth_status, 0, 'checkpoint',
                         extras={'synth_top': 'top'},
                         declared_by='--entry-step 11' if synth_status == 'NOT_APPLICABLE' else '')
    early = D.StepResult('sdc_validation', 'NOT_MEASURED', 0, 'deferred',
                         extras={'deferred_until': 'post_prelayout'}, reason_class='upstream_failed')
    plan = [early, synth]
    monkeypatch.setattr(P, 'step_prelayout_signoff', lambda *_:
                        pytest.fail('upstream checkpoint or Ultra native path was dispatched again'))
    env = dict(vars(D), project=tmp_path, plan=plan, _synth_row=synth,
               args=SimpleNamespace(pdk='gf180mcuD', container='unused'),
               _execution=SimpleNamespace(_ordinary_runtime={'policy': {'mode': mode}}))
    exec(compile(ast.Module(body=[block], type_ignores=[]), '<phase2-handoff>', 'exec'), env)
    assert plan == [early, synth]


def _neutral_phase2_prelayout(project, monkeypatch, *, native_status='PASS', slack=0.25,
                             bad_pvt=False):
    """Substitute tool/emitter writes; retain real callers and SDC/STA consumers."""
    import execution_backend_gates as gates
    import flow_compliance_check as compliance
    import step_preflight as preflight
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'7': 'direct', '8': 'dual', '10': 'direct'}})
    put(project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
        {'clocks': {'clk': {'period_ns': 10}}})
    put(project / 'phase2/stage1/rtl/widget.v',
        'module widget(input clk, d, output q); assign q=d; endmodule\n')
    for corner in ('ss', 'tt'):
        put(project / f'input/pdk/liberty/neutral__{corner}.lib', 'library(neutral) {}\n')
    pdk = SimpleNamespace(name='fixture-pdk', liberty='neutral__tt.lib', macro_libs=[])
    monkeypatch.setattr(E, '_ordinary_runtime',
                        {'project': project, 'policy': {'mode': 'default'}, 'parameters': {}})
    monkeypatch.setattr(D, '_phase2_pdk_config', lambda *_: pdk)
    monkeypatch.setattr(preflight, 'decide', lambda _p, runner, site, **_k:
                        preflight.Decision(runner=runner, site=site, allow=True,
                            flow_steps=['7' if site == 'asic_sdc' else '9'], verdict='READY'))
    monkeypatch.setattr(preflight, 'record', lambda *a, **k: None)
    events = []

    def emit(_runner, current, top, _pdk, _container):
        deck = put(current / f'phase2/stage2/constraints/{top}.asic.sdc',
                   'create_clock -name clk -period 10 [get_ports clk]\n'
                   'set_input_delay 1 -clock clk [get_ports d]\n'
                   'set_output_delay 1 -clock clk [get_ports q]\n')
        rec = {'path': str(deck.relative_to(current)), 'sha256': LC.digest(deck),
               'text': deck.read_text(), 'design_staged': False}
        put(current / 'phase2/stage2/constraints/asic_sdc.json', rec)
        return rec

    def synth(current, top, *_args, **_kwargs):
        events.append('synthesis')
        nl = put(current / f'phase2/stage2/synth/{top}_synth.v',
                 (current / f'phase2/stage1/rtl/{top}.v').read_text())
        return D.StepResult('yosys_synth', 'PASS', 0.0, 'neutral mapped tool write',
                            [str(nl)], extras={'synth_top': top})

    def native(current, top, _pdk, deck, *_args, **_kwargs):
        events.append('native prelayout')
        nl = current / f'phase2/stage2/synth/{top}_synth.v'
        assert nl.is_file(), 'the actual caller must synthesize before native SDC validation'
        state = put(current / 'phase3/librelane/prelayout/neutral/state_out.json', {'nl': str(nl)})
        gate = {'step': '8', 'program': 'librelane_prelayout.judge_sdc',
                'verdict': native_status, 'findings': [],
                'sdc': str(deck), 'sdc_sha256': LC.digest(deck),
                'netlist': str(nl), 'netlist_sha256': LC.digest(nl),
                'source': str(state), 'state_out_sha256': LC.digest(state)}
        put(current / 'phase3/librelane/prelayout/gates/step8_sdc_opensta.json', gate)
        return {'sdc': gate, 'slack': {'verdict': 'PASS', 'findings': []}}

    def corners(current, _top, _pdk, _container, _libs, folder, _notes, **_kwargs):
        for index, label in enumerate(('SS', 'TT')):
            value = slack + index * 0.1
            put(folder / f'sta_{label}.rpt',
                f'# neutral corner {label}\n'
                'Startpoint: reg_a (rising edge-triggered flip-flop)\n'
                'Endpoint: reg_b (rising edge-triggered flip-flop)\n'
                f'  {value} slack ({"MET" if value >= 0 else "VIOLATED"})\n'
                f'tns {min(value, 0)}\nwns {min(value, 0)}\n'
                'STA_BASIS: PRE_LAYOUT_ESTIMATE\n')
        return True

    monkeypatch.setattr(P._ppa_timing, 'emit_step7_asic_sdc', emit)
    monkeypatch.setattr(D, 'step_yosys_synth', synth)
    def prepare(current, top, _pdk, deck):
        # The existing native transport below supplies this resolved fixture.
        # Preparation is not a native execution or a consumer verdict.
        events.append('prepare prelayout')
        return {'resolved': {'STA_CORNERS': ['neutral__ss', 'neutral__tt'],
                             'DEFAULT_CORNER': 'neutral__tt',
                             'LIB': {'neutral__*': [str(current / 'input/pdk/liberty/neutral__tt.lib')]}}}

    monkeypatch.setattr(P, '_prepare_prelayout_librelane', prepare, raising=False)
    monkeypatch.setattr(P, '_prelayout_librelane', native)
    monkeypatch.setattr(P, '_emit_multi_corner_sta', corners)
    # Other flow prerequisites are neutral controls. The changed SDC, PVT,
    # STA consumers and every canonical output/authorship check remain real.
    original_program = compliance._check_program_exit_zero
    def program(current, command):
        name = command.split()[0]
        if name in ('sdc_syntax_check', 'pvt_matrix_check', 'sta_report_check', 'sdc_validator_check'):
            events.append('consumer ' + name)
            return original_program(current, command)
        compliance._record_gate_execution(name, 0, 'PASS')
        return True, 'neutral unrelated prerequisite'
    monkeypatch.setattr(compliance, '_check_program_exit_zero', program)
    original_evaluate = gates.evaluate
    def evaluate(current, row):
        if str(row['id']) == '9':
            return {'status': 'PASS', 'ledger': [], 'step': {'id': '9', 'status': 'PASS'}}
        if str(row['id']) == '10':
            summary = current / 'reports/phase3/sta/pre_pnr_summary.json'
            events.append(('summary before consumer', json.loads(summary.read_text()) if summary.is_file() else None))
        if str(row['id']) == '7' and bad_pvt:
            put(current / 'phase2/stage2/constraints/pvt_matrix.json', {'corners': []})
        return original_evaluate(current, row)
    monkeypatch.setattr(gates, 'evaluate', evaluate)
    original_contracts = gates.contracts
    monkeypatch.setattr(gates, 'contracts', lambda current, row:
                        {'neutral_synthesis': {}} if str(row['id']) == '9'
                        else original_contracts(current, row))
    return pdk, events


def _actual_phase2_constraint_prefix(project):
    """Execute the unchanged fixed-order main call sites, not a copied schedule."""
    tree = ast.parse(Path(D.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    names = {'step_asic_sdc', 'step_sdc_validation', 'step_yosys_synth',
             'step_sdc_validation_post_prelayout'}
    blocks = [n for n in main.body if isinstance(n, ast.If) and any(
        isinstance(c, ast.Name) and c.id in names for c in ast.walk(n))]
    assert len(blocks) == 4
    plan = []
    env = dict(vars(D), project=project, plan=plan, ic_class='digital',
               args=SimpleNamespace(top_name='widget', pdk='fixture-pdk', container='unused', entry_step=None),
               _execution=E, _entry_site=None, _before_entry=lambda *_: False,
               _after_exit=lambda *_: False, _analog_absent=False, _analog_reason='')
    for block in blocks:
        if 'synth_top' in ast.unparse(block):
            env['_synth_row'] = plan[-1]
        exec(compile(ast.Module(body=[block], type_ignores=[]), '<actual-phase2-constraints>', 'exec'), env)
    return plan


def _complete_consumers(project, sid):
    import step_output_collector as versions
    records = []
    for path in (project / 'steps').glob('*/*/*/outputs.json'):
        record = json.loads(path.read_text())
        if record['id'] == sid and (record.get('result') or {}).get('canonical_consumer'):
            records.append(record)
    return sorted(records, key=lambda r: r['finished_at'])


def test_default_constraint_caller_defers_step7_until_current_native_evidence(tmp_path, monkeypatch):
    _pdk, events = _neutral_phase2_prelayout(tmp_path, monkeypatch)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    early = next(r for r in plan if r.name == 'asic_sdc')
    assert early.status == 'NOT_MEASURED', early.detail
    assert early.extras['producer_status'] == 'PASS'
    assert early.extras['deferred_until'] == 'post_prelayout'
    accepted = _complete_consumers(tmp_path, '7')
    assert accepted, accepted
    assert accepted[0]['status'] == 'PASS', accepted
    assert accepted[0]['canonical_pass'] is True
    assert events.index('synthesis') < events.index('native prelayout') < events.index('consumer sdc_syntax_check')
    assert D._aggregate_verdict(plan) == 'PASS'


@pytest.mark.parametrize('native_status', ['FAIL', 'NOT_MEASURED'])
def test_current_native_failure_cannot_release_deferred_step7(tmp_path, monkeypatch, native_status):
    _neutral_phase2_prelayout(tmp_path, monkeypatch, native_status=native_status)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    assert not _complete_consumers(tmp_path, '7')
    assert D._aggregate_verdict(plan) == native_status


def test_measured_pvt_failure_outranks_deferred_step7(tmp_path, monkeypatch):
    _neutral_phase2_prelayout(tmp_path, monkeypatch, bad_pvt=True)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    consumers = _complete_consumers(tmp_path, '7')
    assert consumers and consumers[-1]['status'] == 'FAIL'
    assert D._aggregate_verdict(plan) == 'FAIL'


@pytest.mark.parametrize('change', ['no_late_record', 'old_record', 'changed_sdc', 'changed_rtl', 'unrelated_project'])
def test_late_step7_acceptance_must_be_current_and_owned(tmp_path, monkeypatch, change):
    _neutral_phase2_prelayout(tmp_path, monkeypatch)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    assert D._aggregate_verdict(plan) == 'PASS'
    early = next(r for r in plan if r.name == 'asic_sdc')
    if change == 'no_late_record':
        import step_output_collector as versions
        records = versions.current_acceptance(tmp_path, early.extras['deferred_started_at'])
        record = next(r for r in records if r['id'] == '7')
        path = tmp_path / 'steps' / record['folder'] / 'outputs.json'
        path.rename(path.with_name('control-preserved-outputs.json'))
    elif change == 'old_record':
        import time
        early.extras['deferred_started_at'] = time.time()
    elif change == 'changed_sdc':
        deck = tmp_path / 'phase2/stage2/constraints/widget.asic.sdc'
        deck.write_text(deck.read_text() + '# changed after acceptance\n')
    elif change == 'changed_rtl':
        rtl = tmp_path / 'phase2/stage1/rtl/widget.v'
        rtl.write_text(rtl.read_text() + '// input changed after acceptance\n')
    else:
        other = tmp_path / 'unrelated'
        _pdk, _events = _neutral_phase2_prelayout(other, monkeypatch)
        early = D.step_asic_sdc(other, 'widget', 'unused', pdk_config=_pdk,
                                _use_controller=False)
        plan = [early] + [r for r in plan if r.name != 'asic_sdc']
    assert D._aggregate_verdict(plan) == 'NOT_MEASURED'


def test_current_sta_violation_cannot_publish_accepted_summary(tmp_path, monkeypatch):
    _neutral_phase2_prelayout(tmp_path, monkeypatch, slack=-0.5)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    summary = json.loads((tmp_path / 'reports/phase3/sta/pre_pnr_summary.json').read_text())
    assert summary['passed'] is False
    assert D._aggregate_verdict(plan) == 'FAIL'
    assert not _complete_consumers(tmp_path, '10')


def test_unavailable_summary_producer_keeps_prelayout_unmeasured(tmp_path, monkeypatch):
    _neutral_phase2_prelayout(tmp_path, monkeypatch)
    def unavailable(_project):
        raise LC.Refusal('PRELAYOUT_STA_SUMMARY_UNAVAILABLE', 'neutral unavailable producer')
    monkeypatch.setattr(P, '_publish_prelayout_summary', unavailable)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    assert D._aggregate_verdict(plan) == 'NOT_MEASURED'
    assert not _complete_consumers(tmp_path, '10')


def test_retained_prelayout_publishes_summary_before_first_complete_consumer(tmp_path, monkeypatch):
    import _gate_authorship as authorship
    _pdk, _events = _neutral_phase2_prelayout(tmp_path, monkeypatch)
    plan = _actual_phase2_constraint_prefix(tmp_path)
    accepted = _complete_consumers(tmp_path, '10')
    assert accepted, accepted
    assert accepted[0]['status'] == 'PASS', accepted
    produced = next(doc for label, doc in (e for e in _events if isinstance(e, tuple))
                    if label == 'summary before consumer')
    assert produced and authorship.role_of(produced) == 'producer'
    assert produced['record_role'] == 'prelayout_audit'
    summary = tmp_path / 'reports/phase3/sta/pre_pnr_summary.json'
    doc = json.loads(summary.read_text())
    # Canonical auditing may rewrite the live view; the frozen producer-owned
    # output was present before its first complete consumer started.
    frozen = next(o for o in accepted[0]['outputs'] if o['rel'] == str(summary.relative_to(tmp_path)))
    assert frozen['sha256']
    assert not accepted[0]['result']['canonical_consumer']['step'].get('missing_before_consumer')
    assert doc['passed'] is True and doc['subject']['basis'] == 'content'
    assert D._aggregate_verdict(plan) == 'PASS'


def _step7_owned_postcheck_fixture(tmp_path, monkeypatch, *, design_staged=False):
    """Run the real Step7 emitter; only its authored neutral text is supplied."""
    from _ppa import timing
    gate, pnr, netlist = project(tmp_path)
    text = pnr.read_text()
    # Start before Step7 has an output. This is fixture construction, not a
    # change to the original helper or any retained production run.
    (tmp_path / 'phase2/stage2/constraints/top.asic.sdc').unlink()
    liberty = put(tmp_path / 'input/pdk/liberty/neutral.lib', 'library(neutral) {}\n')
    pdk = SimpleNamespace(name='neutral', liberty=str(liberty), macro_libs=[])
    monkeypatch.setattr(timing, 'author_asic_sdc', lambda *_a, **_k: {
        'text': text, 'design_staged': design_staged, 'staged_sdc': None})
    emitted = timing.emit_step7_asic_sdc(P, tmp_path, 'top', pdk, 'LOCAL')
    canonical = tmp_path / emitted['path']
    record = canonical.parent / timing.ASIC_SDC_RECORD
    judged = LP.judge_sdc(tmp_path / 'phase3/librelane/prelayout/design_sdc',
                         {'PNR_SDC_FILE': str(canonical)}, canonical, gate)
    assert judged['verdict'] == 'PASS'
    assert timing.owned_step7_outputs(P, tmp_path)[emitted['path']] == LC.digest(canonical)
    return gate, canonical, pnr, record


@pytest.mark.parametrize('design_staged,pnr_state', [
    (False, 'absent'), (False, 'derived'), (True, 'derived')])
def test_postcheck_consumes_the_step7_producers_selected_deck(
        tmp_path, monkeypatch, design_staged, pnr_state):
    gate, canonical, pnr, record = _step7_owned_postcheck_fixture(
        tmp_path, monkeypatch, design_staged=design_staged)
    if pnr_state == 'absent':
        pnr.unlink()
    else:
        pnr.write_text(pnr.read_text() + 'set_max_fanout 4 [current_design]\n')
    before = {p: p.read_bytes() for p in (gate, canonical, record)}
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'PASS', row.detail
    receipt = json.loads(Path(row.output_files[0]).read_text())
    assert [r['rc'] for r in receipt['records']] == [0, 0]
    inputs = receipt['binding']['inputs']
    assert inputs['canonical_sdc']['path'] == str(canonical)
    assert inputs['canonical_sdc']['sha256'] == LC.digest(canonical)
    assert inputs['step7_sdc_record']['sha256'] == LC.digest(record)
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('changed', ['canonical', 'record', 'wrong_gate_deck'])
def test_postcheck_keeps_selected_step7_deck_binding_strict(tmp_path, monkeypatch, changed):
    gate, canonical, pnr, record = _step7_owned_postcheck_fixture(tmp_path, monkeypatch)
    if changed == 'canonical':
        canonical.write_text(canonical.read_text() + 'set_max_transition 0.25 [current_design]\n')
    elif changed == 'record':
        payload = json.loads(record.read_text())
        payload['sha256'] = '0' * 64
        record.write_text(json.dumps(payload))
    else:
        # This is a genuine wrong-owner gate even when both decks are valid
        # syntax: Step7 selected canonical, but this gate timed the PnR deck.
        LP.judge_sdc(tmp_path / 'phase3/librelane/prelayout/design_sdc',
                     {'PNR_SDC_FILE': str(pnr)}, pnr, gate)
    row = D.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert row.status == 'NOT_MEASURED', row.detail
    assert 'STALE' in row.detail
    receipt = json.loads(Path(row.output_files[0]).read_text())
    assert receipt['records'] == []


def _resolved_pvt_compound_fixture(current, monkeypatch, *, refuse=None):
    """Real preparation/retention/SDC/STA readers; only resolved tool IO is neutral.

    The native edge copies the existing calibration grammar. These controls
    establish software ownership and currentness, not new OpenSTA measurements.
    """
    import step_output_collector as versions
    real_native = P._prelayout_librelane
    real_prepare = getattr(P, '_prepare_prelayout_librelane', None)
    pdk, events = _neutral_phase2_prelayout(current, monkeypatch)
    monkeypatch.setattr(P, '_prelayout_librelane', real_native)
    if real_prepare is None:
        monkeypatch.delattr(P, '_prepare_prelayout_librelane')
    else:
        monkeypatch.setattr(P, '_prepare_prelayout_librelane', real_prepare)
    put(current / 'phase3/librelane_switch.json',
        {'steps': {'7': 'librelane', '8': 'librelane', '10': 'librelane'}})
    put(current / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {
        'clock_domains': [{'role': 'primary', 'period_ns': 10, 'source_pin': 'clk'}]})
    put(current / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'widget'})
    put(current / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {}})
    put(current / 'input/submission_template/tapeout_declaration.json', {'answers': {}})
    mapped = current / 'phase2/stage2/synth/widget_synth.v'
    D.step_yosys_synth(current, 'widget')
    put(current / 'phase2/stage2/synth/netlist.v', mapped.read_text())
    libs = {}
    for process in ('ss', 'tt', 'ff'):
        lib = put(current / f'input/pdk/liberty/neutral__{process}.lib',
                  f'library(neutral_{process}) {{ time_unit : "1ns"; }}\n')
        libs[f'*_{process}_*'] = [str(lib)]
    configured = [f'{parasitic}_{process}_025C'
                  for parasitic in ('min', 'nom', 'max')
                  for process in ('ss', 'tt', 'ff')]
    nominal = [name for name in configured if name.startswith('nom_')]
    resolved_population = {'STA_CORNERS': configured, 'DEFAULT_CORNER': 'nom_tt_025C',
                           'LIB': libs}
    pvt = current / 'phase2/stage2/constraints/pvt_matrix.json'
    put(pvt, LP.pvt_matrix_from_sta_corners(
        {**resolved_population, 'STA_CORNERS': nominal}, None,
        P._classify_corner_from_name))
    initial_sha = LC.digest(pvt)
    root = current / 'fixture-pdk'
    root.mkdir()
    monkeypatch.setattr(LC, 'resolve_image', lambda *_a, **_k: 'software-fixture-image')
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *_a, **_k: {'path': str(root)})
    resolved_calls, tool_calls, captures = [], [], []

    def resolve(project, image, raw, output, **_kwargs):
        resolved_calls.append(json.loads(raw.read_text())['meta']['step'])
        if refuse:
            raise LC.Refusal(refuse, 'neutral prepare transport refused before native')
        return put(output, {**json.loads(raw.read_text()), **resolved_population})

    def native(project, image, steps, **_kwargs):
        tool_calls.append(steps)
        events.append('native prelayout')
        folder = project / 'phase3/librelane/prelayout/design_sdc/tool-output'
        cfg = json.loads(Path(steps[-1][1]).read_text())
        put(folder / 'config.json', cfg)
        state = {'nl': str(mapped), 'metrics': {}}
        calibration = Path(LP.__file__).parent / 'calibration'
        for name in nominal:
            corner = folder / name
            corner.mkdir(parents=True)
            shutil.copyfile(calibration / 'sta_prepnr_linked_clean_negative.log', corner / 'sta.log')
            shutil.copyfile(calibration / 'sta_prepnr_check_setup_clean_negative.rpt', corner / 'checks.rpt')
            process = 'ss' if '_ss_' in name else 'tt'
            for sense in ('max', 'min'):
                shutil.copyfile(calibration / f'sta_prepnr_cal_{process}_{sense}.rpt',
                                corner / f'{sense}.rpt')
            for check, slack in (('setup', 1.0), ('hold', 0.2)):
                for metric, value in (('ws', slack), ('wns', 0), ('tns', 0)):
                    state['metrics'][f'timing__{check}__{metric}__corner:{name}'] = value
        put(folder / 'state_out.json', state)
        return [folder]

    original_begin = versions.begin_steps
    def begin(project, rows):
        rows = list(rows)
        for sid, inputs in rows:
            if str(sid) == '10':
                captures.append({'inputs': dict(inputs), 'matrix': json.loads(pvt.read_text()),
                                 'sha256': LC.digest(pvt), 'events': list(events)})
        return original_begin(project, rows)

    monkeypatch.setattr(LP, 'resolve_step_config', resolve)
    monkeypatch.setattr(LP, 'run_chain', native)
    monkeypatch.setattr(versions, 'begin_steps', begin)
    return pdk, pvt, initial_sha, resolved_population, resolved_calls, tool_calls, captures


@pytest.mark.parametrize('change', ['unchanged', 'corner_population', 'library_population'])
def test_step7_final_pvt_precedes_step10_capture_and_stays_current(tmp_path, monkeypatch, change):
    import step_output_collector as versions
    pdk, pvt, initial, resolved, resolutions, native, captures = _resolved_pvt_compound_fixture(
        tmp_path, monkeypatch)
    result = P.step_prelayout_signoff(tmp_path, 'widget', pdk, 'LOCAL')
    assert result.status == 'PASS', result.detail
    assert len(captures) == 1
    assert len(captures[0]['matrix']['corners']) == 9, captures
    assert captures[0]['sha256'] != initial
    assert captures[0]['inputs'][str(pvt.relative_to(tmp_path))] == captures[0]['sha256']
    assert 'native prelayout' not in captures[0]['events']
    assert resolutions == list(LP.STEPS) and len(native) == 1
    assert LC.digest(pvt) == captures[0]['sha256']
    assert 'prelayout_timed_corners' not in json.loads(pvt.read_text())
    slack = json.loads((tmp_path / 'phase3/librelane/prelayout/gates/step10_slack.json').read_text())
    assert len(slack['corners']) == 3 and slack['verdict'] == 'PASS'
    current = versions.latest_pass(tmp_path, '10')
    assert current and current['current_inputs'] is True, _complete_consumers(tmp_path, '10')
    assert current['result']['canonical_consumer']['status'] == 'PASS'
    if change != 'unchanged':
        # A genuine new configured scene or Liberty population changes Step7's
        # emitted scientific input; the prior Step10 result cannot become current.
        altered = json.loads(json.dumps(resolved))
        if change == 'corner_population':
            altered['STA_CORNERS'].append('nom_tt_100C')
        else:
            alternate = put(tmp_path / 'input/pdk/liberty/alternate_tt.lib',
                            'library(alternate_tt) { time_unit : "1ns"; }\n')
            altered['LIB']['*_tt_*'] = [str(alternate)]
        put(pvt, LP.pvt_matrix_from_sta_corners(altered, None, P._classify_corner_from_name))
        assert LC.digest(pvt) != captures[0]['sha256']
        assert versions.latest_pass(tmp_path, '10')['current_inputs'] is False


@pytest.mark.parametrize('refusal,expected', [('LL_TOOL_DEADLINE', 'NOT_MEASURED'),
                                               ('LL_STEP_FAILED', 'FAIL')])
def test_pvt_preparation_refusal_cannot_run_native_or_accept_step10(
        tmp_path, monkeypatch, refusal, expected):
    import step_output_collector as versions
    pdk, _pvt, _initial, _resolved, resolutions, native, captures = _resolved_pvt_compound_fixture(
        tmp_path, monkeypatch, refuse=refusal)
    result = P.step_prelayout_signoff(tmp_path, 'widget', pdk, 'LOCAL')
    assert result.status == expected, result.detail
    assert resolutions == [LP.STEPS[0]]
    assert native == [] and captures == []
    assert versions.latest_pass(tmp_path, '10') is None
    index = json.loads((tmp_path / 'steps/index.json').read_text())
    row7 = next(row for row in index['steps'] if row['id'] == '7')
    actual = json.loads((tmp_path / 'steps' / row7['folder'] / 'outputs.json').read_text())
    assert actual['status'] == expected and actual['canonical_pass'] is False
