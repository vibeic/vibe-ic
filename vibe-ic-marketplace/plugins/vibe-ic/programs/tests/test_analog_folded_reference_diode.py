"""Reference-leg graph behavior; electrical qualification stays with native OP."""
import copy
import json

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import test_analog_folded_first_stage_input as parent
from _hostpaths import require_repo

SELECTOR = "ota_folded_reference_diode"
REMOVED = {"mn_fc_cas_in1", "mn_fc_cas_in2"}
REMOVED_NETS = {"fc_l_in1", "fc_l_in2"}


def inputs(project):
    sizing = parent.inputs(project)
    sizing["knobs"][SELECTOR] = True
    for name in REMOVED:
        del sizing["device_parameters"][name]
    return sizing


def build(project):
    return parent.build(project, inputs(project))


def expanded(project, values, diode):
    # Construction precedes ordinary sizing. Keep the same complete parent
    # geometry here so the base runs its graph constructor to completion.
    sizing = parent.inputs(project)
    if diode:
        sizing["knobs"][SELECTOR] = True
    lib = a2.LIBRARY["delta_sigma"]
    devices, nets, _, _ = a2.expand_stages(lib, values)
    record = a2.expand_folded_first_stage(lib, values, sizing["knobs"],
                                         devices, nets, sizing, project)
    return devices, nets, record


def test_existing_normal_constructor_observes_reference_graph_change(tmp_path):
    before, old_nets, _ = expanded(tmp_path / "parent", parent.SPEC, False)
    after, nets, _ = expanded(tmp_path / "variant", parent.SPEC, True)
    # The existing pre-change constructor runs and produces the old graph;
    # the base control therefore observes device values, not an absent API.
    assert len(after) == len(before) - 2
    assert {d["name"] for d in before} - {d["name"] for d in after} == REMOVED
    assert set(old_nets) - set(nets) == REMOVED_NETS


def test_public_variant_preserves_all_other_devices_and_source_cards(tmp_path):
    before = parent.build(tmp_path / "parent")
    project = tmp_path / "variant"
    after = build(project)
    context = parent._context(tmp_path)
    assert not a3._validate_ir(after, context, project)
    old = {d["name"]: d for d in before["devices"]}
    new = {d["name"]: d for d in after["devices"]}
    assert old.keys() - new.keys() == REMOVED
    assert not new.keys() - old.keys()
    for name, device in new.items():
        expected = copy.deepcopy(old[name])
        if name in ("mn_fc_load_in1", "mn_fc_load_in2"):
            index = name[-1]
            expected["nets"] = [f"nd1_{index}", f"nd1_{index}", "vss", "vss"]
        assert device == expected
    for key in ("ports", "device_param_exprs", "constants", "effective_spec_values"):
        assert after.get(key) == before.get(key)
    assert len(after["folded_first_stage"]["expanded_devices"]) == 26
    render = lambda ir: a3.render_netlist(ir, context, [], a3._resolve_params(ir, parent.SPEC)[0])
    cards = lambda text: {line.split()[0]: line for line in text.splitlines() if line.startswith("x")}
    old_cards, new_cards = cards(render(before)), cards(render(after))
    changed = {"xmn_fc_load_in1", "xmn_fc_load_in2"}
    for name in old_cards.keys() & new_cards.keys() - changed:
        assert old_cards[name] == new_cards[name]
    assert old_cards.keys() - new_cards.keys() == {"x" + n for n in REMOVED}


@pytest.mark.parametrize("folded", [False, True])
def test_unselected_parent_graph_and_rendered_source_stay_identical(tmp_path, folded):
    project = tmp_path / "same"
    sizing = parent.inputs(project) if folded else {}
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    lib["spec_knobs"] = [k for k in lib["spec_knobs"] if k["name"] != SELECTOR]
    lib["folded_first_stage"].pop("reference_diode_knob", None)
    for group in a2._stage_groups(lib):
        group.get("folded_first_stage", {}).pop("reference_diode", None)
    current = parent.build(project, sizing)
    # Reconstruct the parent declaration using the same source API. It has
    # no reference selector, and the absent option must remain irrelevant.
    previous = parent.build(project, sizing, lib)
    for ir in (current, previous):
        ir.pop("_provenance")
    assert current == previous
    ctx = parent._context(tmp_path)
    assert a3.render_netlist(current, ctx, [], a3._resolve_params(current, parent.SPEC)[0]) == a3.render_netlist(
        previous, ctx, [], a3._resolve_params(previous, parent.SPEC)[0])


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_selector_uses_normal_boolean_reader(tmp_path, value):
    sizing = inputs(tmp_path)
    sizing["knobs"][SELECTOR] = value
    with pytest.raises(a2.SizingInputsInvalid, match="boolean"):
        parent.build(tmp_path, sizing)


def test_variant_requires_folded_selection(tmp_path):
    sizing = inputs(tmp_path)
    sizing["knobs"][parent.SELECTOR] = False
    with pytest.raises(a2.SizingInputsInvalid, match="requires the folded"):
        parent.build(tmp_path, sizing)


@pytest.mark.parametrize("kind", ["endpoint", "body", "signal_removed", "reference_restored",
                                  "removed_net", "width", "length", "delta_record", "selector"])
def test_actual_a3_refuses_tampered_reference_variant(tmp_path, kind):
    ir = build(tmp_path)
    devices = {d["name"]: d for d in ir["devices"]}
    if kind == "endpoint":
        devices["mn_fc_load_in1"]["nets"][0] = "nd2_1"
    elif kind == "body":
        devices["mn_fc_load_in1"]["nets"][3] = "vdd"
    elif kind == "signal_removed":
        ir["devices"].remove(devices["mn_fc_cas_ref1"])
    elif kind == "reference_restored":
        extra = copy.deepcopy(devices["mn_fc_cas_ref1"])
        extra["name"] = "mn_fc_cas_in1"
        ir["devices"].append(extra)
    elif kind == "removed_net":
        ir["internal_nets"].append("fc_l_in1")
    elif kind in ("width", "length"):
        devices["mn_fc_load_in1"][{"width": "w", "length": "l"}[kind]] *= 2
    elif kind == "delta_record":
        ir["folded_first_stage"]["reference_leg_variant"]["changes"][0]["remove_device"] = "mn_fc_cas_ref1"
    else:
        ir["knobs"][SELECTOR] = False
    assert any("folded" in p for p in a3._validate_ir(ir, parent._context(tmp_path), tmp_path))


def test_removed_device_geometry_is_not_silently_accepted(tmp_path):
    sizing = inputs(tmp_path)
    sizing["device_parameters"]["mn_fc_cas_in1"] = {"w": 48, "l": 2}
    with pytest.raises(a2.SizingInputsInvalid, match="unknown device"):
        parent.build(tmp_path, sizing)


def test_repo_spec_drives_reference_variant_expansion(tmp_path):
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "stage_analog_on_pass_review", "accept_adc_conv", "phase3", "analog",
        "delta_sigma", "spec.json")
    values = a2.spec_row_values(json.loads(source.read_text())["specs"])
    before, _, _ = expanded(tmp_path / "parent", values, False)
    after, _, record = expanded(tmp_path / "variant", values, True)
    assert len(after) == len(before) - 2
    assert all(change["new_nets"][0] == change["new_nets"][1]
               for change in record["reference_leg_variant"]["changes"])
