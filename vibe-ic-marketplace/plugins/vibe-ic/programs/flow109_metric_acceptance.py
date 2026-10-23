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

D71_BINDINGS = {
    "final_gls.final_sdf_annotation": {
        "operator": "covers_all",
        "authority": "requirements/final_gls/final_sdf_annotation.json",
        "item_fields": ("corner", "scenario"),
    },
    "final_gls.final_gls_scenarios": {
        "operator": "covers_all",
        "authority": "requirements/final_gls/final_gls_scenarios.json",
        "item_fields": ("scenario",),
    },
    "final_gls.final_gls_function_timing_errors": {
        "operator": "eq",
        "value": 0,
        "unit": "count",
    },
}
D71_CONSUMER_SOURCE = "programs/flow109_metric_acceptance.py"


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
D44_METRIC_READER_SOURCE = "programs/flow109_metric_acceptance.py"


def _d44_metric_reader_source_compatible(recorded: Any, current: Any) -> bool:
    return (isinstance(recorded, Mapping) and isinstance(current, Mapping)
            and set(recorded) == set(current)
            and D44_METRIC_READER_SOURCE in recorded
            and all(isinstance(name, str) and _HEX.fullmatch(str(digest))
                    for source in (recorded, current) for name, digest in source.items())
            and all(recorded[name] == digest for name, digest in current.items()
                    if name != D44_METRIC_READER_SOURCE))


def _d44_bound_file(project: Path, record: Any, label: str) -> Path:
    if (not isinstance(record, Mapping) or not isinstance(record.get("path"), str)
            or not _HEX.fullmatch(str(record.get("sha256", "")))):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", f"{label} record")
    path = _safe_project_file(project, record["path"])
    if not path.is_file() or _sha(path.read_bytes()) != record["sha256"]:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", label)
    return path


def _d44_bound_json(project: Path, record: Any, label: str) -> tuple[Path, dict]:
    path = _d44_bound_file(project, record, label)
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label) from exc
    if not isinstance(value, dict):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label)
    return path, value


def _d44_current_inputs(project: Path, component: Mapping[str, Any]) -> dict:
    inputs = component.get("inputs")
    if not isinstance(inputs, Mapping) or not inputs:
        raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", "D44 consumed inputs")
    current = {}
    for name, digest in inputs.items():
        if not isinstance(name, str) or not _HEX.fullmatch(str(digest)):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D44 input record")
        path = Path(name)
        path = path if path.is_absolute() else project / path
        if not path.is_file() or _sha(path.read_bytes()) != digest:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", name)
        current[name] = digest
    return current


def _d44_readset_record(project: Path, inputs: Mapping[str, str], value: Any,
                        label: str) -> dict:
    """Bind a native path through the producer's already-current read set."""
    if not isinstance(value, str) or not value:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label)
    try:
        wanted = Path(value)
        wanted = wanted if wanted.is_absolute() else project / wanted
        wanted = wanted.resolve()
    except (OSError, ValueError, TypeError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label) from exc
    for name, digest in inputs.items():
        candidate = Path(name)
        candidate = candidate if candidate.is_absolute() else project / candidate
        try:
            if candidate.resolve() == wanted:
                return {"path": name, "sha256": digest}
        except (OSError, ValueError):
            continue
    raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                        f"{label} absent from D44 read set")


