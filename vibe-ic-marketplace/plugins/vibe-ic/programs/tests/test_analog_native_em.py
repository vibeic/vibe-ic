from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
import _plugin_tree  # noqa: F401
import analog_native_em as em
import _analog_a8_extraction_wrapper as wrapper


TABLE='''2.15 Maximum Current Densities
(11 years @105°C)
Metal1 IMAXM1 mA 0.36 A.v w = 0.16 ... 0.36 µm
Metal1 JMAXM1 mA/µm 1 A.v w > 0.36 µm
Metal2 IMAXM2 mA 0.6 A.v w = 0.2 … 0.3 µm
Metal2 JMAXM2 mA/µm 2 A.v w > 0.3 µm
Metal4 JMAXM4 mA/µm 2 A.v w > 0.3 µm
Via1 JMAXVIA1 mA/Via 0.4 A.v
Contact JMAXCNT mA/Cnt 0.3 A.v
2.16 Layer Thickness Values
'''
TECH='''planes
 metal1,m1
 metal2,m2
 active
end
types
 metal1 metal1,m1
 metal2 metal2,m2
 active diffusion,nd
 metal1 via1,v
 active contact,cnt
end
contact
 via1 metal1 metal2
 contact diffusion metal1
end
lef
 routing m1 Metal1
 routing m2 Metal2
 cut via1 Via1
end
'''


@pytest.mark.parametrize('material,width,current,status',[
 ('metal1','0.2',.0003,'PASS'),
 ('metal2','0.3',.0007,'FAIL'),
 ('metal2','0.31',.00061,'PASS'),
 ('metal2','0.199',.0001,'NOT_MEASURED'),
 ('metal4','0.5',.001,'PASS'),
])
def test_source_width_regimes_and_exact_units(material,width,current,status):
    limits=em.parse_process_limits(TABLE)
    result=em.evaluate_row({'current_a':current,'is_contact':False},limits[material],Fraction(width))
    assert result['status']==status


@pytest.mark.parametrize('cuts,current,status',[(1,.00045,'FAIL'),(4,.0007,'NOT_MEASURED'),(4,.00039,'PASS')])
def test_actual_single_cut_and_conservative_array_bound(cuts,current,status):
    result=em.evaluate_row({'current_a':current,'is_contact':True,'cuts_x':cuts,'cuts_y':1},
                           em.parse_process_limits(TABLE)['via1'],None)
    assert result['status']==status
    assert 'per_cut_current' not in result
    if cuts>1:assert result['current_scope']=='whole-array upper bound only'


@pytest.mark.parametrize('drc,current,status',[(False,.0001,'NOT_MEASURED'),
                                             (True,.0001,'PASS'),
                                             (True,.0003,'NOT_MEASURED')])
def test_subminimum_sheet_partition_uses_lower_bound_of_complete_source_regimes(drc,current,status):
    rules=em.parse_process_limits(TABLE)['metal2']
    result=em.evaluate_row({'current_a':current,'is_contact':False},rules,Fraction('0.1'),
                           drc_qualified=drc)
    assert result['status']==status
    if drc:
        assert result['density_bound_mA_per_um_exact']=='2'
        assert result['limit_mA']==.2
        assert 'DRC-clean drawn wire' in result['current_scope']


def test_partition_bound_requires_complete_source_width_coverage():
    rules=em.parse_process_limits(TABLE)['metal2']
    rules[1]['width_gt_um']='0.4'
    result=em.evaluate_row({'current_a':1e-9,'is_contact':False},rules,Fraction('0.1'),
                           drc_qualified=True)
    assert result['status']=='NOT_MEASURED'


@pytest.mark.parametrize('header',['d g s b','d g s b\n+ w=0.35u l=0.34u ng=1 m=1',
                                    'd g s b params: w=0.35u l=0.34u'])
