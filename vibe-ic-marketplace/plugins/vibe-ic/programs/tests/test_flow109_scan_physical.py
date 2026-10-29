"""D36 source controls. Software authority/upstream fixtures are NOT native credit.

Retained measured native artifacts are reopened unchanged in separate parser
controls. The canonical consumer fixture below is explicitly synthetic: it
isolates authority/upstream producers, never claims real D35/D36/SPM acceptance,
and never launches placement, stitching, simulation or proof.
"""
import copy
from contextlib import contextmanager
import sys
import json
import os
from pathlib import Path

import pytest
import flow109
import flow109_metric_acceptance as metrics


def leaf():
    import flow109_scan_physical
    return flow109_scan_physical



@contextmanager
def forbid_native_call():
    before=sys.getprofile()
    code=leaf().run_native.__code__
    def observe(frame,event,arg):
        if event=='call' and frame.f_code is code:
            pytest.fail('unexpected native stitching launch')
        if before is not None:
            before(frame,event,arg)
    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(before)

def context():
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                                  if p['name'] == 'Small digital IC without DFT'))
    features.update(physical=True, requires_scan=True, requires_dft=True)
    plan = flow109.resolve_plan(features)
    return flow109.execution_context(plan, 'D36', 'D36')


def write(project, name, body):
    p = project / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body if isinstance(body, str) else json.dumps(body, sort_keys=True))
    return leaf().reference(project, p)


def intent(roles=True):
    ports = {'scan_enable': 'shift', 'scan_in': 'sin', 'scan_out': 'sout'}
    if roles:
        ports.update(test='testing', tck='tck')
    return {'requires_scan': True, 'test_port_def': {r: {'native': n, 'public': n} for r, n in ports.items()},
        'test_mode': {'clock': 'clk', 'clock_domains': ['clk'], 'edge': 'rising',
            'scan_clock': 'tck', 'scan_clock_domains': ['tck'], 'scan_edge': 'rising',
            'clock_select': {'native': 'testing', 'functional_value': 0, 'scan_value': 1},
            'reset': {'signal': 'rst', 'style': 'synchronous', 'active_level': 1, 'shift_value': 0}}}


LIB = '''library (source_fixture) {
 cell (scan_unit) { pin(D) {direction: input;} pin(CK) {direction: input;}
 pin(SI) {direction: input;} pin(SE) {direction: input;}
 pin(Q) {direction: output; function: "IQ";} }
 cell (clock_mux) {pin(A) {direction: input;} pin(B) {direction: input;}
 pin(S) {direction: input;} pin(Z) {direction: output;function: "(!S*A)+(S*B)";} }
}'''
NETLIST = '''module unit(input clk,tck,testing,shift,sin,rst, output sout,p);
clock_mux m (.A(clk),.B(tck),.S(testing),.Z(c));
scan_unit a (.D(sin),.CK(c),.SI(sin),.SE(shift),.Q(q0));
scan_unit b (.D(sin),.CK(c),.SI(q0),.SE(shift),.Q(q1));
assign sout=q1;assign p=q0;endmodule'''
SCAN = {'scan_unit': {'si': 'SI', 'se': 'SE', 'clk': 'CK', 'q': 'Q'}}


def census(after):
    lines = []
    for i, cell in [('a', 'scan_unit'), ('b', 'scan_unit'), ('m', 'clock_mux')]:
        lines.append(f'CELL\t{i}\t{cell}\tPLACED\t0 0')
    for i in ['a', 'b']:
        pins = {'D': 'sin', 'CK': 'c', 'Q': 'q0' if i == 'a' else 'q1',
                'SI': ('sin' if i == 'a' else 'q0') if after else '', 'SE': 'shift' if after else ''}
        for p, n in pins.items():
            lines.append(f'PIN\t{i}\t{p}\t{n}\t' + ('OUTPUT' if p == 'Q' else 'INPUT'))
    for p, n in {'A':'clk','B':'tck','S':'testing','Z':'c'}.items():
        lines.append(f'PIN\tm\t{p}\t{n}\t'+('OUTPUT' if p=='Z' else 'INPUT'))
    for idx, (p,n) in enumerate({'clk':'clk','tck':'tck','testing':'testing','shift':'shift',
                               'sin':'sin','rst':'rst','sout':'q1' if after else 'q0','p':'q0'}.items()):
        lines.append(f'BTERM\t{p}\t{idx+1}\t'+('OUTPUT' if p in ('sout','p') else 'INPUT')+'\t'+n)
    return '\n'.join(lines)+'\n'


