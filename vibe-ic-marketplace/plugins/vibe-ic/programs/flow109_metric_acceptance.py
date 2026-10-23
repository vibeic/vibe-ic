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

import csv
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
    "base_43.fill_keepout_violations": {
        "operator": "eq",
        "authority": "requirements/base_43/fill_keepout_violations.json",
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
                          inputs: Mapping[str, Any]) -> dict:
    authority, body = _approved_document(project, relative,
        authority="requirements_owner", schema=AUTHORITY_SCHEMA)
    limits, scope = body.get("limits"), body.get("scope")
    if not isinstance(limits, Mapping) or not limits or body.get("units") != "ratio":
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "D62 per-layer ratio limits")
    normalized = {}
    for layer, band in limits.items():
        if (not isinstance(layer, str) or not _SAFE.fullmatch(layer)
                or not isinstance(band, Mapping) or set(band) != {"min", "max"}
                or (band.get("min") is None and band.get("max") is None)):
            raise MetricRefusal("METRIC_AUTHORITY_INVALID", "D62 per-layer band shape")
        low, high = band.get("min"), band.get("max")
        if low is not None:
            _finite_number(low)
        if high is not None:
            _finite_number(high)
        if low is not None and high is not None and low > high:
            raise MetricRefusal("METRIC_AUTHORITY_INVALID", f"{layer}: minimum exceeds maximum")
        if ((low is not None and not 0.0 <= low <= 1.0)
                or (high is not None and not 0.0 <= high <= 1.0)):
            raise MetricRefusal("METRIC_AUTHORITY_INVALID", f"{layer}: density outside [0,1]")
        normalized[layer] = {"min": low, "max": high}
    if (not isinstance(scope, Mapping) or scope.get("area") != "core"
            or scope.get("kind") != "tiled_windows"):
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "D62 density scope")
    window, step = scope.get("window_um"), scope.get("step_um")
    min_width, min_height = scope.get("minimum_core_dimensions_um", [None, None]) \
        if isinstance(scope.get("minimum_core_dimensions_um"), list) \
        and len(scope["minimum_core_dimensions_um"]) == 2 else (None, None)
    for value in (window, step, min_width, min_height):
        _finite_number(value)
    if window <= 0 or step <= 0 or step >= window or min_width < window or min_height < window:
        raise MetricRefusal("METRIC_AUTHORITY_INVALID",
                            "positive offset checker grid and minimum core dimensions required")
    for role in ("rules", "pdk"):
        record = inputs.get(role)
        if (not isinstance(record, Mapping)
                or body.get(f"{role}_sha256") != record.get("sha256")):
            raise MetricRefusal("METRIC_AUTHORITY_STALE", f"D62 {role} identity")
    authority.update(limits=normalized, unit="ratio", scope=dict(scope),
                     rules_sha256=body["rules_sha256"], pdk_sha256=body["pdk_sha256"],
                     foundry_deck_signoff="NOT_MEASURED")
    return authority


def _d62_keepout_authority(project: Path, relative: str,
                           inputs: Mapping[str, Any]) -> dict:
    authority, body = _approved_document(project, relative,
        authority="requirements_owner", schema=AUTHORITY_SCHEMA)
    if (body.get("expected") != 0 or body.get("unit") != "count"
            or body.get("checker_semantics") != "opendb_fill_obstruction_overlap"
            or not isinstance(body.get("validated_absence"), bool)):
        raise MetricRefusal("METRIC_AUTHORITY_INVALID", "D62 keepout contract")
    for role in ("rules", "pdk"):
        record = inputs.get(role)
        if (not isinstance(record, Mapping)
                or body.get(f"{role}_sha256") != record.get("sha256")):
            raise MetricRefusal("METRIC_AUTHORITY_STALE", f"D62 {role} identity")
    authority.update(value=0, unit="count",
                     checker_semantics=body["checker_semantics"],
                     validated_absence=body["validated_absence"],
                     rules_sha256=body["rules_sha256"], pdk_sha256=body["pdk_sha256"],
                     foundry_deck_signoff="NOT_MEASURED")
    return authority


