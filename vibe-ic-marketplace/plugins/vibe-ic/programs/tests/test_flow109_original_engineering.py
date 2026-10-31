"""Bounded original component evidence, never full-row tool qualification."""
import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest
import _path_layout as layout
import design_one_shot_runner as design
import flow109
import flow109_engineering as engineering
import librelane_contract as contract
from _hostpaths import require_repo


def project(tmp_path, rtl='module neutral(input a, output y); assign y=a; endmodule\n'):
    p = tmp_path / 'subject'
    (p / 'input').mkdir(parents=True)
    (p / 'input/phase1_prompt.md').write_text('Create a combinational buffer with input a and output y.')
    d = p / 'phase2/stage1/rtl'; d.mkdir(parents=True)
    (d / 'neutral.v').write_text(rtl)
    return p


def context(**kwargs):
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
        if p['name'] == 'Small digital IC without DFT'))
    return flow109.execution_context(flow109.resolve_plan(features), 'D11', 'D11', **kwargs)


def run(p, monkeypatch):
    monkeypatch.setattr(contract, 'selected_mode', lambda *_: 'direct')
    with layout.rtl_input_view(p, 'original'):
        return design._step_d11_original_engineering(p, context(), pdk_name=None,
            bounded_rtl=True, top_name='neutral', container='')


def test_source_owned_original_does_not_require_qualified_d09_d10(tmp_path, monkeypatch):
    p = project(tmp_path)
    monkeypatch.setattr(contract, 'selected_mode', lambda *_: 'direct')
    current = context()
    path = tmp_path / 'context.json'; path.write_text(json.dumps(current))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    monkeypatch.setattr(design, '_verilator_stage_exec', lambda *_: lambda argv, *_:
        (0, 'Verilator software execution seam\n', ''))
    with layout.rtl_input_view(p, 'original'):
        observed = design.step_rtl_lint_tool(p, top_name='neutral', container='')
    # VALUE comparison on base: it returns NOT_MEASURED/D11_EVIDENCE_UNPROVEN.
    assert observed.status == 'PASS', observed.detail
    assert observed.name == 'rtl_validate'


def test_runtime_claim_cannot_use_engineering_admission(tmp_path):
    p = project(tmp_path)
    with layout.rtl_input_view(p, 'original'):
        assert engineering.selected_original(p, context()) is True
        assert engineering.selected_original(p, context(runtime_tool_uses=[])) is False
        assert engineering.selected_original(p, context(qualification_registry='absent.json')) is False
    assert engineering.selected_original(p, context()) is False


def test_real_native_component_and_source_output_staleness(tmp_path, monkeypatch):
    p = project(tmp_path)
    rows = run(p, monkeypatch)
    assert rows[-1].status == 'PASS', [(r.name,r.status,r.detail) for r in rows]
    with layout.rtl_input_view(p, 'original'):
        record = rows[-1].extras['engineering_evidence']
        assert engineering.consume(p, record, [asdict(r) for r in rows]) == 'PASS'
        (p / 'phase2/stage1/rtl/new.vh').write_text('`define ADDED 1\n')
        with pytest.raises(ValueError, match='SUBJECT_STALE'):
            engineering.consume(p, record, [asdict(r) for r in rows])
        (p / 'phase2/stage1/rtl/new.vh').unlink()
        output = p / record['checks'][-1]['outputs'][0]['path']
        output.write_text('[{"corrupted":true}]')
        with pytest.raises(ValueError, match='STALE'):
            engineering.consume(p, record, [asdict(r) for r in rows])


def test_real_rom_failure_is_component_failure(tmp_path, monkeypatch):
    p = project(tmp_path, 'module neutral(input a, output y); reg [7:0] mem [0:3]; integer i;\n'
        'initial begin for(i=0;i<4;i=i+1) mem[i]=i; end\nassign y=a ^ mem[0][0]; endmodule\n')
    rows = run(p, monkeypatch)
    assert next(r for r in rows if r.name == 'rom_init_lint').status == 'FAIL'
    assert rows[-1].status == 'FAIL', [(r.name,r.status,r.detail) for r in rows]


def test_empty_native_proof_is_not_measured(tmp_path, monkeypatch):
    p = project(tmp_path)
    monkeypatch.setattr(design, '_step_rtl_hygiene_native', lambda *_:
        design.StepResult('rtl_validate', 'NOT_MEASURED', 0, 'no native context', reason_class='not_executed'))
    rows = run(p, monkeypatch)
    assert rows[-1].status == 'NOT_MEASURED'


def test_real_flow_contract_requires_executed_rewrite_rom_and_hygiene():
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'phase1_phase2_phase3.yaml')
    import yaml
    doc = yaml.safe_load(path.read_text())
    # Consume the checked-in contract, not a second handwritten requirement list.
    steps = doc['flow']['steps'] if 'flow' in doc else doc['steps']
    row = next(s for s in steps if str(s['id']) == '2')
    commands = [r.get('program_exit_zero', '') for r in row['input_contracts']['original']['gate']['all_of']]
    assert all(any(name in command for command in commands) for name in
        ('crosslayer_rewrite_equivalence_check', 'rtl_hygiene_lint', 'rom_init_lint'))


@pytest.mark.parametrize('state,expected', [('current','PASS'), ('wrong_invocation','NOT_MEASURED'),
    ('not_published','NOT_MEASURED'), ('source_changed','NOT_MEASURED')])
def test_real_owner_finalization_preserves_component_row_boundary(tmp_path, monkeypatch, state, expected):
    import os
    import sys
    import benchmark_dispatch as dispatch
    import vibe_ic_one_shot_runner as runner
    p = project(tmp_path)
    current = context()
    attempt = flow109._new_attempt(p, current)
    request = tmp_path / 'selected.json'; request.write_text(json.dumps(current))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    rows = run(p, monkeypatch)
    assert rows[-1].status == 'PASS', rows[-1].detail
    argv = [sys.executable, design.__file__, str(p), '--entry-step', '2', '--exit-step', '2', '--rtl-input', 'original']
    invocation = {'invocation_id':'neutral-owner', 'argv':argv, 'project':str(p),
        'source':dispatch._runner_source_snapshot(argv)}
    summary = {'project':str(p), 'steps':[asdict(row) for row in rows], 'verdict':'PASS',
        'declared_window':{'entry_step':'2','exit_step':'2','dispatched_step_ids':['2']}}
    path = attempt / 'phase2_one_shot.json'
    design._write_phase2_report(path, summary, p, invocation_context=invocation)
    report = json.loads(path.read_bytes())
    if state == 'wrong_invocation': invocation = {**invocation, 'invocation_id':'foreign'}
    if state == 'source_changed': (p / 'input/phase1_prompt.md').write_text('A changed requirement')
    with layout.rtl_input_view(p, 'original'):
        result = runner._finish_d11_selected_owner(p, report, invocation,
            published_current=state != 'not_published')
    assert result['verdict'] == expected, result
    finished = json.loads((attempt / 'result.json').read_bytes())
    assert finished['component_status'] == expected
    assert finished['default_row_status'] == finished['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert finished['components'][0]['completed'] is False
    assert finished['delivery_accepted'] is False