def test_native_mos_pairs_bind_typed_identity_terminals_and_consumed_model_order(header):
    source='.subckt unit d g s b\nXswitch d g s b opaque_foundry_42 w=1u l=1u\n.ends unit\n'
    topology={'block':'unit','devices':[{'name':'switch','role':'nmos','nets':['d','g','s','b']}]}
    raw='.subckt extracted nd ng ns nb\nXnative nd ng ns nb opaque_foundry_42 w=1u l=1u\n.ends extracted\n'
    models=['.subckt opaque_foundry_42 '+header+'\n.ends opaque_foundry_42\n']
    values={'actual.nd':1.1,'actual.ng':.8,'actual.ns':.1,'actual.nb':0}
    result=em.mos_stress(source,topology,'unit',raw,models,values,lambda n:'actual.'+n)
    assert result['status']=='PASS' and result['devices'][0]['role']=='nmos'
    assert result['devices'][0]['pairs_v']=={'gs':.8-.1,'gd':1.1-.8,'gb':.8,'ds':1.1-.1,'db':1.1,'sb':.1}
    assert result['source_models']['opaque_foundry_42']['source_instances']==['switch']
    assert result['maxima_by_model']['opaque_foundry_42']['db']=={'value_v':1.1,'instance':'Xnative'}
    topology['devices'][0]['nets']=['g','d','s','b']
    with pytest.raises(ValueError,match='terminals differ'):
        em.mos_stress(source,topology,'unit',raw,models,values,lambda n:'actual.'+n)


def test_native_mos_pair_export_does_not_guess_subcircuit_pin_order():
    source='.subckt unit d g s b\nXswitch d g s b opaque_model\n.ends unit\n'
    topology={'block':'unit','devices':[{'name':'switch','role':'pmos','nets':['d','g','s','b']}]}
    with pytest.raises(ValueError,match='d/g/s/b order'):
        em.mos_stress(source,topology,'unit','Xnative d g s b opaque_model',
                      ['.subckt opaque_model g d s b\n'],{},lambda n:n)


@pytest.mark.parametrize('unindented',[False,True])
def test_materials_come_from_actual_tech_aliases_and_contacts(unindented):
    text=TECH.replace(' routing','routing').replace(' cut','cut') if unindented else TECH
    aliases,known=em.material_map(text)
    assert aliases['m1']=='metal1' and aliases['v']=='via1'
    assert aliases['cnt']=='contact'
    assert 'nd' in known and 'nd' not in aliases
    assert 'unknown_metal' not in aliases


def put(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(text,indent=2) if isinstance(text,dict) else text)
    return path


@pytest.fixture
def measured_case(tmp_path):
    bdir=tmp_path/'phase3/analog/unit'
    source=put(bdir/'unit.sp','.subckt unit a b\nRcore a b 1\n.ends unit\n')
    top=put(bdir/'topology.json',{'rails':{'vdd':'a','vss':'b'}})
    gds=put(bdir/'unit.gds','native geometry fixture')
    work=tmp_path/'native';raw=put(work/'unit__em.spice','.subckt unit__em a b\nR0 a b 1.0005\n.ends unit__em\n')
    text,interface=wrapper.build_wrapper(raw.read_text(),'unit__em',['a','b'])
    wp=put(work/'interface.sp',text)
    pp=put(work/'post.sp','.subckt unit a b\nXrcx a b '+interface['wrapper_subckt']+'\n.ends unit\n')
    dp=put(work/'op.sp','* native OP fixture\nxdut a b unit\n.control\nop\n.endc\n.end\n')
    scale=struct.unpack('f',struct.pack('f',.005))[0]
    header={'scale_um':scale,'scale_um_numerator':1,'scale_um_denominator':200,'resist_scale':1000}
    row={'node_a':'a','node_b':'b','type':'m2','type_long':'metal2','network':'a',
         'resistance_ohm':1.0,'ext_resistance_value':1,'is_contact':False,
         'width_grid':60,'length_grid':200,'width_um':60*scale,'length_um':200*scale}
    geometry=put(work/'geometry.jsonl',json.dumps(header)+'\n'+json.dumps(row)+'\n')
    capture=put(work/'op.raw','Title: native fixture\nPlotname: Operating Point\nFlags: real\nNo. Variables: 2\nNo. Points: 1\nVariables:\n0 v(a) voltage\n1 v(b) voltage\nValues:\n0 0.0001\n0\n')
    log=put(work/'native.log','Doing analysis at TEMP = 105\nNo. of Data Rows : 1\n')
    mapping=dict(row,spice_resistor='R0',spice_nodes=['a','b'],spice_resistance_ohm=1.0005,
                 voltage_vectors=['a','b'],voltage_v=[.0001,0],current_a=.0001/1.0005)
    currents=put(work/'currents.jsonl',json.dumps(mapping)+'\n')
    rec={'status':'PASS','returncode':0,'unchanged':True,'interface':interface,
         'inputs_before':{str(p):em._sha(p) for p in [source,top,raw,geometry,wp,pp,dp]},
         'outputs':{str(p):em._sha(p) for p in [capture,log,currents]}}
    receipt=put(work/'command.json',rec)
    extraction=put(work/'extraction.json',{'returncode':0,'unchanged':True,
        'source_inputs_before':{str(gds):em._sha(gds)},'outputs':{str(raw):em._sha(raw)}})
    setting={'receipt':str(receipt),'geometry':str(geometry),'spice':str(raw),'extraction_receipt':str(extraction)}
    return tmp_path,setting,{'receipt':receipt,'geometry':geometry,'capture':capture,'log':log,'currents':currents,'source':source,'gds':gds}


