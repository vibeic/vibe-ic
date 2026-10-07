"""Step 8 waits for its tool producer, then consumes current evidence directly."""
import ast
import json
import shutil
from dataclasses import asdict
from pathlib import Path

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
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'direct'}})
    calls = []
    monkeypatch.setattr(E, 'dispatch_fixed_step', lambda *a, **k:
                        calls.append(a) or {'status': 'ADOPTED'})
    assert D.step_sdc_validation(tmp_path).status == 'PASS'
    assert calls == [(tmp_path, '8')]


def project(tmp_path):
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'8': 'dual'}})
    deck = put(tmp_path / 'phase3/stage3/pnr/constraint.sdc',
               'create_clock -name clk -period 10 [get_ports clk]\n'
               'set_input_delay 1 -clock clk [get_ports d]\n'
               'set_output_delay 1 -clock clk [get_ports q]\n')
    put(tmp_path / 'phase2/stage2/constraints/top.asic.sdc', deck.read_text())
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
    for name, path in [('opensta_gate', gate), ('pnr_sdc', deck), ('mapped_netlist', nl)]:
        assert doc['binding']['inputs'][name]['sha256'] == LC.digest(path)
    history = json.loads(report.read_text())
    assert [x['status'] for x in history['steps']] == ['NOT_MEASURED', 'PASS']
    assert history['verdict'] == 'PASS'
    assert early.status == 'NOT_MEASURED'
    assert D._aggregate_verdict([early, row]) == 'PASS'
    gate.write_text(gate.read_text() + '\n')
    assert D._aggregate_verdict([early, row]) == 'NOT_MEASURED'


@pytest.mark.parametrize('changed', ['gate', 'deck', 'netlist'])
def test_mutation_during_consumers_refuses_current_postcheck(tmp_path, monkeypatch, changed):
    paths = dict(zip(('gate', 'deck', 'netlist'), project(tmp_path)))
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