@pytest.fixture
def software_case(tmp_path, monkeypatch):
    native = leaf()
    p = tmp_path.resolve()
    c = context()
    # Only upstream/current D35/intent is isolated. Consumer/reopen/prepare are real.
    prior = {'intent': intent(), 'plan': {'planned_chain_count':1,'max_chain_length':2}, 'scan': {'cells': [{'instance': x,'cell':'scan_unit'} for x in ['a','b']]},
             'accepted': {'D19': 'software fixture', 'D25': 'software fixture', 'D35': 'software fixture'},
             'placed': {'odb': write(p, 'placed.odb', 'SOFTWARE OWNER SOURCE CONTROL ONLY'),
                        'def': write(p, 'placed.def', 'SOFTWARE OWNER SOURCE CONTROL ONLY')}}
    monkeypatch.setattr(native, 'upstream', lambda project, context: copy.deepcopy(prior))
    import librelane_contract
    actual_launch = librelane_contract.local_image_attestation()
    tools = native.tool_readset()
    lib = write(p,'technology/fixture.lib',LIB)
    models = [write(p,'technology/fixture.v','// Explicit software source fixture, not a production model.\n')]
    d19=[]
    for name, rel, schema in [
        ('scenario_constraints','requirements/base_10/scenario_constraints.json',metrics.AUTHORITY_SCHEMA),
        ('mode_library_rc_mapping','adopted/base_10/mode_library_rc_mapping.json','vibeic.flow109.adopted-reference.v1')]:
        payload={'software_upstream_fixture':True}
        src=write(p,'input/'+name+'.json',{name:payload})
        d19.append(write(p,rel,{'schema':schema,**payload,'approval':{'status':'APPROVED','authority':'requirements_owner','source_reference':src}}))
    manifest = {'schema':'vibeic.flow109.d36-input.v1','top':'unit','upstream':prior,'scan_period_ns':17,
        'scan_protocol':'positive_edge_zero_one_alternating_full_chain','test_output_change':{'port':'sout','purpose':'software source fixture'},
        'liberty':lib,'models':models,'defines':['FUNCTIONAL'],'scan_cells':SCAN,
        'D19_mode_authorities':d19,'clock_constraints':[write(p,'fixture.sdc','create_clock -period 17 [get_ports tck]\n')]}
    mref=write(p,native.INPUT,manifest)
    scope={'project':str(p),'purpose':native.PURPOSE,'manifest':mref,'operation_sources':native.operation_sources(),
        'qualified_image':actual_launch['image'],'qualified_image_id':actual_launch['image_id'],
        'actual_tool_readset':tools,'qualified_models':models,'qualified_defines':manifest['defines'],
        'qualified_scan_cells':SCAN,'qualified_cell_types':['scan_unit','clock_mux'],
        'test_output_change':manifest['test_output_change'],
        'qualification_scope':{'purpose':native.PURPOSE,'clock_mixing':'no_mix','edge':'rising','planned_chain_count':1,'scan_protocol':manifest['scan_protocol']}}
    def approve(relative,payload,schema,tag):
        source=write(p,'input/'+tag+'.json',{**scope,'D36':{relative:payload}})
        return write(p,relative,{'schema':schema,**payload,'approval':{'status':'APPROVED','authority':'requirements_owner','source_reference':source}}),source
    req='requirements/scan_physical/scan_flush_errors.json'
    _,qsource=approve(req,{'value':0,'unit':'count'},metrics.AUTHORITY_SCHEMA,'qualification-software-fixture')
    directory=p/'reports/flow109/attempts/software-fixture/D36-native';directory.mkdir(parents=True)
    outputs={k:write(p,str((directory/name).relative_to(p)),body) for k,name,body in [
        ('before','before.tsv',census(False)),('after','after.tsv',census(True)),('netlist','stitched.v',NETLIST),
        ('odb','stitched.odb','SOFTWARE ONLY'),('native_log','native.log','D36_EXECUTE_START\nD36_EXECUTE_DONE\n'),
        ('script','stitch.tcl','// SOFTWARE ONLY'),('testbench','tb.v','// SOFTWARE ONLY'),
        ('compile_log','compile.log','SOFTWARE ONLY'),('simulation_log','simulation.log','D36_FLUSH_DONE checked=16 errors=0\n'),
        ('simulation_result','simulation.result.json',{'returncode':0})]}
    chain=native.derive_map(p/outputs['before']['path'],p/outputs['after']['path'],{**manifest,'qualified_cell_types':scope['qualified_cell_types']},intent(),prior['scan']['cells'])
    outputs['map']=write(p,str((directory/'map.json').relative_to(p)),chain)
    outputs['flush']=write(p,str((directory/'flush.json').relative_to(p)),{'map':outputs['map'],'models':models,
        'defines':manifest['defines'],'clock':native.check_clock(NETLIST,LIB,intent(),chain),
        'protocol':manifest['scan_protocol'],'checked_edges':16,'errors':0})
    outputs['manifest_snapshot']=write(p,str((directory/'manifest.json').relative_to(p)),(p/native.INPUT).read_text())
    live=json.loads(Path(os.environ['VIBEIC_LIBRELANE_LOCAL_ATTESTATION']).read_text())
    launch=write(p,str((directory/'launch.json').relative_to(p)),live)
    doc={'schema':'vibeic.flow109.d36-execution.v1','project':str(p),
        'producer':'phase3_one_shot_runner.step_scan_physical','qualification_source':qsource,
        'manifest':mref,'subject_manifest':manifest,'native_subject':native.native_subject(native.prepare(p,c)),'upstream':prior,'sources':native.operation_sources(),'tools':tools,
        'cid':actual_launch['cid'],'launch':launch,'native_rc':0,'outputs':outputs,'readset':[*outputs.values(),launch]}
    execution=write(p,str((directory/'execution.json').relative_to(p)),doc)
    write(p,native.EXECUTION,execution)
    approve(native.ADOPTED_EXECUTION,{'execution':execution,'producer_sources':doc['sources'],'qualification_source':doc['qualification_source']},'vibeic.flow109.adopted-reference.v1','execution-software-fixture')
    approve('adopted/scan_physical/chain_map_identity.json',{'reference':chain,'reference_identity':{k:{'fixture':'source-only'} for k in ['producer','checker','tool_execution','consumed_inputs','requirements','configuration']}},'vibeic.flow109.adopted-reference.v1','map-software-fixture')
    return p,c,manifest,scope,prior,doc,approve


