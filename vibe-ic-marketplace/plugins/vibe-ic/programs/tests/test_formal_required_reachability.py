"""SOFTWARE source controls; optional native control requires explicit E authorization.

The default suite executes no solver. Native tests use only the exact two-property
constant-output input below, once E receives root's command authorization.
"""
import json
from pathlib import Path
import shutil

import pytest
import formal_property_run as producer
from test_flow109_d14_metric_binding import case as base_case, put, sha, reseal


@pytest.fixture
def reach_case(base_case):
    project, ctx = base_case
    formal = project / 'phase2/stage1/formal'
    put(formal / 'formal_neutral.sv', '''module formal_neutral(input clk);
wire q;
neutral dut(.clk(clk), .q(q));
reg ready = 1'b0;
always @(posedge clk) ready <= 1'b1;
property p_output;
 @(posedge clk) (1'b1) |-> (q == 0);
endproperty
assert property (p_output);
property p_delayed;
 @(posedge clk) ready |-> (q == 0);
endproperty
assert property (p_delayed);
endmodule
''')
    put(formal / 'property_contract.json', {'program': 'formal_harness_gen',
        'chip_read_top': 'neutral', 'property_denominator': 2,
        'covered_obligations': [
            {'id': 'RTL.output', 'property': 'p_output', 'author': 'formal_harness_gen'},
            {'id': 'RTL.delayed', 'property': 'p_delayed', 'author': 'formal_harness_gen'}],
        'unresolved_obligations': []})
    result = reseal(project)
    result.update(property_denominator=2, authored_property_count=2, covered_property_count=2)
    put(formal / 'results.json', result)
    return project, ctx


def software_covers(project, *, statuses=None):
    """Generate through actual emit-only producer, then add marked software log/VCD."""
    emitted = producer.run_reachability(project, emit_only=True)
    formal, original, original_sby, harness, plan, inputs = producer._reachability_inputs(project)
    work = formal / 'reachability'
    sby = work / 'formal_reachability.sby'
    cfg = producer.parse_sby_config(sby.read_text())
    transcript = 'SOFTWARE_ONLY_NOT_NATIVE_EXECUTION\n' + ''.join(
        f'SBY 12:00:00 [formal_reachability_{task}] DONE ({(statuses or {}).get(task, "PASS")}, rc=0)\n'
        for task in cfg)
    log = work / 'formal_reachability.sby.log';put(log, transcript)
    witnesses = {}
    for task in cfg:
        for name in original['proof_inputs']['files']:
            dest = work / f'formal_reachability_{task}/src/{name}'
            dest.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(work / name, dest)
        witnesses[task] = {}
        if (statuses or {}).get(task, 'PASS') == 'PASS':
            vcd = work / f'formal_reachability_{task}/engine_0/trace0.vcd'
            put(vcd, '$comment SOFTWARE_ONLY_NOT_NATIVE $end\n$enddefinitions $end\n#0\n#1\n')
            witnesses[task][str(vcd.relative_to(project))] = sha(vcd)
    targets = {}
    for task in emitted['tasks']:
        source = task['cover_source']
        model = work / f"formal_reachability_{task['task']}/model/cover_identity.json"
        put(model, {'creator': 'SOFTWARE_CONTROL_NOT_NATIVE', 'modules': {'formal_neutral': {'cells': {
            '$generated$cover$17': {'type': '$check', 'parameters': {'FLAVOR': 'cover'},
                'attributes': {'src': f"{source['file']}:{source['line']}.2-{source['line']}.40"}}
        }}}})
        targets[task['task']] = producer._cover_target_identity(project, work, task)
    measured = producer.build_results(original['top'], cfg,
        producer.parse_sby_log(transcript, sby_stem=sby.stem, seed=cfg),
        str(log.relative_to(project)), str(sby.relative_to(project)))
    measured.update(mode='reachability', project=str(project.resolve()), mapping=plan, tasks=emitted['tasks'], original_inputs=inputs,
        sby_sha256=sha(sby), evidence_sha256=sha(log),
        proof_inputs=producer.proof_inputs(sby, work), witnesses=witnesses, target_identities=targets)
    put(work / 'results.json', measured)
    return work, measured















def test_emit_only_and_retained_cover_evidence_are_not_reexecuted(reach_case):
    project, ctx = reach_case
    emitted = producer.run_reachability(project, emit_only=True)
    work = Path(emitted['sby']).parent
    assert emitted['verdict'] == 'EMIT_ONLY'
    assert not (work / 'results.json').exists()
    assert not list(work.glob('formal_reachability_reach_*'))
    with pytest.raises(ValueError, match='retained output exists'):
        producer.run_reachability(project, emit_only=True)








