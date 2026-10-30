"""Native neutral D47 controls; extraction depth is not RC/signoff approval.

No native output is rewritten. Parasitic-free data is emitted by Magic from
an explicitly bad threshold setting on a TEST_ONLY copy. The rc0/no-data case
is separately identified as a SOFTWARE_ONLY producer-result injection.
"""
import copy
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
    source = os.environ.get('D47_NATIVE_CARRIER')
    if not source:
        pytest.skip('explicit native neutral candidate inputs not supplied')
    project = tmp_path/'project'
    shutil.copytree(source, project, ignore=shutil.ignore_patterns('reports','.vibeic'))
    return project


def update(project, change):
    path=project/'input/flow109/D47.json'
    data=json.loads(path.read_text());change(data)
    path.write_text(json.dumps(data))


def invoke(project):
    args=SimpleNamespace(flow='109',flow109_manifest=project/'manifest.json',
        flow109_plan_only=False,execution_mode='default',entry_step='D47',exit_step='D47')
    try:
        rc=flow109.prepare_front_door(args,project)
        result=json.loads((project/'reports/flow109/components/D47.json').read_text())
    except flow109.Flow109Error as exc:
        rc,result=2,{'component_status':exc.code,'reason':str(exc),'native_started':False}
    (project.parent/'observed.json').write_text(json.dumps({'rc':rc,'component':result},indent=2)+'\n')
    return rc,result


def test_normal_candidate_extraction_discloses_C_only_without_row_pass(carrier):
    rc,result=invoke(carrier)
    assert result['component_status']=='PASS',result
    assert result['extraction_depth']=='C_ONLY'
    assert result['measurements']['audit']['summary']['capacitors']==3
    assert result['measurements']['audit']['summary']['resistors']==0
    assert result['require_resistance'] is False
    assert rc==2 and result['default_row_status']=='NOT_MEASURED'
    assert result['completed'] is False and result['qualification']=='NOT_CLAIMED'
    assert result['whole_flow_acceptance']=='NOT_MEASURED'
    assert not (carrier/'input/flow109/D60.json').exists()
    for ref in result['outputs']:
        assert hashlib.sha256((carrier/ref['path']).read_bytes()).hexdigest()==ref['sha256']


def test_actual_parasitic_free_native_output_is_rejected(carrier):
    update(carrier,lambda d:d['options'].update(cthresh=1e12,extresist=False))
    rc,result=invoke(carrier)
    assert result['component_status']=='FAIL',result
    assert result['measurements']['audit']['depth']=='NONE'
    assert result['measurements']['audit']['summary']['capacitors']==0
    assert result['measurements']['audit']['summary']['resistors']==0
    assert 'NO_PARASITICS' in [x['rule'] for x in result['measurements']['audit']['findings']]
    assert result['executions'][0]['returncode']==0
    assert rc==1 and result['default_row_status']=='FAIL'


def test_C_only_does_not_satisfy_declared_resistance_requirement(carrier):
    update(carrier,lambda d:d.update(require_resistance=True))
    rc,result=invoke(carrier)
    assert result['component_status']=='FAIL',result
    audit=result['measurements']['audit']
    assert audit['depth']=='C_ONLY'
    assert 'RESISTANCE_REQUIRED_BUT_ABSENT' in [x['rule'] for x in audit['findings']]
    assert rc==1 and result['default_row_status']=='FAIL'


def test_wrong_source_device_population_fails_existing_consumer(carrier):
    path=carrier/'input/candidate/logical.spice'
    path.write_text('.subckt candidate_top A B\nXmissing A B 0 0 missing_neutral_device\n.ends candidate_top\n')
    update(carrier,lambda d:d['logical_netlist'].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    rc,result=invoke(carrier)
    assert result['component_status']=='FAIL',result
    inventory=result['measurements']['device_inventory']
    assert inventory['a3_devices']==1 and inventory['extracted_devices']==0
    assert inventory['result']=='MISMATCH'
    assert rc==1


def test_missing_candidate_refuses_before_native_or_extracted_output(carrier):
    config=json.loads((carrier/'input/flow109/D47.json').read_text())
    (carrier/config['layout']['path']).unlink()
    rc,result=invoke(carrier)
    assert result['component_status']=='NOT_MEASURED',result
    assert result['native_started'] is False and rc==2
    assert list((carrier/'reports/flow109/D47').rglob('candidate.spice'))==[]


def test_rc_zero_and_done_marker_without_data_cannot_pass(carrier,monkeypatch):
    monkeypatch.setattr(staging.Stage,'sh',lambda *a,**k:(0,'MAGIC_EXTRACT_RESIM_DONE candidate_top -> candidate.spice\n',''))
    rc,result=invoke(carrier)
    assert result['component_status']=='FAIL',result
    assert 'EMPTY_NETLIST' in [x['rule'] for x in result['measurements']['audit']['findings']]
    assert result['measurements']['audit']['depth']=='NONE'
    assert rc==1


def test_undeclared_extraction_style_does_not_fall_back(carrier):
    update(carrier,lambda d:d['options'].update(extract_style='undeclared_neutral_style'))
    rc,result=invoke(carrier)
    assert result['component_status']=='NOT_MEASURED',result
    assert 'D47_STYLE_NOT_DECLARED_BY_TECHNOLOGY' in result['reason']
    assert result['native_started'] is False and rc==2


def test_wrong_logical_top_is_not_an_extraction_of_this_candidate(carrier):
    path=carrier/'input/candidate/logical.spice';path.write_text('.subckt other_candidate A B\n.ends other_candidate\n')
    update(carrier,lambda d:d['logical_netlist'].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    rc,result=invoke(carrier)
    assert result['component_status']=='NOT_MEASURED',result
    assert 'D47_LOGICAL_TOP_ABSENT_OR_AMBIGUOUS' in result['reason']
    assert result['native_started'] is False and rc==2


def test_exact_analog_candidate_owner_keeps_other_profiles_and_qualification_strict():
    registry=flow109.load_registry()
    analog=next(p['features'] for p in registry['reference_profiles'] if p['name']=='Analog IC external trim')
    plan=flow109.resolve_plan(analog);row=flow109.resolve_step(plan,'D47')
    assert flow109.source_owned_native_dispatch(row)['adapter']=='magic_extract_spice_emit'
    for profile in ('assembly','other'):
        foreign=copy.deepcopy(row);foreign['profile']['id']=profile
        assert flow109.source_owned_native_dispatch(foreign) is None
    foreign=copy.deepcopy(row);foreign['id']='D48'
    assert flow109.source_owned_native_dispatch(foreign) is None
    claimed=flow109.execution_context(plan,'D47','D47',runtime_tool_uses=[],qualification_registry='missing.json')
    assert flow109.source_owned_native_admission(claimed) is None
    digital=next(p['features'] for p in registry['reference_profiles'] if p['name']=='Small digital IC without DFT')
    default=flow109.source_owned_native_dispatch(flow109.resolve_step(flow109.resolve_plan(digital),'D47'))
    assert default['kind']=='canonical_backend_window' and default['native_step_id']=='22'
