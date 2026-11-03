"""Declared physical contracts are measured on the geometry they generate."""
import copy
from types import SimpleNamespace
import pytest
import _plugin_tree
import analog_a5_layout_emit as a5
import analog_native_physical as physical
import analog_routing_intent as ri


def declared(*constraints):
    return {"version": 1, "constraints": list(constraints)}


def terminal(device, index=0):
    return {"device": device, "terminal": index}


def test_kelvin_compiles_private_routes_without_changing_schematic():
    devices = [{"name": name, "nets": ["p"], "pars": {}} for name in ("f", "s", "a")]
    before = copy.deepcopy(devices)
    raw = declared({"kind": "kelvin", "net": "p", "force": [terminal("f"), terminal("a")],
                    "sense": terminal("s"), "join": {"port": "p"}})
    compiled = ri.compile_branches(ri.parse_intent(raw), devices, ["p"])
    assert devices == before
    assert compiled.devices[0]["nets"] == compiled.devices[2]["nets"]
    assert compiled.devices[0]["nets"] != compiled.devices[1]["nets"]
    assert set(compiled.canonical[net] for net in compiled.branches["p"]) == {"p"}


@pytest.mark.parametrize("raw", [None, {}, {"version": True, "constraints": []},
    declared({"kind": "unknown"}), declared({"kind": "width", "net": "a", "wire_width_um": float("nan"), "via_cuts": 1}),
    declared({"kind": "width", "net": "a", "wire_width_um": 1, "via_cuts": True}),
    declared({"kind": "separation", "nets": ["a", "b"], "spacing_um": 1, "layer": "metal3"})])
def test_invalid_contracts_are_named(raw):
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_SCHEMA"):
        ri.parse_intent(raw)


def test_star_requires_exact_terminal_partition_and_separate_join():
    devices = [{"name": name, "nets": ["p"], "pars": {}} for name in ("a", "b", "load")]
    constraint = {"kind": "star", "net": "p", "groups": [[terminal("a")], [terminal("b")]], "join": terminal("load")}
    compiled = ri.compile_branches(ri.parse_intent(declared(constraint)), devices, [])
    assert len(compiled.branches["p"]) == 3
    constraint["groups"][1] = [terminal("a")]
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_CONFLICT"):
        ri.compile_branches(ri.parse_intent(declared(constraint)), devices, [])


def geometry():
    rules = {"metal_width_um": {i: .2 for i in range(1, 7)}, "metal_space_um": {i: .2 for i in range(1, 7)},
             "via_width_um": {i: .2 for i in range(1, 6)}, "via_space_um": {i: .2 for i in range(1, 6)},
             "via_surround_um": {}, "metal_area_um2": {}, "via_surround_dir_um": {}}
    return a5.Geo(rules, .2, 100, .3, .1)


def test_multicut_transition_paints_each_requested_cut_with_deck_pitch():
    geo = geometry();geo.intent_cuts = {"p": 3};geo.intent_strict = True
    plan = a5.Plan()
    a5._via_stack(plan, "p", 0, 0, 2, geo, top=4)
    for level in (2, 3):
        cuts = [row["box"] for row in plan.shapes if row["layer"] == f"via{level}"]
        assert len(cuts) == 3
        assert min(b[0] - a[2] for a, b in zip(cuts, cuts[1:])) >= geo.rules_via_space(level)


def test_multicut_unavailable_site_refuses_without_drawing():
    geo = geometry();geo.intent_cuts = {"p": 3};geo.intent_strict = True
    plan = a5.Plan()
    sites = a5.Sites([{"net": "other", "layer": "metal2", "box": (-1000, -1000, 1000, 1000)}], geo)
    with pytest.raises(a5.Refusal, match="ROUTING_INTENT_VIA_SITE"):
        a5._via_stack(plan, "p", 0, 0, 2, geo, top=3, sites=sites)
    assert plan.shapes == []


