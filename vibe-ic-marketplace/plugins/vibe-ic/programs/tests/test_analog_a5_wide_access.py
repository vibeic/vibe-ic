"""Native-grid wide access failures, retaining narrow routing and PDK limits."""
import copy
import json
from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
import analog_a5_layout_emit as layout
import analog_layout_spacing as spacing


def geo(wire=.6, pad=.35):
    rules = {"metal_space_um": {n: .21 for n in range(1, 8)},
             "metal_width_um": {n: .2 for n in range(1, 8)},
             "metal_area_um2": {2: .144, 3: .144},
             "via_width_um": {n: .2 for n in range(1, 7)},
             "via_space_um": {n: .21 for n in range(1, 7)},
             "via_surround_um": {}, "via_surround_dir_um": {}}
    return layout.Geo(rules, .21, 100, wire, pad)


def native_row(box, component=1):
    return {"net": "<device unit>", "layer": "metal2", "box": box,
            "comp": ("unit", component), "lcomp": ("unit", "metal2", component)}


def test_same_native_polygon_can_acquire_a_new_illegal_notch():
    # One L polygon; the added rectangle joins its bottom but leaves a
    # 10-lambda notch at the upright. The former whole-lcomp exemption
    # accepted it. A 21-lambda gap is the independent positive boundary.
    sites = layout.Sites([native_row((0, 0, 100, 20)),
                          native_row((80, 20, 100, 100))], geo())
    assert not sites.clear((10, 10, 70, 80), ["metal2"], ("unit", 1))
    assert sites.clear((10, 10, 59, 80), ["metal2"], ("unit", 1))


def test_actual_subminimum_contact_plus_fallback_pad_is_not_minimum_area():
    # Translated native M2.d marker: .088 um2 pad plus .0242 um2 extension.
    sites = layout.Sites([native_row((0, 0, 20, 44))], geo())
    assert sites.merged_area((9, 3, 31, 25), "metal2", ("unit", 1)) == 1122
    assert sites.merged_area((0, 0, 40, 40), "metal2", ("unit", 1)) == 1680
    assert sites.merged_area((9, 3, 31, 25), "metal3", ("unit", 1)) == 484


def test_reduced_area_fallback_cannot_be_accepted_merely_for_touching(monkeypatch):
    g = geo()
    sites = layout.Sites([native_row((-10, -22, 10, 22))], g)
    # Only the previously accepted .22x.22 fallback fits this control.
    monkeypatch.setattr(sites, "clear", lambda box, *a: box[2]-box[0] == box[3]-box[1] == 22)
    plan = layout.Plan()
    layout._via_stack(plan, "signal", 0, 0, 2, g, sites=sites, friendly=("unit", 1))
    assert any(d["quantity"] == "via_island_clearance_lambda" for d in plan.deviations)


def test_full_area_native_island_remains_available():
    g = geo()
    sites = layout.Sites([native_row((-10, -22, 10, 22))], g)
    plan = layout.Plan()
    layout._via_stack(plan, "signal", 0, 0, 2, g, sites=sites, friendly=("unit", 1))
    assert not plan.deviations
    assert all((r["box"][2]-r["box"][0])*(r["box"][3]-r["box"][1]) >= 1440
               for r in plan.shapes if r["layer"] == "metal2")


def rows():
    return [{"net": "drain", "y": 0, "escape_y": 0, "strapped": False,
             "labels": [{"x": -44, "y": 0}]},
            {"net": "source", "y": 0, "escape_y": 0, "strapped": False,
             "labels": [{"x": 44, "y": 0}]},
            {"net": "gate", "y": 222, "escape_y": 222, "strapped": False,
             "labels": [{"x": 0, "y": 222}]},
            {"net": "body", "y": -54, "escape_y": -54, "strapped": False,
             "body_tap": True, "labels": [{"x": -131, "y": -54}]}]


def test_measured_54_grid_tap_row_keeps_narrow_path_and_moves_wide_plain_only():
    narrow, wide = rows(), rows()
    original = copy.deepcopy(narrow)
    layout._collect_close_plain_rows(narrow, (-141, -305, 141, 305), geo(.3, .15))
    assert narrow == original
    layout._collect_close_plain_rows(wide, (-141, -305, 141, 305), geo())
    assert wide[-1] == original[-1]  # the chosen body connection is untouched
    assert all(g["strapped"] for g in wide[:-1])
    assert all(g["escape_y"] < -305 or g["escape_y"] > 305 for g in wide[:-1])
    # Actual historical rectangle witness, independent of collection logic.
    bad = layout.Plan()
    bad.paint("drain", "metal3", 113453, 71988, 113513, 72112)
    bad.paint("body", "metal3", 113483, 71934, 114650, 71994)
    assert layout.net_shorts(bad)


