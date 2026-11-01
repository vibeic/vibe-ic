from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent))

import _delivery_route
import flow109
import flow109_ip_release as D79
from programs.tests._hostpaths import require_repo
from programs.tests._release_kit import build_project, build_gds, LEF, _write_current_kit
from programs.tests.test_analog_a8_hardmacro_emit import (
    _write_native_measurement_fixture, _select_fixture_binary, _source_power_fixture,
)

DIGITAL_RUN = D79.digital_export.run


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))


def _context(project, profile="Digital hard-IP"):
    features = next(row["features"] for row in flow109.load_registry()["reference_profiles"]
                    if row["name"] == profile)
    context = flow109.execution_context(flow109.resolve_plan(features), "D79", "D79")
    _write(project / "reports/flow109/requests" / (context["context_sha256"] + ".json"), context)
    return context


def _digital(tmp_path, monkeypatch):
    project = build_project(tmp_path / "project", packages=("block_a",))
    calls = []
    def export(project_arg, root, full, pinonly, **kwargs):
        calls.append((project_arg, root, full, pinonly, kwargs))
        return 0, D79.digital_export.Record(design="block_a")
    monkeypatch.setattr(D79.digital_export, "run", export)
    monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", "/fixture/selected-pdk")
    monkeypatch.setenv("EDA_CONTAINER", "fixture-selected-runtime")
    monkeypatch.delenv("VIBEIC_ANALOG_CONTAINER", raising=False)
    return project, _context(project), calls


def _requirements(project, actual):
    payload = {name: {"required_items": items} for name, items in actual.items()}
    source = Path("input/ip_release_requirements.json")
    _write(project / source, payload)
    for name, body in payload.items():
        _write(project / f"requirements/base_49/{name}.json", {
            "schema": D79.metrics.AUTHORITY_SCHEMA, **body,
            "approval": {"status": "APPROVED", "authority": "requirements_owner",
                         "source_reference": {"path": str(source), "sha256": D79._sha(project / source)}}})


def test_registered_dispatch_uses_real_checkout_registry():
    path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json")
    registry = json.loads(path.read_text())
    row = next(row for row in registry["rows"] if row["id"] == "D79")
    profile = row["profiles"][0]
    assert profile["execution_status"] == "SOURCE_ADAPTER_IMPLEMENTED_COMPONENT_ONLY"
    assert profile["dispatch"]["adapter"] == "flow109_ip_release"
    assert profile["native_steps"]
    assert {o["expectation"]["operator"] for o in row["obligations"]} == {"covers_all"}
    assert flow109.source_owned_native_dispatch({**row, "profile": profile}) == profile["dispatch"]


def test_public_front_door_reaches_named_missing_input_without_native(tmp_path, monkeypatch):
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        if name not in D79.os.environ:
            monkeypatch.setenv(name, "")
        monkeypatch.delenv(name, raising=False)
    assert _delivery_route.admit(tmp_path, "ip") is None
    features = next(row["features"] for row in flow109.load_registry()["reference_profiles"]
                    if row["name"] == "Mapped soft-IP with prestitched scan")
    manifest = tmp_path / "manifest.json"
    _write(manifest, {"features": features})
    args = SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode="default", entry_step="D79", exit_step="D79", container="")
    assert flow109.prepare_front_door(args, tmp_path) == 2
    component = json.loads((tmp_path / "reports/flow109/components/D79.json").read_text())
    assert component["reason"] in ("D79_REQUIRED_INPUT_ABSENT", "D79_ENDPOINT_UNBOUND")
    assert component["component_status"] == "NOT_MEASURED"
    assert component["native_started"] is False