def test_no_intent_calls_original_planner_without_changing_tcl(monkeypatch):
    sentinel = a5.Plan();sentinel.tcl = ["native existing drawing"]
    calls = []
    def legacy(*args, **kwargs):
        calls.append(kwargs)
        return sentinel
    monkeypatch.setattr(a5, "_build_plan", legacy)
    assert a5.build_plan([], [], {}, None, geometry(), 0) is sentinel
    assert sentinel.tcl == ["native existing drawing"]
    assert "routing_intent" not in calls[0]


def test_pair_separation_includes_native_endpoint_metal():
    plan = a5.Plan()
    plan.shapes = [{"net": "a", "layer": "metal2", "box": (0, 0, 30, 30)}]
    plan.device_shapes = [{"net": "<device b>", "comp": ("b", 1), "layer": "metal2", "box": (40, 0, 70, 30)}]
    plan.intent_component_nets = {("b", 1): {"b"}}
    intent = ri.parse_intent(declared({"kind": "separation", "nets": ["a", "b"], "spacing_um": .2}))
    compiled = ri.Compiled(intent, [], [], {"a": "a", "b": "b"}, {}, {}, {}, None)
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_SEPARATION"):
        ri.verify_separation(plan, compiled, geometry(), a5)
    plan.device_shapes[0]["box"] = (50, 0, 80, 30)
    assert ri.verify_separation(plan, compiled, geometry(), a5)[0]["minimum_um"] == .2


def test_wrong_layer_load_window_does_not_hide_native_short():
    topology = ri.Topology("star", "p", ((ri.Terminal("f", 0),), (ri.Terminal("s", 0),)), ri.Port("p"))
    compiled = ri.Compiled(ri.RoutingIntent((topology,)), [], [], {"f": "p", "s": "p"}, {}, {"p": ("f", "s")}, {"p": "f"}, None)
    plan = a5.Plan();plan.intent_anchors = {}
    plan.shapes = [{"net": "f", "layer": "metal1", "box": (0, 0, 1, 1)},
                   {"net": "s", "layer": "metal1", "box": (9, 0, 10, 1)}]
    plan.device_shapes = [{"net": "<device>", "layer": "metal1", "box": (0, 0, 10, 1)}]
    regions = {"p": {"box": (4, -1, 6, 2), "layers": ("metal2",), "load_layer": "metal2", "native_component": None}}
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_DISCONNECTED_BRANCH"):
        ri.verify_topology(plan, compiled, regions, a5._linked)


def test_normal_A11_forwards_declared_json_and_invalid_is_named(tmp_path, monkeypatch):
    calls = []
    config = {"routing_intent": declared()}
    monkeypatch.setattr(physical, "_settings", lambda *args: config)
    def run(program, argv, **kwargs):
        calls.append(argv)
        return {"returncode": 127}
    physical.run_step("A11", tmp_path, {"name": "unit"}, {"pdk": "x"}, run)
    assert "--routing-intent" in calls[0]
    config["routing_intent"] = declared({"kind": "width", "net": "p", "wire_width_um": float("inf"), "via_cuts": 1})
    result = physical.run_step("A11", tmp_path, {"name": "unit"}, {"pdk": "x"}, run)
    assert result["status"] == "FAIL"
    assert "ROUTING_INTENT_SCHEMA" in result["detail"]
    assert len(calls) == 1


def native_plan_inputs():
    import json
    from pathlib import Path
    import analog_a5_pdk_device_limits as limits
    data = json.loads((Path(__file__).parent / "fixtures/a11_routing_intent/native_plan.json").read_text())
    facts = a5.PdkFacts()
    facts.gencells = data["gencells"]
    facts.m1_space_um = data["m1_space_um"]
    facts.deck = {name: {tuple(key) if isinstance(key, list) else key: value for key, value in entries}
                  for name, entries in data["deck"].items()}
    facts.layers = limits.LayerIdentity();facts.layers.__dict__.update(data["layers"])
    cells = {tuple(key): dict(cell, layers=facts.layers) for key, cell in data["cells"]}
    geo = a5.Geo(facts.deck, facts.m1_space_um, data["lambda"], .3, .15)
    return data, facts, cells, geo