def grade(project,setting):
    aliases,known=em.material_map(TECH)
    return em.grade_case(project,setting,em.parse_process_limits(TABLE),aliases,known,
                         block='unit',rating_context=em.process_rating_context(TABLE))


def test_real_consumer_recomputes_native_current_and_pg_ranges(measured_case):
    project,setting,_=measured_case
    result,views=grade(project,setting)
    assert result['status']=='PASS' and result['graded_segments']==1
    assert result['pg_voltage_ranges']['a']=={'min_v':0.,'max_v':.0001,'sampled_endpoints':2}
    assert result['feed_voltages']=={'a':.0001,'b':0.}
    assert str(project/'phase3/analog/unit/unit.gds') in views


def test_a16_real_consumer_runs_native_em_case_without_promoting_missing_mission(
        measured_case, monkeypatch):
    import analog_native_physical as physical
    project,case,_=measured_case
    pdf=put(project/'current-density.pdf','source-owned limit bytes')
    source=put(project/'current-density-source.json',
               {'copy':str(pdf),'sha256':em._sha(pdf)})
    converted=type('Converted',(),{'stdout':TABLE})()
    monkeypatch.setattr(em.subprocess,'run',lambda *a,**k:converted)
    monkeypatch.setattr(em,'read_technology',lambda *a,**k:(TECH,{}))
    result=physical._reliability(project,'unit','native','','process',{
        'em':{'limits_source':str(source),'magic_tech':'source.tech','cases':[case]},
        '_features':{'requires_thermal':False,'requires_ir':False,'requires_aging':False}})
    assert result['status']=='NOT_MEASURED'
    assert result['metrics']['mission']['status']=='NOT_MEASURED'
    assert result['metrics']['em']['status']=='PASS'
    assert result['metrics']['em']['result']['cases'][0]['status']=='PASS'


@pytest.mark.parametrize('temperature,expected',[
    (105,'PASS'),(125,'NOT_MEASURED'),(None,'NOT_MEASURED')])
def test_a16_mission_pass_cannot_promote_unrated_native_em(
        measured_case, monkeypatch, temperature, expected):
    import analog_native_physical as physical
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    project,case,paths=measured_case
    paths['log'].write_text((f'Doing analysis at TEMP = {temperature}\n'
                             if temperature is not None else 'No native temperature marker\n'))
    rec=em._read(paths['receipt']);rec['outputs'][str(paths['log'])]=em._sha(paths['log'])
    put(paths['receipt'],rec)
    pdf=put(project/'current-density.pdf','source-owned limit bytes')
    source=put(project/'current-density-source.json',
               {'copy':str(pdf),'sha256':em._sha(pdf)})
    converted=type('Converted',(),{'stdout':TABLE})()
    monkeypatch.setattr(em.subprocess,'run',lambda *a,**k:converted)
    monkeypatch.setattr(em,'read_technology',lambda *a,**k:(TECH,{}))
    put(project/'mission.sp','.control\nop\n.endc\n.end\n')
    put(project/'mission-spec.json',{'specs':[{'name':'max_stress','max':1.0}]})
    monkeypatch.setattr(dr,'resolve_host_root',lambda *a:str(project))
    monkeypatch.setattr(ars,'_container_path',lambda c,root,path:str(path))
    monkeypatch.setattr(ars,'_run_ngspice',lambda *a,**k:(
        True,{'max_stress':.8},'native mission PASS',{}))
    result=physical._reliability(project,'unit','native','','process',{
        'deck':'mission.sp','spec':'mission-spec.json',
        'em':{'limits_source':str(source),'magic_tech':'source.tech','cases':[case]},
        '_features':{'requires_thermal':False,'requires_ir':False,'requires_aging':False}})
    assert result['metrics']['mission']['status']=='PASS'
    assert all(result['metrics'][name]['status']=='NOT_APPLICABLE'
               for name in ('thermal','ir','aging'))
    assert result['metrics']['em']['status']==expected
    assert result['metrics']['em']['result']['cases'][0]['status']==expected
    assert result['status']==expected


