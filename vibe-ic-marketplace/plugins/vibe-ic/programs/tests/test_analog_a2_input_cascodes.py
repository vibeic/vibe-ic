"""Optional physical cascodes are emitted from declarations and ordinary sizing.

These are source/card and current-reader controls, not native performance proof.
"""
import copy
import json
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401
import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import analog_existing_design_validate as existing
from test_analog_a2_ota_compensation import SPEC as BASE_SPEC, MEASURED

SPEC = dict(BASE_SPEC, enob=14.0, osr=512.0)


def _sizing(enabled=True):
    return {"knobs": {"ota_input_drain_cascodes": enabled, "ota_compensation_scale": 6},
        "device_parameters": {
            **{name: {"w": 18, "ng": 2} for name in ("mn_in1", "mn_ref1", "mn_in2", "mn_ref2")},
            **{name: {"w": 24, "l": .5, "ng": 3} for name in
               ("mn_cas_in1", "mn_cas_ref1", "mn_cas_in2", "mn_cas_ref2")},
            "r_cas_top": {"w": .8, "l": 120},
            "r_cas_bottom": {"w": .8, "l": 40}}}


def _build(project, sizing=None, lib=None, **kwargs):
    path = project / "phase3/analog/converter"
    path.mkdir(parents=True, exist_ok=True)
    if sizing is not None:
        (path / "sizing_inputs.json").write_text(json.dumps(sizing))
    return a2.build_ir("converter", "delta_sigma", {"name": "converter"},
        lib or a2.LIBRARY["delta_sigma"], SPEC, None, project, None, {},
        measured_params=MEASURED, **kwargs)


@pytest.fixture
def context(tmp_path):
    models = tmp_path / "models.lib"
    models.write_text("* Valid range for model: L = (0.1 - 5)um\n* W = (0.2 - 10)um\n"
        ".lib typ\n.subckt neutral_n d g s b w=1u l=1u ng=1\n"
        "Ncore d g s b native_n w=w l=l nf=ng\n.ends neutral_n\n"
        ".subckt neutral_p d g s b w=1u l=1u ng=1\n"
        "Ncore d g s b native_p w=w l=l nf=ng\n.ends neutral_p\n"
        ".subckt neutral_r p n b w=1u l=1u\n.ends neutral_r\n"
        ".subckt neutral_c p n w=1u l=1u\n.ends neutral_c\n.endl typ\n")
    return {"status": "OK", "family": "neutral", "registry_family": "neutral",
        "model_lib": str(models), "typ_section": "typ",
        "role_models": {"nmos": "neutral_n", "pmos": "neutral_p", "res": "neutral_r", "cap": "neutral_c"},
        "device_terminals": {"nmos": 4, "pmos": 4, "res": 3, "cap": 2},
        "geometry_units": {role: "metric" for role in ("nmos", "pmos", "res", "cap")},
        "unresolved_roles": []}


def _render(ir, context, directory):
    return a3.render_netlist(ir, context, [], a3._resolve_params(ir, SPEC)[0], deck_dir=directory)


def test_omitted_and_false_option_preserve_every_legacy_electrical_card(tmp_path, context):
    old_library = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    old_library.pop("input_drain_cascodes")
    old_library["spec_knobs"] = [row for row in old_library["spec_knobs"]
                                if row["name"] != "ota_input_drain_cascodes"]
    for group in old_library["stage"]:
        group.pop("input_drain_cascodes", None)
    old = _build(tmp_path / "old", lib=old_library)
    omitted = _build(tmp_path / "omitted")
    disabled = _build(tmp_path / "disabled", {"knobs": {"ota_input_drain_cascodes": False}})
    for candidate in (omitted, disabled):
        assert candidate["devices"] == old["devices"]
        assert candidate["internal_nets"] == old["internal_nets"]
        assert candidate["device_param_exprs"] == old["device_param_exprs"]
        assert _render(candidate, context, tmp_path) == _render(old, context, tmp_path)
        assert "input_drain_cascodes" not in candidate


