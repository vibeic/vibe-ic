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


def test_realized_m2_exit_does_not_create_a_phantom_m3_obstacle():
    g = geo()
    plan = a.Plan()
    sites = a.Sites([], g)
    plan.sites = sites
    plan.paint('foreign', 'metal2', 800, 900, 1200, 1100)
    plan.m3_escape_obstacles = [('foreign', (800, 985, 1200, 1015))]
    a._route_m3_leg(plan, 'own', 1000, 0, 2000, g, sites)
    assert all(s['layer'] == 'metal3' for s in plan.shapes if s['net'] == 'own')


def test_moved_island_remains_attached_to_the_existing_route():
    g = geo()
    plan = a.Plan()
    sites = a.Sites([], g)
    plan.sites = sites
    plan.paint('own', 'metal2', 400, 985, 1000, 1015)
    plan.paint('foreign', 'metal3', 985, 985, 1015, 1015)
    start = len(plan.shapes)
    a._via_stack(plan, 'own', 1000, 1000, 2, g, top=3, sites=sites, join_levels=(2,))
    box = next(s['box'] for s in plan.shapes[start:] if s['layer'] == 'metal2')
    assert box[0] < 1000 and 400 < box[2] and box[1] < 1015 and 985 < box[3]
    assert not plan.deviations


def test_endpoint_detour_uses_a_real_channel_beyond_the_endpoint_interval():
    g = geo()
    native = [{'net': '<device opaque>', 'layer': 'metal2',
               'comp': ('opaque', i), 'lcomp': ('opaque', 'metal2', i), 'box': box}
              for i,box in enumerate(((16112,10635,16132,11021),
                                      (16651,10635,16671,10825),
                                      (16739,10635,16759,10825),
                                      (16691,10835,16719,10865)))]
    plan = a.Plan()
    sites = a.Sites(native,g)
    plan.sites = sites
    for net,layer,box in [
        ('vdd','metal3',(16273,10467,16303,10828)),
        ('vdd','metal3',(16107,10813,16303,10843)),
        ('nrm','metal3',(16342,10835,16720,10865)),
        ('nrmb','metal3',(16411,10713,16676,10743)),
        ('nrmb','metal4',(15730,10823,17680,10853)),
        ('vdd','metal2',(16098,10812,16146,10844)),
        ('vss','metal2',(16725,10712,16773,10744)),
        ('nrm','metal2',(16694,10816,16716,10884))]:
        plan.paint(net,layer,*box)
    assert a._route_m3_leg(plan,'nrmb',16426,10838,10728,g,sites)
    assert any(s['net']=='nrmb' and s['layer']=='metal2' and s['box'][1]<10635 for s in plan.shapes)
