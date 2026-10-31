"""Neutral sampled-wave controls for header-only functional repair.

Native simulation is real. The small task fixture does not claim canonical
coordinator/runner qualification; the normal consumer is exercised separately.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import rtl_repair_contract as rc
from test_prompt_structural_repair_contract import native
import test_prompt_structural_repair_contract as supporting

HEADER_SCHEMA = 'vibeic.prompt_header_completion.v1'
HEADER = 'module sample_pair(input wire clk, input wire a, input wire b, output reg p, output reg q);'
PARAM_HEADER = 'module sample_pair #(parameter RESERVED=1)(input wire clk, input wire a, input wire b, output reg p, output reg q);'
WAVE = '''Complete the following two sampled registers. All ports are one bit.
Each rising clock edge samples a into p and b into q.
After a rising edge the waveform rows are:
 a b | p q
 0 0 | 0 0
 0 1 | 0 1
 1 0 | 1 0
 1 1 | 1 1
Between rising edges both outputs retain their sampled values. Falling clock
edges do not sample data. The initial outputs before the first rising edge are unspecified.
'''
RIGHT = HEADER + '\nalways @(posedge clk) begin p <= a; q <= b; end\nendmodule\n'
WRONG = RIGHT.replace('posedge clk', 'negedge clk')
TB = '''`timescale 1ns/1ps
module vibeic_ai_challenge_tb;
reg clk=0; always #5 clk=~clk;
reg drive_a=0,drive_b=1;
wire a=drive_a,b=drive_b;
wire p,q; reg held_p,held_q; integer i;
sample_pair dut(clk,a,b,p,q);
task check(input bit ok); begin
 if(!ok) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1,"sample/hold mismatch"); end
end endtask
initial begin
 @(posedge clk);#1;check(p === a && q === b);held_p=p;held_q=q;
 for(i=0;i<16;i=i+1)begin
  @(negedge clk);#1;check(p === held_p && q === held_q);
  drive_a=i%2;drive_b=(i/2)%2;
  @(posedge clk);#1;check(p === a && q === b);held_p=p;held_q=q;
  #1;drive_a=~drive_a;drive_b=~drive_b;#1;check(p === held_p && q === held_q);
 end
 $display("VIBEIC_AI_CHALLENGE=PASS");$finish;
end
endmodule
'''


def make_task(tmp_path, native, *, header=HEADER, extra_source='', candidate=None):
    project = tmp_path / 'run/projects/neutral_ff'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    source = WRONG.replace(HEADER, header) if candidate is None else candidate
    (rtl/'pair_reg.sv').write_text(source)
    prompt = WAVE + '\n```verilog\n' + header + '\n' + extra_source + '```\n'
    (project/'input').mkdir()
    (project/'input/phase1_prompt.md').write_text(prompt)
    bio._stage_public_original('neutral_ff', prompt, {}, project)
    reports=project/'reports/orchestrator';reports.mkdir(parents=True)
    (reports/'phase2_one_shot.json').write_text(json.dumps({'steps':[
        {'name':'rtl_gen','status':'PASS','detail':'neutral unit fixture'}]}))
    got=bio.collect('rtllm','neutral_ff',project)
    routing={'nature':'completion','route':'SPEC_TO_RTL','source':'neutral_fixture','needs_ai_parse':True}
    task=bd._make_ai_review_task('neutral_ff',project,got,routing,0,project.parent.parent,'PROGRAM',
        program_phases={'phase3_verifying':{'ran':{'step4_functional_evidence':'NOT_APPLICABLE'}}})
    task['verification_execution']=native
    review=write_review(task)
    return task,review


def write_review(task, semantic_verdict="FAIL"):
    evidence=[{'excerpt':'Each rising clock edge samples a into p and b into q.',
               'supports':'This line uniquely specifies the sampled waveform and output values.'}]
    challenge=Path(task['challenge_path']);challenge.parent.mkdir(parents=True,exist_ok=True);challenge.write_text(TB)
    review={'schema':bd._AI_REVIEW_SCHEMA,'id':task['id'],'prompt_sha256':task['prompt_sha256'],
        'rtl_sha256':task['rtl_sha256'],'reviewer':{'kind':'AI','model':'neutral-wave-reviewer'},
        'blind':{'oracle_accessed':False},'routing':{'verdict':'AGREE','ai_nature':'completion'},
        'semantic_review':{'verdict':'FAIL','findings':['The sampled outputs do not match the rising-edge waveform.'],
            'rationale':'The public waveform fixes rising-edge sampling and inter-edge hold; the frozen candidate fails the independent simulation.',
            'prompt_evidence':evidence},
        'verification_test':{'schema':bd._CHALLENGE_SCHEMA,'path':str(challenge),'sha256':bd._sha256_text(TB),
            'top_module':'vibeic_ai_challenge_tb','rationale':'Drive every scalar input combination at both clock phases and compare both sampled registers after rising edges while checking inter-edge hold without asserting a power-up value.',
            'expected_behavior':'At each rising edge p captures a and q captures b, and both outputs hold between rising edges.',
            'prompt_evidence':evidence}}
    if semantic_verdict == 'PASS':
        review['semantic_review'].update(verdict='PASS',findings=[],rationale='The repaired candidate matches the complete sampled waveform and preserves the source header after normal gates.')
    target=Path(task['review_path']);target.parent.mkdir(parents=True,exist_ok=True)
    assert not target.exists()
    target.write_text(json.dumps(review))
    return review



def header_record(task, challenge, source, *, author=None):
    project=Path(task['project']);working=project/'phase2/stage1/rtl/pair_reg.sv';working.write_text(source)
    bundle_hash=bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    author=author or {'kind':'AI','model':'neutral-header-repair'}
    facts=rc.prompt_rtl_source_facts(Path(task['prompt_path']).read_text())
    # Unsupported-source controls still carry the original known header claim;
    # the consumer must derive facts independently and refuse it.
    binding=(rc.prompt_header_preservation(facts) if facts['kind']=='HEADER_ONLY' else
        {'schema':'vibeic.prompt_header_preservation.v1','prompt_sha256':task['prompt_sha256'],
         'module':'sample_pair','header':HEADER,'header_sha256':bd._sha256_text(HEADER)})
    contract={'schema':HEADER_SCHEMA,'prompt_sha256':task['prompt_sha256'],'parent_rtl_sha256':task['rtl_sha256'],
        'candidate_sha256':bundle_hash,'challenge_sha256':challenge['sha256'],'author':author,'oracle_accessed':False,
        'candidate_path':'pair_reg.sv','candidate_file_sha256':hashlib.sha256(working.read_bytes()).hexdigest(),
        'prompt_header_preservation':binding}
    record={'schema':bd._AI_REPAIR_RECORD_SCHEMA,'id':task['id'],'prompt_sha256':task['prompt_sha256'],
        'parent_rtl_sha256':task['rtl_sha256'],'repaired_rtl_sha256':bundle_hash,'challenge_sha256':challenge['sha256'],
        'author':author,'oracle_accessed':False,'rationale':'Restore the prompt-defined sampled waveform while preserving every significant token of the supplied module header.',
        'repair_contract':contract}
    path=bd._repair_record_path(project.parent.parent,task);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record))
    return path,record


def functional_result(task, source, challenge, native, label):
    project=Path(task['project']);(project/'phase2/stage1/rtl/pair_reg.sv').write_text(source)
    got=bio.collect('rtllm',task['id'],project,supplied_rtl=True)
    assert got['ok'],got
    candidate=bd._archive_candidate(task['id'],project,got,project.parent.parent,'AI_REPAIR',archive_key=label)
    return bd._run_verification_challenge(candidate,{**challenge,'execution_backend':native})


def test_header_only_functional_repair_preserves_header_replays_and_fresh_reviews(tmp_path,native):
    task,review=make_task(tmp_path,native)
    failed=bd._validate_ai_review(task)
    assert failed['status']=='REPAIR_REQUIRED' and failed['challenge_result']['status']=='FAIL'
    challenge=failed['verified_challenge']
    assert functional_result(task,RIGHT,challenge,native,'corrected-functional-proof')['status']=='PASS'
    path,record=header_record(task,challenge,RIGHT)
    provenance,reasons=bd._validate_repair_record(path,task,record['repaired_rtl_sha256'],challenge)
    assert reasons==[],reasons
    assert provenance is not None
    requirements=bd._repair_contract_requirements(task,failed)['repair_contract']
    assert requirements['schema']==HEADER_SCHEMA
    project=Path(task['project'])
    got=bio.collect('rtllm',task['id'],project,supplied_rtl=True,
        repair_contract=record['repair_contract'],require_repair_contract=True)
    assert got['ok'],got
    assert got['repair_contract']['header_preservation']['verdict']=='PASS'
    fresh=bd._make_ai_review_task(task['id'],project,got,task['program_routing'],0,project.parent.parent,'AI_REPAIR',
        verification_challenges=[challenge],repair_provenance=provenance,repair_parent_candidate=task['candidate_snapshot'])
    fresh['verification_execution']=native
    assert bd._validate_ai_review(fresh)['status']=='PENDING'
    new_review=copy.deepcopy(review);new_review.update(id=fresh['id'],rtl_sha256=fresh['rtl_sha256'])
    new_review['semantic_review'].update(verdict='PASS',findings=[],rationale='The repaired candidate matches the full sampled waveform and retains the exact source header.')
    new_challenge=Path(fresh['challenge_path']);new_challenge.parent.mkdir(parents=True);new_challenge.write_text(TB)
    new_review['verification_test']['path']=str(new_challenge)
    Path(fresh['review_path']).write_text(json.dumps(new_review))
    accepted=bd._validate_ai_review(fresh)
    assert accepted['status']=='ACCEPTED',accepted
    assert accepted['inherited_challenge_results'][0]['status']=='PASS'


@pytest.mark.parametrize('change',['width','direction','name','parameter_default','drop_header'])
def test_header_mutants_functionally_pass_but_record_and_consumer_refuse(tmp_path,native,change):
    header=PARAM_HEADER if change=='parameter_default' else HEADER
    task,_=make_task(tmp_path,native,header=header)
    parent=bd._validate_ai_review(task);assert parent['status']=='REPAIR_REQUIRED'
    source=RIGHT.replace(HEADER,header)
    if change=='width':source=source.replace('input wire a','input wire [1:0] a')
    elif change=='direction':source=source.replace('input wire a','inout wire a')
    elif change=='name':source=source.replace('input wire a','input wire renamed').replace('p <= a','p <= renamed')
    elif change=='parameter_default':source=source.replace('RESERVED=1','RESERVED=2')
    else:source=source.replace(HEADER,'module sample_pair(clk,a,b,p,q);\ninput wire clk,a,b;output reg p,q;')
    assert functional_result(task,source,parent['verified_challenge'],native,'header-mutant-functional-proof')['status']=='PASS'
    path,record=header_record(task,parent['verified_challenge'],source)
    provenance,reasons=bd._validate_repair_record(path,task,record['repaired_rtl_sha256'],parent['verified_challenge'])
    assert provenance is None and reasons
    got=bio.collect('rtllm',task['id'],Path(task['project']),supplied_rtl=True,
        repair_contract=record['repair_contract'],require_repair_contract=True)
    assert not got['ok'] and got['repair_contract']['verdict']=='REFUSED'


@pytest.mark.parametrize('field',['prompt_sha256','parent_rtl_sha256','candidate_sha256','challenge_sha256','author','candidate_file_sha256'])
def test_header_completion_keeps_every_immutable_binding(tmp_path,native,field):
    task,_=make_task(tmp_path,native)
    parent=bd._validate_ai_review(task)
    path,record=header_record(task,parent['verified_challenge'],RIGHT)
    record['repair_contract'][field]=({'kind':'AI','model':'different-author'} if field=='author' else '0'*64)
    path.write_text(json.dumps(record))
    accepted,reasons=bd._validate_repair_record(path,task,record['repaired_rtl_sha256'],parent['verified_challenge'])
    assert accepted is None and reasons


@pytest.mark.parametrize('source',['wire retained;\n','endmodule\n','module helper;\n'])
def test_header_completion_cannot_discard_supplied_body_or_multiple_modules(tmp_path,native,source):
    task,_=make_task(tmp_path,native,extra_source=source)
    parent=bd._validate_ai_review(task);assert parent['status']=='REPAIR_REQUIRED'
    path,record=header_record(task,parent['verified_challenge'],RIGHT)
    result,reasons=bd._validate_repair_record(path,task,record['repaired_rtl_sha256'],parent['verified_challenge'])
    assert result is None and any('header-only' in x for x in reasons)


@pytest.mark.parametrize('location',['review','provenance'])
def test_header_completion_cannot_replace_a_real_prior_native_structural_proof(tmp_path,native,monkeypatch,location):
    supporting.supplied_header_prompt(monkeypatch)
    task,review=supporting.task_and_review(tmp_path,native,nature='completion',bind_header=True)
    prior=bd._validate_ai_review(task)
    assert prior['status']=='REPAIR_REQUIRED' and prior['structural_result']['verdict']=='FAIL'
    project=Path(task['project']);working=project/'phase2/stage1/rtl/neutral_select.sv'
    working.write_text(supporting.existing.WRONG.replace('assign ns', '// cosmetic change keeps the violating architecture\nassign ns'))
    uncontracted=bio.collect('rtllm',task['id'],project,supplied_rtl=True)
    frozen=bd._archive_candidate(task['id'],project,uncontracted,project.parent.parent,'AI_REPAIR',archive_key='structural-downgrade-functional-proof')
    assert bd._run_verification_challenge(frozen,{**prior['verified_challenge'],'execution_backend':native})['status']=='PASS'
    # Reuse the same fully valid header schema; only active architecture proof
    # inheritance distinguishes this from an ordinary functional repair.
    author={'kind':'AI','model':'neutral-header-repair'}
    bundle=bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    contract={'schema':HEADER_SCHEMA,'prompt_sha256':task['prompt_sha256'],'parent_rtl_sha256':task['rtl_sha256'],
        'candidate_sha256':bundle,'challenge_sha256':prior['verified_challenge']['sha256'],'author':author,'oracle_accessed':False,
        'candidate_path':'neutral_select.sv','candidate_file_sha256':hashlib.sha256(working.read_bytes()).hexdigest(),
        'prompt_header_preservation':review['structural_verification']['prompt_header_preservation']}
    if location=='provenance':
        task['repair_provenance']={'repair_contract':{'schema':'vibeic.prompt_structural_completion.v1',
            'structural':review.pop('structural_verification')}}
        Path(task['review_path']).write_text(json.dumps(review))
    record={'schema':bd._AI_REPAIR_RECORD_SCHEMA,'id':task['id'],'prompt_sha256':task['prompt_sha256'],
        'parent_rtl_sha256':task['rtl_sha256'],'repaired_rtl_sha256':bundle,'challenge_sha256':contract['challenge_sha256'],
        'author':author,'oracle_accessed':False,'rationale':'Neutral downgrade control must retain the actually measured native structural obligation.',
        'repair_contract':contract}
    path=bd._repair_record_path(project.parent.parent,task);path.parent.mkdir(parents=True);path.write_text(json.dumps(record))
    got,reasons=bd._validate_repair_record(path,task,bundle,prior['verified_challenge'])
    assert got is None and any('active structural contract' in x for x in reasons)
    # Disabling just inherited-proof ownership admits this same functionally
    # passing, structurally violating payload: the negative is non-vacuous.
    with monkeypatch.context() as disabled:
        disabled.setattr(bd,'_inherited_structural_contract',lambda *args: None)
        unsafe,unsafe_reasons=bd._validate_repair_record(path,task,bundle,prior['verified_challenge'])
        assert unsafe is not None and unsafe_reasons==[]
    current_verdict={**prior,'verified_structural_contract':None} if location=='provenance' else prior
    assert bd._repair_contract_requirements(task,current_verdict)['repair_contract']['schema']=='vibeic.prompt_structural_completion.v1'


def test_header_proof_cannot_replace_immutable_functional_confirmation(tmp_path,native):
    task,review=make_task(tmp_path,native)
    parent=bd._validate_ai_review(task);assert parent['status']=='REPAIR_REQUIRED'
    still_wrong=WRONG.replace('p <= a','p <= ~a')
    path,record=header_record(task,parent['verified_challenge'],still_wrong)
    provenance,reasons=bd._validate_repair_record(path,task,record['repaired_rtl_sha256'],parent['verified_challenge'])
    assert not reasons
    project=Path(task['project'])
    got=bio.collect('rtllm',task['id'],project,supplied_rtl=True,
        repair_contract=record['repair_contract'],require_repair_contract=True)
    assert got['ok'] and got['repair_contract']['header_preservation']['verdict']=='PASS'
    fresh=bd._make_ai_review_task(task['id'],project,got,task['program_routing'],0,project.parent.parent,'AI_REPAIR',
        verification_challenges=[parent['verified_challenge']],repair_provenance=provenance,
        repair_parent_candidate=task['candidate_snapshot'])
    fresh['verification_execution']=native
    write_review(fresh,semantic_verdict='PASS')
    refused=bd._validate_ai_review(fresh)
    assert refused['status']=='REJECTED'
    assert refused['challenge_result']['status']=='FAIL'
    assert refused['inherited_challenge_results'][0]['status']=='FAIL'


def test_explicit_program_rebind_keeps_the_header_contract():
    original={'schema':HEADER_SCHEMA,'candidate_sha256':'old-bundle',
        'candidate_path':'pair_reg.sv','candidate_file_sha256':'old-file',
        'prompt_header_preservation':{'header':HEADER,'header_sha256':'immutable-header'}}
    rebound=bd._program_output_repair_contract(original,{'source':'neutral'},
        {'output_rtl_sha256':'new-bundle','output_rtl':{'pair_reg.sv':{'sha256':'new-file'}}})
    assert rebound['candidate_sha256']=='new-bundle'
    assert rebound['candidate_file_sha256']=='new-file'
    assert rebound['prompt_header_preservation']==original['prompt_header_preservation']
    assert original['candidate_file_sha256']=='old-file'
