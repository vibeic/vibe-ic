"""Normal folded graph controls; synthetic references never qualify an ADC."""
import copy
import hashlib
import json
import shutil

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
from test_pr3511_typed_a2_a3_residual import SPEC, MEASURED, _context, _matched_build
from _hostpaths import require_repo

SELECTOR = "ota_folded_cascode_first_stage"


def inputs(project):
    sizing = {"knobs": {SELECTOR: True}, "device_parameters": {}}
    for index in (1, 2):
        for name, w, l in [("mn_tail", 8, 1), ("mn_in", 48, 1), ("mn_ref", 48, 1),
                ("mp_fc_top_in", 192, 1), ("mp_fc_top_ref", 192, 1),
                ("mp_fc_in", 64, 1), ("mp_fc_ref", 64, 1),
                ("mn_fc_load_in", 48, 2), ("mn_fc_load_ref", 48, 2),
                ("mn_fc_cas_in", 48, 2), ("mn_fc_cas_ref", 48, 2)]:
            sizing["device_parameters"][name + str(index)] = {"w": w, "l": l}
    for name, w, l in [("mp_fc_bias", 16, 1), ("mn_fc_bias_sink", .5, 1),
            ("mp_fc_bias_source", 16, 1), ("mn_fc_bias", 12, 2),
            ("r_fc_p_shift", .5, 56.11), ("r_fc_n_shift", .5, 56.11)]:
        sizing["device_parameters"][name] = {"w": w, "l": l}
    evidence = project / "input/topology_evidence"
    evidence.mkdir(parents=True)
    refs = {"decision": {"scope": "synthetic source-control decision"},
        "parent_history": {"iterations": [{"iter": i, "changes": "synthetic retained failure",
                                            "tt_pass": False} for i in range(5)]},
        "device_characterization": {"scope": "synthetic source-binding fixture, no electrical qualification"}}
    sizing["topology_evidence"] = {}
    for role, data in refs.items():
        path = evidence / (role + ".json")
        path.write_text(json.dumps(data))
        sizing["topology_evidence"][role] = {"path": str(path.relative_to(project)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return sizing


def build(project, sizing=None, lib=None):
    return _matched_build(project, inputs(project) if sizing is None else sizing, lib)


def test_unselected_graph_and_full_source_unchanged(tmp_path):
    lib = copy.deepcopy(a2.LIBRARY["delta_sigma"])
    lib.pop("folded_first_stage")
    lib["spec_knobs"] = [k for k in lib["spec_knobs"] if k["name"] != SELECTOR]
    for group in a2._stage_groups(lib):
        group.pop("folded_first_stage", None)
    current = _matched_build(tmp_path / "same", {})
    previous = _matched_build(tmp_path / "same", {}, lib)
    for ir in (current, previous):
        ir.pop("_provenance")
    assert current == previous
    ctx = _context(tmp_path)
    assert a3.render_netlist(current, ctx, [], a3._resolve_params(current, SPEC)[0]) == a3.render_netlist(
        previous, ctx, [], a3._resolve_params(previous, SPEC)[0])


def test_explicit_false_preserves_original_physical_graph(tmp_path):
    absent = _matched_build(tmp_path / "absent", {})
    disabled = _matched_build(tmp_path / "disabled", {"knobs": {SELECTOR: False}})
    assert absent["devices"] == disabled["devices"]
    assert absent["ports"] == disabled["ports"]
    assert "folded_first_stage" not in disabled


def test_actual_normal_folded_graph_body_and_geometry_render(tmp_path):
    base = _matched_build(tmp_path / "base", {})
    project = tmp_path / "enabled"
    ir = build(project)
    assert not a3._validate_ir(ir, _context(tmp_path), project)
    audit = ir["folded_first_stage"]
    assert len(audit["expanded_devices"]) == 28
    folded_bias_cards = [card for row in ir["ota_bias_network"]["stage_table"]
                         for card in row["folded_cards"]]
    assert len(folded_bias_cards) == 6
    assert len(ir["devices"]) == len(base["devices"]) + 18 + len(folded_bias_cards)
    before = {d["name"]: d for d in base["devices"]}
    after = {d["name"]: d for d in ir["devices"]}
    removed = {f"mp_ld{leg}_{i}" for leg in (1, 2) for i in (1, 2)}
    assert set(before) - set(after) == removed
    bias_cards = {name for row in ir["ota_bias_network"]["stage_table"]
                  for name in row["translator_devices"]}
    for name in before.keys() & after.keys():
        if name not in bias_cards | {f"mn_{kind}{i}" for kind in ("in", "ref") for i in (1, 2)}:
            assert before[name] == after[name]
    for name in bias_cards:
        assert before[name]["role"] == after[name]["role"]
        assert before[name]["nets"] == after[name]["nets"]
    assert ir["ports"] == base["ports"]
    assert ir["device_param_exprs"] == base["device_param_exprs"]
    assert audit["evidence"]["parent_history_entries"] == 5
    assert audit["evidence"]["new_sizing_budget"] is False
    assert audit["geometry_status"] == "DESIGN_INPUT_SEED_NOT_MEASURED"
    assert audit["evidence"]["characterization_status"] == "REFERENCE_BOUND_NOT_QUALIFIED"
    assert len(audit["independent_sizing_inputs"]) == 57
    text = a3.render_netlist(ir, _context(tmp_path), [], a3._resolve_params(ir, SPEC)[0],
                              deck_dir=project / "phase3/analog/converter")
    cards = {s.split()[0].casefold(): s for s in text.splitlines() if s.lower().startswith("x")}
    for d in audit["expanded_devices"]:
        card = cards["x" + d["name"].casefold()]
        assert card.split()[1:1 + len(d["nets"])] == d["nets"]
    assert not any(s.lower().startswith("vfc") for s in text.splitlines())


@pytest.mark.parametrize("value", [1, 0, "true", None, [], {}])
def test_nonboolean_folded_selection_refuses(tmp_path, value):
    sizing = inputs(tmp_path)
    sizing["knobs"][SELECTOR] = value
    with pytest.raises(a2.SizingInputsInvalid, match="boolean"):
        build(tmp_path, sizing)


def test_unknown_selection_and_mutual_exclusion_refuse(tmp_path):
    with pytest.raises(a2.SizingInputsInvalid, match="unknown sizing knob"):
        build(tmp_path / "unknown", {"knobs": {"unknown_first_stage": True}})
    sizing = inputs(tmp_path / "conflict")
    sizing["knobs"]["ota_input_drain_cascodes"] = True
    with pytest.raises(a2.SizingInputsInvalid, match="mutually exclusive"):
        build(tmp_path / "conflict", sizing)


@pytest.mark.parametrize("name", ["r_fc_p_shift", "r_fc_n_shift", "mn_fc_bias", "mn_in1"])
def test_missing_physical_geometry_refuses_before_emission(tmp_path, name):
    sizing = inputs(tmp_path)
    del sizing["device_parameters"][name]
    with pytest.raises(a2.SizingInputsInvalid, match="explicit w/l"):
        build(tmp_path, sizing)


@pytest.mark.parametrize("role", ["decision", "parent_history", "device_characterization"])
def test_missing_or_stale_topology_evidence_refuses(tmp_path, role):
    sizing = inputs(tmp_path)
    sizing["topology_evidence"][role] = None
    with pytest.raises(a2.SizingInputsInvalid, match="missing or invalid"):
        build(tmp_path, sizing)


@pytest.mark.parametrize("kind", ["endpoint", "body", "geometry", "record", "removed"])
def test_actual_a3_rejects_selected_graph_tampering(tmp_path, kind):
    ir = build(tmp_path)
    d = next(d for d in ir["devices"] if d["name"] == "mp_fc_in1")
    if kind == "endpoint":
        d["nets"][0] = "nd2_1"
    elif kind == "body":
        d["nets"][3] = "vss"
    elif kind == "geometry":
        d["w"] *= 2
    elif kind == "record":
        ir["folded_first_stage"]["source_ratios"][0]["w_over_l_ratio"] = 2
    else:
        ir["devices"].append(ir["folded_first_stage"]["before_devices"][0])
    assert any("folded" in p for p in a3._validate_ir(ir, _context(tmp_path), tmp_path))


def test_source_owned_matching_and_ratio_controls_refuse(tmp_path):
    sizing = inputs(tmp_path / "pair")
    sizing["device_parameters"]["mp_fc_top_in1"]["w"] = 193
    with pytest.raises(a2.SizingInputsInvalid, match="matched geometry"):
        build(tmp_path / "pair", sizing)
    sizing = inputs(tmp_path / "ratio")
    sizing["device_parameters"]["mn_fc_bias_sink"]["w"] = .6
    with pytest.raises(a2.SizingInputsInvalid, match="source-owned W/L ratio"):
        build(tmp_path / "ratio", sizing)


@pytest.mark.parametrize("kind", ["characterization", "input"])
def test_actual_a3_rejects_stale_current_files(tmp_path, kind):
    ir = build(tmp_path)
    path = (tmp_path / "input/topology_evidence/device_characterization.json" if kind == "characterization"
            else tmp_path / "phase3/analog/converter/sizing_inputs.json")
    path.write_text(path.read_text() + " ")
    assert a2.folded_first_stage_problems(ir, tmp_path)


def test_empty_history_and_outside_project_reference_refuse(tmp_path):
    project = tmp_path / "empty"
    sizing = inputs(project)
    path = project / sizing["topology_evidence"]["parent_history"]["path"]
    path.write_text('{"iterations":[]}')
    sizing["topology_evidence"]["parent_history"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(a2.SizingInputsInvalid, match="nonempty original parent history"):
        build(project, sizing)
    project = tmp_path / "outside"
    sizing = inputs(project)
    path = tmp_path / "outside-ref.json"
    path.write_text('{}')
    sizing["topology_evidence"]["decision"] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    with pytest.raises(a2.SizingInputsInvalid, match="outside project"):
        build(project, sizing)


def test_empty_characterization_and_symlink_references_refuse(tmp_path):
    project = tmp_path / "empty-characterization"
    sizing = inputs(project)
    ref = sizing["topology_evidence"]["device_characterization"]
    path = project / ref["path"]
    path.write_bytes(b"")
    ref["sha256"] = hashlib.sha256(b"").hexdigest()
    with pytest.raises(a2.SizingInputsInvalid, match="absent"):
        build(project, sizing)


def test_normal_emitter_returns_honest_gap_for_missing_characterization(tmp_path):
    sizing = inputs(tmp_path)
    sizing["topology_evidence"]["device_characterization"] = None
    block = tmp_path / "phase3/analog/converter"
    block.mkdir(parents=True)
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "stage_analog_on_pass_review", "accept_adc_conv", "phase3", "analog",
        "delta_sigma", "spec.json")
    shutil.copy2(source, block / "spec.json")
    (block / "sizing_inputs.json").write_text(json.dumps(sizing))
    record = a2.emit_for_block(tmp_path, {"name": "converter", "type": "delta_sigma"}, "ihp-sg13g2")
    assert record["status"] == "INVALID_SIZING_INPUT"
    assert "device_characterization" in record["admission_refusals"][0]["detail"]
    assert record["emitted"] is False
    assert (block / "topology_gap.json").is_file()
    assert not (block / "topology.json").exists()
    project = tmp_path / "symlink"
    sizing = inputs(project)
    ref = sizing["topology_evidence"]["decision"]
    original = project / ref["path"]
    alias = original.with_name("alias.json")
    alias.symlink_to(original)
    ref["path"] = str(alias.relative_to(project))
    with pytest.raises(a2.SizingInputsInvalid, match="absent"):
        build(project, sizing)
