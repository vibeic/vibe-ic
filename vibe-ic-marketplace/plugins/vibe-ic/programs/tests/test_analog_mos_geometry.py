"""Calibrated finger geometry follows selected native model source, not family names."""
import copy

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import analog_mos_geometry as mos


@pytest.fixture
def context(tmp_path):
    library=tmp_path/'corners.lib';devices=tmp_path/'devices.lib'
    library.write_text('* Valid range for model: L = (0.1 - 5)um\n* W = (0.2 - 10)um\n'
        '.lib ordinary\n.include "devices.lib"\n.endl ordinary\n'
        '.lib foreign\n* Valid range for model: L = (0.1 - 2)um\n* W = (0.2 - 1)um\n.include "absent.lib"\n.endl foreign\n')
    devices.write_text('.subckt fet d g s b\n+ w=2u l=1u ng=1 m=1\n'
        'Ncore d g s b intrinsic w=w l=l nf=\'ng\' mult=\'m\'\n.ends fet\n')
    return {'model_lib':str(library),'typ_section':'ordinary','role_models':{'nmos':'fet'},
            'geometry_units':{'nmos':'metric'}}, devices


def ir(width=16, ng=None):
    device={'name':'signal_device','role':'nmos','nets':['out','in','vss','vss'],'w':width,'l':1.}
    if ng is not None:device['ng']=ng
    return {'block':'neutral_amplifier','block_type':'ota','topology':'neutral stage',
            'ports':['out','in','vss'],'devices':[device]}


def test_selected_primary_source_bounds_choose_minimum_count_and_keep_ir_total_width(context):
    pdk,_path=context;original=ir();before=copy.deepcopy(original)
    ctx=mos.discover_context(pdk)
    assert ctx['nmos']['bounds']=={'w':(.2,10.),'l':(.1,5.)}
    effective,records=mos.apply_fingers(original,{},ctx)
    assert effective=={'signal_device':{'ng':2}}
    assert records[0]['total_width_um']==16 and records[0]['finger_width_um']==8
    assert records[0]['ng']==2 and not records[0]['explicit']
    assert original==before and len(ctx['nmos']['inputs'])==2
    text=a3.render_netlist(original,pdk,[],{})
    assert 'w=16u l=1u ng=2' in text and 'm=' not in text


def test_count_can_exceed_minimum_for_exact_native_grid_and_m_is_independent(context):
    pdk,_path=context;design=ir(28,4);design['devices'][0]['m']=3
    effective,records=mos.apply_fingers(design,{},mos.discover_context(pdk))
    assert effective['signal_device']['ng']==4 and records[0]['finger_width_um']==7
    text=a3.render_netlist(design,pdk,[],{})
    assert 'w=28u l=1u m=3 ng=4' in text


@pytest.mark.parametrize('count',[0,-1,1.5,True,'2'])
def test_invalid_explicit_count_refuses(context,count):
    pdk,_path=context
    with pytest.raises(mos.GeometryDomainError,match='positive integer'):
        mos.apply_fingers(ir(8,count),{},mos.discover_context(pdk))


@pytest.mark.parametrize('width,count',[(16,1),(.3,2),(512,1)])
def test_explicit_count_must_keep_actual_per_finger_width_inside_source_range(context,width,count):
    pdk,_path=context
    with pytest.raises(mos.GeometryDomainError,match='calibrated model w range'):
        mos.apply_fingers(ir(width,count),{},mos.discover_context(pdk))


def test_resolved_geometry_controls_count_not_unresolved_literal(context):
    pdk,_path=context
    values,rows=mos.apply_fingers(ir(8),{'signal_device':{'w':32}},mos.discover_context(pdk))
    assert values['signal_device']=={'w':32,'ng':4} and rows[0]['finger_width_um']==8


def test_discovered_nf_alias_is_emitted_without_guessing_ng(context):
    pdk,path=context
    path.write_text(path.read_text().replace('ng=1','nf=1').replace("nf='ng'","nf='nf'"))
    assert 'nf=2' in a3.render_netlist(ir(),pdk,[],{})
    assert 'ng=' not in a3.render_netlist(ir(),pdk,[],{})


@pytest.mark.parametrize('mutation',['undeclared','unused','double_division','different_device','mixed_device',
    'duplicate_width','duplicate_count','conflicting_count_aliases'])
def test_unsupported_or_unused_wrapper_parameter_cannot_silently_accept_ng(context,mutation):
    pdk,path=context;text=path.read_text()
    if mutation=='undeclared':text=text.replace('ng=1 ','').replace("nf='ng'",'nf=1')
    elif mutation=='unused':text=text.replace("nf='ng'",'nf=1')
    elif mutation=='double_division':text=text.replace('w=w','w=\'w/ng\'')
    elif mutation=='different_device':text=text.replace('w=w','w=1u').replace('.ends fet','Nother d g s b intrinsic w=w nf=1\n.ends fet')
    elif mutation=='mixed_device':text=text.replace('.ends fet','Nother d g s b intrinsic w=w nf=1\n.ends fet')
    elif mutation=='duplicate_width':text=text.replace('w=w','w=w w=2*w')
    elif mutation=='duplicate_count':text=text.replace("nf='ng'","nf='ng' nf=1")
    else:text=text.replace("nf='ng'","nf='ng' ng=1")
    path.write_text(text)
    with pytest.raises(mos.GeometryDomainError,match='supported finger|unsupported wrapper'):
        a3.render_netlist(ir(8,2),pdk,[],{})