def test_actual_plan_honours_all_four_declarations_and_preserves_pdk_facts():
    data, facts, cells, geo = native_plan_inputs()
    before = copy.deepcopy(facts.deck)
    plan = a5.build_plan(data["devices"], data["ports"], cells, facts, geo, 48, data["pin_spec"],
                         routing_intent=data["routing_intent"])
    evidence = plan.routing_intent_evidence["constraints"]
    assert {item["kind"] for item in evidence} == {"kelvin", "star", "width", "separation"}
    assert all(not item["outside_join_connected"] for item in evidence if item["kind"] in ("kelvin", "star"))
    assert next(item for item in evidence if item["kind"] == "separation")["minimum_um"] >= .18
    assert {pin["net"] for pin in plan.pins} == set(data["ports"])
    assert all(not row["net"].startswith("__routing_intent") for row in plan.shapes)
    assert facts.deck == before


def test_native_fixed_terminal_spacing_cannot_be_silently_waived():
    data, facts, cells, geo = native_plan_inputs()
    data["routing_intent"]["constraints"][-1]["spacing_um"] = .21
    with pytest.raises(a5.Refusal, match="ROUTING_INTENT_SEPARATION"):
        a5.build_plan(data["devices"], data["ports"], cells, facts, geo, 48, data["pin_spec"], routing_intent=data["routing_intent"])


def test_minimum_width_refusal_names_pdk_floor_before_routing():
    data, facts, cells, geo = native_plan_inputs()
    raw = declared({"kind": "width", "net": "load", "wire_width_um": .001, "via_cuts": 1})
    with pytest.raises(a5.Refusal, match="ROUTING_INTENT_WIDTH_BELOW_PDK_MINIMUM"):
        a5.build_plan(data["devices"], data["ports"], cells, facts, geo, 48, data["pin_spec"], routing_intent=raw)


def test_device_area_repair_cannot_hide_a_premature_join():
    topology = ri.Topology("star", "p", ((ri.Terminal("f", 0),), (ri.Terminal("s", 0),)), ri.Port("p"))
    compiled = ri.Compiled(ri.RoutingIntent((topology,)), [], [], {"f": "p", "s": "p"}, {}, {"p": ("f", "s")}, {"p": "f"}, None)
    plan = a5.Plan();plan.intent_anchors = {}
    plan.shapes = [{"net": "f", "layer": "metal2", "box": (0, 0, 10, 2)},
                   {"net": "s", "layer": "metal2", "box": (0, 8, 10, 10)},
                   {"net": "f", "layer": "metal2", "box": (8, 0, 10, 10)},
                   {"net": "f", "layer": "metal2", "box": (0, 0, 2, 10)}]
    plan.patch_of[("metal2", (0, 0, 2, 10))] = "device"
    regions = {"p": {"box": (8, 0, 10, 10), "layers": ("metal2",), "load_layer": "metal2", "native_component": None}}
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_PREMATURE_JOIN"):
        ri.verify_topology(plan, compiled, regions, a5._linked)


def wide_terminal_inputs():
    facts = a5.PdkFacts()
    facts.layers = None
    facts.gencells = {"passive": {"namespace": "pdk", "params": {}, "class": "resistor"}}
    facts.deck = geometry().rules
    facts.m1_space_um = .2
    device = {"name": "r", "model": "passive", "class": "resistor", "nets": ["a", "b"], "pars": {}}
    cell = {"labels": [{"name": "R1", "layer": "metal1", "level": 1, "x": -200, "y": 0},
                       {"name": "R2", "layer": "metal1", "level": 1, "x": 200, "y": 0}],
            "sections": {"metal1": [(-250, -50, -150, 50), (150, -50, 250, 50)]},
            "bbox": (-300, -100, 300, 100), "delta": (300, 100), "cell": "passive", "layers": None}
    return device, {a5.config_key(device): cell}, facts, geometry()


