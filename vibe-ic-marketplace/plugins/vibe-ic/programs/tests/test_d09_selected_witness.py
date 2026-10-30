"""Selected properties cannot borrow unselected options as implementation proof."""
from pathlib import Path
from types import SimpleNamespace
import json
import os

import pytest
import benchmark_dispatch as dispatch
import design_one_shot_runner as design
import vibe_ic_one_shot_runner as front
from test_flow109_d09_owned_metrics import populate,write,d01_precondition,normal_author

CASES=[
    ('LSB-first','L2_FRS','frs_sections','PASS'),
    ('unsigned','L2_FRS','frs_sections','PASS'),
    ('MSB-first','L2_FRS','frs_sections','NOT_MEASURED'),
    ('signed_2c','L2_FRS','frs_sections','NOT_MEASURED'),
    ('FSM','L9_INTEGRATION_SPEC','integration.architecture','NOT_MEASURED'),
    ('SV','L9_INTEGRATION_SPEC','integration.architecture','NOT_MEASURED'),
    ('sub-module','L9_INTEGRATION_SPEC','integration.architecture','NOT_MEASURED'),
    ('16','L2_FRS','frs_sections','NOT_MEASURED'),
]


@pytest.mark.parametrize('value,layer,field,status',CASES,ids=[c[0] for c in CASES])
def test_exclusive_property_uses_actual_selected_witness(tmp_path,monkeypatch,value,layer,field,status):
    project=tmp_path/'unit';populate(project)
    # All these input variants retain the actual selected default width32.
    # Additional source examples cannot make this a width16 implementation.
    p=project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json';l9=json.loads(p.read_text())
    l9['parameters'][0]['type']='typical 8 / 16 / 32; size >= 4'
    demand={'id':'required_variant','requirement':'The implementation must use '+value+' only.',
            'evidence':['input/spec.md:4 — only '+value+' is allowed']}
    if layer=='L9_INTEGRATION_SPEC':
        l9['integration']={'architecture':[{'source':'input/spec.md','evidence':demand['requirement']}]}
    write(p,l9)
    p=project/'phase1/generated_docs/L2_FRS.json';l2=json.loads(p.read_text())
    l2['frs_sections'].append({'content':demand['requirement']});write(p,l2)
    p=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(p.read_text())
    body['source_demands'].append(demand)
    body['expectations'].append(dict(demand,layer=layer,field_path=field,expected_tokens=[value]));write(p,body)
    with (project/'input/spec.md').open('a') as out:out.write('\n'+demand['requirement'])
    monkeypatch.setattr(design,'_serial_d01_state',d01_precondition) # TEST_ONLY upstream source authority separation.
    author=normal_author(project)
    document={'project':str(project),'verdict':'PASS','steps':[author],
              'declared_window':{'entry_step':'1','exit_step':'1','dispatched_step_ids':['1']}}
    report_path=project/'reports/orchestrator/phase2_one_shot.json'
    invocation={}
    def child(argv,*,env=None,**kwargs):
        context=json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        design._write_phase2_report(report_path,document,project,invocation_context=context)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(front.subprocess,'run',child)
    assert front._run_phase('D09 selected witness control',Path(front.PROGRAMS_DIR)/'phase2_one_shot_runner.py',
        [str(project),'--entry-step','1','--exit-step','1'],env=dict(os.environ),invocation=invocation)==0
    report=json.loads(report_path.read_text())
    actual,evidence,detail=front._d09_bound_phase2_evidence(project,report,invocation,published_current=True)
    assert actual==status,detail
    selected=json.loads((project/'plugin_output/declaration.json').read_text())
    assert selected['bit_order']=='LSB_first' and selected['integer_encoding']=='unsigned'
    owned=report['d09_owned_metrics']
    assert owned['source_demands']==body['source_demands']
    assert owned['source_option_context']['used_as_selected_evidence'] is False
    if status=='PASS':
        assert 'required_variant' in [m['id'] for m in evidence['owned_metrics']['mapped_items']]
    else:
        assert owned['missing_items']==['required_variant']
        assert detail=='D09_REQUIRED_MAPPING_MISSING: required_variant'
        target=owned['responsibility_register'][-1]['targets'][0]
        assert value in target['unestablished_tokens']
    assert not (project/'reports/flow109/default_rows').exists()
    assert not (project/'reports/audit/ai_judgements').exists()
