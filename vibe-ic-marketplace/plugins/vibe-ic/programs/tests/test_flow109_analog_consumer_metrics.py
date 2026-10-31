"""SOURCE_ONLY consumer regressions; no native job or qualification is run.

Existing native-format unit fixtures exercise real parsers and grading. Reader
edge injections exercise the canonical completion seam, never claim a native
receipt, approval, model qualification, physical coverage or row PASS.
"""
import copy
import json
from pathlib import Path

import pytest
import flow109
import analog_native_em as power
import em_current_density_check as em
import ir_drop_budget_check as ir
import si_crosstalk_check as si
import analog_bound_measurements as measured
from test_analog_native_em import measured_case, grade, put, TABLE, TECH

OWNERS = {'D48':si, 'D56':power, 'D57':ir, 'D58':em}
IDS = {'D48':['base_36.si_required_windows','base_36.coupling_noise_delay_bounds'],
       'D56':['base_40.power_activity_coverage','base_40.per_mode_rail_average_peak_power'],
       'D57':['base_33.rail_source_coverage','base_33.static_dynamic_ir_limits'],
       'D58':['base_34.em_current_lifetime_limits','base_34.current_temperature_model_coverage']}


def context(row):
    for profile in flow109.load_registry()['reference_profiles']:
        if not profile['features'].get('physical'):continue
        features = dict(profile['features'], requires_si=True)
        plan = flow109.resolve_plan(features)
        if any(r['id']==row and r['profile']['id']=='analog_die' for r in plan['rows']):
            return flow109.execution_context(plan, row, row)
    raise AssertionError('registered analog row absent: '+row)


def consume(project, row, component):
    ctx = context(row)
    base = {'step_id':row, 'context_sha256':ctx['context_sha256'], 'component_status':'NOT_MEASURED',
            'default_row_status':'NOT_MEASURED','completed':False,
            'whole_flow_acceptance':'NOT_MEASURED','delivery_accepted':False}
    return flow109._selected_step_result(project, ctx, dict(base, **component), adapter=OWNERS[row])


@pytest.mark.parametrize('row', OWNERS)
def test_nested_measured_failure_survives_missing_native_basis(tmp_path, row):
    component = {'windows':[{'noise_status':'FAIL'}]} if row=='D48' else (
        {'cases':[{'status':'FAIL'}]} if row=='D56' else (
        {'measurement':{'status':'FAIL'}} if row=='D57' else {'blocks':[{'status':'NOT_MEASURED','cases':[{'status':'FAIL'}]}]}))
    result = consume(tmp_path, row, component)
    assert result['default_row_status']=='FAIL', result
    assert result['completed'] is False and result['whole_flow_acceptance']=='NOT_MEASURED'


@pytest.mark.parametrize('row', OWNERS)
def test_missing_basis_never_becomes_zero_or_empty_PASS(tmp_path, row):
    result = consume(tmp_path, row, {'component_status':'PASS'})
    assert result['default_row_status']=='NOT_MEASURED' and result['completed'] is False
    assert result['delivery_accepted'] is False


@pytest.mark.parametrize('row', OWNERS)
def test_prior_obligation_failure_retains_its_id_after_refusal(tmp_path, row):
    oid = IDS[row][0]
    result = consume(tmp_path,row, {'metric_acceptance':{'status':'FAIL','obligations':[{'id':oid,'status':'FAIL'}]}})
    assert result['default_row_status']=='FAIL', result
    items = result['metric_acceptance']['obligations']
    assert any(o['id']==oid and o['status']=='FAIL' for o in items), items


@pytest.mark.parametrize('row', ['D56','D57','D58'])
def test_actual_completion_harvests_partial_numeric_observation_without_row_credit(tmp_path,monkeypatch,row):
    if row=='D56':
        observation = {'cases':[{'name':'mode0','status':'PASS','rails':{'vdd':{'power_w':{'avg':.006,'peak_abs':.009}}}}],
                       'source_cases':{'mode0':{}},'config':{}}
    elif row=='D57':
        observation = {'status':'PASS','source_node':'supply','sampled_nodes':['load'], 'node_drops_mv':{'load':12.},
            'vdd_reference_v':1.2,'window_s':None,'analysis':{'kind':'OP'},'budget_result':{'pass':True},'readset':{}}
    else:
        observation = {'blocks':[{'block':'unit','status':'NOT_MEASURED','cases':[{'name':'op0','numeric_status':'PASS',
            'rating_context':{'native_temperature_c':105},'interconnect_results':[{'status':'PASS','material':'Metal2','current_a':.0001}]}]}]}
    helper = '_'+row.lower()+'_metric_observation'
    monkeypatch.setattr(OWNERS[row],helper,lambda *args: observation,raising=False)
    result = consume(tmp_path,row,{'component_status':'PASS'})
    actual = (result.get('metric_acceptance') or {}).get('native_observation')
    assert actual==observation, result
    assert result['default_row_status']=='NOT_MEASURED' and result['completed'] is False


