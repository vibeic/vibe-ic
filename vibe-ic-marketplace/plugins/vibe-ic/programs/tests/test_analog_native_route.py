import pytest

import _plugin_tree  # noqa: F401
import analog_native_route as route


ROUTING = {"routing_layers": [1, 4], "threads": 8, "detailed_route_iterations": 40,
           "rail": {"width_um": 1.64, "via_pitch_um": 40}}


def test_the_layer_map_gives_the_drawn_numbers():
    text = "Metal1 NET,SPNET,PIN,LEFPIN,VIA 8 0\nMetal1 PIN,LEFPIN 8 2\nVia1 VIA 19 0\nDIEAREA ALL 189 4\n"
    assert route.layer_numbers(text) == {"Metal1": (8, 0), "Via1": (19, 0)}


def test_the_lef_stack_lists_routing_and_cut_layers_bottom_up():
    text = ("LAYER Cont\n TYPE CUT ;\nEND Cont\nLAYER Metal1\n TYPE ROUTING ;\n PITCH 0.48 0.42 ;\nEND Metal1\n"
            "LAYER Via1\n TYPE CUT ;\nEND Via1\nLAYER Top\n TYPE ROUTING ;\n PITCH 3.28 ;\nEND Top\n")
    assert route.lef_stack(text) == (["Metal1", "Top"], ["Via1"], {"Metal1": (.48, .42), "Top": (3.28, 3.28)})


def test_keepout_devices_form_their_own_first_group_and_the_upper_plane_is_apart():
    banks = [{"members": ["c1"], "plane": "above"}, {"members": ["m1", "m2"], "plane": "base"},
             {"members": ["m3"], "plane": "base"}]
    assert route.group_devices(banks, ["m2"]) == ([["m2"], ["m1"], ["m3"]], ["c1"])


def test_wrapping_keeps_order_and_the_width_limit():
    widths = {"a": 40, "b": 40, "c": 40}
    assert route.wrap_by_width("abc", widths.get, 90, 5) == [["a", "b"], ["c"]]


def test_shelves_place_macros_and_report_their_extent():
    macros = [{"w": 60, "h": 10}, {"w": 60, "h": 20}, {"w": 60, "h": 5}]
    assert route.shelf_pack(macros, 10, 0, 130, 2) == (132, 27)
    assert [(m["x"], m["y"]) for m in macros] == [(10, 0), (72, 0), (10, 22)]


def test_columns_stay_below_the_declared_height():
    assert route.columns_by_height([("a", 40), ("b", 40), ("c", 40)], 90, 5) == [
        [("a", 5), ("b", 45)], [("c", 5)]]


def test_route_violations_are_counted_from_the_native_report():
    assert route.route_violations("violation type: Short\n x\nviolation type: EOL\n") == 2
    assert route.route_violations("") == 0


def test_the_site_comes_from_the_lef():
    assert route.site_name("SITE CoreSite\n CLASS CORE ;\nEND CoreSite\n") == "CoreSite"
    assert route.site_name("MACRO x\nEND x\n") is None


LEF_LAYERS = [{"name": "M1", "dc_density": 1.0}, {"name": "V1", "dc_density": .4},
              {"name": "M2", "dc_density": 2.0}, {"name": "T", "dc_density": 15.0}]


def test_supply_width_comes_from_the_declared_current_and_the_lef_density():
    rule = route.supply_rule(.9, LEF_LAYERS, ["M1", "M2"], 1, 2, .4, lambda level, width: .24)
    assert rule["M2"] == {"width_um": .45, "needed_um": .45, "short_um": 0.0, "space_um": .24}


def test_a_declared_low_metal_width_records_its_shortfall():
    rule = route.supply_rule(.9, LEF_LAYERS, ["M1", "M2"], 1, 2, .4, lambda level, width: .24)
    assert rule["M1"]["width_um"] == .4 and rule["M1"]["short_um"] == .5


def test_strap_pairs_spread_through_the_columns():
    assert route.strap_gaps(17, 1) == [7]
    assert route.strap_gaps(18, 2) == [5, 11]
    assert route.strap_gaps(17, 0) == [] and route.strap_gaps(1, 3) == []


def test_the_route_script_assigns_the_supply_rule_to_supply_nets_only():
    supply = {"Metal1": {"width_um": .4, "space_um": .22}, "Metal2": {"width_um": .45, "space_um": .25}}
    cfg = {**ROUTING, "routing_layers": [1, 2]}
    text = route.route_tcl("top", "t.lef", "c.lef", "Site", {}, ["Metal1", "Metal2"], (10, 10), [], [], "Metal2",
                           cfg, ["vdd", "vss"], supply)
    assert "create_ndr -name SUPPLY -spacing {Metal1 0.22 Metal2 0.25} -width {Metal1 0.4 Metal2 0.45}" in text
    assert text.count("assign_ndr") == 2 and "-net vdd" in text and "-net vss" in text


def test_a_rail_keeps_its_declared_position():
    kdb = pytest.importorskip("klayout.db")
    builder = route.MacroBuilder.__new__(route.MacroBuilder)
    builder.kdb = kdb
    builder.layout = kdb.Layout()
    builder.routing = ["M1", "M2", "M3", "M4", "M5", "M6"]
    builder.cuts = ["V1", "V2", "V3", "V4", "V5"]
    builder.numbers = {name: (i, 0) for i, name in enumerate(builder.routing + builder.cuts, 1)}
    builder.lef, builder.instances = [], []
    stem = {"top_via_um": .42, "island_um": .62, "lower_via_um": .19, "top_pad_um": .4}
    rail = builder.rail("vdd", 5000, 100000, ROUTING["rail"], stem, (4, 5, 6), suffix="_a", y=7000)
    assert (rail["x"], rail["y"], rail["name"], rail["net"]) == (5000, 7000, "rail_vdd_a", "vdd")