def test_enabled_expansion_precedes_sizing_and_uses_real_model_cards(tmp_path, context):
    baseline, enabled = _build(tmp_path / "baseline"), _build(tmp_path / "enabled", _sizing())
    before = {d["name"]: d for d in baseline["devices"]}
    after = {d["name"]: d for d in enabled["devices"]}
    assert set(after) - set(before) == {"mn_cas_in1", "mn_cas_ref1", "mn_cas_in2", "mn_cas_ref2", "r_cas_top", "r_cas_bottom"}
    assert {name for name in before if before[name] != after[name]} == {"mn_in1", "mn_ref1", "mn_in2", "mn_ref2"}
    for row in enabled["input_drain_cascodes"]["branches"]:
        original, cascode = after[row["source"]], after[row["cascode"]]
        assert original["nets"][0] == row["midpoint"]
        assert cascode["nets"] == [row["original_drain"], "ncas_bias", row["midpoint"], row["bulk"]]
        assert (cascode["w"], cascode["l"], cascode["ng"]) == (24, .5, 3)
    text = _render(enabled, context, tmp_path)
    assert "xmn_cas_in1 nd1_1 ncas_bias ncas_mid_in1 vss neutral_n w=24u l=0.5u ng=3" in text
    assert "xr_cas_top vdd ncas_bias vss neutral_r w=0.8u l=120u" in text
    assert "xr_cas_bottom ncas_bias vcm vss neutral_r w=0.8u l=40u" in text
    assert enabled["knobs"]["ota_input_drain_cascodes"] is True
    assert enabled["knob_sources"]["ota_input_drain_cascodes"] == "explicit_design_sizing"
    assert enabled["sizing_inputs"]["input_view"]["sha256"]
    # Compensation keeps its existing capacitor-expression/splitting path.
    overrides = a3._resolve_params(enabled, SPEC)[0]
    assert overrides["cc1"]["l"] > a3._resolve_params(baseline, SPEC)[0]["cc1"]["l"]


def _neutral():
    lib = {"ports": ["supply", "ground", "midref"],
        "spec_knobs": [{"name": "use_stack", "type": "boolean", "default": False}],
        "input_drain_cascodes": {"enable_knob": "use_stack", "bias": {
            "net": "stack_bias", "upper": "supply", "lower": "midref", "body": "ground",
            "top_device": "bias_up", "bottom_device": "bias_down"}},
        "stage": [{"count_from": "stages", "input_drain_cascodes": [
            {"source": "sense{i}", "cascode": "stack{i}", "midpoint": "join{i}"}]}]}
    devices = [{"name": "sense1", "role": "nmos", "nets": ["drain", "signal", "tail", "ground"], "w": 6, "l": 1}]
    nets = ["drain", "signal", "tail"]
    sizing = {"device_parameters": {name: {"w": 1, "l": 25} for name in ("bias_up", "bias_down")}}
    return lib, devices, nets, sizing


def test_neutral_renamed_declarations_and_bulk_are_the_only_wiring_authority():
    lib, devices, nets, sizing = _neutral()
    record = a2.expand_input_drain_cascodes(lib, {"stages": 1}, {"use_stack": True}, devices, nets, sizing)
    assert devices[0]["nets"] == ["join1", "signal", "tail", "ground"]
    assert devices[1]["nets"] == ["drain", "stack_bias", "join1", "ground"]
    assert [d["nets"] for d in devices[2:]] == [["supply", "stack_bias", "ground"], ["stack_bias", "midref", "ground"]]
    assert record["branches"][0]["source"] == "sense1"


@pytest.mark.parametrize("mutation", ["missing_target", "wrong_role", "bad_terminal_count", "duplicate_target",
    "device_alias", "midpoint_alias", "bias_net_alias", "bias_device_alias", "foreign_bias", "same_bias_endpoints",
    "malformed_branch", "missing_bias_size", "invalid_template"])
def test_malformed_targets_or_aliases_refuse_without_partial_topology_mutation(mutation):
    lib, devices, nets, sizing = _neutral()
    branch = lib["stage"][0]["input_drain_cascodes"][0]
    bias = lib["input_drain_cascodes"]["bias"]
    if mutation == "missing_target": branch["source"] = "absent{i}"
    elif mutation == "wrong_role": devices[0]["role"] = "res"
    elif mutation == "bad_terminal_count": devices[0]["nets"].pop()
    elif mutation == "duplicate_target": lib["stage"][0]["input_drain_cascodes"].append(dict(branch, cascode="another{i}", midpoint="another_join{i}"))
    elif mutation == "device_alias": branch["cascode"] = "SENSE{i}"
    elif mutation == "midpoint_alias": branch["midpoint"] = "SIGNAL"
    elif mutation == "bias_net_alias": bias["net"] = "MIDREF"
    elif mutation == "bias_device_alias": bias["bottom_device"] = "BIAS_UP"
    elif mutation == "foreign_bias": bias["upper"] = "not_declared"
    elif mutation == "same_bias_endpoints": bias["upper"] = "MIDREF"
    elif mutation == "malformed_branch": branch["extra"] = "unconsumed"
    elif mutation == "missing_bias_size": sizing["device_parameters"].pop("bias_up")
    else: branch["cascode"] = "stack{undefined}"
    before = copy.deepcopy((devices, nets))
    with pytest.raises(a2.SizingInputsInvalid):
        a2.expand_input_drain_cascodes(lib, {"stages": 1}, {"use_stack": True}, devices, nets, sizing)
    assert (devices, nets) == before


