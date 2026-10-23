"""Runtime metric acceptance controls for the source-whitelisted A01 binding."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

import flow109
import flow109_metric_acceptance as metrics
import flow109_analog as analog
from programs.tests._hostpaths import require_repo
from test_flow109_analog_a01 import _case, _run
from test_flow109_analog_a01 import legacy_component_registry  # noqa: F401


def _identity():
    return {key: {"identity": key} for key in
            ("producer", "checker", "tool_execution", "consumed_inputs",
             "requirements", "configuration")}


def _authority(tmp_path: Path, name: str, fields: tuple[str, ...], items: list[dict]):
    source = tmp_path / "input/owner-approved-analog-requirements.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source.write_text("Owner-approved analog requirements, revision neutral-1.\n")
    relative = f"requirements/base_A1/{name}.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": metrics.AUTHORITY_SCHEMA,
        "approval": {"status": "APPROVED", "authority": "requirements_owner",
                     "source_reference": {"path": str(source.relative_to(tmp_path)),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}},
        "required_items": [{key: item[key] for key in fields} for item in items],
    }
    path.write_text(json.dumps(body, indent=2) + "\n")
    return path


def _approved_case(tmp_path: Path):
    manifest, registry = _case(tmp_path)
    _authority(tmp_path, "analog_specs_with_units", ("block", "name", "unit"),
               [{"block": "regulator_alpha", "name": "vout", "unit": "V"}])
    _authority(tmp_path, "required_measurements", ("block", "name"),
               [{"block": "regulator_alpha", "name": "vout"}])
    return manifest, registry


def _report_and_context(project: Path):
    report = json.loads((project / "reports/flow109/components/A01.json").read_text())
    request = next((project / "reports/flow109/requests").glob("*.json"))
    return report, json.loads(request.read_text())


def test_checked_in_registry_is_the_source_owned_binding_denominator():
    path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json")
    registry = json.loads(path.read_text())
    row = next(item for item in registry["rows"] if item["id"] == "A01")
    assert {item["id"] for item in row["obligations"]} == set(metrics.A01_BINDINGS)
    assert {item["expectation"]["operator"] for item in row["obligations"]} == {"covers_all"}
    assert {item["status"] for item in row["obligations"]} == {"IMPLEMENTED_A01_RUNTIME_BINDING"}
    assert row["metric_acceptance_status"] == "IMPLEMENTED_A01_RUNTIME"


def test_safe_operators_are_typed_and_fail_closed():
    ident = _identity()
    assert metrics.evaluate_operator("eq",
        {"status": "MEASURED", "value": 0, "unit": "count", "identity": ident},
        {"status": "APPROVED", "value": 0, "unit": "count"})[0] == "PASS"
    assert metrics.evaluate_operator("covers_all",
        {"status": "MEASURED", "value": ["a", "b"], "identity": ident},
        {"status": "APPROVED", "required_items": ["a"], "validated_absence": False})[0] == "PASS"
    assert metrics.evaluate_operator("within_declared_bounds",
        {"status": "MEASURED", "value": 1.5, "unit": "V", "identity": ident},
        {"status": "APPROVED", "limits": {"min": 1.0, "max": 2.0}, "unit": "V"})[0] == "PASS"
    reference_identity = _identity()
    assert metrics.evaluate_operator("matches_adopted_reference",
        {"status": "MEASURED", "value": {"digest": "a"}, "identity": ident},
        {"status": "APPROVED", "reference": {"digest": "a"},
         "reference_identity": reference_identity})[0] == "PASS"

    for bad in (True, math.nan, math.inf):
        with pytest.raises(metrics.MetricRefusal):
            metrics.evaluate_operator("eq",
                {"status": "MEASURED", "value": bad, "unit": "count", "identity": ident},
                {"status": "APPROVED", "value": 0, "unit": "count"})
    broken = _identity()
    broken["producer"] = {"digest": None}
    with pytest.raises(metrics.MetricRefusal, match="IDENTITY_INCOMPLETE"):
        metrics.evaluate_operator("eq",
            {"status": "MEASURED", "value": 0, "unit": "count", "identity": broken},
            {"status": "APPROVED", "value": 0, "unit": "count"})
    assert metrics.evaluate_operator("covers_all",
        {"status": "MEASURED", "value": [], "identity": ident},
        {"status": "APPROVED", "required_items": [], "validated_absence": False})[0] == "NOT_MEASURED"


def test_actual_front_door_producer_and_consumer_can_pass_both_a01_metrics(tmp_path):
    _approved_case(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    assert report["component_status"] == "PASS"
    assert report["metric_acceptance_status"] == "PASS"
    assert report["metric_acceptance"]["delivery_blocked"] is False
    assert [o["status"] for o in report["metric_acceptance"]["obligations"]] == ["PASS", "PASS"]
    assert report["flow109_acceptance"] == "NOT_MEASURED"
    assert all(item["measurement"]["identity"]["tool_execution"]["qualification_sha256"]
               for item in report["metric_acceptance"]["obligations"])


def test_actual_measurement_that_misses_approved_required_set_is_fail(tmp_path):
    _approved_case(tmp_path)
    path = tmp_path / "requirements/base_A1/required_measurements.json"
    body = json.loads(path.read_text())
    body["required_items"].append({"block": "regulator_alpha", "name": "gain"})
    path.write_text(json.dumps(body))
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    assert report["metric_acceptance_status"] == "FAIL"
    assert report["metric_acceptance"]["delivery_blocked"] is True


def test_actual_unmeasured_a01_component_with_valid_authority_stays_typed(tmp_path, monkeypatch):
    manifest, _ = _case(tmp_path, specs=False)
    _authority(tmp_path, "analog_specs_with_units", ("block", "name", "unit"),
               [{"block": "regulator_alpha", "name": "vout", "unit": "V"}])
    _authority(tmp_path, "required_measurements", ("block", "name"),
               [{"block": "regulator_alpha", "name": "vout"}])
    context = flow109.execution_context(flow109.resolve_plan(manifest["features"]), "A01", "A01",
        runtime_tool_uses=manifest["runtime_tool_uses"], qualification_registry="qualifications.json")
    # Obtain the real producer/gate NOT_MEASURED component without recursively
    # invoking the metric layer we are about to exercise.
    monkeypatch.setattr(analog, "accept_a01", lambda *_: {
        "status": "NOT_MEASURED", "obligations": []})
    component = analog.execute(tmp_path, context)
    assert component["component_status"] == "NOT_MEASURED"
    result = metrics.accept_a01(tmp_path, context, component)
    assert result["status"] == "NOT_MEASURED"
    assert {item["status"] for item in result["obligations"]} == {"NOT_MEASURED"}


@pytest.mark.parametrize("damage, reason", [
    ("missing", "METRIC_AUTHORITY_ABSENT"),
    ("stale", "METRIC_AUTHORITY_STALE"),
    ("ai", "METRIC_AUTHORITY_UNAPPROVED"),
])
def test_missing_stale_or_ai_owned_requirement_authority_is_not_measured(tmp_path, damage, reason):
    _approved_case(tmp_path)
    path = tmp_path / "requirements/base_A1/analog_specs_with_units.json"
    if damage == "missing":
        path.unlink()
    elif damage == "stale":
        (tmp_path / "input/owner-approved-analog-requirements.md").write_text("changed\n")
    else:
        body = json.loads(path.read_text())
        body["approval"]["authority"] = "AI"
        path.write_text(json.dumps(body))
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    acceptance = report["metric_acceptance"]
    assert acceptance["status"] == "NOT_MEASURED" and acceptance["delivery_blocked"]
    assert reason in {o.get("reason") for o in acceptance["obligations"]}


def test_corrupted_current_output_and_false_producer_cannot_pass(tmp_path):
    _approved_case(tmp_path)
    assert _run(tmp_path).returncode == 0
    report, context = _report_and_context(tmp_path)
    spec = tmp_path / "phase3/analog/regulator_alpha/spec.json"
    spec.write_text(spec.read_text().replace('"target": 1.8', '"target": 1.7'))
    stale = metrics.accept_a01(tmp_path, context, report)
    assert stale["status"] == "NOT_MEASURED" and stale["reason"] == "METRIC_EVIDENCE_STALE"

    false = copy.deepcopy(report)
    false["component_status"] = "FAIL"
    false["reason"] = "A01_PRODUCER_FAILED"
    failed = metrics.accept_a01(tmp_path, context, false)
    assert failed["status"] == "FAIL"
    assert {o["status"] for o in failed["obligations"]} == {"FAIL"}


def test_source_whitelist_reverse_guard_keeps_unknown_obligation_unimplemented(tmp_path, monkeypatch):
    _approved_case(tmp_path)
    assert _run(tmp_path).returncode == 0
    report, context = _report_and_context(tmp_path)
    monkeypatch.delitem(metrics.A01_BINDINGS, "base_A1.required_measurements")
    reversed_result = metrics.accept_a01(tmp_path, context, report)
    assert reversed_result["status"] == "NOT_MEASURED"
    assert any(o["status"] == "UNIMPLEMENTED_METRIC_BINDING"
               for o in reversed_result["obligations"])