def test_frozen_executed_driver_is_preferred_to_mutable_source_path(measured_case):
    project,setting,paths=measured_case
    driver=put(project/'producer.py','executed source bytes\n')
    frozen=put(paths['receipt'].parent/'executed_driver.py',driver.read_text())
    rec=em._read(paths['receipt']);rec['inputs_before'][str(driver)]=em._sha(driver)
    rec['executed_driver_copy']=str(frozen);put(paths['receipt'],rec)
    first,views=grade(project,setting)
    assert first['status']=='PASS' and str(frozen) in views and str(driver) not in views
    driver.write_text('later unrelated producer implementation\n')
    second,after=grade(project,setting)
    assert second['status']=='PASS' and views==after


def corrected_alias_case(measured_case):
    project,setting,paths=measured_case
    lines=paths['geometry'].read_text().splitlines();header=json.loads(lines[0]);row=json.loads(lines[1])
    header.update(reader_resistance_offset_ohm=0,zero_resistance='ideal-equivalence')
    row.update(node_a='alias_a',ideal_short=False)
    ideal=dict(row,node_a='a',node_b='alias_a',type='nd',type_long='diffusion',
               resistance_ohm=0,ext_resistance_value=0,ideal_short=True)
    paths['geometry'].write_text('\n'.join(json.dumps(r) for r in (header,row,ideal))+'\n')
    rec=em._read(paths['receipt'])
    raw=Path(setting['spice']);raw.write_text(raw.read_text().replace('1.0005','1'))
    mapping=json.loads(paths['currents'].read_text());mapping.update(row)
    mapping.update(spice_resistance_ohm=1,current_a=.0001)
    paths['currents'].write_text(json.dumps(mapping)+'\n')
    rec['inputs_before'].update({str(p):em._sha(p) for p in (paths['geometry'],raw)})
    rec['outputs'][str(paths['currents'])]=em._sha(paths['currents']);put(paths['receipt'],rec)
    extraction=Path(setting['extraction_receipt']);er=em._read(extraction)
    er['outputs'][str(raw)]=em._sha(raw);put(extraction,er)
    return project,setting,paths


def test_corrected_ideal_alias_uses_emitted_positive_resistor_and_actual_vector(measured_case):
    project,setting,_=corrected_alias_case(measured_case)
    result,_=grade(project,setting)
    assert result['status']=='PASS' and result['graded_segments']==1
    assert result['ideal_connections']['count']==1
    assert result['ideal_connections']['alias_groups']==[['a','alias_a']]
    assert result['non_interconnect_materials']=={'nd':1}


@pytest.mark.parametrize('damage',['wrong-alias','legacy-header','historical-floor','false-ideal'])
def test_corrected_alias_cannot_relabel_wrong_nodes_or_historical_resistance(measured_case,damage):
    project,setting,paths=corrected_alias_case(measured_case)
    rows=[json.loads(line) for line in paths['geometry'].read_text().splitlines()]
    if damage=='wrong-alias':rows[2]['node_a']='unrelated'
    elif damage=='legacy-header':
        rows[0].pop('reader_resistance_offset_ohm');rows[0].pop('zero_resistance')
    elif damage=='false-ideal':rows[2]['ext_resistance_value']=.001
    else:
        raw=Path(setting['spice']);raw.write_text(raw.read_text().replace('R0 a b 1','R0 a b 1.0005'))
        rec=em._read(paths['receipt']);rec['inputs_before'][str(raw)]=em._sha(raw);put(paths['receipt'],rec)
        extraction=Path(setting['extraction_receipt']);er=em._read(extraction)
        er['outputs'][str(raw)]=em._sha(raw);put(extraction,er)
    paths['geometry'].write_text(''.join(json.dumps(row)+'\n' for row in rows))
    rec=em._read(paths['receipt']);rec['inputs_before'][str(paths['geometry'])]=em._sha(paths['geometry']);put(paths['receipt'],rec)
    with pytest.raises(ValueError):grade(project,setting)


