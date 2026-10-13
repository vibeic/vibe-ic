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


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


@pytest.mark.parametrize('mode', ['dual', 'librelane'])
def test_tool_step8_defers_before_synth_without_frontend_dispatch(tmp_path, monkeypatch, mode):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': mode}})
    calls = []
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *a, **k:
                        calls.append(a) or {'status': 'ADOPTED'})
    row = D.step_sdc_validation(tmp_path)
    assert row.status == 'NOT_MEASURED'
    assert 'SDC_VALIDATION_DEFERRED' in row.detail
    assert row.extras['deferred_until'] == 'post_prelayout'
    assert not calls


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
    monkeypatch.setattr(E, '_ordinary_runtime', {'policy': {'mode': 'default'}})
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *_a, **_k:
                        pytest.fail('Default direct Step 8 dispatched a Controller'))
    row = D.step_sdc_validation(tmp_path)
    assert row.status == ('PASS' if present else 'FAIL'), row.detail
    report = tmp_path / 'reports/phase2/sdc_check.json'
    assert report.is_file()
    assert str(report) in row.output_files
    assert 'deferred_until' not in row.extras


def test_default_direct_step8_refuses_rc_zero_without_fresh_output(tmp_path, monkeypatch):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'direct'}})
    put(tmp_path / 'reports/phase2/sdc_check.json', {'stale': 'PASS'})
    monkeypatch.setattr(E, '_ordinary_runtime', {'policy': {'mode': 'default'}})
    monkeypatch.setattr(D, '_run', lambda *_a, **_k: (0, '', ''))
    row = D.step_sdc_validation(tmp_path)
    assert row.status == 'FAIL'
    assert 'SDC_CHECK_OUTPUT_ABSENT' in row.detail
    assert row.output_files == []


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


def test_postcheck_is_wired_only_after_passing_prelayout():
    tree = ast.parse(Path(P.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    guarded = [n for n in ast.walk(main) if isinstance(n, ast.If) and
               ast.unparse(n.test) == "_pls.status == 'PASS'"]
    assert any('step_sdc_validation_post_prelayout(project, effective_top)' in
               ast.unparse(n) for n in guarded)


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

    def native(current, top, _pdk, deck, *_args):
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