def test_digital_export_is_invoked_then_real_structural_current_and_docs_consumers_run(tmp_path, monkeypatch):
    project, context, calls = _digital(tmp_path, monkeypatch)
    result = D79.execute(project, context)
    assert result["component_status"] == "PASS", result
    assert calls == [(project, "/fixture/selected-pdk", False, False,
                      {"container": "fixture-selected-runtime", "pdk_name": "gf180mcuD"})]
    package = result["packages"][0]
    assert set(package["views"]) == {".lef", ".lib", ".gds", ".v"}
    assert package["documentation_check"]["detail"]["pin_count_cross_check"] == "AGREES"
    assert D79.consume_default_row_completion(project, context, result)["default_row_status"] == "NOT_MEASURED"
    assert result["whole_flow_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("suffix", [".lef", ".lib", ".gds", ".v"])
def test_missing_view_refuses_without_fabrication(tmp_path, monkeypatch, suffix):
    project, context, _ = _digital(tmp_path, monkeypatch)
    path = project / "phase3/stage4/hardmacro" / ("block_a" + suffix)
    path.unlink()
    result = D79.execute(project, context)
    assert (result["component_status"], result["reason"]) == ("NOT_MEASURED", "D79_VIEW_MISSING")
    assert not path.exists()


@pytest.mark.parametrize("defect", ["pins", "direction", "outline", "polarity"])
def test_present_interface_and_outline_mismatches_fail(tmp_path, monkeypatch, defect):
    project, context, _ = _digital(tmp_path, monkeypatch)
    root = project / "phase3/stage4/hardmacro"
    if defect in ("pins", "direction"):
        path = root / "block_a.v"
        before = path.read_text()
        path.write_text(before.replace("dout", "wrong_port") if defect == "pins"
                        else before.replace("output wire dout", "input wire dout"))
    elif defect == "outline":
        path = root / "block_a.lef"
        path.write_text(path.read_text().replace("SIZE 120.000 BY 80.000", "SIZE 240.000 BY 80.000"))
    else:
        path = root / "block_a.lib"
        path.write_text(path.read_text().replace("primary_power", "primary_ground"))
    result = D79.execute(project, context)
    assert result["component_status"] == "FAIL", result
    assert result["reason"] == "D79_INTERFACE_OR_OUTLINE_MISMATCH"
    assert D79.consume_default_row_completion(project, context, result)["default_row_status"] == "FAIL"


def test_current_native_receipt_is_required_beyond_structural_pass(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    (project / "phase3/stage4/hardmacro/current_kit.json").unlink()
    result = D79.execute(project, context)
    assert result["packages"][0]["checks"][0]["status"] == "PASS"
    assert result["reason"] == "D79_CURRENT_PROVENANCE_UNBOUND"
    assert result["component_status"] == "NOT_MEASURED"


def test_refused_export_cannot_be_rescued_by_preexisting_good_views(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    monkeypatch.setattr(D79.digital_export, "run", lambda *a, **k: (
        2, D79.digital_export.Record(status="SKIPPED_NO_CAPABILITY", reason="fixture unavailable")))
    result = D79.execute(project, context)
    assert (result["component_status"], result["reason"]) == ("NOT_MEASURED", "D79_NATIVE_TOOL_UNAVAILABLE")
    assert result["producer_invoked"] is True
    assert result["native_started"] is False


def test_context_and_receipt_drift_refuse(tmp_path, monkeypatch):
    project, context, calls = _digital(tmp_path, monkeypatch)
    bad = copy.deepcopy(context)
    bad["context_sha256"] = "f" * 64
    assert D79.execute(project, bad)["reason"] == "D79_CONTEXT_MISMATCH"
    assert not calls
    result = D79.execute(project, context)
    path = project / "phase3/stage4/hardmacro/block_a.lef"
    path.write_text(path.read_text() + "\n# drift\n")
    consumed = D79.consume_default_row_completion(project, context, result)
    assert consumed["default_row_status"] == "NOT_MEASURED"
    assert consumed["metric_acceptance"]["reason"] == "D79_CURRENT_PROVENANCE_UNBOUND"


def test_approved_source_bound_metrics_use_actual_views_and_constraints(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    component = D79.execute(project, context)
    actual = D79._observation(project, context, component)
    _requirements(project, actual)
    component = D79.execute(project, context)
    consumed = D79.consume_default_row_completion(project, context, component)
    assert consumed["default_row_status"] == "PASS", consumed["metric_acceptance"]
    assert consumed["whole_flow_acceptance"] == "NOT_MEASURED"
    assert consumed["delivery_accepted"] is False
    assert consumed["metric_acceptance"]["qualification"] == "NOT_CLAIMED"
    prior = copy.deepcopy(component)
    prior["default_row_status"] = "FAIL"
    assert D79.consume_default_row_completion(project, context, prior)["default_row_status"] == "FAIL"


def test_unknown_or_empty_requirement_cannot_be_echoed_as_coverage(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    component = D79.execute(project, context)
    actual = D79._observation(project, context, component)
    actual["ip_integration_limits_documented"] = [{"name": "block_a", "constraint": "ARBITRARY-KEYWORD"}]
    _requirements(project, actual)
    component = D79.execute(project, context)
    consumed = D79.consume_default_row_completion(project, context, component)
    assert consumed["default_row_status"] == "NOT_MEASURED"
    assert consumed["metric_acceptance"]["obligations"][1]["reason"] == "D79_REQUIREMENTS_UNRECOGNIZED"


@pytest.mark.parametrize("defect", ["empty", "unapproved", "source_drift", "payload_drift"])
def test_requirement_authority_must_be_nonempty_current_and_independent(tmp_path, monkeypatch, defect):
    project, context, _ = _digital(tmp_path, monkeypatch)
    result = D79.execute(project, context)
    actual = D79._observation(project, context, result)
    if defect == "empty":
        actual["ip_endpoint_views"] = []
    _requirements(project, actual)
    path = project / "requirements/base_49/ip_endpoint_views.json"
    body = json.loads(path.read_text())
    if defect == "unapproved":
        body["approval"]["status"] = "DRAFT"
    elif defect == "source_drift":
        source = project / "input/ip_release_requirements.json"
        source.write_text(source.read_text() + "\n")
    elif defect == "payload_drift":
        body["required_items"] = [{"name": "block_a", "view": ".lef"}]
    _write(path, body)
    result = D79.execute(project, context)
    consumed = D79.consume_default_row_completion(project, context, result)
    assert consumed["default_row_status"] == "NOT_MEASURED"
    assert consumed["metric_acceptance"]["obligations"][0]["status"] == "NOT_MEASURED"


def test_prior_failed_obligation_survives_later_authority_refusal(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    result = D79.execute(project, context)
    result["metric_acceptance"] = {"status": "NOT_MEASURED", "obligations": [
        {"id": "base_49.ip_endpoint_views", "status": "FAIL"}]}
    assert D79.consume_default_row_completion(project, context, result)["default_row_status"] == "FAIL"


def test_view_symlink_cannot_be_admitted(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    view = project / "phase3/stage4/hardmacro/block_a.lef"
    foreign = tmp_path / "foreign.lef"
    foreign.write_text(view.read_text())
    view.unlink()
    view.symlink_to(foreign)
    result = D79.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D79_VIEW_MISSING"


def test_multiple_signoff_candidates_refuse_before_export(tmp_path, monkeypatch):
    project, context, calls = _digital(tmp_path, monkeypatch)
    (project / "phase3/stage4/gds/unrelated.gds").write_bytes(build_gds("unrelated"))
    result = D79.execute(project, context)
    assert result["reason"] == "D79_ENDPOINT_UNBOUND"
    assert not calls


def _analog(tmp_path, monkeypatch):
    project, block, topo = _write_native_measurement_fixture(tmp_path)
    _select_fixture_binary(monkeypatch)
    build_project(project, packages=())
    topo["ports"] = ["vdd", "vss", "vin", "aux", "vout"]
    _write(block / "topology.json", topo)
    _write(block / "spec.json", {"block": "blk", "interface": {"pins": [{"name": p} for p in topo["ports"]]}})
    (block / "blk.gds").write_bytes(build_gds("blk"))
    (block / "post_layout_extracted.spice").write_text(".subckt blk vdd vss vin aux vout\n.ends blk\n")
    measurement_path = block / "a8_measurement.json"
    measurement = json.loads(measurement_path.read_text())
    measurement.update(declared_ports=topo["ports"], source_gds_sha256=D79._sha(block / "blk.gds"),
                       source_netlist_sha256=D79._sha(block / "post_layout_extracted.spice"))
    model = {"path": "/fixture/analog-pdk/sky130A/libs.tech/ngspice/fixture.lib",
             "section": "tt", "sha256": "d" * 64}
    measurement.update(model_source=model["path"], model_source_sha256=model["sha256"],
                       model_section=model["section"], model_bindings=[model])
    _write(measurement_path, measurement)
    (block / "blk.sp").write_text(f'.lib "{model["path"]}" tt\n* Synthetic A3 device source for source-only controls\n')
    monkeypatch.setattr(D79.analog_export, "_remote_sha256", lambda *a, **k: ("d" * 64, ""))
    _write(block / "netlist_provenance.json", {"block": "blk", "_provenance": {
        "design_content": "structure_and_geometry", "artifact_sha256": D79._sha(block / "blk.sp"),
        "rendered_from": {"topology_json": {"path": str((block / "topology.json").relative_to(project)),
                                            "sha256": D79._sha(block / "topology.json")},
                          "spec_json": {"path": str((block / "spec.json").relative_to(project)),
                                        "sha256": D79._sha(block / "spec.json")}}}})
    _write(project / "input/submission_template/tapeout_declaration.json", {
        "schema": "vibe-ic/tapeout_declaration/1", "answers": {"deliverable": "HARDMACRO"},
        "answer_provenance": {"deliverable": {"answered_by": "owner", "citation": "Synthetic source control"}}})
    _write(project / "reports/phase3/technology_units.json", {"pdk": "sky130A"})
    monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", "/fixture/analog-pdk")
    monkeypatch.setenv("EDA_CONTAINER", "fixture-analog-runtime")
    monkeypatch.delenv("VIBEIC_ANALOG_CONTAINER", raising=False)
    monkeypatch.setattr(D79.analog_export, "magicrc_for", lambda *a, **k:
                        "/fixture/analog-pdk/sky130A/libs.tech/magic/sky130A.magicrc")
    lef = (LEF.format(name="blk").replace("VPWR", "vdd").replace("VGND", "vss")
           .replace("clk", "vin").replace("rst_n", "aux").replace("dout", "vout")
           .replace("DIRECTION INPUT", "DIRECTION INOUT").replace("DIRECTION OUTPUT", "DIRECTION INOUT"))
    calls = []
    def native(container, command, timeout=900, *, marker=None, log_path=None):
        calls.append((container, command))
        hdir = project / "phase3/analog/hardmacro/blk"
        output = Path(re.search(r"(?m)^lef write (.+) -hide$", (hdir / marker).read_text()).group(1))
        output.write_text(lef)
        return 0, "SYNTHETIC native transport control", ""
    monkeypatch.setattr(D79.analog_export, "_docker_exec", native)
    return project, _context(project, "Analog hard-IP"), calls


def test_analog_real_emitter_and_lineage_feed_explicit_view_docs(tmp_path, monkeypatch):
    project, context, calls = _analog(tmp_path, monkeypatch)
    result = D79.execute(project, context)
    assert result["component_status"] == "PASS", result
    assert len(calls) == 1 and calls[0][0] == "fixture-analog-runtime"
    package = result["packages"][0]
    assert package["characterization_scope"]["timing_arcs"] == "NOT_MEASURED"
    assert package["documentation_check"]["detail"]["pin_count_cross_check"] == "AGREES"
    assert D79._observation(project, context, result)["ip_endpoint_views"]
    notes = (project / "phase3/stage4/documentation/ip/blk/RELEASE_NOTES.md").read_text()
    assert "reports/phase3/digital_hardmacro.json" not in notes
    assert "phase3/analog/hardmacro/blk" in notes
    _requirements(project, D79._observation(project, context, result))
    result = D79.execute(project, context)
    consumed = D79.consume_default_row_completion(project, context, result)
    assert consumed["default_row_status"] == "PASS", consumed
    assert consumed["whole_flow_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("manifest", [{"blocks": [{"name": "blk"}]},
                                     {"blocks": [{"block": "blk"}]}, ["blk"]])
def test_declared_analog_record_shapes_preserve_exact_population(tmp_path, monkeypatch, manifest):
    project, context, _ = _analog(tmp_path, monkeypatch)
    _write(project / "phase3/analog/analog_block_list.json", manifest)
    result = D79.execute(project, context)
    assert result["component_status"] == "PASS", result
    assert [row["name"] for row in result["endpoints"]] == ["blk"]


@pytest.mark.parametrize("entries", [["blk", {}], ["blk", "blk"],
                                    [{"name": "blk", "block": "other"}]])
def test_malformed_or_duplicate_analog_population_refuses(tmp_path, monkeypatch, entries):
    project, context, calls = _analog(tmp_path, monkeypatch)
    _write(project / "phase3/analog/analog_block_list.json", {"blocks": entries})
    result = D79.execute(project, context)
    assert result["reason"] == "D79_ENDPOINT_UNBOUND"
    assert result["component_status"] == "NOT_MEASURED"
    assert not calls


@pytest.mark.parametrize("defect", ["empty", "missing_gds", "stale", "stub"])
def test_analog_missing_or_unbound_inputs_never_release(tmp_path, monkeypatch, defect):
    project, context, calls = _analog(tmp_path, monkeypatch)
    if defect == "empty":
        _write(project / "phase3/analog/analog_block_list.json", {"blocks": []})
    elif defect == "missing_gds":
        (project / "phase3/analog/blk/blk.gds").unlink()
    elif defect == "stale":
        (project / "phase3/analog/blk/blk.gds").write_bytes(build_gds("blk", width_um=121))
        monkeypatch.setattr(D79.analog_export, "_native_measurement_produce", lambda *a, **k: (None, "fixture has no native producer"))
    else:
        path = project / "phase3/analog/blk/netlist_provenance.json"
        doc = json.loads(path.read_text())
        doc["_provenance"]["design_content"] = "structure_only"
        _write(path, doc)
    result = D79.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED", result
    assert not result["completed"]
    if defect in ("empty", "missing_gds", "stale"):
        assert not calls


def _refresh_records(project, component):
    for field in ("inputs", "outputs"):
        component[field] = [D79._record(project, row["path"]) for row in component[field]]
    for package in component["packages"]:
        for field in ("producer_receipts", "documents"):
            package[field] = [D79._record(project, row["path"]) for row in package.get(field, [])]
        package["views"] = {suffix: D79._record(project, row["path"])
                            for suffix, row in package["views"].items()}


@pytest.mark.parametrize("matching_claim", [False, True])
def test_recomputed_failure_defeats_rebound_caller_pass(tmp_path, monkeypatch, matching_claim):
    project, context, _ = _digital(tmp_path, monkeypatch)
    component = D79.execute(project, context)
    view = project / "phase3/stage4/hardmacro/block_a.v"
    view.write_text(view.read_text().replace("output wire dout", "input wire dout"))
    _write_current_kit(project, "block_a")
    endpoint = D79.Endpoint("digital", "block_a", ())
    if matching_claim:
        component["checks"] = [D79._digital_audit(D79.digital_check.run_audit(project))]
        component["packages"][0]["checks"] = [D79._structural(project, endpoint)]
    _refresh_records(project, component)
    result = D79.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "FAIL", result
    assert result["metric_acceptance"]["reason"] == "D79_EXISTING_CONSUMER_FAILURE"


def test_analog_failure_precedes_later_pin_refusal(tmp_path, monkeypatch):
    project, context, _ = _analog(tmp_path, monkeypatch)
    assert D79.execute(project, context)["component_status"] == "PASS"
    (project / "phase3/analog/hardmacro/blk/blk.lib").unlink()
    def later_refusal(*args, **kwargs):
        raise AssertionError("later refusal must not erase the existing FAIL")
    monkeypatch.setattr(D79.analog_pins, "run_audit", later_refusal)
    with pytest.raises(D79.D79Refusal) as exc:
        D79._audits(project, D79._endpoints(project, context))
    assert exc.value.failed is True


def test_recomputed_structural_failure_defeats_matching_caller_check(tmp_path, monkeypatch):
    project, context, _ = _analog(tmp_path, monkeypatch)
    component = D79.execute(project, context)
    root = project / "phase3/analog/hardmacro/blk"
    view = root / "blk.v"
    view.write_text(view.read_text().replace("inout vin;", "output vin;"))
    path = root / "a8_views_provenance.json"
    manifest = json.loads(path.read_text())
    manifest["views"][".v"]["sha256"] = D79._sha(view)
    _write(path, manifest)
    endpoint = D79.Endpoint("analog", "blk", ())
    assert all(row["status"] == "PASS" for row in D79._audits(project, [endpoint]))
    structural = D79._structural(project, endpoint)
    assert structural["status"] == "FAIL"
    component["packages"][0]["checks"] = [structural]
    _refresh_records(project, component)
    result = D79.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "FAIL", result
    assert result["metric_acceptance"]["reason"] == "D79_EXISTING_CONSUMER_FAILURE"


@pytest.mark.parametrize("bits", [
    'pin ("dout[0]") { direction : input; } pin ("dout[1]") { direction : output;',
    'pin ("dout[0]") { } pin ("dout[1]") { direction : output;',
])
def test_liberty_bit_directions_cannot_overwrite_one_another(tmp_path, monkeypatch, bits):
    project = build_project(tmp_path / "project", packages=("block_a",), bus_width=2)
    lib = project / "phase3/stage4/hardmacro/block_a.lib"
    lib.write_text(lib.read_text().replace("pin (dout) {", bits))
    _write_current_kit(project, "block_a")
    monkeypatch.setattr(D79.digital_export, "run", lambda *a, **k: (
        0, D79.digital_export.Record(design="block_a")))
    monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", "/fixture/selected-pdk")
    result = D79.execute(project, _context(project))
    assert result["component_status"] == "FAIL", result
    sets = result["packages"][0]["checks"][0]["detail"]["interface"]["liberty_signal_direction_sets"]
    assert len(sets["dout"]) == 2


@pytest.mark.parametrize("body", [
    'bus (dout) { direction : output; pin ("dout[0]") {} pin ("dout[1]") {} }',
    'bus (dout) { pin ("dout[0]") {} pin ("dout[1]") {} direction : output; }',
    'bus (dout) { pin ("dout[0]") { direction : output; } pin ("dout[1]") { direction : output; } }',
])
def test_valid_liberty_bus_directions_remain_valid(tmp_path, body):
    project = build_project(tmp_path / "project", packages=("block_a",), bus_width=2)
    ep = D79.Endpoint("digital", "block_a", ())
    path = ep.paths(project)[".lib"]
    text = path.read_text()
    start = text.index("    pin (dout)")
    depth, end = 1, text.index("{", start) + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    path.write_text(text[:start] + body + "\n" + text[end:])
    result = D79._structural(project, ep)
    assert result["status"] == "PASS", result
    parsed = D79.digital_check.parse_liberty(path.read_text())
    assert parsed["direction_sets"]["dout"] == {"output"}
    assert parsed["pin_direction"]["dout[0]"] == "output"


@pytest.mark.parametrize("defect", ["selected_pdk", "magic_namespace", "model_hash", "missing_models"])
def test_analog_selected_pdk_and_models_bind_before_export(tmp_path, monkeypatch, defect):
    project, context, calls = _analog(tmp_path, monkeypatch)
    if defect == "selected_pdk":
        _write(project / "reports/phase3/technology_units.json", {"pdk": "ihp-sg13g2"})
    elif defect == "magic_namespace":
        monkeypatch.setattr(D79.analog_export, "magicrc_for", lambda *a, **k:
                            "/fixture/analog-pdk/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.magicrc")
    elif defect == "model_hash":
        monkeypatch.setattr(D79.analog_export, "_remote_sha256", lambda *a: ("e" * 64, ""))
    else:
        path = project / "phase3/analog/blk/a8_measurement.json"
        value = json.loads(path.read_text())
        value.pop("model_bindings")
        _write(path, value)
    result = D79.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED", result
    assert result["reason"] in ("D79_ANALOG_PDK_UNBOUND", "D79_ANALOG_MODEL_UNBOUND")
    assert result["native_started"] is False and calls == []


def test_legitimate_layout_technology_alias_is_accepted(tmp_path, monkeypatch):
    project, context, _ = _analog(tmp_path, monkeypatch)
    block = project / "phase3/analog/blk"
    (block / "layout.mag").write_text("magic\ntech sky130\n")
    path = block / "a8_measurement.json"
    value = json.loads(path.read_text())
    value["source_layout_sha256"] = D79._sha(block / "layout.mag")
    _write(path, value)
    result = D79.execute(project, context)
    assert result["component_status"] == "PASS", result


def test_consumer_rechecks_selected_model_namespace(tmp_path, monkeypatch):
    project, context, _ = _analog(tmp_path, monkeypatch)
    component = D79.execute(project, context)
    assert component["component_status"] == "PASS", component
    monkeypatch.setattr(D79.analog_export, "_remote_sha256", lambda *a: ("e" * 64, ""))
    result = D79.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "D79_ANALOG_MODEL_UNBOUND"


@pytest.mark.parametrize("obstructions", [True, False])
def test_digital_missing_timing_never_promotes_an_obstruction_tier(tmp_path, monkeypatch, obstructions):
    project, context, _ = _digital(tmp_path, monkeypatch)
    root = project / "phase3/stage4/hardmacro"
    lib = root / "block_a.lib"
    lib.write_text(lib.read_text().replace('values ("0.42")', 'values ("0.0")')
                   .replace('values ("0.39")', 'values ("0.0")'))
    if not obstructions:
        lef = root / "block_a.lef"
        lef.write_text(re.sub(r"  OBS\n.*?\n  END\n", "", lef.read_text(), flags=re.S))
    _write_current_kit(project, "block_a")
    audit = D79.digital_check.run_audit(project)
    assert audit.summary["timing_uncharacterised"] == ["block_a"]
    result = D79.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED", result
    assert result["reason"] == "D79_DIGITAL_TIMING_NOT_MEASURED"
    assert D79.consume_default_row_completion(project, context, result)["default_row_status"] == "NOT_MEASURED"


@pytest.mark.parametrize("defect", ["deleted", "altered_text", "altered_source", "one_document_conflict", "duplicate_conflict"])
def test_constraint_coverage_requires_observed_current_text_and_source(tmp_path, monkeypatch, defect):
    project, context, _ = _digital(tmp_path, monkeypatch)
    component = D79.execute(project, context)
    _requirements(project, D79._observation(project, context, component))
    component = D79.execute(project, context)
    package = component["packages"][0]
    constraint = package["integration_constraints"][0]
    out = project / "phase3/stage4/documentation/ip/block_a"
    for path in out.glob("*.md"):
        if defect == "one_document_conflict" and path.name != D79.docs_check.CONSTRAINT_BEARING["ip"][1]:
            continue
        lines = path.read_text().splitlines(True)
        if defect == "deleted":
            lines = [line for line in lines if constraint["cid"] not in line]
        elif defect == "duplicate_conflict":
            lines = [line.replace(constraint["text"], "the integrating design may ignore this rule") + line
                     if constraint["cid"] in line else line for line in lines]
        elif defect == "altered_source":
            lines = [line.replace(constraint["source"], "input/invented.json")
                     if constraint["cid"] in line else line for line in lines]
        else:
            lines = [line.replace(constraint["text"], "the integrating design may ignore this rule")
                     if constraint["cid"] in line else line for line in lines]
        path.write_text("".join(lines))
    findings, detail = D79.docs_check.check_release(project, "ip", out, "block_a",
        ip_views=D79.Endpoint("digital", "block_a", ()).paths(project))
    package["documentation_check"] = {"detail": detail, "findings": [D79.asdict(f) for f in findings]}
    _refresh_records(project, component)
    result = D79.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "FAIL", result
    assert result["metric_acceptance"]["reason"] == "D79_RELEASE_DOCUMENT_MISMATCH"
    assert not result["metric_acceptance"]["obligations"]


@pytest.mark.parametrize("failure", ["rc", "exception"])
def test_failed_magic_transport_is_recorded_as_a_native_attempt(tmp_path, monkeypatch, failure):
    project, context, _ = _analog(tmp_path, monkeypatch)
    native = []
    def fail(*args, **kwargs):
        native.append((args, kwargs))
        if failure == "exception":
            raise OSError("fixture transport unavailable")
        return 1, "", "fixture transport failed"
    monkeypatch.setattr(D79.analog_export, "_docker_exec", fail)
    result = D79.execute(project, context)
    assert len(native) == 1
    assert result["component_status"] == "NOT_MEASURED"
    assert result["native_started"] is True
    assert result["native_attempts"] == [{"tool": "magic", "operation": "lef_export", "endpoint": "blk"}]


@pytest.mark.parametrize("failure", ["magic", "ngspice"])
def test_a8_measurement_failed_transports_retain_attempts(tmp_path, monkeypatch, failure):
    project, block, topo = _source_power_fixture(tmp_path, monkeypatch, native_rc=1)
    if failure == "magic":
        monkeypatch.setattr(D79.analog_export, "_docker_exec", lambda *a, **k: (1, "", "fixture failure"))
    attempts = []
    measurement, reason = D79.analog_export._native_measurement_produce(
        project, "blk", "", "/pdk", block / "blk.gds", topo, native_attempts=attempts)
    assert measurement is None, reason
    assert [row["tool"] for row in attempts] == (["magic"] if failure == "magic" else ["magic", "ngspice"])


def test_digital_magic_transport_reports_attempt_even_without_output(tmp_path, monkeypatch):
    gen = D79.digital_export
    project = tmp_path / "project"
    lef = project / "phase3/stage4/hardmacro/block_a.lef"
    lef.parent.mkdir(parents=True)
    gds, routed = project / "input.gds", project / "routed.def"
    gds.write_bytes(build_gds("block_a"))
    routed.write_text("DESIGN block_a ;\nEND DESIGN\n")
    calls = []
    def failed_transport(*args, **kwargs):
        calls.append(args)
        return gen._watchdog.SupervisedResult(rc=1, out="", err="fixture failure", outcome="natural", elapsed_s=0)
    monkeypatch.setattr(gen._watchdog, "run_host_supervised", failed_transport)
    attempts = []
    ok, reason = gen._write_lef_here("block_a", gds, routed, lef, "/fixture",
                                   "/fixture/tech.magicrc", False, False, 900, native_attempts=attempts)
    assert not ok and len(calls) == 1, reason
    assert attempts == [{"tool": "magic", "operation": "lef_export"}]


def test_digital_sta_failed_transport_reports_attempt(tmp_path, monkeypatch):
    gen = D79.digital_export
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "block_a_pnr.v").write_text("module block_a; endmodule\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10 clk\n")
    spef = tmp_path / "phase3/stage3/extracted/spef_corners/block_a.max.spef"
    _write(spef, '*SPEF "IEEE 1481-1998"\n')
    library = tmp_path / "input/pdk/fixture.lib"
    _write(library, "library (fixture) {}\n")
    _write(tmp_path / "reports/phase3/sta_mcorner_ocv.rpt",
           f"=== SETUP corner: process=SS liberty={library}, SPEF=block_a.max.spef ===\n")
    calls = []
    def failed_transport(*args, **kwargs):
        calls.append(args)
        return 1, "", "fixture STA failure"
    monkeypatch.setattr(gen, "_sh", failed_transport)
    text, result = gen.characterise_liberty(tmp_path, "block_a", "", tmp_path / "hm")
    assert text is None and result["characterised"] is False
    assert len(calls) == 1
    assert result["native_attempts"] == [{"tool": "sta", "operation": "write_timing_model"}]


def test_digital_current_kit_reuse_records_no_native_attempt(tmp_path, monkeypatch):
    project, context, _ = _digital(tmp_path, monkeypatch)
    gen = D79.digital_export
    routed = project / "phase3/stage3/pnr/routed.def"
    routed.write_text("VERSION 5.8 ;\nDESIGN block_a ;\nPINS 5 ;\n" + "\n".join(
        f"- {name} + NET {name} + DIRECTION {direction} + USE {use} ;"
        for name, direction, use in [("clk", "INPUT", "SIGNAL"), ("rst_n", "INPUT", "SIGNAL"),
                                     ("dout", "OUTPUT", "SIGNAL"), ("VPWR", "INOUT", "POWER"),
                                     ("VGND", "INOUT", "GROUND")]) + "\nEND PINS\nEND DESIGN\n")
    hm = project / "phase3/stage4/hardmacro"
    record = json.loads((hm / "current_kit.json").read_text())
    record["inputs"]["def"] = D79.current_kit.entry(project, routed)
    _write(hm / "current_kit.json", record)
    _write(hm / "liberty_timing.json", {"netlist": str(project / record["inputs"]["timing_netlist"]["path"])})
    monkeypatch.setattr(gen, "resolve_pdk_binding", lambda *a, **k: gen.PdkBinding(
        "gf180mcuD", project / "input/pdk", project / record["inputs"]["pdk_magicrc"]["path"]))
    monkeypatch.setattr(gen, "run", DIGITAL_RUN)
    monkeypatch.setattr(gen, "_sh", lambda *a, **k: pytest.fail("reuse launched native work"))
    result = D79.execute(project, context)
    assert result["component_status"] == "PASS", result
    assert result["native_attempts"] == [] and result["native_started"] is False


def test_explicit_analog_docs_reject_supply_misclassification(tmp_path, monkeypatch):
    project, context, _ = _analog(tmp_path, monkeypatch)
    result = D79.execute(project, context)
    assert result["component_status"] == "PASS", result
    views = D79.Endpoint("analog", "blk", ()).paths(project)
    path = views[".lib"]
    path.write_text(path.read_text().replace("primary_power", "primary_ground"))
    out = project / "phase3/stage4/documentation/ip/blk"
    findings, detail = D79.docs_check.check_release(project, "ip", out, "blk", ip_views=views)
    assert not detail["pass"]
    assert any(f.rule == "IP_SUPPLY_IDENTITY_MISMATCH" for f in findings)