def test_ideal_interconnect_does_not_invent_zero_current(measured_case):
    project,setting,paths=corrected_alias_case(measured_case)
    rows=[json.loads(line) for line in paths['geometry'].read_text().splitlines()]
    rows[2].update(type='m2',type_long='metal2')
    paths['geometry'].write_text(''.join(json.dumps(row)+'\n' for row in rows))
    rec=em._read(paths['receipt']);rec['inputs_before'][str(paths['geometry'])]=em._sha(paths['geometry']);put(paths['receipt'],rec)
    result,_=grade(project,setting)
    assert result['status']=='NOT_MEASURED'
    assert 'ideal interconnect current is not measured' in result['unmeasured'][0]['detail']


@pytest.mark.parametrize('damage',[None,'wrong-alias','legacy-reader'])
def test_native_magic_zero_material_artifact_binds_only_real_positive_edges(damage):
    data=json.loads((Path(__file__).parent/'fixtures/native_em_ideal_resistors.json').read_text())
    header,rows=data['header'],data['geometry']
    if damage=='wrong-alias':
        next(row for row in rows if row['ideal_short'])['node_a']='unrelated'
    elif damage=='legacy-reader':
        header.pop('reader_resistance_offset_ohm');header.pop('zero_resistance')
    if damage:
        with pytest.raises(ValueError):em.bind_native_resistors(header,rows,data['spice'])
    else:
        bound=em.bind_native_resistors(header,rows,data['spice'])
        assert sorted(r for _,_,r in bound)==[.0625,.5]
        assert all(not row['ideal_short'] for _,row,_ in bound)
        assert sum(row['ideal_short'] for row in rows)==1


@pytest.mark.parametrize('temperature,scope,expected',[
    (105,'source-rated native temperature','PASS'),
    (125,'numeric current comparison only','NOT_MEASURED'),
    (None,'numeric current comparison only','NOT_MEASURED')])
def test_source_rating_is_distinct_from_bound_native_temperature(
        measured_case,temperature,scope,expected):
    project,setting,paths=measured_case
    paths['log'].write_text((f'Doing analysis at TEMP = {temperature} and TNOM = 27\n'
                             if temperature is not None else 'No native temperature marker\n'))
    rec=em._read(paths['receipt']);rec['outputs'][str(paths['log'])]=em._sha(paths['log'])
    if temperature is not None:
        rec['source_binding']={'conditions':{'temperature_c':temperature}}
    put(paths['receipt'],rec)
    aliases,known=em.material_map(TECH)
    result,_=em.grade_case(project,setting,em.parse_process_limits(TABLE),aliases,known,
                           block='unit',rating_context=em.process_rating_context(TABLE))
    assert result['status']==expected
    assert result['graded_segments']==1 and result['violations']==[]
    context=result['rating_context']
    assert context['source_rating']['duration_years']==11 and context['source_rating']['temperature_c']==105
    assert context['native_temperature_c']==temperature and context['comparison_scope']==scope
    assert 'no temperature/lifetime extrapolation' in context['lifetime_scope']


def test_rating_uses_native_temperature_and_refuses_source_condition_misbinding():
    with pytest.raises(ValueError,match='native temperature differs'):
        em.native_rating_context('Doing analysis at TEMP = 125',em.process_rating_context(TABLE),
                                 {'conditions':{'temperature_c':105}})
    result=em.native_rating_context('',em.process_rating_context(TABLE),{})
    assert result['native_temperature_c'] is None and result['comparison_scope']=='numeric current comparison only'


