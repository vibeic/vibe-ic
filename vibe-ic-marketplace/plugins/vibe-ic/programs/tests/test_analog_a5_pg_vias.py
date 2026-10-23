from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
import analog_a5_layout_emit as layout


def setup():
    facts=layout.PdkFacts()
    facts.tech_lef=layout.tech_lef_layers('\n'.join(
        f'LAYER Metal{i}\n TYPE ROUTING ;\n DIRECTION {"VERTICAL" if i%2==0 else "HORIZONTAL"} ;\nEND Metal{i}'
        for i in range(1,8)))
    geo=SimpleNamespace(wire={i:30 for i in range(1,8)},lam=100,
        via_pad={i:10 for i in range(1,7)},long_half={i:20 for i in range(1,7)},
        rules_via_space=lambda k:15)
    return facts,geo


def test_optional_pg_landing_count_changes_only_declared_rails():
    facts,geo=setup()
    default,_=layout.pin_spec_for(['supply','return','signal'],{'vdd':'supply','vss':'return'}, {},facts,geo)
    changed,_=layout.pin_spec_for(['supply','return','signal'],{'vdd':'supply','vss':'return'}, {},facts,geo,pg_via_cuts=2)
    assert default['ports']['supply']['cuts']==1
    assert changed['ports']['supply']['cuts']==2
    assert changed['ports']['return']['cuts']==2
    assert changed['ports']['signal']==default['ports']['signal']


def test_requested_cuts_are_separate_spaced_native_landing_rectangles():
    _,geo=setup()
    paint,bars=layout._pin_stack_boxes(100,200,2,6,geo,2)
    for k in range(2,6):
        cuts=[box for layer,box in paint if layer==f'via{k}']
        assert len(cuts)==2
        assert cuts[1][0]-cuts[0][2]>=geo.rules_via_space(k)
        for box in cuts:
            assert bars[k][0]<=box[0]<box[2]<=bars[k][2]
            assert bars[k+1][0]<=box[0]<box[2]<=bars[k+1][2]


@pytest.mark.parametrize('value',[0,-1,True,2.5,'2'])
def test_bad_pg_landing_count_refused(value):
    facts,geo=setup()
    with pytest.raises(ValueError,match='positive integer'):
        layout.pin_spec_for(['a'],{'vdd':'a'}, {},facts,geo,pg_via_cuts=value)


def test_pg_bus_trunk_width_keeps_local_signal_width_and_native_clearance():
    facts,geo=setup()
    spec,_=layout.pin_spec_for(['supply','return','signal'],{'vdd':'supply','vss':'return'}, {},facts,geo)
    before=dict(geo.wire)
    assert layout._pg_route_widths(spec,geo,None)=={}
    widths=layout._pg_route_widths(spec,geo,3.01)
    assert widths=={'supply':{2:302,3:302},'return':{2:302,3:302}}
    assert geo.wire==before and 'signal' not in widths
    offsets=layout._track_offsets(['signal','supply','return','signal'],100,
                                  {n:v[3]-geo.wire[3] for n,v in widths.items()})
    actual=[30,302,302,30]
    for i in range(1,len(offsets)):
        assert offsets[i]-offsets[i-1]-(actual[i]+actual[i-1])/2==100-30
    assert layout._track_offsets(['signal','supply','return'],100,{})==[100,200,300]


@pytest.mark.parametrize('value',[0,-1,True,float('nan'),float('inf'),'3'])
def test_bad_pg_wire_width_refused(value):
    _,geo=setup()
    with pytest.raises(layout.Refusal,match='finite positive'):
        layout._pg_route_widths({'ports':{'a':{'rail':True}}},geo,value)


def test_pg_wire_width_does_not_guess_rails_from_names():
    _,geo=setup()
    with pytest.raises(layout.Refusal,match='topology-declared'):
        layout._pg_route_widths({'ports':{'vdd':{'rail':False}}},geo,3)


def cut_facts():
    facts,geo=setup()
    geo.rules={'via_width_um':{i:.2 for i in range(1,7)}}
    facts.tech_lef=[]
    for i in range(1,8):
        facts.tech_lef.append({'name':f'Metal{i}','type':'ROUTING',
                              'direction':'VERTICAL' if i%2==0 else 'HORIZONTAL','dc_density':2})
        if i<7:facts.tech_lef.append({'name':f'Via{i}','type':'CUT','dc_density':.4})
    return facts,geo


def test_lef_cut_density_uses_declared_cut_area_instead_of_per_cut_shortcut():
    facts,geo=cut_facts()
    spec={'specs':[{'name':'load','max':1.,'unit':'mA'}]}
    out,_=layout.pin_spec_for(['supply'],{'vdd':'supply'},spec,facts,geo)
    # PDK cut side floor .2um => area .04um²; .4mA/um² permits .016mA/cut.
    assert out['ports']['supply']['cuts']==63
    assert all(r['limit_mA']==.016 for r in out['ports']['supply']['em']['cut_rule'])
    assert all(r['unit']=='mA/um^2' for r in out['ports']['supply']['em']['cut_rule'])


def test_cut_area_is_not_guessed_from_a_large_painted_contact_enclosure():
    facts,geo=cut_facts()
    geo.rules={};geo.via_pad={i:500 for i in range(1,7)}
    out,_=layout.pin_spec_for(['supply'],{'vdd':'supply'},
                              {'specs':[{'name':'load','max':1.,'unit':'mA'}]},facts,geo)
    assert out['ports']['supply']['em']['result']=='NOT_MEASURED'
    assert 'area floor absent' in out['ports']['supply']['em']['cut_sizing_reason']
    assert out['ports']['supply']['cuts']==1


def test_explicit_primary_per_via_limits_preserve_three_cut_geometry():
    facts,geo=cut_facts()
    facts.cut_current_source={'path':'foundry-process.pdf','sha256':'source-hash'}
    facts.cut_current_limits={f'via{i}':{'value_mA':'0.4','source_rule':{'unit':'mA/Via','value':'0.4'}}for i in range(1,7)}
    out,basis=layout.pin_spec_for(['supply'],{'vdd':'supply'},
                                 {'specs':[{'name':'load','max':1.,'unit':'mA'}]},facts,geo)
    assert out['ports']['supply']['cuts']==3
    assert basis['cut_current_limits_source']==facts.cut_current_source
    assert all(r['source']==facts.cut_current_source and r['limit_mA']==.4
               for r in out['ports']['supply']['em']['cut_rule'])


def test_nonpositive_primary_cut_limit_refuses_instead_of_sizing():
    facts,geo=cut_facts()
    facts.cut_current_limits={'via2':{'value_mA':'0','source_rule':{'unit':'mA/Via','value':'0'}}}
    with pytest.raises(layout.Refusal,match='nonpositive cut current'):
        layout.pin_spec_for(['supply'],{'vdd':'supply'},
                            {'specs':[{'name':'load','max':1.,'unit':'mA'}]},facts,geo)