def d62_authorities(project: Path, inputs: Mapping[str, Any]) -> dict:
    """Load both independently approved D62 checker inputs before launch."""
    return {
        "density": _d62_bounds_authority(project,
            D62_BINDINGS["base_43.fill_density_rules"]["authority"], inputs),
        "keepout": _d62_keepout_authority(project,
            D62_BINDINGS["base_43.fill_keepout_violations"]["authority"], inputs),
    }


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
    checker_outputs = {"density-limits.txt", "density.csv", "checker.census",
                       "checker.log"}
    exact_outputs = geometry_outputs | checker_outputs | {"producer.log", "consumer.log"}
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
    executions = receipt.get("executions")
    expected_roles = ("fill_producer", "independent_odb_readback",
                      "current_odb_metric_checker")
    executable_path = Path(str(use.get("executable", {}).get("path", "")))
    if not executable_path.is_absolute():
        executable_path = (project / executable_path).resolve()
    if (not isinstance(executions, list) or len(executions) != len(expected_roles)
            or tuple(run.get("role") for run in executions) != expected_roles
            or any(run.get("returncode") != 0 or not isinstance(run.get("argv"), list)
                   or len(run["argv"]) != 4 or run["argv"][0] != str(executable_path)
                   or run["argv"][1:3] != ["-no_init", "-exit"]
                   or not isinstance(run.get("read_set"), dict) or not run["read_set"]
                   or not isinstance(run.get("path_bindings"), dict) or not run["path_bindings"]
                   for run in executions)
            or Path(executions[0]["argv"][3]).name != "flow109_density_fill.tcl"
            or Path(executions[1]["argv"][3]).name != "flow109_density_fill.tcl"
            or Path(executions[2]["argv"][3]).name != "flow109_density_checks.tcl"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D62 native execution set")
    if (receipt.get("qualification") != expected_qualification
            or receipt.get("tool") != expected_tool
            or set(receipt.get("inputs", {})) != {"input_odb", "rules", "pdk", "config", "executable"}
            or receipt.get("inputs") != component.get("inputs")
            or receipt.get("authorities") != component.get("authorities")
            or receipt.get("authority_inputs") != component.get("authority_inputs")
            or executions != component.get("executions")
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
                           "executable": use.get("executable"),
                           "executions": executions},
        "consumed_inputs": receipt["inputs"],
        "requirements": "bound-per-obligation",
        "configuration": use.get("config"),
        "models": {"status": "NOT_APPLICABLE_TO_ODB_GEOMETRY_IDENTITY"},
        "outputs": {name: outputs[name] for name in sorted(exact_outputs)},
        "source": receipt["operation_sources"],
    }
    _identity_complete(identity)
    return {"status": "MEASURED", "value": value, "identity": identity}