def _d44_fresh_native_identity(project: Path, component: Mapping[str, Any],
                               admission: Mapping[str, Any]) -> tuple[dict, dict]:
    """Reopen a just-executed source-owned EQY proof, without a reuse claim."""
    from flow109_final_lec import _proof_binding, operation_sources
    import flow109_final_lec_physical as physical

    if (component.get("native_started") is not True
            or "native_error" not in component or component.get("native_error") is not None
            or component.get("native_proof_reused") is True):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "completed fresh D44 native execution required")
    sources = component.get("source_sha256")
    current_sources = operation_sources()
    if not _d44_metric_reader_source_compatible(sources, current_sources):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "D44 source closure")
    inputs = _d44_current_inputs(project, component)
    proof_path, proof = _d44_bound_json(project, component.get("proof_receipt"),
                                        "current proof")
    if component.get("proof") != proof:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "current proof differs")
    if (proof.get("program") != "librelane_eqy"
            or proof.get("engine") != "eqy (LibreLane Yosys.EQY)"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native proof type")

    source_value = proof.get("source")
    if not isinstance(source_value, str):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native proof source")
    native = Path(source_value)
    if not native.is_absolute():
        native = project / native
    native = native.resolve()
    expected_native = (proof_path.parent / "native").resolve()
    if (native != expected_native or not native.is_dir()
            or not native.is_relative_to(project)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native proof source")

    config_path = native / "config.json"
    state_in_path = native / "state_in.json"
    state_out_path = native / "state_out.json"
    try:
        config_raw = config_path.read_bytes()
        config = json.loads(config_raw)
        state_in = json.loads(state_in_path.read_text())
        state_out = json.loads(state_out_path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "native config/state") from exc
    meta = config.get("meta") if isinstance(config, dict) else None
    if (not isinstance(config, dict) or not isinstance(state_in, dict)
            or not isinstance(state_out, dict)
            or proof.get("config_sha256") != _sha(config_raw)
            or not isinstance(meta, Mapping) or meta.get("step") != "Yosys.EQY"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native config identity")

    preparation_path, preparation = _d44_bound_json(
        project, component.get("transformation_receipt"), "current preparation")
    outputs = preparation.get("outputs")
    if (preparation.get("schema") != physical.SCHEMA
            or preparation.get("producer") != "flow109_final_lec_physical"
            or preparation.get("status") != "PREPARED_NOT_EQUIVALENCE_PROVEN"
            or preparation.get("kind") != physical.KIND
            or not isinstance(outputs, Mapping) or set(outputs) != {"gold", "gate"}):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "current physical preparation")
    output_paths = {}
    for side in ("gold", "gate"):
        output_paths[side] = _d44_bound_file(project, outputs[side], f"{side} proof view")
        _d44_readset_record(project, inputs, str(output_paths[side]), f"{side} proof view")
    _d44_readset_record(project, inputs, str(preparation_path), "current preparation")
    raw_netlist = preparation.get("raw_adopted_netlist")
    if (not isinstance(raw_netlist, Mapping) or not isinstance(raw_netlist.get("path"), str)
            or not _HEX.fullmatch(str(raw_netlist.get("sha256", "")))):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "raw adopted netlist")
    raw_read = _d44_readset_record(project, inputs, raw_netlist["path"],
                                   "raw adopted netlist")
    if raw_read["sha256"] != raw_netlist["sha256"]:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "raw adopted netlist")
    prep_inputs = preparation.get("inputs")
    if not isinstance(prep_inputs, Mapping) or any(
            inputs.get(name) != digest for name, digest in prep_inputs.items()):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE",
                            "physical preparation read set")

    verilog_files = config.get("VERILOG_FILES")
    models = config.get("CELL_VERILOG_MODELS")
    if (not isinstance(verilog_files, list) or len(verilog_files) != 1
            or not isinstance(verilog_files[0], str)
            or Path(verilog_files[0]).resolve() != output_paths["gold"].resolve()
            or state_in.get("nl") != state_out.get("nl")
            or not isinstance(state_in.get("nl"), str)
            or Path(state_in["nl"]).resolve() != output_paths["gate"].resolve()
            or not isinstance(models, list) or not models
            or not all(isinstance(model, str) and model for model in models)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "native proof view configuration")
    model_records = [_d44_readset_record(project, inputs, model, "native model")
                     for model in models]
    preprocessing = component.get("preprocessing_models")
    if (not isinstance(preprocessing, Mapping)
            or set(preprocessing) != set(models)
            or any(preprocessing.get(model) != record["sha256"]
                   for model, record in zip(models, model_records))):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE",
                            "native preprocessing models")

    evidence = proof.get("evidence_sha256")
    if not isinstance(evidence, Mapping) or not evidence:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "partition evidence")
    actual = [native / "scratch/partition.list",
              *sorted((native / "scratch/strategies").glob("*/*/status"))]
    actual_names = [str(path.relative_to(native)) for path in actual if path.is_file()]
    if set(evidence) != set(actual_names) or "scratch/partition.list" not in evidence:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "partition evidence population")
    evidence_records = []
    status_values = {}
    for name in actual_names:
        path = _safe_project_file(project, str((native / name).relative_to(project)))
        if _sha(path.read_bytes()) != evidence.get(name):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", name)
        evidence_records.append({"path": str(path.relative_to(project)),
                                 "sha256": evidence[name]})
        match = re.fullmatch(r"scratch/strategies/([^/]+)/([^/]+)/status", name)
        if match:
            status_values.setdefault(match.group(1), {})[match.group(2)] = path.read_text().strip()
    listing = (native / "scratch/partition.list").read_text().splitlines()
    declared = []
    for line in listing:
        if not line.strip():
            continue
        words = line.partition(":")[0].split()
        if len(words) < 2:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "partition list")
        declared.append(words[1])
    if (not declared or len(declared) != len(set(declared))
            or declared != proof.get("declared_partitions")
            or status_values != proof.get("partitions")):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "partition proof differs from native evidence")

    census = component.get("model_census")
    top = preparation.get("top")
    interfaces = preparation.get("functional_interfaces")
    if not isinstance(census, Mapping) or set(census) != {"gold", "gate"}:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "model census")
    normalized = {}
    for side in ("gold", "gate"):
        value = census.get(side)
        modules = value.get("modules") if isinstance(value, Mapping) else None
        ports = value.get("ports") if isinstance(value, Mapping) else None
        if (not isinstance(modules, list) or not modules or top not in modules
                or not isinstance(ports, Mapping)):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "model census")
        try:
            normalized[side] = {name: [port["direction"], len(port["bits"])]
                                for name, port in ports.items()}
        except (KeyError, TypeError) as exc:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "model census") from exc
    if (normalized["gold"] != normalized["gate"]
            or interfaces != normalized
            or _proof_binding(proof).get("status") != "PASS"
            or not isinstance(proof.get("compared_points"), int)
            or proof.get("compared_points") <= 0):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "complete non-blackbox proof required")

    execution = {
        "mode": "fresh_native_executed",
        "policy": dict(admission),
        "proof_engine": {"program": proof["program"], "engine": proof["engine"]},
        "proof_source_closure": dict(sources),
        "current_metric_reader": {"path": D44_METRIC_READER_SOURCE,
                                  "sha256": current_sources[D44_METRIC_READER_SOURCE]},
        "model_census": census,
    }
    configuration = {
        "config": {"path": str(config_path.relative_to(project)),
                   "sha256": proof["config_sha256"]},
        "state_in": {"path": str(state_in_path.relative_to(project)),
                     "sha256": _sha(state_in_path.read_bytes())},
        "state_out": {"path": str(state_out_path.relative_to(project)),
                      "sha256": _sha(state_out_path.read_bytes())},
        "current_preparation": dict(component["transformation_receipt"]),
        "raw_adopted_netlist": dict(raw_netlist),
        "reference_view": dict(outputs["gold"]),
        "gate_view": dict(outputs["gate"]),
        "models": model_records,
        "partition_evidence": evidence_records,
        "current_proof": dict(component["proof_receipt"]),
    }
    return execution, configuration