def test_per_net_width_widens_target_wire_and_preserves_control_wire():
    device, cells, facts, geo = wide_terminal_inputs()
    plan = a5.build_plan([device], ["a", "b"], cells, facts, geo, 40,
                         routing_intent=declared({"kind": "width", "net": "a", "wire_width_um": .6, "via_cuts": 2}))
    rails = {net: [row["box"] for row in plan.shapes if row["net"] == net and row["layer"] == "metal2"
                   and row["box"][2] - row["box"][0] > row["box"][3] - row["box"][1] + 40] for net in ("a", "b")}
    assert rails["a"] and rails["b"]
    assert min(box[3] - box[1] for box in rails["a"]) == 60
    assert min(box[3] - box[1] for box in rails["b"]) == 30
    assert all(row["box"][2] - row["box"][0] >= 60 and row["box"][3] - row["box"][1] >= 60
               for row in plan.shapes if row["net"] == "a" and row["layer"].startswith("metal"))


def test_same_net_cut_spacing_is_never_exempted():
    geo = geometry()
    plan = a5.Plan();plan.intent_component_nets = {}
    plan.shapes = [{"net": "p", "layer": "via2", "box": (0, 0, 20, 20)}]
    compiled = ri.Compiled(ri.RoutingIntent(), [], [], {"p": "p"}, {}, {}, {}, None)
    assert not ri._safe([("via2", (30, 0, 50, 20))], "p", plan, compiled, geo, a5)
    assert ri._safe([("via2", (40, 0, 60, 20))], "p", plan, compiled, geo, a5)


def test_declared_shield_is_real_connected_metal_between_pair():
    data, facts, cells, geo = native_plan_inputs()
    raw = declared({"kind": "separation", "nets": ["load", "signal"], "shield_net": "return", "layer": "metal4"})
    plan = a5.build_plan(data["devices"], data["ports"], cells, facts, geo, 48, data["pin_spec"], routing_intent=raw)
    shield = plan.routing_intent_evidence["constraints"][0]
    assert shield["connected"] and shield["continuous_projection"]
    assert any(row["net"] == "return" and row["layer"] == "metal4"
               and tuple(row["box"]) == tuple(shield["shield_box_lambda"]) for row in plan.shapes)
    assert {pin["net"]: pin["index"] for pin in plan.pins} == {net: spec["index"] for net, spec in data["pin_spec"]["ports"].items()}


def test_a_cut_layer_cannot_silently_become_a_metal_shield():
    data, facts, cells, geo = native_plan_inputs()
    raw = declared({"kind": "separation", "nets": ["load", "signal"], "shield_net": "return", "layer": "via1"})
    with pytest.raises(a5.Refusal, match="ROUTING_INTENT_SHIELD_LAYER"):
        a5.build_plan(data["devices"], data["ports"], cells, facts, geo, 48, data["pin_spec"], routing_intent=raw)


@pytest.mark.parametrize("kind", ["kelvin", "star"])
def test_terminal_load_join_reaches_actual_native_contact(kind):
    template, cells, facts, geo = wide_terminal_inputs()
    devices = [dict(template, name=name, nets=["a", "b"]) for name in ("force", "sense", "load")]
    constraint = {"kind": kind, "net": "a", "join": terminal("load")}
    if kind == "kelvin":
        constraint.update(force=[terminal("force")], sense=terminal("sense"))
    else:
        constraint["groups"] = [[terminal("force")], [terminal("sense")]]
    plan = a5.build_plan(devices, ["a", "b"], cells, facts, geo, 40, routing_intent=declared(constraint))
    assert plan.routing_intent_evidence["constraints"][0]["outside_join_connected"] is False
    assert not a5.net_shorts(plan)