def transient_case(measured_case,scale):
    import numpy as np
    project,setting,paths=measured_case;work=paths['receipt'].parent
    analysis={'kind':'TRAN','step_s':.001,'stop_s':2,'start_s':0,'temperature_c':105,'window_s':[0,2]}
    raw=work/'tran.raw'
    matrix=np.array([[0,-scale,0],[.1,-.8*scale,0],[1,scale,0],[2,3*scale,0]],dtype='<f8')
    raw.write_bytes(b'Title: native fixture\nPlotname: Transient Analysis\nFlags: real\nNo. Variables: 3\nNo. Points: 4\nVariables:\n0 time time\n1 v(a) voltage\n2 v(b) voltage\nBinary:\n'+matrix.tobytes())
    stats=em.window_statistics(em.NativeRaw(raw),analysis['window_s'],[('a','b',1.0005)])[0]
    mapping=json.loads(paths['currents'].read_text());mapping.pop('current_a');mapping.pop('voltage_v')
    mapping['current_statistics_a']=stats;paths['currents'].write_text(json.dumps(mapping)+'\n')
    settings=put(work/'settings.json',{'analysis':analysis})
    deck=work/'op.sp';deck.write_text('xdut a b unit\n.tran .001 2 0\n.end\n')
    rec=em._read(paths['receipt']);rec.update(analysis=analysis,deck=str(deck))
    rec['inputs_before'].update({str(p):em._sha(p) for p in (settings,deck)})
    rec['outputs'].pop(str(paths['capture']));rec['outputs'].update({str(p):em._sha(p) for p in (raw,paths['currents'])})
    put(paths['receipt'],rec)
    return project,setting,paths,stats


@pytest.mark.parametrize('scale,expected',[(.0001,'PASS'),(.001,'NOT_MEASURED')])
def test_native_transient_current_uses_integrals_and_peak_excess_is_not_lifetime_fail(measured_case,scale,expected):
    project,setting,_,statistics=transient_case(measured_case,scale)
    result,_=grade(project,setting)
    assert result['status']==expected and result['measurement_status']=='PASS'
    assert statistics['avg']==pytest.approx(scale/1.0005)
    assert result['pg_voltage_ranges']['a']['min_v']==-scale
    assert result['pg_voltage_ranges']['a']['max_v']==3*scale
    assert result['feed_voltages']=={'a':3*scale,'b':0.}
    assert result['analysis']['window_s']==[0,2]
    if expected=='NOT_MEASURED':
        assert result['violations']==[]
        assert result['unmeasured'][0]['numeric_peak_comparison']=='ABOVE_DC_TABLE'
        assert result['unmeasured'][0]['current_statistics_a']==statistics


@pytest.mark.parametrize('damage',['statistics','settings','deck','native-failure'])
def test_transient_stats_and_executed_analysis_are_current_and_native_fail_stays_fail(measured_case,damage):
    project,setting,paths,_=transient_case(measured_case,.0001)
    rec=em._read(paths['receipt'])
    if damage=='statistics':
        row=json.loads(paths['currents'].read_text());row['current_statistics_a']['peak_abs']=0
        paths['currents'].write_text(json.dumps(row)+'\n');rec['outputs'][str(paths['currents'])]=em._sha(paths['currents'])
    elif damage=='settings':rec['analysis']['window_s']=[.1,2]
    elif damage=='deck':
        deck=Path(rec['deck']);deck.write_text(deck.read_text().replace('.tran .001 2 0','.tran .002 2 0'))
        rec['inputs_before'][str(deck)]=em._sha(deck)
    else:
        paths['log'].write_text(';;RESIDUAL_FAIL actual native refusal\n')
        rec['outputs'][str(paths['log'])]=em._sha(paths['log'])
    put(paths['receipt'],rec)
    if damage=='native-failure':assert grade(project,setting)[0]['status']=='FAIL'
    else:
        with pytest.raises(ValueError):grade(project,setting)