def _d44_source_owned_identity(project: Path, component: Mapping[str, Any],
                               context: Mapping[str, Any]) -> tuple[dict, dict]:
    import flow109
    try:
        current_context = flow109.validate_execution_context(context)
        admission = flow109.source_owned_native_admission(current_context)
    except (ValueError, KeyError, TypeError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "current source-owned D44 context required") from exc
    if (not isinstance(admission, Mapping) or admission.get("admitted") is not True
            or admission.get("reason") != "SOURCE_OWNED_EXISTING_NATIVE_COMPONENT"
            or admission.get("native_step_id") != "flow109.D44"
            or admission.get("acceptance_scope") != "existing_native_component_only"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "current source-owned D44 admission required")
    if component.get("component_status") != "PASS":
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D44 PASS component required")
    adoption = component.get("retained_native")
    if adoption is None:
        execution, configuration = _d44_fresh_native_identity(project, component, admission)
        _identity_complete({"producer": {"mode": "fresh_native_executed"},
                            "checker": {"name": "flow109_final_lec.bind_metrics"},
                            "tool_execution": execution,
                            "consumed_inputs": _d44_current_inputs(project, component),
                            "requirements": {"registry_sha256": context.get("registry_sha256")},
                            "configuration": configuration})
        return execution, configuration
    if (not isinstance(adoption, Mapping)
            or adoption.get("mode") != "current_views_exactly_match_retained_native_EQY_subject"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "D44 retained-native adoption receipt required")
    _, retained = _d44_bound_json(project, adoption.get("receipt"), "retained manifest")
    required = {"native_receipt", "operation_sources", "preparation", "proof",
                "reference_view", "gate_view", "config", "state_in",
                "input_fingerprint", "native_step_receipt", "partition_list",
                "strategy_statuses", "method_source", "run_script", "argv",
                "current_preparation"}
    if (retained.get("schema") != "vibeic.flow109.final-lec-retained-native.v1"
            or retained.get("status") != "PASS" or not required <= set(retained)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "retained manifest schema")
    records, values = {}, {}
    json_records = {"native_receipt", "operation_sources", "preparation", "proof",
                    "config", "state_in", "input_fingerprint", "native_step_receipt",
                    "current_preparation"}
    for name in json_records:
        records[name], values[name] = _d44_bound_json(project, retained[name], name)
    for name in required - json_records - {"strategy_statuses"}:
        records[name] = _d44_bound_file(project, retained[name], name)
    status_records = retained["strategy_statuses"]
    if not isinstance(status_records, list) or not status_records:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "partition statuses")
    status_paths = []
    for index, record in enumerate(status_records):
        path = _d44_bound_file(project, record, f"partition status {index}")
        status_paths.append({"path": str(path.relative_to(project)), "sha256": record["sha256"]})
    native, proof = values["native_receipt"], values["proof"]
    config, fingerprint = values["config"], values["input_fingerprint"]
    step = values["native_step_receipt"]
    from flow109_final_lec import EDA_IMAGE, operation_sources
    argv_path = records["argv"]
    try:
        argv = json.loads(argv_path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native argv") from exc
    image = retained.get("image")
    local = step.get("input", {}).get("local_image")
    if (image != EDA_IMAGE or native.get("component_status") != "PASS"
            or native.get("native_status") != "PASS"
            or native.get("exit_code") != 0 or native.get("image") != image
            or not isinstance(local, Mapping) or local.get("image") != image
            or native.get("image_id") != local.get("image_id")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(native.get("image_id", "")))
            or not _HEX.fullmatch(str(native.get("cid", "")))
            or local.get("cid") != native.get("cid") or local.get("network_mode") != "none"
            or not isinstance(argv, list) or not all(isinstance(item, str) for item in argv)
            or image not in argv
            or argv.index(image) + 1 >= len(argv) or argv[argv.index(image) + 1] != "--skip"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native image/command identity")
    if (native.get("source_closure", {}).get("sha256") != retained["operation_sources"]["sha256"]
            or native.get("positive", {}).get("proof", {}).get("sha256") !=
               retained["proof"]["sha256"]
            or native.get("argv", {}).get("sha256") != retained["argv"]["sha256"]
            or proof.get("config_sha256") != retained["config"]["sha256"]
            or step.get("input") != fingerprint):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "native proof/config/source identity")
    component_proof_path, component_proof = _d44_bound_json(
        project, component.get("proof_receipt"), "current proof")
    if component_proof != proof or component.get("proof") != proof:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "current proof differs")
    if component.get("transformation_receipt") != retained["current_preparation"]:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "current preparation differs")
    sources = component.get("source_sha256")
    if not isinstance(sources, Mapping) or dict(sources) != operation_sources():
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "D44 source closure")
    execution = {
        "policy": dict(admission),
        "image": image,
        "image_id": native.get("image_id"),
        "cid": native.get("cid"),
        "argv": {"path": str(argv_path.relative_to(project)),
                 "sha256": retained["argv"]["sha256"]},
        "native_receipt": dict(retained["native_receipt"]),
        "native_step_receipt": dict(retained["native_step_receipt"]),
        "method_source": dict(retained["method_source"]),
        "run_script": dict(retained["run_script"]),
        "model_census": component.get("model_census"),
    }
    configuration = {
        "config": dict(retained["config"]),
        "input_fingerprint": dict(retained["input_fingerprint"]),
        "original_source_closure": dict(retained["operation_sources"]),
        "original_preparation": dict(retained["preparation"]),
        "original_state": dict(retained["state_in"]),
        "reference_view": dict(retained["reference_view"]),
        "gate_view": dict(retained["gate_view"]),
        "current_preparation": dict(retained["current_preparation"]),
        "partition_list": dict(retained["partition_list"]),
        "partition_statuses": status_paths,
        "current_proof": {"path": str(component_proof_path.relative_to(project)),
                          "sha256": component["proof_receipt"]["sha256"]},
    }
    _identity_complete({"producer": {"retained": dict(adoption)},
                        "checker": {"name": "flow109_final_lec.bind_metrics"},
                        "tool_execution": execution,
                        "consumed_inputs": _d44_current_inputs(project, component),
                        "requirements": {"registry_sha256": context.get("registry_sha256")},
                        "configuration": configuration})
    return execution, configuration