def test_unlabeled_native_contact_still_belongs_to_its_terminal_net():
    cell = {"bbox": (0, 0, 30, 130), "sections": {"polycont": [(0, 0, 30, 30), (0, 100, 30, 130)],
            "poly": [(10, 0, 20, 130)]}, "labels": [{"name": "G", "layer": "polycont", "x": 15, "y": 115, "level": 1}]}
    device = {"name": "m", "class": "mosfet", "nets": ["d", "g", "s", "b"], "pars": {}}
    rows = [{"net": "<device m>", "layer": "metal1", "box": box, "comp": ("m", i), "lcomp": ("m", "metal1", i)}
            for i, box in enumerate(((0, 0, 30, 30), (0, 100, 30, 130)))]
    plan = a5.Plan();plan.device_shapes = rows
    plan.shapes = [{"net": "g", "layer": "metal1", "box": (0, 100, 30, 130)},
                   {"net": "d", "layer": "metal1", "box": (40, 0, 70, 30)}]
    plan.intent_placed = [{"dev": device, "cell": cell, "origin": (0, 0), "rows": rows}]
    raw = declared({"kind": "separation", "nets": ["g", "d"], "spacing_um": .5})
    compiled = ri.compile_branches(ri.parse_intent(raw), [device], ["g", "d"])
    ri._anchors(plan, compiled, a5)
    assert ri._canonical(rows[0], compiled, plan) == {"g"}
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_SEPARATION"):
        ri.verify_separation(plan, compiled, geometry(), a5)


def test_sense_route_cannot_carry_force_terminal_through_the_load():
    f, s = ri.Terminal("f", 0), ri.Terminal("s", 0)
    topology = ri.Topology("kelvin", "p", ((f,), (s,)), ri.Port("p"))
    compiled = ri.Compiled(ri.RoutingIntent((topology,)), [], [], {"f": "p", "s": "p"}, {f: "f", s: "s"},
                           {"p": ("f", "s")}, {"p": "f"}, None)
    plan = a5.Plan()
    plan.shapes = [{"net": "f", "layer": "metal2", "box": (9, 0, 10, 1)},
                   {"net": "s", "layer": "metal2", "box": (0, 0, 10, 1)}]
    plan.device_shapes = [{"net": "<device f>", "layer": "metal2", "box": (0, 0, 1, 1), "comp": ("f", 0)},
                          {"net": "<device s>", "layer": "metal2", "box": (3, 0, 4, 1), "comp": ("s", 0)}]
    plan.intent_anchors = {f: [{"layer": "metal2", "box": (0, 0, 1, 1), "comp": ("f", 0)}],
                           s: [{"layer": "metal2", "box": (3, 0, 4, 1), "comp": ("s", 0)}]}
    regions = {"p": {"box": (9, -1, 11, 2), "layers": ("metal2",), "load_layer": "metal2", "native_component": None}}
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_DISCONNECTED_BRANCH"):
        ri.verify_topology(plan, compiled, regions, a5._linked)


def test_a_remote_via_cannot_turn_an_insulated_crossing_into_a_load_join():
    f, s = ri.Terminal("f", 0), ri.Terminal("s", 0)
    topology = ri.Topology("kelvin", "p", ((f,), (s,)), ri.Port("p"))
    compiled = ri.Compiled(ri.RoutingIntent((topology,)), [], [], {"f": "p", "s": "p"}, {f: "f", s: "s"},
                           {"p": ("f", "s")}, {"p": "f"}, None)
    plan = a5.Plan()
    plan.shapes = [{"net": "f", "layer": "metal3", "box": (0, 0, 1, 1)},
                   {"net": "f", "layer": "via2", "box": (0, 0, 1, 1)},
                   {"net": "f", "layer": "metal2", "box": (0, 0, 5, 1)},
                   {"net": "s", "layer": "metal3", "box": (9, 0, 10, 1)}]
    plan.device_shapes = [{"net": "<device>", "layer": "metal3", "box": (0, 0, 10, 1)},
                          {"net": "<device f>", "layer": "metal3", "box": (0, 0, 1, 1), "comp": ("f", 0)},
                          {"net": "<device s>", "layer": "metal3", "box": (9, 0, 10, 1), "comp": ("s", 0)}]
    plan.intent_anchors = {f: [{"layer": "metal3", "box": (0, 0, 1, 1), "comp": ("f", 0)}],
                           s: [{"layer": "metal3", "box": (9, 0, 10, 1), "comp": ("s", 0)}]}
    regions = {"p": {"box": (4, -1, 6, 2), "layers": ("metal2", "metal3", "via2"), "load_layer": "metal2", "native_component": None}}
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_DISCONNECTED_BRANCH"):
        ri.verify_topology(plan, compiled, regions, a5._linked)


