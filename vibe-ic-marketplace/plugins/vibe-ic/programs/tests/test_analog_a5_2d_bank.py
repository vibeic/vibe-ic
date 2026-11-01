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
    plan.paint('foreign', 'metal3', 800, 985, 1200, 1015)
    plan.m3_escape_obstacles = [('foreign', (800, 985, 1200, 1015))]
    a._route_m3_leg(plan, 'own', 1000, 0, 2000, g, sites)
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


def test_overpass_can_land_on_m4_beyond_a_blocked_m3_rail_endpoint():
    g = geo()
    plan = a.Plan()
    sites = a.Sites([], g)
    plan.sites = sites
    plan.paint('own', 'metal4', 500, 985, 1500, 1015)
    plan.paint('foreign', 'metal3', 800, 985, 1200, 1015)
    plan.m3_escape_obstacles = [('foreign', (800, 985, 1200, 1015))]
    handled = a._route_m3_leg(plan, 'own', 1000, 1000, 0, g, sites)
    assert handled
    assert any(s['net'] == 'own' and s['layer'] == 'via3' and abs(s['box'][0]-1000) >= 200 for s in plan.shapes)


def test_body_exit_plane_keeps_same_net_notches_illegal():
    import pytest
    g = geo()
    native = [{'net': '<device body>', 'layer': 'metal1',
               'comp': ('body', 0), 'lcomp': ('body', 'metal1', 0),
               'box': (980, 980, 1020, 1020)}]
    plan = a.Plan()
    sites = a.Sites(native, g)
    plan.sites = sites
    plan.paint('vss', 'metal3', 800, 935, 848, 967)
    with pytest.raises(a.Refusal, match='body exit path'):
        a._via_stack(plan, 'vss', 1000, 1000, 1, g, top=3, sites=sites,
                     friendly=('body', 0), exit_path=(400, 1000, 15), search_lambda=0)
    a._via_stack(plan, 'vss', 1000, 1000, 1, g, top=2, sites=sites,
                 friendly=('body', 0), exit_path=(400, 1000, 15), search_lambda=0)
    assert not plan.deviations
