"""Explicit SOFTWARE State/launch/authority controls, never native qualification.

The existing Yosys parser consumes the small netlists. SDK resynthesis and D23
execution are NOT performed or claimed by these synthetic upstream fixtures.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import librelane_contract as contract
import design_one_shot_runner as design
import vibe_ic_one_shot_runner as public
from test_flow109_selection import profile, _public_d09_entry


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2)+'\n')


def ref(project, rel, content):
    path=project/rel;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(content)
    return {'path':rel,'sha256':metrics._sha(path.read_bytes())}


def context():
    features=profile();features.update(physical=True,requires_scan=True,requires_dft=True)
    return flow109.execution_context(flow109.resolve_plan(features),'D24','D24')


MAPPED='module unit(input d,ck,output q); DFF ff0(.D(d),.CK(ck),.Q(q)); endmodule\n'
REPLACED=MAPPED.replace('DFF ', 'SFF ')
OPTIMIZED=REPLACED.replace('endmodule', 'BUF buffer0(.A(d),.Y(unused)); endmodule')


def software_case(project, monkeypatch, output=OPTIMIZED):
    current=context();attempt=flow109._new_attempt(project,current)
    source=ref(project,'input/mapped.v',MAPPED)
    replaced=ref(project,'input/replaced.v',REPLACED)
    lib=ref(project,'input/SOFTWARE.lib','library(SOFTWARE_UNIT_ONLY) {}\n')
    listing=ref(project,'input/SOFTWARE_d23.json',json.dumps({'pdk_sha256':{
        str((project/lib['path']).resolve()):lib['sha256']}}))
    upstream={'D23_result':ref(project,'input/SOFTWARE_d23_result.json','{}'),
        'scan_cell_list':listing,'mapped':source,'replaced':replaced,
        'cells':[{'instance':'ff0','cell':'SFF'}],'top':'unit'}
    monkeypatch.setattr(flow109,'dft_source_intent',lambda *a:{'requires_scan':True,'source_binding':{'SOFTWARE':True}})
    original_binding=flow109.d23_scan_replacement_binding
    monkeypatch.setattr(flow109,'d23_scan_replacement_binding',lambda *a:copy.deepcopy(upstream))
    host={'cid':'c'*64,'image':'SOFTWARE_IMAGE_ONLY','container_inspect':{
        'Id':'c'*64,'Image':'SOFTWARE_IMAGE_ID','Config':{'Hostname':'c'*12},
        'State':{'Running':True,'Paused':False,'Dead':False}}}
    launch=ref(project,'input/SOFTWARE_launch.json',json.dumps(host))
    authority={'cid':host['cid'],'image':host['image'],'image_id':'SOFTWARE_IMAGE_ID',
        'attestation_path':str(project/launch['path']),'attestation_sha256':launch['sha256']}
    monkeypatch.setattr(contract,'local_image_attestation',lambda *a:copy.deepcopy(authority))
    folder=attempt/'resynthesis';rel=lambda name:str((folder/name).relative_to(project))
    cfg=ref(project,rel('config.json'),json.dumps({'meta':{'step':'Yosys.Resynthesis'},
        'DESIGN_NAME':'unit','SYNTH_ELABORATE_ONLY':False,'CELL_LIBS':{'nom':[str((project/lib['path']).resolve())]}}))
    netlist=ref(project,rel('unit.v'),output)
    state_in=ref(project,rel('state_in.json'),json.dumps({'nl':str((project/replaced['path']).resolve())}))
    state=ref(project,rel('state_out.json'),json.dumps({'nl':str((project/netlist['path']).resolve())}))
    log=ref(project,rel('resynthesis.log'),'SOFTWARE SDK OUTPUT STAND-IN, NOT NATIVE EXECUTION\n')
    config_input=ref(project,'input/flow109/D24/resynthesis.json','{"DESIGN_NAME":"unit","PDK":"SOFTWARE"}')
    document={'schema':'vibeic.flow109.d24-component.v1','producer':'D24','operation':'Yosys.Resynthesis',
        'source':replaced,'scan_cell_list':listing,'config_input':config_input,
        'consumed_config_files':contract.config_file_hashes(json.loads((project/cfg['path']).read_text()),[]),
        'config':cfg,'state_in':state_in,'state':state,'netlist':netlist,'log':log,'returncode':0,
        'launch':authority,'native_module':metrics.d24_native_module(),
        'yosys_sha256':metrics._sha(Path(shutil.which('yosys')).read_bytes()),
        'producer_source_sha256':metrics._sha(Path(design.__file__).read_bytes())}
    component=ref(project,str((attempt/'d24_component.json').relative_to(project)),json.dumps(document))
    adopted={'artifact_id':'D24_POST_SCAN_NETLIST','path':'phase2/stage2/synth/post_dft_netlist.v',
             'sha256':netlist['sha256']}
    # Root authority is explicitly a SOFTWARE fixture here, never native adoption.
    source_ref=ref(project,'input/SOFTWARE_adoption.json',json.dumps({'reference':adopted,'native_component':component,'launch':authority}))
    write(project/'adopted/base_15/adopted_post_dft_netlist.json',{'schema':'vibeic.flow109.adopted-reference.v1',
        'approval':{'status':'APPROVED','authority':'requirements_owner','source_reference':source_ref},
        'reference':adopted,'native_component':component})
    return current,{'post_dft_component':component},document,upstream,original_binding


def qualified_software(project,current,module):
    runtime=[];entries=[]
    config=ref(project,'input/qualification/D24/SOFTWARE_config.json',json.dumps({
        'purpose':'D24.default.post_dft_resynthesis','model_sources':metrics.d24_model_sources(),'native_module':module}))
    evidence=ref(project,'input/qualification/D24/SOFTWARE_evidence.json','{"scope":"SOFTWARE_CONTROL_NOT_PLATFORM_QUALIFICATION"}')
    for use in current['resolved_row']['tool_uses']:
        binary=Path(shutil.which(use['executable_name'])).resolve();digest=metrics._sha(binary.read_bytes())
        identity={'use_id':use['use_id'],'tool_id':use['tool_id'],'version':'SOFTWARE_ONLY','executable':{'path':str(binary),'sha256':digest},
            'build_sha256':digest,'config':config,'pdk':{'applicable':False,'reason':'SOFTWARE control'},
            'deck':{'applicable':False,'reason':'SOFTWARE control'},'corner':'SOFTWARE_ONLY',
            'semantics':{'purpose':use['purpose'],'native_steps':use['native_steps']}}
        entry={'use_id':use['use_id'],'status':'QUALIFIED','identity':identity,'reference_evidence':[evidence]}
        entries.append(entry);runtime.append({**identity,'qualification_sha256':admission.canonical_sha(entry)})
    registry='input/qualification/D24/SOFTWARE_registry.json'
    write(project/registry,{'schema':'vibeic.flow109.qualifications.v1','uses':entries})
    return flow109.execution_context(flow109.resolve_plan(current['features']),'D24','D24',runtime_tool_uses=runtime,qualification_registry=registry)


@pytest.mark.parametrize('damage',['none','missing_scan','replaced_scan','missing_adoption','forged_adoption','changed_log',
                                  'wrong_state','missing_qualification','stale_model','missing_original_d23','changed_library','foreign_component_adoption','elaboration_only'])
def test_actual_d24_consumer_and_independent_adoption(tmp_path,monkeypatch,damage):
    output=OPTIMIZED.replace('SFF ff0(.D(d),.CK(ck),.Q(q));','') if damage=='missing_scan' else OPTIMIZED.replace('SFF ','DFF ') if damage=='replaced_scan' else OPTIMIZED
    current,component,document,upstream,original=software_case(tmp_path,monkeypatch,output)
    current=qualified_software(tmp_path,current,document['native_module']) if damage!='missing_qualification' else current
    adopted=tmp_path/'adopted/base_15/adopted_post_dft_netlist.json'
    if damage=='missing_adoption':adopted.unlink()
    elif damage=='forged_adoption':
        body=json.loads(adopted.read_text());body['reference']['sha256']='a'*64;write(adopted,body)
    elif damage=='foreign_component_adoption':
        body=json.loads(adopted.read_text());owner_input=tmp_path/body['approval']['source_reference']['path']
        payload=json.loads(owner_input.read_text())
        payload['native_component']={**payload['native_component'],'sha256':'a'*64}
        write(owner_input,payload);body['native_component']=payload['native_component']
        body['approval']['source_reference']['sha256']=metrics._sha(owner_input.read_bytes());write(adopted,body)
    elif damage=='elaboration_only':
        cfg=tmp_path/document['config']['path'];data=json.loads(cfg.read_text())
        data['SYNTH_ELABORATE_ONLY']=True;write(cfg,data)
        document['config']['sha256']=metrics._sha(cfg.read_bytes())
        write(tmp_path/component['post_dft_component']['path'],document)
        component['post_dft_component']['sha256']=metrics._sha((tmp_path/component['post_dft_component']['path']).read_bytes())
    elif damage=='changed_log':(tmp_path/document['log']['path']).write_text('changed')
    elif damage=='wrong_state':
        body=json.loads((tmp_path/document['state_in']['path']).read_text());body['nl']=str(tmp_path/'input/foreign.v')
        # Intentionally coherent output hashes, to reach the actual State identity check.
        write(tmp_path/document['state_in']['path'],body)
        document['state_in']['sha256']=metrics._sha((tmp_path/document['state_in']['path']).read_bytes())
        write(tmp_path/component['post_dft_component']['path'],document)
        component['post_dft_component']['sha256']=metrics._sha((tmp_path/component['post_dft_component']['path']).read_bytes())
    elif damage=='missing_original_d23':monkeypatch.setattr(flow109,'d23_scan_replacement_binding',original)
    elif damage=='changed_library':(tmp_path/'input/SOFTWARE.lib').write_text('changed library')
    elif damage=='stale_model':
        use=current['runtime_tool_uses'][0];cfg=tmp_path/use['config']['path'];data=json.loads(cfg.read_text())
        data['model_sources']['flow109_metric_acceptance.py:accept_d24']='a'*64;write(cfg,data)
        registry=json.loads((tmp_path/current['qualification_registry']).read_text())
        for use,entry in zip(current['runtime_tool_uses'],registry['uses']):
            use['config']['sha256']=metrics._sha(cfg.read_bytes());entry['identity']['config']=copy.deepcopy(use['config'])
            use['qualification_sha256']=admission.canonical_sha(entry)
        write(tmp_path/current['qualification_registry'],registry)
        current=flow109.execution_context(flow109.resolve_plan(current['features']),'D24','D24',runtime_tool_uses=current['runtime_tool_uses'],qualification_registry=current['qualification_registry'])
        assert admission.require_admission(tmp_path,current)['status']=='PASS'
    result=metrics.accept_d24(tmp_path,current,component)
    expected='PASS' if damage=='none' else 'FAIL' if damage in ('missing_scan','replaced_scan') else 'NOT_MEASURED'
    assert result['status']==expected,result
    assert result['delivery_blocked'] is (damage!='none')
    if damage=='none':
        assert metrics._sha(REPLACED.encode())!=document['netlist']['sha256']
        assert result['obligations'][0]['measurement']['value']==0
    if damage=='stale_model':assert result['reason']=='D24_MODEL_QUALIFICATION_STALE',result
    if damage in ('missing_scan','replaced_scan'):assert result['obligations'][0]['measurement']['value']>0


@pytest.mark.parametrize('physical',[True,False])
def test_selected_public_d24_reuses_component_and_normal_row_writer(tmp_path,monkeypatch,physical):
    current,component,document,_,_=software_case(tmp_path,monkeypatch)
    if not physical:
        current=flow109.execution_context(flow109.resolve_plan(profile('Mapped soft-IP with prestitched scan')),'D24','D24')
    current=qualified_software(tmp_path,current,document['native_module'])
    path=tmp_path/'context.json';write(path,current)
    monkeypatch.setenv(flow109.CONTEXT_ENV,str(path))
    attempt=flow109._new_attempt(tmp_path,current);monkeypatch.setenv(flow109.ATTEMPT_ENV,str(attempt))
    def forbidden(*a,**k):pytest.fail('selected reader must not rerun resynthesis or legacy opt_clean')
    monkeypatch.setattr(design,'_d24_resynthesis',forbidden)
    monkeypatch.setattr(design,'_step_post_dft_optimization',forbidden)
    result=public._complete_step12_post_dft(tmp_path,'SOFTWARE_ONLY')
    assert result['verdict']=='PASS',result
    finished=public._finish_selected_native_owner(tmp_path,'12',result)
    assert finished['default_row_status']=='PASS',finished
    assert finished['whole_flow_acceptance']=='NOT_MEASURED'
    assert (tmp_path/'phase2/stage2/synth/post_dft_netlist.v').read_text()==OPTIMIZED
    assert json.loads((attempt/'result.json').read_text())['components'][0]['metric_acceptance']['status']=='PASS'


@pytest.mark.parametrize('missing_qualification',[False,True])
def test_full_public_d24_frontdoor_bounded_reader(tmp_path,monkeypatch,missing_qualification):
    current,component,document,_,_=software_case(tmp_path,monkeypatch)
    if not missing_qualification:
        current=qualified_software(tmp_path,current,document['native_module'])
    runner=_public_d09_entry(tmp_path,monkeypatch)
    write(tmp_path/'manifest.json',{k:current[k]for k in ('features','runtime_tool_uses','qualification_registry')})
    argv=list(sys.argv)
    for flag in ('--entry-step','--exit-step'):argv[argv.index(flag)+1]='D24'
    monkeypatch.setattr(sys,'argv',argv)
    def forbidden(*a,**k):pytest.fail('public D24 reader must not launch phases/resynthesis/legacy opt_clean')
    monkeypatch.setattr(design,'_d24_resynthesis',forbidden)
    monkeypatch.setattr(design,'_step_post_dft_optimization',forbidden)
    monkeypatch.setattr(runner,'_run_phase',forbidden)
    rc=runner._main()
    assert rc==(2 if missing_qualification else 0)
    attempt=Path(os.environ[flow109.ATTEMPT_ENV]);result=json.loads((attempt/'result.json').read_text())
    assert result['default_row_status']==('NOT_MEASURED' if missing_qualification else 'PASS'),result
    assert result['components'][0]['completed'] is (not missing_qualification)
    assert result['whole_flow_acceptance']=='NOT_MEASURED'
    summary=json.loads((tmp_path/'reports/orchestrator/vibe_ic_one_shot.json').read_text())
    assert summary['declared_window']=={'entry_step':'12','exit_step':'12'}
    assert summary['whole_flow_verdict']=='NOT_MEASURED'


def test_d24_late_adoption_change_revokes_qualified_success(tmp_path,monkeypatch):
    current,component,document,_,_=software_case(tmp_path,monkeypatch)
    current=qualified_software(tmp_path,current,document['native_module'])
    stable=metrics.accept_d24(tmp_path,current,component)
    assert stable['status']=='PASS',stable
    qualify=metrics._d24_qualification
    def qualify_then_change(*args):
        answer=qualify(*args);assert answer['status']=='PASS'
        path=tmp_path/'adopted/base_15/adopted_post_dft_netlist.json'
        body=json.loads(path.read_text());body['approval']['status']='NOT_MEASURED';write(path,body)
        return answer
    monkeypatch.setattr(metrics,'_d24_qualification',qualify_then_change)
    answer=metrics.accept_d24(tmp_path,current,component)
    assert answer['status']==answer['metric_status']==answer['qualification']=='NOT_MEASURED',answer
    assert answer['delivery_blocked'] is True
    assert answer['admission']['status']=='PASS' and answer['obligations']==stable['obligations']


def test_d24_measured_scan_failure_survives_missing_adoption(tmp_path,monkeypatch):
    output=OPTIMIZED.replace('SFF ff0(.D(d),.CK(ck),.Q(q));','')
    current,component,_,_,_=software_case(tmp_path,monkeypatch,output)
    (tmp_path/'adopted/base_15/adopted_post_dft_netlist.json').unlink()
    answer=metrics.accept_d24(tmp_path,current,component)
    assert answer['status']==answer['metric_status']=='FAIL',answer
    assert answer['qualification']=='NOT_MEASURED' and answer['delivery_blocked'] is True
    assert answer['obligations'][0]['measurement']['value']>0


@pytest.mark.parametrize('missing',['original_d23','resynthesis_config'])
def test_real_d24_producer_refuses_before_sdk_execution(tmp_path,monkeypatch,missing):
    current,component,document,_,original=software_case(tmp_path,monkeypatch)
    from librelane.steps import Step
    def forbidden(*a,**k):pytest.fail('missing required upstream/config must not start native SDK')
    monkeypatch.setattr(Step.factory.get('Yosys.Resynthesis'),'start',forbidden)
    before=(tmp_path/component['post_dft_component']['path']).read_bytes()
    if missing=='original_d23':
        monkeypatch.setattr(flow109,'d23_scan_replacement_binding',original)
        with pytest.raises(flow109.Flow109Error):design._d24_resynthesis(tmp_path,current)
    else:
        (tmp_path/document['config_input']['path']).unlink()
        with pytest.raises(ValueError,match='D24_RESYNTHESIS_CONFIG_MISSING'):
            design._d24_resynthesis(tmp_path,current)
    assert (tmp_path/component['post_dft_component']['path']).read_bytes()==before
    assert not (tmp_path/'phase2/stage2/synth/post_dft_netlist.v').exists()


def test_public_d24_reports_actual_sdk_error_class_without_publication(tmp_path,monkeypatch):
    current,_,_,_,_=software_case(tmp_path,monkeypatch)
    path=tmp_path/'context.json';write(path,current);monkeypatch.setenv(flow109.CONTEXT_ENV,str(path))
    adopted=tmp_path/'adopted/base_15/adopted_post_dft_netlist.json'
    body=json.loads(adopted.read_text());body.pop('native_component')
    source=tmp_path/body['approval']['source_reference']['path'];payload=json.loads(source.read_text())
    payload.pop('native_component');write(source,payload)
    body['approval']['source_reference']['sha256']=metrics._sha(source.read_bytes());write(adopted,body)
    from librelane.steps.step import StepError
    def software_sdk_failure(*args):
        raise StepError('SOFTWARE_ONLY: actual SDK exception class, no native execution')
    monkeypatch.setattr(design,'_d24_resynthesis',software_sdk_failure)
    result=public._complete_step12_post_dft(tmp_path,'SOFTWARE_ONLY')
    assert result['verdict']==result['component_status']=='NOT_MEASURED',result
    assert 'SOFTWARE_ONLY' in result['detail']
    assert not (tmp_path/'phase2/stage2/synth/post_dft_netlist.v').exists()


@pytest.mark.parametrize('reuse',['adopted_original','missing_original_adoption','changed_original_receipt'])
def test_d24_retained_native_launch_requires_actual_original_owner_binding(tmp_path,monkeypatch,reuse):
    current,component,document,_,_=software_case(tmp_path,monkeypatch)
    current=qualified_software(tmp_path,current,document['native_module'])
    original=copy.deepcopy(document['launch'])
    active={**original,'cid':'d'*64,'attestation_path':str(tmp_path/'input/SOFTWARE_current_launch.json'),
            'attestation_sha256':'d'*64}
    monkeypatch.setattr(contract,'local_image_attestation',lambda *a:copy.deepcopy(active))
    if reuse=='missing_original_adoption':
        adopted=tmp_path/'adopted/base_15/adopted_post_dft_netlist.json';body=json.loads(adopted.read_text())
        source=tmp_path/body['approval']['source_reference']['path'];payload=json.loads(source.read_text())
        payload.pop('launch');write(source,payload)
        body['approval']['source_reference']['sha256']=metrics._sha(source.read_bytes());write(adopted,body)
    elif reuse=='changed_original_receipt':
        path=Path(original['attestation_path']);path.write_text(path.read_text()+'\n')
    answer=metrics.accept_d24(tmp_path,current,component)
    assert answer['status']==('PASS' if reuse=='adopted_original' else 'NOT_MEASURED'),answer
    if reuse!='adopted_original':assert answer['reason']=='D24_ORIGINAL_LAUNCH_UNPROVEN',answer
    else:assert answer['native_observation']['launch']==original