def test_upper_plane_wire_keeps_its_larger_pdk_floor():
    device, cells, facts, _ = wide_terminal_inputs()
    facts.deck["metal_width_um"][6] = 1.64
    geo = a5.Geo(facts.deck, .2, 100, .3, .1)
    cell = cells[a5.config_key(device)]
    cell["sections"] = {"metal6": [(-300, -100, -100, 100), (100, -100, 300, 100)]}
    cell["bbox"] = (-350, -150, 350, 150);cell["delta"] = (350, 150)
    for label in cell["labels"]:
        label["layer"], label["level"] = "metal6", 6
    plan = a5.build_plan([device], ["a", "b"], cells, facts, geo, 40,
                         routing_intent=declared({"kind": "width", "net": "a", "wire_width_um": .6, "via_cuts": 1}))
    wires = [row["box"] for row in plan.shapes if row["net"] == "a" and row["layer"] == "metal6"
             and row["box"][2] - row["box"][0] > 200]
    assert wires and min(box[3] - box[1] for box in wires) >= 164


def test_intent_cut_spacing_rounds_pdk_minimum_up_and_preserves_legacy():
    geo = geometry()
    geo.rules["via_space_um"][2] = .045
    assert geo.rules_via_space(2) == 4
    legacy, _ = a5._pin_stack_boxes(0, 0, 2, 3, geo, 2)
    old_cuts = [box for layer, box in legacy if layer == "via2"]
    assert old_cuts[1][0] - old_cuts[0][2] == 4
    geo.intent_strict = True
    geo.intent_cuts = {"p": 2}
    assert geo.rules_via_space(2) == 5
    plan = a5.Plan()
    a5._via_stack(plan, "p", 0, 0, 2, geo, top=3)
    cuts = [row["box"] for row in plan.shapes if row["layer"] == "via2"]
    assert len(cuts) == 2
    assert cuts[1][0] - cuts[0][2] == 5
    assert (cuts[1][0] - cuts[0][2]) / geo.lam >= .045


def test_intent_cut_width_rounds_up_without_changing_legacy_geometry():
    rules = copy.deepcopy(geometry().rules)
    rules["via_width_um"][2] = .045
    geo = a5.Geo(rules, .2, 100, .3, .01)
    assert geo.via_pad[2] == geo.via_pad_min[2] == 2
    before = {name: getattr(geo, name)[2] for name in ("short_half", "long_half", "enc_half", "patch")}
    legacy = a5.Plan()
    a5._via_stack(legacy, "p", 0, 0, 2, geo, top=3)
    assert [row["box"][2] - row["box"][0] for row in legacy.shapes if row["layer"] == "via2"] == [4]
    geo.intent_strict = True
    assert geo.via_pad[2] == geo.via_pad_min[2] == 3
    assert all(getattr(geo, name)[2] == value + 1 for name, value in before.items())
    geo.intent_cuts = {"p": 2}
    plan = a5.Plan()
    a5._via_stack(plan, "p", 0, 0, 2, geo, top=3)
    cuts = [row["box"] for row in plan.shapes if row["layer"] == "via2"]
    assert len(cuts) == 2
    assert min(min(box[2] - box[0], box[3] - box[1]) / geo.lam for box in cuts) >= .045
    assert rules["via_width_um"][2] == .045


def current_budget(net="load", device="load_device", mv=1.0):
    return {"kind": "current_budget", "net": net, "device": device, "ir_drop_mv": mv}


def path(**changes):
    values = dict(current_ma=1.0, budget_mv=10.0, cut_ohms=(20.0, 20.0), sheet_ohm=0.1, pin_sheet_ohm=0.1,
                  pin_run=1000, source=0, sinks=(1000, 2000), leg_ohms=(4.0, 4.0))
    return ri.CurrentPath(**{**values, **changes})


@pytest.mark.parametrize("field,value", [("ir_drop_mv", 0), ("ir_drop_mv", float("nan")), ("device", "")])
def test_current_budget_contract_is_named(field, value):
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_SCHEMA"):
        ri.parse_intent(declared({**current_budget(), field: value}))


