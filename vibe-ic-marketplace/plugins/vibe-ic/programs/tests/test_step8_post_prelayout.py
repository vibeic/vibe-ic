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