def test_d36_metric_source_consumer_positive_and_unchanged_owner_reuse(software_case,monkeypatch):
    p,c,*_=software_case
    assert metrics.accept_d36(p,c)['status']=='PASS'
    with forbid_native_call():
        result=leaf().owner(p,c)
    assert result['default_row_status']=='PASS' and result['producer_reused'] is True and result['native_started'] is False
    assert len(result['metric_acceptance']['obligations'])==2
    canonical=flow109._selected_step_result(p,c,result,leaf())
    assert canonical['completed'] is True and canonical['default_row_status']=='PASS'
    assert json.loads((p/'reports/flow109/default_rows/D36.json').read_text())['metric_acceptance']['map_reference']==result['metric_acceptance']['map_reference']


@pytest.mark.parametrize('mutation', ['placed','model','unapproved','resealed_map','direction','chain_order','clock','zero','skipped','protocol'])
def test_d36_actual_source_consumer_refuses_changed_inputs(software_case,mutation):
    p,c,m,scope,prior,doc,approve=software_case
    assert metrics.accept_d36(p,c)['status']=='PASS'
    if mutation in ['placed','model']:
        r=prior['placed']['odb'] if mutation=='placed' else m['models'][0]
        (p/r['path']).write_text('CHANGED')
    elif mutation=='unapproved':
        q=p/'adopted/scan_physical/native_execution.json';d=json.loads(q.read_text());d['approval']['status']='DRAFT';q.write_text(json.dumps(d))
    else:
        key={'resealed_map':'map','direction':'after','chain_order':'after','clock':'netlist','zero':'after','skipped':'native_log','protocol':'flush'}[mutation]
        f=p/doc['outputs'][key]['path'];raw=f.read_text()
        if mutation=='resealed_map':d=json.loads(raw);d['chains'][0]['cells'].reverse();raw=json.dumps(d)
        if mutation=='direction':raw=raw.replace('BTERM\tsout\t7\tOUTPUT','BTERM\tsout\t7\tINPUT')
        if mutation=='chain_order':raw=raw.replace('PIN\tb\tSI\tq0','PIN\tb\tSI\tsin')
        if mutation=='clock':raw=raw.replace('.CK(c)','.CK(clk)')
        if mutation=='zero':raw=''
        if mutation=='skipped':raw='wrapper rc0\n'
        if mutation=='protocol':d=json.loads(raw);d['checked_edges']=0;raw=json.dumps(d)
        f.write_text(raw)
        # Caller reseals outputs/receipt/current pointer; independent adoption stays exact.
        previous=doc['outputs'][key];new=leaf().reference(p,f)
        doc['outputs'][key]=new;doc['readset']=[new if r==previous else r for r in doc['readset']]
        execution=p/json.loads((p/leaf().EXECUTION).read_text())['path'];execution.write_text(json.dumps(doc))
        (p/leaf().EXECUTION).write_text(json.dumps(leaf().reference(p,execution)))
    result=metrics.accept_d36(p,c)
    assert result['status']=='NOT_MEASURED' and result['delivery_blocked'] is True