def test_a_net_cannot_declare_both_a_width_and_a_current_budget():
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_CONFLICT"):
        ri.parse_intent(declared(current_budget(), {"kind": "width", "net": "load", "wire_width_um": 1, "via_cuts": 1}))


def test_rail_resistance_follows_the_current_each_segment_carries():
    # both legs on one side: all the current for 1000, half for the next 1000
    assert path().rail_ohm(100) == pytest.approx(0.1 * (1000 + 0.25 * 1000) / 100)
    # one leg each side: each segment carries half
    assert path(sinks=(1000, -1000)).rail_ohm(100) == pytest.approx(0.1 * (0.25 * 1000 + 0.25 * 1000) / 100)


def test_derived_size_scales_with_the_declared_current_and_meets_the_budget():
    small, large = path().size(), path(current_ma=4.0).size()
    assert large.rail_lam > small.rail_lam and large.cuts > small.cuts
    for candidate in (path(), path(current_ma=4.0)):
        assert candidate.total_ohm(candidate.size()) <= candidate.budget_ohm


def test_budget_the_terminal_legs_already_exceed_is_refused_with_numbers():
    with pytest.raises(ri.IntentRefusal, match="ROUTING_INTENT_IR_BUDGET_UNACHIEVABLE.*2.000 ohm of parallel"):
        path(budget_mv=1.0).size()


def test_resize_keeps_the_seated_stack_and_absorbs_a_longer_rail():
    first = path().size()
    longer = path(source=-20000)
    assert longer.total_ohm(first) > longer.budget_ohm
    resized = longer.resize(first)
    assert resized.cuts == first.cuts and resized.rail_lam > first.rail_lam
    assert longer.total_ohm(resized) <= longer.budget_ohm


def test_tech_lef_resistances_are_read_per_layer():
    layers = a5.tech_lef_layers("""
LAYER Metal2
  TYPE ROUTING ;
  RESISTANCE RPERSQ 0.103 ;
END Metal2
LAYER Via2
  TYPE CUT ;
  RESISTANCE 20 ;
END Via2
""")
    assert [(row["name"], row["resistance"]) for row in layers] == [("Metal2", 0.103), ("Via2", 20.0)]


def test_only_a_wide_rail_moves_row_tracks_and_it_clears_its_neighbours():
    geo = geometry()
    assert a5._row_rail_centres(["a", "b"], 0, 100, geo) == ({"a": 100, "b": 200}, 0)
    wide = copy.copy(geo);wide.rail_wire = 300
    geo.intent_profiles = {"a": wide}
    centres, extra = a5._row_rail_centres(["a", "b"], 0, 100, geo)
    assert centres["a"] - 150 >= 0 and extra > 0
    assert centres["b"] - centres["a"] >= 150 + geo.wire[2] // 2 + geo.metal_space("metal2")


def budgeted_inputs(device="force", mv=32.0, current=1.0):
    data, facts, cells, geo = native_plan_inputs()
    data["pin_spec"]["resistance_ohm"] = {"metal_per_square": {k: 0.1 for k in range(1, 8)},
                                          "cut": {k: 20.0 for k in range(1, 7)}}
    if current:
        data["pin_spec"]["ports"]["load"]["em"] = {"result": "SIZED", "current_mA": current}
    constraints = [item for item in data["routing_intent"]["constraints"] if item["kind"] != "width"]
    data["routing_intent"]["constraints"] = constraints + [current_budget("load", device, mv)]
    return data, facts, cells, geo


def plan_for(data, facts, cells, geo):
    return a5.build_plan(data["devices"], data["ports"], cells, facts, geo, 48, data["pin_spec"],
                         routing_intent=data["routing_intent"])


