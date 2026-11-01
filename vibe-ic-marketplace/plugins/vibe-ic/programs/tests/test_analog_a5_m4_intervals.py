"""Geometry controls for vertical trunk track reuse in normal A5."""
import pytest
import _plugin_tree
import analog_a5_layout_emit as a
from test_analog_a5_shared_escape import geo


def test_interval_allocator_reuses_only_after_the_required_edge_gap():
    tracks = a._interval_tracks({
        'first': (0, 100), 'overlap': (50, 250),
        'near': (120, 130), 'next': (151, 300),
    }, 21)
    assert tracks['first'] != tracks['near']
    assert tracks['first'] == tracks['next']
    assert len(set(tracks.values())) == 3


@pytest.mark.parametrize('gap,shares', [(55, False), (89, True)])
def test_m4_reuse_includes_via_enclosure_not_only_wire_ends(gap, shares):
    bus, _ = a._m4_trunk_tracks(
        [{'first': 0}, {'first': 1000},
         {'next': 1000 + gap}, {'next': 2000}], geo())
    assert (bus['first'] == bus['next']) is shares


def test_disjoint_vertical_spans_share_real_painted_trunks_without_shorts():
    g = geo()
    rails = [{'a': 1000, 'guard': 1069}, {'a': 2000},
             {'b': 3000}, {'b': 4000}, {'guard': 4500}]
    bus, margin = a._m4_trunk_tracks(rails, g)
    assert bus['a'] == bus['b'] != bus['guard']
    _, _, pitch = a._m4_trunk_envelope(g)
    assert margin < (len(bus) + 3) * pitch
    plan = a.Plan()
    sites = a.Sites([], g)
    plan.sites = sites
    for net, x in bus.items():
        ys = [row[net] for row in rails if net in row]
        half = g.wire[4] // 2
        plan.paint(net, 'metal4', x-half, min(ys), x+half, max(ys))
    for row in rails:
        for net, y in row.items():
            x = bus[net]
            plan.paint(net, 'metal2', x, y-15, margin+1000, y+15)
            assert a._via_stack(plan, net, x, y, 2, g, top=4,
                                sites=sites, search_lambda=0) == (x, y)
    assert not plan.deviations
    for i, first in enumerate(plan.shapes):
        for second in plan.shapes[i+1:]:
            if first['net'] == second['net'] or first['layer'] != second['layer']:
                continue
            required = g.metal_space(first['layer'], first['box'], second['box'])
            assert a.box_separation(first['box'], second['box']) >= required


def test_wide_m4_trunks_obey_the_width_dependent_source_spacing():
    g = geo()
    g.wire[4] = 80
    g.rules['metal_width_spacing_um'] = {
        4: [{'width_gt_um': .39, 'parallel_gt_um': 1., 'spacing_um': .51}]}
    bus, _ = a._m4_trunk_tracks(
        [{'a': 0, 'b': 100}, {'a': 3000, 'b': 3100}], g)
    first = (bus['a']-40, 0, bus['a']+40, 3000)
    second = (bus['b']-40, 100, bus['b']+40, 3100)
    assert a.box_separation(first, second) >= g.metal_space('metal4', first, second)


def test_fixed_centre_bus_via_does_not_walk_into_another_interval():
    g = geo()
    plan = a.Plan()
    sites = a.Sites([], g)
    plan.sites = sites
    plan.paint('own', 'metal2', -100, -15, 100, 15)
    plan.paint('foreign', 'metal3', -50, -50, 50, 50)
    assert a._via_stack(plan, 'own', 0, 0, 2, g, top=4,
                        sites=sites, search_lambda=0) == (0, 0)
    assert any(d['quantity'] == 'via_island_clearance_lambda' for d in plan.deviations)
    assert all('within 0 lambda' in d['detail'] for d in plan.deviations)
