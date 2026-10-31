"""SOURCE_ONLY D41 controls. No repair/RCX/STA process or DUT executes.

Native receipt/RCX and requirement APIs are explicit doubles with invalid disk
sentinels. Real numeric parsers, real neutral OpenDB readback, original raw/
canonical decision publishers, worker envelope, versions and finalizer execute.
Unit qualification fixtures never qualify an EDA runtime or IC.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import odb
import execution_backend_producers as producer
import execution_backend_worker as worker
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as ll
import librelane_postroute_repair as repair
import librelane_signoff as signoff
import _native_postroute_timing as native
from _ppa import closure
import phase3_one_shot_runner as runner
import step_output_collector as versions
import test_flow109_window_continuation as windows

REAL_DOCUMENT = metrics._approved_document
REAL_RECEIPT = ll.validate_step_receipt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / 'SOURCE_ONLY_D41';project.mkdir()
    def put(path, value):
        path = project / path;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value,(dict,list)) else value)
        return path
    c = SimpleNamespace(project=project,put=put,receipts={},bodies={})
    c.nl=put('input/neutral.v','module neutral(input a, output y); assign y=a; endmodule\n')
    c.sdc=put('input/neutral.sdc','create_clock -period 24 [get_ports a]\n')
    c.lib=put('input/neutral.lib','SOURCE_ONLY_LIBERTY_SENTINEL\n')
    c.rules=put('input/neutral.rc','SOURCE_ONLY_RCX_RULESET_SENTINEL\n')
    c.lef=put('input/neutral.lef', '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS
 DATABASE MICRONS 1000 ;
END UNITS
LAYER M1
 TYPE ROUTING ;
 DIRECTION HORIZONTAL ;
 PITCH 1 ;
 WIDTH 0.1 ;
END M1
MACRO BUF
 CLASS CORE ;
 ORIGIN 0 0 ;
 SIZE 1 BY 1 ;
END BUF
MACRO FILL
 CLASS CORE SPACER ;
 ORIGIN 0 0 ;
 SIZE 1 BY 1 ;
END FILL
END LIBRARY
''')
    def odb_file(name, fillers):
        d=put('input/'+name+'.def','VERSION 5.8 ;\nDESIGN neutral ;\nUNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 10000 10000 ) ;\nCOMPONENTS '+str(fillers+1)+' ;\n- u BUF + PLACED ( 0 0 ) N ;\n'+''.join(f'- f{i} FILL + PLACED ( {1000*(i+1)} 0 ) N ;\n' for i in range(fillers))+'END COMPONENTS\nEND DESIGN\n')
        database=odb.dbDatabase.create()
        try:
            odb.read_lef(database,str(c.lef));odb.read_def(database.getTech(),str(d))
            path=project/'input'/(name+'.odb');odb.write_db(database,str(path))
        finally:odb.dbDatabase.destroy(database)
        return d,path
    before_def,before_odb=odb_file('before',2)
    after_def,after_odb=odb_file('after',3)
    c.initial=put('phase3/librelane/32-config/bridge/state_in.json',{'def':str(before_def),'odb':str(before_odb),'nl':str(c.nl),'sdc':str(c.sdc)})
    c.configs={};c.corners=['slow_scene','fast_scene'];c.chains={};c.bindings={}
    steps=(repair.REPAIR_STEP,*repair.MEASURE_STEPS)
    for step in steps:
        c.configs[step]=put('phase3/librelane/32-config/'+step+'.json',{'meta':{'step':step},'DESIGN_NAME':'neutral',
            'STA_CORNERS':c.corners,'LIB':{'*':[str(c.lib)]},'PAD_LIBS':{},'RCX_RULESETS':{'*':str(c.rules)},
            'CELL_LEFS':[str(c.lef)],'FILL_CELLS':['FILL'],'DECAP_CELLS':[]})
    def chain(lane, changed, setup):
        previous=c.initial;folders=[]
        fields={f'timing__{kind}__ws__corner:{corner}':value for corner in c.corners for kind,value in [('setup',setup),('hold',.2)]}
        fields.update({f'design__max_{kind}_violation__count__corner:{corner}':0 for corner in c.corners for kind in ['slew','cap','fanout']})
        fields.update(vibeic__prr__input_fillers=2.0,vibeic__prr__changed=changed)
        for index,step in enumerate(steps,1):
            folder=project/'phase3/librelane'/lane/(f'{index:02d}-'+step.lower().replace('.','-'));folders.append(folder)
            body={'def':str(after_def if changed else before_def),'odb':str(after_odb if changed else before_odb),
                'nl':str(c.nl),'sdc':str(c.sdc),'metrics':fields}
            state=put(folder/'state_out.json',body)
            put(folder/'state_in.json',json.loads(previous.read_text()))
            config=c.configs[step]
            if step==repair.REPAIR_STEP:
                config=put('phase3/librelane/32-config/'+step+'@'+lane+'.json',json.loads(config.read_text()))
                doc=json.loads(config.read_text());doc['VIBEIC_PRR_CENSUS_ONLY']=not changed;config.write_text(json.dumps(doc))
            put(folder/'config.json',json.loads(config.read_text()))
            log=put(folder/'invocation.log','PRR: input instances=1 fillers=2\n'+('[INFO DPL-0001] Placed 3 filler instances.\n' if changed else 'PRR: census only: nothing repaired; the input database is the result\n'))
            put(folder/'pdk_root.json',{'mounts_under_it':[]})
            put(folder/'vibeic_receipt.json','SOURCE_ONLY_INVALID_NATIVE_RECEIPT\n')
            cfg=json.loads(config.read_text())
            fp={'step':step,'image':'SOURCE_ONLY_DOUBLE','state':sha(previous),'config':sha(config),
                'state_files':{str(p):sha(p) for p in ll._walk_paths({k:v for k,v in json.loads(previous.read_text()).items() if k!='metrics'})},
                'config_files':ll.config_file_hashes(cfg,[])}
            if step==repair.REPAIR_STEP:fp['plugin']=ll._plugin_digests(step)
            if step=='OpenROAD.RCX':fp['rcx_pdk_files']=ll._rcx_pdk_input_hashes(cfg,project,[])
            if step=='OpenROAD.STAPostPNR':fp['liberty_files']=ll._sta_liberty_input_hashes(cfg,project,[])
            fingerprint=put(folder/'input_fingerprint.json',fp)
            c.receipts[str(folder)]={'input':fp,'sha256':{'state_out.json':sha(state),'invocation.log':sha(log),
                'input_fingerprint.json':sha(fingerprint),'config.json':sha(folder/'config.json'),'pdk_root.json':sha(folder/'pdk_root.json')}}
            previous=state
        measurement=repair.summarize(fields,c.corners)
        measurement.update(sta_state=str(previous),sta_state_sha256=sha(previous),drv_count=0,drv_pin_checks=[],
            antenna_nets=0,antenna_pins=0,antenna_state=str(folders[1]/'state_out.json'),
            native_timing_dir=str(folders[0]/'native_signoff'),native_odb_sha256=sha(after_odb if changed else before_odb),native_sdc_sha256=sha(c.sdc),
            ocv_applied={'mode':'flat_ocv','early':.9,'late':1.1})
        spef=put(folders[2]/'native.spef','SOURCE_ONLY_INVALID_SPEF\n')
        measurement['rcx_binding']={'producer':'OpenROAD.RCX','scope':'SOURCE_ONLY_RCX_API_DOUBLE',
            'scenes':{corner:{'path':str(spef),'sha256':sha(spef)} for corner in c.corners}}
        c.bindings[str(folders[2])]=measurement['rcx_binding']
        scene=put(folders[0]/'native_signoff/measurement_scene.sdc',c.sdc.read_text())
        measurement['native_measurement_sdc_sha256']=sha(scene)
        for corner in c.corners:
            report=put(folders[0]/('native_signoff/sta_'+corner+'.rpt'),f'OCV_BASIS flat_ocv\nworst slack max {setup}\nworst slack min 0.2\n')
            script=[f'read_db {native._q(after_odb if changed else before_odb)}',f'read_liberty {native._q(c.lib)}',
                f'read_sdc {native._q(scene)}',f'read_spef {native._q(spef)}','set_propagated_clock [all_clocks]',
                *native._ocv_tcl(report,.9,1.1,None),f'report_worst_slack -max -digits 6 >> {native._q(report)}',
                f'report_worst_slack -min -digits 6 >> {native._q(report)}','exit']
            put(report.with_suffix('.tcl'),'\n'.join(script)+'\n');put(report.with_suffix('.log'),'SOURCE_ONLY_SUCCESSFUL_NATIVE_CHILD_API_DOUBLE\n')
            log=put(folders[-1]/corner/'sta.log','max slew violation count 0\nmax cap violation count 0\nmax fanout violation count 0\n')
            c.receipts[str(folders[-1])]['sha256'][str(log.relative_to(folders[-1]))]=sha(log)
        c.chains[lane]=(folders,measurement)
        return folders,measurement
    base_folders,baseline=chain('32-base',0,-.4)
    folders,final=chain('32-cand01',1,.5)
    c.folders=folders;c.final=final
    config=project/'phase3/librelane/32-config/Vibeic.PostRouteRepair@32-cand01.json'
    candidate={'candidate':'32-cand01','from':None,'config':str(config),'repair_state':str(folders[0]/'state_out.json'),
        'measurement':final,'repair_metrics':json.loads((folders[0]/'state_out.json').read_text())['metrics'],'decision':'PROPOSED'}
    c.ledger=put('phase3/tool_arms/32/candidates.json',{'candidates':[candidate]})
    registry=closure.load_registry();runs=[]
    for i,cid in enumerate(repair.CONTROLLERS):
        run={'schema':closure.SCHEMA_RUN,'controller':cid,'outcome':'CONVERGED' if i==0 else 'NOT_TRIGGERED',
            'closed_loop_success':True,'collateral_regressions':[],
            'reason':'SOURCE_ONLY_CONTROLLER_RECORD','registry_digest':registry.digest(),'promoted':1 if i==0 else 0,
            'iterations':[{'index':0,'argv':['SOURCE_ONLY_ACTUATOR_API_DOUBLE']}] if i==0 else []}
        run['digest']=closure.cj.digest_of(run);runs.append(run)
    report={'step':'32','mode':'librelane','site':'after_direct_route','image':'SOURCE_ONLY_DOUBLE','arm':'librelane',
        'input_state':str(c.initial),'corners':c.corners,'baseline':baseline,'final':final,'adopted':'32-cand01',
        'adopted_state':str(folders[0]/'state_out.json'),'floors':{'setup':[0,'SOURCE_ONLY'],'hold':[0,'SOURCE_ONLY']},
        'candidates':[{**candidate,'controller':repair.CONTROLLERS[0],'closure_decision':'PROMOTED','closure_reason':'SOURCE_ONLY'}],
        'closure':runs,'repair_trigger':repair.measured_repair_trigger(baseline),'verdict':'PASS',
        'drv_signoff_verdict':'PASS','drv_signoff':{'verdict':'PASS','counts':{'max_slew':0,'max_capacitance':0,'max_fanout':0},
            'failures':[],'not_measured':[],'waived':[]}}
    c.report=report;c.report_path=put(repair.REPORT_REL,report)
    context={'project':str(project),'image':'SOURCE_ONLY_DOUBLE','configs':{k:str(v) for k,v in c.configs.items()},
        'corners':c.corners,'mounts':[],'lane':'32','arm':'librelane','derate':[.9,1.1],'aocv_table':None}
    c.native_context=put('phase3/tool_arms/32/impl/context.json',context)
    c.current=put('phase3/tool_arms/32/impl/current.json',{'candidate':'32-cand01','repair_state':report['adopted_state'],
        'repair_input':report['adopted_state'],'repair_folder':str(folders[0]),'measurement':final})
    handoff={'state':report['adopted_state'],'state_sha256':sha(folders[0]/'state_out.json'),'views':{}}
    for view,src,name in [('def',after_def,'routed.def'),('nl',c.nl,'neutral_pnr.v')]:
        dest=put('phase3/stage3/pnr/'+name,src.read_text())
        handoff['views'][view]={'source':str(src),'source_sha256':sha(src),'dest':str(dest),'dest_sha256':sha(dest)}
    put('reports/phase3/librelane_postroute_repair_handoff.json',handoff)
    monkeypatch.setattr(ll,'validate_step_receipt',lambda folder,step:c.receipts[str(folder)])
    monkeypatch.setattr(signoff,'bind_rcx_spefs',lambda folder,*args:c.bindings[str(folder)])
    monkeypatch.setattr(producer,'_parameters',lambda *args:(runner,ll,SimpleNamespace(name='neutral'),None))
    monkeypatch.setattr(producer,'_retained_synth_census',lambda *args:None)
    monkeypatch.setattr(runner,'step_postroute_repair_librelane',lambda *args:SimpleNamespace(status='PASS',detail='SOURCE_ONLY_NATIVE_CHILD_API_DOUBLE'))
    def publish():
        c.report_path.write_text(json.dumps(c.report))
        repair._publish_declared_repair(project,c.report,c.report_path)
        # The actual producer branch publishes canonical decision and binds
        # its original raw producer report before the D41 metric readback.
        return producer.produce_signoff(project,{'step_id':'32','top':'neutral','image_id':'SOURCE_ONLY_DOUBLE','pdk_root':str(project),'execution_mode':'default'})
    c.publish=publish
    c.context=flow109.execution_context(flow109.resolve_plan(windows._profile()),'D41','D41')
    path=put('context.json',c.context);monkeypatch.setenv(flow109.CONTEXT_ENV,str(path))
    def bounds(relative,body):
        src=put('input/requirement-source.txt','SOURCE_ONLY_INDEPENDENT_REQUIREMENT_READER_DOUBLE\n')
        sentinel=put(relative,'SOURCE_ONLY_INVALID_APPROVAL_SENTINEL\n')
        c.bodies[relative]=({'status':'SOURCE_ONLY_METHOD_DOUBLE','path':relative,'sha256':sha(sentinel),
            'source':{'path':str(src.relative_to(project)),'sha256':sha(src)}},body)
    expected={f'timing__{kind}__ws__corner:{corner}':('ns',{'min':0}) for corner in c.corners for kind in ['setup','hold']}
    expected.update({f'design__max_{kind}_violation__count__corner:{corner}':('count',{'max':0}) for corner in c.corners for kind in ['slew','cap','fanout']})
    bounds('requirements/base_28/post_repair_timing_drv.json',{'limits':{k:v[1] for k,v in expected.items()},'units':{k:v[0] for k,v in expected.items()}})
    bounds('requirements/base_28/repair_iteration_budget.json',{'basis':'candidate_attempts','limits':{'max':2},'units':'count'})
    monkeypatch.setattr(metrics,'_approved_document',lambda project,relative,**kw:c.bodies[relative] if relative in c.bodies else REAL_DOCUMENT(project,relative,**kw))
    c.bounds=bounds
    def observe():
        judge=getattr(metrics,'accept_d41',None)
        assert callable(judge),'D41 consumer absent'
        result=judge(project,c.context,{'native_image':'SOURCE_ONLY_DOUBLE','verdict':'PASS'})
        put('SOURCE_ONLY_D41_OBSERVATION.json',result);return result
    c.observe=observe;c.publish()
    return c


def test_existing_registry_dispatch_is_native32_not_rcx_only22(case):
    assert case.context['resolved_row']['profile']['dispatch']['native_step_id']=='32'
    assert case.context['resolved_row']['position']==63


def test_real_declared_corner_values_filler_roster_and_retained_budget(case):
    result=case.observe()
    assert result['metric_status']=='PASS',json.dumps(result,indent=2)
    assert result['status']==result['qualification']=='NOT_MEASURED'
    assert result['obligations'][0]['measurements'][0]['measurement']['value'] in (.5,.2)
    assert result['obligations'][1]['measurement']['value']==0
    assert result['obligations'][2]['measurement']['value']==1


def test_actual_neutral_odb_roster_is_not_input_equal_count_policy(case):
    path=case.project/'reports/phase3/execution-backend-32.json'
    snap=json.loads(path.read_text())
    assert snap['filler']['method']=='NATIVE_ODB_ROSTER'
    assert len(snap['filler']['before'])==2 and len(snap['filler']['after'])==3
    assert case.observe()['obligations'][1]['status']=='PASS'


@pytest.mark.parametrize('bad',['timing','budget','filler'])
def test_real_numeric_violation_is_fail(case,bad):
    if bad=='timing':case.bodies['requirements/base_28/post_repair_timing_drv.json'][1]['limits']['timing__setup__ws__corner:slow_scene']['min']=1
    elif bad=='budget':case.bodies['requirements/base_28/repair_iteration_budget.json'][1]['limits']['max']=0
    else:
        path=case.project/'input/after.odb'
        db=odb.dbDatabase.create()
        try:
            odb.read_db(db,str(path));db.getChip().getBlock().findInst('f0').setPlacementStatus('UNPLACED');odb.write_db(db,str(path))
        finally:odb.dbDatabase.destroy(db)
        for receipt in case.receipts.values():
            if str(path) in receipt['input']['state_files']:
                receipt['input']['state_files'][str(path)]=sha(path)
        for folder,receipt in case.receipts.items():
            fp=case.put(Path(folder)/'input_fingerprint.json',receipt['input'])
            receipt['sha256']['input_fingerprint.json']=sha(fp)
        case.final['native_odb_sha256']=sha(path)
        current=json.loads(case.current.read_text());current['measurement']=case.final;case.current.write_text(json.dumps(current))
        ledger=json.loads(case.ledger.read_text());ledger['candidates'][0]['measurement']=case.final;case.ledger.write_text(json.dumps(ledger))
        case.publish()
    result=case.observe()
    assert result['status']=='FAIL',json.dumps(result,indent=2)


@pytest.mark.parametrize('bad',['report','script','log','state','config','netlist','library','RC','foreign_report','missing_corner','filler','history','policy','requirements'])
def test_changed_foreign_missing_or_incomplete_source_is_nm(case,bad):
    scene=Path(case.final['native_timing_dir'])
    if bad in ['report','script','log']:
        p=scene/('sta_slow_scene'+{'report':'.rpt','script':'.tcl','log':'.log'}[bad]);p.write_text(p.read_text()+'\nCHANGED\n')
    elif bad=='missing_corner':(scene/'sta_fast_scene.rpt').unlink()
    elif bad=='state':(case.folders[-1]/'state_out.json').write_text('{}')
    elif bad=='config':case.configs['OpenROAD.RCX'].write_text('{}')
    elif bad=='netlist':case.nl.write_text('CHANGED NETLIST')
    elif bad=='library':case.lib.write_text('CHANGED LIBERTY')
    elif bad=='RC':case.rules.write_text('CHANGED RC RULESET')
    elif bad=='foreign_report':
        p=case.project/'reports/phase3/execution-backend-32.json';b=json.loads(p.read_text());b['source_report_sha256']='0'*64;p.write_text(json.dumps(b))
    elif bad=='filler':
        p=case.project/'reports/phase3/execution-backend-32.json';b=json.loads(p.read_text());b['filler']={'status':'NOT_MEASURED'};p.write_text(json.dumps(b))
    elif bad=='history':case.ledger.unlink()
    elif bad=='policy':
        case.report['closure'][0]['registry_digest']='0'*64;case.publish()
    else:case.put('input/requirement-source.txt','CHANGED REQUIREMENT AUTHORITY')
    result=case.observe()
    assert result['status']==result['metric_status']=='NOT_MEASURED',json.dumps(result,indent=2)


def test_measured_fail_survives_later_missing_history_and_authority(case):
    case.bodies['requirements/base_28/post_repair_timing_drv.json'][1]['limits']['timing__hold__ws__corner:slow_scene']['min']=1
    case.ledger.unlink();case.bodies.pop('requirements/base_28/repair_iteration_budget.json')
    assert case.observe()['status']=='FAIL'


def test_real_native_receipt_api_rejects_disk_sentinels(case,monkeypatch):
    monkeypatch.setattr(ll,'validate_step_receipt',REAL_RECEIPT)
    result=case.observe()
    assert result['status']=='NOT_MEASURED' and result['reason']=='LL_STEP_OUTPUT_UNBOUND'


def test_normal_existing_producer_blocks_numeric_violation_and_retains_raw(case):
    raw=(case.project/repair.DECLARED_REPAIR_REL/'postroute_timing_repair_decision.json').read_bytes()
    case.bodies['requirements/base_28/post_repair_timing_drv.json'][1]['limits']['timing__setup__ws__corner:slow_scene']['min']=1
    result=case.publish()
    assert result['verdict']=='FAIL',json.dumps(result,indent=2)
    assert result['metric_acceptance']['metric_status']=='FAIL'
    assert (case.project/repair.DECLARED_REPAIR_REL/'postroute_timing_repair_decision.json').read_bytes()==raw