@pytest.mark.parametrize('wrong_gds',[False,True])
def test_partition_consumer_uses_same_layout_native_drc(measured_case,wrong_gds):
    project,setting,paths=measured_case
    rows=paths['geometry'].read_text().splitlines();row=json.loads(rows[1]);row['width_grid']=20
    row['width_um']=20*json.loads(rows[0])['scale_um']
    paths['geometry'].write_text(rows[0]+'\n'+json.dumps(row)+'\n')
    mapping=json.loads(paths['currents'].read_text());mapping.update(row)
    paths['currents'].write_text(json.dumps(mapping)+'\n')
    rec=em._read(paths['receipt']);rec['inputs_before'][str(paths['geometry'])]=em._sha(paths['geometry'])
    rec['outputs'][str(paths['currents'])]=em._sha(paths['currents']);put(paths['receipt'],rec)
    pv=put(project/'pv.json',{'metrics':{'drc':{'executed':True,'verdict':'PASS','returncode':0,
        'native':{'block':'unit','gds_sha256':'wrong' if wrong_gds else em._sha(paths['gds']),
                  'engines':{'native':{'judge':'PASS','metric':{'status':'MEASURED','value':0}}}}}}})
    setting['pv_receipt']=str(pv)
    result,views=grade(project,setting)
    assert result['status']==('NOT_MEASURED' if wrong_gds else 'PASS')
    assert result['native_drc_bound_partitions']==(0 if wrong_gds else 1)
    assert str(pv) in views


@pytest.mark.parametrize('damage',['capture','source','gds','width','vector'])
def test_changed_or_misbound_native_data_cannot_pass(measured_case,damage):
    project,setting,paths=measured_case
    if damage in ('capture','source','gds'):
        paths[damage].write_text(paths[damage].read_text()+'\nchanged')
    elif damage=='width':
        rows=paths['geometry'].read_text().splitlines();row=json.loads(rows[1]);row['width_grid']*=2
        paths['geometry'].write_text(rows[0]+'\n'+json.dumps(row)+'\n')
        rec=em._read(paths['receipt']);rec['inputs_before'][str(paths['geometry'])]=em._sha(paths['geometry']);put(paths['receipt'],rec)
    else:
        row=json.loads(paths['currents'].read_text());row.update(voltage_vectors=['b','b'],voltage_v=[0,0],current_a=0)
        paths['currents'].write_text(json.dumps(row)+'\n');rec=em._read(paths['receipt']);rec['outputs'][str(paths['currents'])]=em._sha(paths['currents']);put(paths['receipt'],rec)
    with pytest.raises(ValueError):grade(project,setting)


def test_native_residual_failure_keeps_fail_precedence(measured_case):
    project,setting,paths=measured_case
    paths['log'].write_text(';;RESIDUAL_FAIL native equations invalid\n')
    paths['source'].write_text('changed source')
    rec=em._read(paths['receipt']);rec['outputs'][str(paths['log'])]=em._sha(paths['log']);put(paths['receipt'],rec)
    result,_=grade(project,setting)
    assert result['status']=='FAIL'


def compressed_case(measured_case,kind='OP'):
    if kind=='TRAN':
        project,setting,paths,_=transient_case(measured_case,.0001)
        plain=paths['receipt'].parent/'tran.raw'
    else:
        import numpy as np
        project,setting,paths=measured_case;plain=paths['capture']
        plain.write_bytes(b'Title: native fixture\nPlotname: Operating Point\nFlags: real\nNo. Variables: 2\n'
                          b'No. Points: 1\nVariables:\n0 v(a) voltage\n1 v(b) voltage\nBinary:\n'
                          +np.array([.0001,0],dtype='<f8').tobytes())
        rec=em._read(paths['receipt']);rec['outputs'][str(plain)]=em._sha(plain);put(paths['receipt'],rec)
    before,_=grade(project,setting);original=plain.read_bytes();stored=plain.with_name(plain.name+'.gz')
    stored.write_bytes(gzip.compress(original,mtime=0))
    rec=em._read(paths['receipt']);rec['argv']=['native-ngspice','-b','-r',str(plain),str(plain.parent/'op.sp')]
    rec['native_raw']={'executed_path':str(plain),'stored_path':str(stored),'encoding':'gzip',
                       'sha256':em._sha(stored),'raw_sha256':hashlib.sha256(original).hexdigest(),'raw_bytes':len(original)}
    rec['outputs'].pop(str(plain));rec['outputs'][str(stored)]=em._sha(stored)
    plain.unlink();put(paths['receipt'],rec)
    return project,setting,paths,stored,before