def _d44_identity(project: Path, component: Mapping[str, Any], context: Mapping[str, Any],
                  obligation: Mapping[str, Any]) -> dict:
    uses = context.get("runtime_tool_uses")
    explicit_claim = uses is not None or context.get("qualification_registry") is not None
    if explicit_claim:
        if not isinstance(uses, list) or not uses:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                                "exact D44 qualified tool execution identities absent")
        tool_execution = {
            "context_sha256": context.get("context_sha256"),
            "uses": [{key: use.get(key) for key in
                      ("use_id", "tool_id", "build_sha256", "executable",
                       "qualification_sha256")} for use in uses],
        }
        configuration = {use.get("use_id"): use.get("config") for use in uses}
    else:
        tool_execution, configuration = _d44_source_owned_identity(project, component, context)
        tool_execution = {"context_sha256": context.get("context_sha256"),
                          "source_owned": tool_execution}
    inputs = _d44_current_inputs(project, component)
    sources = component.get("source_sha256")
    if not isinstance(sources, Mapping) or not sources:
        raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", "D44 inputs/source closure")
    identity = {
        "producer": {"name": "flow109_final_lec.execute",
                     "proof_receipt": component.get("proof_receipt")},
        "checker": {"name": "flow109_final_lec.bind_metrics",
                    "binding_schema": component.get("metric_bindings", {}).get("schema")},
        "tool_execution": tool_execution,
        "consumed_inputs": dict(inputs),
        "requirements": {"obligation": dict(obligation),
                         "registry_sha256": context.get("registry_sha256")},
        "configuration": configuration,
        "source": dict(sources),
    }
    _identity_complete(identity)
    return identity


def _d44_reopen_fresh_reader_baseline(project: Path, context: Mapping[str, Any],
                                      component: Mapping[str, Any], current: Mapping[str, Any]
                                      ) -> dict:
    """Recover only the mapping invalidated by this reader's own source update."""
    if component.get("retained_native") is not None:
        return dict(current)
    values = current.get("metrics")
    proof = values.get("final_lec_unproved") if isinstance(values, Mapping) else None
    mapping = (values.get("sta_lvs_release_netlist_mapping")
               if isinstance(values, Mapping) else None)
    if (not isinstance(proof, Mapping) or proof.get("status") != "PASS"
            or not isinstance(mapping, Mapping) or mapping.get("status") != "FAIL"
            or mapping.get("reason") not in {
                "D44_BASELINE_SUBJECT_MISMATCH", "D44_OPERATION_SOURCE_CHANGED"}):
        return dict(current)
    try:
        from flow109_final_lec import BASELINE, SCHEMA as D44_SCHEMA, _record, operation_sources, prepare
        recorded_sources = component.get("source_sha256")
        prepared = prepare(project, context)
        if not _d44_metric_reader_source_compatible(recorded_sources, operation_sources()):
            return dict(current)
        baseline_record = component.get("common_baseline")
        baseline_path, baseline = _d44_bound_json(project, baseline_record, "common baseline")
        if baseline_path != (project / BASELINE).resolve():
            return dict(current)
        expected = {
            "schema": D44_SCHEMA,
            "producer": "flow109_final_lec",
            "context_sha256": context.get("context_sha256"),
            "source_sha256": recorded_sources,
            "rtl": [_record(project, item) for item in prepared["paths"]["rtl"]],
            "adopted_netlist": _record(project, prepared["paths"]["adopted_netlist"]),
            "consumer_netlists": {
                role: _record(project, prepared["paths"][role])
                for role in ("sta", "lvs_reference", "release")},
            "transformations": prepared["manifest"]["transformations"],
            "mapping": "same_logical_bytes",
            "consumer_adoption": "NOT_MEASURED",
            "proof": component.get("proof_receipt"),
        }
        if prepared.get("physical_input"):
            expected["transformation_receipt"] = component.get("transformation_receipt")
        if baseline != expected:
            return dict(current)
        _, proof_value = _d44_bound_json(project, component.get("proof_receipt"), "current proof")
        if proof_value != component.get("proof"):
            return dict(current)
        roles = baseline.get("consumer_netlists")
        records = [baseline.get("adopted_netlist"),
                   *(roles.values() if isinstance(roles, Mapping) else [])]
        if (not isinstance(roles, Mapping) or set(roles) != {"sta", "lvs_reference", "release"}
                or len(records) != 4
                or len({record.get("sha256") for record in records
                        if isinstance(record, Mapping)}) != 1):
            return dict(current)
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError):
        return dict(current)
    recovered_mapping = {
        **mapping,
        "status": "PASS",
        "value": "matches_adopted_reference",
        "reference": dict(baseline_record),
        "consumer_roles": ["lvs_reference", "release", "sta"],
        "consumer_adoption": "NOT_MEASURED",
    }
    recovered_mapping.pop("reason", None)
    recovered_mapping.pop("detail", None)
    recovered = dict(current)
    recovered["metrics"] = {**values,
                            "sta_lvs_release_netlist_mapping": recovered_mapping}
    recovered["status"] = "PASS"
    return recovered