def test_d36_real_clock_function_truth_and_missing_selector():
    native=leaf();chain={'chains':[{'cells':[{'instance':n,'cell':'scan_unit',**SCAN['scan_unit']} for n in ['a','b']]}]}
    assert native.check_clock(NETLIST,LIB,intent(),chain)['truth_rows_per_cell']==8
    with pytest.raises(metrics.MetricRefusal,match='CLOCK_SELECTION_UNPROVEN'):
        native.check_clock(NETLIST.replace('.CK(c)','.CK(clk)'),LIB,intent(),chain)


def test_d36_registry_entry_is_existing_physical_owner():
    features=copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                                if p['name']=='Small digital IC without DFT'))
    features.update(physical=True,requires_scan=True,requires_dft=True)
    row=flow109.resolve_step(flow109.resolve_plan(features),'D36')
    route=flow109.source_owned_native_dispatch(row)
    assert route is not None
    assert route['producer']=='phase3_one_shot_runner.py:step_scan_physical'
    assert row['profile']['native_steps'] and len(row['obligations'])==2


def test_d36_retained_native_map_reopens_without_native_replay():
    root=Path(os.environ['FLOW109_D36_NATIVE_REFERENCE']);native=leaf()
    before=root/'native01/pre-stitch.tsv';after=root/'native01/post-stitch.tsv'
    cells,_,_=native.snapshot(before)
    types=sorted({c['cell'] for c in cells.values()})
    scan_type=next(t for t in types if '__sdff' in t)
    population=[{'instance':n,'cell':c['cell']} for n,c in cells.items() if c['cell']==scan_type]
    defs={scan_type:{'si':'SI','se':'SE','clk':'CLK','q':'Q'}}
    native_intent={'test_port_def':{r:{'public':r} for r in ['scan_in','scan_out','scan_enable']},'test_mode':{'clock':'clk','edge':'rising'}}
    result=native.derive_map(before,after,{'scan_cells':defs,'qualified_cell_types':types},native_intent,population)
    assert result['population']==2 and result['endpoints']['before']['id']==result['endpoints']['after']['id']
    # Real measured fixture has no tck/test selector; never promote it to formal D36 scope.
    lib=(root/'controls02/readset/liberty.lib').read_text()
    full_intent=intent();full_intent['test_mode']['clock']='clk'
    with pytest.raises(metrics.MetricRefusal,match='CLOCK_SELECTION_UNPROVEN'):
        native.check_clock((root/'native01/stitched.v').read_text(),lib,full_intent,result)