def test_multiple_native_cards_require_the_same_unique_forwarded_geometry(context):
    pdk,path=context
    path.write_text(path.read_text().replace('.ends fet',
        'Nother d g s b intrinsic w="w" nf="ng"\n.ends fet'))
    assert mos.discover_context(pdk)['nmos']['finger_parameter']=='ng'
    assert 'w=16u l=1u ng=2' in a3.render_netlist(ir(),pdk,[],{})


def test_comment_cannot_mint_finger_parameter(context):
    pdk,path=context
    path.write_text('.subckt fet d g s b w=2u l=1u ; ng=1 is only prose\n'
                    'Ncore d g s b intrinsic w=w l=l nf=1\n.ends fet\n')
    with pytest.raises(mos.GeometryDomainError,match='supported finger'):
        a3.render_netlist(ir(8,2),pdk,[],{})


def test_no_source_domain_keeps_default_count_absent_and_rendering_unchanged(context):
    pdk,_path=context
    library=__import__('pathlib').Path(pdk['model_lib'])
    library.write_text('.lib ordinary\n.include "devices.lib"\n.endl ordinary\n')
    ctx=mos.discover_context(pdk);effective,records=mos.apply_fingers(ir(),{},ctx)
    assert effective=={} and records==[]
    assert 'ng=' not in a3.render_netlist(ir(),pdk,[],{})


def test_conflicting_selected_source_domains_refuse(context):
    pdk,path=context
    path.write_text('* Valid range for model: L = (0.1 - 5)um\n* W = (0.2 - 12)um\n'+path.read_text())
    with pytest.raises(mos.GeometryDomainError,match='ambiguous source calibrated w'):
        mos.discover_context(pdk)


def test_companion_library_domain_cannot_refuse_or_redefine_selected_mos(context):
    pdk,path=context
    companion=path.parent/'passives.lib'
    companion.write_text('* Valid range for model: W = (1 - 100)um\n'
                         '.subckt passive a b w=1u l=1u\nRbody a b 1\n.ends passive\n')
    pdk['deck_loads']=[(pdk['model_lib'],'ordinary'),(str(companion),None)]
    assert mos.discover_context(pdk)['nmos']['bounds']['w']==(.2,10.)


def test_project_relative_selected_library_is_discovered_from_destination(context,tmp_path):
    pdk,path=context
    (tmp_path/'input').mkdir()
    destination=tmp_path/'phase3/analog/neutral_amplifier'
    destination.mkdir(parents=True)
    pdk['model_lib']='corners.lib'
    assert 'w=16u l=1u ng=2' in a3.render_netlist(ir(),pdk,[],{},destination)


def test_a2_typed_ng_is_mos_only_and_integer_and_supports_new_field():
    design=ir();a2.apply_sizing_inputs({'device_parameters':{'signal_device':{'ng':2}}},{},{},[],design['devices'],[],{},{})
    assert design['devices'][0]['ng']==2 and isinstance(design['devices'][0]['ng'],int)
    for role,count in (('cap',2),('nmos',1.5),('nmos',True)):
        design=ir();design['devices'][0]['role']=role
        with pytest.raises(a2.SizingInputsInvalid):
            a2.apply_sizing_inputs({'device_parameters':{'signal_device':{'ng':count}}},{},{},[],design['devices'],[],{},{})


@pytest.mark.parametrize('parameters',[{'w':32,'ng':4},{'ng':2}])
def test_a2_native_geometry_bounds_apply_to_each_finger_regardless_of_input_order(parameters):
    design=ir()
    a2.apply_sizing_inputs({'device_parameters':{'signal_device':parameters}},
        {},{},[],design['devices'],[],{'nmos':{'min_width_um':.2}},
        {'nmos':{'max_width_um':10}})
    device=design['devices'][0]
    assert .2<=device['w']/device['ng']<=10
    assert device['w']==parameters.get('w',16)


@pytest.mark.parametrize('width,count',[(16,1),(.3,2)])
def test_a2_count_only_change_still_checks_existing_native_finger_width(width,count):
    design=ir(width)
    with pytest.raises(a2.SizingInputsInvalid,match='PDK minimum|PDK maximum'):
        a2.apply_sizing_inputs({'device_parameters':{'signal_device':{'ng':count}}},
            {},{},[],design['devices'],[],{'nmos':{'min_width_um':.2}},
            {'nmos':{'max_width_um':10}})


def test_legacy_params_cannot_double_or_override_typed_count(context):
    pdk,_path=context;design=ir(8,2);design['devices'][0]['params']={'ng':4}
    with pytest.raises(mos.GeometryDomainError,match='duplicate finger'):
        a3.render_netlist(design,pdk,[],{})
