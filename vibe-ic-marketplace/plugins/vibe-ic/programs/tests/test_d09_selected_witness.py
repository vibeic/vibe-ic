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


@pytest.fixture
def retained_mapping_case(tmp_path):
    """TEST_ONLY exact retained source/RTL inputs, never borrowed acceptance."""
    import shutil
    source=Path(os.environ['VIBEIC_D09_RETAINED_CASE'])
    project=tmp_path/'retained';project.mkdir()
    for rel in ['phase1/generated_docs','input/docs','input/submission_template']:
        shutil.copytree(source/rel,project/rel)
    for rel in ['input/flow109-manifest.json','input/step_0_5ic_answers.json',
                'plugin_output/declaration.json','phase2/stage1/rtl/spm.v',
                'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json']:
        target=project/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,target)
    return project


def test_existing_allowed_choices_map_without_implementing_every_alternative(retained_mapping_case):
    import serial_parallel_mul_synth as serial
    project=retained_mapping_case
    body=json.loads((project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json').read_text())
    answer=serial.d09_owned_metrics(project,'digital_arithmetic_primitive')
    assert answer['source_demands']==body['source_demands']
    assert len(answer['source_demands'])==137
    assert len(answer['required_rtl_items'])==30
    assert answer['missing_items']==[],answer['missing_items']
    assert len(answer['mapped_items'])==30
    traces={r['id']:r for r in answer['responsibility_register']}
    for identity in ['architecture:submodule-complete-if-used','architecture:no-stubs-if-used']:
        target=traces[identity]['targets'][0]
        assert target['generator_contract']['relation']=='CONDITIONAL_NONUSE'
        assert target['verification_status']=='NOT_MEASURED'
    for identity in ['encoding:bit-pattern-equivalence','parameter:size-domain']:
        target=traces[identity]['targets'][0]
        assert target['generator_contract']['later_verification']['status']=='NOT_MEASURED'
        assert set(target['generator_contract']['later_verification']['steps'])=={'D13','D14'}
    assert not (project/'reports/flow109/default_rows').exists()
    assert not (project/'reports/audit/ai_judgements').exists()


@pytest.mark.parametrize('change',['exclusive_order','exclusive_encoding','new_behavior','changed_rtl'])
def test_allowed_contract_never_satisfies_an_incompatible_obligation(retained_mapping_case,change):
    import serial_parallel_mul_synth as serial
    project=retained_mapping_case
    if change=='changed_rtl':
        path=project/'phase2/stage1/rtl/spm.v';path.write_text(path.read_text()+'\n// changed source\n')
        with pytest.raises(ValueError,match='D09_SERIAL_SPEC_RTL_OR_DECLARATION_MISMATCH'):
            serial.d09_owned_metrics(project,'digital_arithmetic_primitive')
        return
    path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(path.read_text())
    value={'exclusive_order':'MSB-first','exclusive_encoding':'signed_2c','new_behavior':'saturating addition'}[change]
    demand={'id':'new-obligation','requirement':'The implementation must use '+value+' only.',
            'evidence':['input/docs/extra.md:1 — '+value+' only']}
    body['source_demands'].append(demand)
    body['expectations'].append(dict(demand,layer='L2_FRS',field_path='frs_sections',expected_tokens=[value]))
    write(path,body)
    path=project/'phase1/generated_docs/L2_FRS.json';doc=json.loads(path.read_text());doc['frs_sections'].append({'content':demand['requirement']});write(path,doc)
    (project/'input/docs/extra.md').write_text(demand['requirement'])
    result=serial.d09_owned_metrics(project,'digital_arithmetic_primitive')
    assert result['missing_items']==['new-obligation']
    assert len(result['source_demands'])==138
    assert result['rtl_requirement_mapping']=='NOT_MEASURED'


@pytest.mark.parametrize('field,other',[('bit_order','MSB_first'),('integer_encoding','signed_2c')])
@pytest.mark.parametrize('includes_selected',[True,False],ids=['member','not-member'])
def test_declared_choice_membership_at_normal_consumer(tmp_path,monkeypatch,field,other,includes_selected):
    project=tmp_path/'unit';populate(project)
    selected={'bit_order':'LSB_first','integer_encoding':'unsigned'}[field]
    values=([selected,other] if includes_selected else [other])
    table='| Field | Required | Allowed values |\n|---|---|---|\n| `'+field+'` | yes | '+' / '.join('`'+x+'`' for x in values)+' |'
    path=project/'phase1/generated_docs/L9_INTEGRATION_SPEC.json';l9=json.loads(path.read_text());l9['integration']={'build_declaration':[{'evidence':table}]};write(path,l9)
    path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(path.read_text())
    demand={'id':'choice-membership','requirement':'Declare '+field+', choosing one of the allowed values.', 'evidence':['input/spec.md:4 — '+table]}
    body['source_demands'].append(demand);body['expectations'].append(dict(demand,layer='L9_INTEGRATION_SPEC',field_path='integration.build_declaration',expected_tokens=[field,*values]));write(path,body)
    with (project/'input/spec.md').open('a') as stream:stream.write('\n'+table)
    monkeypatch.setattr(design,'_serial_d01_state',d01_precondition)
    author=normal_author(project)
    document={'project':str(project),'verdict':'PASS','steps':[author], 'declared_window':{'entry_step':'1','exit_step':'1','dispatched_step_ids':['1']}}
    out=project/'reports/orchestrator/phase2_one_shot.json';invocation={}
    def child(argv,*,env=None,**kwargs):
        design._write_phase2_report(out,document,project,invocation_context=json.loads(env[dispatch._RUNNER_CONTEXT_ENV]));return SimpleNamespace(returncode=0)
    monkeypatch.setattr(front.subprocess,'run',child)
    assert front._run_phase('D09 choice membership',Path(front.PROGRAMS_DIR)/'phase2_one_shot_runner.py',[str(project),'--entry-step','1','--exit-step','1'],env=dict(os.environ),invocation=invocation)==0
    report=json.loads(out.read_text());status,_,detail=front._d09_bound_phase2_evidence(project,report,invocation,published_current=True)
    assert status==('PASS' if includes_selected else 'NOT_MEASURED'),detail
    assert report['d09_owned_metrics']['missing_items']==([] if includes_selected else ['choice-membership'])


def test_required_primary_is_not_selected_secondary(tmp_path):
    import serial_parallel_mul_synth as serial
    p=tmp_path/'unit';populate(p)
    path=p/'phase1/generated_docs/L9_INTEGRATION_SPEC.json';doc=json.loads(path.read_text());doc['integration']={'build_declaration':[{'evidence':'| size_param | yes | 64(primary) / 32(secondary) |'}]};write(path,doc)
    spec,reason=serial.extract_serial_parallel_mul_spec(p,'digital_arithmetic_primitive');assert spec,reason
    out=p/'phase2/stage1/rtl/unit.v';out.parent.mkdir(parents=True);out.write_text(serial.emit_rtl(spec));write(p/'plugin_output/declaration.json',dict(serial.plugin_declaration(spec),size_param=32));declaration,_=serial.planned_declaration(p,spec);write(p/'plugin_output/declaration.json',declaration)
    path=p/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json';body=json.loads(path.read_text());d={'id':'required-primary','requirement':'Require size_param primary 64.','evidence':['input/spec.md:4 — primary 64 required']};body['source_demands'].append(d);body['expectations'].append(dict(d,layer='L9_INTEGRATION_SPEC',field_path='integration.build_declaration',expected_tokens=['size_param','64']));write(path,body)
    answer=serial.d09_owned_metrics(p,'digital_arithmetic_primitive')
    assert declaration['size_param']==32
    assert answer['missing_items']==['required-primary'],answer['missing_items']
