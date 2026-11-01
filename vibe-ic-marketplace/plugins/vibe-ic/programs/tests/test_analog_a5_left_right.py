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
    ds=fixture_devices(caps=13);before=deepcopy([d['dev'] for d in ds])
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


def assert_regional_rails_clear(descriptions, geometry):
    """Check complete horizontal landing envelopes on their reported plane."""
    for i, first in enumerate(descriptions):
        assert first['rail_level'] == 4
        for second in descriptions[i+1:]:
            if first['region'] == second['region']:
                continue
            assert first['rail_level'] == second['rail_level']
            level = first['rail_level']
            layer = f'metal{level}'
            stack = a.Plan()
            a._via_stack(stack, '<rail>', 0, 0, level-1, geometry,
                         top=level+1, horizontal=True)
            pads = [r['box'] for r in stack.shapes if r['layer'] == layer]
            hx = max(abs(b[j]) for b in pads for j in (0, 2))
            hy = max(geometry.wire[level]//2,
                     max(abs(b[j]) for b in pads for j in (1, 3)))
            for net, (lo, hi) in first['rail_intervals_lambda'].items():
                for other, (ol, oh) in second['rail_intervals_lambda'].items():
                    y, oy = first['rails_lambda'][net], second['rails_lambda'][other]
                    if net == other and y == oy:
                        continue
                    box = (lo-hx, y-hy, hi+hx, y+hy)
                    other_box = (ol-hx, oy-hy, oh+hx, oy+hy)
                    assert a.box_separation(box, other_box) >= geometry.metal_space(
                        layer, box, other_box)


def test_cross_region_M4_intervals_keep_pitch_or_join_the_same_net():
    _,_,_,desc=a._place_left_right_rows(fixture_devices(),['top','bottom'],geo(),None,260,())
    assert_regional_rails_clear(desc, geo())


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