def test_d36_map_expectation_mismatch_remains_fail(software_case):
    p,c,m,scope,prior,doc,approve=software_case
    relative='adopted/scan_physical/chain_map_identity.json'
    body=json.loads((p/relative).read_text());reference=body['reference'];reference['chains'][0]['cells'].reverse()
    approve(relative,{'reference':reference,'reference_identity':body['reference_identity']},'vibeic.flow109.adopted-reference.v1','wrong-map-software-fixture')
    result=metrics.accept_d36(p,c)
    assert result['status']=='FAIL' and result['obligations'][0]['status']=='FAIL'


def test_d36_adopted_native_error_survives_missing_map_authority(software_case):
    p,c,m,scope,prior,doc,approve=software_case
    native=leaf()
    for key in ['flush','simulation_log','simulation_result']:
        previous=doc['outputs'][key];f=p/previous['path']
        if key=='flush':d=json.loads(f.read_text());d['errors']=1;f.write_text(json.dumps(d))
        elif key=='simulation_log':f.write_text('D36_FLUSH_DONE checked=16 errors=1\n')
        else:f.write_text(json.dumps({'returncode':1}))
        new=native.reference(p,f);doc['outputs'][key]=new;doc['readset']=[new if r==previous else r for r in doc['readset']]
    f=p/json.loads((p/native.EXECUTION).read_text())['path'];f.write_text(json.dumps(doc));execution=native.reference(p,f)
    (p/native.EXECUTION).write_text(json.dumps(execution))
    approve(native.ADOPTED_EXECUTION,{'execution':execution,'producer_sources':doc['sources'],'qualification_source':doc['qualification_source']},'vibeic.flow109.adopted-reference.v1','native-error-software-fixture')
    assert metrics.accept_d36(p,c)['status']=='FAIL'
    (p/'adopted/scan_physical/chain_map_identity.json').unlink()
    assert metrics.accept_d36(p,c)['status']=='FAIL'


def test_d36_pattern_binding_refuses_other_map(software_case):
    p,c,*_=software_case;native=leaf()
    current=metrics.accept_d36(p,c)['map_reference']
    with pytest.raises(flow109.Flow109Error):
        native.pattern_map_binding(p,current,c)
    result=native.owner(p,c)
    flow109._selected_step_result(p,c,result,native)
    assert native.pattern_map_binding(p,current,c)==current
    wrong={**current,'sha256':'0'*64}
    with pytest.raises(metrics.MetricRefusal,match='PATTERN_MAP_STALE'):
        native.pattern_map_binding(p,wrong,c)


