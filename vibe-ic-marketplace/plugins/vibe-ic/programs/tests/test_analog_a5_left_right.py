"""Focused geometry controls for the normal A5 left/right placement option."""
from copy import deepcopy
import pytest
import _plugin_tree
import analog_a5_layout_emit as a
import analog_native_physical as physical
from test_analog_a5_shared_escape import capacitor, geo


def fixture_devices(caps=7, mos=3):
    ds = [capacitor('c'+str(i)) for i in range(caps)]
    for i in range(mos):
        d = capacitor('m'+str(i));d['dev']['class']='mosfet';d['access_pitch']=69
        for g in d['groups']:g['level']=2
        ds.append(d)
    return ds


def test_regions_are_left_right_and_cap_row_chunks_keep_local_shared_owners():
    ds=fixture_devices();before=deepcopy([d['dev'] for d in ds])
    rows,rails,bus,desc=a._place_left_right_rows(ds,['top','bottom'],geo(),None,260,())
    assert [d['dev'] for d in ds]==before
    cap=[d for d in ds if d['placement_region']=='cmim'];mos=[d for d in ds if d['placement_region']=='ota']
    assert max(d['right_lo'] for d in cap)<min(d['box_x'] for d in mos)
    assert len([r for r in desc if r['region']=='cmim'])==2
    for row in rows:
        names={d['dev']['name'] for d in row}
        for d in row:
            for g in d['groups']:
                if 'shared_escape_owner' in g:assert g['shared_escape_owner'] in names
        if len(row)==1:assert all('shared_escape_owner' not in g for g in row[0]['groups'])
    assert min(d['box_y'] for d in mos)<max(d['box_y'] for d in cap)


def test_cross_region_M2_intervals_keep_pitch_or_join_the_same_net():
    _,_,_,desc=a._place_left_right_rows(fixture_devices(),['top','bottom'],geo(),None,260,())
    g=geo();clearance=2*max(g.long_half[2],g.wire[2]//2)+g.metal_space('metal2')
    cap=[r for r in desc if r['region']=='cmim'];mos=[r for r in desc if r['region']=='ota']
    for left in cap:
        for right in mos:
            for n,(lo,hi) in left['rail_intervals_lambda'].items():
                for other,(ol,oh) in right['rail_intervals_lambda'].items():
                    y,oy=left['rails_lambda'][n],right['rails_lambda'][other]
                    if n==other and y==oy:continue
                    assert max(lo-oh,ol-hi,0)>=clearance or abs(y-oy)>=clearance


def test_matching_groups_are_not_split_between_rows_or_regions():
    ds=fixture_devices(7,4)
    rows,_,_,_=a._place_left_right_rows(ds,['top','bottom'],geo(),None,260,[('m0','m3')])
    pair=[d for d in ds if d['dev']['name'] in ('m0','m3')]
    assert pair[0]['row']==pair[1]['row']
    assert pair[0]['placement_region']==pair[1]['placement_region']=='ota'
    with pytest.raises(a.Refusal,match='matching unit spans'):
        a._place_left_right_rows(fixture_devices(),['top','bottom'],geo(),None,260,[('c0','m0')])


def test_normal_A11_forwards_left_right_and_shared_options(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(physical,'_settings',lambda *args:{'shared_capacitor_escapes':True,'left_right_regions':True})
    def run(program,argv,**kwargs):calls.append(argv);return {'returncode':127}
    physical.run_step('A11',tmp_path,{'name':'unit'},{'pdk':'ihp-sg13g2'},run)
    assert '--left-right-regions' in calls[0]
    assert '--shared-capacitor-escapes' in calls[0]


def test_undersized_target_keeps_complete_regions_and_exposes_overflow():
    ds=fixture_devices(2,1)
    rows,rails,_,desc=a._place_left_right_rows(ds,['top','bottom'],geo(),None,40,())
    assert sum(len(row) for row in rows)==3
    assert len(rows)==len(rails)==len(desc)
    assert max(row['column_lambda'][1] for row in desc)>4000
    assert all(d['dev']['name'] in {n for row in desc for n in row['devices']} for d in ds)