def test_real_plan_widens_only_the_current_rail_and_adds_cuts_only_to_its_pin_stack():
    budgeted = plan_for(*budgeted_inputs())
    record = next(item for item in budgeted.routing_intent_evidence["constraints"] if item["kind"] == "current_budget")
    assert record["current_mA"] == 1.0
    assert record["modelled_ohm"]["total"] <= 32.0
    assert record["rail_width_um"] > 0.3 and record["cuts_per_via"] > 1

    data, facts, cells, geo = budgeted_inputs()
    data["routing_intent"]["constraints"].pop()
    control = plan_for(data, facts, cells, geo)
    assert not any(item["kind"] == "current_budget" for item in control.routing_intent_evidence["constraints"])

    def narrowest(plan, net, layer="metal3"):
        return min(min(row["box"][2] - row["box"][0], row["box"][3] - row["box"][1])
                   for row in plan.shapes if row["net"] == net and row["layer"] == layer)

    def rail_heights(plan, net):
        return sorted(row["box"][3] - row["box"][1] for row in plan.shapes if row["net"] == net
                      and row["layer"] == "metal2" and row["box"][2] - row["box"][0] > 2 * (row["box"][3] - row["box"][1]))

    assert max(rail_heights(budgeted, "load")) == round(record["rail_width_um"] * 100)
    assert max(rail_heights(control, "load")) < max(rail_heights(budgeted, "load"))
    assert max(rail_heights(budgeted, "signal")) == max(rail_heights(control, "signal"))
    # Terminal legs carry a share of the current and keep their width.
    assert narrowest(budgeted, "load") == narrowest(control, "load")
    count = lambda plan: sum(row["net"] == "load" and row["layer"] == "via2" for row in plan.shapes)
    assert count(budgeted) >= count(control) + record["cuts_per_via"] - 1
    assert not a5.net_shorts(budgeted)


def test_tighter_budget_draws_a_lower_resistance_path():
    loose, tight = (next(item for item in plan_for(*budgeted_inputs(mv=mv)).routing_intent_evidence["constraints"]
                         if item["kind"] == "current_budget") for mv in (120.0, 32.0))
    assert tight["modelled_ohm"]["total"] < loose["modelled_ohm"]["total"]
    assert tight["rail_width_um"] > loose["rail_width_um"]


@pytest.mark.parametrize("changes,code", [({"current": None}, "ROUTING_INTENT_CURRENT_UNDECLARED"),
                                          ({"device": "sense"}, "ROUTING_INTENT_CURRENT_PATH_UNSUPPORTED"),
                                          ({"device": "absent"}, "ROUTING_INTENT_ENDPOINT"),
                                          ({"mv": 0.001}, "ROUTING_INTENT_IR_BUDGET_UNACHIEVABLE")])
def test_current_budget_refuses_what_it_cannot_establish(changes, code):
    with pytest.raises(a5.Refusal, match=code):
        plan_for(*budgeted_inputs(**changes))


def test_missing_lef_resistance_is_refused_not_assumed():
    data, facts, cells, geo = budgeted_inputs()
    data["pin_spec"].pop("resistance_ohm")
    with pytest.raises(a5.Refusal, match="ROUTING_INTENT_RESISTANCE_UNDECLARED"):
        plan_for(data, facts, cells, geo)


def test_a_join_extension_is_as_wide_as_the_pin(monkeypatch):
    painted = []
    pin = {"net": "out", "layer": "metal4", "strip_box": (0, 0, 1000, 100), "width_lam": 1000}
    plan = SimpleNamespace(pins=[pin], paint=lambda *args: painted.append(args))
    geo = SimpleNamespace(rules={"metal_width_um": {4: .2, 5: 1.}}, intent_cuts={},
                          metal_space=lambda layer: 10)
    a5 = SimpleNamespace(_pin_stack_boxes=lambda *args: (None, {4: (-24, -24, 24, 24), 5: (-24, -24, 24, 24)}))
    monkeypatch.setattr(ri, "_safe", lambda *args: True)
    ri._join_port(plan, "out", 2, 0, SimpleNamespace(canonical={"out": "out"}), geo, a5)
    x1, _, x2, _ = painted[0][2:]
    assert x2 - x1 == 1000
    assert pin["label_box"][2] - pin["label_box"][0] == 1000
