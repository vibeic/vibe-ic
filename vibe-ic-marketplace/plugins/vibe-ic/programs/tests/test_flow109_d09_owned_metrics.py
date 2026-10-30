"""D09's real producer/checker boundary; D01 isolated as a software precondition."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import sys

import pytest
import design_one_shot_runner as design
import serial_parallel_mul_synth as serial
import vibe_ic_one_shot_runner as front
import benchmark_dispatch as dispatch


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def populate(project):
    project.mkdir(exist_ok=True)
    docs = project / 'phase1/generated_docs'
    write(docs / 'L2_FRS.json', {'content':'serial-parallel multiplier; synchronous active-high reset', 'frs_sections':[{'content':'p = (x * y) mod 2^N; N denotes size'}]})
    write(docs / 'L9_INTEGRATION_SPEC.json', {'top_module':'unit', 'top_ports':[
        {'name':name,'direction':direction,'width':width}
        for name,direction,width in [('clk','input',1),('rst','input',1),('x','input',32),
                                     ('y','input',1),('p','output',1)]],
        'parameters':[{'name':'size','default':'32'}],
        'resets':[{'name':'rst','polarity':'active_high','sync':'synchronous'}]})
    body = project / 'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
    claims = ['The RTL computes p = (x * y) mod 2^size.',
              'The RTL uses synchronous active-high reset rst on rising clock clk.',
              'The RTL exposes exactly the L9 ports and parameters.']
    demands=[{'id':str(i),'requirement':claim,'evidence':['input/spec.md:1 — '+claim]} for i,claim in enumerate(claims)]
    targets=[{'layer':'L2_FRS','field_path':'frs_sections','expected_tokens':['p','x','y','mod','2','N']},
             {'layer':'L9_INTEGRATION_SPEC','field_path':'resets','expected_tokens':['rst','synchronous','active-high']},
             {'sub_expectations':[{'layer':'L9_INTEGRATION_SPEC','field_path':'top_ports','expected_tokens':['clk','rst','x','y','p']},
                                  {'layer':'L9_INTEGRATION_SPEC','field_path':'parameters','expected_tokens':['size','32']}]}]
    write(body, {'source_demands':demands, 'expectations':[dict(d,**target) for d,target in zip(demands,targets)],
                 'responsibility_register':[]})
    spec = project / 'input/spec.md'; spec.parent.mkdir(exist_ok=True); spec.write_text('\n'.join(claims))


def d01_precondition(root):
    body = root / 'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
    return {'current':True, 'evidence_sha256':hashlib.sha256(body.read_bytes()).hexdigest(),
            'detail':'TEST_ONLY actual upstream D01 isolated'}


def normal_author(project):
    result = design.step_rtl_gen(project, 'digital_arithmetic_primitive')
    assert result.status == 'PASS', result
    design._finalize_rtl_provenance()
    design._RTL_SESSION_OWNED=False
    design._RTL_SESSION_PROJECT=None
    return asdict(result)


@pytest.fixture
def owned(tmp_path, monkeypatch, request):
    project=tmp_path/'unit'
    populate(project)
    if getattr(request, 'param', None) == 'unmapped_rtl':
        path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
        body=json.loads(path.read_text())
        demand={'id':'new-rtl','requirement':'Saturating addition after multiplication is required.',
                'evidence':['input/spec.md:2 — saturating addition is required']}
        body['source_demands'].append(demand)
        body['expectations'].append(dict(demand,layer='L2_FRS',field_path='frs_sections',expected_tokens=['saturating addition']))
        write(path,body)
        path=project/'phase1/generated_docs/L2_FRS.json';doc=json.loads(path.read_text())
        doc['frs_sections'].append({'content':'saturating addition is required','evidence':'input/spec.md:2'});write(path,doc)
        with (project/'input/spec.md').open('a') as out:out.write('\nsaturating addition is required\n')
    monkeypatch.setattr(design, '_serial_d01_state', d01_precondition)
    row=normal_author(project)
    document={'project':str(project),'verdict':'PASS',
        'declared_window':{'entry_step':'1','exit_step':'1','dispatched_step_ids':['1']},
        'steps':[row]}
    out=project/'reports/orchestrator/phase2_one_shot.json'
    design._write_phase2_report(out,document,project)
    # Real dispatcher issues invocation/source/material and normal producer binds it.
    invocation={}
    def child(argv, *, env=None, **kwargs):
        context=json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        design._write_phase2_report(out, document, project, invocation_context=context)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(front.subprocess,'run',child)
    assert front._run_phase('D09 test child', Path(front.PROGRAMS_DIR)/'phase2_one_shot_runner.py',
        [str(project),'--entry-step','1','--exit-step','1'],env=dict(os.environ),invocation=invocation)==0
    yield project, json.loads(out.read_text()), invocation
    design._RTL_SESSION_OWNED=False
    design._RTL_SESSION_PROJECT=None


def consume(owned):
    project,report,invocation=owned
    return front._d09_bound_phase2_evidence(project,report,invocation,published_current=True)


def test_real_bound_author_two_owned_metrics_pass_without_native_credit(owned):
    project,report,_=owned
    status,evidence,detail=consume(owned)
    assert status=='PASS', detail
    assert len(evidence['owned_metrics']['source_demands'])==3
    assert len(evidence['owned_metrics']['mapped_items'])==3
    assert set(s['name'] for s in report['steps'])=={'rtl_gen'}
    assert not (project/'reports/flow109/default_rows/D10.json').exists()
    assert not (project/'reports/flow109/default_rows/D11.json').exists()
    assert not (project/'reports/flow109/default_rows/D12.json').exists()
    assert not (project/'reports/flow109/default_rows/D13.json').exists()


@pytest.mark.parametrize('change',['new_requirement','missing_mapping','port','parameter','source','material','invocation','producer','empty','duplicate'])
def test_missing_tampered_or_unmapped_inputs_refuse(owned,change):
    project,report,invocation=owned
    if change in ('new_requirement','empty','duplicate'):
        path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
        doc=json.loads(path.read_text())
        if change=='new_requirement':doc['source_demands'].append({'id':'owed','requirement':'The result must additionally invert its top bit.','evidence':['input/spec.md:2']})
        elif change=='empty':doc['source_demands']=[]
        else:doc['source_demands'].append(doc['source_demands'][0])
        write(path,doc)
    elif change=='missing_mapping':
        report['steps'][0]['extras']['d09_owned_metrics']['mapped_items'].pop()
    elif change in ('port','parameter'):
        path=project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json';doc=json.loads(path.read_text())
        if change=='port':doc['top_ports'][2]['direction']='output'
        else:doc['parameters'][0]['default']='16'
        write(path,doc)
    elif change=='source':report['runner_binding']['source']['producer']={'sha256':'0'*64}
    elif change=='material':(project/'input/spec.md').write_text('changed')
    elif change=='invocation':report['runner_binding']['invocation_id']='wrong'
    elif change=='producer':report['runner_binding']['producer']['sha256']='0'*64
    path=project/'reports/orchestrator/phase2_one_shot.json';write(path,report)
    status,_,detail=consume(owned)
    assert status in ('NOT_MEASURED','FAIL'), detail


def test_additional_unrecognized_requirement_is_not_dropped_after_fresh_publication(owned):
    project,_,_=owned
    path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
    body=json.loads(path.read_text());body['source_demands'].append({'id':'owed',
        'requirement':'The result must invert its top bit.','evidence':['input/spec.md:2']});write(path,body)
    answer=serial.d09_owned_metrics(project,'digital_arithmetic_primitive')
    assert len(answer['source_demands'])==4
    assert answer['missing_items']==['owed']
    assert answer['rtl_requirement_mapping']=='NOT_MEASURED'


@pytest.mark.parametrize('name',['rtl_lint_tool','reference_tb','cdc_rdc'])
def test_real_downstream_failure_is_still_failure(owned,name):
    project,report,_=owned
    report['steps'].append({'name':name,'status':'FAIL'})
    write(project/'reports/orchestrator/phase2_one_shot.json',report)
    status,_,detail=consume(owned)
    assert status=='FAIL'
    assert name in detail


def test_async_reset_does_not_satisfy_a_no_async_requirement(owned):
    project,_,_=owned
    write(project/'phase1/generated_docs/L2_FRS.json',
          {'content':'serial-parallel multiplier; asynchronous active-high reset'})
    path=project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    doc=json.loads(path.read_text());doc['resets'][0]['sync']='asynchronous';write(path,doc)
    spec,reason=serial.extract_serial_parallel_mul_spec(project,'digital_arithmetic_primitive')
    assert spec is not None, reason
    (project/'phase2/stage1/rtl/unit.v').write_text(serial.emit_rtl(spec))
    (project/'plugin_output/declaration.json').unlink()
    declaration,_=serial.planned_declaration(project,spec)
    write(project/'plugin_output/declaration.json',declaration)
    demand={'id':'clock','requirement':'A synchronous reset is required.', 'evidence':['input/spec.md:1']}
    write(project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json',
          {'source_demands':[demand], 'expectations':[dict(demand,layer='L9_INTEGRATION_SPEC',field_path='resets',
            expected_tokens=['rst','synchronous','active-high'])], 'responsibility_register':[]})
    answer=serial.d09_owned_metrics(project,'digital_arithmetic_primitive')
    assert answer['missing_items']==['clock']
    assert answer['rtl_requirement_mapping']=='NOT_MEASURED'


def test_later_owner_result_is_not_a_d09_prerequisite(owned):
    project,_,_=owned
    path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(path.read_text())
    demand={'id':'physical','requirement':'Die geometry remains an unresolved physical requirement.',
            'evidence':['input/spec.md:2']}
    body['source_demands'].append(demand)
    body['expectations'].append(dict(demand,layer='L19_CONSTRAINTS_PDK',field_path='constraints.unresolved',expected_tokens=['NOT_DETERMINED']))
    write(path,body);write(project/'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',{'constraints':{'unresolved':{'die':'NOT_DETERMINED'}}})
    result=serial.d09_owned_metrics(project,'digital_arithmetic_primitive')
    assert len(result['source_demands'])==4
    assert len(result['required_rtl_items'])==3
    assert len(result['mapped_items'])==3
    assert result['rtl_requirement_mapping']=='PASS'
    physical=next(r for r in result['responsibility_register'] if r['id']=='physical')
    assert physical['mapping_status']=='DOWNSTREAM_RESPONSIBILITY_PRESERVED'
    assert physical['verification_status']=='NOT_MEASURED'
    assert not (project/'reports/flow109/default_rows/D31.json').exists()


@pytest.mark.parametrize('owned',['unmapped_rtl'],indirect=True)
def test_fresh_bound_producer_cannot_promote_an_unmapped_rtl_requirement(owned):
    project,report,_=owned
    assert report['d09_owned_metrics']['missing_items']==['new-rtl']
    status,_,detail=consume(owned)
    assert status=='NOT_MEASURED'
    assert detail=='D09_REQUIRED_MAPPING_MISSING: new-rtl'
    assert not (project/'reports/flow109/default_rows/D09.json').exists()


def test_registry_required_population_is_the_explicit_owned_trace(owned):
    project,report,_=owned
    registry=json.loads((Path(serial.__file__).resolve().parents[1]/'flow/flow109.json').read_text())
    row=next(row for row in registry['rows'] if row['id']=='D09')
    expected=next(ob for ob in row['obligations'] if ob['metric']=='rtl_requirement_mapping')['expectation']['required_set_ref']
    assert expected=='reports/orchestrator/phase2_one_shot.json#/d09_owned_metrics/required_rtl_items'
    assert report['d09_owned_metrics']['required_rtl_items']==['0','1','2']
    assert len(report['d09_owned_metrics']['responsibility_register'])==3