@pytest.fixture
def si_capture(tmp_path):
    model=put(tmp_path/'coupling.sp','Cc aggressor victim 1p\n')
    net=put(tmp_path/'unit.sp','.include coupling.sp\nRv victim 0 1k\n')
    bench=put(tmp_path/'tb.sp','.include unit.sp\n.end\n')
    def ref(path):return {'path':str(path.relative_to(tmp_path)),'sha256':measured.sha(path)}
    window={'id':'edge','aggressor':'v(aggressor)','victim':'v(victim)','baseline_v':0.,'from_s':0.,'to_s':2.,
            'max_noise_v':.3,'min_aggressor_swing_v':.9}
    data={'netlist':ref(net),'testbench':ref(bench),'coupling_model':ref(model),
          'analysis':{'kind':'TRAN','step_s':1.,'start_s':0.,'stop_s':2.,'temperature_c':25},'windows':[window]}
    put(tmp_path/'input/flow109/D48.json',data)
    data,inputs=si._d48_inputs(tmp_path)
    # Native-format neutral source fixture. This is not an executed native receipt.
    binary=put(tmp_path/'source-only-tool','SOURCE_ONLY parser fixture, never executed\n')
    capture=put(tmp_path/'capture.dat','time bound_w0_aggressor bound_w0_victim\n0 0 0\n1 1 .2\n2 0 0\n')
    log=put(tmp_path/'native.log','SOURCE_ONLY neutral capture fixture\n')
    views={role:inputs[role] for role in ('netlist','testbench')}
    views.update(deck=inputs['testbench'],native_binary={'path':str(binary),'sha256':measured.sha(binary)})
    views.update(measured.consumed_input_views(tmp_path,bench))
    native={'status':'PASS','native_inputs':views,'bindings':si._d48_bindings(data,str(binary)),
        'capture':{'path':str(capture),'sha256':measured.sha(capture)},
        'executions':[{'returncode':0,'argv':['SOURCE_ONLY'],'log':str(log),'log_sha256':measured.sha(log)}],
        'measurements':{'w0_noise':.2,'w0_amax':1.,'w0_amin':0.}}
    return tmp_path,data,inputs,native


def test_si_existing_capture_parser_exposes_noise_without_delay_credit(si_capture):
    root,data,inputs,native=si_capture
    status,_,windows=si._d48_consume(root,native,data,inputs)
    assert status=='PASS' and windows[0]['peak_noise_v']==.2
    result=consume(root,'D48',{'component_status':'PASS','inputs':inputs,'native':native,'windows':windows})
    obligations=(result.get('metric_acceptance') or {}).get('obligations',[])
    assert [(o['id'],o['status']) for o in obligations]==[(oid,'NOT_MEASURED') for oid in IDS['D48']], result
    assert result['default_row_status']=='NOT_MEASURED'


def test_si_relabelled_capture_vectors_are_not_executed_measurements(si_capture):
    root,data,inputs,native=si_capture
    native['bindings']['capture']['w0_victim']='v(foreign)'
    try: status=si._d48_consume(root,native,data,inputs)[0]
    except ValueError as exc:status=str(exc)
    assert status=='D48_EXECUTED_BINDINGS_DIFFER_FROM_REQUEST', status


def test_em_late_mapping_gap_preserves_earlier_measured_DC_violation(measured_case):
    project,setting,paths=measured_case
    # Change the actual source OP voltage and matching current above the source limit.
    paths['capture'].write_text(paths['capture'].read_text().replace('0 0.0001','0 0.01'))
    mapping=json.loads(paths['currents'].read_text());mapping.update(voltage_v=[.01,0],current_a=.01/1.0005)
    paths['currents'].write_text(json.dumps(mapping)+'\n'+json.dumps(dict(mapping,spice_resistor='foreign'))+'\n')
    rec=power._read(paths['receipt'])
    for path in (paths['capture'],paths['currents']):rec['outputs'][str(path)]=power._sha(path)
    put(paths['receipt'],rec)
    try: result,_=grade(project,setting)
    except ValueError as exc:result={'status':'NOT_MEASURED','reason':str(exc)}
    assert result['status']=='FAIL', result
    assert result['violations'][0]['material']=='metal2'


def test_em_successful_native_segments_are_exposed_for_coverage(measured_case):
    result,_=grade(*measured_case[:2])
    actual=result.get('interconnect_results',[])
    assert len(actual)==1 and actual[0]['status']=='PASS', result
    assert actual[0]['material']=='metal2'


def test_si_later_window_gap_does_not_erase_measured_noise_failure(si_capture):
    root,data,inputs,native=si_capture
    data['windows'][0]['max_noise_v']=.1
    data['windows'].append(dict(data['windows'][0],id='later'))
    native['bindings']=si._d48_bindings(data,native['bindings']['execution']['ngspice_bin'])
    capture=Path(native['capture']['path'])
    capture.write_text('time bound_w0_aggressor bound_w0_victim bound_w1_aggressor bound_w1_victim\n0 0 0 0 0\n1 1 .2 1 .2\n2 0 0 0 0\n')
    native['capture']['sha256']=measured.sha(capture)
    try:status=si._d48_consume(root,native,data,inputs)[0]
    except (ValueError,KeyError):status='NOT_MEASURED'
    assert status=='FAIL', status