def _d44_measurements(project: Path, context: Mapping[str, Any],
                      component: Mapping[str, Any], obligations: Mapping[str, Any]
                      ) -> tuple[dict, dict, dict]:
    # Import at consumption time: flow109_final_lec imports accept_d44 for its
    # adapter integration, so a module-level reverse import would be circular.
    from flow109_final_lec import bind_metrics
    current = bind_metrics(project, context, component)
    current = _d44_reopen_fresh_reader_baseline(project, context, component, current)
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
        try:
            identity = _d44_identity(project, component, context, obligations[oid])
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            return {"status": "NOT_MEASURED",
                    "reason": getattr(exc, "code", "METRIC_EXECUTION_EVIDENCE_INVALID"),
                    "detail": str(exc)}
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


def _d71_bound_file(project: Path, record: Any, label: str,
                    inputs: Mapping[str, str] | None = None) -> tuple[Path, bytes]:
    if (not isinstance(record, Mapping) or not isinstance(record.get("path"), str)
            or not _HEX.fullmatch(str(record.get("sha256", "")))):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", f"{label} record")
    path = Path(record["path"])
    path = path if path.is_absolute() else project / path
    try:
        path = path.resolve()
        raw = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", label) from exc
    if _sha(raw) != record["sha256"]:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", label)
    if inputs is not None:
        matched = False
        for name, digest in inputs.items():
            candidate = Path(name)
            candidate = candidate if candidate.is_absolute() else project / candidate
            try:
                if candidate.resolve() == path and digest == record["sha256"]:
                    matched = True
                    break
            except (OSError, ValueError):
                continue
        if not matched:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                                f"{label} absent from D71 read set")
    return path, raw


def _d71_bound(project: Path, record: Any, label: str,
               inputs: Mapping[str, str] | None = None) -> tuple[Path, dict]:
    path, raw = _d71_bound_file(project, record, label, inputs)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label) from exc
    if not isinstance(value, dict):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label)
    return path, value


def _d71_inputs(project: Path, component: Mapping[str, Any]) -> dict[str, str]:
    inputs = component.get("inputs")
    if not isinstance(inputs, Mapping) or not inputs:
        raise MetricRefusal("METRIC_IDENTITY_INCOMPLETE", "D71 consumed inputs")
    current = {}
    for name, digest in inputs.items():
        if not isinstance(name, str) or not _HEX.fullmatch(str(digest)):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D71 input record")
        path = Path(name)
        path = path if path.is_absolute() else project / path
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", name) from exc
        if _sha(raw) != digest:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", name)
        current[name] = digest
    return current


def _d71_input_json(project: Path, inputs: Mapping[str, str], suffix: str,
                    label: str) -> tuple[Path, dict, dict]:
    matches = [(name, digest) for name, digest in inputs.items()
               if name == suffix or name.endswith("/" + suffix)]
    if len(matches) != 1:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", label)
    name, digest = matches[0]
    record = {"path": name, "sha256": digest}
    path, value = _d71_bound(project, record, label, inputs)
    return path, value, record


