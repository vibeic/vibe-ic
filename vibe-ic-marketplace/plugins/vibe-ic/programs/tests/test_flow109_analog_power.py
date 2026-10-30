"""Retained real tiny native captures; negative copies are TEST_ONLY, not ADC facts."""
import hashlib,json,os,shutil,math
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109


@pytest.fixture
def carrier(tmp_path):
    source=os.environ.get('D56_NATIVE_CARRIER')
    if not source:pytest.skip('explicit retained neutral native carrier absent')
    project=tmp_path/'project';shutil.copytree(source,project,ignore=shutil.ignore_patterns('reports','.vibeic'))
    return project


@pytest.fixture
def retained(tmp_path):
    bank=Path(os.environ.get('D56_RETAINED_BANK','/missing-normal-packet'))
    if not bank.is_dir():pytest.skip('normal ordinary-entry positive has not emitted a packet')
    project=tmp_path/'project';shutil.copytree(bank,project)
    return project


def change(project,edit):
    p=project/'input/flow109/D56.json';d=json.loads(p.read_text());edit(d);p.write_text(json.dumps(d))


def invoke(project):
    args=SimpleNamespace(flow='109',flow109_manifest=project/'manifest.json',flow109_plan_only=False,execution_mode='default',entry_step='D56',exit_step='D56')
    try:
        rc=flow109.prepare_front_door(args,project);r=json.loads((project/'reports/flow109/components/D56.json').read_text())
    except flow109.Flow109Error as exc:rc,r=2,{'component_status':exc.code,'reason':str(exc)}
    (project.parent/'observed.json').write_text(json.dumps({'rc':rc,'component':r},indent=2));return rc,r


def test_real_current_and_variable_voltage_power_match_analytic_time_integrals(carrier):
    rc,r=invoke(carrier)
    assert r['component_status']=='PASS',r
    a=r['cases'][0]['rails']['supply'];assert a['negative_node']=='ref'
    assert a['current_a']['avg']==pytest.approx(.002,rel=1e-10)
    assert a['current_a']['rms']==pytest.approx(math.sqrt(13/3)/1000,rel=1e-10)
    assert a['current_a']['peak_abs']==pytest.approx(.003,rel=1e-10)
    assert a['power_w']['avg']==pytest.approx(13/3000,rel=1e-10)
    assert a['power_w']['peak_abs']==pytest.approx(.009,rel=1e-10)
    assert a['power_w']['avg']!=pytest.approx(a['voltage_v']['avg']*a['current_a']['avg'],rel=1e-3)
    assert r['cases'][0]['units']=={'current_a':'A','voltage_v':'V','power_w':'W','window_s':'s'}
    assert rc==2 and r['completed'] is False and r['native_started'] is True
    assert r['activity_coverage']==r['power_bounds']==r['whole_flow_acceptance']=='NOT_MEASURED'
    assert r['qualification']=='NOT_CLAIMED'
    produced=r['cases'][0]['retained_case']
    rec=json.loads((carrier/produced['receipt']['path']).read_text())
    assert rec['native_raw']['encoding']=='gzip'
    assert rec['argv'][rec['argv'].index('-r')+1]==rec['native_raw']['executed_path']
    assert rec['native_raw']['executed_path']!=rec['native_raw']['stored_path']
    assert rec['native_environment']['SPICE_USERINIT_DIR']
    assert rec['native_init_before']==rec['native_init_after']
    bank=Path(os.environ['D56_RETAINED_BANK']);shutil.copytree(carrier,bank)
    # Transport the normal program's ready-to-consume input, byte-for-byte.
    # No provenance/artifact field is authored by this test.
    (bank/'input/flow109/D56.json').write_bytes((carrier/r['retained_inputs']['path']).read_bytes())


def test_genuine_different_load_changes_native_current_and_power(carrier):
    change(carrier,lambda d:d.update(cases=[json.loads((carrier/'load2-case.json').read_text())]))
    rc,r=invoke(carrier)
    assert r['component_status']=='PASS',r
    a=r['cases'][0]['rails']['supply']
    assert a['current_a']['avg']==pytest.approx(.001,rel=1e-10)
    assert a['power_w']['avg']==pytest.approx(13/6000,rel=1e-10)
    assert a['power_w']['peak_abs']==pytest.approx(.0045,rel=1e-10)
    assert rc==2


@pytest.mark.parametrize('kind',['wrong_source','wrong_rail','wrong_ground','raw_changed','source_changed','window_truncated','missing_raw','empty_rails','failed_log','missing_launch','forged_receipt'])
def test_incomplete_foreign_or_changed_native_evidence_is_not_power_PASS(retained,kind):
    carrier=retained
    config=json.loads((carrier/'input/flow109/D56.json').read_text());case=config['cases'][0]
    if kind=='wrong_source':case['supplies']['supply']='Vref'
    elif kind=='wrong_rail':case['external']['supply']='unbound_rail'
    elif kind=='wrong_ground':case['signal_ground']='0'
    elif kind=='window_truncated':case['window_s']=[0,3e-6]
    elif kind=='empty_rails':case.update(supplies={},required_rails=[],external={})
    elif kind=='missing_launch':case['launch']['path']=str(carrier/'missing-origin-launch.json')
    else:
        field='capture' if kind in ('raw_changed','missing_raw') else 'deck' if kind=='source_changed' else 'log' if kind=='failed_log' else 'receipt'
        p=carrier/case[field]['path']
        if kind=='missing_raw':p.unlink()
        elif kind=='failed_log':p.write_text('fatal error: TEST_ONLY changed log\n')
        elif kind=='forged_receipt':
            d=json.loads(p.read_text());d['returncode']=0;d['status']='PASS';d['outputs'][str(Path(d['deck']).parent/'tran.raw')]='0'*64;p.write_text(json.dumps(d))
        else:p.write_bytes(p.read_bytes()+b'\nTEST_ONLY altered input')
        if p.is_file():case[field]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    (carrier/'input/flow109/D56.json').write_text(json.dumps(config))
    rc,r=invoke(carrier)
    assert r['component_status']=='NOT_MEASURED',r
    assert r['cases'][0]['status']=='NOT_MEASURED' and 'rails' not in r['cases'][0]
    assert rc==2


def test_no_cases_or_rails_cannot_claim_zero_activity_coverage(carrier):
    change(carrier,lambda d:d.update(cases=[]))
    rc,r=invoke(carrier)
    assert r['component_status']=='NOT_MEASURED' and r['cases']==[] and rc==2,r


def test_retained_normal_packet_reopens_original_launch_without_native_replay(retained):
    rc,r=invoke(retained)
    assert r['component_status']=='PASS',r
    assert r['native_started'] is False and rc==2
    assert r['cases'][0]['rails']['supply']['power_w']['avg']==pytest.approx(13/3000,rel=1e-10)


def test_ordinary_rc_zero_without_raw_cannot_claim_power(carrier,monkeypatch):
    import analog_native_interconnect_run as producer
    # SOFTWARE_ONLY missing native output, not an execution/qualification fact.
    def no_capture(command,work,container,environment,seconds,log,*args,**kwargs):
        Path(log).write_text('TEST_ONLY rc0 without native capture\n')
        return {'argv':list(map(str,command)),'returncode':0,'capture_budget_exceeded':False}
    monkeypatch.setattr(producer,'execute',no_capture)
    rc,r=invoke(carrier)
    assert r['component_status']=='NOT_MEASURED' and rc==2,r
    assert r['cases'][0]['status']=='NOT_MEASURED' and 'rails' not in r['cases'][0]