def test_em_aggregate_late_required_population_error_keeps_measured_failure(measured_case,monkeypatch):
    project,setting,paths=measured_case
    paths['capture'].write_text(paths['capture'].read_text().replace('0 0.0001','0 0.01'))
    mapping=json.loads(paths['currents'].read_text());mapping.update(voltage_v=[.01,0],current_a=.01/1.0005)
    put(paths['currents'],json.dumps(mapping)+'\n')
    rec=power._read(paths['receipt'])
    for path in (paths['capture'],paths['currents']):rec['outputs'][str(path)]=power._sha(path)
    put(paths['receipt'],rec)
    pdf=put(project/'source-only.pdf','SOURCE_ONLY document-conversion edge; not qualification\n')
    source=put(project/'source-limits.json',{'copy':str(pdf),'sha256':power._sha(pdf)})
    monkeypatch.setattr(power,'_limit_document_text',lambda *args:(TABLE,{}))
    monkeypatch.setattr(power,'read_technology',lambda *args:(TECH,{}))
    result=power.run(project,'unit',{'limits_source':str(source),'magic_tech':'source-only.tech',
        'cases':[dict(setting,name='op0')],'required_cases':[1,'absent']})
    assert result['cases'][0]['status']=='FAIL', result
    assert result['status']=='FAIL', result


@pytest.mark.parametrize('sign', [-1,1])
def test_supply_power_integrates_actual_voltage_times_signed_current(tmp_path,sign):
    import numpy as np
    path=tmp_path/'supply.raw'
    times=np.array([0.,.1,1.,2.])
    matrix=np.stack([times,1.+times,sign*.001*(1.+times)],axis=1).astype('<f8')
    path.write_bytes(b'Title: SOURCE_ONLY supply integration fixture\nPlotname: Transient Analysis\nFlags: real\nNo. Variables: 3\nNo. Points: 4\nVariables:\n0 time time\n1 v(vdd) voltage\n2 i(vfeed) current\nBinary:\n'+matrix.tobytes())
    stats=power.supply_wave_statistics(power.NativeRaw(path),[0,2],'Vfeed vdd 0 PWL(0 1 2 3)\n',{'vdd':'Vfeed'},{'vdd':'vdd'})['vdd']
    assert stats['power_w']['avg']==pytest.approx(-sign*.001*13/3)
    assert stats['power_w']['peak_abs']==pytest.approx(.009)
    assert stats['power_w']['avg']!=pytest.approx(stats['voltage_v']['avg']*stats['current_a']['avg'])


@pytest.mark.parametrize('load,expected',[(1.19,'PASS'),(1.18,'FAIL'),(1.17,'FAIL')])
def test_ir_native_reader_preserves_strict_budget_and_reopens_retained_record(tmp_path,load,expected):
    # Neutral log/data formats only; no simulator invocation or qualified receipt.
    net=put(tmp_path/'network.sp','Rwire source load 1\n')
    bench=put(tmp_path/'bench.sp','.include network.sp\n.end\n')
    body={'analysis':{'kind':'OP','temperature_c':27},'measurements':{
        'source_v':{'analysis':'OP','expression':'v(source)','unit':'V'},
        'load_v':{'analysis':'OP','expression':'v(load)','unit':'V'}}}
    bindings=put(tmp_path/'bindings.json',body)
    def ref(path):return {'path':path.name,'sha256':measured.sha(path)}
    cfg={'netlist':ref(net),'testbench':ref(bench),'bindings':ref(bindings),
         'source_node':'source','required_nodes':['load'],'arguments':{'budget_pct':5/3}}
    put(tmp_path/'input/flow109/D57.json',cfg)
    data=ir._d57_inputs(tmp_path)
    log=put(tmp_path/'native.log',f'MEAS source_v=1.2 load_v={load}\n')
    views={role:{'path':str(path),'sha256':measured.sha(path)} for role,path in data['paths'].items()}
    views['deck']=views['testbench'];views.update(measured.consumed_input_views(tmp_path,bench))
    record={'status':'PASS','bindings':body,'native_inputs':views,'measurements':{'source_v':1.2,'load_v':load},
            'executions':[{'returncode':0,'log':str(log),'log_sha256':measured.sha(log)}]}
    work=tmp_path/'retained';work.mkdir()
    put(work/'measurements/result.json',record)
    answer=ir._d57_grade(tmp_path,data,record,work)
    assert answer['status']==expected, answer
    result=consume(tmp_path,'D57',{'component_status':answer['status'],'measurement':answer})
    assert result['default_row_status']==('FAIL' if expected=='FAIL' else 'NOT_MEASURED'), result
    observation=(result.get('metric_acceptance') or {}).get('native_observation')
    assert observation is not None and observation['node_drops_mv']['load']==pytest.approx((1.2-load)*1000), result