def _d71_source_owned_measurements(project: Path, context: Mapping[str, Any],
                                   component: Mapping[str, Any]) -> tuple[dict, dict, dict, dict]:
    import flow109
    import flow109_final_gls as final_gls

    try:
        current_context = flow109.validate_execution_context(context)
        admission = flow109.source_owned_native_admission(current_context)
    except (ValueError, KeyError, TypeError) as exc:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "current source-owned D71 context required") from exc
    if (not isinstance(admission, Mapping) or admission.get("admitted") is not True
            or admission.get("native_step_id") != "flow109.D71"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "current source-owned D71 admission required")
    if (component.get("schema") != final_gls.SCHEMA or component.get("step_id") != "D71"
            or component.get("native_started") is not True
            or component.get("execution_scope") != final_gls.ENGINEERING_SCOPE
            or component.get("engineering_component_status") not in {"PASS", "FAIL"}):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                            "measured engineering D71 component required")
    sources = component.get("operation_sources")
    current_sources = final_gls.operation_sources()
    if not _d71_source_boundary(sources, current_sources, final_gls):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "D71 producer source closure")
    inputs = _d71_inputs(project, component)
    _, manifest, manifest_record = _d71_input_json(project, inputs, final_gls.INPUT,
                                                   "D71 manifest")
    requirements_path, requirements = _d71_bound(
        project, manifest.get("requirements"), "D71 requirements", inputs)
    required_corners = requirements.get("required_corners")
    required_scenarios = requirements.get("required_scenarios")
    behaviors = requirements.get("required_timing_behaviors")
    if (not isinstance(required_corners, list) or not required_corners
            or len(required_corners) != len(set(required_corners))
            or not isinstance(required_scenarios, list) or not required_scenarios
            or len(required_scenarios) != len(set(required_scenarios))
            or not isinstance(behaviors, list) or not behaviors):
        raise MetricRefusal("METRIC_REQUIREMENTS_INVALID", "D71 required population")
    unsupported = sorted(set(behaviors) - set(final_gls.SUPPORTED_REQUIRED_BEHAVIORS))
    if unsupported or set(behaviors) != set(final_gls.SUPPORTED_REQUIRED_BEHAVIORS):
        reason = "D71_REQUIRED_TIMING_BEHAVIOR_UNSUPPORTED" if unsupported \
            else "D71_REQUIRED_TIMING_BEHAVIOR_INCOMPLETE"
        missing = {"status": "NOT_MEASURED", "reason": reason,
                   "detail": unsupported or behaviors}
        pending = {"status": "UNSUPPORTED", "required_timing_behaviors": list(behaviors)}
        return missing, missing, missing, pending

    catalog_record = requirements.get("source_catalog")
    catalog_path, catalog = _d71_bound(project, catalog_record, "functional scenario catalog",
                                       inputs)
    catalog_cases = catalog.get("cases")
    names = {item.get("name") for item in catalog_cases or [] if isinstance(item, Mapping)
             and item.get("state") == "passed"}
    if not set(required_scenarios) <= names:
        raise MetricRefusal("METRIC_REQUIREMENTS_INVALID", "scenario catalog population")

    result = component.get("result")
    checker = component.get("checker")
    native = component.get("native")
    if (not isinstance(result, Mapping) or result.get("schema") != final_gls.SCHEMA
            or result.get("program") != "flow109_final_gls" or result.get("step_id") != "D71"
            or not isinstance(checker, Mapping) or not isinstance(native, Mapping)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D71 result/checker")
    _, checker_body = _d71_bound(project, result.get("post_layout_sim_check"),
                                 "D71 checker output")
    if checker_body != checker:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "D71 checker output")
    _, published = _d71_bound(project, result.get("results_json"), "published D71 result")
    for key in ("schema", "program", "step_id", "verdict", "annotation_population",
                "final_sdfs", "d44_baseline", "d70_receipt", "d69_receipt",
                "native_step", "limitations", "judge", "execution_scope",
                "full_row_acceptance"):
        if published.get(key) != result.get(key):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE",
                                f"published D71 result {key}")
    _, native_manifest = _d71_bound(project, native.get("manifest"), "native GLS manifest")
    _, native_runs = _d71_bound(project, native.get("runs"), "native GLS runs")
    if result.get("native_step") != native.get("runs"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "native GLS result binding")

    d70_path, d70 = _d71_bound(project, result.get("d70_receipt"), "D70 receipt", inputs)
    if (d70.get("schema") != final_gls.D70_SCHEMA or d70.get("step_id") != "D70"
            or d70.get("component_status") != "PASS" or d70.get("sdf_role") != "final"
            or d70.get("producer") != "flow109_final_electrical"
            or set(d70.get("required_corners") or []) != set(required_corners)
            or set(d70.get("final_sdfs") or {}) != set(required_corners)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D70 final SDF declaration")
    _, d44 = _d71_bound(project, result.get("d44_baseline"), "D44 common baseline", inputs)
    _, d69 = _d71_bound(project, result.get("d69_receipt"), "D69 receipt", inputs)
    if (d44.get("producer") != "flow109_final_lec"
            or d44.get("mapping") != "same_logical_bytes"
            or d69.get("schema") != "vibeic.flow109.final-extract.v1"
            or d69.get("step_id") != "D69" or d69.get("component_status") != "PASS"):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "D44/D69 dependency")
    netlist_path = _d71_bound_file(project, d70.get("netlist"), "D70 netlist", inputs)[0]
    sdc_path = _d71_bound_file(project, d70.get("sdc"), "D70 SDC", inputs)[0]
    _, state = _d71_bound(project, d70.get("sta_state"), "D70 native STA state", inputs)
    if (Path(str(state.get("nl", ""))).resolve() != netlist_path
            or Path(str(state.get("sdc", ""))).resolve() != sdc_path
            or set(state.get("sdf") or {}) != set(required_corners)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "D70 native STA subject")
    sdf_records = {}
    for corner in required_corners:
        path, _ = _d71_bound_file(
            project, d70["final_sdfs"][corner], f"D70 SDF {corner}", inputs)
        if Path(str(state["sdf"].get(corner, ""))).resolve() != path:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", f"D70 SDF state {corner}")
        sdf_records[corner] = dict(d70["final_sdfs"][corner])

    manifest_cases = native_manifest.get("cases")
    if (Path(str(native_manifest.get("netlist", ""))).resolve() != netlist_path
            or {item.get("id") for item in manifest_cases or [] if isinstance(item, Mapping)}
               != set(required_scenarios)
            or native_runs.get("netlist") != str(netlist_path)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "native GLS subject")
    rows = native_runs.get("runs")
    if not isinstance(rows, list):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native GLS runs")
    expected = {(corner, scenario) for corner in required_corners
                for scenario in required_scenarios}
    by_pair = {(row.get("corner"), row.get("case")): row for row in rows
               if isinstance(row, Mapping)}
    if len(by_pair) != len(rows) or set(by_pair) != expected:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native GLS population")

    population = result.get("annotation_population")
    required = population.get("required") if isinstance(population, Mapping) else None
    observed = population.get("observed") if isinstance(population, Mapping) else None
    expected_items = [{"corner": corner, "scenario": scenario}
                      for corner, scenario in sorted(expected)]
    if required != expected_items or not isinstance(observed, list):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "published GLS population")
    judge = result.get("judge")
    corners = judge.get("corners") if isinstance(judge, Mapping) else None
    readback = judge.get("existing_case_readback") if isinstance(judge, Mapping) else None
    if (not isinstance(corners, Mapping) or set(corners) != set(required_corners)
            or not isinstance(readback, list)):
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "native GLS judgment")
    readback_by_pair = {(item.get("corner"), item.get("scenario")): item
                        for item in readback if isinstance(item, Mapping)}
    if len(readback_by_pair) != len(readback) or set(readback_by_pair) != expected:
        raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "functional readback population")

    annotations, passed_scenarios = [], set(required_scenarios)
    functional_errors = annotation_errors = 0
    infrastructure_failure = False
    for corner in required_corners:
        judged_corner = corners[corner]
        cases = judged_corner.get("cases") if isinstance(judged_corner, Mapping) else None
        judged_cases = {item.get("id"): item for item in cases or []
                        if isinstance(item, Mapping)}
        if set(judged_cases) != set(required_scenarios):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", f"judge cases {corner}")
        if result.get("final_sdfs", {}).get(corner, {}).get("sha256") != sdf_records[corner]["sha256"]:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", f"published SDF {corner}")
        for scenario in required_scenarios:
            row = by_pair[(corner, scenario)]
            case = judged_cases[scenario]
            evidence = readback_by_pair[(corner, scenario)]
            stdout = Path(str(row.get("stdout", "")))
            try:
                stdout_sha = _sha(stdout.read_bytes())
            except OSError as exc:
                raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE",
                                    f"native transcript {corner}/{scenario}") from exc
            if stdout_sha != evidence.get("stdout_sha256"):
                raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE",
                                    f"native transcript {corner}/{scenario}")
            checks = evidence.get("source_self_check", {}).get("checks")
            if not isinstance(checks, Mapping) or not isinstance(checks.get("errors"), int):
                raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                                    f"functional check {corner}/{scenario}")
            functional_errors += checks["errors"]
            sdf_errors = case.get("sdf_errors")
            if not isinstance(sdf_errors, int) or sdf_errors < 0:
                raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                                    f"annotation errors {corner}/{scenario}")
            annotation_errors += sdf_errors
            annotated = (case.get("sdf_delays_applied", 0) > 0 and sdf_errors == 0
                         and row.get("compile_rc") == 0 and row.get("sim_rc") == 0)
            if annotated:
                annotations.append({"corner": corner, "scenario": scenario})
            if case.get("verdict") != "PASS" or checks["errors"]:
                passed_scenarios.discard(scenario)
            if row.get("compile_rc") != 0 or row.get("sim_rc") != 0:
                infrastructure_failure = True

    requirement_record = dict(manifest["requirements"])
    catalog_identity = {"path": str(catalog_path), "sha256": catalog_record["sha256"]}
    authority_sources = {
        "requirements": requirement_record,
        "catalog": catalog_identity,
        "d70_receipt": dict(result["d70_receipt"]),
        "sta_state": dict(d70["sta_state"]),
        "netlist": dict(d70["netlist"]),
        "sdc": dict(d70["sdc"]),
        "final_sdfs": sdf_records,
    }
    identity = {
        "producer": {"name": "flow109_final_gls.execute", "result": dict(result["results_json"]),
                     "native_manifest": dict(native["manifest"]), "native_runs": dict(native["runs"])},
        "checker": {"name": "post_layout_sim_check.audit",
                    "report": dict(result["post_layout_sim_check"])},
        "tool_execution": {"policy": dict(admission),
                           "scope": component["execution_scope"],
                           "producer_context_sha256": component.get("context_sha256")},
        "consumed_inputs": dict(inputs),
        "requirements": authority_sources,
        "configuration": {"compile_flags": judge.get("compile_flags"),
                          "required_timing_behaviors": list(behaviors),
                          "limitations": list(result.get("limitations") or [])},
        "source": dict(sources),
    }
    _identity_complete(identity)
    annotation = {"status": "MEASURED", "value": annotations, "identity": identity}
    scenarios = {"status": "MEASURED",
                 "value": [{"scenario": name} for name in sorted(passed_scenarios)],
                 "identity": identity}
    errors = {"status": "MEASURED", "value": functional_errors + annotation_errors,
              "unit": "count", "functional_errors": functional_errors,
              "annotation_errors": annotation_errors, "identity": identity}
    if set(map(_json_key, annotations)) != set(map(_json_key, expected_items)):
        annotation.update(status="FAIL", reason="D71_REQUIRED_SDF_ANNOTATION_MISSING")
    if passed_scenarios != set(required_scenarios):
        scenarios.update(status="FAIL", reason="D71_REQUIRED_SCENARIO_FAILED")
    if infrastructure_failure and errors["value"] == 0:
        errors.update(status="FAIL", reason="D71_NATIVE_GLS_EXECUTION_FAILED")
    if (component.get("engineering_component_status") == "FAIL"
            or result.get("verdict") != "PASS" or checker.get("verdict") != "PASS"
            or judge.get("verdict") != "PASS"):
        errors.update(status="FAIL", reason="D71_MEASURED_RESULT_FAILED")
    pending = {"status": "PENDING_DERIVED_REQUIREMENTS", "sources": authority_sources,
               "annotation_items": expected_items,
               "scenario_items": [{"scenario": name} for name in sorted(required_scenarios)],
               "upstream_scope_complete": (
                   d69.get("flow109_acceptance") == "PASS"
                   and d70.get("flow109_acceptance") == "PASS")}
    return annotation, scenarios, errors, pending


