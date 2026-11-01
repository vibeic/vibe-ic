"""Drawn pin width must carry the declared current, or the site must refuse."""
from fractions import Fraction

import pytest
import _plugin_tree  # noqa: F401
import analog_a5_layout_emit as a
from test_analog_a5_2d_bank import connected
from test_analog_a5_pins_and_min_area import TECH_LEF


@pytest.mark.parametrize('rail_end,center', [(300, 1813), (6000, 1815)], ids=['short', 'long'])
@pytest.mark.parametrize('current_ma,required_width', [(25.05, 167), (25.2, 168)], ids=['odd', 'even'])
@pytest.mark.parametrize('corridor_width', [None, 166, 168], ids=['clear', 'narrow', 'exact-fit'])
def test_pin_em_width_meets_the_current_or_refuses(rail_end, center, current_ma,
                                                 required_width, corridor_width):
    rules = {
        'metal_space_um': {n: .21 for n in range(1, 8)},
        'metal_width_um': {n: .2 for n in range(1, 8)},
        'metal_area_um2': {2: .144, 3: .144},
        'via_width_um': {n: .2 for n in range(1, 7)},
        'via_space_um': {n: .21 for n in range(1, 7)},
        'via_surround_um': {}, 'via_surround_dir_um': {},
        'metal_width_spacing_um': {},
    }
    rules['metal_width_um'][6] = 1.64
    rules['metal_space_um'][6] = 1.64
    geo = a.Geo(rules, .21, 100, .3, .15)
    facts = a.PdkFacts()
    facts.tech_lef = a.tech_lef_layers(TECH_LEF)
    facts.sources['tech_lef'] = 'existing synthetic TECH_LEF fixture'
    spec, _ = a.pin_spec_for(['vp'], {'vdd': 'vp'},
        {'specs': [{'name': 'iout', 'max': current_ma, 'unit': 'mA'}]}, facts, geo)
    assert spec['ports']['vp']['width_lam'] == required_width
    assert spec['ports']['vp']['cuts'] == 63

    plan, sites = a.Plan(), a.Sites([], geo)
    plan.sites = sites
    rail = (200, 985, rail_end, 1015)
    plan.paint('vp', 'metal2', *rail)
    plan.paint('extent', 'metal1', 9900, 9900, 10000, 10000)
    if corridor_width is not None:
        # Above the stack, only the full-height stripe must pass this gap.
        clearance = geo.space[6]
        plan.paint('left', 'metal6', 0, 2000,
                   center - corridor_width // 2 - clearance, 10000)
        plan.paint('right', 'metal6', center + corridor_width // 2 + clearance,
                   2000, 10000, 10000)
    before = list(plan.shapes), list(plan.tcl)

    def draw():
        a._draw_pins(plan, ['vp'], {'vp': rail}, spec, geo, sites, 10000, 69)

    if corridor_width == 166:
        with pytest.raises(a.Refusal, match='pin_site_clearance'):
            draw()
        assert (plan.shapes, plan.tcl) == before and plan.pins == []
        return

    draw()
    pin = plan.pins[0]
    strip = pin['strip_box']
    width = strip[2] - strip[0]
    capacity_ma = Fraction(width, geo.lam) * 15
    assert capacity_ma >= Fraction(str(current_ma)), (
        f'drawn {width} lambda carries {float(capacity_ma)} mA, '
        f'below declared {current_ma} mA (required {required_width} lambda)')
    assert width == pin['width_lam'] == 168
    assert pin['layer'] == 'metal6' and pin['lef_layer'] == 'TM1'
    assert pin['use'] == 'power' and strip[1] == 0 and strip[3] == 10000
    assert pin['cuts_per_via'] == 63
    assert all(sum(r['layer'] == f'via{k}' for r in plan.shapes) == 63
               for k in range(2, 6))
    assert connected(plan, 'vp', ('metal2', 250, 1000),
                     ('metal6', (strip[0] + strip[2]) // 2, 1500))
    assert not a.net_shorts(plan)
