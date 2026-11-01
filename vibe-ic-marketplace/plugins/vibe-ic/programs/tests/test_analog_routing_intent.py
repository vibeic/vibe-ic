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