def test_conditional_property_requires_native_assertion_mapping(reach_case):
    project, ctx = reach_case
    formal = project / 'phase2/stage1/formal'
    path = formal / 'formal_neutral.sv'
    put(path, path.read_text().replace('property p_output;', '`ifndef SPM_SAFETY_ONLY\nproperty p_output;').replace('assert property (p_output);', 'assert property (p_output);\n`endif'))
    result = json.loads((formal / 'results.json').read_text())
    with pytest.raises(ValueError, match='conditionally compiled'):
        producer.reachability_plan(project, result)








@pytest.mark.parametrize('task', ['reach_0', 'reach_1'])
def test_sby_actual_config_parser_preserves_each_task_script_and_global_files(reach_case, task):
    """SBY --dumpcfg is parser-only: it never creates a solver task directory."""
    import subprocess
    project, ctx = reach_case
    emitted = producer.run_reachability(project, emit_only=True)
    path = Path(emitted['sby'])
    result = subprocess.run(['sby', '--dumpcfg', str(path), task],
        cwd=path.parent, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    files = result.stdout.split('[files]', 1)[1].splitlines()
    assert {'neutral.v', 'formal_neutral.sv'} <= {line.strip() for line in files}
    assert 'read_verilog -sv -DSIMULATION neutral.v' in result.stdout
    assert not list(path.parent.glob('formal_reachability_reach_*'))


@pytest.mark.parametrize('change', ['assert_cell', 'wrong_source', 'duplicate_cover'])
def test_cover_target_is_native_type_count_and_source_not_hand_authored_cell_name(reach_case, change):
    project, ctx = reach_case
    work, measured = software_covers(project)
    path = work / 'formal_reachability_reach_0/model/cover_identity.json'
    body = json.loads(path.read_text())
    cells = body['modules']['formal_neutral']['cells']
    cell = next(iter(cells.values()))
    if change == 'assert_cell':cell['parameters']['FLAVOR'] = 'assert'
    if change == 'wrong_source':cell['attributes']['src'] = 'formal_neutral.sv:1.2-1.40'
    if change == 'duplicate_cover':cells['$second$cover'] = cell.copy()
    put(path, body)
    with pytest.raises(ValueError, match='native cover target'):
        producer.check_reachability(project)




def smt_safety_deck(text, *, engine="smtbmc yices"):
    # Retain the canonical script, assumptions, source reads and aliases. Only
    # the supplemental task/options/engine declarations are removed.
    text = '\n'.join(line for line in text.splitlines()
        if not (line.split() and line.split()[0] in ('bmc', 'bmc:'))) + '\n'
    return text.replace('safety: abc pdr', 'safety: ' + engine)


def software_smt_safety(project, *, engine="smtbmc yices"):
    """Authored existing --sby input and SOFTWARE transcript, never native proof."""
    formal = project / 'phase2/stage1/formal'
    path = formal / 'formal_neutral.sby'
    text = smt_safety_deck(path.read_text(), engine=engine)
    put(path, text)
    cfg = producer.parse_sby_config(text)
    assert set(cfg) == {'safety'} and cfg['safety'].engine == engine
    log = formal / 'formal_neutral.sby.log'
    put(log, 'SOFTWARE_ONLY_NOT_NATIVE_PROOF\nSBY 12:00:00 [formal_neutral_safety] DONE (PASS, rc=0)\n')
    original = json.loads((formal / 'results.json').read_text())
    measured = producer.build_results(original['top'], cfg,
        producer.parse_sby_log(log.read_text(), sby_stem=path.stem, seed=cfg),
        str(log.relative_to(project)), str(path.relative_to(project)))
    original.update(measured, sby_sha256=sha(path), evidence_sha256=sha(log),
                    proof_inputs=producer.proof_inputs(path, formal))
    put(formal / 'results.json', original)
    return path




def test_existing_authored_smt_safety_only_entry_admits_same_model_without_execution(reach_case, monkeypatch):
    project, _ = reach_case
    path = software_smt_safety(project)
    formal = path.parent
    before = path.read_bytes()
    monkeypatch.setattr(producer, '_run_sby', lambda *a, **k: pytest.fail('emit-only must not execute'))
    monkeypatch.setattr(producer, 'detect_engines', lambda *a, **k: pytest.fail('emit-only must not probe'))
    result = producer.run(project, sby=path, harness=formal / 'formal_neutral.sv',
        rtl=[project / 'phase2/stage1/rtl/neutral.v'], top='formal_neutral', container=None, emit_only=True)
    assert result['verdict'] == 'EMIT_ONLY', result
    assert path.read_bytes() == before
    assert result['all_proved'] is False