@pytest.mark.parametrize('kind',['OP','TRAN'])
def test_actual_em_consumer_plain_and_gzip_have_identical_electrical_results(measured_case,kind):
    project,setting,_,stored,before=compressed_case(measured_case,kind)
    result,views=grade(project,setting)
    assert result==before and result['status']=='PASS'
    assert views[str(stored)]['sha256']==em._sha(stored)


@pytest.mark.parametrize('damage',['compressed_changed','raw_sha','raw_bytes','metadata_absent','wrong_kind',
                                  'wrong_argv','ambiguous_plain','relabelled_stored_path','truncated_gzip'])
def test_real_gzip_consumer_refuses_changed_missing_or_relabelled_native_capture(measured_case,damage):
    project,setting,paths,stored,_=compressed_case(measured_case)
    rec=em._read(paths['receipt'])
    if damage=='compressed_changed':stored.write_bytes(stored.read_bytes()+b'changed')
    elif damage=='raw_sha':rec['native_raw']['raw_sha256']='0'*64
    elif damage=='raw_bytes':rec['native_raw']['raw_bytes']+=1
    elif damage=='metadata_absent':rec.pop('native_raw')
    elif damage=='wrong_kind':rec['native_raw']['executed_path']=str(stored.parent/'tran.raw')
    elif damage=='wrong_argv':rec['argv'][3]=str(stored.parent/'unrelated.raw')
    elif damage=='ambiguous_plain':
        plain=stored.with_suffix('');plain.write_bytes(gzip.decompress(stored.read_bytes()))
        rec['outputs'][str(plain)]=em._sha(plain)
    elif damage=='relabelled_stored_path':
        other=stored.parent/'copied.raw.gz';other.write_bytes(stored.read_bytes())
        rec['native_raw']['stored_path']=str(other);rec['outputs'][str(other)]=em._sha(other)
    else:
        stored.write_bytes(stored.read_bytes()[:-5])
        rec['outputs'][str(stored)]=rec['native_raw']['sha256']=em._sha(stored)
    put(paths['receipt'],rec)
    with pytest.raises((ValueError,OSError)):grade(project,setting)


def test_actual_native_failure_remains_fail_even_if_compressed_capture_is_missing(measured_case):
    project,setting,paths,stored,_=compressed_case(measured_case)
    stored.unlink();paths['log'].write_text(';;RESIDUAL_FAIL retained native electrical failure\n')
    rec=em._read(paths['receipt']);rec['outputs'][str(paths['log'])]=em._sha(paths['log']);put(paths['receipt'],rec)
    assert grade(project,setting)[0]['status']=='FAIL'


@pytest.mark.parametrize('record',[{'result':'REFUSED'},
                                  {'result':'OK','netlist_content_sha256':'older-source'}])
def test_known_layout_source_disagreement_uses_existing_producer_identity(measured_case,record):
    project,setting,paths=measured_case
    put(paths['source'].parent/'layout_provenance.json',record)
    with pytest.raises(ValueError,match='layout/source disagreement'):
        grade(project,setting)


@pytest.mark.parametrize('residual,expected',[(False,'NOT_MEASURED'),(True,'FAIL')])
def test_execution_bound_is_incomplete_unless_native_equations_already_failed(measured_case,residual,expected):
    project,setting,paths=measured_case
    if residual:paths['log'].write_text(';;RESIDUAL_FAIL native equations invalid\n')
    rec=em._read(paths['receipt']);rec.update(returncode=124,status='FAIL')
    rec['outputs'][str(paths['log'])]=em._sha(paths['log']);put(paths['receipt'],rec)
    paths['capture'].unlink()
    result,_=grade(project,setting)
    assert result['status']==expected


@pytest.mark.parametrize('em_status,expected',[('PASS','NOT_MEASURED'),('FAIL','FAIL')])
def test_a16_integrates_native_em_without_promoting_missing_mission(tmp_path,monkeypatch,em_status,expected):
    import analog_native_physical as physical
    monkeypatch.setattr(em,'run',lambda *a,**k:{'status':em_status,'outputs':[],'native_inputs':{},'cases':[]})
    result=physical._reliability(tmp_path,'unit','native','','process',{'em':{'cases':[{'receipt':'native'}]},
        '_features':{'requires_thermal':False,'requires_ir':False,'requires_aging':False}})
    assert result['status']==expected
    assert result['metrics']['em']['status']==em_status