def _d71_source_boundary(recorded: Any, current: Any, final_gls: Any) -> bool:
    """Accept only consumer-induced AST reachability growth around D71's producer."""
    if (not isinstance(recorded, Mapping) or not isinstance(current, Mapping)
            or D71_CONSUMER_SOURCE not in recorded
            or D71_CONSUMER_SOURCE not in current
            or any(not isinstance(name, str) or not _HEX.fullmatch(str(digest))
                   for sources in (recorded, current) for name, digest in sources.items())):
        return False
    recorded_names, current_names = set(recorded), set(current)
    if not recorded_names <= current_names:
        return False
    if any(digest != current.get(name) for name, digest in recorded.items()
           if name != D71_CONSUMER_SOURCE):
        return False
    added = current_names - recorded_names
    if not added:
        return True

    from execution_provider_catalog import _local_imports, source_closure

    consumer_path = Path(__file__).resolve()
    producer_path = Path(final_gls.__file__).resolve()
    try:
        consumer_direct = set(_local_imports(str(consumer_path), consumer_path.read_text()))
        producer_direct = set(_local_imports(str(producer_path), producer_path.read_text()))
        consumer_closure = set(source_closure({consumer_path}))
        producer_closure = set(source_closure({producer_path}))
        added_paths = {(consumer_path.parent.parent / name).resolve() for name in added}
    except (OSError, ValueError, TypeError):
        return False
    # The consumer must now reach the unchanged D71 producer directly. Only
    # previously-unrecorded direct dependencies of that same producer may be
    # added; arbitrary consumer imports and transitive growth remain stale.
    return (producer_path in consumer_direct
            and added_paths == ((consumer_closure & producer_direct) - {
                (consumer_path.parent.parent / name).resolve() for name in recorded_names})
            and added_paths <= producer_closure)


