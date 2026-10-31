"""Actual ordinary supplied-source owner and native IR; D01 isolated explicitly."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sys
import uuid
import os
import shutil
import pytest
import design_one_shot_runner as design
import vibe_ic_one_shot_runner as front
import benchmark_dispatch as dispatch

RTL = "module cell_keep(output logic [7:0] q); initial q=8'ha5; endmodule\nmodule unit(input on, iso, output [7:0] y); cell_keep u_state(y); endmodule\n"


def put(root, rel, body):
    path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(body if isinstance(body,str) else json.dumps(body))
    return path


def case(root, monkeypatch, *, unknown=False):
    # Exact original two-module D15 carrier, including its genuine empty
    # parameter and clock/reset populations. Not a serial benchmark fixture.
    assert hashlib.sha256(RTL.encode()).hexdigest() == '931ac7bddbfa37b3a7d3c98942387b068b389e295dad1664468facee015b5be9'
    put(root,'input/rtl/unit.sv',RTL)
    ports=[{'name':n,'direction':d,'width':w} for n,d,w in [('on','input',1),('iso','input',1),('y','output',8)]]
    put(root,'phase1/generated_docs/L9_INTEGRATION_SPEC.json',{'top_module':'unit','top_ports':ports,'parameters':[]})
    put(root,'input/spec.md','q initializes to A5. u_state.q connects to y. Interface is on,iso,y with no parameters.')
    facts=[{'constant':{'module':'cell_keep','port':'q','bits':['1','0','1','0','0','1','0','1']}},
           {'connection':{'module':'unit','cell':'u_state','type':'cell_keep','cell_port':'q','top_port':'y'}}]
    demands=[{'id':str(i),'requirement':text,'evidence':['input/spec.md:1']} for i,text in enumerate(['q initializes to A5','u_state.q connects to y','Complete declared interface'])]
    expects=[{**demands[i],'layer':'L2_FRS','field_path':'/requirements/'+str(i),'expected_tokens':['A5' if i==0 else 'q']} for i in range(2)]
    expects.append({**demands[2],'sub_expectations':[{'layer':'L9_INTEGRATION_SPEC','field_path':p,'expected_tokens':['interface']} for p in ('top_ports','parameters')]})
    if unknown:
        facts.append({'unrecognized_function':{'operator':'saturating_addition'}})
        demands.append({'id':'unsupported','requirement':'Additional saturating arithmetic','evidence':['input/spec.md:1']})
        expects.append({**demands[-1],'layer':'L2_FRS','field_path':'/requirements/2','expected_tokens':['saturating']})
    for i,fact in enumerate(facts):
        fact.update(id=demands[i]['id'],text=demands[i]['requirement'])
    put(root,'phase1/generated_docs/L2_FRS.json',{'requirements':facts})
    put(root,'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json',{'source_demands':demands,'expectations':expects,'responsibility_register':[]})
    def accepted_d01(project):
        path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
        return {'current':True,'evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'detail':'TEST_ONLY accepted D01 precondition isolated, NOT a native/current-row approval'}
    monkeypatch.setattr(design,'_serial_d01_state',accepted_d01)
    owner=asdict(design.step_reused_ip_consume(root,top_name='unit'))
    assert owner['status']=='PASS',owner
    argv=[sys.executable,str(Path(front.PROGRAMS_DIR)/'phase2_one_shot_runner.py'),str(root),'--entry-step','1','--exit-step','1']
    invocation={'invocation_id':uuid.uuid4().hex,'argv':argv,'project':str(root),
                'source':dispatch._runner_source_snapshot(argv)}
    report={'project':str(root),'verdict':'PASS','declared_window':{'entry_step':'1','exit_step':'1','dispatched_step_ids':['1']},
            'steps':[{'name':'rtl_gen','status':'WAIVED','extras':{}},owner]}
    design._write_phase2_report(root/'reports/orchestrator/phase2_one_shot.json',report,root,invocation_context=invocation)
    return root,json.loads((root/'reports/orchestrator/phase2_one_shot.json').read_text()),invocation


def consume(case):
    root,report,invocation=case
    return front._d09_bound_phase2_evidence(root,report,invocation,published_current=True)


def test_actual_supplied_owner_and_complete_native_population_pass(tmp_path,monkeypatch):
    owned=case(tmp_path,monkeypatch)
    status,evidence,detail=consume(owned)
    assert status=='PASS',detail
    assert evidence['owned_metrics']['mapped_items']==['0','1','2']
    assert evidence['owned_metrics']['native_witness']['sha256']
    assert not (tmp_path/'reports/flow109/default_rows/D09.json').exists()
    assert not (tmp_path/'reports/flow109/default_rows/D10.json').exists()
    if os.environ.get('D09_CAPTURE_ROOT'):
        shutil.copytree(tmp_path,Path(os.environ['D09_CAPTURE_ROOT'])/'positive',dirs_exist_ok=True)


@pytest.mark.parametrize('damage',['staged_source','foreign_owner','stale_owner','population','port','parameter','removed_witness','unsupported_claim','ambiguous_publishers','original_source','forged_native_witness','top_metrics'])
def test_each_absent_stale_or_unsupported_proof_refuses(tmp_path,monkeypatch,damage):
    owned=case(tmp_path,monkeypatch,unknown=damage=='unsupported_claim')
    root,report,invocation=owned
    if damage != 'unsupported_claim':
        status,_,detail=consume(owned)
        assert status == 'PASS', detail
    if damage=='original_source':(root/'input/rtl/unit.sv').write_text(RTL+'// changed source\n')
    elif damage=='top_metrics':report['d09_owned_metrics']={}
    elif damage=='forged_native_witness':
        path=root/'reports/audit/phase2/d09_supplied_elaboration.json'
        body=json.loads(path.read_text());body['modules']['cell_keep']['ports']['q']['bits']=['0']*8
        put(root,str(path.relative_to(root)),body)
        report['steps'][1]['extras']['d09_owned_metrics']['native_witness']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        report['d09_owned_metrics']=report['steps'][1]['extras']['d09_owned_metrics']
    elif damage=='staged_source':(root/'phase2/stage1/rtl/unit.sv').write_text(RTL+'// changed\n')
    elif damage=='foreign_owner':report['runner_binding']['project']=str(root.parent/'foreign')
    elif damage=='stale_owner':report['runner_binding']['invocation_id']='stale'
    elif damage=='population':
        path=root/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(path.read_text());body['source_demands'].append({'id':'unmapped','requirement':'new required function','evidence':['input/spec.md:1']});put(root,str(path.relative_to(root)),body)
    elif damage in ('port','parameter'):
        path=root/'phase1/generated_docs/L9_INTEGRATION_SPEC.json';body=json.loads(path.read_text())
        if damage=='port':body['top_ports'][0]['direction']='output'
        else:body['parameters']=[{'name':'new_parameter','default':'1'}]
        put(root,str(path.relative_to(root)),body)
    elif damage=='removed_witness':(root/'reports/audit/phase2/d09_supplied_elaboration.json').unlink(missing_ok=True)
    elif damage=='ambiguous_publishers':report['steps'].append(dict(report['steps'][1]))
    put(root,'reports/orchestrator/phase2_one_shot.json',report)
    status,_,detail=consume(owned)
    assert status in ('NOT_MEASURED','FAIL'),detail


def test_missing_real_d01_is_not_accepted(tmp_path,monkeypatch):
    owned=case(tmp_path,monkeypatch)
    monkeypatch.setattr(design,'_serial_d01_state',lambda p: (_ for _ in ()).throw(ValueError('current D01 publication/review absent')))
    status,_,detail=consume(owned)
    assert status=='NOT_MEASURED' and 'D01' in detail
