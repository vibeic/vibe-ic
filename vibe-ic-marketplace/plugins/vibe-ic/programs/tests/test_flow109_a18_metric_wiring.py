"""A18 consumer controls with synthetic artifacts, never native qualification."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_native_flow as native


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


@pytest.fixture
def carrier(tmp_path):
    root = tmp_path
    script = put(root, "input/top.tcl", "puts synthetic-control")
    core = put(root, "phase3/analog/core/core.gds", "synthetic-core")
    pex = put(root, "phase3/analog/core/core.pex.spice", "synthetic-core-pex")
    measurement = put(root, "phase3/analog/core/a8_measurement.json", {})
    log = put(root, "phase3/analog/core/native.log", "synthetic-native-log")
    top = put(root, "top/top.gds", "synthetic-top")
    extracted = put(root, "top/top.extracted.spice", "synthetic-top-pex")
    def view(path):
        return {"path": str(path.relative_to(root)), "sha256": digest(path)}
    provenance = {"producer": "analog_a8_hardmacro_emit", "block": "core",
        "source_gds": str(core.relative_to(root)), "source_gds_sha256": digest(core),
        "views": {".gds": view(core)}, "native_measurement": {
            **view(measurement), "source_netlist": str(pex.relative_to(root)),
            "source_netlist_sha256": digest(pex), "native_log": str(log.relative_to(root)),
            "native_log_sha256": digest(log)}}
    put(root, "phase3/analog/hardmacro/core/a8_views_provenance.json", provenance)
    source = put(root, "input/route-source.txt", "synthetic-control limit VREF length <= 10 um")
    put(root, "requirements/analog_top_route/analog_sensitive_route_constraints.json", {
        "schema": "vibeic.flow109.requirement-authority.v1", "approval": {
            "status": "APPROVED", "authority": "requirements_owner", "source_reference": view(source)},
        "limits": {"VREF": {"max": 10}}, "units": {"VREF": "um"}})
    evidence = {"component_status": "PASS", "core_embedded_unchanged": True,
        "core_input_sha256": digest(core), "outputs": {
            path.name: {"sha256": digest(path)} for path in (top, extracted)},
        "checks": {"analog_top_pad_core_connectivity_errors": 0},
        "route_measurements": [{"net": "VREF", "length_um": 9, "unit": "um",
            "geometry_sha256": digest(top), "pex_sha256": digest(extracted), "pass": True}]}
    receipt = put(root, "top/a18.json", evidence)
    settings = {"implementation_script": str(script), "evidence": str(receipt),
                "outputs": [str(top), str(extracted), str(receipt)]}
    def run_case(during_execution=None, after_capture=None, omit_receipt_hash=False):
        receipt.write_text(json.dumps(evidence))
        def run(*args, **kwargs):
            if during_execution:
                during_execution()
            outputs = {str(p): digest(p) for p in (top, extracted, receipt)}
            if after_capture:
                after_capture()
            if omit_receipt_hash:
                outputs.pop(str(receipt))
            return {"returncode": 0, "missing_outputs": [], "outputs": outputs}
        return native._views("A18", root, {"name": "core"},
            {"features": {}, "config": {"analog_top": settings}}, run)
    return root, evidence, run_case


def test_positive_measured_values(carrier):
    _, _, run = carrier
    result = run()
    assert result.get("metric_acceptance", {}).get("status") == "PASS", result
    assert result["status"] == "PASS"


def test_missing_pad_core_connection_fails(carrier):
    _, evidence, run = carrier
    evidence["checks"]["analog_top_pad_core_connectivity_errors"] = 1
    result = run()
    assert result["status"] == "FAIL", result


def test_measured_route_exceeds_source_limit_fails(carrier):
    _, evidence, run = carrier
    evidence["route_measurements"][0]["length_um"] = 11
    result = run()
    assert result["status"] == "FAIL", result


@pytest.mark.parametrize("fault", ["absent_limits", "foreign_geometry", "foreign_pex",
    "absent_measurements", "wrong_unit", "nan", "negative_length", "boolean_count", "stale_a17", "missing_net"])
def test_unbound_inputs_refuse(carrier, fault):
    root, evidence, run = carrier
    row = evidence["route_measurements"][0]
    if fault == "absent_limits":
        (root / "requirements/analog_top_route/analog_sensitive_route_constraints.json").unlink()
    elif fault == "foreign_geometry":
        row["geometry_sha256"] = "f" * 64
    elif fault == "foreign_pex":
        row["pex_sha256"] = "f" * 64
    elif fault == "absent_measurements":
        evidence.pop("route_measurements")
    elif fault == "wrong_unit":
        row["unit"] = "mm"
    elif fault == "nan":
        row["length_um"] = float("nan")
    elif fault == "negative_length":
        row["length_um"] = -1
    elif fault == "boolean_count":
        evidence["checks"]["analog_top_pad_core_connectivity_errors"] = False
    elif fault == "stale_a17":
        (root / "phase3/analog/core/core.gds").write_text("changed")
    elif fault == "missing_net":
        evidence["route_measurements"] = []
    result = run()
    assert result.get("metric_acceptance", {}).get("status") == "NOT_MEASURED", result


def test_producer_failure_survives_missing_limits(carrier):
    root, evidence, run = carrier
    evidence["component_status"] = "FAIL"
    (root / "requirements/analog_top_route/analog_sensitive_route_constraints.json").unlink()
    result = run()
    assert result["status"] == "FAIL"


def test_limits_changed_during_execution_refuse(carrier):
    root, _, run = carrier
    path = root / "requirements/analog_top_route/analog_sensitive_route_constraints.json"
    def change():
        body = json.loads(path.read_text())
        body["limits"]["VREF"]["max"] = 100
        path.write_text(json.dumps(body))
    result = run(change)
    assert result.get("metric_acceptance", {}).get("status") == "NOT_MEASURED", result
    assert "NOT_PREDECLARED" in str(result["metric_acceptance"])


def test_current_output_must_match_producer_hash(carrier):
    root, _, run = carrier
    result = run(lambda: (root / "top/top.gds").write_text("foreign geometry"))
    assert result.get("metric_acceptance", {}).get("status") == "NOT_MEASURED", result
    assert "STALE" in str(result["metric_acceptance"])


@pytest.mark.parametrize("bad_route, expected", [(False, "PASS"), (True, "FAIL")])
def test_canonical_single_row_preserves_measurements_without_row_pass(carrier, monkeypatch, bad_route, expected):
    import flow109
    root, evidence, run = carrier
    if bad_route:
        evidence["route_measurements"][0]["length_um"] = 11
    observed = {**run(), "step": "A18", "block": "core"}
    monkeypatch.setattr(native, "execute_window", lambda *args: {
        "window_verdict": observed["status"], "steps": [observed]})
    context = {"requested_step": "A18", "resolved_row": {"id": "A18"},
               "context_sha256": "c" * 64}
    result = flow109._selected_step_result(root, context, native.execute(root, context), native)
    assert result.get("metric_acceptance_status") == expected, result
    assert result["default_row_status"] == ("FAIL" if bad_route else "NOT_MEASURED")
    assert result["delivery_accepted"] is False


@pytest.mark.parametrize("fault", ["changed_checks", "changed_routes", "missing_receipt_hash"])
def test_receipt_values_require_execution_bound_json(carrier, fault):
    root, evidence, run = carrier
    if fault == "changed_checks":
        evidence["checks"]["analog_top_pad_core_connectivity_errors"] = 1
    elif fault == "changed_routes":
        evidence["route_measurements"][0]["length_um"] = 11
    original_geometry = {name: digest(root / "top" / name)
                         for name in ("top.gds", "top.extracted.spice")}
    def alter_receipt():
        path = root / "top/a18.json"
        value = json.loads(path.read_text())
        value["checks"]["analog_top_pad_core_connectivity_errors"] = 0
        value["route_measurements"][0]["length_um"] = 9
        path.write_text(json.dumps(value))
    result = run(after_capture=alter_receipt if fault != "missing_receipt_hash" else None,
                 omit_receipt_hash=fault == "missing_receipt_hash")
    assert {name: digest(root / "top" / name) for name in original_geometry} == original_geometry
    assert result["metric_acceptance"]["status"] == "NOT_MEASURED", result
    assert all(row["status"] == "NOT_MEASURED"
               for row in result["metric_acceptance"]["metrics"].values()), result


def test_receipt_refusal_retains_producer_failure(carrier):
    _, evidence, run = carrier
    evidence["component_status"] = "FAIL"
    result = run(omit_receipt_hash=True)
    assert result["status"] == "FAIL", result
    assert result["metric_acceptance"]["status"] == "NOT_MEASURED", result


def test_bound_receipt_keeps_partial_not_measured(carrier):
    root, _, run = carrier
    (root / "requirements/analog_top_route/analog_sensitive_route_constraints.json").unlink()
    result = run()
    rows = result["metric_acceptance"]["metrics"]
    assert result["status"] == "PASS", result
    assert result["metric_acceptance"]["status"] == "NOT_MEASURED", result
    assert rows["analog_top_pad_core_connectivity_errors"]["status"] == "PASS", result
    assert rows["analog_sensitive_route_constraints"]["status"] == "NOT_MEASURED", result


@pytest.mark.parametrize("producer", ["positive", "retained_fail"])
def test_ordered_window_a18_actual_consumer(carrier, monkeypatch, producer):
    import os
    from types import SimpleNamespace
    import _delivery_route
    import flow109

    root, evidence, run = carrier
    if producer == "retained_fail":
        fixture = Path(__file__).parent / "fixtures/flow109_a18/ldo_ic_top_a18_evidence.json"
        receipt = Path(os.environ.get("A18_RETAINED_RECEIPT", str(fixture)))
        expected_sha256 = os.environ.get("A18_RETAINED_RECEIPT_SHA256",
            "bd14d1366e9be588c5a622df2edb3f8ce1fe6fd42145357932176cb3fcf4022b")
        assert digest(receipt) == expected_sha256
        evidence.clear()
        evidence.update(json.loads(receipt.read_text()))
        assert evidence["component_status"] == "FAIL"
        assert evidence["checks"]["analog_top_pad_core_connectivity_errors"] == 2
    features = next(p["features"] for p in flow109.load_registry()["reference_profiles"]
                    if p["name"] == "Analog IC external trim")
    manifest = put(root, "manifest.json", {"features": features})
    monkeypatch.setattr(_delivery_route, "report_label", lambda project: {"delivery_route": "IC"})
    consumed = []
    def window(project, context):
        assert context["requested_step"] == "A18"
        observed = {**run(), "step": "A18", "block": "core"}
        consumed.append(observed)
        return {"window_verdict": observed["status"], "steps": [observed]}
    monkeypatch.setattr(native, "execute_window", window)
    actual_execute = native.execute
    def upstream(project, context):
        return {"step_id": context["requested_step"], "context_sha256": context["context_sha256"],
                "component_status": "PASS", "default_row_status": "PASS", "completed": True,
                "flow109_acceptance": "PASS", "whole_flow_acceptance": "NOT_MEASURED",
                "delivery_accepted": False,
                "reason": "Synthetic prerequisite completion for A18 propagation control only"}
    def analog_execute(project, context):
        return actual_execute(project, context) if context["requested_step"] == "A18" else upstream(project, context)
    monkeypatch.setattr(native, "execute", analog_execute)
    for module in ("flow109_analog_floorplan", "pad_ring_gen"):
        monkeypatch.setitem(sys.modules, module, SimpleNamespace(execute=upstream))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode="default", entry_step="A17", exit_step="A18")
    plan = flow109.resolve_plan(features)
    context = flow109.execution_context(plan, "A17", "A18")
    assert context["dispatch_kind"] == "ordered_adapters"
    assert [row["id"] for row in context["resolved_rows"]] == ["A17", "D31", "D32", "A18"]
    rc = flow109.prepare_front_door(args, root)
    result = json.loads((root / "reports/flow109/components/A18.json").read_text())
    assert len(consumed) == 1
    assert result["native_results"]["steps"] == consumed
    assert result["component_status"] == ("FAIL" if producer == "retained_fail" else "PASS")
    assert result.get("metric_acceptance_status") == (
        "NOT_MEASURED" if producer == "retained_fail" else "PASS"), result
    assert result["metric_acceptance"]["blocks"] == [consumed[0]["metric_acceptance"]]
    assert result["flow109_acceptance"] == ("FAIL" if producer == "retained_fail" else "NOT_MEASURED")
    assert result["whole_flow_acceptance"] == "NOT_MEASURED"
    assert result["delivery_accepted"] is False
    assert rc == (1 if producer == "retained_fail" else 2)


@pytest.fixture
def completion_case(carrier, monkeypatch):
    import copy
    import shutil
    from types import SimpleNamespace
    import flow109
    import flow109_admission as admission
    import flow109_metric_acceptance as metrics
    import pad_ring_gen as pads
    import analog_hardmacro_check as packages
    import librelane_contract as launch
    import _delivery_route

    root, evidence, run = carrier
    image = "ghcr.io/vibeic/vibeic-eda@sha256:1fb01aadad86b5aea7c84cffb723f10d3b20aab7b6bf938f428a215a3233cfda"
    config = {"analog_top": {"implementation_script": str(root / "input/top.tcl"),
        "evidence": str(root / "top/a18.json"), "outputs": [str(root / "top" / name)
        for name in ("top.gds", "top.extracted.spice", "a18.json")]}}
    put(root, "input/analog_flow.json", config)
    put(root, "phase3/analog/analog_block_list.json", {"blocks": [{"name": "core", "type": "ldo"}]})
    features = copy.deepcopy(next(p["features"] for p in flow109.load_registry()["reference_profiles"]
                                 if p["name"] == "Analog IC external trim"))
    plan = flow109.resolve_plan(features)
    model_sources = {Path(native.__file__).name: digest(Path(native.__file__)),
                     Path(metrics.__file__).name: digest(Path(metrics.__file__))}
    contexts = {}
    for step in ("D03", "A17", "D31", "D32", "A18"):
        row = flow109.resolve_step(plan, step)
        uses, qualified = [], []
        reference = put(root, "reports/qualification/" + step + "-reference.txt", "SYNTHETIC SOURCE CONTROL ONLY")
        for index, use in enumerate(row["tool_uses"]):
            binary = Path(shutil.which(use["executable_name"])).resolve()
            selected = put(root, f"input/qualification/{step}-{index}.json", {
                "purpose": use["purpose"], "native_steps": use["native_steps"], "model_sources": model_sources})
            identity = {"use_id": use["use_id"], "tool_id": use["tool_id"], "version": "synthetic-control",
                "build_sha256": digest(binary), "executable": {"path": str(binary), "sha256": digest(binary)},
                "config": {"path": str(selected.relative_to(root)), "sha256": digest(selected)},
                "pdk": {"applicable": False, "reason": "synthetic source control"},
                "deck": {"applicable": False, "reason": "synthetic source control"}, "corner": "synthetic",
                "semantics": {"purpose": use["purpose"], "native_steps": use["native_steps"]}}
            record = {"use_id": use["use_id"], "status": "QUALIFIED", "identity": identity,
                      "reference_evidence": [{"path": str(reference.relative_to(root)), "sha256": digest(reference)}]}
            qualified.append(record)
            uses.append({**identity, "qualification_sha256": admission.canonical_sha(record)})
        registry = put(root, "reports/qualification/" + step + ".json", {"schema": "vibeic.flow109.qualifications.v1", "uses": qualified})
        contexts[step] = flow109.execution_context(plan, step, step, runtime_tool_uses=uses,
                                                  qualification_registry=str(registry.relative_to(root)))
        put(root, "reports/flow109/requests/" + contexts[step]["context_sha256"] + ".json", contexts[step])
    material = put(root, "reports/prerequisite-material.gds", "SYNTHETIC MATERIAL SEAM")
    material_inputs = {str(material): digest(material)}
    def native_row(step):
        return {"step": step, "block": "core", "status": "PASS",
                "input_views": native._input_views(root, "core", step),
                "output_views": {str(root / "phase3/analog/core/core.gds"): digest(root / "phase3/analog/core/core.gds")},
                "producer_context": {"image": image, "driver_sha256": digest(Path(native.__file__))}}
    def report(step, rows):
        path = root / "reports/analog_native" / ("synthetic-" + step)
        value = {"attempt": str(path), "source_sha256": digest(Path(native.__file__)),
                 "image": image, "steps": rows, "window_verdict": native._aggregate(rows)}
        put(root, str((path / "result.json").relative_to(root)), value)
        return value
    a17 = report("A17", [native_row("A17")])
    for step in ("D03", "A17", "D31", "D32"):
        body = {"step_id": step, "component_status": "PASS", "default_row_status": "PASS", "completed": True,
                "context_sha256": contexts[step]["context_sha256"], "native_results": a17,
                "inputs": [{"path": str(material), "sha256": digest(material)}] if step == "D03" else material_inputs,
                "outputs": [{"path": str(material.relative_to(root)), "sha256": digest(material)}],
                "native_db": {"top": "synthetic_top"}, "native_launch": {"image": image},
                "tools": {u["tool_id"]: {"path": u["executable"]["path"], "sha256": u["build_sha256"]}
                          for u in contexts[step]["runtime_tool_uses"]}}
        if step == "D31":
            consume_report = put(root, "reports/prerequisite-consume.json", {"status": "PASS"})
            body["outputs"].append({"path": str(consume_report.relative_to(root)), "sha256": digest(consume_report)})
        put(root, "reports/flow109/default_rows/" + step + ".json", body)
        if step == "D31":
            put(root, "reports/component.json", {k: v for k, v in body.items()
                if k not in ("default_row_status", "completed")})
    def d31_material(project, context, component):
        for view in component["outputs"]:
            flow109._current_project_ref(project, view, "SYNTHETIC_D31_GEOMETRY_STALE")
        return {"status": "PASS", "qualification": "PASS", "reason": "SYNTHETIC NATIVE MATERIAL SEAM"}
    monkeypatch.setattr(metrics, "accept_d31", d31_material)
    monkeypatch.setattr(pads, "_d32_inputs", lambda project: {"top": "synthetic_top", "inputs": {str(material): digest(material)}})
    monkeypatch.setattr(packages, "run_audit", lambda project: SimpleNamespace(summary={"design_bound_blocks": ["core"]}))
    monkeypatch.setattr(launch, "resolve_image", lambda *args, **kwargs: image)
    monkeypatch.setattr(_delivery_route, "report_label", lambda project: {"delivery_route": "IC"})
    def generate():
        observed = {**native_row("A18"), **run()}
        observed["input_views"].update({v["path"]: v["sha256"] for v in observed["native_inputs"].values()})
        invocation_log = put(root, "reports/analog_native/synthetic-A18/magic.log", "SYNTHETIC MAGIC EXECUTION SEAM")
        observed["executions"][0].update(argv=["magic", "-dnull", "-noconsole"],
            cwd=str(root / "input"), log=str(invocation_log), log_sha256=digest(invocation_log))
        observed["output_views"] = native._output_views(observed)
        return report("A18", [observed])
    current_report = generate()
    monkeypatch.setattr(native, "execute_window", lambda *args: current_report)
    def invoke():
        context = contexts["A18"]
        return flow109._selected_step_result(root, context, native.execute(root, context), native)
    return SimpleNamespace(root=root, contexts=contexts, evidence=evidence, invoke=invoke,
                           report=current_report, generate=generate, config=config, features=features)


def test_a18_completion_automatic_canonical_pass(completion_case):
    result = completion_case.invoke()
    assert result["default_row_status"] == "PASS", (result.get("reason"), result.get("detail"))
    assert result["completed"] is True and result["qualification"] == "PASS", result
    assert set(result["accepted_dependencies"]) == {"D03", "A17", "D31", "D32"}
    assert result["whole_flow_acceptance"] == "NOT_MEASURED" and result["delivery_accepted"] is False


@pytest.mark.parametrize("fault", ["missing_qualification", "stale_qualification", "stale_model",
    "missing_prerequisite", "foreign_prerequisite", "foreign_prerequisite_image", "stale_prerequisite_material", "missing_block",
    "duplicate_block", "missing_route_quantity", "stale_native_receipt"])
def test_a18_completion_refuses_incomplete_evidence(completion_case, fault):
    import copy
    import flow109
    case = completion_case
    if fault == "missing_qualification":
        case.contexts["A18"]["runtime_tool_uses"] = None
        payload = {k: v for k, v in case.contexts["A18"].items() if k != "context_sha256"}
        case.contexts["A18"]["context_sha256"] = flow109.digest(payload)
    elif fault in ("stale_qualification", "stale_model"):
        import flow109_admission as admission
        context = case.contexts["A18"]
        use = context["runtime_tool_uses"][0]
        path = case.root / use["config"]["path"]
        if fault == "stale_qualification":
            path.write_text("changed")
        else:
            value = json.loads(path.read_text());value["model_sources"] = {"foreign": "f" * 64}
            path.write_text(json.dumps(value))
            registry = case.root / context["qualification_registry"]
            data = json.loads(registry.read_text())
            use["config"]["sha256"] = digest(path)
            record = next(r for r in data["uses"] if r["use_id"] == use["use_id"])
            record["identity"]["config"] = use["config"]
            use["qualification_sha256"] = admission.canonical_sha(record)
            registry.write_text(json.dumps(data))
            context["context_sha256"] = flow109.digest({k: v for k, v in context.items() if k != "context_sha256"})
    elif fault == "missing_prerequisite":
        (case.root / "reports/flow109/default_rows/D32.json").unlink()
    elif fault == "foreign_prerequisite":
        path = case.root / "reports/flow109/default_rows/D32.json"
        body = json.loads(path.read_text());body["context_sha256"] = "f" * 64
        path.write_text(json.dumps(body))
    elif fault == "foreign_prerequisite_image":
        path = case.root / "reports/flow109/default_rows/D32.json"
        body = json.loads(path.read_text());body["native_launch"]["image"] = "foreign"
        path.write_text(json.dumps(body))
    elif fault == "stale_prerequisite_material":
        (case.root / "reports/prerequisite-material.gds").write_text("FOREIGN MATERIAL")
    elif fault in ("missing_block", "duplicate_block"):
        if fault == "missing_block":
            case.report["steps"] = []
        else:
            case.report["steps"].append(copy.deepcopy(case.report["steps"][0]))
        put(case.root, str((Path(case.report["attempt"]) / "result.json").relative_to(case.root)), case.report)
    elif fault == "missing_route_quantity":
        case.evidence["route_measurements"][0].pop("length_um")
        replacement = case.generate()
        case.report.clear();case.report.update(replacement)
    elif fault == "stale_native_receipt":
        (case.root / "top/a18.json").write_text("{}")
    result = case.invoke()
    assert result["default_row_status"] == "NOT_MEASURED", result
    assert result["completed"] is False, result


def test_a18_completion_retained_connectivity_failure(completion_case):
    case = completion_case
    fixture = Path(__file__).parent / "fixtures/flow109_a18/ldo_ic_top_a18_evidence.json"
    retained = json.loads(fixture.read_text())
    assert retained["checks"]["analog_top_pad_core_connectivity_errors"] == 2
    case.evidence.clear();case.evidence.update(retained)
    replacement = case.generate()
    case.report.clear();case.report.update(replacement)
    result = case.invoke()
    assert result["default_row_status"] == "FAIL" and result["completed"] is False, result


def test_a18_completion_non_a18_unchanged():
    component = {"step_id": "A17", "component_status": "NOT_MEASURED"}
    consume = getattr(native, "consume_default_row_completion", None)
    assert consume is None or consume(Path("/unused"), {"requested_step": "A17"}, component) is component


def test_a18_completion_front_door_automatically_finishes(completion_case):
    from types import SimpleNamespace
    import flow109
    case = completion_case
    context = case.contexts["A18"]
    manifest = put(case.root, "manifest.json", {"features": case.features,
        "runtime_tool_uses": context["runtime_tool_uses"], "qualification_registry": context["qualification_registry"]})
    args = SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode="default", entry_step="A18", exit_step="A18")
    assert flow109.prepare_front_door(args, case.root) == 0
    result = json.loads((case.root / "reports/flow109/components/A18.json").read_text())
    assert result["completed"] is True and result["default_row_status"] == "PASS", result
    assert result["whole_flow_acceptance"] == "NOT_MEASURED" and result["delivery_accepted"] is False


def test_a18_integration_completed_flag_cannot_bypass_qualification(completion_case):
    import flow109
    case = completion_case
    context = case.contexts["A18"]
    context["runtime_tool_uses"] = None
    context["context_sha256"] = flow109.digest({k: v for k, v in context.items() if k != "context_sha256"})
    component = native.execute(case.root, context)
    component.update(completed=True, default_row_status="PASS")
    result = flow109._selected_step_result(case.root, context, component, native)
    assert result["default_row_status"] == "NOT_MEASURED", result
    assert result["completed"] is False


def test_a18_integration_preserves_a17_material_reader(completion_case):
    import flow109_mixed_native as mixed
    case = completion_case
    path = case.root / "reports/flow109/default_rows/A17.json"
    manifest = {"upstream_receipts": {"A17": {"path": str(path.relative_to(case.root)), "sha256": digest(path)}}}
    (case.root / "phase3/analog/core/core.gds").write_text("FOREIGN A17 GEOMETRY")
    with pytest.raises(mixed.Refusal, match="A17_CURRENT_RESULT_INVALID"):
        mixed._accepted_upstream(case.root, manifest, "A17")


def test_a18_integration_registry_metrics_bound():
    import flow109
    row = next(row for row in flow109.load_registry()["rows"] if row["id"] == "A18")
    assert row["metric_acceptance_status"] == "IMPLEMENTED"
    assert [item["status"] for item in row["obligations"]] == ["IMPLEMENTED", "IMPLEMENTED"]
    assert row["obligations"][0]["expectation"]["value"] == 0
    assert row["obligations"][1]["expectation"]["missing_bounds"] == "BLOCKED"



def test_a18_completion_accepts_existing_window_projection(completion_case):
    case = completion_case
    path = case.root / "reports/flow109/default_rows/A17.json"
    body = json.loads(path.read_text())
    report = body["native_results"]
    body["native_results"] = {"attempt": report["attempt"], "steps": report["steps"]}
    path.write_text(json.dumps(body))
    result = case.invoke()
    assert result["default_row_status"] == "PASS", (result.get("reason"), result.get("detail"))