@pytest.mark.parametrize("value", [0, 1, -1, "true", None, [], {}])
def test_only_real_boolean_can_select_optional_topology(tmp_path, value):
    with pytest.raises(a2.SizingInputsInvalid, match="boolean"):
        _build(tmp_path, {"knobs": {"ota_input_drain_cascodes": value}})


def test_public_a2_producer_emits_named_gap_and_no_ir_for_invalid_option(tmp_path, monkeypatch):
    bdir = tmp_path / "phase3/analog/converter"
    bdir.mkdir(parents=True)
    required = a2.LIBRARY["delta_sigma"]["requires_bound"]
    (bdir / "spec.json").write_text(json.dumps({"specs": [
        {"name": name, "target": value, "unit": required.get(name, {}).get("unit", "")}
        for name, value in SPEC.items()]}))
    (bdir / "sizing_inputs.json").write_text(json.dumps({"knobs": {"ota_input_drain_cascodes": 1}}))
    monkeypatch.setattr(a2, "pdk_measured_params", lambda *args: (dict(MEASURED), {}))
    row = a2.emit_for_block(tmp_path, {"name": "converter", "type": "delta_sigma"}, "neutral")
    assert row["status"] == "INVALID_DESIGN_SIZING_INPUTS", row
    assert row["emitted"] is False
    assert "boolean" in row["admission_refusals"][0]["detail"]
    assert (bdir / "topology_gap.json").is_file()
    assert not (bdir / "topology.json").exists()


@pytest.mark.parametrize("name,parameter,value", [("mn_cas_in1", "ng", 0), ("mn_cas_in1", "ng", True),
    ("mn_cas_in1", "ng", 1.5), ("mn_cas_in1", "w", float("nan")), ("r_cas_top", "l", -1),
    ("mn_cas_in1", "ng", 1), ("mn_cas_in1", "l", 6)])
def test_new_devices_obey_existing_geometry_and_finger_rules(tmp_path, name, parameter, value):
    sizing = _sizing(); sizing["device_parameters"][name][parameter] = value
    with pytest.raises(a2.SizingInputsInvalid):
        _build(tmp_path, sizing,
            role_minima={"nmos": {"min_width_um": .2, "min_length_um": .1}},
            role_maxima={"nmos": {"max_width_um": 10, "max_length_um": 5}})


def test_current_reader_accepts_declared_bool_without_fabricating_emission_history(tmp_path, context, monkeypatch):
    ir = _build(tmp_path, _sizing())
    bdir = tmp_path / "phase3/analog/converter"
    (bdir / "topology.json").write_text(json.dumps(ir))
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": name, "target": value} for name, value in SPEC.items()]}))
    netlist = bdir / "converter.sp"
    netlist.write_text(_render(ir, context, bdir))
    monkeypatch.setattr(existing, "_context", lambda *args: copy.deepcopy(context))
    row = existing.validate(tmp_path, "converter", "neutral")
    assert row["status"] == "PASS", row.get("detail")
    assert row["operation"] == "validate_existing"
    assert not (bdir / "netlist_provenance.json").exists()
    original = netlist.read_text()
    for old, new in (("nd1_1 ncas_bias ncas_mid_in1", "ncas_bias nd1_1 ncas_mid_in1"),
                     ("l=120u", "l=121u"), ("w=24u l=0.5u ng=3", "w=24u l=0.5u ng=1"),
                     ("neutral_n w=24u", "foreign_model w=24u")):
        assert old in original
        netlist.write_text(original.replace(old, new))
        assert existing.validate(tmp_path, "converter", "neutral")["status"] == "FAIL"
    netlist.write_text(original)
    (bdir / "sizing_inputs.json").write_text(json.dumps(_sizing(False)))
    assert existing.validate(tmp_path, "converter", "neutral")["status"] == "FAIL"


def test_legacy_typed_reader_requires_no_new_optional_metadata(tmp_path, context, monkeypatch):
    ir = _build(tmp_path)
    ir["knobs"].pop("ota_input_drain_cascodes")
    ir["knob_sources"].pop("ota_input_drain_cascodes")
    ir["spec_knobs"] = [row for row in ir["spec_knobs"] if row["name"] != "ota_input_drain_cascodes"]
    bdir = tmp_path / "phase3/analog/converter"
    (bdir / "topology.json").write_text(json.dumps(ir))
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": name, "target": value} for name, value in SPEC.items()]}))
    (bdir / "converter.sp").write_text(_render(ir, context, bdir))
    monkeypatch.setattr(existing, "_context", lambda *args: copy.deepcopy(context))
    row = existing.validate(tmp_path, "converter", "neutral")
    assert row["status"] == "PASS", row.get("detail")
    assert not (bdir / "netlist_provenance.json").exists()


