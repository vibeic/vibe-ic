"""Packing, source-derived high-plane channels and local routing controls."""
import _plugin_tree
import analog_a5_layout_emit as a
from test_analog_a5_shared_escape import capacitor, geo


def test_compact_shelves_backfill_earlier_free_space():
    ds = []
    for name, width, height in [('a', 1200, 1000), ('b', 1200, 1000),
                                 ('c', 600, 800), ('d', 600, 800)]:
        d = capacitor(name)
        d['dev']['class'] = 'mosfet'
        d['bbox'] = (0, 0, width, height)
        d['cell']['delta'] = (0, 0)
        d['access_pitch'] = 69
        for g in d['groups']:
            g['level'] = 2
        ds.append(d)
    rows, _, _, _ = a._place_shared_rows(ds, ['top', 'bottom'], geo(), None,
                                         31, (), reserve_bus=False, compact_rows=True)
    assert len(rows) == 2
    assert sorted(d['dev']['name'] for row in rows for d in row) == ['a', 'b', 'c', 'd']
    assert all(len(row) == 2 for row in rows)
    assert [d['right_lo'] - d['box_x'] for d in ds] == [1200, 1200, 600, 600]


def test_high_plane_channel_clears_both_actual_stack_envelopes():
    g = geo()
    first, second = capacitor('a'), capacitor('b', ('other', 'bottom'))
    gap = a._access_gap(first, second, g)
    left, right = a.Plan(), a.Plan()
    a._via_stack(left, 'a', 400, 0, 7, g, top=3)
    a._via_stack(right, 'b', gap-400, 0, 7, g, top=3)
    for one in left.shapes:
        for two in right.shapes:
            if one['layer'] == two['layer'] and one['layer'].startswith('metal'):
                assert a.box_separation(one['box'], two['box']) >= g.metal_space(one['layer'], one['box'], two['box'])
    assert gap < 1600


def test_local_m3_leg_uses_m2_overpass_at_a_foreign_escape():
    g = geo()
    plan = a.Plan()
    sites = a.Sites([], g)
    plan.sites = sites
    plan.paint('foreign', 'metal3', -200, 985, 200, 1015)
    plan.m3_escape_obstacles = [('foreign', (-200, 985, 200, 1015))]
    a._route_m3_leg(plan, 'own', 0, 0, 2000, g, sites)
    assert any(s['net'] == 'own' and s['layer'] == 'metal2' and s['box'][1] < 1000 < s['box'][3] for s in plan.shapes)
    for one in plan.shapes:
        for two in plan.shapes:
            if one['net'] != two['net'] and one['layer'] == two['layer']:
                assert a.box_separation(one['box'], two['box']) >= g.metal_space(one['layer'], one['box'], two['box'])


def test_complementary_switches_and_inverters_stay_electrically_local():
    def mos(name, nets):
        return {'dev': {'name': name, 'class': 'mosfet', 'nets': nets}}
    ds = [mos('tn', ['a', 'ck', 'b', 'vss']), mos('tp', ['b', 'ckb', 'a', 'vdd']),
          mos('in', ['out', 'in', 'vss', 'vss']), mos('ip', ['out', 'in', 'vdd', 'vdd'])]
    assert a._complementary_groups(ds) == [['tn', 'tp'], ['in', 'ip']]
