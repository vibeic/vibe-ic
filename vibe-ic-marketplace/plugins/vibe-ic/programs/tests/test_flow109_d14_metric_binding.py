"""SOFTWARE transcript fixtures, not native proof or SPM acceptance.

Exercise the actual producer parsers, source-read admission, proof-chain audit,
metric consumer and normal completion publisher without invoking any solver.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import _chip_synth_read as chip
import flow109
import flow109_metric_acceptance as metrics
import formal_property_run as producer


def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context():
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
        if p['name'] == 'Small digital IC without DFT'))
    return flow109.execution_context(flow109.resolve_plan(features), 'D14', 'D14')


def reseal(project, *, mode='prove', status='PASS'):
    formal = project / 'phase2/stage1/formal'
    sby = formal / 'formal_neutral.sby'
    text = producer.emit_sby(['neutral.v'], 'formal_neutral.sv', 'formal_neutral',
                            dut_simdef=chip.chip_sim_define(chip.chip_rtl_files(project / 'phase2/stage1/rtl'), [])[0], harness_top='formal_neutral')
    # Keep the canonical script; task options are authored independently.
    text = text.replace('safety: mode prove', 'safety: mode ' + mode)
    put(sby, text)
    cfg = producer.parse_sby_config(text)
    log = formal / 'formal_neutral.sby.log'
    put(log, 'SOFTWARE_ONLY_NOT_NATIVE_PROOF\n' + ''.join(
        f'SBY 12:00:00 [formal_neutral_{task}] DONE ({status}, rc={0 if status == "PASS" else 1})\n'
        for task in cfg))
    for task in cfg:
        for name in ('neutral.v', 'formal_neutral.sv'):
            dest = formal / f'{sby.stem}_{task}/src/{name}'
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(formal / name, dest)
    result = producer.build_results('formal_neutral', cfg,
        producer.parse_sby_log(log.read_text(), sby_stem=sby.stem, seed=cfg),
        str(log.relative_to(project)), str(sby.relative_to(project)))
    result.update(proof_inputs=producer.proof_inputs(sby, formal),
        chip_read=chip.current_chip_read(project, 'neutral'),
        sby_sha256=sha(sby), evidence_sha256=sha(log),
        program_owner_sha256=producer.program_owner_identity(),
        property_denominator=1, authored_property_count=1, covered_property_count=1,
        unresolved_obligations=[], formal_completion='PASS',
        property_contract=str((formal / 'property_contract.json').relative_to(project)),
        property_contract_sha256=sha(formal / 'property_contract.json'))
    put(formal / 'results.json', result)
    return result


@pytest.fixture
def case(tmp_path):
    project = tmp_path / 'SOFTWARE_ONLY'
    rtl = project / 'phase2/stage1/rtl/neutral.v'
    put(rtl, 'module neutral(input clk, output wire q); assign q = 1\'b0; endmodule\n')
    formal = project / 'phase2/stage1/formal'
    put(formal / 'neutral.v', rtl.read_text())
    put(formal / 'formal_neutral.sv', '''module formal_neutral(input clk);
wire q;
neutral dut(.clk(clk), .q(q));
always @(*) assert(q == 0);
endmodule
''')
    put(formal / 'property_contract.json', {'program': 'formal_harness_gen',
        'chip_read_top': 'neutral', 'property_denominator': 1,
        'covered_obligations': [{'id': 'RTL.output', 'property': 'p_output', 'author': 'formal_harness_gen'}],
        'unresolved_obligations': []})
    source = project / 'input/formal-partitions.json'
    put(source, {'scope': 'SOFTWARE_ONLY_NOT_NATIVE_QUALIFICATION',
                 'required_items': [{'task': 'safety'}]})
    put(project / 'requirements/base_08/proof_partition_coverage.json',
        {'schema': metrics.AUTHORITY_SCHEMA,
         'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                      'source_reference': {'path': str(source.relative_to(project)), 'sha256': sha(source)}},
         'required_items': [{'task': 'safety'}]})
    reseal(project)
    return project, context()


def rows(answer):
    return {r['id'].split('.')[-1]: r for r in answer['obligations']}


def test_actual_consumer_positive_keeps_vacuity_and_whole_row_unmeasured(case):
    project, ctx = case
    answer = metrics.accept_d14(project, ctx)
    measured = rows(answer)
    assert measured['unproved_required_properties']['status'] == 'PASS', answer
    assert measured['proof_partition_coverage']['status'] == 'PASS', answer
    assert measured['vacuous_required_proofs']['status'] == 'NOT_MEASURED'
    assert measured['vacuous_required_proofs']['reason'] == 'D14_PROPERTY_ANTECEDENT_REACHABILITY_MAPPING_ABSENT'
    assert 'measurement' not in measured['vacuous_required_proofs']
    assert answer['status'] == 'NOT_MEASURED'
    assert answer['delivery_blocked'] is True


@pytest.mark.parametrize('change', ['rtl', 'deck', 'log', 'task_src', 'contract', 'owner',
                                    'result', 'assumption', 'authority', 'incomplete', 'bmc'])
def test_actual_consumer_rejects_changed_or_incomplete_evidence(case, change):
    project, ctx = case
    formal = project / 'phase2/stage1/formal'
    if change in ('rtl', 'deck', 'log', 'task_src', 'contract', 'assumption'):
        relative = {'rtl': 'phase2/stage1/rtl/neutral.v',
            'deck': 'phase2/stage1/formal/formal_neutral.sby',
            'log': 'phase2/stage1/formal/formal_neutral.sby.log',
            'task_src': 'phase2/stage1/formal/formal_neutral_safety/src/neutral.v',
            'contract': 'phase2/stage1/formal/property_contract.json',
            'assumption': 'phase2/stage1/formal/formal_neutral.sv'}[change]
        path = project / relative
        path.write_text(path.read_text() + '\n// changed actual input\n')
    elif change in ('owner', 'result', 'incomplete'):
        path = formal / 'results.json'; result = json.loads(path.read_text())
        if change == 'owner': result['program_owner_sha256']['formal_property_run.py'] = 'missing-owner'
        if change == 'result': result['properties'][0]['engine'] = 'invented engine'
        if change == 'incomplete':
            result.update(verdict='INCOMPLETE', unresolved_obligations=[{'id': 'missing'}])
        put(path, result)
    elif change == 'authority':
        path = project / 'requirements/base_08/proof_partition_coverage.json'
        body = json.loads(path.read_text());body['required_items'] = [{'task': 'foreign'}];put(path, body)
    else:
        reseal(project, mode='bmc')
    answer = metrics.accept_d14(project, ctx)
    assert answer['status'] == 'NOT_MEASURED', answer
    assert rows(answer)['unproved_required_properties']['status'] == 'NOT_MEASURED', answer
    assert rows(answer)['proof_partition_coverage']['status'] == 'NOT_MEASURED', answer


def test_native_counterexample_transcript_is_not_hidden_by_missing_authority(case):
    project, ctx = case
    reseal(project, status='FAIL')
    (project / 'requirements/base_08/proof_partition_coverage.json').unlink()
    answer = metrics.accept_d14(project, ctx)
    assert answer['status'] == 'FAIL', answer
    assert rows(answer)['unproved_required_properties']['status'] == 'FAIL'
    assert rows(answer)['vacuous_required_proofs']['status'] == 'NOT_MEASURED'


def test_normal_completion_publisher_blocks_component_pass(case):
    project, ctx = case
    result = flow109._selected_step_result(project, ctx,
        {'step_id': 'D14', 'context_sha256': ctx['context_sha256'], 'component_status': 'PASS',
         'default_row_status': 'PASS', 'completed': True})
    assert result['flow109_acceptance'] == 'NOT_MEASURED', result
    assert result['completed'] is False
    assert result['delivery_accepted'] is False
    published = json.loads((project / 'reports/flow109/default_rows/D14.json').read_text())
    assert published == result
    assert rows(published['metric_acceptance'])['vacuous_required_proofs']['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('change', ['define', 'denominator', 'vacuity_zero', 'missing', 'refutation'])
def test_resealed_model_changes_and_self_reported_zeros_do_not_grant_credit(case, change):
    project, ctx = case
    formal = project / 'phase2/stage1/formal'
    path = formal / 'results.json'
    result = json.loads(path.read_text())
    if change == 'missing':
        path.unlink()
    elif change == 'define':
        sby = formal / 'formal_neutral.sby'
        put(sby, sby.read_text().replace('-DSIMULATION', '-DOTHER'))
        result['sby_sha256'] = sha(sby)
        put(path, result)
    else:
        if change == 'denominator': result['property_denominator'] = 0
        if change == 'vacuity_zero': result['vacuous_required_proofs'] = 0
        if change == 'refutation': result['structural_refutations'] = [{'id': 'invented'}]
        put(path, result)
    answer = metrics.accept_d14(project, ctx)
    assert answer['status'] == 'NOT_MEASURED', answer
    assert rows(answer)['vacuous_required_proofs']['status'] == 'NOT_MEASURED'
    if change != 'vacuity_zero':
        assert all(r['status'] == 'NOT_MEASURED' for r in answer['obligations']), answer