@pytest.mark.parametrize('missing',['period','models','clock_constraints'])
def test_d36_missing_protocol_or_model_refuses_before_native(software_case,missing,monkeypatch):
    p,c,m,scope,prior,doc,approve=software_case
    if missing=='period':m.pop('scan_period_ns')
    elif missing=='models':m['models']=[]
    else:m['clock_constraints']=[]
    manifest=write(p,leaf().INPUT,m);scope['manifest']=manifest
    approve('requirements/scan_physical/scan_flush_errors.json',{'value':0,'unit':'count'},metrics.AUTHORITY_SCHEMA,'changed-software-qualification')
    with forbid_native_call():
        result=leaf().owner(p,c)
    assert result['component_status']=='NOT_MEASURED' and result['native_started'] is False
    assert result['reason']=={'period':'D36_SCAN_PROTOCOL_ABSENT','models':'D36_MODEL_OR_MODE_AUTHORITY_ABSENT','clock_constraints':'D36_CLOCK_CONSTRAINTS_ABSENT'}[missing]


def test_d36_source_declared_chain_limit_is_not_relaxed(software_case):
    p,c,m,scope,prior,doc,approve=software_case
    prior['plan']['max_chain_length']=1
    m['upstream']=prior;scope['manifest']=write(p,leaf().INPUT,m)
    approve('requirements/scan_physical/scan_flush_errors.json',{'value':0,'unit':'count'},metrics.AUTHORITY_SCHEMA,'tight-plan-software-fixture')
    with forbid_native_call():
        result=leaf().owner(p,c)
    assert result['reason']=='D36_PLAN_LIMIT_EXCEEDED' and result['native_started'] is False


def test_d36_independently_reviewed_metadata_refresh_reuses_original_native(software_case):
    p,c,m,scope,prior,doc,approve=software_case;native=leaf()
    assert metrics.accept_d36(p,c)['status']=='PASS'
    execution=json.loads((p/native.EXECUTION).read_text());before=(p/execution['path']).read_bytes()
    prior['accepted']['D35']='republished software admission; identical native placed input'
    m['upstream']=prior;scope['manifest']=write(p,native.INPUT,m)
    approve('requirements/scan_physical/scan_flush_errors.json',{'value':0,'unit':'count'},metrics.AUTHORITY_SCHEMA,'refreshed-qualification-software-fixture')
    approve(native.ADOPTED_EXECUTION,{'execution':execution,'producer_sources':doc['sources'],'qualification_source':doc['qualification_source']},'vibeic.flow109.adopted-reference.v1','refreshed-execution-software-fixture')
    body=json.loads((p/'adopted/scan_physical/chain_map_identity.json').read_text())
    approve('adopted/scan_physical/chain_map_identity.json',{k:body[k] for k in ['reference','reference_identity']},'vibeic.flow109.adopted-reference.v1','refreshed-map-software-fixture')
    with forbid_native_call():
        result=native.owner(p,c)
    assert result['default_row_status']=='PASS' and result['producer_reused'] is True
    assert (p/execution['path']).read_bytes()==before


def test_d36_explicit_unqualified_runtime_is_not_rescued_by_default(software_case):
    p,c,*_=software_case
    assert metrics.accept_d36(p,c)['status']=='PASS'
    plan=flow109.resolve_plan(c['features'])
    bad=flow109.execution_context(plan,'D36','D36',runtime_tool_uses=[],qualification_registry='absent.json')
    with forbid_native_call():
        result=leaf().owner(p,bad)
    assert result['component_status']=='NOT_MEASURED' and result['native_started'] is False
    assert result['reason']=='QUALIFICATION_RUNTIME_ABSENT'


def test_d36_canonical_writer_reopens_after_genuine_owner_pass(software_case):
    p,c,m,*_=software_case
    with forbid_native_call():
        owner=leaf().owner(p,c)
    assert owner['default_row_status']=='PASS' and owner['metric_acceptance']['status']=='PASS'
    (p/m['models'][0]['path']).write_text('actual model changed after owner read')
    assert metrics.accept_d36(p,c)['status']=='NOT_MEASURED'
    canonical=flow109._selected_step_result(p,c,owner,leaf())
    assert canonical['default_row_status']=='NOT_MEASURED'
    assert canonical['completed'] is False
    row=json.loads((p/'reports/flow109/default_rows/D36.json').read_text())
    assert row['default_row_status']=='NOT_MEASURED' and row['completed'] is False
