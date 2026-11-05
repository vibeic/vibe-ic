"""A18 consumer controls with synthetic artifacts, never native qualification."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_native_flow as native
from programs.tests.test_analog_macro_top import declaration

RUN_RECORD = "reports/phase3/analog_macro_top_run.json"


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
    declaration(root)
    core = put(root, "phase3/analog/core/core.gds", "synthetic-core")
    l9_path = root / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text())
    l9["macros"]["stage_alpha"]["gds"] = str(core.relative_to(root))
    l9_path.write_text(json.dumps(l9))
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
            "status": "APPROVED", "authority": "requirements_owner", 'approver': 'neutral-requirements-reviewer', "source_reference": view(source)},
        "limits": {"VREF": {"max": 10}}, "units": {"VREF": "um"}})
    evidence = {"component_status": "PASS", "core_embedded_unchanged": True,
        "core_inputs_sha256": {str(core): digest(core)}, "outputs": {str(path): digest(path) for path in (top, extracted)},
        "checks": {"analog_top_pad_core_connectivity_errors": 0},
        "route_measurements": [{"net": "VREF", "length_um": 9, "unit": "um",
            "geometry_sha256": digest(top), "pex_sha256": digest(extracted), "pass": True}]}
    receipt = put(root, RUN_RECORD, evidence)
    settings = {}
    def run_case(during_execution=None, after_capture=None, omit_receipt_hash=False):
        receipt.write_text(json.dumps(evidence))
        def run(*args, **kwargs):
            if during_execution:
                during_execution()
            from analog_macro_top_gen import RECORD
            evidence.update(producer="analog_macro_top_run", generation_sha256=digest(root / RECORD))
            import shutil
            evidence["native_tools"] = {name: {"path": str(Path(shutil.which(name)).resolve()), "sha256": digest(Path(shutil.which(name)).resolve())} for name in ("python3", "openroad")}
            receipt.write_text(json.dumps(evidence))
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
        path = root / RUN_RECORD
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












def test_a18_completion_non_a18_unchanged():
    component = {"step_id": "A17", "component_status": "NOT_MEASURED"}
    consume = getattr(native, "consume_default_row_completion", None)
    assert consume is None or consume(Path("/unused"), {"requested_step": "A17"}, component) is component
