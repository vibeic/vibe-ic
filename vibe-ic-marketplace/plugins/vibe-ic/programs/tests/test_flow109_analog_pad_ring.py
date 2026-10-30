"""D32 real PDK native component controls; no ADC/ESD/physical-PG credit."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import flow109
import analog_hardmacro_gds_emit as staging


@pytest.fixture
def carrier(tmp_path):
    source=os.environ.get('D32_NATIVE_CARRIER')
    if not source:pytest.skip('explicit neutral native carrier not supplied')
    project=tmp_path/'project';shutil.copytree(source,project,ignore=shutil.ignore_patterns('reports','.vibeic'))
    return project


def change(project,edit):
    p=project/'input/flow109/D32.json';d=json.loads(p.read_text());edit(d);p.write_text(json.dumps(d))


def invoke(project):
    args=SimpleNamespace(flow='109',flow109_manifest=project/'manifest.json',flow109_plan_only=False,execution_mode='default',entry_step='D32',exit_step='D32')
    try:
        rc=flow109.prepare_front_door(args,project);result=json.loads((project/'reports/flow109/components/D32.json').read_text())
    except flow109.Flow109Error as exc:
        rc,result=2,{'component_status':exc.code,'reason':str(exc),'native_started':False}
    (project.parent/'observed.json').write_text(json.dumps({'rc':rc,'component':result},indent=2));return rc,result


def test_native_pad_component_without_synthesized_RTL_or_full_row_claim(carrier):
    rc,r=invoke(carrier)
    assert r['component_status']=='PASS',r
    assert len(r['placement']['pads'])==8 and len(r['placement']['corners'])==4
    assert len(r['placement']['fillers'])==96
    assert r['consumer']['verdict']=='PASS'
    assert len(r['native_db']['ports'])==8 and len(r['native_db']['instances'])==108
    assert all(v['present'] and v['nonempty'] for v in r['native_gds'].values())
    assert 'physical_PG_rail_conduction' in r['unmeasured']
    assert rc==2 and r['completed'] is False and r['qualification']=='NOT_CLAIMED'
    assert r['default_row_status']==r['whole_flow_acceptance']=='NOT_MEASURED'
    assert not list((carrier/'rtl').glob('*.v'))
    for ref in r['outputs']:assert hashlib.sha256((carrier/ref['path']).read_bytes()).hexdigest()==ref['sha256']


def test_actual_native_disconnected_pad_pin_is_not_hidden_by_placement_PASS(carrier):
    p=carrier/'input/candidate/disconnected.def'
    change(carrier,lambda d:d.update(floorplan_def={'path':str(p.relative_to(carrier)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
    rc,r=invoke(carrier)
    assert r['placement']['verdict']=='PASS',r
    assert r['component_status']=='FAIL' and rc==1
    assert r['reason']=='D32_NATIVE_DECLARED_PAD_PIN_DISCONNECTED: pS'


@pytest.mark.parametrize('kind',['missing_floorplan','stale_floorplan','stale_IO_view','wrong_IO_view','missing_port','missing_PDK'])
def test_invalid_subject_or_PDK_views_refuse_before_native(carrier,kind):
    if kind=='missing_floorplan':(carrier/'input/candidate/floorplan.def').unlink()
    elif kind=='stale_floorplan':change(carrier,lambda d:d['floorplan_def'].update(sha256='0'*64))
    elif kind=='stale_IO_view':change(carrier,lambda d:d['io_gds'][0].update(sha256='0'*64))
    elif kind=='wrong_IO_view':change(carrier,lambda d:d['io_gds'][0].update(path='/foreign/other.gds'))
    elif kind=='missing_port':
        p=carrier/'input/candidate/logical.spice';p.write_text('.subckt neutral_top b c d vdd vss iovdd iovss\n.ends neutral_top\n')
        change(carrier,lambda d:d['logical_netlist'].update(sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    else:(carrier/'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').write_text('{"fields":{}}')
    rc,r=invoke(carrier)
    assert r['component_status']=='NOT_MEASURED',r
    assert r['native_started'] is False and rc==2


def test_empty_assignment_is_not_a_pad_population_PASS(carrier):
    p=carrier/'input/candidate/assignment.json';p.write_text('{}')
    change(carrier,lambda d:d['pad_assignment'].update(sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    rc,r=invoke(carrier)
    assert r['component_status']=='NOT_MEASURED',r
    assert r['placement']['verdict']=='SKIP' and r['native_started'] is False and rc==2


def test_rc_zero_without_native_readback_is_not_component_PASS(carrier,monkeypatch):
    # SOFTWARE_ONLY process-edge injection; genuine producer/checker still run.
    monkeypatch.setattr(staging.Stage,'sh',lambda *a,**k:(0,'',''))
    rc,r=invoke(carrier)
    assert r['placement']['verdict']==r['consumer']['verdict']=='PASS',r
    assert r['component_status']=='NOT_MEASURED' and rc==2
