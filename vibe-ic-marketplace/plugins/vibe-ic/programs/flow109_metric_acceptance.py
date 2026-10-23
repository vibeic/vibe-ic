"""Typed runtime metric acceptance for the 109-flow registry.

This module is BLOCKING for the row whose adapter invokes it: a row is PASS
only when every applicable, source-whitelisted metric binding is current and
PASS.  It does not establish G1-G9 or whole-flow acceptance.

The registry declares obligations; it does not make arbitrary project data
executable.  Operator implementations and per-row evidence extraction are
source owned here.  Missing, stale or unsupported evidence is NOT_MEASURED,
never an implicit false, zero or empty set.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
SCHEMA = "vibeic.flow109.metric-acceptance.v1"
AUTHORITY_SCHEMA = "vibeic.flow109.requirement-authority.v1"
_HEX = re.compile(r"[0-9a-f]{64}")
_SAFE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")

# This is the executable whitelist.  A project may provide values and an
# approved authority document, but it cannot select an extractor, expression,
# Python attribute or callable.
A01_BINDINGS = {
    "base_A1.analog_specs_with_units": {
        "operator": "covers_all",
        "authority": "requirements/base_A1/analog_specs_with_units.json#/required_items",
        "item_fields": ("block", "name", "unit"),
    },
    "base_A1.required_measurements": {
        "operator": "covers_all",
        "authority": "requirements/base_A1/required_measurements.json#/required_items",
        "item_fields": ("block", "name"),
    },
}

D62_BINDINGS = {
    "base_43.fill_density_rules": {
        "operator": "within_declared_bounds",
        "authority": "requirements/base_43/fill_density_rules.json",
    },
    "base_43.fill_geometry_identity": {
        "operator": "matches_adopted_reference",
        "authority": "adopted/base_43/fill_geometry_identity.json",
    },
}


class MetricRefusal(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MetricRefusal("METRIC_VALUE_INVALID", str(exc)) from exc


def _finite_number(value: Any, *, count: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricRefusal("METRIC_TYPE_INVALID", "bool/non-numeric value is not a measurement")
    if isinstance(value, float) and not math.isfinite(value):
        raise MetricRefusal("METRIC_VALUE_INVALID", "NaN/Inf is not a measurement")
    if count and (not isinstance(value, int) or value < 0):
        raise MetricRefusal("METRIC_TYPE_INVALID", "count must be a nonnegative integer")
    return value


def _identity_complete(identity: Any) -> None:
    """Reject absent/None identity leaves; matching None never proves equality."""
    if not isinstance(identity, Mapping) or not identity:
        raise MetricRefusal("METRIC_IDENTITY_ABSENT", "typed producer/consumer identity required")
    required = ("producer", "checker", "tool_execution", "consumed_inputs",
                "requirements", "configuration")
    if any(key not in identity for key in required):
        raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", "missing required identity dimension")

    def visit(value: Any, label: str) -> None:
        if value is None:
            raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", label)
        if isinstance(value, Mapping):
            if not value:
                raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", label)
            for key, child in value.items():
                visit(child, f"{label}.{key}")
        elif isinstance(value, list):
            if not value:
                raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", label)
            for index, child in enumerate(value):
                visit(child, f"{label}[{index}]")

    visit(identity, "identity")


def evaluate_operator(operator: str, measured: Mapping[str, Any],
                      authority: Mapping[str, Any]) -> tuple[str, str]:
    """Evaluate the four registry operators with strict typed inputs."""
    if measured.get("status") == "FAIL":
        return "FAIL", str(measured.get("reason") or "measured producer/checker failure")
    if measured.get("status") != "MEASURED":
        return "NOT_MEASURED", str(measured.get("reason") or "measurement is not current")
    _identity_complete(measured.get("identity"))
    if authority.get("status") != "APPROVED":
        return "NOT_MEASURED", "approved authority absent"

    value = measured.get("value")
    if operator == "eq":
        expected = authority.get("value")
        unit = measured.get("unit")
        if unit == "count":
            _finite_number(value, count=True)
            _finite_number(expected, count=True)
        elif isinstance(value, (int, float)) or isinstance(expected, (int, float)):
            _finite_number(value)
            _finite_number(expected)
            if type(value) is not type(expected):
                raise MetricRefusal("METRIC_TYPE_INVALID", "numeric types differ")
        elif type(value) is not type(expected) or value is None:
            raise MetricRefusal("METRIC_TYPE_INVALID", "eq operands require the same concrete type")
        passed = value == expected and unit == authority.get("unit")
    elif operator == "covers_all":
        if not isinstance(value, list) or not isinstance(authority.get("required_items"), list):
            raise MetricRefusal("METRIC_TYPE_INVALID", "covers_all requires typed lists")
        required = authority["required_items"]
        if not required and authority.get("validated_absence") is not True:
            return "NOT_MEASURED", "empty required set lacks validated absence"
        actual_keys, required_keys = [_json_key(v) for v in value], [_json_key(v) for v in required]
        if len(actual_keys) != len(set(actual_keys)) or len(required_keys) != len(set(required_keys)):
            raise MetricRefusal("METRIC_VALUE_INVALID", "duplicate set item")
        passed = set(required_keys).issubset(actual_keys)
    elif operator == "matches_adopted_reference":
        reference = authority.get("reference")
        reference_identity = authority.get("reference_identity")
        _identity_complete(reference_identity)
        passed = _json_key(value) == _json_key(reference)
    elif operator == "within_declared_bounds":
        number = _finite_number(value)
        limits = authority.get("limits")
        if not isinstance(limits, Mapping) or not limits:
            return "NOT_MEASURED", "declared bounds absent"
        if measured.get("unit") != authority.get("unit") or not measured.get("unit"):
            return "NOT_MEASURED", "measurement/bounds unit mismatch"
        low, high = limits.get("min"), limits.get("max")
        if low is None and high is None:
            return "NOT_MEASURED", "neither bound is declared"
        if low is not None:
            _finite_number(low)
        if high is not None:
            _finite_number(high)
        if low is not None and high is not None and low > high:
            raise MetricRefusal("METRIC_AUTHORITY_INVALID", "minimum exceeds maximum")
        passed = (low is None or number >= low) and (high is None or number <= high)
    else:
        raise MetricRefusal("METRIC_OPERATOR_UNIMPLEMENTED", str(operator))
    return ("PASS", "expectation satisfied") if passed else ("FAIL", "measured value misses expectation")


def _safe_project_file(project: Path, relative: str) -> Path:
    path = project / relative
    if path.is_symlink() or not path.resolve().is_relative_to(project):
        raise MetricRefusal("METRIC_FOREIGN_INPUT", relative)
    return path


def _approved_authority(project: Path, reference: str,
                        expected_fields: tuple[str, ...]) -> tuple[dict, dict]:
    relative, marker, pointer = reference.partition("#/")
    if marker != "#/" or pointer != "required_items":
        raise MetricRefusal("METRIC_AUTHORITY_REF_UNIMPLEMENTED", reference)
    path = _safe_project_file(project, relative)
    if not path.is_file():
        raise MetricRefusal("METRIC_AUTHORITY_ABSENT", relative)
    raw = path.read_bytes()
    try:
        body = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", relative) from exc
    if not isinstance(body, dict):
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", relative)
    approval = body.get("approval")
    source = approval.get("source_reference") if isinstance(approval, dict) else None
    if (body.get("schema") != AUTHORITY_SCHEMA
            or approval.get("status") != "APPROVED"
            or approval.get("authority") != "requirements_owner"
            or not isinstance(source, dict)
            or not isinstance(source.get("path"), str)
            or not _HEX.fullmatch(str(source.get("sha256", "")))):
        raise MetricRefusal("METRIC_AUTHORITY_UNAPPROVED", relative)
    source_path = _safe_project_file(project, source["path"])
    if not source_path.is_file() or _sha(source_path.read_bytes()) != source["sha256"]:
        raise MetricRefusal("METRIC_AUTHORITY_STALE", source["path"])
    items = body.get("required_items")
    if not isinstance(items, list):
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "required_items must be a list")
    normalized = []
    for item in items:
        if (not isinstance(item, dict) or set(item) != set(expected_fields)
                or any(not isinstance(item[key], str) or not item[key]
                       for key in expected_fields)
                or not all(_SAFE.fullmatch(item[key]) for key in ("block", "name")
                           if key in item)):
            raise MetricRefusal("METRIC_AUTHORITY_INVALID", "required item shape")
        normalized.append({key: item[key] for key in expected_fields})
    if not normalized:
        absence = body.get("validated_absence")
        absence_source = absence.get("source_reference") if isinstance(absence, dict) else None
        if (not isinstance(absence, dict) or absence.get("status") != "VALIDATED"
                or absence.get("authority") != "requirements_owner"
                or not isinstance(absence_source, dict)
                or not isinstance(absence_source.get("path"), str)
                or not _HEX.fullmatch(str(absence_source.get("sha256", "")))):
            raise MetricRefusal("METRIC_EMPTY_SET_UNVALIDATED", relative)
        absence_path = _safe_project_file(project, absence_source["path"])
        if (not absence_path.is_file()
                or _sha(absence_path.read_bytes()) != absence_source["sha256"]):
            raise MetricRefusal("METRIC_EMPTY_SET_UNVALIDATED", absence_source["path"])
    authority = {"status": "APPROVED", "required_items": normalized,
                 "validated_absence": not normalized,
                 "approval": approval, "path": relative, "sha256": _sha(raw),
                 "source": {"path": source["path"], "sha256": source["sha256"]}}
    return authority, body


def _approved_document(project: Path, relative: str, *, authority: str,
                       schema: str) -> tuple[dict, dict]:
    path = _safe_project_file(project, relative)
    if not path.is_file():
        raise MetricRefusal("METRIC_AUTHORITY_ABSENT", relative)
    raw = path.read_bytes()
    try:
        body = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", relative) from exc
    approval = body.get("approval") if isinstance(body, dict) else None
    source = approval.get("source_reference") if isinstance(approval, dict) else None
    if (not isinstance(body, dict) or body.get("schema") != schema
            or not isinstance(approval, dict)
            or approval.get("status") != "APPROVED"
            or approval.get("authority") != authority
            or not isinstance(source, dict)
            or not isinstance(source.get("path"), str)
            or not _HEX.fullmatch(str(source.get("sha256", "")))):
        raise MetricRefusal("METRIC_AUTHORITY_UNAPPROVED", relative)
    source_path = _safe_project_file(project, source["path"])
    if not source_path.is_file() or _sha(source_path.read_bytes()) != source["sha256"]:
        raise MetricRefusal("METRIC_AUTHORITY_STALE", source["path"])
    return ({"status": "APPROVED", "path": relative, "sha256": _sha(raw),
             "source": {"path": source["path"], "sha256": source["sha256"]},
             "approval": approval}, body)


def _d62_bounds_authority(project: Path, relative: str,
                          component: Mapping[str, Any]) -> dict:
    authority, body = _approved_document(project, relative,
        authority="requirements_owner", schema=AUTHORITY_SCHEMA)
    limits, units = body.get("limits"), body.get("units")
    if (not isinstance(limits, Mapping) or not isinstance(units, str) or not units
            or (limits.get("min") is None and limits.get("max") is None)):
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "D62 limits/units")
    if limits.get("min") is not None:
        _finite_number(limits["min"])
    if limits.get("max") is not None:
        _finite_number(limits["max"])
    if (limits.get("min") is not None and limits.get("max") is not None
            and limits["min"] > limits["max"]):
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "minimum exceeds maximum")
    rules = component.get("inputs", {}).get("rules")
    if (not isinstance(rules, Mapping)
            or body.get("rules_sha256") != rules.get("sha256")):
        raise MetricRefusal("METRIC_AUTHORITY_STALE", "D62 rules identity")
    authority.update(limits=dict(limits), unit=units,
                     rules_sha256=body["rules_sha256"])
    return authority


def _d62_reference_authority(project: Path, relative: str) -> dict:
    authority, body = _approved_document(project, relative,
        authority="layout_owner", schema="vibeic.flow109.adopted-reference.v1")
    if "reference" not in body or "reference_identity" not in body:
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "D62 adopted reference")
    _identity_complete(body["reference_identity"])
    authority.update(reference=body["reference"],
                     reference_identity=body["reference_identity"])
    return authority


def _d62_measurement(project: Path, component: Mapping[str, Any],
                     context: Mapping[str, Any]) -> dict:
    if component.get("component_status") == "FAIL":
        return {"status": "FAIL", "reason": component.get("reason")}
    if component.get("component_status") != "PASS":
        return {"status": "NOT_MEASURED", "reason": "D62 component is not current PASS"}
    uses = context.get("runtime_tool_uses")
    if not isinstance(uses, list) or len(uses) != 1:
        return {"status": "NOT_MEASURED", "reason": "exact D62 tool execution identity absent"}
    from flow109_density_fill import operation_sources, validate_filled_odb
    handoff = validate_filled_odb(project, component.get("receipt"))
    if handoff != component.get("handoff"):
        raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", "D62 consumer handoff")
    receipt_path = _safe_project_file(project, component["receipt"]["path"])
    receipt = json.loads(receipt_path.read_text())
    outputs = receipt.get("outputs")
    geometry_outputs = {"filled.odb", "before.def", "filled.def", "readback.def",
                        "producer.census", "consumer.census"}
    exact_outputs = geometry_outputs | {"producer.log", "consumer.log"}
    if not isinstance(outputs, dict) or set(outputs) != exact_outputs:
        raise MetricRefusal("METRIC_EVIDENCE_ABSENT", "D62 exact native output set")
    if receipt.get("operation_sources") != operation_sources():
        raise MetricRefusal("METRIC_SOURCE_CHANGED", "D62 operation sources")
    use = uses[0]
    expected_qualification = {
        "status": "PASS", "reason": "QUALIFICATION_BINDINGS_CURRENT",
        "uses": [{"use_id": use.get("use_id"),
                  "qualification_sha256": use.get("qualification_sha256")}],
        "context_sha256": context.get("context_sha256"), "native_started": False}
    expected_tool = {key: use.get(key) for key in
                     ("tool_id", "version", "build_sha256", "executable")}
    if (receipt.get("qualification") != expected_qualification
            or receipt.get("tool") != expected_tool
            or set(receipt.get("inputs", {})) != {"input_odb", "rules", "pdk", "config", "executable"}
            or receipt.get("inputs") != component.get("inputs")
            or receipt.get("manifest") != component.get("manifest")
            or outputs != component.get("outputs")
            or receipt.get("measurements") != component.get("measurements")):
        raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", "D62 invocation/read-set identity")
    # Reference value excludes attempt-relative paths. Exact paths and the full
    # read set remain in identity, while adopted-reference comparison is stable
    # across independent executions of identical bytes.
    value = {
        "manifest_sha256": receipt["manifest"]["sha256"],
        "inputs": {name: entry["sha256"] for name, entry in receipt["inputs"].items()},
        "outputs": {name: outputs[name]["sha256"] for name in sorted(geometry_outputs)},
        "measurements": receipt["measurements"],
        "tool": receipt["tool"],
        "qualification": receipt["qualification"],
        "operation_sources": receipt["operation_sources"],
    }
    identity = {
        "producer": {"name": "flow109_density_fill._native_fill",
                     "receipt": component["receipt"]},
        "checker": {"name": "flow109_density_fill.validate_filled_odb",
                    "measurements": receipt["measurements"]},
        "tool_execution": {"context_sha256": context.get("context_sha256"),
                           "use_id": use.get("use_id"),
                           "qualification_sha256": use.get("qualification_sha256"),
                           "build_sha256": use.get("build_sha256"),
                           "executable": use.get("executable")},
        "consumed_inputs": receipt["inputs"],
        "requirements": "bound-per-obligation",
        "configuration": use.get("config"),
        "models": {"status": "NOT_APPLICABLE_TO_ODB_GEOMETRY_IDENTITY"},
        "outputs": {name: outputs[name] for name in sorted(exact_outputs)},
        "source": receipt["operation_sources"],
    }
    _identity_complete(identity)
    return {"status": "MEASURED", "value": value, "identity": identity}


def _a01_measurements(project: Path, component: Mapping[str, Any],
                      context: Mapping[str, Any]) -> tuple[dict, dict]:
    if component.get("component_status") == "FAIL":
        failure = {"status": "FAIL", "reason": component.get("reason")}
        return failure, failure
    if component.get("component_status") != "PASS":
        missing = {"status": "NOT_MEASURED", "reason": "A01 component is not current PASS"}
        return missing, missing
    blocks = component.get("blocks")
    if (not isinstance(blocks, list) or not blocks
            or any(b.get("component_status") != "PASS" or not b.get("current_emission")
                   or not b.get("source_input_bound") for b in blocks)):
        missing = {"status": "NOT_MEASURED", "reason": "current emitted block/gate proof incomplete"}
        return missing, missing
    uses = context.get("runtime_tool_uses")
    if not isinstance(uses, list) or len(uses) != 1:
        missing = {"status": "NOT_MEASURED", "reason": "exact A01 tool execution identity absent"}
        return missing, missing
    executions = component.get("executions")
    if (not isinstance(executions, list) or len(executions) != len(blocks) + 1
            or any(not isinstance(run, dict) or not isinstance(run.get("argv"), list)
                   or len(run["argv"]) < 2 for run in executions)
            or any(run.get("returncode") != 0 for run in executions)
            or Path(executions[0]["argv"][1]).name != "analog_a1_spec_emit.py"
            or any(Path(run["argv"][1]).name != "analog_a1_spec_extract_check.py"
                   for run in executions[1:])):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "A01 producer/consumer execution set")
    for relative, expected in component.get("inputs", {}).items():
        path = _safe_project_file(project, relative)
        if expected is None:
            if path.exists():
                raise MetricRefusal("METRIC_INPUT_CHANGED", relative)
        elif (not path.is_file() or not _HEX.fullmatch(str(expected))
              or _sha(path.read_bytes()) != expected):
            raise MetricRefusal("METRIC_INPUT_CHANGED", relative)
    source_identity = component.get("source_sha256")
    if not isinstance(source_identity, dict) or not source_identity:
        raise MetricRefusal("METRIC_SOURCE_IDENTITY_ABSENT", "A01 operation sources")
    for relative, expected in source_identity.items():
        path = HERE.parent / relative
        if (not path.is_file() or not _HEX.fullmatch(str(expected))
                or _sha(path.read_bytes()) != expected):
            raise MetricRefusal("METRIC_SOURCE_CHANGED", relative)
    specs, measurements = [], []
    output_identity = {}
    for block in blocks:
        name = block.get("block")
        if not isinstance(name, str) or not _SAFE.fullmatch(name):
            raise MetricRefusal("METRIC_EVIDENCE_INVALID", "block identity")
        relative = f"phase3/analog/{name}/spec.json"
        path = _safe_project_file(project, relative)
        expected = component.get("outputs", {}).get(relative)
        if not path.is_file() or not _HEX.fullmatch(str(expected or "")) or _sha(path.read_bytes()) != expected:
            raise MetricRefusal("METRIC_EVIDENCE_STALE", relative)
        body = json.loads(path.read_text())
        provenance = body.get("_provenance") if isinstance(body, dict) else None
        if (not isinstance(provenance, dict) or provenance.get("producer") != "analog_a1_spec_emit"
                or provenance.get("defaults_used") is not False
                or provenance.get("fields_defaulted") != []
                or provenance.get("ai_handoff") is not None):
            raise MetricRefusal("METRIC_EVIDENCE_UNSUPPORTED", f"partial/defaulted {relative}")
        for entry in body.get("specs", []):
            if not isinstance(entry, dict):
                raise MetricRefusal("METRIC_EVIDENCE_INVALID", relative)
            metric, unit = entry.get("name"), entry.get("unit")
            values = [entry.get(key) for key in ("min", "typ", "max", "value", "target")
                      if key in entry]
            if (not isinstance(metric, str) or not _SAFE.fullmatch(metric)
                    or not isinstance(unit, str) or not unit or not values):
                raise MetricRefusal("METRIC_EVIDENCE_INVALID", relative)
            for value in values:
                _finite_number(value)
            specs.append({"block": name, "name": metric, "unit": unit})
            measurements.append({"block": name, "name": metric})
        output_identity[relative] = expected
    if not specs:
        raise MetricRefusal("METRIC_EVIDENCE_ABSENT", "no source-owned measured fields")
    producer_reports = [{"path": path, "sha256": digest}
                        for path, digest in component.get("outputs", {}).items()
                        if path.endswith("/producer.json")]
    gate_reports = [{"path": b["gate_report"],
                     "sha256": component.get("outputs", {}).get(b["gate_report"])}
                    for b in blocks]
    for evidence in producer_reports + gate_reports:
        path = _safe_project_file(project, evidence["path"])
        if (not path.is_file() or not _HEX.fullmatch(str(evidence["sha256"] or ""))
                or _sha(path.read_bytes()) != evidence["sha256"]):
            raise MetricRefusal("METRIC_EVIDENCE_STALE", evidence["path"])
    if len(producer_reports) != 1:
        raise MetricRefusal("METRIC_EVIDENCE_ABSENT", "unique producer report")
    producer_body = json.loads(_safe_project_file(project, producer_reports[0]["path"]).read_text())
    if producer_body != component.get("producer_report"):
        raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", "producer report record")
    for block, evidence in zip(blocks, gate_reports):
        gate_body = json.loads(_safe_project_file(project, evidence["path"]).read_text())
        if gate_body != block.get("gate"):
            raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", evidence["path"])
    identity = {
        "producer": {"name": "analog_a1_spec_emit", "reports": producer_reports},
        "checker": {"name": "analog_a1_spec_extract_check",
                    "gate_reports": gate_reports},
        "tool_execution": {"context_sha256": context.get("context_sha256"),
                           "use_id": uses[0].get("use_id"),
                           "qualification_sha256": uses[0].get("qualification_sha256"),
                           "executable": uses[0].get("executable")},
        "consumed_inputs": {path: digest for path, digest in component.get("inputs", {}).items()
                            if digest is not None},
        "requirements": "bound-per-obligation",
        "configuration": uses[0].get("config"),
        "models": {"status": "NOT_APPLICABLE_TO_STRUCTURED_SPEC_BINDING"},
        "outputs": output_identity,
        "source": component.get("source_sha256"),
    }
    _identity_complete(identity)
    return ({"status": "MEASURED", "value": specs, "identity": identity},
            {"status": "MEASURED", "value": measurements, "identity": identity})


def accept_a01(project: Path, context: Mapping[str, Any],
               component: Mapping[str, Any]) -> dict:
    """Evaluate the complete, and only, currently whitelisted A01 binding."""
    project = Path(project).resolve()
    obligations = context.get("resolved_row", {}).get("obligations")
    result = {"schema": SCHEMA, "row_id": "A01", "status": "NOT_MEASURED",
              "delivery_blocked": True, "obligations": []}
    if not isinstance(obligations, list):
        result["reason"] = "METRIC_OBLIGATIONS_ABSENT"
        return result
    try:
        specs, required_measurements = _a01_measurements(project, component, context)
    except (MetricRefusal, OSError, ValueError) as exc:
        result["reason"] = getattr(exc, "code", "METRIC_EVIDENCE_INVALID")
        result["detail"] = str(exc)
        return result
    measured_by_id = {
        "base_A1.analog_specs_with_units": specs,
        "base_A1.required_measurements": required_measurements,
    }
    for obligation in obligations:
        oid = obligation.get("id") if isinstance(obligation, dict) else None
        binding = A01_BINDINGS.get(oid)
        if (binding is None or obligation.get("expectation", {}).get("operator") != binding["operator"]
                or obligation.get("expectation", {}).get("required_set_ref") != binding["authority"]):
            result["obligations"].append({"id": oid, "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        # A concrete measured failure is terminal evidence for this metric.
        # Missing authority cannot demote it to NOT_MEASURED.
        if measured_by_id[oid].get("status") == "FAIL":
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "FAIL",
                "detail": measured_by_id[oid].get("reason") or "measured component failure"})
            continue
        try:
            authority, _ = _approved_authority(project, binding["authority"], binding["item_fields"])
            measured = dict(measured_by_id[oid])
            if measured.get("status") == "MEASURED":
                measured["identity"] = dict(measured["identity"])
                measured["identity"]["requirements"] = {
                    "path": authority["path"], "sha256": authority["sha256"],
                    "source": authority["source"]}
            status, detail = evaluate_operator(binding["operator"], measured, authority)
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": status, "detail": detail,
                "measurement": measured, "authority": authority})
        except (MetricRefusal, OSError, ValueError) as exc:
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "NOT_MEASURED",
                "reason": getattr(exc, "code", "METRIC_ACCEPTANCE_REFUSED"), "detail": str(exc)})
    statuses = [item["status"] for item in result["obligations"]]
    if statuses and all(status == "PASS" for status in statuses) and len(statuses) == len(obligations):
        result.update(status="PASS", delivery_blocked=False,
                      reason="ALL_APPLICABLE_METRICS_CURRENT_AND_PASS")
    elif "FAIL" in statuses:
        result.update(status="FAIL", reason="MEASURED_METRIC_FAILURE")
    else:
        result["reason"] = "METRIC_BINDING_INCOMPLETE_OR_NOT_CURRENT"
    return result


def accept_d62(project: Path, context: Mapping[str, Any],
               component: Mapping[str, Any]) -> dict:
    """Bind the real D62 geometry receipt without inventing density signoff."""
    project = Path(project).resolve()
    obligations = context.get("resolved_row", {}).get("obligations")
    result = {"schema": SCHEMA, "row_id": "D62", "status": "NOT_MEASURED",
              "delivery_blocked": True, "obligations": []}
    if not isinstance(obligations, list):
        result["reason"] = "METRIC_OBLIGATIONS_ABSENT"
        return result
    try:
        geometry = _d62_measurement(project, component, context)
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        geometry = {"status": "NOT_MEASURED",
                    "reason": getattr(exc, "code", "METRIC_EVIDENCE_INVALID"),
                    "detail": str(exc)}
    for obligation in obligations:
        oid = obligation.get("id") if isinstance(obligation, dict) else None
        binding = D62_BINDINGS.get(oid)
        if binding is None:
            result["obligations"].append({"id": oid, "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        expectation = obligation.get("expectation", {})
        ref_key = "bounds_ref" if oid == "base_43.fill_density_rules" else "reference_ref"
        declared = str(expectation.get(ref_key, "")).partition("#/")[0]
        if expectation.get("operator") != binding["operator"] or declared != binding["authority"]:
            result["obligations"].append({"id": oid, "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        if oid == "base_43.fill_density_rules":
            try:
                authority = _d62_bounds_authority(project, binding["authority"], component)
                item = {"id": oid, "metric": obligation.get("metric"),
                        "operator": binding["operator"], "status": "NOT_MEASURED",
                        "reason": "D62_DENSITY_VALUE_NOT_MEASURED",
                        "detail": "native receipt reports geometry and fill count, not density",
                        "authority": authority}
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                item = {"id": oid, "metric": obligation.get("metric"),
                        "operator": binding["operator"], "status": "NOT_MEASURED",
                        "reason": getattr(exc, "code", "METRIC_ACCEPTANCE_REFUSED"),
                        "detail": str(exc)}
            result["obligations"].append(item)
            continue
        # Concrete native/checker failure outranks missing adopted authority.
        if geometry.get("status") == "FAIL":
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "FAIL",
                "detail": geometry.get("reason") or "measured component failure"})
            continue
        try:
            authority = _d62_reference_authority(project, binding["authority"])
            measured = dict(geometry)
            if measured.get("status") == "MEASURED":
                measured["identity"] = dict(measured["identity"])
                measured["identity"]["requirements"] = {
                    "path": authority["path"], "sha256": authority["sha256"],
                    "source": authority["source"]}
            status, detail = evaluate_operator(binding["operator"], measured, authority)
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": status, "detail": detail,
                "measurement": measured, "authority": authority})
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "NOT_MEASURED",
                "reason": getattr(exc, "code", "METRIC_ACCEPTANCE_REFUSED"),
                "detail": str(exc)})
    statuses = [item["status"] for item in result["obligations"]]
    if "FAIL" in statuses:
        result.update(status="FAIL", reason="MEASURED_METRIC_FAILURE")
    else:
        result["reason"] = "METRIC_BINDING_INCOMPLETE_OR_NOT_CURRENT"
    return result
