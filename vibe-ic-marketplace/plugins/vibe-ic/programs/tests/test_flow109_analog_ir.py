"""Small native D57 method controls; never extracted-ADC or row qualification."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import flow109


def digest(path):
    return {'path': str(path.name), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture(autouse=True)
def context_environment(monkeypatch):
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.delenv(name, raising=False)


def project(tmp_path, resistance=1, transient=False):
    root=tmp_path/'project';root.mkdir()
    network=root/'network.sp'
    load='pulse(0.001 0.004 1u 1n 1n 1u 2u)' if transient else '0.001'
    network.write_text(f'* TEST_ONLY explicit neutral power network, ohms/A/V\nVfeed supply 0 1.2\nRwire supply load {resistance}\nIload load 0 {load}\n')
    template=root/'mission.sp';template.write_text('* TEST_ONLY declared mission\n.include network.sp\n.control\nop\n.endc\n.end\n')
    bindings=root/'bindings.json'
    analysis={'kind':'TRAN','step_s':1e-8,'start_s':0.,'stop_s':3e-6,'temperature_c':27} if transient else {'kind':'OP','temperature_c':27}
    measurements={label:{'analysis':analysis['kind'],'expression':'v('+node+')','unit':'V',**({'statistic':'AVG','from_s':0.,'to_s':3e-6} if transient else {})} for label,node in [('source_v','supply'),('load_v','load')]}
    body={'analysis':analysis,'measurements':measurements}
    if transient:body['capture']={'source_v':'v(supply)','load_v':'v(load)'}
    bindings.write_text(json.dumps(body))
    cfg={'netlist':digest(network),'testbench':digest(template),'bindings':digest(bindings),
         'source_node':'supply','required_nodes':['load'],'arguments':{'budget_pct':1.0}}
    path=root/'input/flow109/D57.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(cfg))
    profile=next(p for p in flow109.load_registry()['reference_profiles'] if p['name']=='Analog IC external trim')
    (root/'manifest.json').write_text(json.dumps({'features':profile['features']}))
    # Use the existing normal operator-route writer for this TEST_ONLY control.
    # This is not an ADC owner adoption or native qualification receipt.
    import _delivery_route
    assert _delivery_route.admit(root, 'ic') is None
    return root


def invoke(root):
    args=SimpleNamespace(flow='109',flow109_manifest=root/'manifest.json',flow109_plan_only=False,
                         execution_mode='default',entry_step='D57',exit_step='D57',route='ic')
    try:
        rc=flow109.prepare_front_door(args,root)
        result=json.loads((root/'reports/flow109/components/D57.json').read_text())
    except flow109.Flow109Error as exc:
        rc,result=2,{'component_status':exc.code,'reason':str(exc)}
    (root.parent/'OBSERVATION.json').write_text(json.dumps({'rc':rc,'result':result},indent=2)+'\n')
    return rc,result


@pytest.mark.parametrize(('resistance','expected','drop'),[(1,'PASS',1.),(20,'FAIL',20.)])
def test_normal_native_static_drop_uses_existing_budget(tmp_path,resistance,expected,drop):
    rc,result=invoke(project(tmp_path,resistance))
    assert result['component_status']==expected,result
    assert result['measurement']['budget_result']['measured']['drop_mv']==pytest.approx(drop,abs=1e-8)
    assert result['measurement']['required_nodes']==['load']
    assert result['measurement']['vdd_reference_v']==pytest.approx(1.2)
    assert result['completed'] is False
    assert result['whole_flow_acceptance']=='NOT_MEASURED' and result['qualification']=='NOT_CLAIMED'
    assert rc==(2 if expected=='PASS' else 1)


def test_normal_native_transient_reads_required_node_capture(tmp_path):
    rc,result=invoke(project(tmp_path,5,True))
    assert result['component_status']=='FAIL',result
    assert result['measurement']['node_drops_mv']['load']==pytest.approx(20.,abs=1e-6)
    assert result['measurement']['sample_count']>2
    assert result['measurement']['window_s']==[0.,3e-6]
    assert rc==1 and result['completed'] is False


@pytest.mark.parametrize('fault',['missing_required_node','unbound_source','scalar_vdd_override','scalar_report_only'])
def test_invalid_source_or_coverage_never_becomes_native_ir(tmp_path,fault):
    root=project(tmp_path);path=root/'input/flow109/D57.json';cfg=json.loads(path.read_text())
    if fault=='missing_required_node':cfg['required_nodes'].append('unmeasured_node')
    elif fault=='unbound_source':cfg['netlist']['sha256']='0'*64
    elif fault=='scalar_vdd_override':cfg['arguments']['vdd']=100.
    else:
        fake=root/'scalar.json';fake.write_text('{"max_ir_drop_mv":0,"vdd":1.2}')
        cfg={'report':str(fake),'arguments':{'budget_pct':1}}
    path.write_text(json.dumps(cfg))
    rc,result=invoke(root)
    assert result['component_status']!='PASS'
    assert rc!=0
    assert result.get('native_started',False) is False


@pytest.mark.parametrize('fault',['network','log','required_node','capture'])
def test_changed_current_native_inputs_refuse(tmp_path,monkeypatch,fault):
    import analog_native_flow as native
    root=project(tmp_path,1,transient=fault=='capture')
    original=native.NativeCommands.__call__
    def tamper(self,program,args,**kwargs):
        execution=original(self,program,args,**kwargs)
        if program=='analog_bound_measurements.py':
            report=Path(args[args.index('--out')+1])/'result.json';record=json.loads(report.read_text())
            if fault=='network':(root/'network.sp').write_text('* TEST_ONLY altered source after actual native\n')
            elif fault=='log':Path(record['executions'][0]['log']).write_text('TEST_ONLY changed native transcript\n')
            elif fault=='capture':Path(record['capture']['path']).write_text('time bound_source_v bound_load_v\n')
            else:
                path=root/'input/flow109/D57.json';cfg=json.loads(path.read_text());cfg['required_nodes']=['changed_required_node'];path.write_text(json.dumps(cfg))
        return execution
    monkeypatch.setattr(native.NativeCommands,'__call__',tamper)
    rc,result=invoke(root)
    assert result['component_status']=='NOT_MEASURED',result
    assert rc==2 and result['completed'] is False


def test_software_zero_exit_empty_producer_is_not_measurement(tmp_path,monkeypatch):
    import analog_native_flow as native
    root=project(tmp_path)
    monkeypatch.setattr(native.NativeCommands,'__call__',lambda *args,**kwargs:
                        {'returncode':0,'stdout':'','stderr':'','argv':[]})
    rc,result=invoke(root)
    assert result['component_status']=='NOT_MEASURED',result
    assert result['reason']=='D57_NATIVE_RECEIPT_ABSENT'
    assert rc==2
