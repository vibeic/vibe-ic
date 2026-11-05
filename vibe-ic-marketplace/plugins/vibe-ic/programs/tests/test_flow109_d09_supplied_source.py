"""Supplied RTL staging and authored RTL native metrics remain separate."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sys
import uuid
import pytest
import design_one_shot_runner as design
import vibe_ic_one_shot_runner as front
import benchmark_dispatch as dispatch
import ai_signed_judgement as judgement
import flow109_metric_acceptance as metrics

RTL = "module cell_keep(output logic [7:0] q); initial q=8'ha5; endmodule\nmodule unit(input on, iso, output [7:0] y); cell_keep u_state(y); endmodule\n"


def put(root, rel, body):
    path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(body if isinstance(body,str) else json.dumps(body))
    return path


def case(root, monkeypatch, *, unknown=False, authored=False, damage=None, deferred=None, mixed=False, debug=None, interface=None):
    # Exact original two-module D15 carrier, including its genuine empty
    # parameter and clock/reset populations. Not a serial benchmark fixture.
    assert hashlib.sha256(RTL.encode()).hexdigest() == '931ac7bddbfa37b3a7d3c98942387b068b389e295dad1664468facee015b5be9'
    source = RTL
    if debug is not None:
        source += ('module debug_only; generate if (' + str(int(debug)) + ') begin '
                   'integer fd; initial fd=$fopen("debug.log","w"); end endgenerate endmodule\n')
    put(root,'phase2/stage1/rtl/unit.sv' if authored else 'input/rtl/unit.sv',source)
    ports=[{'name':n,'direction':d,'width':w} for n,d,w in [('on','input',1),('iso','input',1),('y','output',8)]]
    if interface == 'optional':
        ports.append({'name':'optional_status','direction':'input','optional':True})
    elif interface == 'chosen_width':
        ports[-1]['width'] = None
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
    aliases={'fields':('fields.top_ports','fields.parameters'),
             'layer':('L9_INTEGRATION_SPEC.top_ports','L9_INTEGRATION_SPEC.parameters'),
             'bracket':('top_ports[0].name','parameters[0]'),
             'pointer':('/top_ports/0/name','/parameters')}
    if damage in aliases:
        for leaf, path in zip(expects[2]['sub_expectations'],aliases[damage]): leaf['field_path']=path
    if damage == 'missing_constant': facts[0]['constant'].pop('bits')
    if damage == 'constant': facts[0]['constant']['bits'] = ['0'] * 8
    if damage == 'connection': facts[1]['connection']['type'] = 'wrong_cell_type'
    for i,fact in enumerate(facts):
        fact.update(id=demands[i]['id'],text=demands[i]['requirement'])
    put(root,'phase1/generated_docs/L2_FRS.json',{'requirements':facts})
    put(root,'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json',{'source_demands':demands,'expectations':expects,'responsibility_register':[]})
    if deferred:
        layer, field = deferred
        demand = {'id':'later','requirement':'Counter must increment on every enabled cycle','evidence':['input/spec.md:1']}
        if mixed:
            structural = {k:v for k,v in expects[0].items() if k not in ('id','requirement','evidence')}
            expects[0] = {**demands[0],'sub_expectations':[structural,
                {'layer':layer,'field_path':field,'expected_tokens':['increment']},
                {'layer':'L2_FRS','field_path':'behavior','expected_tokens':['increment']}]}
            put(root,'phase1/generated_docs/L2_FRS.json',{'requirements':facts,'behavior':'Counter increments'})
        else:
            demands.append(demand)
            expects.append({**demand,'layer':layer,'field_path':field,'expected_tokens':['increment']})
        path = root / ('phase1/generated_docs/' + layer + '.json')
        doc = json.loads(path.read_text()) if path.exists() else {}
        node=doc
        for part in field.split('.')[:-1]: node=node.setdefault(part,{})
        node[field.split('.')[-1]]=demand['requirement']
        put(root,str(path.relative_to(root)),doc)
        put(root,'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json',{'source_demands':demands,'expectations':expects,'responsibility_register':[]})
    def accepted_d01(project):
        path=project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
        return {'current':True,'evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'detail':'TEST_ONLY accepted D01 precondition isolated, NOT a native/current-row approval'}
    monkeypatch.setattr(design,'_serial_d01_state',accepted_d01)
    if authored:
        owner=asdict(design.step_rtl_gen(root,'unknown'))
        assert owner['status']=='PASS_WITH_WAIVERS' and owner['extras']['fallback_skill']=='spec-to-rtl',owner
        if isinstance(authored, str):
            owner['extras']['fallback_skill']=authored
        if damage=='port':
            put(root,'phase2/stage1/rtl/unit.sv',RTL.replace('input on, iso,','input on,'))
        elif damage=='no_rtl':
            (root/'phase2/stage1/rtl/unit.sv').unlink()
        if damage!='no_review':
            put(root,'reports/audit/ai_judgements/1.json',{'schema':judgement.SCHEMA,'step_id':'1',
                'evidence_sha256':judgement.evidence_sha256(root,'1'),'verdict':'PASS',
                'signed_by':'TEST_ONLY source author','judgement':'TEST_ONLY native fixture author review'})
    else:
        owner=asdict(design.step_reused_ip_consume(root,top_name='unit'))
        assert owner['status']=='PASS',owner
    argv=[sys.executable,str(Path(front.PROGRAMS_DIR)/'phase2_one_shot_runner.py'),str(root),'--entry-step','1','--exit-step','1']
    invocation={'invocation_id':uuid.uuid4().hex,'argv':argv,'project':str(root),
                'source':dispatch._runner_source_snapshot(argv)}
    report={'project':str(root),'verdict':'PASS','declared_window':{'entry_step':'1','exit_step':'1','dispatched_step_ids':['1']},
            'steps':[owner] if authored else [{'name':'rtl_gen','status':'WAIVED','extras':{}},owner]}
    design._write_phase2_report(root/'reports/orchestrator/phase2_one_shot.json',report,root,invocation_context=invocation)
    return root,json.loads((root/'reports/orchestrator/phase2_one_shot.json').read_text()),invocation


def consume(case):
    root,report,invocation=case
    return front._d09_bound_phase2_evidence(root,report,invocation,published_current=True)


@pytest.mark.parametrize('pre_entry', [False, True, 'both'])
def test_supplied_owner_stages_rtl_without_downstream_metrics(tmp_path, monkeypatch, pre_entry):
    def unexpected_metrics(*args, **kwargs):
        raise AssertionError('supplied staging must not run authored metrics')
    monkeypatch.setattr(metrics, '_d09_source_owned_metrics', unexpected_metrics)
    root, report, invocation = case(tmp_path, monkeypatch)
    if pre_entry == 'both':
        report['steps'].insert(0, {**report['steps'][1], 'name': 'reused_ip_consume(pre-entry)'})
        put(root, 'reports/orchestrator/phase2_one_shot.json', report)
    elif pre_entry:
        report['steps'][1]['name'] = 'reused_ip_consume(pre-entry)'
        put(root, 'reports/orchestrator/phase2_one_shot.json', report)
    status, evidence, detail = consume((root, report, invocation))
    assert status == 'PASS', detail
    assert 'unit.sv' in {item['path'] for item in evidence['rtl_inventory']}
    assert 'owned_metrics' not in evidence
    for row in ('D09', 'D10', 'D11', 'D13'):
        assert not (root / f'reports/flow109/default_rows/{row}.json').exists()


@pytest.mark.parametrize('damage,expected', [
    ('staged_source', 'NOT_MEASURED'), ('original_source', 'NOT_MEASURED'),
    ('foreign_owner', 'NOT_MEASURED'), ('stale_owner', 'NOT_MEASURED'),
    ('ambiguous_publishers', 'NOT_MEASURED'), ('tool_fail', 'FAIL'),
])
def test_supplied_staging_preserves_real_failures_and_current_sources(tmp_path, monkeypatch, damage, expected):
    root, report, invocation = case(tmp_path, monkeypatch)
    if damage == 'staged_source':
        (root / 'phase2/stage1/rtl/unit.sv').write_text(RTL + '// changed\n')
    elif damage == 'original_source':
        (root / 'input/rtl/unit.sv').write_text(RTL + '// changed\n')
    elif damage == 'foreign_owner':
        report['runner_binding']['project'] = str(root.parent / 'foreign')
    elif damage == 'stale_owner':
        report['runner_binding']['invocation_id'] = 'stale'
    elif damage == 'ambiguous_publishers':
        report['steps'].append(dict(report['steps'][1]))
    else:
        report['steps'].append({'name': 'rtl_lint_tool', 'status': 'FAIL'})
    put(root, 'reports/orchestrator/phase2_one_shot.json', report)
    status, _, detail = consume((root, report, invocation))
    assert status == expected, detail


@pytest.mark.parametrize('unknown',[False,True],ids=['complete','unmapped'])
@pytest.mark.parametrize('skill',['spec-to-rtl','catalog-glue-author'])
def test_accepted_spec_to_rtl_author_uses_native_source_metrics(tmp_path,monkeypatch,unknown,skill):
    owned=case(tmp_path,monkeypatch,authored=skill,unknown=unknown)
    root,report,_=owned
    author=report['steps'][0]
    result=metrics.d09_owned_metrics(root,author)
    assert result['mapped_items']==['0','1','2']
    assert result['missing_items']==[]
    assert result['required_rtl_items']==['0','1','2']
    assert result['responsibility_register']==([{'id':'unsupported','normal_owner':['D13','D14'],'status':'NOT_MEASURED'}] if unknown else [])
    assert result['declared_ports_parameters']=='PASS'
    assert result==report['d09_owned_metrics']
    assert (root/result['native_witness']['path']).is_file()
    status,_,detail=consume(owned)
    assert status=='PASS',detail


@pytest.mark.parametrize('debug',[False,True],ids=['disabled','active'])
def test_native_elaboration_decides_debug_branch_support(tmp_path,monkeypatch,debug):
    owned=case(tmp_path,monkeypatch,authored='catalog-glue-author',debug=debug)
    status,_,detail=consume(owned)
    assert status==('NOT_MEASURED' if debug else 'PASS'),detail
    if debug:
        assert 'D09_NATIVE_WITNESS_UNAVAILABLE' in owned[1]['steps'][0]['extras']['d09_owned_metrics_refusal']


@pytest.mark.parametrize('damage', [None, 'unapproved', 'missing_mapping'])
def test_authored_metrics_use_current_approved_phase1_population(tmp_path, monkeypatch, damage):
    root, report, invocation = case(tmp_path, monkeypatch, authored='catalog-glue-author')
    path = root / 'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
    body = json.loads(path.read_text()); body.pop('source_demands')
    body['schema'] = 'vibeic.phase1-expert-expectations.v1'
    spec = put(root, 'input/docs/spec.md', (root / 'input/spec.md').read_text())
    cite = f'input/docs/spec.md:1 sha256:{metrics._sha(spec.read_bytes())} — {spec.read_text()}'
    for item in body['expectations']: item['evidence'] = [cite]
    payload = {'required_items': [{'id': e['id']} for e in body['expectations']],
        'source_documents': [{'path': 'input/docs/spec.md', 'sha256': metrics._sha(spec.read_bytes())}],
        'expectations': body['expectations'],
        'features': [{'feature': 'has_digital', 'declared': True, 'evidence': [cite]}]}
    source = put(root, 'input/base_requirements_candidates.json', {'requirements_trace': payload})
    put(root, 'requirements/base_01/requirements_trace.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'required_items': payload['required_items'],
        'approval': {'status': 'PENDING' if damage == 'unapproved' else 'APPROVED',
            'authority': 'requirements_owner', 'approver': 'TEST_ONLY delegated expert',
            'source_reference': {'path': 'input/base_requirements_candidates.json',
                                 'sha256': metrics._sha(source.read_bytes())}}})
    if damage == 'missing_mapping': body['expectations'].pop()
    put(root, str(path.relative_to(root)), body)
    review = json.loads((root / 'reports/audit/ai_judgements/1.json').read_text())
    review['evidence_sha256'] = judgement.evidence_sha256(root, '1')
    put(root, 'reports/audit/ai_judgements/1.json', review)
    out = root / 'reports/orchestrator/phase2_one_shot.json'
    design._write_phase2_report(out, report, root, invocation_context=invocation)
    status, evidence, detail = consume((root, json.loads(out.read_text()), invocation))
    assert status == ('PASS' if damage is None else 'NOT_MEASURED'), detail
    if damage is None:
        assert evidence['owned_metrics']['required_rtl_items'] == ['0', '1', '2']


@pytest.mark.parametrize('damage,status,reason',[
    ('port','FAIL','D09_DECLARED_PORTS_PARAMETERS_MISMATCH'),
    ('no_rtl','NOT_MEASURED','bound RTL inventory is empty'),
    ('no_review','NOT_MEASURED','awaiting_signed_judgement'),
    ('no_handoff','NOT_MEASURED','normal spec-to-rtl handoff required')])
@pytest.mark.parametrize('skill',['spec-to-rtl','catalog-glue-author'])
def test_spec_to_rtl_author_preserves_interface_and_output_refusals(tmp_path,monkeypatch,damage,status,reason,skill):
    owned=case(tmp_path,monkeypatch,authored=skill,damage=damage)
    root,report,_=owned
    if damage=='no_handoff':
        (root/'phase2/stage1/fallback_skill.md').unlink()
    actual,_,detail=consume(owned)
    assert actual==status and reason in detail,detail
    if damage=='port':
        assert report['d09_owned_metrics']['declared_ports_parameters']=='FAIL'
    else:
        with pytest.raises(metrics.MetricRefusal,match='no AI review output|awaiting_signed_judgement|normal spec-to-rtl handoff required'):
            metrics.d09_owned_metrics(root,report['steps'][0])


@pytest.mark.parametrize('mixed',[False,'valid','missing'])
@pytest.mark.parametrize('layer,owners,field',[(*item,'deferred_clause') for item in [
    ('L2_FRS',['D13','D14']), ('L3_CMD_PROTOCOL',['D13','D14']),
    ('L4_REGMAP',['D13','D14']), ('L5_ADI_SPEC',['D13','D14']),
    ('L9_INTEGRATION_SPEC',['D13','D14']), ('L10_TEST_CASES',['D13','D14']),
    ('L12_BEHAVIORAL_SEQUENCES',['D13','D14']), ('L13_LAB_CALIBRATION',['D13','D14']),
    ('L19_CONSTRAINTS_PDK',['D19','D20','D21','D22','D26']),
    ('L22_VERIFICATION_PLAN',['D13','D14']),
    ('L24_SIGNOFF',['D22','D26','D65','D66','D77']),
    ('L21_POWER_INTENT',['D05','D15','D46']),
    ('L27_DELIVERY',['D13','D14'])]]+[
    ('L9_INTEGRATION_SPEC',['D19','D20','D21','D22','D26'],'integration.'+family)
    for family in ('timing','constraints','ppa','technology','synthesis')])
def test_authored_later_demands_remain_named_without_structural_credit(tmp_path,monkeypatch,layer,owners,field,mixed):
    owned=case(tmp_path,monkeypatch,authored=True,deferred=(layer,field),mixed=mixed,
        damage='missing_constant' if mixed=='missing' else None)
    status,evidence,detail=consume(owned)
    assert status==('NOT_MEASURED' if mixed=='missing' else 'PASS'),detail
    result=owned[1]['d09_owned_metrics']
    assert result['required_rtl_items']==['0','1','2']
    assert result['mapped_items']==(['1','2'] if mixed=='missing' else ['0','1','2'])
    assert result['missing_items']==(['0'] if mixed=='missing' else [])
    expected=[{'id':'0' if mixed else 'later','normal_owner':owners,'status':'NOT_MEASURED'}]
    if mixed: expected.append({'id':'0','normal_owner':['D13','D14'],'status':'NOT_MEASURED'})
    assert result['responsibility_register']==expected
    assert {d['id'] for d in result['source_demands']}==set(result['required_rtl_items'])|{r['id'] for r in result['responsibility_register']}


@pytest.mark.parametrize('damage,missing',[('constant','0'),('connection','1'),('missing_constant','0'),('fields','2'),('layer','2'),('bracket','2'),('pointer','2')])
def test_false_explicit_structural_witness_stays_owned_and_unmeasured(tmp_path,monkeypatch,damage,missing):
    owned=case(tmp_path,monkeypatch,authored=True,damage=damage)
    status,_,detail=consume(owned)
    result=owned[1]['d09_owned_metrics']
    assert status=='NOT_MEASURED' and detail=='D09_REQUIRED_MAPPING_MISSING: '+missing
    assert result['missing_items']==[missing] and missing in result['required_rtl_items']
    assert result['responsibility_register']==[]


@pytest.mark.parametrize('interface', ['optional', 'chosen_width'])
def test_author_uses_canonical_optional_and_unspecified_port_contract(tmp_path, monkeypatch, interface):
    owned = case(tmp_path, monkeypatch, authored='catalog-glue-author', interface=interface)
    status, _, detail = consume(owned)
    assert status == 'PASS', detail
    assert owned[1]['d09_owned_metrics']['declared_ports_parameters'] == 'PASS'
