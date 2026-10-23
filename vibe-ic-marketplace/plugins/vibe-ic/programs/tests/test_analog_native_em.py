from fractions import Fraction
import json
from pathlib import Path
import struct

import pytest
import _plugin_tree  # noqa: F401
import analog_native_em as em
import _analog_a8_extraction_wrapper as wrapper


TABLE='''2.15 Maximum Current Densities
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
    log=put(work/'native.log','Doing analysis at TEMP = 27\nNo. of Data Rows : 1\n')
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
    return em.grade_case(project,setting,em.parse_process_limits(TABLE),aliases,known,block='unit')


def test_real_consumer_recomputes_native_current_and_pg_ranges(measured_case):
    project,setting,_=measured_case
    result,views=grade(project,setting)
    assert result['status']=='PASS' and result['graded_segments']==1
    assert result['pg_voltage_ranges']['a']=={'min_v':0.,'max_v':.0001,'sampled_endpoints':2}
    assert result['feed_voltages']=={'a':.0001,'b':0.}
    assert str(project/'phase3/analog/unit/unit.gds') in views


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
