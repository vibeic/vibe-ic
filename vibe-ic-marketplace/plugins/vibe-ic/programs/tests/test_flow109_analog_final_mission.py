"""D70 neutral native method controls; upstream authority is SOFTWARE ONLY.

No fixture is a qualified D69/A02 receipt or ADC geometry. The genuine final
basis positive remains pending a sealed, qualified RC + simulation-view owner.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109
import flow109_final_electrical as final


def put(root, name, data):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data) if isinstance(data,(dict,list)) else data)
    return final.files._record(root,path)


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for key in (flow109.CONTEXT_ENV,flow109.ATTEMPT_ENV):monkeypatch.delenv(key,raising=False)


def case(tmp_path,monkeypatch,upper=0.7):
    root=tmp_path/'case';root.mkdir()
    netlist=put(root,'network.sp','* TEST_ONLY neutral circuit\nV1 supply 0 1.2\nRfeed supply out testres l=1 w=1\n')
    model=put(root,'models.lib','.lib tt\n.model testres R(rsh=1000)\n.endl tt\n')
    model['section']='tt'
    load=put(root,'load.sp','* TEST_ONLY explicit load\nRload out 0 1000\n')
    tb=put(root,'mission.sp','* TEST_ONLY mission\n.lib models.lib tt\n.include network.sp\n.include load.sp\n.control\nop\n.endc\n.end\n')
    binding=put(root,'bindings.json',{'analysis':{'kind':'OP','temperature_c':27},'measurements':{'vout':{'analysis':'OP','expression':'v(out)','unit':'V'}}})
    spec=put(root,'spec.json',{'specs':{'vout':{'min':0.5,'max':upper}}})
    ref=put(root,'upstream-final.json',{'TEST_ONLY':'SOFTWARE D69 authority double, not extraction evidence'})
    requirements=put(root,'model-requirements.json',{'required_smokes':[{'id':'TEST_ONLY','model':model,'corner':'tt'}]})
    report=put(root,'model-report.json',{'TEST_ONLY':'SOFTWARE A02 consumer double, no native model qualification'})
    cfg={'schema':final.SCHEMA,'mission':'TEST_ONLY divider at explicit OP/load/corner',
         'final_parasitics_receipt':ref,'required_corners':['tt'],'models':{'tt':[model]},
         'model_requirements':requirements,'model_report':report,
         'scenarios':[{'id':'loaded','corner':'tt','testbench':tb,'bindings':binding,'load':load,'spec':spec}]}
    put(root,final.INPUT,cfg)
    basis={'component_parasitics_current':True,'extraction_depth':'RC','fill_sensitive_parasitics':{'status':'PASS'},
           'final_spefs':{'tt':{'TEST_ONLY':'no SPEF qualification'}},'simulation_netlists':{'tt':netlist}}
    def software_d69(project,receipt):
        final.files._bound(project,receipt)
        return basis
    monkeypatch.setattr(final.extract,'validate_final_parasitics',software_d69)
    import flow109_analog_model_check as models
    monkeypatch.setattr(models,'consume',lambda *a:{'verdict':'PASS','scope':'TEST_ONLY SOFTWARE upstream'})
    profile=next(p for p in flow109.load_registry()['reference_profiles'] if p['name']=='Analog IC external trim')
    put(root,'manifest.json',{'features':profile['features']})
    import _delivery_route
    assert _delivery_route.admit(root,'ic') is None
    return root,cfg,basis


def invoke(root):
    args=SimpleNamespace(flow='109',flow109_manifest=root/'manifest.json',flow109_plan_only=False,
                        execution_mode='default',entry_step='D70',exit_step='D70',route='ic')
    try:
        rc=flow109.prepare_front_door(args,root)
        result=json.loads((root/'reports/flow109/components/D70.json').read_text())
    except flow109.Flow109Error as exc:rc,result=2,{'component_status':exc.code,'reason':str(exc)}
    put(root.parent,'OBSERVATION.json',{'rc':rc,'result':result})
    return rc,result


@pytest.mark.parametrize('limit,expected,rc',[(0.7,'PASS',2),(0.55,'FAIL',1)])
def test_normal_neutral_native_mission_actual_value(tmp_path,monkeypatch,limit,expected,rc):
    root,_,_=case(tmp_path,monkeypatch,limit)
    code,result=invoke(root)
    assert result['component_status']==expected,result
    assert result['scenarios'][0]['values']['vout']==pytest.approx(0.6)
    assert code==rc and result['completed'] is False
    assert result['flow109_acceptance']==('FAIL' if expected=='FAIL' else 'NOT_MEASURED')
    assert result['qualification']=='NOT_CLAIMED'
    if expected=='PASS':
        assert final.validate_analog_mission(root,result['receipt'])['component_electrical_current'] is True


@pytest.mark.parametrize('fault',['missing_final','stale_final','C_ONLY','unqualified','empty_scenarios','missing_corner','missing_load','missing_limits','wrong_model_corner'])
def test_ordinary_entry_missing_or_unqualified_inputs_refuse(tmp_path,monkeypatch,fault):
    root,cfg,basis=case(tmp_path,monkeypatch)
    if fault=='missing_final':(root/'upstream-final.json').unlink()
    elif fault=='stale_final':(root/'upstream-final.json').write_text('changed')
    elif fault=='C_ONLY':basis['extraction_depth']='C_ONLY'
    elif fault=='unqualified':basis['fill_sensitive_parasitics']['status']='NOT_MEASURED'
    elif fault=='empty_scenarios':cfg['scenarios']=[]
    elif fault=='missing_corner':cfg['scenarios'][0].pop('corner')
    elif fault=='missing_load':cfg['scenarios'][0].pop('load')
    elif fault=='missing_limits':cfg['scenarios'][0].pop('spec')
    else:cfg['models']={'ss':cfg['models']['tt']}
    put(root,final.INPUT,cfg)
    code,result=invoke(root)
    assert result['component_status']!='PASS',result
    assert code!=0 and result.get('native_started',False) is False


@pytest.mark.parametrize('upper,expected,rc',[(0.7,'NOT_MEASURED',2),(0.55,'FAIL',1)])
def test_unsupported_aging_cannot_offset_native_failure(tmp_path,monkeypatch,upper,expected,rc):
    root,cfg,_=case(tmp_path,monkeypatch,upper)
    cfg['aging']={'required':True};put(root,final.INPUT,cfg)
    code,result=invoke(root)
    assert result['component_status']==expected,result
    assert result['scenarios'][0]['values']['vout']==pytest.approx(0.6)
    assert code==rc


@pytest.mark.parametrize('fault',['native_log','unsupported_requirement'])
def test_current_readback_rejects_changed_native_log(tmp_path,monkeypatch,fault):
    root,_,_=case(tmp_path,monkeypatch)
    code,result=invoke(root)
    assert result['component_status']=='PASS',result
    receipt=final._read(final.files._bound(root,result['scenarios'][0]['native_receipt']))
    if fault=='native_log':
        Path(receipt['executions'][0]['log']).write_text('TEST_ONLY altered after native acquisition\n')
    else:
        # TEST_ONLY forged component claims PASS over a new unsupported demand.
        cfg=final._read(root/final.INPUT);cfg['aging']={'required':True}
        result['manifest']=put(root,final.INPUT,cfg)
        result['receipt']=put(root,'TEST_ONLY-forged-component.json',result)
    with pytest.raises(Exception):final.validate_analog_mission(root,result['receipt'])
    assert code==2 and result['completed'] is False


def test_software_zero_exit_empty_is_not_final_mission(tmp_path,monkeypatch):
    import analog_native_flow
    root,_,_=case(tmp_path,monkeypatch)
    monkeypatch.setattr(analog_native_flow.NativeCommands,'__call__',lambda *a,**k:{'returncode':0})
    code,result=invoke(root)
    assert result['component_status']=='NOT_MEASURED',result
    assert code==2


@pytest.mark.parametrize('qualified,selected,expected',[
    ('tt','tt','ACCEPTED'), ('tt','ss','REFUSED'),
    ('tt',None,'REFUSED'), (None,'tt','REFUSED'),
    (None,None,'ACCEPTED'), ('ss','ss','ACCEPTED'),
    ('tt','','REFUSED'), ('','', 'REFUSED'),
])
def test_selected_library_section_matches_qualified_smoke(tmp_path,monkeypatch,qualified,selected,expected):
    """Actual input consumer, SOFTWARE upstream only; never starts ngspice."""
    root,cfg,basis=case(tmp_path,monkeypatch)
    # Exact same file owns both sections in the independent counterexample.
    text=('.lib tt\n.model testres R(rsh=1000)\n.endl tt\n'
          '.lib ss\n.model testres R(rsh=1500)\n.endl ss\n')
    if qualified is None and selected is None:
        text='.model testres R(rsh=1000)\n'  # genuine no-section include semantics
    model=put(root,'models.lib',text)
    qualified_model=dict(model);selected_model=dict(model)
    if qualified is not None:qualified_model['section']=qualified
    if selected is not None:selected_model['section']=selected
    cfg['models']={'tt':[selected_model]}
    cfg['model_requirements']=put(root,'model-requirements.json',{
        'required_smokes':[{'id':'SOFTWARE_ONLY_tt','model':qualified_model,'corner':'tt'}]})
    directive='.include models.lib' if selected is None else '.lib models.lib '+selected
    cfg['scenarios'][0]['testbench']=put(root,'mission.sp',
        '* SOFTWARE_ONLY section identity\n'+directive+'\n.include network.sp\n.include load.sp\n.end\n')
    try:
        resolved=final._analog_inputs(root,cfg,basis)
        observed='ACCEPTED';reason=None
    except final.AdmissionRefusal as exc:
        resolved=[];observed='REFUSED';reason=exc.code
    put(root.parent,'SECTION_OBSERVATION.json',{'qualified_section':qualified,'selected_section':selected,
        'same_model_sha256':model['sha256'],'declared_corner':'tt','observed':observed,
        'resolved_scenarios':len(resolved),'reason':reason,'native_started':False,
        'scope':'actual _analog_inputs SOFTWARE control; no native qualification'})
    assert observed==expected,{'observed':observed,'qualified':qualified,'selected':selected,'resolved':len(resolved)}
    assert len(resolved)==(1 if expected=='ACCEPTED' else 0)