def test_ordinary_plan_routes_dense_access_and_keeps_narrow_geometry(monkeypatch):
    dev = {"name": "unit", "model": "native_mos", "class": "mosfet",
           "nets": ["drain", "gate", "return", "return"],
           "pars": {"w": 4., "l": .5, "m": 1}}
    text = """magic
magscale 1 1
<< metal1 >>
rect -141 -305 -121 305
rect 121 -305 141 305
rect -121 -305 121 -285
rect -121 285 121 305
<< metal2 >>
rect -54 -180 -34 180
rect 34 -180 54 180
rect -14 225 14 255
<< labels >>
rlabel metal1 0 -295 0 -295 0 B
rlabel metal2 -44 0 -44 0 0 D
rlabel metal2 44 0 44 0 0 S
rlabel metal2 0 240 0 240 0 G
<< end >>
"""
    cell = layout.parse_cell(text)
    cell.update(bbox=(-170, -340, 170, 340), delta=(170, 340))
    pdk = SimpleNamespace(layers=None, gencells={"native_mos": {
        "namespace": "provider", "params": ["w", "l", "m", "guard"]}})
    monkeypatch.setattr(layout, "ring_layer_of", lambda _: "metal1")
    monkeypatch.setattr(layout, "body_tap_direct_m1_layer", lambda *a: "metal1")
    # The measured tap-search output is the input to routing under test.
    monkeypatch.setattr(layout, "choose_tap", lambda *a: (-131, -54, 100, False))
    def build(g):
        return layout.build_plan([dev], ["drain", "gate", "return"],
                                 {layout.config_key(dev): cell}, pdk, g, 0)
    narrow = build(geo(.3, .15))
    wide = build(geo())
    assert not layout.net_shorts(wide)
    assert any(r["layer"] == "metal2" and r["net"] == "drain"
               for r in wide.shapes)
    monkeypatch.setattr(layout, "_collect_close_plain_rows", lambda *a: None)
    legacy = build(geo(.3, .15))
    assert narrow.shapes == legacy.shapes and narrow.tcl == legacy.tcl


def native_declarations():
    source = "mets_lay = [metal2_drw, metal3_drw, metal4_drw, metal5_drw]\n"
    values = {}
    for suffix, width, length, gap in [("e", .39, 1., .24), ("f", 10., 10., .6)]:
        stem, key = "mn_"+suffix, "Mn_"+suffix
        source += (f"{stem}_value = drc_rules['{key}'].to_f\n"
                   f"{stem}_width = drc_rules['{key}_w'].to_f / 2\n"
                   f"{stem}_length = drc_rules['{key}_cr'].to_f\n"
                   f"{stem}_l1 = met_lay.sized(-1 * {stem}_width.um).sized({stem}_width.um)\n"
                   f"met_lay.sep({stem}_l1, {stem}_value.um, projection_limits({stem}_length.um + 0.001.um, nil))\n")
        values.update({key: gap, key+"_w": width, key+"_cr": length})
    return json.dumps({"drc_rules": values}), source


def test_native_width_and_parallel_predicates_reach_actual_site_clearance():
    config, source = native_declarations()
    g = geo()
    g.rules["metal_width_spacing_um"] = spacing.parse_native_rules(config, source)
    # .22um clears the unconditional .21, but not a long .6um-wide run's .24.
    sites = layout.Sites([{"net": "other", "layer": "metal3", "box": (82, 0, 142, 200)}], g)
    assert not sites.clear((0, 0, 60, 200), ["metal3"], None, "mine")
    assert sites.clear((0, 0, 60, 100), ["metal3"], None, "mine")
    wide = layout.Sites([{"net": "other", "layer": "metal3", "box": (1225, 0, 2425, 2000)}], g)
    assert not wide.clear((0, 0, 1200, 2000), ["metal3"], None, "mine")
    assert wide.clear((0, 0, 1200, 1000), ["metal3"], None, "mine")
    # Narrow/short source geometry retains its ordinary unconditional spacing.
    assert g.metal_space("metal3", (0, 0, 30, 2000), (52, 0, 82, 2000)) == 21


@pytest.mark.parametrize("change", ["slope", "missing", "invalid"])
def test_unsupported_native_predicates_are_not_invented(change):
    config, source = native_declarations()
    if change == "slope":
        source = source.replace("projection_limits", "arbitrary_nonlinear_predicate")
    elif change == "missing":
        config = json.dumps({"drc_rules": {}})
    else:
        config = config.replace('"Mn_e": 0.24', '"Mn_e": true')
    with pytest.raises(ValueError):
        spacing.parse_native_rules(config, source)


@pytest.mark.parametrize("before,after", [
    ("['Mn_e_w'].to_f / 2", "['Mn_e_w'].to_f / 2 / 2"),
    ("['Mn_e_w'].to_f / 2", "['Mn_e_w'].to_f * 2"),
    ("['Mn_e'].to_f", "['Mn_e'].to_f / 2"),
    ("['Mn_e_cr'].to_f", "['Mn_e_cr'].to_f + 1"),
    (".sized(mn_e_width.um)", ".sized(mn_e_width.um).sized(1.um)"),
    ("mn_e_length.um + 0.001.um", "mn_e_length.um + 0.001.um + 1.um"),
    ("metal5_drw]", "metal5_drw] + [metal6_drw]"),
])
def test_native_statements_reject_trailing_arithmetic_and_changed_operators(before, after):
    config, source = native_declarations()
    assert before in source
    with pytest.raises(ValueError):
        spacing.parse_native_rules(config, source.replace(before, after))


@pytest.mark.parametrize("write", [
    "mets_lay = [metal6_drw]", "mets_lay += [metal6_drw]",
    "mets_lay[0] = metal6_drw", "mets_lay << metal6_drw",
    "mn_e_width += 0.01", "mn_e_width = 0.0975",
])
def test_native_predicate_and_layer_reassignments_are_unsupported(write):
    config, source = native_declarations()
    with pytest.raises(ValueError):
        spacing.parse_native_rules(config, source + write + "\n")


def test_native_indentation_inline_comments_and_result_assignment_are_supported():
    config, source = native_declarations()
    expected = spacing.parse_native_rules(config, source)
    source = source.replace("\nmet_lay.sep(mn_e", "\nmn_e_l = met_lay.sep(mn_e")
    source = "\n".join("  " + line + "  # native declaration" for line in source.splitlines())
    assert spacing.parse_native_rules(config, source) == expected