def _d62_rule_measurements(project: Path, component: Mapping[str, Any],
                           context: Mapping[str, Any], geometry: Mapping[str, Any]
                           ) -> tuple[dict, dict]:
    if geometry.get("status") != "MEASURED":
        missing = {"status": geometry.get("status", "NOT_MEASURED"),
                   "reason": geometry.get("reason") or "D62 geometry is not current"}
        return missing, missing
    receipt_path = _safe_project_file(project, component["receipt"]["path"])
    receipt = json.loads(receipt_path.read_text())
    authorities = d62_authorities(project, receipt.get("inputs", {}))
    if authorities != receipt.get("authorities"):
        raise MetricRefusal("METRIC_AUTHORITY_STALE", "D62 executed authority identity")
    outputs = receipt["outputs"]
    census_path = _safe_project_file(project, outputs["checker.census"]["path"])
    census_lines = census_path.read_text().splitlines()
    expected_labels = ("DENSITY_VIOLATIONS", "FILL_OBSTRUCTIONS", "FILLS_CHECKED",
                       "KEEPOUT_VIOLATIONS", "CORE_DBU", "DBU_PER_MICRON")
    census = {}
    for line, label in zip(census_lines, expected_labels):
        fields = line.split()
        if not fields or fields[0] != label:
            raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 checker census order")
        census[label] = fields[1:]
    if len(census_lines) != len(expected_labels):
        raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 checker census length")
    try:
        density_violations, obstruction_count, fills_checked, keepout_violations = (
            int(census[key][0]) for key in expected_labels[:4])
        core = [int(value) for value in census["CORE_DBU"]]
        dbu = int(census["DBU_PER_MICRON"][0])
    except (IndexError, TypeError, ValueError) as exc:
        raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 checker census values") from exc
    if (len(core) != 4 or dbu <= 0 or any(value < 0 for value in
            (density_violations, obstruction_count, fills_checked, keepout_violations))):
        raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 checker census range")

    density_path = _safe_project_file(project, outputs["density.csv"]["path"])
    with density_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required_fields = ["Layer", "X0", "Y0", "X1", "Y1", "FilledArea(um^2)",
                           "WindowArea(um^2)", "Density", "Min", "Max", "Status"]
        if reader.fieldnames != required_fields:
            raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 density CSV header")
        rows = list(reader)
    if not rows:
        raise MetricRefusal("METRIC_EVIDENCE_ABSENT", "D62 density windows")
    limits = authorities["density"]["limits"]
    per_layer = {layer: [] for layer in limits}
    observed_violations = 0
    for row in rows:
        try:
            density = float(row["Density"])
            low, high = float(row["Min"]), float(row["Max"])
            bounds = [float(row[key]) for key in ("X0", "Y0", "X1", "Y1")]
            filled_area, window_area = (float(row[key]) for key in
                                        ("FilledArea(um^2)", "WindowArea(um^2)"))
        except (TypeError, ValueError) as exc:
            raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 density row") from exc
        for value in (density, low, high, *bounds, filled_area, window_area):
            _finite_number(value)
        if (window_area <= 0 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]
                or row["Status"] not in {"OK", "UNDER", "OVER", "NO_LIMIT"}):
            raise MetricRefusal("METRIC_EVIDENCE_INVALID", "D62 density window geometry")
        band = limits.get(row["Layer"])
        if band is None:
            if row["Status"] != "NO_LIMIT":
                raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", "unapproved density layer band")
            continue
        expected_low = -1.0 if band["min"] is None else float(band["min"])
        expected_high = -1.0 if band["max"] is None else float(band["max"])
        expected_status = ("UNDER" if expected_low >= 0 and density < expected_low
                           else "OVER" if expected_high >= 0 and density > expected_high
                           else "OK")
        if (abs(low - expected_low) > 1e-9 or abs(high - expected_high) > 1e-9
                or row["Status"] != expected_status):
            raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", "D62 density authority/result")
        observed_violations += expected_status != "OK"
        per_layer[row["Layer"]].append({
            "window_um": bounds, "density": density, "min": band["min"],
            "max": band["max"], "status": expected_status})
    if any(not layer_rows for layer_rows in per_layer.values()):
        raise MetricRefusal("METRIC_EVIDENCE_ABSENT", "approved D62 density layer unmeasured")
    if observed_violations != density_violations:
        raise MetricRefusal("METRIC_EVIDENCE_MISMATCH", "D62 density violation census")
    scope = authorities["density"]["scope"]
    core_width, core_height = (core[2] - core[0]) / dbu, (core[3] - core[1]) / dbu
    min_width, min_height = scope["minimum_core_dimensions_um"]
    if core_width < min_width or core_height < min_height:
        raise MetricRefusal("METRIC_SCOPE_UNSUPPORTED", "D62 core below approved density scope")

    common_identity = dict(geometry["identity"])
    density_identity = dict(common_identity)
    density_identity["checker"] = {
        "name": "OpenROAD.check_metal_density",
        "report": outputs["density.csv"], "census": outputs["checker.census"]}
    density_identity["requirements"] = {
        "path": authorities["density"]["path"], "sha256": authorities["density"]["sha256"],
        "source": authorities["density"]["source"]}
    keepout_identity = dict(common_identity)
    keepout_identity["checker"] = {
        "name": "flow109_density_checks.native_fill_obstruction_overlap",
        "census": outputs["checker.census"]}
    keepout_identity["requirements"] = {
        "path": authorities["keepout"]["path"], "sha256": authorities["keepout"]["sha256"],
        "source": authorities["keepout"]["source"]}
    _identity_complete(density_identity)
    _identity_complete(keepout_identity)
    density = {"status": "MEASURED", "value": {
        "per_layer": per_layer, "violations": density_violations,
        "scope": scope, "core_dimensions_um": [core_width, core_height],
        "foundry_deck_signoff": "NOT_MEASURED"}, "unit": "ratio",
        "identity": density_identity}
    if obstruction_count == 0 and not authorities["keepout"]["validated_absence"]:
        keepout = {"status": "NOT_MEASURED",
                   "reason": "D62_KEEPOUT_SET_EMPTY_WITHOUT_VALIDATED_ABSENCE"}
    else:
        keepout = {"status": "MEASURED", "value": keepout_violations, "unit": "count",
                   "checked_fill_obstructions": obstruction_count,
                   "fills_checked": fills_checked,
                   "foundry_deck_signoff": "NOT_MEASURED",
                   "identity": keepout_identity}
    return density, keepout


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
    try:
        density, keepout = _d62_rule_measurements(project, component, context, geometry)
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        missing = {"status": "NOT_MEASURED",
                   "reason": getattr(exc, "code", "METRIC_EVIDENCE_INVALID"),
                   "detail": str(exc)}
        density, keepout = missing, missing
    measured_by_id = {
        "base_43.fill_density_rules": density,
        "base_43.fill_keepout_violations": keepout,
        "base_43.fill_geometry_identity": geometry,
    }
    for obligation in obligations:
        oid = obligation.get("id") if isinstance(obligation, dict) else None
        binding = D62_BINDINGS.get(oid)
        if binding is None:
            result["obligations"].append({"id": oid, "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        expectation = obligation.get("expectation", {})
        declared_ok = (str(expectation.get("bounds_ref", "")).partition("#/")[0]
                       == binding["authority"] if oid == "base_43.fill_density_rules"
                       else str(expectation.get("reference_ref", "")).partition("#/")[0]
                       == binding["authority"] if oid == "base_43.fill_geometry_identity"
                       else expectation.get("value") == 0
                       and expectation.get("unit") == "count")
        if expectation.get("operator") != binding["operator"] or not declared_ok:
            result["obligations"].append({"id": oid, "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        measured = measured_by_id[oid]
        if measured.get("status") == "FAIL":
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "FAIL",
                "detail": measured.get("reason") or "measured component failure"})
            continue
        if oid == "base_43.fill_density_rules":
            try:
                authority = _d62_bounds_authority(project, binding["authority"],
                                                  component.get("inputs", {}))
                if measured.get("status") != "MEASURED":
                    status, detail = "NOT_MEASURED", measured.get("reason", "density not current")
                elif measured["value"]["violations"]:
                    status, detail = "FAIL", "native per-layer density window violation"
                else:
                    status, detail = "PASS", "all approved per-layer density windows pass"
                item = {"id": oid, "metric": obligation.get("metric"),
                        "operator": binding["operator"], "status": status,
                        "detail": detail, "measurement": measured, "authority": authority}
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                item = {"id": oid, "metric": obligation.get("metric"),
                        "operator": binding["operator"], "status": "NOT_MEASURED",
                        "reason": getattr(exc, "code", "METRIC_ACCEPTANCE_REFUSED"),
                        "detail": str(exc)}
            result["obligations"].append(item)
            continue
        if oid == "base_43.fill_keepout_violations":
            try:
                authority = _d62_keepout_authority(project, binding["authority"],
                                                    component.get("inputs", {}))
                status, detail = evaluate_operator(binding["operator"], measured, authority)
                item = {"id": oid, "metric": obligation.get("metric"),
                        "operator": binding["operator"], "status": status, "detail": detail,
                        "measurement": measured, "authority": authority}
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                item = {"id": oid, "metric": obligation.get("metric"),
                        "operator": binding["operator"], "status": "NOT_MEASURED",
                        "reason": getattr(exc, "code", "METRIC_ACCEPTANCE_REFUSED"),
                        "detail": str(exc)}
            result["obligations"].append(item)
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
    if statuses and all(status == "PASS" for status in statuses) \
            and len(statuses) == len(obligations):
        result.update(status="PASS", delivery_blocked=False,
                      reason="ALL_APPLICABLE_METRICS_CURRENT_AND_PASS")
    elif "FAIL" in statuses:
        result.update(status="FAIL", reason="MEASURED_METRIC_FAILURE")
    else:
        result["reason"] = "METRIC_BINDING_INCOMPLETE_OR_NOT_CURRENT"
    return result


D44_BINDINGS = {
    "final_lec.final_lec_unproved": {
        "operator": "eq",
        "value": 0,
        "unit": "count",
    },
    "final_lec.sta_lvs_release_netlist_mapping": {
        "operator": "matches_adopted_reference",
        "authority": "adopted/final_lec/sta_lvs_release_netlist_mapping.json",
    },
}


def _d44_identity(component: Mapping[str, Any], context: Mapping[str, Any],
                  obligation: Mapping[str, Any]) -> dict:
    uses = context.get("runtime_tool_uses")
    if not isinstance(uses, list) or not uses:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "exact D44 tool execution identities absent")
    inputs = component.get("inputs")
    sources = component.get("source_sha256")
    if not isinstance(inputs, Mapping) or not inputs or not isinstance(sources, Mapping) or not sources:
        raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", "D44 inputs/source closure")
    identity = {
        "producer": {"name": "flow109_final_lec.execute",
                     "proof_receipt": component.get("proof_receipt")},
        "checker": {"name": "flow109_final_lec.bind_metrics",
                    "binding_schema": component.get("metric_bindings", {}).get("schema")},
        "tool_execution": {
            "context_sha256": context.get("context_sha256"),
            "uses": [{key: use.get(key) for key in
                      ("use_id", "tool_id", "build_sha256", "executable",
                       "qualification_sha256")} for use in uses],
        },
        "consumed_inputs": dict(inputs),
        "requirements": {"obligation": dict(obligation),
                         "registry_sha256": context.get("registry_sha256")},
        "configuration": {use.get("use_id"): use.get("config") for use in uses},
        "source": dict(sources),
    }
    _identity_complete(identity)
    return identity


def _d44_measurements(project: Path, context: Mapping[str, Any],
                      component: Mapping[str, Any], obligations: Mapping[str, Any]
                      ) -> tuple[dict, dict, dict]:
    # Import at consumption time: flow109_final_lec imports accept_d44 for its
    # adapter integration, so a module-level reverse import would be circular.
    from flow109_final_lec import bind_metrics
    current = bind_metrics(project, context, component)
    values = current.get("metrics")
    if not isinstance(values, Mapping) or set(values) != {
            "final_lec_unproved", "sta_lvs_release_netlist_mapping"}:
        missing = {"status": "NOT_MEASURED", "reason": "D44_METRIC_BINDINGS_ABSENT"}
        return missing, missing, current

    def measurement(name: str, oid: str, *, mapping: bool = False) -> dict:
        value = values[name]
        status = value.get("status") if isinstance(value, Mapping) else None
        if status == "FAIL":
            return {"status": "FAIL", "reason": value.get("reason") or
                    "D44 measured metric failure"}
        if status != "PASS":
            return {"status": "NOT_MEASURED", "reason": value.get("reason") or
                    "D44 measurement is not current"}
        identity = _d44_identity(component, context, obligations[oid])
        return {"status": "MEASURED",
                "value": value.get("reference") if mapping else value.get("value"),
                **({} if mapping else {"unit": value.get("unit")}),
                "identity": identity}

    return (measurement("final_lec_unproved", "final_lec.final_lec_unproved"),
            measurement("sta_lvs_release_netlist_mapping",
                        "final_lec.sta_lvs_release_netlist_mapping", mapping=True), current)


def accept_d44(project: Path, context: Mapping[str, Any],
               component: Mapping[str, Any]) -> dict:
    """Evaluate only the two registered D44 bindings; G1-G9 remain separate."""
    project = Path(project).resolve()
    declared = context.get("resolved_row", {}).get("obligations")
    result = {"schema": SCHEMA, "row_id": "D44", "status": "NOT_MEASURED",
              "delivery_blocked": True, "obligations": [],
              "scope": "D44 row metrics only; not production qualification or G1-G9"}
    if not isinstance(declared, list):
        result["reason"] = "METRIC_OBLIGATIONS_ABSENT"
        return result
    obligations = {item.get("id"): item for item in declared if isinstance(item, Mapping)}
    if set(obligations) != set(D44_BINDINGS):
        result["reason"] = "METRIC_OBLIGATIONS_UNREGISTERED"
        return result
    unproved, mapping, current = _d44_measurements(project, context, component, obligations)
    measured_by_id = {
        "final_lec.final_lec_unproved": unproved,
        "final_lec.sta_lvs_release_netlist_mapping": mapping,
    }
    for obligation in declared:
        oid = obligation["id"]
        binding = D44_BINDINGS[oid]
        expectation = obligation.get("expectation", {})
        declared_ok = (expectation == {
            "operator": "eq", "value": binding.get("value"), "unit": binding.get("unit"),
            "source": "contract invariant: no unresolved required violations"}
            if oid == "final_lec.final_lec_unproved" else expectation == {
                "operator": "matches_adopted_reference",
                "reference_ref": binding.get("authority")})
        if not declared_ok:
            result["obligations"].append({"id": oid,
                "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        measured = measured_by_id[oid]
        if measured.get("status") == "FAIL":
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "FAIL",
                "detail": measured.get("reason") or "measured component failure"})
            continue
        try:
            if oid == "final_lec.final_lec_unproved":
                authority = {"status": "APPROVED", "value": binding["value"],
                    "unit": binding["unit"], "authority": "flow109_registry_contract",
                    "registry_sha256": context.get("registry_sha256")}
            else:
                if measured.get("status") != "MEASURED":
                    authority = {"status": "NOT_MEASURED"}
                else:
                    reference = current["metrics"]["sta_lvs_release_netlist_mapping"]
                    authority = {"status": "APPROVED", "reference": reference["reference"],
                        "reference_identity": measured["identity"],
                        "authority": "current_adopted_D44_reference",
                        "path": binding["authority"]}
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
    if statuses and all(status == "PASS" for status in statuses) \
            and len(statuses) == len(declared):
        result.update(status="PASS", delivery_blocked=False,
                      reason="ALL_APPLICABLE_METRICS_CURRENT_AND_PASS")
    elif "FAIL" in statuses:
        result.update(status="FAIL", reason="MEASURED_METRIC_FAILURE")
    else:
        result["reason"] = "METRIC_BINDING_INCOMPLETE_OR_NOT_CURRENT"
    return result
