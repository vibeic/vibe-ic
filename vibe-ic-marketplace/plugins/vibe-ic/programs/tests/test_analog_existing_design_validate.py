"""Current typed-DUT read validation; no emitter or native simulation runs."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_existing_design_validate as existing
import analog_a3_netlist_gen_check as gate
import _analog_a_check_common as common


@pytest.fixture
def design(tmp_path, monkeypatch):
    bdir = tmp_path / "phase3/analog/cell"
    bdir.mkdir(parents=True)
    library = tmp_path / "models.lib"
    library.write_text(".lib typ\n.subckt native_n d g s b params: w=1u l=1u\n.ends native_n\n.endl typ\n")
    context = {"status": "OK", "family": "fixture", "registry_family": "fixture",
        "model_lib": str(library), "typ_section": "typ", "role_models": {"nmos": "native_n"},
        "device_terminals": {"nmos": 4}, "geometry_units": {"nmos": "metric"}, "unresolved_roles": []}
    monkeypatch.setattr(existing, "_context", lambda *args: copy.deepcopy(context))
    ir = {"block": "cell", "block_type": "amplifier", "topology": "source-bound transistor circuit " * 8,
        "ports": ["vdd", "vss", "inp", "out"], "rails": {"positive": "vdd", "negative": "vss"},
        "internal_nets": [], "role_terminals": {"nmos": 4},
        "devices": [{"name": "mn", "role": "nmos", "nets": ["out", "inp", "vss", "vss"], "w": 2, "l": 1}],
        "device_param_exprs": [{"device": "mn", "param": "w", "expr": "gain / 5"}],
        "knobs": {"compensation_scale": 3}, "knob_sources": {"compensation_scale": "explicit_design_sizing"}}
    spec = {"specs": [{"name": "gain", "target": 10}]}
    (bdir / "topology.json").write_text(json.dumps(ir))
    (bdir / "spec.json").write_text(json.dumps(spec))
    (bdir / "sizing_inputs.json").write_text(json.dumps({"knobs": {"compensation_scale": 3}}))
    overrides, _, _, _ = existing.emitter._resolve_params(ir, existing.emitter.spec_values(spec))
    (bdir / "cell.sp").write_text(existing.emitter.render_netlist(ir, context, [], overrides, deck_dir=bdir))
    return tmp_path, bdir, library


def record(design):
    project, bdir, _ = design
    row = existing.validate(project, "cell", "fixture")
    (bdir / existing.RECEIPT).write_text(json.dumps(row))
    return row


def test_current_read_validation_discloses_actual_design_without_rewriting_emission(design):
    _, bdir, _ = design
    before = {path.name: path.read_bytes() for path in bdir.iterdir()}
    row = record(design)
    assert row["status"] == "PASS", row
    assert row["operation"] == "validate_existing" and row["device_count"] == 1
    assert row["design_content"] == "structure_and_geometry"
    assert existing.consume(bdir) == row
    assert common.netlist_content(bdir).klass == common.CONTENT_DESIGN_BOUND
    assert gate._check_block(design[0], "cell") == ("PASS", [])
    assert not (bdir / "netlist_provenance.json").exists()
    assert all((bdir / name).read_bytes() == data for name, data in before.items())


def test_current_boolean_sizing_declaration_is_read_not_reinterpreted(design):
    project, bdir, _ = design
    topology = bdir / "topology.json"
    ir = json.loads(topology.read_text())
    ir["spec_knobs"] = [{"name": "retain_existing",
                         "type": "boolean", "default": False}]
    ir["knobs"]["retain_existing"] = True
    ir["knob_sources"]["retain_existing"] = "explicit_design_sizing"
    topology.write_text(json.dumps(ir))
    (bdir / "sizing_inputs.json").write_text(json.dumps({
        "knobs": {"compensation_scale": 3, "retain_existing": True}}))
    row = existing.validate(project, "cell", "fixture")
    assert row["status"] == "PASS", row


def test_a17_reads_the_current_validation_without_manufacturing_emission_history(design):
    import analog_a8_hardmacro_emit as hardmacro
    project, bdir, _ = design
    topology = json.loads((bdir / "topology.json").read_text())
    spec = json.loads((bdir / "spec.json").read_text())
    spec.update(block="cell", interface={"pins": [{"name": port} for port in topology["ports"]]})
    (bdir / "spec.json").write_text(json.dumps(spec))
    (bdir.parent / "analog_block_list.json").write_text(json.dumps({"blocks": ["cell"]}))
    row = record(design)
    assert row["status"] == "PASS", row
    binding, why = hardmacro._declared_a3_subject_binding(project, "cell", bdir, topology)
    assert why == ""
    assert (binding or {}).get("a3_netlist_sha256") == row["inputs"]["netlist"]["sha256"]
    assert binding["source"] == "existing_design_read_validation"
    assert binding["existing_design_validation"] == str((bdir / existing.RECEIPT).relative_to(project))
    assert binding["a3_netlist_sha256"] == row["inputs"]["netlist"]["sha256"]
    assert "netlist_provenance" not in binding
    assert not (bdir / "netlist_provenance.json").exists()
    net = bdir / "cell.sp"
    net.write_text(net.read_text().replace("w=2u", "w=3u"))
    binding, why = hardmacro._declared_a3_subject_binding(project, "cell", bdir, topology)
    assert binding is None


def test_present_silent_a3_sidecar_remains_authoritative_for_a3_and_a8(design):
    import analog_a8_hardmacro_emit as hardmacro
    project, bdir, _ = design
    topology = json.loads((bdir / "topology.json").read_text())
    spec = json.loads((bdir / "spec.json").read_text())
    spec.update(block="cell", interface={"pins": [
        {"name": port} for port in topology["ports"]]})
    (bdir / "spec.json").write_text(json.dumps(spec))
    (bdir.parent / "analog_block_list.json").write_text(json.dumps({
        "blocks": ["cell"]}))
    row = record(design)
    assert row["status"] == "PASS", row
    assert existing.consume(bdir) == row

    (bdir / "netlist_provenance.json").write_text("{}")
    content = common.netlist_content(bdir)
    assert content.klass == common.CONTENT_UNDISCLOSED
    assert content.source is None
    binding, why = hardmacro._declared_a3_subject_binding(
        project, "cell", bdir, topology)
    assert binding is None
    assert why == "A3 netlist provenance names a different block"


@pytest.mark.parametrize("old,new", [
    ("w=2u", "w=3u"),
    ("out inp vss vss native_n", "inp out vss vss native_n"),
    ("out inp vss vss native_n", "out inp vss vdd native_n"),
    ("native_n w=", "wrong_model w="),
    (".subckt cell vdd vss inp out", ".subckt cell vdd vss out inp"),
    (".ends cell", "xextra out inp vss vss native_n w=2u l=1u\n.ends cell"),
    (".ends cell", "xmn out inp vss vss native_n w=2u l=1u\n.ends cell"),
])
def test_geometry_terminals_models_ports_and_exact_identities_are_checked(design, old, new):
    project, bdir, _ = design
    row = record(design)
    assert row["status"] == "PASS"
    path = bdir / "cell.sp"
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, new))
    assert existing.validate(project, "cell", "fixture")["status"] == "FAIL"
    assert existing.consume(bdir) is None
    assert common.netlist_content(bdir).klass == common.CONTENT_UNDISCLOSED


def test_equivalent_units_and_parameter_order_are_normalized(design):
    project, bdir, _ = design
    path = bdir / "cell.sp"
    path.write_text(path.read_text().replace("w=2u l=1u", "l=1000n w=0.002m"))
    assert existing.validate(project, "cell", "fixture")["status"] == "PASS"


@pytest.mark.parametrize("changed", ["model", "spec", "topology", "sizing"])
def test_cached_pass_never_stamps_changed_inputs_around_old_validation(design, changed):
    _, bdir, library = design
    assert record(design)["status"] == "PASS"
    path = {"model": library, "spec": bdir / "spec.json", "topology": bdir / "topology.json", "sizing": bdir / "sizing_inputs.json"}[changed]
    if changed == "model":
        path.write_text(path.read_text() + "* changed native model bytes\n")
    else:
        data = json.loads(path.read_text()); data["changed_current_input"] = True
        path.write_text(json.dumps(data))
    assert existing.consume(bdir) is None


def test_forged_cached_pass_is_not_current_validation(design):
    _, bdir, _ = design
    row = record(design)
    row["inputs"] = {}; row["device_count"] = 500; row["normalized_cards_sha256"] = "0" * 64
    (bdir / existing.RECEIPT).write_text(json.dumps(row))
    assert existing.consume(bdir) is None


def test_receipt_for_phase3_cannot_disclose_another_phase_dut(design):
    project, bdir, _ = design
    row = record(design)
    other = project / "phase2/analog/cell"; other.mkdir(parents=True)
    (other / "cell.sp").write_text((bdir / "cell.sp").read_text().replace("w=2u", "w=4u"))
    (other / existing.RECEIPT).write_text(json.dumps(row))
    assert existing.consume(other) is None
    assert common.netlist_content(other).klass == common.CONTENT_UNDISCLOSED


def test_recorded_ir_source_spec_must_match_the_current_spec(design):
    project, bdir, _ = design
    path = bdir / "topology.json"; ir = json.loads(path.read_text())
    ir["_provenance"] = {"inputs": [existing._view(bdir / "spec.json")]}
    path.write_text(json.dumps(ir))
    assert record(design)["status"] == "PASS"
    spec = bdir / "spec.json"; data = json.loads(spec.read_text()); data["new_source_condition"] = True
    spec.write_text(json.dumps(data))
    row = existing.validate(project, "cell", "fixture")
    assert row["status"] == "FAIL" and "recorded source" in row["detail"]


def test_existing_structure_only_disclosure_keeps_its_tier(design):
    _, bdir, _ = design
    assert record(design)["status"] == "PASS"
    (bdir / "netlist_provenance.json").write_text(json.dumps({"_provenance": {"design_content": "structure_only"}}))
    assert common.netlist_content(bdir).klass == common.CONTENT_STRUCTURE_ONLY


def test_unresolved_expression_and_inconsistent_sizing_are_refused(design):
    project, bdir, _ = design
    ir_path = bdir / "topology.json"; ir = json.loads(ir_path.read_text())
    ir["device_param_exprs"][0]["expr"] = "absent_source_value / 5"
    ir_path.write_text(json.dumps(ir))
    assert existing.validate(project, "cell", "fixture")["status"] == "FAIL"
    ir["device_param_exprs"][0]["expr"] = "gain / 5"; ir_path.write_text(json.dumps(ir))
    (bdir / "sizing_inputs.json").write_text(json.dumps({"knobs": {"compensation_scale": 2}}))
    assert existing.validate(project, "cell", "fixture")["status"] == "FAIL"


def test_expression_owned_override_cannot_be_ignored_after_raw_ir_match(design):
    project, bdir, _ = design
    path = bdir / "topology.json"; ir = json.loads(path.read_text())
    ir["devices"][0]["w"] = 3; path.write_text(json.dumps(ir))
    # The frozen DUT remains 2um, and gain/5 still resolves to 2um. Raw IR
    # equality alone used to accept this silently ignored 3um request.
    (bdir / "sizing_inputs.json").write_text(json.dumps({"device_parameters": {"mn": {"w": 3}}}))
    row = existing.validate(project, "cell", "fixture")
    assert row["status"] == "FAIL" and "expression-owned" in row["detail"]
    assert "w=2u" in (bdir / "cell.sp").read_text()


def test_allowed_direct_sizing_is_compared_with_final_resolved_geometry(design, monkeypatch):
    project, bdir, _ = design
    (bdir / "sizing_inputs.json").write_text(json.dumps({"device_parameters": {"mn": {"l": 1}}}))
    assert existing.validate(project, "cell", "fixture")["status"] == "PASS"
    resolve = existing.emitter._resolve_params
    def changed_resolution(ir, values):
        overrides, bound, nominal, env = resolve(ir, values)
        overrides.setdefault("mn", {})["l"] = 2
        return overrides, bound, nominal, env
    monkeypatch.setattr(existing.emitter, "_resolve_params", changed_resolution)
    row = existing.validate(project, "cell", "fixture")
    assert row["status"] == "FAIL" and "final resolved geometry" in row["detail"]


@pytest.mark.parametrize("value", [True, -1, float("nan")])
def test_direct_sizing_uses_existing_positive_finite_number_rules(design, value):
    project, bdir, _ = design
    (bdir / "sizing_inputs.json").write_text(json.dumps({"device_parameters": {"mn": {"l": value}}}))
    assert existing.validate(project, "cell", "fixture")["status"] == "FAIL"


def test_ideal_primitive_refusal_remains_before_content_disclosure(design):
    project, bdir, _ = design
    assert record(design)["status"] == "PASS"
    path = bdir / "cell.sp"; path.write_text(path.read_text().replace(".ends cell", "r1 out vss 1k\n.ends cell"))
    status, findings = gate._check_block(project, "cell")
    assert status == "FAIL" and findings[0]["rule"] == "A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK"
