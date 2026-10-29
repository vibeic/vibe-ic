"""SOFTWARE source controls; optional native control requires explicit E authorization.

The default suite executes no solver. Native tests use only the exact two-property
constant-output input below, once E receives root's command authorization.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
import flow109
import flow109_metric_acceptance as metrics
import formal_property_run as producer
from test_flow109_d14_metric_binding import case as base_case, put, sha, reseal, rows


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
    measured = producer.build_results(original['top'], cfg,
        producer.parse_sby_log(transcript, sby_stem=sby.stem, seed=cfg),
        str(log.relative_to(project)), str(sby.relative_to(project)))
    measured.update(mode='reachability', project=str(project.resolve()), mapping=plan, tasks=emitted['tasks'], original_inputs=inputs,
        sby_sha256=sha(sby), evidence_sha256=sha(log),
        proof_inputs=producer.proof_inputs(sby, work), witnesses=witnesses)
    put(work / 'results.json', measured)
    return work, measured


def test_all_three_metrics_do_not_replace_missing_native_qualification(reach_case):
    project, ctx = reach_case
    original = (project / 'phase2/stage1/formal/results.json').read_bytes()
    software_covers(project)
    checked = producer.check_reachability(project)
    assert checked['status'] == 'PASS'
    assert set(checked['reached']) == {'p_delayed', 'p_output'}
    answer = metrics.accept_d14(project, ctx)
    assert answer['metric_status'] == 'PASS', answer
    assert answer['status'] == answer['qualification'] == 'NOT_MEASURED'
    assert answer['delivery_blocked'] is True
    assert all(r['status'] == 'PASS' for r in answer['obligations'])
    result = flow109._selected_step_result(project, ctx,
        {'step_id': 'D14', 'context_sha256': ctx['context_sha256'], 'component_status': 'PASS',
         'default_row_status': 'PASS', 'completed': True})
    assert result['flow109_acceptance'] == 'NOT_MEASURED' and result['completed'] is False
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert (project / 'phase2/stage1/formal/results.json').read_bytes() == original


def test_unreachable_or_incomplete_antecedent_never_counts_as_nonvacuous(reach_case):
    project, ctx = reach_case
    software_covers(project, statuses={'reach_0': 'FAIL'})
    checked = producer.check_reachability(project)
    assert checked['status'] == 'NOT_MEASURED'
    assert checked['pending'] == ['p_delayed']
    answer = metrics.accept_d14(project, ctx)
    assert answer['status'] == 'NOT_MEASURED', answer
    assert rows(answer)['vacuous_required_proofs']['status'] == 'NOT_MEASURED'
    assert rows(answer)['vacuous_required_proofs']['reason'] == 'D14_ANTECEDENT_NOT_PROVEN_REACHABLE'


@pytest.mark.parametrize('change', ['witness_property', 'witness_bytes', 'deck', 'assumption',
                                   'task_src', 'property_map', 'original_source', 'proof_contract', 'foreign_carrier'])
def test_cover_witness_must_match_exact_property_model_and_proof(reach_case, change):
    project, ctx = reach_case
    work, measured = software_covers(project)
    if change == 'witness_property':
        measured['witnesses']['reach_0'] = measured['witnesses']['reach_1']
    elif change == 'witness_bytes':
        put(project / next(iter(measured['witnesses']['reach_0'])), 'changed witness')
    elif change == 'deck':
        put(work / 'formal_reachability.sby', (work / 'formal_reachability.sby').read_text().replace('smtbmc yices', 'smtbmc z3'))
        measured['sby_sha256'] = sha(work / 'formal_reachability.sby')
    elif change == 'assumption':
        p = work / 'formal_neutral.sv';put(p, p.read_text().replace('endmodule', 'always @* assume(1\'b0);\nendmodule'))
    elif change == 'task_src':
        put(work / 'formal_reachability_reach_0/src/formal_neutral.sv', 'different actual read')
    elif change == 'property_map':
        measured['tasks'][0]['property'] = 'p_output'
    elif change == 'foreign_carrier':
        measured['project'] = str(project.parent / 'different_carrier')
    elif change == 'original_source':
        p = project / 'phase2/stage1/rtl/neutral.v';put(p, p.read_text()+'\n// different actual source\n')
    else:
        p = project / 'phase2/stage1/formal/property_contract.json'
        d = json.loads(p.read_text());d['covered_obligations'][0]['id'] = 'substitute';put(p, d)
    put(work / 'results.json', measured)
    with pytest.raises((ValueError, OSError)):
        producer.check_reachability(project)
    answer = metrics.accept_d14(project, ctx)
    assert answer['status'] == 'NOT_MEASURED', answer
    assert rows(answer)['vacuous_required_proofs']['status'] == 'NOT_MEASURED'


def test_well_formed_forged_owner_is_refused_by_actual_consumer_and_publisher(reach_case):
    project, ctx = reach_case
    path = project / 'phase2/stage1/formal/results.json'
    original = json.loads(path.read_text())
    original['program_owner_sha256']['formal_property_run.py'] = 'a' * 64
    put(path, original)
    software_covers(project)
    answer = metrics.accept_d14(project, ctx)
    assert answer['status'] == 'NOT_MEASURED', answer
    assert answer['reason'] == 'D14_ORIGINAL_OWNER_UNBOUND'
    assert all(r['status'] == 'NOT_MEASURED' for r in answer['obligations'])
    published = flow109._selected_step_result(project, ctx,
        {'step_id': 'D14', 'context_sha256': ctx['context_sha256'],
         'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True})
    assert published['default_row_status'] == 'NOT_MEASURED'
    assert published['completed'] is False


def test_genuine_retained_source_reuse_does_not_restamp_or_qualify_software(reach_case):
    project, ctx = reach_case
    name = os.environ.get('VIBEIC_RETAINED_FORMAL_SOURCE')
    if not name:
        pytest.skip('NOT_RUN: explicit readonly retained source checkout required')
    retained = Path(name)
    path = project / 'phase2/stage1/formal/results.json'
    original = json.loads(path.read_text())
    owners = {n: sha(retained / 'programs' / n) for n in producer.program_owner_identity()}
    assert owners != producer.program_owner_identity(), 'exercise genuine older source, not current-file equality'
    original['program_owner_sha256'] = owners
    put(path, original)
    result_ref = {'path': str(path.relative_to(project)), 'sha256': sha(path)}
    execution = project / 'input/retained-source/SOFTWARE_ONLY_EXECUTION.json'
    put(execution, {'scope': 'SOFTWARE_SOURCE_CONTROL_NOT_NATIVE_QUALIFICATION',
        'project': str(project), 'program_owner_sha256': owners, 'result': result_ref})
    reference = {'result': result_ref, 'source_root': str(retained),
                 'original_execution': {'path': str(execution.relative_to(project)), 'sha256': sha(execution)}}
    source = project / 'input/retained-source/source.json'
    put(source, {'purpose': 'D14.original_formal_execution', 'project': str(project), 'reference': reference})
    put(project / 'adopted/base_08/formal_execution.json',
        {'schema': 'vibeic.flow109.adopted-reference.v1',
         'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                      'source_reference': {'path': str(source.relative_to(project)), 'sha256': sha(source)}},
         'reference': reference})
    software_covers(project)
    before = path.read_bytes()
    answer = metrics.accept_d14(project, ctx)
    assert answer['metric_status'] == 'PASS', answer
    assert answer['status'] == answer['qualification'] == 'NOT_MEASURED'
    assert answer['evidence']['owner_provenance']['kind'] == 'adopted_original_producer'
    assert answer['evidence']['retained_owners'] == owners
    assert path.read_bytes() == before
    # Replacing a retained digest after adoption cannot borrow its authority.
    original['program_owner_sha256']['formal_property_run.py'] = 'a' * 64
    put(path, original)
    refused = metrics.accept_d14(project, ctx)
    assert refused['reason'] == 'D14_ORIGINAL_OWNER_UNBOUND', refused


@pytest.mark.parametrize('with_registry', [False, True])
def test_absent_or_unknown_purpose_qualification_blocks_actual_publisher(reach_case, with_registry):
    project, ctx = reach_case
    if with_registry:
        put(project / 'input/unknown-qualification.json', {'schema': 'vibeic.flow109.qualifications.v1', 'uses': []})
        ctx = flow109.execution_context(flow109.resolve_plan(ctx['features']), 'D14', 'D14',
            runtime_tool_uses=[{'use_id': 'unknown-purpose', 'tool_id': 'python3'}],
            qualification_registry='input/unknown-qualification.json')
    software_covers(project)
    answer = metrics.accept_d14(project, ctx)
    assert answer['metric_status'] == 'PASS', answer
    assert answer['status'] == answer['qualification'] == 'NOT_MEASURED'
    assert answer['delivery_blocked'] is True
    assert answer['admission']['status'] == 'NOT_MEASURED'
    published = flow109._selected_step_result(project, ctx,
        {'step_id': 'D14', 'context_sha256': ctx['context_sha256'],
         'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True})
    assert published['default_row_status'] == 'NOT_MEASURED' and published['completed'] is False
    assert published['qualification'] == 'NOT_MEASURED'



def test_emit_only_and_retained_cover_evidence_are_not_reexecuted(reach_case):
    project, ctx = reach_case
    emitted = producer.run_reachability(project, emit_only=True)
    work = Path(emitted['sby']).parent
    assert emitted['verdict'] == 'EMIT_ONLY'
    assert not (work / 'results.json').exists()
    assert not list(work.glob('formal_reachability_reach_*'))
    with pytest.raises(ValueError, match='retained output exists'):
        producer.run_reachability(project, emit_only=True)


@pytest.mark.skipif(os.environ.get('VIBEIC_AUTHORIZED_SMALL_REACHABILITY_CONTROL') != '1',
                    reason='NOT_RUN: requires root authorization and E native execution')
@pytest.mark.parametrize('reachable', [True, False])
def test_native_small_antecedent_control_for_E_only(reach_case, reachable):
    project, ctx = reach_case
    formal = project / 'phase2/stage1/formal'
    harness = formal / 'formal_neutral.sv'
    if not reachable:
        put(harness, harness.read_text().replace('ready |->', "(ready && 1'b0) |->"))
    result = producer.run(project, harness=harness,
        rtl=[project / 'phase2/stage1/rtl/neutral.v'], top='formal_neutral',
        container=None, timeout=30, mem_limit_kb=1048576)
    assert result['all_proved'] is True and result['unbounded_proved'] is True, result
    covered = producer.run_reachability(project, container=None, timeout=30, mem_limit_kb=1048576)
    assert covered['reachability_check']['status'] == ('PASS' if reachable else 'NOT_MEASURED'), covered
    accepted = metrics.accept_d14(project, ctx)
    put(project / 'native_formal_acceptance.json', accepted)
    put(project / 'native_cover_command_result.json', covered)
    assert accepted['metric_status'] == ('PASS' if reachable else 'NOT_MEASURED'), accepted
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['delivery_blocked'] is True


def test_binding_only_obligation_uses_existing_disposition_without_fake_cover(reach_case):
    project, ctx = reach_case
    formal = project / 'phase2/stage1/formal'
    rtl = project / 'phase2/stage1/rtl/neutral.v'
    put(rtl, rtl.read_text().replace('input clk,', 'input clk, input rst,'))
    put(formal / 'neutral.v', rtl.read_text())
    harness = formal / 'formal_neutral.sv'
    text = harness.read_text().replace('wire q;', "wire q;\n(* anyseq *) wire rst;\nwire rst_active = rst;\nreg rst_active_q = 0;\nreg f_past_valid = 0;\nalways @(posedge clk) begin rst_active_q <= rst_active; f_past_valid <= 1; end")
    text = text.replace('.clk(clk), .q(q)', '.clk(clk), .rst(rst), .q(q)')
    text = text.replace("(1'b1) |->", '(f_past_valid && rst_active_q) |->')
    put(harness, text)
    contract = json.loads((formal / 'property_contract.json').read_text())
    oid = 'L8.clock_and_reset_waveform.resets.0.name'
    contract['property_denominator'] = 3
    contract['unresolved_obligations'] = [{'id': oid, 'kind': 'binding',
        'binding': {'role': 'reset', 'port': 'rst'}, 'status': 'UNAUTHORED'}]
    put(formal / 'property_contract.json', contract)
    result = reseal(project)
    result.update(property_denominator=3, authored_property_count=2, covered_property_count=2,
        verdict='INCOMPLETE', proof_verdict='PASS', formal_completion='INCOMPLETE',
        unresolved_obligations=contract['unresolved_obligations'])
    put(formal / 'results.json', result)
    plan = producer.reachability_plan(project, result)
    binding = next(r for r in plan['obligations'] if r['id'] == oid)
    assert binding['kind'] == 'binding'
    assert binding['disposition']['status'] == 'DISCHARGED_BY_BINDING'
    assert 'properties' not in binding
    software_covers(project)
    answer = metrics.accept_d14(project, ctx)
    assert answer['metric_status'] == 'PASS', answer
    assert answer['status'] == answer['qualification'] == 'NOT_MEASURED'
    assert len(answer['evidence']['result']['unresolved_obligations']) == 1
    assert json.loads((formal / 'results.json').read_text())['property_denominator'] == 3


def test_structural_obligation_reuses_current_verified_program_closure(reach_case):
    project, ctx = reach_case
    formal = project / 'phase2/stage1/formal'
    rtl = project / 'phase2/stage1/rtl/neutral.v'
    path = formal / 'property_contract.json'
    contract = json.loads(path.read_text())
    oid = 'L8.clocks.0.edge'
    claim = {'rule': 'clock_edge', 'signal': 'clk', 'value': 'posedge'}
    contract.update(property_denominator=3,
        structural_subject={'top': 'neutral', 'rtl_files': [str(rtl)]},
        unresolved_obligations=[{'id': oid, 'kind': 'STRUCTURAL',
            'program_rule': {'kind': 'STRUCTURAL', 'claims': [claim]}}])
    put(path, contract)
    evidence = {'scope': 'SOFTWARE_ONLY_NOT_NATIVE_QUALIFICATION', 'top': 'neutral',
        'rtl_sha256': {str(rtl): sha(rtl)}, 'claims': [{**claim, 'verdict': 'PASS'}]}
    put(formal / producer.STRUCTURAL_EVIDENCE, evidence)
    receipt = {'program': 'formal_property_run', 'invocation_status': 'INVOKED_BY_PROGRAM',
        'binding': {'contract_sha256': sha(path), 'evidence_sha256': sha(formal / producer.STRUCTURAL_EVIDENCE),
                    'top': 'neutral', 'rtl_sha256': {str(rtl): sha(rtl)}},
        'dispositions': [{'id': oid, 'status': 'DISCHARGED_BY_PROGRAM',
                          'properties': [], 'claims': [{'claim': claim}]}]}
    put(formal / producer.PROGRAM_RECEIPT, receipt)
    result = reseal(project)
    result.update(property_denominator=3, authored_property_count=3, covered_property_count=3,
                  program_discharged_obligations=[oid])
    put(formal / 'results.json', result)
    plan = producer.reachability_plan(project, result)
    row = next(r for r in plan['obligations'] if r['id'] == oid)
    assert row['kind'] == 'structural' and 'properties' not in row
    software_covers(project)
    answer = metrics.accept_d14(project, ctx)
    assert answer['metric_status'] == 'PASS', answer
    assert answer['status'] == answer['qualification'] == 'NOT_MEASURED'


def test_conditional_property_requires_native_assertion_mapping(reach_case):
    project, ctx = reach_case
    formal = project / 'phase2/stage1/formal'
    path = formal / 'formal_neutral.sv'
    put(path, path.read_text().replace('property p_output;', '`ifndef SPM_SAFETY_ONLY\nproperty p_output;').replace('assert property (p_output);', 'assert property (p_output);\n`endif'))
    result = json.loads((formal / 'results.json').read_text())
    with pytest.raises(ValueError, match='conditionally compiled'):
        producer.reachability_plan(project, result)



def software_qualified_binding(project, ctx):
    """SOFTWARE admission control only; never a genuine platform qualification.

    Default metric/native-purpose fixtures never call this helper. Root alone
    may adopt actual E purpose measurements into production per-use receipts.
    """
    import flow109_admission as admission
    proof = project / 'input/qualification/D14/SOFTWARE_ONLY.json'
    put(proof, {'scope': 'SOFTWARE_ADMISSION_CONTROL_NOT_NATIVE_QUALIFICATION'})
    entries, runtime = [], []
    models = metrics.d14_model_sources()
    for use in ctx['resolved_row']['tool_uses']:
        tool = use['tool_id']
        config = project / ('input/qualification/D14/' + tool + '.json')
        put(config, {'purpose': 'D14.default.formal_and_reachability', 'tool_id': tool,
            'native_steps': metrics.D14_TOOL_STEPS[tool], 'engines': metrics.D14_ENGINES,
            'model_sources': models})
        binary = Path(shutil.which(use['executable_name'])).resolve()
        identity = {'use_id': use['use_id'], 'tool_id': tool,
            'version': 'SOFTWARE_CONTROL_NOT_NATIVE_QUALIFICATION', 'build_sha256': sha(binary),
            'executable': {'path': str(binary), 'sha256': sha(binary)},
            'config': {'path': str(config.relative_to(project)), 'sha256': sha(config)},
            'pdk': {'applicable': False, 'reason': 'bounded RTL formal source control'},
            'deck': {'applicable': False, 'reason': 'no physical rule deck'}, 'corner': 'RTL',
            'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps']}}
        entry = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                 'reference_evidence': [{'path': str(proof.relative_to(project)), 'sha256': sha(proof)}]}
        entries.append(entry)
        runtime.append({**identity, 'qualification_sha256': admission.canonical_sha(entry)})
    registry = project / 'input/qualification/D14/registry.json'
    put(registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': entries,
                   'scope': 'SOFTWARE_ADMISSION_CONTROL_NOT_NATIVE_QUALIFICATION'})
    return flow109.execution_context(flow109.resolve_plan(ctx['features']), 'D14', 'D14',
        runtime_tool_uses=runtime, qualification_registry=str(registry.relative_to(project)))


@pytest.mark.parametrize('stale', [False, True])
def test_explicit_software_qualified_binding_positive_and_stale_negative(reach_case, stale):
    project, ctx = reach_case
    assert set(use['tool_id'] for use in ctx['resolved_row']['tool_uses']) == set(metrics.D14_TOOL_STEPS)
    assert ctx['qualification_registry'] is None and not ctx['runtime_tool_uses']
    software_covers(project)
    qualified = software_qualified_binding(project, ctx)
    if stale:
        config = project / qualified['runtime_tool_uses'][0]['config']['path']
        put(config, {'purpose': 'stale qualification input'})
    answer = metrics.accept_d14(project, qualified)
    assert answer['metric_status'] == 'PASS', answer
    assert answer['qualification'] == ('NOT_MEASURED' if stale else 'PASS'), answer
    assert answer['status'] == ('NOT_MEASURED' if stale else 'PASS'), answer
    published = flow109._selected_step_result(project, qualified,
        {'step_id': 'D14', 'context_sha256': qualified['context_sha256'],
         'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True})
    assert published['completed'] is (not stale)
    assert published['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert published['delivery_accepted'] is False
    # Synthetic reference wording is explicit and never installed on a real carrier.
    assert json.loads((project / qualified['qualification_registry']).read_text())['scope'] == 'SOFTWARE_ADMISSION_CONTROL_NOT_NATIVE_QUALIFICATION'