@pytest.mark.parametrize("mutation", ["baseline_enabled", "metadata_only", "partial", "wrong_cascode_gate",
    "wrong_original_drain", "wrong_resistor_end", "wrong_resistor_size", "missing_bias_sizing",
    "expression_bias_size", "stale_record", "disabled_record", "source_enable_mismatch"])
def test_normal_read_and_a3_consumers_require_actual_declared_graph(tmp_path, context, monkeypatch, mutation):
    sizing = _sizing()
    ir = _build(tmp_path, sizing)
    bdir = tmp_path / "phase3/analog/converter"
    expected_record = copy.deepcopy(ir["input_drain_cascodes"])
    if mutation in ("baseline_enabled", "metadata_only"):
        ir = _build(tmp_path / "baseline")
        ir["knobs"]["ota_input_drain_cascodes"] = True
        ir["knob_sources"]["ota_input_drain_cascodes"] = "explicit_design_sizing"
        # The original review reproducer supplies no resistor geometry.
        sizing = {"knobs": {"ota_input_drain_cascodes": True}}
        if mutation == "metadata_only":
            ir["input_drain_cascodes"] = expected_record
            sizing = _sizing()
    else:
        devices = {device["name"]: device for device in ir["devices"]}
        if mutation == "partial": ir["devices"].remove(devices["mn_cas_in1"])
        elif mutation == "wrong_cascode_gate": devices["mn_cas_in1"]["nets"][1] = "vcm"
        elif mutation == "wrong_original_drain": devices["mn_in1"]["nets"][0] = "nd1_1"
        elif mutation == "wrong_resistor_end": devices["r_cas_bottom"]["nets"][1] = "vss"
        elif mutation == "wrong_resistor_size": devices["r_cas_top"]["w"] = .9
        elif mutation == "missing_bias_sizing": del sizing["device_parameters"]["r_cas_top"]["l"]
        elif mutation == "expression_bias_size": ir["device_param_exprs"].append({"device": "r_cas_top", "param": "l", "expr": "120"})
        elif mutation == "stale_record": ir["input_drain_cascodes"]["branches"][0]["original_drain"] = "vss"
        elif mutation == "disabled_record":
            ir["knobs"]["ota_input_drain_cascodes"] = False
            sizing["knobs"]["ota_input_drain_cascodes"] = False
        else: sizing["knobs"]["ota_input_drain_cascodes"] = False
    (bdir / "sizing_inputs.json").write_text(json.dumps(sizing))
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": name, "target": value} for name, value in SPEC.items()]}))
    (bdir / "topology.json").write_text(json.dumps(ir))
    (bdir / "converter.sp").write_text(_render(ir, context, bdir))
    monkeypatch.setattr(existing, "_context", lambda *args: copy.deepcopy(context))
    # The same shared check is reached by normal A3 emission and read validation.
    assert any("INPUT_DRAIN_CASCODE_INVALID" in row for row in a3._validate_ir(ir, context, tmp_path))
    assert existing.validate(tmp_path, "converter", "neutral")["status"] == "FAIL"
    if mutation == "baseline_enabled":
        # Exercise the emission API too, with no pre-existing DUT to keep.
        (bdir / "converter.sp").unlink()
        monkeypatch.setattr(a3, "resolve_pdk_context", lambda *args: copy.deepcopy(context))
        emitted = a3.emit_for_block(tmp_path, {"name": "converter", "type": "delta_sigma"},
                                    "neutral", "", False)
        assert emitted["status"] == "IR_NOT_RENDERABLE", emitted
        assert any("INPUT_DRAIN_CASCODE_INVALID" in problem for problem in emitted["problems"])
        assert not (bdir / "converter.sp").exists()


def test_real_graph_does_not_need_an_invented_expansion_history_record(tmp_path, context, monkeypatch):
    ir = _build(tmp_path, _sizing())
    ir.pop("input_drain_cascodes")
    bdir = tmp_path / "phase3/analog/converter"
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": name, "target": value} for name, value in SPEC.items()]}))
    (bdir / "topology.json").write_text(json.dumps(ir))
    (bdir / "converter.sp").write_text(_render(ir, context, bdir))
    monkeypatch.setattr(existing, "_context", lambda *args: copy.deepcopy(context))
    assert not a3._validate_ir(ir, context, tmp_path)
    row = existing.validate(tmp_path, "converter", "neutral")
    assert row["status"] == "PASS", row.get("detail")
    assert not (bdir / "netlist_provenance.json").exists()