def _d71_authority(project: Path, binding: Mapping[str, Any], pending: Mapping[str, Any],
                   kind: str) -> dict:
    path = project / binding["authority"]
    required = pending[f"{kind}_items"]
    if not path.is_file():
        return {"status": "PENDING_DERIVED_REQUIREMENTS", "required_items": required,
                "sources": pending["sources"], "path": binding["authority"]}
    authority, _ = _approved_authority(project, binding["authority"] + "#/required_items",
                                       binding["item_fields"])
    source = authority["source"]
    required_source = pending["sources"]["requirements"]
    source_path = Path(source["path"])
    source_path = source_path if source_path.is_absolute() else project / source_path
    required_path = Path(required_source["path"])
    required_path = required_path if required_path.is_absolute() else project / required_path
    if (source["sha256"] != required_source["sha256"]
            or source_path.resolve() != required_path.resolve()):
        raise MetricRefusal("METRIC_AUTHORITY_STALE", binding["authority"])
    if {_json_key(item) for item in authority["required_items"]} != {
            _json_key(item) for item in required}:
        raise MetricRefusal("METRIC_AUTHORITY_STALE", binding["authority"])
    return authority


def accept_d71(project: Path, context: Mapping[str, Any],
               component: Mapping[str, Any]) -> dict:
    """Bind observed D71 metrics; incomplete final authority still blocks delivery."""
    project = Path(project).resolve()
    declared = context.get("resolved_row", {}).get("obligations")
    result = {"schema": SCHEMA, "row_id": "D71", "status": "NOT_MEASURED",
              "metric_status": "NOT_MEASURED", "delivery_blocked": True,
              "obligations": [], "scope": (
                  "limited Icarus SDF-delay/self-check metrics only; not D69/D70, "
                  "physical signoff, whole-flow or whole-IC acceptance")}
    if not isinstance(declared, list):
        result["reason"] = "METRIC_OBLIGATIONS_ABSENT"
        return result
    obligations = {item.get("id"): item for item in declared if isinstance(item, Mapping)}
    if set(obligations) != set(D71_BINDINGS):
        result["reason"] = "METRIC_OBLIGATIONS_UNREGISTERED"
        return result
    try:
        annotation, scenarios, errors, pending = _d71_source_owned_measurements(
            project, context, component)
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        missing = {"status": "NOT_MEASURED",
                   "reason": getattr(exc, "code", "METRIC_EXECUTION_EVIDENCE_INVALID"),
                   "detail": str(exc)}
        annotation = scenarios = errors = missing
        pending = {"status": "NOT_MEASURED"}
    measured = {
        "final_gls.final_sdf_annotation": annotation,
        "final_gls.final_gls_scenarios": scenarios,
        "final_gls.final_gls_function_timing_errors": errors,
    }
    for obligation in declared:
        oid = obligation.get("id")
        binding = D71_BINDINGS[oid]
        expectation = obligation.get("expectation", {})
        declared_ok = (expectation.get("operator") == binding["operator"]
                       and (str(expectation.get("required_set_ref", "")).partition("#/")[0]
                            == binding.get("authority") if binding["operator"] == "covers_all"
                            else expectation.get("value") == 0
                            and expectation.get("unit") == "count"))
        if not declared_ok:
            result["obligations"].append({"id": oid,
                "status": "UNIMPLEMENTED_METRIC_BINDING"})
            continue
        measurement = measured[oid]
        if measurement.get("status") == "FAIL":
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "FAIL",
                "detail": measurement.get("reason"), "measurement": measurement})
            continue
        if measurement.get("status") != "MEASURED":
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "NOT_MEASURED",
                "reason": measurement.get("reason", "METRIC_ACCEPTANCE_REFUSED"),
                "detail": measurement.get("detail"), "measurement": measurement})
            continue
        try:
            authority = (_d71_authority(project, binding, pending,
                                        "annotation" if oid.endswith("final_sdf_annotation")
                                        else "scenario")
                         if binding["operator"] == "covers_all" else
                         {"status": "APPROVED", "value": 0, "unit": "count",
                          "authority": "flow109_registry_contract",
                          "registry_sha256": context.get("registry_sha256")})
            status, detail = evaluate_operator(binding["operator"], measurement, authority)
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": status, "detail": detail,
                "measurement": measurement, "authority": authority})
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            result["obligations"].append({"id": oid, "metric": obligation.get("metric"),
                "operator": binding["operator"], "status": "NOT_MEASURED",
                "reason": getattr(exc, "code", "METRIC_ACCEPTANCE_REFUSED"),
                "detail": str(exc)})
    statuses = [item["status"] for item in result["obligations"]]
    if "FAIL" in statuses:
        result.update(status="FAIL", metric_status="FAIL", reason="MEASURED_METRIC_FAILURE")
    elif statuses and all(status == "PASS" for status in statuses) \
            and len(statuses) == len(declared):
        result["metric_status"] = "PASS"
        if (component.get("component_status") == "PASS"
                and component.get("full_row_acceptance") == "PASS"
                and pending.get("upstream_scope_complete") is True):
            result.update(status="PASS", delivery_blocked=False,
                          reason="ALL_APPLICABLE_METRICS_AND_UPSTREAM_SCOPE_PASS")
        else:
            result["reason"] = "D71_UPSTREAM_OR_FINAL_SCOPE_NOT_ACCEPTED"
    else:
        result["reason"] = "METRIC_BINDING_INCOMPLETE_OR_NOT_CURRENT"
    return result
