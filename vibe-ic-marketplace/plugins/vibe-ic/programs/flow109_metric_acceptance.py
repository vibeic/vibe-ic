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
from decimal import Decimal
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


def dft_port_consistency(binding: Mapping, elaboration: Mapping, top: str) -> dict:
    """Compare declared scan access with the selected Yosys-elaborated top."""
    intent = binding.get("intent") if isinstance(binding, Mapping) else None
    if not isinstance(intent, Mapping) or type(intent.get("requires_scan")) is not bool:
        return {"status": "NOT_MEASURED", "reason": "DFT_INTENT_MISSING"}
    if not intent["requires_scan"]:
        return {"status": "NOT_MEASURED", "reason": "SCAN_NOT_REQUIRED",
                "skip_reason": intent.get("reason")}
    declared = intent.get("test_port_def")
    ports = ((elaboration.get("modules") or {}).get(top) or {}).get("ports")
    roles = {"scan_enable": "input", "scan_in": "input", "scan_out": "output",
             "test": "input", "tck": "input"}
    if not isinstance(declared, Mapping) or not isinstance(ports, Mapping):
        return {"status": "NOT_MEASURED", "reason": "DFT_PORT_EVIDENCE_MISSING"}
    mismatches = []
    for role, direction in roles.items():
        entry = declared.get(role)
        name = entry.get("public") if isinstance(entry, Mapping) else None
        if not isinstance(name, str) or not name:
            return {"status": "NOT_MEASURED", "reason": "DFT_PORT_DECLARATION_MISSING"}
        actual = ports.get(name)
        if not isinstance(actual, Mapping) or actual.get("direction") != direction or len(actual.get("bits", [])) != 1:
            mismatches.append({"role": role, "port": name, "expected_direction": direction})
    return {"status": "FAIL" if mismatches else "PASS",
            "reason": "DFT_PORT_MISMATCH" if mismatches else "DFT_PORTS_MATCH",
            "mismatches": mismatches}


def dry_run_d10(project: Path, gate: str) -> dict:
    """Run one existing D10 frontend gate without publishing project artifacts.

    This is diagnostic, not a metric binding or a Flow109 acceptance decision.
    """
    import os
    import shutil
    import tempfile
    import _cdc_netlist as native
    import _specrtl_common
    import librelane_contract as contract
    import p0_tool_frontend_check as frontend

    answer = {'step_id': 'D10', 'gate': gate, 'dry_run': True,
              'gate_status': 'NOT_MEASURED', 'row_status': 'NOT_MEASURED',
              'tool_qualification': 'NOT_MEASURED', 'delivery_accepted': False}
    if gate not in ('p0_tool_frontend_check', 'dft_port_consistency'):
        answer['reason'] = 'UNPROVEN_ADAPTER_BINDING'
        if gate == 'feature_inventory' and not (project / 'adopted/base_04/feature_inventory.json').is_file():
            answer['reason'] = 'MISSING_ADOPTED_FEATURE_INVENTORY'
        return answer
    try:
        files = _specrtl_common.rtl_source_files(project)
        top = frontend._top(project)
        if not files or not top:
            raise ValueError('selected RTL or top is missing')
        before = native.source_binding(project, top, files)
        binding = None
        if gate == 'dft_port_consistency':
            import fault_scan_chain_insert as scan
            binding, problems = scan.load_d09_dft_contract(project)
            if binding is None or problems:
                raise ValueError('DFT intent unavailable: ' + '; '.join(problems))
        paths = {name: shutil.which(name) for name in ('yosys', 'verilator')}
        if any(not path for path in paths.values()):
            raise ValueError('native frontend tools unavailable')
        def tool_hashes():
            return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for name, path in paths.items()}
        tools_before = tool_hashes()
        authority = (contract.local_image_attestation()
                     if os.environ.get(contract.LOCAL_ATTESTATION_ENV) else None)
        with tempfile.TemporaryDirectory(prefix='flow109-d10-gate-') as td:
            result = frontend.check(project, output_project=Path(td))
            elab = Path(td) / frontend.RTL_ELAB_REL
            elab_sha = hashlib.sha256(elab.read_bytes()).hexdigest() if elab.is_file() else None
            elaboration = json.loads(elab.read_text()) if elab_sha else None
        after = native.source_binding(project, top, _specrtl_common.rtl_source_files(project))
        if gate == 'dft_port_consistency':
            current_binding, problems = scan.load_d09_dft_contract(project)
            if current_binding != binding or problems:
                raise ValueError('DFT intent changed during diagnostic')
        if before != after or tools_before != tool_hashes():
            raise ValueError('source or tools changed during diagnostic')
        tools = result.get('tools') or {}
        codes = {name: (tools.get(name) or {}).get('exit_code')
                 for name in ('Yosys.JsonHeader', 'Verilator.Lint')}
        answer.update(input_fingerprint=before['fingerprint'], tool_sha256=tools_before,
                      image_id=authority.get('image_id') if authority else None,
                      cid=authority.get('cid') if authority else None,
                      native_exit_codes=codes, findings=result.get('findings', []),
                      elaboration_sha256=elab_sha)
        if result.get('not_measured') or any(type(code) is not int for code in codes.values()):
            answer['reason'] = 'NATIVE_FRONTEND_NOT_MEASURED'
        elif any(code < 0 or code >= 128 for code in codes.values()):
            answer['reason'] = 'NATIVE_FRONTEND_ABNORMAL_TERMINATION'
        elif result.get('passed') is True and elab_sha:
            if gate == 'dft_port_consistency':
                port_result = dft_port_consistency(binding, elaboration, top)
                answer.update(gate_status=port_result['status'], reason=port_result['reason'],
                              port_evidence=port_result, intent_binding=binding)
            else:
                answer.update(gate_status='PASS', reason='NATIVE_FRONTEND_PASS')
        elif result.get('passed') is False:
            answer.update(gate_status='FAIL', reason='NATIVE_FRONTEND_FAIL')
            answer['native_diagnostics'] = {
                name: str((tools.get(name) or {}).get('output', ''))[-2000:]
                for name in codes}
        else:
            answer['reason'] = 'NATIVE_FRONTEND_OUTPUT_MISSING'
    except (native.Refusal, contract.Refusal, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer['reason'] = 'NATIVE_FRONTEND_UNAVAILABLE'
        answer['detail'] = str(exc)
    return answer

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

D31_BINDINGS = {
    "base_20.floorplan_boundary_pin_feasibility": {
        "operator": "within_declared_bounds",
        "bounds_ref": "requirements/base_20/floorplan_boundary_pin_feasibility.json#/limits",
        "unit_ref": "requirements/base_20/floorplan_boundary_pin_feasibility.json#/units",
        "missing_bounds": "BLOCKED",
    },
    "base_20.illegal_macro_overlap": {
        "operator": "eq", "value": 0, "unit": "count",
        "source": "contract invariant: no unresolved required violations",
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

D19_BINDINGS = {
    "base_10.exception_justification": {
        "operator": "covers_all",
        "required_set_ref": "requirements/base_10/exception_justification.json#/required_items",
    },
    "base_10.scenario_constraints": {
        "operator": "covers_all",
        "required_set_ref": "requirements/base_10/scenario_constraints.json#/required_items",
    },
    "base_10.mode_library_rc_mapping": {
        "operator": "matches_adopted_reference",
        "reference_ref": "adopted/base_10/mode_library_rc_mapping.json",
    },
}

D30_BINDINGS = {
    "base_19.adopted_netlist_sdc_library": {
        "operator": "matches_adopted_reference",
        "reference_ref": "adopted/base_19/adopted_netlist_sdc_library.json",
    },
    "base_19.post_synth_crossing_power_changes": {
        "operator": "covers_all",
        "required_set_ref": "requirements/base_19/post_synth_crossing_power_changes.json#/required_items",
        "empty_set_policy": "requires validated absence/applicability evidence",
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
            or not isinstance(approval, dict)
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


def _d19_ref(project: Path, record: Any, label: str) -> dict:
    """Reopen a declared input; neither a corner name nor a path is evidence."""
    if (not isinstance(record, Mapping) or set(record) != {"path", "sha256"}
            or not isinstance(record.get("path"), str)
            or Path(record["path"]).is_absolute()
            or ".." in Path(record["path"]).parts
            or Path(record["path"]).as_posix() != record["path"]
            or not _HEX.fullmatch(str(record.get("sha256", "")))):
        raise MetricRefusal("D19_INPUT_IDENTITY_MISSING", label)
    path = _safe_project_file(project, record["path"])
    if not path.is_file() or not path.stat().st_size or _sha(path.read_bytes()) != record["sha256"]:
        raise MetricRefusal("D19_INPUT_STALE", label + ": " + record["path"])
    return dict(record)


def d19_admission(project: Path, context: Mapping[str, Any], *, publish: bool = False) -> dict:
    """BLOCKING plan admission before the existing SDC producer dispatches.

    Consume the two registry contracts, or project their explicit declarations
    from L19 into those same paths. Approval must bind their semantic payload in
    an input JSON document, not merely an unrelated document's hash. D01 owns
    scan applicability; L20 is required for scan, never an override of D01.
    This checks a plan and current files, not native shift/capture execution.
    """
    import flow109
    import l_doc_consumer_contract as layers
    from _atomic_artefact import write_json

    project = Path(project).resolve()
    features = context.get("features", {})
    technology = features.get("technology_specific")
    if (type(technology) is not bool
            or not technology and (features.get("soft_ip") is not True
                                  or features.get("physical") or features.get("digital_netlist"))):
        raise MetricRefusal("D19_TECHNOLOGY_APPLICABILITY_UNRESOLVED", "resolved endpoint required")
    try:
        intent = flow109.dft_source_intent(project, context)
    except flow109.Flow109Error as exc:
        raise MetricRefusal("D19_D01_AUTHORITY_UNAVAILABLE", str(exc)) from exc
    layer_docs, layer_refs = {}, {}
    for name in ("L19", "L20"):
        path, body = layers.load_l_doc(project, name)
        if path is None or not isinstance(body, Mapping):
            if name == "L20" and not intent["requires_scan"]:
                continue
            raise MetricRefusal("D19_" + name + "_MISSING", name)
        path = Path(path)
        layer_docs[name] = body
        layer_refs[name] = _d19_ref(project, {
            "path": path.relative_to(project).as_posix(), "sha256": _sha(path.read_bytes())}, name)
    sources = {"D01": intent["source_binding"], **layer_refs}
    documents, authorities = {}, {}
    fields = layer_docs["L19"].get("fields")
    fields = fields if isinstance(fields, Mapping) else {}
    for name, relative, schema in (
            ("scenario_constraints", "requirements/base_10/scenario_constraints.json", AUTHORITY_SCHEMA),
            ("mode_library_rc_mapping", "adopted/base_10/mode_library_rc_mapping.json",
             "vibeic.flow109.adopted-reference.v1")):
        path = _safe_project_file(project, relative)
        body = (json.loads(path.read_text()) if path.is_file()
                else fields.get(name))
        if not isinstance(body, Mapping):
            raise MetricRefusal("D19_APPROVED_" + name.upper() + "_MISSING", relative)
        approval = body.get("approval")
        if (body.get("schema") != schema or not isinstance(approval, Mapping)
                or approval.get("status") != "APPROVED"
                or approval.get("authority") != "requirements_owner"
                or not isinstance(approval.get("approver"), str)
                or not approval["approver"].strip()):
            raise MetricRefusal("D19_PLAN_UNAPPROVED", relative)
        ref = _d19_ref(project, approval.get("source_reference"), name + " approval")
        if (not ref["path"].startswith("input/")
                or not (project / ref["path"]).resolve().is_relative_to((project / "input").resolve())):
            raise MetricRefusal("D19_APPROVED_INPUT_MISSING", name)
        try:
            approved = json.loads((project / ref["path"]).read_text())[name]
        except (ValueError, KeyError, TypeError) as exc:
            raise MetricRefusal("D19_APPROVED_STRUCTURED_SOURCE_MISSING", name) from exc
        payload = {key: value for key, value in body.items()
                   if key not in ("schema", "approval", "producer_binding")}
        if payload != approved:
            raise MetricRefusal("D19_APPROVED_FIELDS_DIFFER", name)
        documents[relative] = dict(body)
        authorities[name] = {"status": "APPROVED", "source": ref, **payload}
    requirement = authorities["scenario_constraints"]
    modes, checks = (requirement.get(key) for key in ("required_modes", "required_checks"))
    corners = requirement.get("required_corners", [])
    for label, values in (("MODES", modes), ("CORNERS", corners), ("CHECKS", checks)):
        if (not isinstance(values, list) or not values and (label != "CORNERS" or technology)
                or any(not isinstance(value, str) or not _SAFE.fullmatch(value) for value in values)
                or len(set(values)) != len(values)):
            raise MetricRefusal("D19_APPROVED_" + label + "_MISSING", label)
    if not technology and corners:
        raise MetricRefusal("D19_TECHNOLOGY_FEATURE_CONFLICT", "portable plan declares target corners")
    mandatory_modes = {"functional", "shift", "capture"} if intent["requires_scan"] else {"functional"}
    if not mandatory_modes.issubset(modes):
        raise MetricRefusal("D19_REQUIRED_MODE_MISSING", ",".join(sorted(mandatory_modes - set(modes))))
    if not {"setup", "hold"}.issubset(checks):
        raise MetricRefusal("D19_REQUIRED_CHECK_MISSING", "setup/hold")
    required = requirement.get("required_items")
    item_fields = ("mode", "corner", "check") if technology else ("mode", "check")
    if (not isinstance(required, list) or not required
            or any(not isinstance(item, Mapping) or set(item) != set(item_fields)
                   or item["mode"] not in modes or technology and item["corner"] not in corners
                   or item["check"] not in checks for item in required)
            or len(set(map(_json_key, required))) != len(required)):
        raise MetricRefusal("D19_SCENARIO_INVALID", "approved required_items")
    # The owner declares combinations. A Cartesian product would invent extra
    # corner/check requirements (e.g. setup and hold need not use one corner).
    if any({item[key] for item in required} != set(values)
           for key, values in (("mode", modes), ("corner", corners), ("check", checks))
           if key in item_fields):
        raise MetricRefusal("D19_REQUIRED_SCENARIO_MISSING", "approved mode/corner/check census")
    expected = required
    mapping = authorities["mode_library_rc_mapping"].get("reference")
    if not isinstance(mapping, list) or not mapping:
        raise MetricRefusal("D19_LIBRARY_RC_MAPPING_MISSING", "reference")
    actual, consumed = [], {}
    for entry in mapping:
        if not isinstance(entry, Mapping) or any(key not in entry for key in item_fields):
            raise MetricRefusal("D19_SCENARIO_INVALID", "mapping entry")
        item = {key: entry[key] for key in item_fields}
        if item not in expected:
            raise MetricRefusal("D19_SCENARIO_UNAPPROVED", _json_key(item))
        libraries, rc = entry.get("libraries"), entry.get("rc")
        refs = [(entry.get("sdc"), "sdc")]
        if technology:
            if not isinstance(libraries, list) or not libraries:
                raise MetricRefusal("D19_LIBRARY_MAPPING_MISSING", _json_key(item))
            if (not isinstance(rc, Mapping) or not isinstance(rc.get("corner"), str)
                    or not rc["corner"] or "model" not in rc):
                raise MetricRefusal("D19_RC_MAPPING_MISSING", _json_key(item))
            refs += [(rc["model"], "rc"), *((lib, "library") for lib in libraries)]
        elif libraries or rc or "corner" in entry:
            raise MetricRefusal("D19_TECHNOLOGY_FEATURE_CONFLICT", "portable mapping declares technology")
        for ref, label in refs:
            current = _d19_ref(project, ref, _json_key(item) + ":" + label)
            consumed[current["path"]] = current["sha256"]
        actual.append(item)
    if (len(actual) != len(set(map(_json_key, actual)))
            or set(map(_json_key, actual)) != set(map(_json_key, expected))):
        missing = set(map(_json_key, expected)) - set(map(_json_key, actual))
        raise MetricRefusal("D19_REQUIRED_SCENARIO_MISSING", ",".join(sorted(missing)))
    producer = HERE / "design_one_shot_runner.py"
    binding = {"sources": sources, "consumed_inputs": dict(sorted(consumed.items())),
               "producer_sha256": _sha(producer.read_bytes()),
               "checker_sha256": _sha(Path(__file__).read_bytes()),
               "context_sha256": context["context_sha256"]}
    artifacts = {}
    for relative, body in documents.items():
        path = _safe_project_file(project, relative)
        if publish:
            write_json(path, {**body, "producer_binding": binding})
        if not path.is_file() or json.loads(path.read_text()).get("producer_binding") != binding:
            raise MetricRefusal("D19_PRODUCER_BINDING_MISSING", relative)
        artifacts[relative] = {"path": relative, "sha256": _sha(path.read_bytes())}
    result = {"schema": "vibeic.flow109.d19-plan-admission.v1", "step_id": "D19",
            "binding": binding, "artifacts": artifacts, "authorities": authorities,
            "scenarios": actual, "mapping": mapping, "native_dispatched": False,
            "native_controls_qualification": "NOT_MEASURED"}
    if publish and d19_admission(project, context) != result:
        raise MetricRefusal("D19_INPUTS_CHANGED_DURING_PUBLICATION", "plan inputs")
    return result


D19_PURPOSE = 'D19.default.constraint_plan_load'
D19_STEPS = ['Python.SDCPlan', 'Misc.LoadBaseSDC']


def d19_native_module() -> dict:
    """The actual installed legacy copy step, not a timing/STA capability."""
    import inspect
    import importlib.metadata
    from librelane.steps.misc import LoadBaseSDC
    path = Path(inspect.getfile(LoadBaseSDC)).resolve()
    return {'path': str(path), 'sha256': _sha(path.read_bytes()),
            'version': importlib.metadata.version('librelane'), 'step': LoadBaseSDC.id}


def d19_model_sources() -> dict:
    import ast
    import design_one_shot_runner as producer
    import vibe_ic_one_shot_runner as public
    sources = {}
    for module, names in ((Path(__file__), ('d19_admission', 'accept_d19', '_d19_native_outputs',
            '_d19_exception_observe', '_d19_exception_commands', '_d19_qualification', 'd19_native_module', 'd19_model_sources')),
            (Path(producer.__file__), ('step_asic_sdc', '_d19_load_base_sdc', '_publish_d19_owner')),
            (Path(public.__file__), ('_finish_d19_selected_owner',))):
        text = module.read_text()
        nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
        for name in names:
            sources[module.name + ':' + name] = _sha(ast.get_source_segment(text, nodes[name]).encode())
    return sources


def _d19_exception_commands(path: Path) -> list[str]:
    """Census a bounded static plan input; do not claim Tcl/SDC validation.

    Runtime Tcl and unclassified commands stay unresolved. No evaluation or
    synthesized netlist/STA is needed merely to identify approved exceptions.
    """
    exceptions = {'set_false_path', 'set_multicycle_path', 'set_clock_groups',
                  'set_max_delay', 'set_min_delay', 'set_disable_timing', 'set_data_check'}
    ordinary = {'create_clock', 'create_generated_clock', 'set_units', 'set_input_delay',
                'set_output_delay', 'set_clock_uncertainty', 'set_clock_latency',
                'set_clock_transition', 'set_clock_groups', 'set_propagated_clock',
                'set_ideal_network', 'set_input_transition', 'set_driving_cell', 'set_load',
                'set_max_transition', 'set_max_fanout', 'set_max_capacitance', 'set_case_analysis',
                'set_clock_sense', 'set_timing_derate', 'set_operating_conditions', 'set_wire_load_model'}
    collections = {'get_ports', 'get_pins', 'get_clocks', 'get_cells', 'get_nets',
                   'all_inputs', 'all_outputs', 'all_clocks', 'all_registers', 'current_design'}
    text = re.sub(r'\\\r?\n', ' ', path.read_text())
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        command = line.split()[0]
        if (command not in ordinary | exceptions or any(c in line for c in (';', '$'))
                or any(x not in collections for x in re.findall(r'\[\s*([^\s\[\]]+)', line))):
            raise MetricRefusal('D19_EXCEPTION_CENSUS_UNSUPPORTED', str(path))
        if command in exceptions:
            found.append(' '.join(line.split()))
    if len(found) != len(set(found)):
        raise MetricRefusal('D19_EXCEPTION_CENSUS_AMBIGUOUS', str(path))
    return found


def _d19_native_outputs(project: Path, current: Mapping, component: Mapping) -> tuple[list, dict]:
    """Reopen genuine normal native step config/state and unchanged SDC bytes."""
    loads = component.get('native_sdc_outputs')
    if not isinstance(loads, list) or len(loads) != len(current['mapping']):
        raise MetricRefusal('D19_NATIVE_SDC_OUTPUTS_MISSING', 'Misc.LoadBaseSDC')
    files = {}
    module = d19_native_module()
    fields = ('mode', 'corner', 'check')
    for entry, output in zip(current['mapping'], loads):
        scenario = {k: entry[k] for k in fields if k in entry}
        if (output.get('scenario') != scenario or output.get('source_sdc') != entry['sdc']
                or output.get('native_module') != module):
            raise MetricRefusal('D19_NATIVE_INPUT_IDENTITY_MISMATCH', str(scenario))
        for name in ('sdc', 'config', 'state'):
            ref = _d19_ref(project, output.get(name), 'native ' + name)
            files[ref['path']] = ref['sha256']
        cfg = json.loads((project / output['config']['path']).read_text())
        state = json.loads((project / output['state']['path']).read_text())
        target = _safe_project_file(project, output['sdc']['path'])
        if (cfg.get('meta', {}).get('step') != 'Misc.LoadBaseSDC'
                or cfg.get('FALLBACK_SDC') != str((project / entry['sdc']['path']).resolve())
                or target.name != str(cfg.get('DESIGN_NAME')) + '.sdc'
                or state.get('sdc') != str(target)
                or output['sdc']['sha256'] != entry['sdc']['sha256']):
            raise MetricRefusal('D19_NATIVE_SDC_OUTPUT_MISMATCH', str(scenario))
    return loads, files


def _d19_exception_observe(project: Path, context: Mapping, current: Mapping, component: Mapping) -> tuple:
    fields = ('mode', 'corner', 'check') if context['features']['technology_specific'] else ('mode', 'check')
    fields += ('command', 'justification')
    authority, body = _approved_authority(project, D19_BINDINGS['base_10.exception_justification']['required_set_ref'], fields)
    source = json.loads((project / authority['source']['path']).read_text())
    payload = {k: v for k, v in body.items() if k not in ('schema', 'approval', 'producer_binding')}
    if (not authority['source']['path'].startswith('input/')
            or source.get('exception_justification') != payload):
        raise MetricRefusal('D19_APPROVED_EXCEPTION_FIELDS_DIFFER', 'exception_justification')
    loads, files = _d19_native_outputs(project, current, component)
    actual, required = [], authority['required_items']
    for entry, output in zip(current['mapping'], loads):
        scenario = {k: entry[k] for k in fields if k in entry}
        commands = _d19_exception_commands(project / output['sdc']['path'])
        for command in commands:
            matches = [r for r in required if all(r.get(k) == v for k, v in scenario.items())
                       and r['command'] == command and r['justification'].strip()]
            if len(matches) != 1:
                raise MetricRefusal('D19_EXCEPTION_UNJUSTIFIED', command)
            actual.append(matches[0])
    if set(map(_json_key, actual)) != set(map(_json_key, required)):
        raise MetricRefusal('D19_REQUIRED_EXCEPTION_MISSING', 'approved vs actual emitted SDC census')
    files[authority['path']] = authority['sha256']
    files[authority['source']['path']] = authority['source']['sha256']
    if not required:
        absence = body['validated_absence']['source_reference']
        files[absence['path']] = absence['sha256']
    for path, digest in files.items():
        _d19_ref(project, {'path': path, 'sha256': digest}, 'exception readback')
    return actual, authority, files


def _d19_qualification(project: Path, context: Mapping) -> dict:
    import flow109_admission as admission
    qualified = admission.require_admission(project, context)
    uses = context['runtime_tool_uses']
    if (len(uses) != 1 or uses[0]['tool_id'] != 'python3'
            or uses[0]['semantics'] != {'purpose': 'D19.default', 'native_steps': D19_STEPS}):
        raise MetricRefusal('D19_QUALIFICATION_SCOPE_INVALID', 'constraint plan + native SDC copy only')
    expected = {'purpose': D19_PURPOSE, 'native_steps': D19_STEPS,
                'model_sources': d19_model_sources(), 'native_module': d19_native_module()}
    if json.loads((project / uses[0]['config']['path']).read_text()) != expected:
        raise MetricRefusal('D19_MODEL_QUALIFICATION_STALE', 'actual consumed model/module')
    return qualified


def accept_d19(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """Reopen the actual producer's existing contracts and all consumed files.

    Read the actual exception census/approved plan and native SDC copy outputs.
    This row does not claim later SDC semantic validation, STA or scan timing.
    """
    result = {"schema": SCHEMA, "row_id": "D19", "status": "NOT_MEASURED",
              "metric_status": "NOT_MEASURED", "qualification": "NOT_MEASURED",
              "scope": "constraint plan and Misc.LoadBaseSDC copy; not SDC validation or STA",
              "delivery_blocked": True, "obligations": []}
    try:
        current = d19_admission(project, context)
        if component.get("d19_plan_admission") != current:
            raise MetricRefusal("D19_PRODUCER_RECEIPT_STALE", "current plan differs")
        consumed = dict(current["binding"]["consumed_inputs"])
        if not context["features"]["technology_specific"]:
            import _path_layout as layout
            outputs = component.get("portable_sdc_outputs")
            if not isinstance(outputs, list) or len(outputs) != len(current["mapping"]):
                raise MetricRefusal("D19_PORTABLE_SDC_OUTPUTS_MISSING", "current producer outputs")
            for output, entry in zip(outputs, current["mapping"]):
                expected = (layout.constraints_dir(project) /
                            f"{entry['mode']}.{entry['check']}.sdc").relative_to(project).as_posix()
                if (not isinstance(output, Mapping) or output.get("source_sdc") != entry["sdc"]
                        or not isinstance(output.get("sdc"), Mapping)
                        or output["sdc"].get("path") != expected):
                    raise MetricRefusal("D19_PORTABLE_SDC_OUTPUT_MISMATCH", expected)
                actual_output = _d19_ref(project, output["sdc"], expected)
                if actual_output["sha256"] != entry["sdc"]["sha256"]:
                    raise MetricRefusal("D19_PORTABLE_SDC_OUTPUT_MISMATCH", expected)
                consumed[actual_output["path"]] = actual_output["sha256"]
        binding = current["binding"]
        identity = {"producer": {"sha256": binding["producer_sha256"]},
                    "checker": {"sha256": binding["checker_sha256"]},
                    "tool_execution": {"kind": "python_constraint_plan_admission",
                                       "native_qualification": "NOT_MEASURED"},
                    "consumed_inputs": consumed,
                    "requirements": current["artifacts"],
                    "configuration": {"context_sha256": context["context_sha256"],
                                      "sources": binding["sources"]}}
        for obligation in context["resolved_row"]["obligations"]:
            oid = obligation["id"]
            spec = D19_BINDINGS.get(oid)
            if spec is None or any(obligation["expectation"].get(key) != value
                                   for key, value in spec.items()):
                result["obligations"].append({"id": oid, "status": "UNIMPLEMENTED_METRIC_BINDING"})
                continue
            name = oid.split(".")[-1]
            if name == "exception_justification":
                try:
                    values, authority, native_files = _d19_exception_observe(project, context, current, component)
                    native_identity = dict(identity, consumed_inputs={**consumed, **native_files},
                        tool_execution={"kind": "Misc.LoadBaseSDC", "scope": "copy only, no SDC semantics or STA"})
                    measured = {"status": "MEASURED", "identity": native_identity, "value": values}
                    status, detail = evaluate_operator(spec['operator'], measured, authority)
                    result['obligations'].append({'id': oid, 'status': status,
                        'measurement': measured, 'authority': authority, 'detail': detail})
                except (MetricRefusal, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
                    result['obligations'].append({'id': oid, 'status': 'NOT_MEASURED',
                        'reason': getattr(exc, 'code', 'D19_EXCEPTION_NOT_MEASURED'), 'detail': str(exc)})
                continue
            if name == "mode_library_rc_mapping" and not context["features"]["technology_specific"]:
                result["obligations"].append({"id": oid, "status": "NOT_MEASURED",
                    "reason": "D19_TARGET_TECHNOLOGY_NOT_SPECIFIED"})
                continue
            authority = dict(current["authorities"][name])
            if name == "mode_library_rc_mapping":
                authority["reference_identity"] = identity
            measured = {"status": "MEASURED", "identity": identity,
                        "value": current["scenarios"] if name == "scenario_constraints" else current["mapping"]}
            status, detail = evaluate_operator(spec["operator"], measured, authority)
            result["obligations"].append({"id": oid, "status": status,
                "measurement": measured, "authority": authority, "detail": detail})
        statuses = [item["status"] for item in result["obligations"]]
        result["reason"] = "D19_REQUIRED_PLAN_INPUTS_OR_NATIVE_LOAD_NOT_MEASURED"
        if statuses and all(status == "PASS" for status in statuses):
            result['metric_status'] = 'PASS'
            import flow109_admission as admission
            try:
                qualified = _d19_qualification(project, context)
            except (admission.AdmissionRefusal, MetricRefusal, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
                qualified = {'status': 'NOT_MEASURED', 'reason': getattr(exc, 'code', 'D19_QUALIFICATION_NOT_MEASURED'), 'detail': str(exc)}
            result['qualification'] = qualified['status']
            result['admission'] = qualified
            result['reason'] = qualified.get('reason', 'D19_QUALIFICATION_NOT_MEASURED')
            if qualified['status'] == 'PASS':
                result.update(status='PASS', delivery_blocked=False, reason='D19_PLAN_AND_NATIVE_COPY_QUALIFIED')
        elif "FAIL" in statuses:
            result['status'] = result['metric_status'] = 'FAIL'
        if d19_admission(project, context) != current:
            raise MetricRefusal('D19_INPUTS_CHANGED_DURING_READ', 'current plan changed')
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        # A final readback refusal revokes delivery, even after qualification.
        # Preserve any already observed failure and its bound measurement.
        failed = result['status'] == 'FAIL' or any(
            item['status'] == 'FAIL' for item in result['obligations'])
        result.update(status='FAIL' if failed else 'NOT_MEASURED',
            metric_status='FAIL' if failed else 'NOT_MEASURED',
            qualification='NOT_MEASURED', delivery_blocked=True,
            reason=getattr(exc, "code", "D19_METRIC_REFUSED"),
            detail=str(exc) + '; prior_reason=' + str(result.get('reason')))
    return result


D20_STEPS = ['sdc_syntax_check._regex_audit', 'sdc_validator_check.evaluate',
             'sdc_exception_correlation_check.audit']
D20_REFERENCE = 'adopted/base_11/cdc_exception_reconciliation.json'


def d20_model_sources():
    """Bind the Python SDC algorithms, their helpers/constants and D20 owner.

    Importing a runner is not consuming every phase it can dispatch. Follow
    symbol references only within this method's existing pure Python modules;
    keep the two shared owner functions scoped to their own source segments.
    """
    import ast
    import design_one_shot_runner as owner
    modules = ('flow109_metric_acceptance', 'sdc_syntax_check',
        'sdc_validator_check', 'sdc_exception_correlation_check',
        'sdc_constraints', '_path_layout', '_reference_flow_boundary',
        '_design_module_set')
    texts, definitions, imports = {}, {}, {}
    for module in modules:
        path = Path(__file__) if module == 'flow109_metric_acceptance' else HERE / (module + '.py')
        texts[module] = path.read_text()
        definitions[module], imports[module] = {}, {}
        for node in ast.parse(texts[module]).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                definitions[module][node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name):
                            definitions[module][name.id] = node
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for name in node.names:
                    alias = name.asname or name.name.split('.')[0]
                    target = (name.name, None) if isinstance(node, ast.Import) else (node.module, name.name)
                    imports[module][alias] = (node, target)
    pending = [('flow109_metric_acceptance', name) for name in
        ('d20_model_sources', 'd20_input_files', '_d20_observe', 'accept_d20')]
    pending.extend(tuple(step.split('.')) for step in D20_STEPS)
    pending.extend([('_design_module_set', '_source_files'),
        ('_path_layout', 'rtl_dir'), ('_path_layout', 'fpga_early_dir'),
        ('_path_layout', 'synth_dir')])
    result = {}
    while pending:
        module, name = pending.pop()
        key = module + '.py:' + name
        if key in result:
            continue
        node = definitions[module][name]
        result[key] = _sha(ast.get_source_segment(texts[module], node).encode())
        aliases = dict(imports[module])
        for part in ast.walk(node):
            if isinstance(part, (ast.Import, ast.ImportFrom)):
                for item in part.names:
                    alias = item.asname or item.name.split('.')[0]
                    target = (item.name, None) if isinstance(part, ast.Import) else (part.module, item.name)
                    aliases[alias] = (part, target)
        for part in ast.walk(node):
            if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load):
                if part.id in definitions[module]:
                    pending.append((module, part.id))
                if part.id in aliases:
                    declaration, (target, imported) = aliases[part.id]
                    result[module + '.py:import:' + part.id] = _sha(
                        ast.get_source_segment(texts[module], declaration).encode())
                    if target in definitions and imported in definitions[target]:
                        pending.append((target, imported))
            elif isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name):
                binding = aliases.get(part.value.id)
                if binding:
                    target, imported = binding[1]
                    if target in definitions and imported is None and part.attr in definitions[target]:
                        pending.append((target, part.attr))
    text = Path(owner.__file__).read_text()
    nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    for name in ('step_sdc_validation', '_complete_d20_validation'):
        result['design_one_shot_runner.py:' + name] = _sha(ast.get_source_segment(text, nodes[name]).encode())
    return result


def d20_input_files(project, source):
    import _design_module_set as modules
    import _path_layout as layout
    paths = [source, project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
             project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json',
             project / 'reports/phase2/cdc/crossing.json']
    # Bind exactly the existing validator's module-set readset. Optional FPGA
    # or synth outputs are observed only when present, never required here.
    paths.extend(modules._source_files([layout.rtl_dir(project),
        layout.fpga_early_dir(project), layout.synth_dir(project)]))
    return {str(p.relative_to(project)): _sha(p.read_bytes()) if p.is_file() else None for p in paths}


def _d20_observe(project, context, component):
    import sdc_syntax_check as syntax
    import sdc_validator_check as validator
    import sdc_exception_correlation_check as correlation
    evidence = component.get('d20_evidence', {})
    authority = component.get('sdc_authority', {})
    source = _d19_ref(project, authority.get('source'), 'original caller SDC')
    path = _safe_project_file(project, source['path'])
    if path.parent != project / 'input/constraints':
        raise MetricRefusal('D20_FOREIGN_SDC', source['path'])
    inputs = d20_input_files(project, path)
    if (evidence.get('inputs') != inputs or evidence.get('model_sources') != d20_model_sources()
            or any(v is None for v in inputs.values())
            or not any(k.startswith('phase2/stage1/rtl/') for k in inputs)):
        raise MetricRefusal('D20_INPUT_OR_METHOD_STALE', 'complete SDC/RTL/L8/CDC readset required')
    for relative, digest in inputs.items():
        _d19_ref(project, {'path': relative, 'sha256': digest}, relative)
    reports = evidence.get('reports')
    expected_reports = ['reports/phase2/sdc_check.json', 'reports/sdc_validator.json',
                        'reports/phase2/sdc_exception_correlation.json']
    if not isinstance(reports, dict) or set(reports) != set(expected_reports):
        raise MetricRefusal('D20_PREFLIGHT_EVIDENCE_ABSENT', 'all three original checker reports required')
    stored = []
    for relative in expected_reports:
        _d19_ref(project, {'path': relative, 'sha256': reports[relative]}, relative)
        body = json.loads((project / relative).read_text())
        if body.get('sdc_authority') != authority:
            raise MetricRefusal('D20_PREFLIGHT_BINDING_MISMATCH', relative)
        bound = body.get('summary', body)
        if (bound.get('sdc_sha256_expected') != source['sha256']
                or bound.get('sdc_sha256_observed') != source['sha256']
                or bound.get('sdc_files_checked') != [str(path)]):
            raise MetricRefusal('D20_PREFLIGHT_BINDING_MISMATCH', relative)
        stored.append(body)
    commands = _d19_exception_commands(path)
    # Existing correlation checks model clock-to-clock false/multicycle paths.
    # Other static exception commands are censused, but not silently validated.
    for command in commands:
        clock = r'\[get_clocks\s+(?:\w+|\{\w+\})\]'
        if not re.fullmatch(r'(?:set_false_path|set_multicycle_path\s+[1-9]\d*(?:\s+-(?:setup|hold))?)'
                            r'\s+-from\s+' + clock + r'\s+-to\s+' + clock, command):
            raise MetricRefusal('D20_EXCEPTION_METHOD_UNSUPPORTED', command)
    fresh_syntax = syntax._regex_audit(str(project), include_phase3=False,
                                      sdc_path=path, sdc_sha256=source['sha256'])
    fresh_validator = validator.evaluate(project, project / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json',
                                         sdc_path=path, sdc_sha256=source['sha256'])
    fresh = correlation.audit(project, sdc_path=path, sdc_sha256=source['sha256'])
    if (stored[0].get('passed') != fresh_syntax.passed
            or stored[1].get('verdict') != fresh_validator.report.get('verdict')
            or any(stored[2].get(k) != fresh.get(k) for k in (
                'verdict', 'false_paths', 'multicycle_paths', 'known_async_pairs', 'findings'))):
        raise MetricRefusal('D20_PREFLIGHT_RESULT_CHANGED', 'actual pure Python checker readback differs')
    fields = ('mode', 'corner', 'check') if context['features']['technology_specific'] else ('mode', 'check')
    population, body = _approved_authority(project,
        'requirements/base_10/exception_justification.json#/required_items', fields + ('command', 'justification'))
    declared = json.loads((project / population['source']['path']).read_text())
    if declared.get('exception_justification') != {k: v for k, v in body.items() if k not in ('schema', 'approval', 'producer_binding')}:
        raise MetricRefusal('D20_REQUIRED_POPULATION_UNBOUND', 'existing D19 exception authority differs')
    required = {' '.join(item['command'].split()) for item in population['required_items']}
    count = len(set(commands) ^ required) + len(fresh.get('findings', []))
    known = {frozenset(pair) for pair in fresh['known_async_pairs']}
    count += sum(frozenset(re.findall(r'\[get_clocks\s+\{?(\w+)\}?\]', command)) not in known
                 for command in commands if command.startswith('set_false_path '))
    if not fresh_syntax.passed or fresh_validator.rc != 0:
        count += 1
    value = {'exception_commands': commands, 'known_async_pairs': fresh['known_async_pairs'], 'inputs': inputs}
    consumed = dict(inputs)
    for ref in ({'path': population['path'], 'sha256': population['sha256']}, population['source'],
                *([body['validated_absence']['source_reference']] if not population['required_items'] else [])):
        consumed[ref['path']] = ref['sha256']
    identity = {'producer': {'name': 'step_sdc_validation', 'source': source},
        'checker': {'methods': d20_model_sources(), 'reports': reports},
        'tool_execution': {'context_sha256': context['context_sha256'], 'steps': D20_STEPS},
        'consumed_inputs': consumed, 'requirements': {k: population[k] for k in ('path', 'sha256', 'source')},
        'configuration': {'scope': 'original caller SDC; no STA or mapped-netlist obligation'}}
    return count, value, identity


def accept_d20(project, context, component):
    """Complete only existing invalid-exception and CDC-reference obligations."""
    import flow109
    import flow109_admission as admission
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D20', 'status': 'NOT_MEASURED',
              'qualification': 'NOT_MEASURED', 'delivery_blocked': True, 'obligations': []}
    try:
        context = flow109.validate_execution_context(context)
        specs = {'base_11.invalid_timing_exceptions': {'operator': 'eq', 'value': 0, 'unit': 'count'},
                 'base_11.cdc_exception_reconciliation': {'operator': 'matches_adopted_reference',
                                                       'reference_ref': D20_REFERENCE}}
        obligations = context['resolved_row']['obligations']
        if (context['resolved_row']['id'] != 'D20' or {o['id'] for o in obligations} != set(specs)
                or any(any(o['expectation'].get(k) != v for k, v in specs[o['id']].items()) for o in obligations)):
            raise MetricRefusal('D20_OBLIGATIONS_UNREGISTERED', 'only the two existing operators')
        count, value, identity = _d20_observe(project, context, component)
        status, detail = evaluate_operator('eq', {'status': 'MEASURED', 'value': count,
            'unit': 'count', 'identity': identity}, {'status': 'APPROVED', 'value': 0, 'unit': 'count'})
        result['obligations'].append({'id': 'base_11.invalid_timing_exceptions', 'status': status,
                                      'value': count, 'detail': detail})
        if status == 'FAIL':
            result.update(status='FAIL', reason='D20_INVALID_TIMING_EXCEPTIONS')
            return result
        adopted, body = _approved_document(project, D20_REFERENCE, authority='requirements_owner',
                                          schema='vibeic.flow109.adopted-reference.v1')
        declared = json.loads((project / adopted['source']['path']).read_text())
        if declared.get('cdc_exception_reconciliation') != {k: v for k, v in body.items() if k not in ('schema', 'approval')}:
            raise MetricRefusal('D20_REFERENCE_SOURCE_UNBOUND', D20_REFERENCE)
        status, detail = evaluate_operator('matches_adopted_reference',
            {'status': 'MEASURED', 'value': value, 'identity': identity},
            {**adopted, 'reference': body.get('reference'), 'reference_identity': body.get('reference_identity')})
        result['obligations'].append({'id': 'base_11.cdc_exception_reconciliation', 'status': status,
                                     'value': value, 'authority': adopted, 'detail': detail})
        if status == 'FAIL':
            result.update(status='FAIL', reason='D20_CDC_REFERENCE_MISMATCH')
            return result
        result['accepted_dependencies'] = {step: flow109._accepted_row(project,
            Path('reports/flow109/default_rows') / (step + '.json'), step)[1]
            for step in context['resolved_row']['acceptance_deps']}
        qualified = admission.require_admission(project, context)
        uses = context['runtime_tool_uses']
        expected = {'purpose': 'D20.default.constraint_validation', 'native_steps': D20_STEPS,
                    'model_sources': d20_model_sources()}
        if len(uses) != 1 or json.loads((project / uses[0]['config']['path']).read_text()) != expected:
            raise MetricRefusal('D20_MODEL_QUALIFICATION_STALE', 'only current Python method/readset')
        refs = {**identity['consumed_inputs'], **component['d20_evidence']['reports'],
                adopted['path']: adopted['sha256'], adopted['source']['path']: adopted['source']['sha256'],
                **{ref['path']: ref['sha256'] for ref in result['accepted_dependencies'].values()}}
        for relative, digest in refs.items():
            _d19_ref(project, {'path': relative, 'sha256': digest}, 'completion readback')
        if (d20_model_sources() != component['d20_evidence']['model_sources']
                or d20_input_files(project, project / component['sdc_authority']['source']['path']) != value['inputs']):
            raise MetricRefusal('D20_INPUT_OR_METHOD_STALE', 'changed during completion')
        result.update(status='PASS', qualification=qualified['status'], delivery_blocked=False,
                      reason='D20_CURRENT_METRICS_DEPENDENCIES_AND_METHOD_PASS')
    except (MetricRefusal, ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D20_EVIDENCE_UNPROVEN'), detail=str(exc))
    return result


D24_BINDINGS = {
    'base_15.scan_preservation_errors': {'operator': 'eq', 'value': 0, 'unit': 'count'},
    'base_15.adopted_post_dft_netlist': {'operator': 'matches_adopted_reference',
        'reference_ref': 'adopted/base_15/adopted_post_dft_netlist.json',
        'identity': 'artifact_id_and_sha256_from_native_scan_report'},
}


def d24_native_module() -> dict:
    import inspect
    import importlib.metadata
    from librelane.steps import Step
    step = Step.factory.get('Yosys.Resynthesis')
    if step is None:
        raise MetricRefusal('D24_NATIVE_STEP_UNAVAILABLE', 'Yosys.Resynthesis')
    path = Path(inspect.getfile(step)).resolve()
    return {'path': str(path), 'sha256': _sha(path.read_bytes()),
            'version': importlib.metadata.version('librelane'), 'step': step.id}


def d24_model_sources() -> dict:
    import ast
    import design_one_shot_runner as owner
    import vibe_ic_one_shot_runner as public
    import dft_post_optimization_scan_survival_check as cells
    import flow109
    sources = {}
    for module, names in ((Path(__file__), ('accept_d24', '_d24_native_observe', '_d24_adoption',
            '_d24_qualification', 'd24_model_sources', 'd24_native_module')),
            (Path(owner.__file__), ('_d24_resynthesis',)),
            (Path(public.__file__), ('_d24_post_dft_component', '_complete_step12_post_dft', '_finish_selected_native_owner')),
            (Path(flow109.__file__), ('_selected_step_result', 'd23_scan_replacement_binding', '_d23_original_launch')),
            (Path(cells.__file__), ('reconcile_scan_cell_list',))):
        text = module.read_text()
        nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
        for name in names:
            sources[module.name + ':' + name] = _sha(ast.get_source_segment(text, nodes[name]).encode())
    return sources


def _d24_adoption(project: Path) -> tuple:
    authority, body = _approved_document(project, D24_BINDINGS['base_15.adopted_post_dft_netlist']['reference_ref'],
        authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')
    reference = body.get('reference')
    if (not isinstance(reference, dict) or set(reference) != {'artifact_id', 'path', 'sha256'}
            or reference['artifact_id'] != 'D24_POST_SCAN_NETLIST'
            or reference['path'] != 'phase2/stage2/synth/post_dft_netlist.v'):
        raise MetricRefusal('D24_INDEPENDENT_ADOPTION_UNBOUND', 'post-DFT artifact identity')
    source = authority['source']
    if not source['path'].startswith('input/'):
        raise MetricRefusal('D24_INDEPENDENT_ADOPTION_UNBOUND', 'independent host input required')
    document = json.loads((project / source['path']).read_bytes())
    if (document.get('reference') != reference
            or document.get('native_component') != body.get('native_component')):
        raise MetricRefusal('D24_INDEPENDENT_ADOPTION_DIFFERS', source['path'])
    if (project / reference['path']).exists():
        _d19_ref(project, {k: reference[k] for k in ('path', 'sha256')}, 'adopted D24 output')
    return {**authority, 'reference': reference}, reference


def _d24_native_observe(project: Path, context: Mapping, component: Mapping) -> dict:
    import flow109
    import librelane_contract as contract
    import dft_post_optimization_scan_survival_check as cells
    import design_one_shot_runner as owner
    import shutil
    intent = flow109.dft_source_intent(project, context)
    upstream = flow109.d23_scan_replacement_binding(project, context, intent)
    bound = flow109._current_project_ref(project, component.get('post_dft_component'), 'D24_NATIVE_COMPONENT_UNBOUND')
    path = project / bound['path']
    attempt = path.parent
    if (attempt.parent != project / 'reports/flow109/attempts'
            or not attempt.name.startswith('window-') or attempt.is_symlink()):
        raise MetricRefusal('D24_NATIVE_COMPONENT_FOREIGN', str(path))
    doc = json.loads(path.read_bytes())
    if (doc.get('schema') != 'vibeic.flow109.d24-component.v1' or doc.get('producer') != 'D24'
            or doc.get('operation') != 'Yosys.Resynthesis' or doc.get('returncode') != 0
            or doc.get('source') != upstream['replaced'] or doc.get('scan_cell_list') != upstream['scan_cell_list']
            or doc.get('producer_source_sha256') != _sha(Path(owner.__file__).read_bytes())):
        raise MetricRefusal('D24_NATIVE_COMPONENT_STALE', str(path))
    current = contract.local_image_attestation()
    original = doc.get('launch')
    if not isinstance(original, dict) or any(original.get(k) != current.get(k) for k in ('image', 'image_id')):
        raise MetricRefusal('D24_ORIGINAL_LAUNCH_UNPROVEN', 'same immutable image required')
    if original.get('cid') == current.get('cid'):
        if any(original.get(k) != current.get(k) for k in ('attestation_path', 'attestation_sha256')):
            raise MetricRefusal('D24_ORIGINAL_LAUNCH_UNPROVEN', 'current host receipt differs')
    else:
        adoption, _ = _d24_adoption(project)
        owner_input = json.loads((project / adoption['source']['path']).read_bytes())
        if owner_input.get('native_component') != bound or owner_input.get('launch') != original:
            raise MetricRefusal('D24_ORIGINAL_LAUNCH_UNPROVEN', 'retained launch lacks independent source adoption')
    # Validate the actual original host receipt, including reuse in another CID.
    launch_path = Path(str(original.get('attestation_path', '')))
    raw = launch_path.read_bytes()
    if _sha(raw) != original.get('attestation_sha256'):
        raise MetricRefusal('D24_ORIGINAL_LAUNCH_UNPROVEN', str(launch_path))
    host = json.loads(raw)
    inspected = host['container_inspect']
    if (host['cid'] != original['cid'] or inspected['Id'] != original['cid']
            or inspected['Image'] != original['image_id'] or host['image'] != original['image']
            or not inspected['Config']['Hostname'].startswith(original['cid'][:12])
            or inspected['State']['Running'] is not True
            or inspected['State'].get('Paused') or inspected['State'].get('Dead')):
        raise MetricRefusal('D24_ORIGINAL_LAUNCH_UNPROVEN', 'original CID/image/launch differs')
    files = {bound['path']: bound['sha256']}
    for name in ('config', 'state_in', 'state', 'netlist', 'log', 'config_input'):
        ref = flow109._current_project_ref(project, doc.get(name), 'D24_NATIVE_OUTPUT_STALE')
        if name != 'config_input' and (project / ref['path']).parent != attempt / 'resynthesis':
            raise MetricRefusal('D24_NATIVE_OUTPUT_FOREIGN', name)
        files[ref['path']] = ref['sha256']
    cfg = json.loads((project / doc['config']['path']).read_bytes())
    state_in = json.loads((project / doc['state_in']['path']).read_bytes())
    state = json.loads((project / doc['state']['path']).read_bytes())
    actual = (project / doc['netlist']['path']).resolve()
    if cfg.get('SYNTH_ELABORATE_ONLY') is not False:
        raise MetricRefusal('D24_NATIVE_ENGINE_UNSUPPORTED', 'resynthesis mapping required')
    if (cfg.get('meta', {}).get('step') != 'Yosys.Resynthesis' or cfg.get('DESIGN_NAME') != upstream['top']
            or state_in.get('nl') != str((project / upstream['replaced']['path']).resolve())
            or state.get('nl') != str(actual)):
        raise MetricRefusal('D24_STATE_INPUT_OUTPUT_MISMATCH', 'actual normal SDK State')
    d23_doc = json.loads((project / upstream['scan_cell_list']['path']).read_bytes())
    if (not doc.get('consumed_config_files')
            or contract.config_file_hashes(cfg, []) != doc['consumed_config_files']):
        raise MetricRefusal('D24_NATIVE_CONFIG_INPUTS_STALE', 'resolved native input files changed')
    libraries = cfg.get('CELL_LIBS')
    libs = [p for values in libraries.values() for p in values] if isinstance(libraries, dict) else []
    if not libs or any(d23_doc['pdk_sha256'].get(str(Path(p).resolve())) != _sha(Path(p).read_bytes()) for p in libs):
        raise MetricRefusal('D24_ADOPTED_LIBRARY_MISMATCH', 'same D23 Liberty required')
    module = doc.get('native_module', {})
    if module != d24_native_module():
        raise MetricRefusal('D24_NATIVE_MODULE_STALE', 'actual installed SDK')
    tool = shutil.which('yosys')
    if not tool or _sha(Path(tool).read_bytes()) != doc.get('yosys_sha256'):
        raise MetricRefusal('D24_NATIVE_TOOL_STALE', 'actual parser')
    check = cells.reconcile_scan_cell_list((project / upstream['mapped']['path']).read_text(),
        (project / upstream['replaced']['path']).read_text(), actual.read_text(), upstream['cells'], top=upstream['top'])
    if check.get('verdict') not in ('PASS', 'FAIL'):
        raise MetricRefusal('D24_SCAN_CENSUS_UNMEASURED', str(check))
    return {'upstream': upstream, 'component': bound, 'document': doc, 'files': files,
            'scan': check, 'launch': original, 'native_module': module}


def _d24_qualification(project: Path, context: Mapping, native: Mapping) -> dict:
    import flow109_admission as admission
    accepted = admission.require_admission(project, context)
    for use in context['runtime_tool_uses']:
        expected = {'purpose': 'D24.default.post_dft_resynthesis',
            'model_sources': d24_model_sources(), 'native_module': native['native_module']}
        if (use['semantics']['purpose'] != 'D24.default'
                or json.loads((project / use['config']['path']).read_bytes()) != expected):
            raise MetricRefusal('D24_MODEL_QUALIFICATION_STALE', use['use_id'])
    return accepted


def accept_d24(project: Path, context: Mapping, component: Mapping) -> dict:
    """Logical preservation/adoption only; not chain length, connectivity or LEC."""
    import flow109
    import flow109_admission as admission
    import librelane_contract as contract
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D24', 'status': 'NOT_MEASURED',
        'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
        'delivery_blocked': True, 'obligations': []}
    try:
        current = flow109.validate_execution_context(context)
        declared = current['resolved_row']['obligations']
        if (current['resolved_row']['id'] != 'D24'
                or {o['id'] for o in declared} != set(D24_BINDINGS)
                or len(declared) != len(D24_BINDINGS)):
            raise MetricRefusal('D24_OBLIGATIONS_UNREGISTERED', 'existing two scan contracts only')
        native = _d24_native_observe(project, context, component)
        scan = native['scan']
        errors = len(scan.get('missing', [])) + len(scan.get('extra', [])) if scan['verdict'] == 'FAIL' else 0
        if scan['verdict'] == 'FAIL' and not errors:
            result['obligations'].append({'id': 'base_15.scan_preservation_errors', 'status': 'FAIL',
                'measurement': {'native_scan_observation': scan}, 'reason': 'D24_SCAN_CONTRADICTION'})
            raise MetricRefusal('D24_SCAN_CONTRADICTION', str(scan))
        result['native_observation'] = native
        identity = {'producer': {'source_sha256': native['document']['producer_source_sha256']},
            'checker': {'sources': d24_model_sources()},
            'tool_execution': {'component': native['component'], 'launch': native['launch'],
                               'operation': 'Yosys.Resynthesis'},
            'consumed_inputs': native['files'],
            'requirements': {'registry_sha256': current['registry_sha256'],
                             'obligations': [o['id'] for o in declared]},
            'configuration': {'context_sha256': current['context_sha256'],
                              'native_config': native['document']['config']}}
        for obligation in context['resolved_row']['obligations']:
            oid = obligation['id']; spec = D24_BINDINGS.get(oid)
            if spec is None or any(obligation['expectation'].get(k) != v for k,v in spec.items()):
                raise MetricRefusal('D24_METRIC_CONTRACT_UNSUPPORTED', oid)
            if oid.endswith('scan_preservation_errors'):
                authority = {'status': 'APPROVED', 'value': spec['value'], 'unit': spec['unit'],
                             'source': obligation['expectation']['source']}
                measured = {'status': 'MEASURED', 'identity': identity, 'value': errors,
                            'unit': 'count', 'native_scan_observation': scan}
                status, detail = evaluate_operator(spec['operator'], measured, authority)
                result['obligations'].append({'id': oid, 'status': status,
                    'measurement': measured, 'authority': authority, 'detail': detail})
            else:
                authority, reference = _d24_adoption(project)
                owner_document = json.loads((project / authority['source']['path']).read_bytes())
                if owner_document.get('native_component') not in (None, native['component']):
                    raise MetricRefusal('D24_INDEPENDENT_COMPONENT_DIFFERS', 'owner-adopted native component differs')
                actual = {'artifact_id': 'D24_POST_SCAN_NETLIST', 'path': reference['path'],
                          'sha256': native['document']['netlist']['sha256']}
                authority['reference_identity'] = {**identity, 'requirements': authority.copy()}
                measured = {'status': 'MEASURED', 'identity': identity, 'value': actual}
                status, detail = evaluate_operator(spec['operator'], measured, authority)
                result['obligations'].append({'id': oid, 'status': status,
                    'authority': authority, 'measurement': measured, 'detail': detail})
                result['adopted_netlist'] = actual
        failed = any(item['status'] == 'FAIL' for item in result['obligations'])
        result['status'] = result['metric_status'] = 'FAIL' if failed else 'PASS'
        if not failed:
            result['metric_status'] = 'PASS';result['status'] = 'NOT_MEASURED'
            result['admission'] = _d24_qualification(project, context, native)
            result['qualification'] = result['admission']['status']
            if result['qualification'] == 'PASS':result.update(status='PASS', delivery_blocked=False)
        if _d24_native_observe(project, context, component) != native:
            raise MetricRefusal('D24_INPUT_CHANGED_DURING_READ', 'native observation changed')
        if result.get('adopted_netlist'):
            _, current = _d24_adoption(project)
            if current != result['adopted_netlist']:
                raise MetricRefusal('D24_INPUT_CHANGED_DURING_READ', 'adoption changed')
        result['reason'] = 'D24_CURRENT_LOGICAL_SCAN_AND_ADOPTION_' + result['status']
    except (flow109.Flow109Error, admission.AdmissionRefusal, contract.Refusal, MetricRefusal,
            OSError, ValueError, KeyError, TypeError, AttributeError, ImportError) as exc:
        # Fail closed while retaining independently observed failures.
        failed = any(x['status'] == 'FAIL' for x in result['obligations'])
        result.update(status='FAIL' if failed else 'NOT_MEASURED', metric_status='FAIL' if failed else 'NOT_MEASURED',
            qualification='NOT_MEASURED', delivery_blocked=True,
            reason=getattr(exc, 'code', 'D24_EVIDENCE_NOT_MEASURED'), detail=str(exc))
    return result

def _d30_file(project: Path, record: Any, label: str) -> Path:
    if (not isinstance(record, Mapping) or set(record) != {"path", "sha256"}
            or not isinstance(record.get("path"), str)
            or not _HEX.fullmatch(str(record.get("sha256", "")))):
        raise MetricRefusal("D30_SOURCE_UNBOUND", label)
    path = (project / record["path"]).resolve()
    if (not path.is_relative_to(project) or not path.is_file()
            or not path.stat().st_size or _sha(path.read_bytes()) != record["sha256"]):
        raise MetricRefusal("D30_SOURCE_STALE_OR_FOREIGN", label)
    return path


def d30_consumed_timing(project: Path, admission: Mapping[str, Any]) -> dict:
    """Read D26's sealed native readset, never infer reads from a template.

    Historical STAPrePNR receipts did not seal per-corner sta.log. Those
    receipts remain unmeasured: sealing a log here cannot establish what the
    native producer read. This is identity evidence, not new timing signoff.
    """
    import fnmatch
    import librelane_contract as native
    project = Path(project).resolve()
    try:
        inputs = {}

        def ref(path):
            path = Path(path).resolve()
            if not path.is_relative_to(project) or not path.is_file() or not path.stat().st_size:
                raise MetricRefusal("D30_SOURCE_STALE_OR_FOREIGN", str(path))
            name = path.relative_to(project).as_posix()
            inputs[name] = _sha(path.read_bytes())
            return {"path": name, "sha256": inputs[name]}

        timing = admission["pre_route_timing"]["timing_modes"]
        for record in (admission["pre_route_timing"]["D26_result"], timing["receipt"]):
            ref(_d30_file(project, record, "D26 current consumer"))
        if admission["requires_scan"]:
            arm = timing["post_scan_arms"]["functional"]
            folder = (project / arm["native"]["folder"]).resolve()
            corners = arm["slack_gate"]["corners"]
        else:
            gate_path = project / "phase3/librelane/prelayout/gates/step10_slack.json"
            ref(gate_path)
            gate = json.loads(gate_path.read_text())
            state_path = _d30_file(project, {"path": gate["source"],
                "sha256": gate["state_out_sha256"]}, "D26 functional state")
            folder, corners = state_path.parent, gate["corners"]
            if gate.get("verdict") != "PASS":
                raise MetricRefusal("D30_TIMING_SOURCE_UNQUALIFIED", "D26 functional gate")
        receipt_ref = ref(folder / "vibeic_receipt.json")
        receipt = native.validate_step_receipt(folder, "OpenROAD.STAPrePNR")
        fingerprint, hashes = receipt["input"], receipt["sha256"]
        records = {name: ref(folder / name) for name in
                   ("config.json", "state_in.json", "state_out.json", "pdk_root.json")}
        if any(hashes.get(name) != record["sha256"] for name, record in records.items()):
            raise MetricRefusal("D30_NATIVE_SOURCE_UNBOUND", "config/state/PDK producer hashes")
        config = json.loads((folder / "config.json").read_text())
        state = json.loads((folder / "state_in.json").read_text())
        after = json.loads((folder / "state_out.json").read_text())
        # LibreLane writes a resolved config copy in the output folder; its
        # bytes can differ from the launch config fingerprint. Both identities
        # are producer sealed, rather than assumed to be interchangeable.
        if (not _HEX.fullmatch(str(fingerprint.get("config", "")))
                or fingerprint.get("state") != records["state_in.json"]["sha256"]
                or config.get("meta", {}).get("step") != "OpenROAD.STAPrePNR"):
            raise MetricRefusal("D30_NATIVE_SOURCE_UNBOUND", "native input fingerprint")
        netlist = ref(Path(state["nl"]))
        point = admission["normalized_preroute_chain"]["points"]["D26"]["input"]
        if (netlist != point or state["nl"] != after.get("nl")
                or fingerprint["state_files"].get(state["nl"]) != netlist["sha256"]):
            raise MetricRefusal("D30_NATIVE_SOURCE_UNBOUND", "D26 actual netlist")
        if not isinstance(corners, Mapping) or not corners or config.get("MACROS"):
            raise MetricRefusal("D30_TIMING_SOURCE_UNQUALIFIED", "corners/macro timing closure")
        # Resolve only the native producer's sealed mounts, not arbitrary
        # host fallbacks for an unreadable guest library path.
        pdk = json.loads((folder / "pdk_root.json").read_text())
        mounts = [(Path(host).resolve(), Path(guest))
                  for host, guest in pdk.get("mounts_under_it", [])]
        mounts.sort(key=lambda pair: len(str(pair[1])), reverse=True)

        def consumed(name):
            path = Path(name)
            if not path.is_absolute():
                raise MetricRefusal("D30_NATIVE_INPUT_UNBOUND", str(name))
            source = path
            if not path.resolve().is_relative_to(project):
                match = next(((host, guest) for host, guest in mounts
                              if path.is_relative_to(guest)), None)
                if match is None:
                    raise MetricRefusal("D30_NATIVE_INPUT_UNBOUND", str(name))
                source = match[0] / path.relative_to(match[1])
            recorded = fingerprint.get("config_files", {}).get(name)
            if (not _HEX.fullmatch(str(recorded or "")) or not source.is_file()
                    or _sha(source.read_bytes()) != recorded):
                raise MetricRefusal("D30_NATIVE_INPUT_STALE_OR_MISSING", str(name))
            inputs[str(source.resolve())] = recorded
            return {"path": name, "sha256": recorded}

        logs = {path.relative_to(folder).as_posix() for path in folder.glob("*/sta.log")}
        expected_logs = {f"{corner}/sta.log" for corner in corners}
        if logs != expected_logs or any(name not in hashes for name in expected_logs):
            raise MetricRefusal("D30_NATIVE_READ_LOG_UNBOUND", "D26 per-corner producer logs")
        values = []
        for corner in sorted(corners):
            log_ref = ref(folder / corner / "sta.log")
            if hashes.get(f"{corner}/sta.log") != log_ref["sha256"]:
                raise MetricRefusal("D30_NATIVE_READ_LOG_UNBOUND", corner)
            text = (folder / corner / "sta.log").read_text()
            sdc_reads = re.findall(r"^Reading design constraints file at '([^']+)'", text, re.M)
            netlist_reads = re.findall(r"^Reading top-level netlist at '([^']+)'", text, re.M)
            if (sdc_reads != [config.get("PNR_SDC_FILE")]
                    or netlist_reads != [state["nl"]]):
                raise MetricRefusal("D30_NATIVE_READSET_UNPROVEN", corner + ": SDC/netlist")
            libraries = [path for name, path in native._STA_CELL_LIBRARY_RE.findall(text)
                         if name == corner]
            declared = set()
            for field in ("CELL_LIBS", "PAD_LIBS", "EXTRA_LIBS"):
                groups = ((config.get('CELL_LIBS') or config.get('LIB'))
                          if field == 'CELL_LIBS' else config.get(field)) or {}
                groups = groups.items() if isinstance(groups, Mapping) else [("*", groups)]
                for pattern, paths in groups:
                    if fnmatch.fnmatch(corner, pattern):
                        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
                            raise MetricRefusal("D30_NATIVE_READSET_UNPROVEN", field)
                        declared.update(paths)
            if not declared or set(libraries) != declared or len(libraries) != len(set(libraries)):
                raise MetricRefusal("D30_NATIVE_READSET_UNPROVEN", corner + ": libraries")
            values.append({"mode": "functional", "corner": corner,
                           "sdc": consumed(sdc_reads[0]),
                           "libraries": [consumed(path) for path in sorted(libraries)]})
        if any(not Path(project / name).is_file() or
               _sha(Path(project / name).read_bytes()) != sha for name, sha in inputs.items()):
            raise MetricRefusal("D30_SOURCE_CHANGED_DURING_READ", "native readset")
        return {"status": "MEASURED", "value": values, "consumed_inputs": inputs,
                "native_receipt": receipt_ref, "native_records": records,
                "scope": "functional handoff identity; no shift/capture timing credit"}
    except (native.Refusal, ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return {"status": "NOT_MEASURED", "reason": getattr(exc, "code", "D30_NATIVE_SOURCE_UNBOUND"),
                "detail": str(exc)}


def _d25_inputs(project: Path) -> dict:
    """BLOCKING: admit only an independently approved, exact reset-boundary subject."""
    import _specrtl_common as sources
    project = Path(project).resolve()
    consumed = {}

    def bound(record, *, model=False):
        if (not isinstance(record, Mapping) or not isinstance(record.get('path'), str)
                or not _HEX.fullmatch(str(record.get('sha256', '')))):
            raise MetricRefusal('D25_NATIVE_INPUT_UNBOUND', str(record))
        path = Path(record['path']) if model else _safe_project_file(project, record['path'])
        if path.is_symlink() or not path.is_file() or _sha(path.read_bytes()) != record['sha256']:
            raise MetricRefusal('D25_NATIVE_INPUT_STALE', str(path))
        consumed[str(path.resolve())] = record['sha256']
        return path.resolve()

    manifest_path = project / 'input/flow109/D25.json'
    manifest = json.loads(manifest_path.read_text())
    consumed[str(manifest_path)] = _sha(manifest_path.read_bytes())
    required, required_doc = _approved_document(project,
        'requirements/base_16/required_lec_partitions.json', authority='requirements_owner', schema=AUTHORITY_SCHEMA)
    adopted, adopted_doc = _approved_document(project,
        'adopted/base_16/mode_assumptions.json', authority='requirements_owner',
        schema='vibeic.flow109.adopted-reference.v1')
    if required['source'] != adopted['source']:
        raise MetricRefusal('D25_AUTHORITY_MISMATCH', 'requirements and adopted mode source differ')
    source_path = bound(required['source'])
    source = json.loads(source_path.read_text())
    for authority in (required, adopted):
        bound({'path': authority['path'], 'sha256': authority['sha256']})
    bound(source['source_reference'])
    items, mode, qualification = (source.get(k) for k in
                                 ('required_items', 'mode_assumptions', 'native_qualification'))
    if (required_doc.get('required_items') != items or adopted_doc.get('mode_assumptions') != mode
            or not isinstance(items, list) or not items or not isinstance(mode, Mapping)
            or mode.get('purpose') != 'functional_after_observed_reset'
            or manifest.get('purpose') != mode['purpose']
            or manifest.get('top') != mode.get('top')
            or not _SAFE.fullmatch(str(mode.get('top', '')))
            or mode.get('clock', {}).get('edge') != 'rising'
            or mode.get('before_reset') != 'NOT_MEASURED'
            or mode.get('DUT_initial_state') != 'unconstrained'
            or mode.get('power_up_reset_schedule') != 'not_assumed'
            or mode.get('physical_clock_frequency') != 'not_assumed'
            or any(mode.get(k) is not False for k in ('power_pins', 'four_state_qualification',
                    'timing_notifier_qualification', 'scan_qualification', 'SPM_qualification'))
            or not isinstance(qualification, Mapping)
            or qualification.get('native_entry') != 'librelane.steps.yosys.EQY.start'
            or qualification.get('allow_native_nondefault_preprocessor_for_named_scope') is not True
            or qualification.get('default_or_global_force_enabled') is not False):
        raise MetricRefusal('D25_PURPOSE_UNSUPPORTED', 'exact approved conditional purpose required')
    for role in ('clock', 'reset'):
        if not _SAFE.fullmatch(str(mode.get(role, {}).get('port', ''))):
            raise MetricRefusal('D25_MODE_INVALID', role)
    if mode['reset'].get('active_level') not in (0, 1):
        raise MetricRefusal('D25_MODE_INVALID', 'reset polarity')
    gold = [bound(r) for r in manifest['rtl']]
    declared = set(sources.rtl_source_files(project))
    declared.update(sources.rtl_source_files(project, exts=('*.vh', '*.svh')))
    if set(gold) != {p.resolve() for p in declared} or len(gold) != 1:
        raise MetricRefusal('D25_NATIVE_READSET_INCOMPLETE', 'qualified original RTL population differs')
    gate = bound(manifest['gate_netlist'])
    if (manifest['rtl'][0]['sha256'] != qualification.get('original_rtl_sha256')
            or manifest['gate_netlist']['sha256'] not in qualification.get('allowed_gate_sha256', [])):
        raise MetricRefusal('D25_SUBJECT_NOT_QUALIFIED', 'foreign actual original subject')
    if (manifest['liberty'] != {k: qualification['liberty'][k] for k in ('path', 'sha256')}
            or manifest['models'] != qualification.get('models')):
        raise MetricRefusal('D25_MODEL_NOT_QUALIFIED', 'actual Liberty/model identity differs')
    liberty = bound(manifest['liberty'], model=True)
    models = [bound(r, model=True) for r in manifest['models']]
    import librelane_contract as contract
    try:
        current_launch = contract.local_image_attestation()
    except contract.Refusal as exc:
        raise MetricRefusal('D25_NATIVE_LAUNCH_UNBOUND', str(exc)) from exc
    if (qualification.get('qualified_image_id') != current_launch['image_id']
            or qualification.get('qualified_image_reference') != current_launch['image']
            or not isinstance(qualification.get('actual_tool_readset'), Mapping)
            or not qualification['actual_tool_readset']
            or qualification.get('passing_gate_sha256') not in qualification['allowed_gate_sha256']
            or qualification.get('rejection_control_gate_sha256') not in qualification['allowed_gate_sha256']
            or qualification.get('passing_gate_sha256') == qualification.get('rejection_control_gate_sha256')):
        raise MetricRefusal('D25_TOOLCHAIN_UNQUALIFIED', 'exact measured native image/tool/control-role authority absent')
    for name, sha in qualification['actual_tool_readset'].items():
        bound({'path': name, 'sha256': sha}, model=True)

    return {'manifest': manifest, 'manifest_path': manifest_path, 'mode': dict(mode),
            'qualification': dict(qualification), 'required_items': items,
            'required': required, 'adopted': adopted, 'gold': gold, 'gate': gate,
            'liberty': liberty, 'models': models, 'consumed': consumed, 'bound': bound}


def _d25_accept_eqy(project: Path, context: Mapping, result: dict, specs: Mapping) -> dict:
    """Reopen a genuine source-owned native execution, then grade all three operators."""
    import librelane_eqy as native
    prepared = _d25_inputs(project)
    execution = native.d25_reopen(project, prepared, context)
    proof = execution['proof']
    component = ('PASS' if proof['verdict'] == 'PASS' else 'FAIL'
                 if proof['verdict'] == 'FAIL' else 'NOT_MEASURED')
    if (component == 'PASS' and prepared['manifest']['gate_netlist']['sha256']
            != prepared['qualification']['passing_gate_sha256']):
        raise MetricRefusal('D25_REJECTION_CONTROL_CANNOT_PASS', 'CEX control is never a PASS subject')
    identity = {'producer': {'name': 'librelane_eqy.run_eqy', 'sources': execution['sources']},
                'checker': {'name': 'accept_d25', 'sources': execution['reader_sources']},
                'tool_execution': {'record': execution['execution_record'], 'launch': execution['launch']},
                'consumed_inputs': execution['consumed_inputs'],
                'requirements': {'required': prepared['required']['sha256'], 'adopted': prepared['adopted']['sha256']},
                'configuration': {'mode': prepared['mode'], 'subject': execution['subject']}}
    actual = [{'block': prepared['mode']['top'], 'name': name,
               'mode': prepared['mode']['purpose']} for name in proof['partitions'] or {}]
    values = {'covers_all': actual, 'eq': len(proof['unproven_points']),
              'matches_adopted_reference': execution['mode']}
    obligations = []
    for obligation in context['resolved_row']['obligations']:
        oid = obligation['id']
        spec = specs[oid]
        operator = spec['operator']
        authority = ({**prepared['required'], 'required_items': prepared['required_items']}
            if operator == 'covers_all' else {'status': 'APPROVED', 'value': 0, 'unit': 'count'}
            if operator == 'eq' else {**prepared['adopted'], 'reference': prepared['mode'],
                                     'reference_identity': identity})
        measured = {'status': 'FAIL' if component == 'FAIL' else 'MEASURED'
                    if component == 'PASS' else 'NOT_MEASURED',
                    'value': values[operator], 'identity': identity,
                    'reason': 'D25_NATIVE_CEX' if component == 'FAIL' else proof['explanation']}
        if operator == 'eq':
            measured['unit'] = 'count'
        status, reason = evaluate_operator(operator, measured, authority)
        obligations.append({'id': oid, 'operator': operator, 'status': status, 'reason': reason,
                            'observed_value': values[operator]})
    statuses = [o['status'] for o in obligations]
    status = ('FAIL' if component == 'FAIL' or 'FAIL' in statuses else 'PASS'
              if len(statuses) == 3 and all(s == 'PASS' for s in statuses) else 'NOT_MEASURED')
    result.update(status=status, component_status=component,
                  qualification='PASS', qualification_scope=prepared['mode']['purpose'],
                  delivery_blocked=status != 'PASS', obligations=obligations,
                  native_tool='Yosys.EQY', native_execution=execution,
                  native_assumptions=prepared['mode'],
                  reason='D25_NATIVE_CEX' if status == 'FAIL' else
                  'D25_NAMED_NATIVE_METRICS_PASS' if status == 'PASS' else 'D25_NATIVE_INCOMPLETE')
    return result


def accept_d25(project: Path, context: Mapping[str, Any]) -> dict:
    """Consume existing LEC evidence without relabeling equiv_* as EQY.

    The retained native checker may reject an implementation. Its successful
    point count supplies neither an approved partition census nor adopted modes.
    """
    import flow109
    import lec_run
    import lec_equivalence_check as checker
    import _specrtl_common as sources
    from dataclasses import asdict
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D25', 'status': 'NOT_MEASURED',
              'component_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    specs = {
        'base_16.required_lec_partitions': {'operator': 'covers_all',
            'required_set_ref': 'requirements/base_16/required_lec_partitions.json#/required_items'},
        'base_16.unproved_equivalence': {'operator': 'eq', 'value': 0, 'unit': 'count'},
        'base_16.mode_assumptions': {'operator': 'matches_adopted_reference',
            'reference_ref': 'adopted/base_16/mode_assumptions.json'}}
    try:
        current = flow109.validate_execution_context(context)
        if current['resolved_row']['id'] != 'D25':
            raise MetricRefusal('D25_CONTEXT_INVALID', 'not D25')
        obligations = current['resolved_row']['obligations']
        if ({o['id'] for o in obligations} != set(specs)
                or any(any(o['expectation'].get(k) != v for k, v in specs[o['id']].items())
                       for o in obligations)):
            raise MetricRefusal('D25_OBLIGATIONS_UNREGISTERED', 'registered operators differ')
        if (project / 'input/flow109/D25.json').is_file():
            if not (project / 'reports/lec_eqy_execution.json').is_file():
                raise MetricRefusal('D25_NATIVE_EXECUTION_ABSENT', 'current canonical native binding missing')
            return _d25_accept_eqy(project, current, result, specs)
        if (all(current['features'].get(key) is False
                for key in ('requires_dft', 'requires_scan'))
                and (project / 'reports/lec_eqy.json').exists()):
            # Reopen the existing generic producer's actual inputs and output.
            # Named-purpose qualification still belongs to _d25_accept_eqy;
            # a generic EQY observation never supplies that approval itself.
            import librelane_contract as contract
            import librelane_eqy as native
            import synth_handoff_netlist_check as handoff
            from _rtl_include_hub import silicon_rtl_selection
            import tempfile
            flow109.dft_source_intent(project, current)
            flow109._accepted_row(project, Path('reports/flow109/default_rows/D22.json'), 'D22')
            adopted = handoff.bound_handoff(project)
            if adopted is None or adopted.get('verdict') != 'PASS':
                raise MetricRefusal('D25_NATIVE_SUBJECT_UNBOUND', 'current D22 handoff absent')
            folder = project / 'phase3/librelane/lec_eqy/01-yosys-eqy'
            if folder.is_symlink() or not (folder / 'vibeic_receipt.json').is_file():
                raise MetricRefusal('D25_NATIVE_EXECUTION_ABSENT', str(folder))
            try:
                receipt = contract.validate_step_receipt(folder, 'Yosys.EQY')
            except contract.Refusal as exc:
                raise MetricRefusal('D25_NATIVE_INPUT_STALE', str(exc)) from exc
            root = project / 'phase3/librelane/lec-eqy-config'
            cfg_path, state_path = root / 'eqy.resolved.json', root / 'state_in.json'
            cfg, state = json.loads(cfg_path.read_bytes()), json.loads(state_path.read_bytes())
            fp = receipt['input']
            mapped = Path(adopted['mapped'])
            rtl = list(silicon_rtl_selection(project / 'phase2/stage1/rtl'))
            manifest, _ = flow109._bound_project_json(
                project, Path('input/flow109/D22.json'), 'D25_NATIVE_SUBJECT_UNBOUND')
            if (cfg.get('DESIGN_NAME') != manifest.get('top') or cfg.get('PDK') != manifest.get('pdk')
                    or cfg.get('VERILOG_FILES') != [str(p.resolve()) for p in rtl]
                    or state.get('nl') != str(mapped)
                    or fp.get('state_files') != {str(mapped): contract.digest(mapped)}
                    or fp.get('config') != contract.digest(cfg_path)
                    or fp.get('state') != contract.digest(state_path)):
                raise MetricRefusal('D25_NATIVE_SUBJECT_UNBOUND', 'native EQY source/state differs')
            mounts = handoff._receipt_pdk_mounts(folder, receipt)
            if contract.config_file_hashes(cfg, mounts) != fp.get('config_files'):
                raise MetricRefusal('D25_NATIVE_INPUT_STALE', 'native EQY config files changed')
            synthesis = json.loads((Path(adopted['native']).parent / 'config.json').read_bytes())
            groups = synthesis.get('CELL_LIBS') or synthesis.get('LIB') or {}
            selected = {value for group in groups.values() for value in group}
            import fnmatch
            proof_groups = cfg.get('CELL_LIBS') or cfg.get('LIB') or {}
            proof_libraries = {value for pattern, group in proof_groups.items()
                if fnmatch.fnmatch(cfg.get('DEFAULT_CORNER', ''), pattern) for value in group}
            if len(selected) != 1 or len(proof_libraries) != 1:
                raise MetricRefusal('D25_MODEL_NOT_QUALIFIED', 'EQY and adopted synthesis libraries differ')
            selected_name, proof_name = next(iter(selected)), next(iter(proof_libraries))
            selected_binding = (adopted.get('consumed_config_files') or {}).get(selected_name)
            proof_path = Path(proof_name)
            for host, guest in sorted(mounts, key=lambda m: len(str(m[1])), reverse=True):
                if proof_path.is_relative_to(guest):
                    proof_path = Path(host) / proof_path.relative_to(guest)
                    break
            # The handoff verified the original canonical source and every
            # receipt digest before publishing these actual consumer paths.
            if (not isinstance(selected_binding, Mapping)
                    or Path(selected_binding['path']).resolve() != proof_path.resolve()
                    or selected_binding['sha256'] != contract.digest(proof_path)):
                raise MetricRefusal('D25_MODEL_NOT_QUALIFIED', 'EQY and adopted synthesis libraries differ')
            script = Path(cfg['EQY_SCRIPT'])
            if script.read_text() != native.eqy_script(
                    manifest['top'], rtl, mapped, next(iter(proof_libraries))):
                raise MetricRefusal('D25_NATIVE_CONFIGURATION_UNBOUND', 'EQY script differs')
            try:
                launch = contract.local_image_attestation()
            except contract.Refusal as exc:
                raise MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', str(exc)) from exc
            original = fp.get('local_image') or {}
            if any(launch.get(key) != original.get(key) for key in ('image', 'image_id')):
                raise MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'native EQY image differs')
            with tempfile.TemporaryDirectory() as temporary:
                observed = native.judge_eqy(folder, Path(temporary) / 'lec_eqy.json')
            component = observed['verdict'] if observed['verdict'] in ('PASS', 'FAIL') else 'NOT_MEASURED'
            result.update(component_status=component, native_tool='Yosys.EQY',
                native_consumer=observed,
                library_binding={'synthesis_recorded': selected_name, 'proof_recorded': proof_name,
                    'consumed_path': str(proof_path.resolve()), 'sha256': selected_binding['sha256']},
                reason='D25_NATIVE_TOOL_PURPOSE_UNQUALIFIED',
                qualification_detail='generic EQY inputs are bound; named mode/model authority is still required')
            return result
        consumed = {}

        def bound_file(record):
            name, digest = record['path'], str(record['sha256']).removeprefix('sha256:')
            path = Path(name)
            path = path if path.is_absolute() else _safe_project_file(project, name)
            if path.is_symlink() or not path.is_file() or _sha(path.read_bytes()) != digest:
                raise MetricRefusal('D25_NATIVE_INPUT_STALE', name)
            consumed[str(path)] = digest
            return path

        path = _safe_project_file(project, 'reports/lec.json')
        if not path.is_file():
            raise MetricRefusal('D25_NATIVE_EVIDENCE_ABSENT', str(path))
        raw = path.read_bytes()
        report = json.loads(raw)
        if (report.get('program') != 'lec_run'
                or report.get('tool') != 'yosys equiv_make+equiv_simple+equiv_induct'):
            raise MetricRefusal('D25_NATIVE_PRODUCER_PURPOSE_MISMATCH', 'unsupported actual producer/tool')
        identity, execution = report['proof_identity'], report['proof_execution']
        gold = identity['gold_rtl']
        declared = {p.resolve() for p in sources.rtl_source_files(project)}
        declared.update(p.resolve() for p in sources.rtl_source_files(project, exts=('*.vh', '*.svh')))
        if {bound_file(record).resolve() for record in gold} != declared:
            raise MetricRefusal('D25_NATIVE_READSET_INCOMPLETE', 'current RTL/header population differs')
        bound_file(identity['gate_netlist'])
        if identity.get('liberty', {}).get('state') != 'unused':
            bound_file(identity['liberty'])
        for record in identity['scan'].values():
            if record != {'state': 'absent'}:
                bound_file(record)
        recipe = identity['equivalence_script']['sha256']
        if (report.get('lec_resume', {}).get('checkpoint_key') != lec_run.lec_checkpoint_key(identity)
                or execution.get('canonical_recipe_sha256') != recipe
                or report.get('lec_resume', {}).get('base_script_sha256') != recipe
                or identity.get('gold_frontend') != report.get('gold_frontend')
                or identity.get('gold_defines') != report.get('gold_defines')):
            raise MetricRefusal('D25_NATIVE_ASSUMPTIONS_STALE', 'existing proof recipe/identity differs')
        legs = execution.get('evidence_legs')
        if not isinstance(legs, list) or not legs:
            raise MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'native evidence legs absent')
        for leg in legs:
            bound_file({'path': 'reports/' + leg['path'], 'sha256': leg['sha256']})
        judged = checker.audit(project)
        binding = judged.summary.get('subject_binding', {})
        if binding.get('state') != 'MATCH':
            raise MetricRefusal('D25_NATIVE_SUBJECT_UNBOUND', str(binding))
        for count in (judged.compared_points, judged.unproven_points, judged.non_equivalent_points):
            _finite_number(count, count=True)
        if judged.compared_points <= 0:
            raise MetricRefusal('D25_NATIVE_COMPARISON_EMPTY', 'no native compared points')
        if (_sha(path.read_bytes()) != _sha(raw)
                or any(_sha(Path(p).read_bytes()) != sha for p, sha in consumed.items())):
            raise MetricRefusal('D25_NATIVE_INPUT_STALE', 'changed during consumer read')
        component = ('PASS' if judged.passed else 'NOT_MEASURED'
                     if judged.not_measured or judged.inconclusive else 'FAIL')
        result.update(component_status=component,
            status='FAIL' if component == 'FAIL' else 'NOT_MEASURED', native_consumer=asdict(judged),
            native_tool=report['tool'], consumed_inputs=consumed,
            native_report={'path': 'reports/lec.json', 'sha256': _sha(raw)},
            native_assumptions={'scan': identity['scan'], 'gold_frontend': identity.get('gold_frontend'),
                                'gold_defines': identity.get('gold_defines')},
            qualification_reason='D25_NATIVE_TOOL_PURPOSE_UNQUALIFIED',
            qualification_detail={'required_native_steps': current['resolved_row']['profile']['native_steps'],
                'actual_native_tool': report['tool'],
                'source_owned_tool_uses': current['resolved_row']['tool_uses'],
                'proof_identity_complete': lec_run.proof_identity_complete(identity)})
        for obligation in obligations:
            oid, spec = obligation['id'], specs[obligation['id']]
            measured = {'status': 'NOT_MEASURED', 'reason': 'D25_NATIVE_TOOL_PURPOSE_UNQUALIFIED'}
            item = {'id': oid, 'operator': spec['operator'], 'status': 'NOT_MEASURED'}
            authority = {'status': 'NOT_MEASURED'}
            if spec['operator'] == 'eq':
                measured.update(value=judged.unproven_points, unit='count')
                authority = {'status': 'APPROVED', 'value': spec['value'], 'unit': spec['unit']}
                item['observed_value'] = judged.unproven_points
            else:
                ref = spec.get('required_set_ref', spec.get('reference_ref')).partition('#/')[0]
                try:
                    authority, body = _approved_document(project, ref, authority='requirements_owner',
                        schema=AUTHORITY_SCHEMA if spec['operator'] == 'covers_all'
                        else 'vibeic.flow109.adopted-reference.v1')
                    measured['reason'] = ('D25_PARTITION_CENSUS_UNBOUND' if spec['operator'] == 'covers_all'
                                          else 'D25_CONSUMED_MODE_ASSUMPTIONS_UNBOUND')
                except MetricRefusal as exc:
                    measured['reason'] = exc.code
                    item['detail'] = str(exc)
            item['status'], item['reason'] = evaluate_operator(spec['operator'], measured, authority)
            result['obligations'].append(item)
        # A real canonical consumer rejection remains blocking even while
        # unrelated authority/qualification obligations are not measured.
        result.update(status='FAIL' if component == 'FAIL' else 'NOT_MEASURED',
                      reason='D25_NATIVE_CONSUMER_FAILED' if component == 'FAIL'
                      else 'D25_METRIC_QUALIFICATION_AND_AUTHORITY_UNPROVEN')
    except (MetricRefusal, flow109.Flow109Error, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D25_NATIVE_BINDING_UNPROVEN'), detail=str(exc))
    return result


def accept_d26(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """BLOCKING: measure functional pre-layout metrics from sealed native reads.

    The owner separately checks the current timing-mode and mapped-SDC semantic
    receipts. This reader supplies their missing registry metrics; it never
    turns an absent report, corner, unit or source-owned bound into zero.
    """
    import fnmatch
    import librelane_contract as native
    import librelane_prelayout as sta
    from eda_report_audit import _STA_TIME_TO_NS

    project = Path(project).resolve()
    specs = {
        'base_11.unconstrained_required_paths': {'operator': 'eq', 'value': 0, 'unit': 'count'},
        'base_13.prelayout_timing_targets': {
            'operator': 'within_declared_bounds',
            'bounds_ref': 'requirements/base_13/prelayout_timing_targets.json#/limits',
            'unit_ref': 'requirements/base_13/prelayout_timing_targets.json#/units',
            'missing_bounds': 'BLOCKED', 'modes': 'functional_only'},
        'base_13.unconstrained_endpoints': {'operator': 'eq', 'value': 0, 'unit': 'count'},
    }
    result = {'schema': SCHEMA, 'row_id': 'D26', 'status': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    consumed = {}

    def local(value):
        path = Path(value)
        name = path.relative_to(project).as_posix() if path.is_absolute() else path.as_posix()
        path = _safe_project_file(project, name)
        if not path.is_file() or not path.stat().st_size:
            raise MetricRefusal('D26_NATIVE_INPUT_ABSENT', name)
        consumed[str(path)] = _sha(path.read_bytes())
        return path

    def bound(record):
        path = local(record['path'])
        if consumed[str(path)] != record['sha256']:
            raise MetricRefusal('D26_NATIVE_INPUT_STALE', str(path))
        return path

    try:
        row = context['resolved_row']
        obligations = row['obligations']
        if (row['id'] != 'D26' or len(obligations) != len(specs)
                or {o['id'] for o in obligations} != set(specs)
                or any(any(o['expectation'].get(k) != v for k, v in specs[o['id']].items())
                       for o in obligations)):
            raise MetricRefusal('D26_METRIC_CONTRACT_UNSUPPORTED', 'existing three contracts required')
        timing = json.loads(bound(component['timing_modes_receipt']).read_text())
        if (timing['schema'] != 'vibeic.flow109.d26-timing-modes.v1'
                or timing['step_id'] != 'D26' or timing['position'] != 38
                or timing['aggregate_status'] not in ('PASS', 'FAIL')):
            raise MetricRefusal('D26_TIMING_MODES_UNBOUND', 'current measured functional mode required')
        if timing['scan']['applicability'] == 'NOT_APPLICABLE':
            if timing['post_scan_arms']:
                raise MetricRefusal('D26_TIMING_MODES_UNBOUND', 'unexpected post-scan arm')
            gate = json.loads(local('phase3/librelane/prelayout/gates/step10_slack.json').read_text())
            state_path = bound({'path': gate['source'], 'sha256': gate['state_out_sha256']})
            folder = state_path.parent
        else:
            folder = local(Path(timing['post_scan_arms']['functional']['native']['folder'])
                           / 'state_out.json').parent
        receipt = native.validate_step_receipt(folder, 'OpenROAD.STAPrePNR')
        local(folder / 'vibeic_receipt.json')
        config, before, after = [json.loads(local(folder / name).read_text())
                                 for name in ('config.json', 'state_in.json', 'state_out.json')]
        fingerprint = receipt['input']
        if (any(receipt['sha256'].get(name) != _sha(local(folder / name).read_bytes())
                for name in ('config.json', 'state_in.json', 'state_out.json', 'pdk_root.json'))
                or fingerprint.get('state') != _sha((folder / 'state_in.json').read_bytes())
                or not _HEX.fullmatch(str(fingerprint.get('config', '')))
                or config.get('meta', {}).get('step') != 'OpenROAD.STAPrePNR'
                or before['nl'] != after['nl']
                or fingerprint['state_files'].get(before['nl']) != _sha(local(before['nl']).read_bytes())):
            raise MetricRefusal('D26_NATIVE_SUBJECT_UNBOUND', 'actual native input/output netlist differs')
        mounts = json.loads(local(folder / 'pdk_root.json').read_text()).get('mounts_under_it', [])
        mounts = sorted(mounts, key=lambda p: len(str(p[1])), reverse=True)

        def actual_input(name):
            path = Path(name)
            if not path.is_absolute():
                raise MetricRefusal('D26_NATIVE_READSET_UNBOUND', name)
            source = next((Path(host) / path.relative_to(guest) for host, guest in mounts
                           if path.is_relative_to(guest)), path)
            expected = fingerprint.get('config_files', {}).get(name)
            if (not _HEX.fullmatch(str(expected or '')) or not source.is_file()
                    or _sha(source.read_bytes()) != expected):
                raise MetricRefusal('D26_NATIVE_READSET_STALE', name)
            consumed[str(source.resolve())] = expected

        corners = sta._corners(folder)
        if not corners or not config.get('STA_CORNERS') or config.get('MACROS'):
            raise MetricRefusal('D26_NATIVE_POPULATION_UNMEASURED', 'complete standard-cell corner set required')
        libraries = config.get('CELL_LIBS') or config.get('LIB') or {}

        def selected_libs(corner):
            selected = []
            # Match the native resolver's complete standard/pad/extra library
            # population. Every selected path must occur in the actual read
            # log and retain its original fingerprint SHA and native unit.
            for group in (libraries, config.get('PAD_LIBS'), config.get('EXTRA_LIBS')):
                if group is None:
                    continue
                groups = ([values for pattern, values in group.items()
                           if fnmatch.fnmatch(corner, pattern)]
                          if isinstance(group, Mapping) else [group])
                for values in groups:
                    values = [values] if isinstance(values, str) else values
                    if (not isinstance(values, (list, tuple))
                            or any(not isinstance(p, str) or not p for p in values)):
                        raise MetricRefusal('D26_NATIVE_POPULATION_UNMEASURED', 'invalid library selector')
                    selected.extend(values)
            if len(set(selected)) != len(selected):
                raise MetricRefusal('D26_NATIVE_POPULATION_UNMEASURED', 'duplicate configured library')
            return sorted(selected)

        rows, measured_models = {}, set()
        for corner in corners:
            for name in ('sta.log', 'checks.rpt'):
                p = local(corner / name)
                if receipt['sha256'].get(p.relative_to(folder).as_posix()) != _sha(p.read_bytes()):
                    raise MetricRefusal('D26_NATIVE_REPORT_UNSEALED', str(p))
            log = (corner / 'sta.log').read_text()
            deck = config.get('PNR_SDC_FILE')
            if (not deck or re.findall(r"^Reading design constraints file at '([^']+)'", log, re.M) != [deck]
                    or re.findall(r"^Reading top-level netlist at '([^']+)'", log, re.M) != [before['nl']]):
                raise MetricRefusal('D26_NATIVE_READSET_UNPROVEN', corner.name)
            actual_input(deck)
            read_libs = [path for label, path in native._STA_CELL_LIBRARY_RE.findall(log)
                         if label == corner.name]
            declared = selected_libs(corner.name)
            if not declared or sorted(read_libs) != declared or len(set(read_libs)) != len(read_libs):
                raise MetricRefusal('D26_NATIVE_READSET_UNPROVEN', corner.name + ': libraries')
            for path in read_libs:
                actual_input(path)
            unit = sta._native_time_unit(folder, corner, read_libs)
            if unit not in _STA_TIME_TO_NS:
                raise MetricRefusal('D26_NATIVE_UNIT_UNMEASURED', corner.name)
            local(corner / sta._TIME_UNIT_REPORT)
            counts = sta.check_setup_counts((corner / 'checks.rpt').read_text(), sta.supply_names(config))
            if counts is None or sta.black_boxes(log) or sta.sdc_diagnostics(log, Path(deck)):
                raise MetricRefusal('D26_NATIVE_POPULATION_UNMEASURED', corner.name + ': incomplete linked timing')
            values = {check + '_ws': _finite_number(after['metrics'].get(
                f'timing__{check}__ws__corner:{corner.name}')) * _STA_TIME_TO_NS[unit]
                      for check in ('setup', 'hold')}
            rows[corner.name] = {'counts': counts, 'slack': values, 'unit': 'ns', 'native_unit': unit}
            measured_models.add(tuple(declared))
        if (set(rows) != {key.split('corner:', 1)[1] for key in after['metrics']
                         if key.startswith('timing__setup__ws__corner:')}
                or any(not selected_libs(c) or tuple(selected_libs(c)) not in measured_models
                       for c in config['STA_CORNERS'])):
            raise MetricRefusal('D26_NATIVE_POPULATION_UNMEASURED', 'missing configured timing model/corner')
        identity = {'producer': {'receipt': _sha((folder / 'vibeic_receipt.json').read_bytes())},
            'checker': {'source': _sha(Path(__file__).read_bytes())},
            'tool_execution': {'step': 'OpenROAD.STAPrePNR',
                'input_fingerprint_sha256': _sha(_json_key(fingerprint).encode())},
            'consumed_inputs': consumed,
            'requirements': {'obligations': [o['id'] for o in obligations]},
            'configuration': {'mode': 'functional', 'corners': sorted(rows)}}
        result['native_observation'] = {'corners': rows, 'consumed_inputs': consumed,
            'scope': 'functional pre-layout estimate, ideal clocks and no routed parasitics'}
        for obligation in obligations:
            oid, spec = obligation['id'], specs[obligation['id']]
            item = {'id': oid, 'operator': spec['operator']}
            if spec['operator'] == 'eq':
                endpoint = oid.endswith('unconstrained_endpoints')
                value = sum(r['counts'].get('unconstrained_endpoints', 0) if endpoint
                            else sum(r['counts'].values()) for r in rows.values())
                status, reason = evaluate_operator('eq', {'status': 'MEASURED', 'identity': identity,
                    'value': value, 'unit': 'count'}, {'status': 'APPROVED', 'value': 0, 'unit': 'count'})
                item.update(status=status, reason=reason, observed_value=value, unit='count')
            else:
                try:
                    authority, body = _approved_document(project, spec['bounds_ref'].split('#')[0],
                        authority='requirements_owner', schema=AUTHORITY_SCHEMA)
                    payload = {k: v for k, v in body.items() if k not in ('schema', 'approval')}
                    source = json.loads(bound(authority['source']).read_text())
                    if (source.get('prelayout_timing_targets') != payload
                            or not body.get('limits')
                            or not set(body['limits']) <= {'setup_ws', 'hold_ws'}
                            or set(body.get('units', {})) != set(body['limits'])):
                        raise MetricRefusal('D26_BOUNDS_SOURCE_UNBOUND', 'exact independent declared slack payload required')
                    bound({'path': authority['path'], 'sha256': authority['sha256']})
                    checks = []
                    for corner, row_values in rows.items():
                        for field in body['limits']:
                            value = row_values['slack'][field]
                            status, reason = evaluate_operator('within_declared_bounds',
                                {'status': 'MEASURED', 'identity': identity, 'value': value, 'unit': 'ns'},
                                {'status': 'APPROVED', 'limits': body['limits'][field], 'unit': body['units'][field]})
                            checks.append({'corner': corner, 'metric': field, 'value': value,
                                           'unit': 'ns', 'status': status, 'reason': reason})
                    states = [c['status'] for c in checks]
                    item.update(status='FAIL' if 'FAIL' in states else 'PASS'
                        if states and all(s == 'PASS' for s in states) else 'NOT_MEASURED',
                        checks=checks, authority=authority)
                except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                    item.update(status='NOT_MEASURED', reason=getattr(exc, 'code', 'D26_BOUNDS_UNMEASURED'),
                                detail=str(exc))
            result['obligations'].append(item)
        if any(_sha(Path(p).read_bytes()) != digest for p, digest in consumed.items()):
            raise MetricRefusal('D26_INPUT_CHANGED_DURING_READ', 'native/authority readset')
        states = [o['status'] for o in result['obligations']]
        result['status'] = 'FAIL' if 'FAIL' in states else 'PASS' if states == ['PASS'] * 3 else 'NOT_MEASURED'
        result['delivery_blocked'] = result['status'] != 'PASS'
        result['reason'] = 'D26_NATIVE_METRICS_' + result['status']
    except (native.Refusal, MetricRefusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(status='FAIL' if any(o.get('status') == 'FAIL' for o in result['obligations'])
                      else 'NOT_MEASURED', delivery_blocked=True,
                      reason=getattr(exc, 'code', 'D26_NATIVE_METRICS_UNMEASURED'), detail=str(exc))
    return result


def d30_consumed_changes(project: Path, context: Mapping[str, Any]) -> dict:
    """Observe the no-power-intent, single-clock logical change population.

    Reuse the independently adopted original native LEC producer's complete
    pre/post JSON views. This executes no synthesis or proof. Multi-clock,
    asynchronous-reset and power-intent changes need their actual producer;
    they are not covered by this conditional empty-population observation.
    """
    import _cdc_netlist as graph
    import librelane_eqy as lec
    import flow109
    project = Path(project).resolve()
    try:
        if context.get('features', {}).get('has_power_intent') is not False:
            raise MetricRefusal('D30_POWER_CHANGE_POPULATION_UNMEASURED', 'power-intent delta producer required')
        prepared = _d25_inputs(project)
        # This is a read-only current registry contract, never a new execution
        # context/request. The adopted producer receipt must match it too.
        row = flow109.resolve_step(flow109.resolve_plan(context['features']), 'D25')
        original = lec.d25_reopen(project, prepared, {'resolved_row': row})
        record = _d30_file(project, original['execution_record'], 'adopted native change views')
        doc = json.loads(record.read_text())
        if original['proof']['verdict'] != 'PASS':
            raise MetricRefusal('D30_CHANGE_PROOF_UNQUALIFIED', 'adopted original LEC must pass')
        authority, _, source = _d12_source(project, 'clock_reset_crossing_census', D12_FIELDS)
        original_rtl = {r['path']: r['sha256'] for r in original['subject']['rtl']}
        source_input = source['subject']['input']
        source_rtl = {r['path']: r['sha256'] for r in source_input['files']
                      if r['path'] in source_input['rtl_files']}
        if source_rtl != original_rtl:
            raise MetricRefusal('D30_CHANGE_INPUT_STALE', 'original RTL and input-role subjects differ')
        consumed = dict(original['consumed_inputs'])
        for ref in (original['execution_record'], original['execution_authority'], authority):
            path = _d30_file(project, {k: ref[k] for k in ('path', 'sha256')}, 'change source')
            consumed[str(path)] = _sha(path.read_bytes())
        path = _d30_file(project, authority['source'], 'original input roles')
        consumed[str(path)] = _sha(path.read_bytes())
        for ref in source_input['files']:
            path = _d30_file(project, ref, 'original role source input')
            consumed[str(path)] = ref['sha256']
        inputs = source['input_domains']
        clock = original['mode']['clock']['port']
        population = {}
        combinational = {'$and', '$or', '$xor', '$xnor', '$not', '$logic_not', '$logic_and',
            '$logic_or', '$mux', '$pmux', '$buf', '$pos', '$add', '$sub', '$mul', '$neg',
            '$eq', '$ne', '$eqx', '$nex', '$lt', '$le', '$gt', '$ge', '$shl', '$shr',
            '$sshl', '$sshr', '$shift', '$shiftx', '$slice', '$concat', '$reduce_and',
            '$reduce_or', '$reduce_xor', '$reduce_xnor', '$reduce_bool', '$_BUF_', '$_NOT_',
            '$_AND_', '$_OR_', '$_XOR_', '$_XNOR_', '$_MUX_', '$scopeinfo'}
        for side in ('gold', 'gate'):
            views = [r for r in doc['derivation'][side]['files'] if r['path'].endswith('/after.json')]
            if len(views) != 1:
                raise MetricRefusal('D30_CHANGE_POPULATION_UNMEASURED', side + ': original native JSON absent')
            path = _d30_file(project, views[0], side + ' native JSON')
            consumed[str(path)] = views[0]['sha256']
            nl = graph.load(path, top=original['mode']['top'])
            decoded = {f.name for f in nl.flops}
            if (not decoded or nl.memories or nl.ambiguous_drivers
                    or any(name not in decoded and c['type'] not in combinational
                           for name, c in nl.cells.items())
                    or any(not f.q or len(f.d) != len(f.q) or f.arst is not None
                           or nl.sample_edge(f) != 1 for f in nl.flops)
                    or graph.clock_domains(nl) != [clock]):
                raise MetricRefusal('D30_CHANGE_POPULATION_UNMEASURED', side + ': not a complete synchronous single-clock graph')
            ports = {name for name, (direction, _) in nl.ports.items() if direction in ('input', 'inout')}
            if (set(inputs) != ports or any(r.get('clock') != clock
                    or r.get('role') not in ('clock', 'synchronous_data', 'synchronous_reset', 'inactive')
                    for r in inputs.values())):
                raise MetricRefusal('D30_CHANGE_POPULATION_UNMEASURED', side + ': original input roles differ or are asynchronous')
            q_bits = sum(len(f.q) for f in nl.flops)
            if len(nl.flop_of_q()) != q_bits:
                raise MetricRefusal('D30_CHANGE_POPULATION_UNMEASURED', side + ': state driver population differs')
            population[side] = {'cells': len(nl.cells), 'flop_cells': len(nl.flops),
                'q_bits': q_bits, 'clock_domains': [clock], 'native_view': views[0]}
        if any(_sha(Path(name).read_bytes()) != digest for name, digest in consumed.items()):
            raise MetricRefusal('D30_CHANGE_INPUT_STALE', 'native/role source changed')
        return {'status': 'MEASURED', 'value': [], 'population': population,
            'subject': original['subject'], 'has_power_intent': False,
            'consumed_inputs': consumed, 'execution_record': original['execution_record'],
            'scope': 'no register clock/reset-domain crossing changes in complete single-clock synchronous views; no authored power-intent changes; no physical power/timing qualification'}
    except (graph.Refusal, MetricRefusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'status': 'NOT_MEASURED', 'reason': getattr(exc, 'code', 'D30_CHANGE_POPULATION_UNMEASURED'),
                'detail': str(exc)}


def accept_d30(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """Bind the delivered bundle; the missing delta producer still blocks D30."""
    import flow109
    project = Path(project).resolve()
    result = {"schema": SCHEMA, "row_id": "D30", "status": "NOT_MEASURED",
              "delivery_blocked": True, "obligations": []}
    for obligation in context["resolved_row"]["obligations"]:
        oid, spec = obligation["id"], D30_BINDINGS.get(obligation["id"])
        item = {"id": oid, "status": "NOT_MEASURED"}
        if spec is None or any(obligation["expectation"].get(k) != v for k, v in spec.items()):
            item.update(status="UNIMPLEMENTED_METRIC_BINDING",
                        reason="D30_POST_SYNTH_CROSSING_POWER_CENSUS_UNBOUND")
        else:
            try:
                admission = flow109.dft_preroute_admission(project, context)
                chain = flow109._complete_preroute_chain(project, context, admission,
                    component.get("d30_delivery_receipt"), d30_context_sha256=context["context_sha256"])
                if chain.get("status") != "PASS":
                    item.update(status="FAIL" if chain.get("status") == "FAIL" else "NOT_MEASURED",
                                reason=chain.get("reason", "D30_DELIVERY_BINDING_UNPROVEN"))
                else:
                    path = _d30_file(project, chain["d30_delivery_receipt"], "D30 delivery")
                    delivery = json.loads(path.read_text())
                    current = d30_consumed_timing(project, admission)
                    if current["status"] != "MEASURED":
                        raise MetricRefusal(current["reason"], current.get("detail", "D26 actual inputs"))
                    if (delivery.get("consumed_timing") != current
                            or delivery.get("metric_reader_source_sha256") != _sha(Path(__file__).read_bytes())):
                        raise MetricRefusal("D30_DELIVERY_READSET_STALE", "D30 producer did not bind current readset")
                    if spec['operator'] == 'covers_all':
                        observed = d30_consumed_changes(project, context)
                        if observed['status'] != 'MEASURED':
                            raise MetricRefusal(observed['reason'], observed.get('detail', 'native changes'))
                        if delivery.get('consumed_changes') != observed:
                            raise MetricRefusal('D30_DELIVERY_READSET_STALE', 'change population was not producer-bound')
                        authority, body = _approved_authority(project, spec['required_set_ref'], ('kind', 'name'))
                        source = json.loads((project / authority['source']['path']).read_text())
                        payload = {k: v for k, v in body.items() if k not in ('schema', 'approval')}
                        absence = dict(payload.get('validated_absence') or {})
                        if absence.pop('source_reference', None) != authority['source']:
                            raise MetricRefusal('D30_CHANGE_AUTHORITY_UNBOUND', 'conditional absence source differs')
                        payload['validated_absence'] = absence
                        if (source.get('post_synth_crossing_power_changes') != payload
                                or body.get('subject') != observed['subject']
                                or body.get('has_power_intent') is not False
                                or not authority.get('validated_absence') or body['required_items']):
                            raise MetricRefusal('D30_CHANGE_AUTHORITY_UNBOUND', 'independent exact conditional absence required')
                        consumed = {**observed['consumed_inputs'], **current['consumed_inputs'],
                            authority['path']: authority['sha256'],
                            authority['source']['path']: authority['source']['sha256'],
                            chain['d30_delivery_receipt']['path']: chain['d30_delivery_receipt']['sha256']}
                        identity = {'producer': {'sha256': delivery['producer_source_sha256']},
                            'checker': {'sha256': delivery['metric_reader_source_sha256']},
                            'tool_execution': observed['execution_record'], 'consumed_inputs': consumed,
                            'requirements': {k: authority[k] for k in ('path', 'sha256', 'source')},
                            'configuration': {'profile': delivery['profile_identity']}}
                        status, detail = evaluate_operator('covers_all', {'status': 'MEASURED',
                            'identity': identity, 'value': observed['value']}, authority)
                        if any(_sha(Path(project / name).read_bytes()) != digest for name, digest in consumed.items()):
                            raise MetricRefusal('D30_SOURCE_CHANGED_DURING_READ', 'change observation')
                        item.update(status=status, measurement=observed, authority=authority, detail=detail)
                        result['obligations'].append(item)
                        continue
                    authority, body = _approved_document(project, spec["reference_ref"],
                        authority="requirements_owner", schema="vibeic.flow109.adopted-reference.v1")
                    approved = json.loads((project / authority["source"]["path"]).read_text())
                    payload = {key: body[key] for key in ("reference", "reference_identity")}
                    if approved.get("adopted_netlist_sdc_library") != payload:
                        raise MetricRefusal("D30_ADOPTED_REFERENCE_SOURCE_MISMATCH", "independent approval semantics")
                    _identity_complete(body["reference_identity"])
                    authority.update(payload)
                    consumed = {**current["consumed_inputs"],
                                chain["d30_delivery_receipt"]["path"]: chain["d30_delivery_receipt"]["sha256"]}
                    for reference in chain["references"].values():
                        consumed[reference["path"]] = reference["sha256"]
                    identity = {"producer": {"sha256": delivery["producer_source_sha256"]},
                        "checker": {"sha256": delivery["metric_reader_source_sha256"]},
                        "tool_execution": {"receipt": current["native_receipt"],
                                           "records": current["native_records"]},
                        "consumed_inputs": consumed, "requirements": authority,
                        "configuration": {"context_sha256": context["context_sha256"],
                                          "profile": delivery["profile_identity"]}}
                    measured = {"status": "MEASURED", "identity": identity,
                        "value": {"netlist_sha256": chain["references"]["D30"]["sha256"],
                                  "timing": current["value"]}}
                    status, detail = evaluate_operator(spec["operator"], measured, authority)
                    for record in ({"path": name, "sha256": sha} for name, sha in {
                            **consumed, authority["path"]: authority["sha256"],
                            authority["source"]["path"]: authority["source"]["sha256"]}.items()):
                        path = project / record["path"]
                        if not path.is_file() or _sha(path.read_bytes()) != record["sha256"]:
                            raise MetricRefusal("D30_SOURCE_CHANGED_DURING_READ", record["path"])
                    item.update(status=status, measurement=measured, authority=authority, detail=detail)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
                item.update(reason=getattr(exc, "code", "D30_METRIC_REFUSED"), detail=str(exc))
        result["obligations"].append(item)
    statuses = [item["status"] for item in result["obligations"]]
    if statuses and all(status == "PASS" for status in statuses):
        result.update(status="PASS", delivery_blocked=False)
    elif "FAIL" in statuses:
        result["status"] = "FAIL"
    result["reason"] = ("D30_ADOPTED_BUNDLE_MISMATCH" if result["status"] == "FAIL"
                        else "D30_POST_SYNTH_CROSSING_POWER_CENSUS_UNBOUND")
    return result


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


def _a01_chip_specs(project, outputs):
    """Retain chip facts separately from the existing per-block denominator."""
    import analog_a1_spec_emit as owner
    amendment = owner.approved_electrical_attribution(project)
    if not amendment:
        return [], {}, {}
    if not any(row['scope'] == 'chip' for row in amendment['rows']):
        return [], {}, amendment['readset']
    path = project / owner.CHIP_SPECS_REL
    digest = _sha(path.read_bytes())
    if outputs.get(owner.CHIP_SPECS_REL, outputs.get(str(path))) != digest:
        raise MetricRefusal('METRIC_EVIDENCE_STALE', owner.CHIP_SPECS_REL)
    body = json.loads(path.read_text())
    owner.validate_attribution_output(project, body, None)
    return ([{'scope': 'chip', 'name': entry['name'], 'unit': entry['unit']}
             for entry in body['specs']], {owner.CHIP_SPECS_REL: digest}, amendment['readset'])


def _a01_measurements(project: Path, component: Mapping[str, Any],
                      context: Mapping[str, Any]) -> tuple[dict, dict]:
    if component.get("component_status") == "FAIL":
        failure = {"status": "FAIL", "reason": component.get("reason")}
        return failure, failure
    if component.get("component_status") != "PASS":
        missing = {"status": "NOT_MEASURED", "reason": "A01 component is not current PASS"}
        return missing, missing
    if "native_results" in component:
        return _a01_native_measurements(project, component, context)
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
        from analog_a1_spec_emit import validate_attribution_output
        validate_attribution_output(project, body, name)
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
    chip_specs, chip_outputs, attribution_inputs = _a01_chip_specs(project, component.get('outputs', {}))
    output_identity.update(chip_outputs)
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
                            if digest is not None} | attribution_inputs,
        "requirements": "bound-per-obligation",
        "configuration": uses[0].get("config"),
        "models": {"status": "NOT_APPLICABLE_TO_STRUCTURED_SPEC_BINDING"},
        "outputs": output_identity,
        "source": component.get("source_sha256"),
    }
    _identity_complete(identity)
    return ({"status": "MEASURED", "value": specs, "identity": identity, "chip_specs": chip_specs},
            {"status": "MEASURED", "value": measurements, "identity": identity})


def _a01_native_measurements(project, component, context):
    """Read the normal A01 attempt; specification targets are not performance results."""
    import analog_native_flow as owner
    import librelane_contract as launch
    if not any((project / path).is_file() for path in (
            'phase3/analog/analog_block_list.json', 'phase1/analog/analog_block_list.json')):
        raise MetricRefusal('METRIC_INPUT_ABSENT', 'existing analog block declaration required')
    names = [b.get('name') or b.get('block') for b in owner._declared_blocks(project)]
    try:
        image = launch.resolve_image(project, record=False)
    except launch.Refusal as exc:
        raise MetricRefusal(exc.code, str(exc)) from exc
    rows, readset = owner._a18_current_rows(project, component['native_results'], 'A01', names, image)
    specs, measurements, checks = [], [], []
    l5 = project / 'phase1/generated_docs/L5_ADI_SPEC.json'
    for row in rows:
        name = row['block']
        gates = [e for e in row.get('executions', [])
                 if e.get('program') == 'analog_a1_spec_extract_check.py']
        if len(gates) != 1 or gates[0].get('returncode') != 0:
            raise MetricRefusal('METRIC_EXECUTION_EVIDENCE_INVALID', name)
        gate = gates[0]
        log = _safe_project_file(project, str(Path(gate['log']).relative_to(project)))
        if _sha(log.read_bytes()) != gate.get('log_sha256'):
            raise MetricRefusal('METRIC_EXECUTION_EVIDENCE_INVALID', name)
        if '--json' not in gate.get('args', []):
            raise MetricRefusal('METRIC_EXECUTION_EVIDENCE_INVALID', name)
        report = Path(gate['args'][gate['args'].index('--json') + 1])
        if (gate['args'] != [str(project), '--block', name, '--json', str(report)]
                or not any(Path(str(arg)).name == 'analog_a1_spec_extract_check.py'
                           for arg in gate.get('argv', []))
                or str(report) not in row['output_views']):
            raise MetricRefusal('METRIC_EVIDENCE_ABSENT', str(report))
        body = json.loads(report.read_text())
        if body.get('gate') != 'analog_a1_spec_extract_check' or body.get('verdict') != 'PASS':
            raise MetricRefusal('METRIC_EVIDENCE_INVALID', str(report))
        spec = project / 'phase3/analog' / name / 'spec.json'
        if row['output_views'].get(str(spec)) != _sha(spec.read_bytes()):
            raise MetricRefusal('METRIC_EVIDENCE_STALE', str(spec))
        body = json.loads(spec.read_text())
        from analog_a1_spec_emit import validate_attribution_output
        validate_attribution_output(project, body, name)
        provenance = body.get('_provenance', {})
        if (provenance.get('producer') != 'analog_a1_spec_emit'
                or provenance.get('defaults_used') is not False
                or provenance.get('fields_defaulted') != [] or provenance.get('ai_handoff') is not None
                or provenance.get('input', {}).get('path') != str(l5.relative_to(project))
                or provenance['input'].get('sha256') != _sha(l5.read_bytes())):
            raise MetricRefusal('METRIC_EVIDENCE_UNSUPPORTED', 'incomplete/source-unbound ' + name)
        for entry in body.get('specs', []):
            metric, unit = entry.get('name'), entry.get('unit')
            values = [entry[k] for k in ('min', 'typ', 'max', 'value', 'target') if k in entry]
            if (not isinstance(metric, str) or not _SAFE.fullmatch(metric)
                    or not isinstance(unit, str) or not unit or not values):
                raise MetricRefusal('METRIC_EVIDENCE_INVALID', str(spec))
            for value in values:
                _finite_number(value)
            specs.append({'block': name, 'name': metric, 'unit': unit})
            measurements.append({'block': name, 'name': metric})
        readset[str(log)] = gate['log_sha256']
        checks.append({'block': name, 'report': str(report), 'log_sha256': gate['log_sha256']})
    if not specs:
        raise MetricRefusal('METRIC_EVIDENCE_ABSENT', 'no source-owned specification targets')
    outputs = {key: digest for row in rows for key, digest in row['output_views'].items()}
    chip_specs, chip_outputs, attribution_inputs = _a01_chip_specs(project, outputs)
    from analog_a1_spec_emit import ATTRIBUTION_REL
    if attribution_inputs:
        expected = attribution_inputs[ATTRIBUTION_REL]
        if any(row['input_views'].get(str(project / ATTRIBUTION_REL)) != expected for row in rows):
            raise MetricRefusal('METRIC_INPUT_CHANGED', ATTRIBUTION_REL)
    readset.update({str(project / key): digest for key, digest in attribution_inputs.items()})
    readset.update({str(project / key): digest for key, digest in chip_outputs.items()})
    identity = {'producer': {'name': 'analog_a1_spec_emit', 'input_sha256': _sha(l5.read_bytes())},
        'checker': {'name': 'analog_a1_spec_extract_check', 'checks': checks},
        'tool_execution': {'context_sha256': context['context_sha256'],
                          'uses': context['runtime_tool_uses']},
        'consumed_inputs': readset, 'requirements': 'bound-per-obligation',
        'configuration': {'native_attempt': component['native_results']['attempt']}}
    _identity_complete(identity)
    return ({'status': 'MEASURED', 'value': specs, 'identity': identity, 'chip_specs': chip_specs},
            {'status': 'MEASURED', 'value': measurements, 'identity': identity})


def _d10_blackbox_instances(document: Mapping[str, Any], top: str) -> list[str]:
    """Enumerate reachable native blackboxes; unknown cells never count as zero."""
    import _cdc_netlist as native
    modules = document.get('modules')
    if not isinstance(modules, Mapping) or top not in modules:
        raise MetricRefusal('D10_ELABORATION_INVALID', 'selected top absent')
    blackboxes = {name for name, module in modules.items()
                  if isinstance(module, Mapping)
                  and native._int((module.get('attributes') or {}).get('blackbox', 0))}
    if top in blackboxes:
        raise MetricRefusal('D10_ELABORATION_UNRESOLVED', 'top is a blackbox')
    pending = [(top, '', frozenset())]
    found = []
    while pending:
        name, prefix, ancestors = pending.pop()
        if name in ancestors or not isinstance(modules.get(name), Mapping):
            raise MetricRefusal('D10_ELABORATION_INVALID', 'recursive or malformed hierarchy')
        cells = modules[name].get('cells', {})
        if not isinstance(cells, Mapping):
            raise MetricRefusal('D10_ELABORATION_INVALID', 'cell inventory missing')
        for instance, cell in cells.items():
            if not isinstance(instance, str) or not isinstance(cell, Mapping) or not isinstance(cell.get('type'), str):
                raise MetricRefusal('D10_ELABORATION_INVALID', 'cell identity invalid')
            kind, path = cell['type'], prefix + instance
            if kind in blackboxes:
                found.append(path)
            elif kind in modules:
                pending.append((kind, path + '/', ancestors | {name}))
            elif not kind.startswith('$'):
                raise MetricRefusal('D10_ELABORATION_UNRESOLVED', path)
    return sorted(found)


def observe_d10_frontend_metrics(project: Path, context: Mapping[str, Any], p0: Mapping[str, Any]) -> dict:
    """Bind native counts and reviewed per-use admission to typed obligations.

    Feature inventory and product authority remain independent row debts.
    """
    import _cdc_netlist as native
    import flow109
    import librelane_contract as contract
    import vibe_ic_one_shot_runner as runner
    project = Path(project).resolve()
    answer = {'schema': SCHEMA, 'row_id': 'D10', 'status': 'NOT_MEASURED',
              'delivery_blocked': True, 'qualification': 'NOT_MEASURED', 'obligations': []}
    try:
        current = flow109.validate_execution_context(context)
        if (current.get('resolved_row') or {}).get('id') != 'D10':
            raise MetricRefusal('D10_CONTEXT_INVALID', 'not D10')
        obligations = current['resolved_row']['obligations']
        expected = {'base_04.elaboration_errors', 'base_04.unexpected_blackboxes'}
        selected = {row.get('id'): row for row in obligations if row.get('id') in expected}
        if set(selected) != expected or any(row.get('expectation') != {
                'operator': 'eq', 'value': 0, 'unit': 'count',
                'source': 'contract invariant: no unresolved required violations'}
                for row in selected.values()):
            raise MetricRefusal('D10_OBLIGATIONS_UNREGISTERED', 'two native obligations differ')
        identity = runner._validate_d10_p0_consumer(project, p0)
        from flow109_frontend import d10_native_qualification
        from flow109_admission import AdmissionRefusal
        try:
            admitted = d10_native_qualification(project, current, p0, identity)
            answer['qualification'] = 'PASS'
            answer['qualification_admission'] = admitted
        except AdmissionRefusal as exc:
            answer['qualification_refusal'] = exc.report

        def measured_obligation(oid, value):
            row = {'id': oid, 'status': 'NOT_MEASURED',
                   'observation_status': 'OBSERVED' if value is not None else 'NOT_MEASURED',
                   'observed_value': value, 'unit': 'count',
                   'reason': ('TOOL_QUALIFICATION_UNPROVEN' if value is not None
                              else 'EXPECTED_BLACKBOX_AUTHORITY_MISSING'), 'binding': identity}
            if answer['qualification'] == 'PASS' and value is not None:
                typed_identity = {
                    'producer': identity['producer_result'],
                    'checker': {'source_sha256': _sha(Path(__file__).read_bytes())},
                    'tool_execution': {key: identity[key] for key in
                        ('tool_sha256', 'image_id', 'cid', 'attestation_sha256')},
                    'consumed_inputs': {'fingerprint': identity['input_fingerprint']},
                    'requirements': selected[oid]['expectation'],
                    'configuration': admitted}
                status, detail = evaluate_operator('eq',
                    {'status': 'MEASURED', 'value': value, 'unit': 'count', 'identity': typed_identity},
                    {'status': 'APPROVED', 'value': selected[oid]['expectation']['value'], 'unit': 'count'})
                row.update(status=status, reason=detail, identity=typed_identity)
            return row

        failure = identity.get('native_failure')
        if failure:
            if runner._validate_d10_p0_consumer(project, p0) != identity:
                raise MetricRefusal('D10_NATIVE_BINDING_STALE', 'native failure identity changed')
            answer['native_failure'] = failure
            answer['obligations'] = [
                measured_obligation('base_04.elaboration_errors', failure['elaboration_errors']),
                {'id': 'base_04.unexpected_blackboxes', 'status': 'NOT_MEASURED',
                 'observation_status': 'NOT_MEASURED', 'observed_value': None, 'unit': 'count',
                 'reason': 'D10_FAILED_ELABORATION_NO_BLACKBOX_CENSUS', 'binding': identity}]
            answer['reason'] = 'TOOL_QUALIFICATION_UNPROVEN'
            if answer['obligations'][0]['status'] == 'FAIL':
                answer.update(status='FAIL', reason='D10_QUALIFIED_NATIVE_METRIC_FAILED')
            return answer
        elab = _safe_project_file(project, p0['elaboration_path'])
        raw = elab.read_bytes()
        if _sha(raw) != p0['elaboration_sha256']:
            raise MetricRefusal('D10_ELABORATION_STALE', str(elab))
        graph = json.loads(raw)
        instances = _d10_blackbox_instances(graph, p0['top'])
        if (_sha(elab.read_bytes()) != p0['elaboration_sha256']
                or runner._validate_d10_p0_consumer(project, p0) != identity):
            raise MetricRefusal('D10_NATIVE_BINDING_STALE', 'native identity changed during observation')
        # A successful native elaboration proves zero frontend errors. It does
        # not itself establish expected blackbox exceptions or tool qualification.
        values = {'base_04.elaboration_errors': 0,
                  'base_04.unexpected_blackboxes': 0 if not instances else None}
        for oid in ('base_04.elaboration_errors', 'base_04.unexpected_blackboxes'):
            answer['obligations'].append(measured_obligation(oid, values[oid]))
        answer['observed_blackbox_instances'] = instances
        answer['reason'] = ('D10_FEATURE_INVENTORY_UNPROVEN' if answer['qualification'] == 'PASS'
                            else 'TOOL_QUALIFICATION_AND_FEATURE_INVENTORY_UNPROVEN')
    except (MetricRefusal, native.Refusal, flow109.Flow109Error, contract.Refusal,
            OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer.update(qualification='NOT_MEASURED', obligations=[])
        answer.pop('qualification_admission', None)
        answer.pop('native_failure', None)
        answer['reason'] = getattr(exc, 'code', 'D10_NATIVE_BINDING_UNPROVEN')
        answer['detail'] = str(exc)
    return answer


def _d09_supplied_rtl(project, author, bound, document):
    import reused_ip_rtl_consume as supplied
    import _specrtl_common as rtl
    manifest_rel = 'phase2/stage1/rtl/SOURCE_MANIFEST.json'
    if author['extras'].get('manifest_emitted') != manifest_rel:
        raise MetricRefusal('D09_SUPPLIED_PUBLICATION_UNBOUND', 'normal consume manifest required')
    manifest = document(manifest_rel)
    originals = supplied.discover_provided_build_rtl(project)
    names = [p.name for p in originals]
    if not names or len(names) != len(set(names)):
        raise MetricRefusal('D09_SUPPLIED_POPULATION_INVALID', 'unique complete source population required')
    origins = {str(p.relative_to(project)): _sha(bound(str(p.relative_to(project)))) for p in originals}
    if (manifest.get('generated_by') != 'phase2_runner_consume'
            or manifest.get('build_rtl_provided') is not True
            or set(manifest.get('staged_from_input', [])) != set(origins)
            or manifest.get('staged_from_input_sha256') != origins):
        raise MetricRefusal('D09_SUPPLIED_SOURCE_STALE', 'original source population or bytes differ')
    files = rtl.rtl_source_files(project)
    if {p.name for p in files} != set(names):
        raise MetricRefusal('D09_SUPPLIED_POPULATION_INVALID', 'full staged/source population differs')
    for src in originals:
        staged = 'phase2/stage1/rtl/' + src.name
        if _sha(bound(staged)) != origins[str(src.relative_to(project))]:
            raise MetricRefusal('D09_SUPPLIED_SOURCE_STALE', staged)
    return files


def _d09_source_owned_metrics(project: Path, author: Mapping, *, publish=False, invocation=None) -> dict:
    import shutil
    import tempfile
    import design_one_shot_runner as runner
    import p0_tool_frontend_check as frontend
    import _specrtl_common as rtl
    import _atomic_artefact as atomic
    project = Path(project).resolve()
    supplied_author = author.get('name') == 'reused_ip_consume'
    if supplied_author:
        if author.get('status') != 'PASS' or author.get('extras', {}).get('reused_ip') is not True:
            raise MetricRefusal('D09_AUTHOR_UNSUPPORTED', 'ordinary supplied-source publisher required')
    else:
        import ai_signed_judgement as judgement
        if (author.get('name') != 'rtl_gen' or author.get('status') not in ('PASS_WITH_WAIVERS', 'WAIVED')
                or author.get('extras', {}).get('fallback_skill') not in ('spec-to-rtl', 'catalog-glue-author')
                or not judgement._requested(project, '1')):
            raise MetricRefusal('D09_AUTHOR_UNSUPPORTED', 'normal spec-to-rtl handoff required')
        accepted, detail = judgement.check(project, '1')
        if not accepted:
            raise MetricRefusal('D09_AUTHOR_UNSUPPORTED', detail)
    d01 = runner._serial_d01_state(project)
    reads = {}
    owner_sources = {p.name: _sha(p.read_bytes()) for p in (Path(__file__), Path(runner.__file__), Path(frontend.__file__))}
    def bound(relative):
        path = _safe_project_file(project, relative)
        if not path.is_file():
            raise MetricRefusal('D09_SOURCE_UNAVAILABLE', relative)
        raw = path.read_bytes(); reads[relative] = _sha(raw)
        return raw
    def document(relative):
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('D09_DUPLICATE_SOURCE_KEY: ' + key)
                value[key] = item
            return value
        return json.loads(bound(relative), object_pairs_hook=unique)
    files = _d09_supplied_rtl(project, author, bound, document) if supplied_author else rtl.rtl_source_files(project)
    for path in files:
        relative = str(path.relative_to(project))
        if re.search(r'`include|\$(?:fopen|readmem\w*|system)|DPI-C', bound(relative).decode()):
            raise MetricRefusal('D09_NATIVE_READSET_UNSUPPORTED', relative)
    body = document('reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json')
    l9 = document('phase1/generated_docs/L9_INTEGRATION_SPEC.json')
    demands = body.get('source_demands'); expectations = body.get('expectations')
    if (not isinstance(demands, list) or not demands or not isinstance(expectations, list)
            or any(not isinstance(d, dict) or not d.get('id') or not d.get('requirement')
                   or not isinstance(d.get('evidence'), list) or not d['evidence'] for d in demands)
            or len({d['id'] for d in demands}) != len(demands)
            or len({e.get('id') for e in expectations}) != len(expectations)
            or {d['id'] for d in demands} != {e.get('id') for e in expectations}):
        raise MetricRefusal('D09_REQUIRED_POPULATION_INVALID', 'complete adopted expectations required')
    for expectation in expectations:
        leaves = expectation.get('sub_expectations', [expectation])
        if not isinstance(leaves, list) or not leaves or any(not isinstance(x, dict) for x in leaves):
            raise MetricRefusal('D09_REQUIRED_POPULATION_INVALID', 'expectation leaves')
        for leaf in leaves:
            layer = leaf.get('layer')
            if not isinstance(layer, str) or not re.fullmatch(r'L[0-9]+_[A-Z0-9_]+', layer):
                raise MetricRefusal('D09_REQUIRED_POPULATION_INVALID', 'layer address')
            if layer != 'L9_INTEGRATION_SPEC':
                document('phase1/generated_docs/' + layer + '.json')
    import benchmark_dispatch as dispatch
    previous = author.get('extras', {}).get('d09_owned_metrics')
    if not publish:
        if not isinstance(previous, dict):
            raise MetricRefusal('D09_SUPPLIED_PUBLICATION_STALE', 'normal source-author proof absent')
        invocation = previous.get('publication_invocation')
        published = document('reports/orchestrator/phase2_one_shot.json')
        record = published.get('runner_binding', {})
        candidates = [row for row in published.get('steps', [])
                      if (row.get('status') == 'PASS' and row.get('name') in ('rtl_gen', 'reused_ip_consume'))
                      or (not supplied_author and row == author)]
        if (candidates != [author] or published.get('d09_owned_metrics') != previous
                or record.get('schema') != 'vibeic.runner_report_binding.v1'
                or record.get('report_name') != 'phase2_one_shot.json'
                or record.get('material') != dispatch._runner_material_snapshot(project)
                or any(record.get(k) != (invocation or {}).get(k) for k in ('invocation_id','argv','project','source'))
                or record.get('producer') != {'path':str(HERE / 'design_one_shot_runner.py'),
                    'sha256':_sha((HERE / 'design_one_shot_runner.py').read_bytes())}):
            raise MetricRefusal('D09_SUPPLIED_OWNER_UNBOUND', 'actual current child publisher/material required')
        reads.pop('reports/orchestrator/phase2_one_shot.json', None)
    if (not isinstance(invocation, dict) or set(invocation) != {'invocation_id','argv','project','source'}
            or not invocation.get('invocation_id') or invocation.get('project') != str(project)
            or invocation['source'] != dispatch._runner_source_snapshot(invocation['argv'],
                consumer=invocation['source']['consumer']['path'])):
        raise MetricRefusal('D09_SUPPLIED_OWNER_UNBOUND', 'normal current child invocation required')
    argv = invocation['argv']
    try:
        if (len(argv) < 3 or Path(argv[1]).name != 'phase2_one_shot_runner.py'
                or str(Path(argv[2]).resolve()) != str(project)
                or argv[argv.index('--entry-step') + 1] != '1'
                or argv[argv.index('--exit-step') + 1] != '1'):
            raise ValueError('not the source-author span')
    except (ValueError, IndexError, TypeError) as exc:
        raise MetricRefusal('D09_SUPPLIED_OWNER_UNBOUND', str(exc)) from exc
    top = l9.get('top_module')
    if not isinstance(top, str) or not _SAFE.fullmatch(top):
        raise MetricRefusal('D09_L9_INTERFACE_POPULATION_MISSING', 'top')
    binary = shutil.which('yosys')
    if not binary:
        raise MetricRefusal('D09_NATIVE_WITNESS_UNAVAILABLE', 'yosys')
    tool = {'path': str(Path(binary).resolve()), 'sha256': _sha(Path(binary).read_bytes())}
    native_rel = 'reports/audit/phase2/d09_supplied_elaboration.json'
    log_rel = 'reports/audit/phase2/d09_supplied_elaboration.log'
    if not publish:
        previous = author.get('extras', {}).get('d09_owned_metrics')
        if not isinstance(previous, dict) or previous.get('source_sha256') != reads:
            raise MetricRefusal('D09_SUPPLIED_PUBLICATION_STALE', 'original source-author proof required')
        receipt = previous['native_witness']
        if (receipt.get('tool') != tool or receipt.get('path') != native_rel
                or _sha(bound(native_rel)) != receipt.get('sha256')
                or _sha(bound(log_rel)) != receipt.get('log_sha256')):
            raise MetricRefusal('D09_NATIVE_WITNESS_STALE', native_rel)
    # Reuse the existing supervised native frontend, not a project-provided JSON
    # or a new evaluator. The consumer independently recomputes the native facts.
    with tempfile.TemporaryDirectory(prefix=frontend._ELAB_SCRATCH_PREFIX) as td:
        target = Path(td) / 'rtl_elab.json'
        paths = [str(p.resolve()) for p in files]
        if any(not re.fullmatch(r'[A-Za-z0-9_./-]+', p) for p in paths):
            raise MetricRefusal('D09_NATIVE_READSET_UNSUPPORTED', 'unsafe native path')
        script = ('read_verilog -sv ' + ' '.join(paths)
                  + '; hierarchy -check -top ' + top + '; proc; write_json ' + str(target))
        native = frontend._invoke('yosys', ['-Q', '-T', '-p', script], project, None)
        if native.returncode or not target.is_file():
            raise MetricRefusal('D09_NATIVE_WITNESS_UNAVAILABLE', native.stdout + native.stderr)
        raw = target.read_bytes(); graph = json.loads(raw)
    if not publish and json.loads(bound(native_rel)) != graph:
        raise MetricRefusal('D09_NATIVE_WITNESS_STALE', 'native replay differs')
    module = graph['modules'][top]
    actual_ports = {name: [port['direction'], len(port['bits'])] for name, port in module['ports'].items()}
    ports = l9.get('top_ports'); parameters = l9.get('parameters')
    if (not isinstance(ports, list) or not isinstance(parameters, list)
            or len({p.get('name') for p in ports}) != len(ports)
            or len({p.get('name') for p in parameters}) != len(parameters)):
        raise MetricRefusal('D09_L9_INTERFACE_POPULATION_MISSING', 'complete ports/parameters required')
    declared = {p['name']: [p['direction'], p['width']] for p in ports}
    if any(type(p.get('width')) is not int or p['width'] < 1
           or p.get('direction') not in ('input','output','inout') for p in ports):
        raise MetricRefusal('D09_L9_INTERFACE_POPULATION_MISSING', 'typed port population required')
    # Keep the ordinary L9 default field; unknown parameter expressions are
    # not silently coerced. Empty populations are proved by the native IR.
    raw_parameters = module.get('parameter_default_values', {})
    if any(not isinstance(v,str) or not re.fullmatch('[01]+',v) for v in raw_parameters.values()):
        raise MetricRefusal('D09_NATIVE_PARAMETER_UNSUPPORTED', 'nonconstant parameter')
    actual_parameters = {k:int(v,2) for k,v in raw_parameters.items()}
    declared_parameters = {}
    for parameter in parameters:
        value = parameter.get('default')
        if isinstance(value,bool) or not re.fullmatch('[0-9]+',str(value)):
            raise MetricRefusal('D09_NATIVE_PARAMETER_UNSUPPORTED', 'explicit integer default required')
        declared_parameters[parameter['name']] = int(value)
    interface = declared == actual_ports and declared_parameters == actual_parameters
    mapped, missing, required, trace = [], [], [], []
    by_id = {e['id']: e for e in expectations}
    import phase1_expert_parse_track as track
    def witness(node, shape_only=False):
        # Typed native IR properties only; prose/token echoes cannot prove a
        # functional claim. Unsupported properties remain NOT_MEASURED.
        if not isinstance(node, dict): return False
        node = {k:v for k,v in node.items() if k not in ('id','text','evidence')}
        if shape_only: return set(node) in ({'constant'}, {'connection'})
        if set(node) == {'constant'}:
            item = node['constant']
            if set(item) != {'module', 'port', 'bits'}: return False
            bits = item['bits']
            return (isinstance(bits, list) and bool(bits) and all(b in ('0', '1') for b in bits)
                    and graph['modules'][item['module']]['ports'][item['port']]['bits'] == bits)
        if set(node) == {'connection'}:
            item = node['connection']
            if set(item) != {'module', 'cell', 'type', 'cell_port', 'top_port'}: return False
            parent = graph['modules'][item['module']]; cell = parent['cells'][item['cell']]
            return cell['type'] == item['type'] and cell['connections'][item['cell_port']] == parent['ports'][item['top_port']]['bits']
        return False
    later = {
        ('L19_CONSTRAINTS_PDK','timing','constraints','ppa','technology','synthesis'):['D19','D20','D21','D22','D26'],
        ('L24_SIGNOFF',):['D22','D26','D65','D66','D77'],
        ('L20_DFT_SCAN_TOPOLOGY',):['D23','D36','D52'],
        ('L23_SECURITY_REQUIREMENTS',):['D17','D73'], ('L25_RELIABILITY_MISSION_PROFILE',):['D59']}
    for demand in demands:
        expect = by_id[demand['id']]
        if any(expect.get(k) != demand[k] for k in ('requirement', 'evidence')):
            raise MetricRefusal('D09_REQUIRED_POPULATION_INVALID', 'reviewed source relation differs')
        leaves = expect.get('sub_expectations', [expect]); own = False; complete = True
        for leaf in leaves:
            layer, path = leaf.get('layer'), leaf.get('field_path')
            if layer == 'L21_POWER_INTENT':
                node = track.subtree_at(document('phase1/generated_docs/' + layer + '.json'), path, layer)
                if node is None:
                    raise MetricRefusal('D09_REQUIRED_POPULATION_INVALID', 'retained power authority field absent')
                trace.append({'id':demand['id'], 'normal_owner':['D05','D15','D46'], 'status':'NOT_MEASURED'})
                continue
            doc = l9 if layer == 'L9_INTEGRATION_SPEC' else document('phase1/generated_docs/' + str(layer) + '.json')
            node = track.subtree_at(doc, path, layer)
            scope = track._normalise_field_path(str(path).strip('/').replace('/', '.'), layer)
            spellings = track._field_path_spellings(scope)
            if not supplied_author and not (
                    (layer == 'L9_INTEGRATION_SPEC' and any(p.split('.')[0] in ('top_module','top_ports','parameters') for p in spellings))
                    or (isinstance(node, list) and len(node) == 1 and witness(node[0], shape_only=True))):
                owners = next((owners for fields, owners in later.items() if layer in fields
                    or (layer == 'L9_INTEGRATION_SPEC' and set(scope.split('.')) & set(fields))), ['D13','D14'])
                trace.append({'id':demand['id'], 'normal_owner':owners, 'status':'NOT_MEASURED'})
                continue
            own = True
            ok = interface and ((layer == 'L9_INTEGRATION_SPEC' and path in ('top_module','top_ports','parameters'))
                                or (layer == 'L2_FRS' and isinstance(node, list) and len(node) == 1
                                    and isinstance(node[0], dict) and node[0].get('id') == demand['id']
                                    and node[0].get('text') == demand['requirement'] and witness(node[0])))
            complete = complete and ok
        if own:
            required.append(demand['id'])
            (mapped if complete else missing).append(demand['id'])
    if not required:
        raise MetricRefusal('D09_REQUIRED_POPULATION_INVALID', 'no RTL-owned source requirements')
    # Reopen all consumed source bytes and accepted D01 before publication or
    # observation. The native JSON is an output, not part of source identity.
    reads.pop(native_rel, None)
    reads.pop(log_rel, None)
    if any(_sha(_safe_project_file(project, path).read_bytes()) != digest for path, digest in reads.items()) or runner._serial_d01_state(project) != d01:
        raise MetricRefusal('D09_SOURCE_PROOF_STALE', 'source or accepted D01 changed during native read')
    if owner_sources != {p.name: _sha(p.read_bytes()) for p in (Path(__file__), Path(runner.__file__), Path(frontend.__file__))} or _sha(Path(binary).read_bytes()) != tool['sha256']:
        raise MetricRefusal('D09_SOURCE_PROOF_STALE', 'native tool or producer sources changed')
    log = json.dumps({'argv':native.args,'returncode':native.returncode}) + '\n' + native.stdout + native.stderr
    log_sha = _sha(log.encode()) if publish else previous['native_witness']['log_sha256']
    result = {'schema':'vibeic.d09.owned-metrics.v1','source_demands':demands,
              'mapped_items':mapped,'missing_items':missing,'required_rtl_items':required,
              'responsibility_register':trace,'rtl_requirement_mapping':'PASS' if not missing else 'NOT_MEASURED',
              'declared_ports_parameters':'PASS' if interface else 'FAIL',
              'source_sha256':reads,'owner_source_sha256':owner_sources,'D01':d01,'publication_invocation':invocation,
              'native_witness':{'path':native_rel,'sha256':_sha(raw),'log_path':log_rel,'log_sha256':log_sha,'tool':tool},
              'scope':'D09 source facts only; no D10/D13 or physical/whole-flow credit'}
    if publish:
        atomic.write_bytes(project / native_rel, raw)
        atomic.write_bytes(project / log_rel, log.encode())
    elif previous != result:
        raise MetricRefusal('D09_METRICS_STALE', 'published metrics differ from independent native/source facts')
    return result


def d09_owned_metrics(project: Path, author: Mapping) -> dict:
    """Recompute the supported source-bound author metrics, never trust a stamp."""
    if (author.get('name') == 'reused_ip_consume'
            or author.get('extras', {}).get('fallback_skill') in ('spec-to-rtl', 'catalog-glue-author')):
        return _d09_source_owned_metrics(project, author)
    import serial_parallel_mul_synth as serial
    import design_one_shot_runner as runner
    if (author.get('status') != 'PASS'
            or author.get('extras', {}).get('program_first') is not True
            or author.get('extras', {}).get('deterministic_generator') != 'serial_parallel_mul_synth'):
        raise MetricRefusal('D09_AUTHOR_UNSUPPORTED', 'normal supported serial producer required')
    d01 = runner._serial_d01_state(project)
    binding = runner._Phase1ProjectBinding.open(project)
    try:
        current = runner._try_serial_current_source(binding,
            'digital_arithmetic_primitive', __import__('time').time())
        if current is None:
            raise MetricRefusal('D09_SOURCE_PROOF_STALE', 'current normal source publication required')
        result = serial.d09_owned_metrics(project, 'digital_arithmetic_primitive')
        binding.require_current()
        if runner._serial_d01_state(project) != d01:
            raise MetricRefusal('D09_D01_CHANGED', 'upstream evidence changed during comparison')
    finally:
        binding.close()
    published = json.loads((project / 'reports/orchestrator/phase2_one_shot.json').read_bytes())
    if (author.get('extras', {}).get('d09_owned_metrics') != result
            or published.get('d09_owned_metrics') != result):
        raise MetricRefusal('D09_METRICS_STALE', 'published metrics differ from current source/RTL checks')
    return result


def d10_adopted_rtl(project: Path) -> dict:
    """BLOCKING: D10 consumes the completed D09 subject without regenerating it."""
    import _specrtl_common as sources
    import _path_layout as layout
    project = Path(project).resolve()
    path = _safe_project_file(project, 'reports/flow109/default_rows/D09.json')
    raw = path.read_bytes()
    row = json.loads(raw)
    if (row.get('step_id') != 'D09' or row.get('completed') is not True
            or row.get('component_status') != 'PASS'
            or row.get('default_row_status') != 'PASS'):
        raise MetricRefusal('D10_D09_NOT_ACCEPTED', 'completed canonical D09 required')
    inventory = row['evidence']['rtl_inventory']
    expected = {}
    for item in inventory:
        relative = 'phase2/stage1/rtl/' + item['path']
        source = _safe_project_file(project, relative)
        if relative in expected or _sha(source.read_bytes()) != item['sha256']:
            raise MetricRefusal('D10_D09_RTL_STALE', relative)
        expected[relative] = item['sha256']
    actual = {str(p.resolve().relative_to(project)): _sha(p.read_bytes())
              for p in sources.rtl_source_files(project)}
    rtl_expected = {name: sha for name, sha in expected.items()
                    if Path(name).suffix in ('.v', '.sv')}
    if not rtl_expected or rtl_expected != actual:
        raise MetricRefusal('D10_D09_RTL_STALE', 'full adopted RTL population differs')
    d01 = layout.report_path(project, 'phase1_one_shot.json')
    if d01.is_symlink() or not d01.is_file() or not d01.resolve().is_relative_to(project):
        raise MetricRefusal('D10_D01_SOURCE_MISSING', 'normal D01 report required')
    return {'D09': {'path': str(path.relative_to(project)), 'sha256': _sha(raw)},
            'D01': {'path': str(d01.relative_to(project)), 'sha256': _sha(d01.read_bytes())}}


def _d10_feature_inventory(graph: Mapping, top: str) -> dict:
    """Read resolved native interfaces; defaults remain bound by full RTL inputs.

    The qualified command permits no parameter override. Slang lowers source
    defaults and hierarchy and does not promise parameter-default metadata;
    absence of that metadata must never be presented as an empty parameter set.
    """
    ports = {}
    for port, value in graph['modules'][top]['ports'].items():
        direction, bits = value.get('direction'), value.get('bits')
        if direction not in ('input', 'output', 'inout') or not isinstance(bits, list) or not bits:
            raise MetricRefusal('D10_INVENTORY_INVALID', 'native port shape')
        ports[port] = {'direction': direction, 'width': len(bits),
                       'signed': int(bool(value.get('signed', 0)))}
    return {'top': top, 'ports': ports,
            'parameterization': 'SOURCE_DEFAULTS_NO_OVERRIDES',
            'blackbox_instances': _d10_blackbox_instances(graph, top)}


def _d10_inventory_authority(project: Path, subject: Mapping) -> tuple[dict, dict]:
    """Reopen independent adopted input; never adopt the measured inventory."""
    authority, body = _approved_document(project, 'adopted/base_04/feature_inventory.json',
        authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')
    source = authority['source']
    if not source['path'].startswith('input/'):
        raise MetricRefusal('D10_INVENTORY_AUTHORITY_UNPROVEN', 'independent input source required')
    original = json.loads(_safe_project_file(project, source['path']).read_bytes())
    payload = {key: body[key] for key in ('reference', 'reference_identity')}
    reference_identity = payload['reference_identity']
    _identity_complete(reference_identity)
    if (original.get('feature_inventory') != payload
            or reference_identity['consumed_inputs'] != subject):
        raise MetricRefusal('D10_INVENTORY_AUTHORITY_STALE', 'adopted semantics or subject differs')
    reference = payload['reference']
    if (not isinstance(reference, dict)
            or set(reference) != {'top', 'ports', 'parameterization', 'blackbox_instances'}
            or not isinstance(reference['top'], str) or not reference['top']
            or not isinstance(reference['ports'], dict)
            or any(not isinstance(name, str) or not name or not isinstance(port, dict)
                   or set(port) != {'direction', 'width', 'signed'}
                   or port['direction'] not in ('input', 'output', 'inout')
                   or type(port['width']) is not int or port['width'] <= 0
                   or type(port['signed']) is not int or port['signed'] not in (0, 1)
                   for name, port in reference['ports'].items())
            or reference['parameterization'] != 'SOURCE_DEFAULTS_NO_OVERRIDES'
            or not isinstance(reference['blackbox_instances'], list)
            or any(not isinstance(x, str) or not x for x in reference['blackbox_instances'])
            or reference['blackbox_instances'] != sorted(set(reference['blackbox_instances']))):
        raise MetricRefusal('D10_INVENTORY_AUTHORITY_INVALID', 'complete typed inventory required')
    return {**authority, **payload}, body


def accept_d10(project: Path, context: Mapping[str, Any], p0: Mapping) -> dict:
    """BLOCKING D10 grading; independent missing obligations never erase FAIL."""
    import _cdc_netlist as native
    import _specrtl_common as sources
    import flow109
    import vibe_ic_one_shot_runner as runner
    project = Path(project).resolve()
    observed = observe_d10_frontend_metrics(project, context, p0)
    dft = runner._d10_dft_ports(project, p0)
    result = {'schema': SCHEMA, 'row_id': 'D10', 'status': 'NOT_MEASURED',
              'delivery_blocked': True, 'native_metric_observation': observed,
              'obligations': [dict(r) for r in observed.get('obligations', [])]}
    inventory = {'id': 'base_04.feature_inventory', 'status': 'NOT_MEASURED'}
    result['obligations'].append(inventory)
    try:
        current = flow109.validate_execution_context(context)
        declared = current['resolved_row']['obligations']
        if ({r['id'] for r in declared} != {r['id'] for r in result['obligations']}
                or next(r['expectation'] for r in declared if r['id'] == inventory['id'])
                != {'operator': 'matches_adopted_reference',
                    'reference_ref': 'adopted/base_04/feature_inventory.json'}):
            raise MetricRefusal('D10_OBLIGATIONS_UNREGISTERED', 'all three obligations required')
        binding = runner._validate_d10_p0_consumer(project, p0)
        if observed.get('qualification') != 'PASS':
            raise MetricRefusal('TOOL_QUALIFICATION_UNPROVEN', 'current native per-use qualification required')
        subject = d10_adopted_rtl(project)
        inputs = native.source_binding(project, p0['top'], sources.rtl_source_files(project))
        subject['rtl_inputs'] = inputs['files']
        authority, _ = _d10_inventory_authority(project, subject)
        if p0.get('status') != 'PASS':
            raise MetricRefusal('D10_FAILED_ELABORATION_NO_INVENTORY', 'no graph may be borrowed')
        graph_path = _safe_project_file(project, p0['elaboration_path'])
        raw = graph_path.read_bytes()
        if _sha(raw) != p0['elaboration_sha256']:
            raise MetricRefusal('D10_ELABORATION_STALE', str(graph_path))
        measured = _d10_feature_inventory(json.loads(raw), p0['top'])
        identity = {'producer': binding['producer_result'],
                    'tool_execution': {key: binding[key] for key in
                        ('tool_sha256', 'image_id', 'cid', 'attestation_sha256')},
                    'checker': {'source_sha256': _sha(Path(__file__).read_bytes())},
                    'requirements': {key: authority[key] for key in ('path', 'sha256', 'source')},
                    'configuration': observed['qualification_admission'],
                    'consumed_inputs': subject}
        status, detail = evaluate_operator('matches_adopted_reference',
            {'status': 'MEASURED', 'value': measured, 'identity': identity}, authority)
        inventory.update(status=status, reason=detail, observed_value=measured, identity=identity)
        unexpected = sorted(set(measured['blackbox_instances']) - set(authority['reference']['blackbox_instances']))
        blackbox = next(r for r in result['obligations'] if r['id'] == 'base_04.unexpected_blackboxes')
        bb_status, bb_reason = evaluate_operator('eq',
            {'status': 'MEASURED', 'value': len(unexpected), 'unit': 'count', 'identity': identity},
            {'status': 'APPROVED', 'value': 0, 'unit': 'count'})
        blackbox.update(status=bb_status, reason=bb_reason, observed_value=len(unexpected),
                        unexpected_instances=unexpected, identity=identity)
        after = d10_adopted_rtl(project)
        after['rtl_inputs'] = native.source_binding(project, p0['top'], sources.rtl_source_files(project))['files']
        if (after != subject or _d10_inventory_authority(project, after)[0] != authority
                or runner._validate_d10_p0_consumer(project, p0) != binding):
            raise MetricRefusal('D10_INVENTORY_BINDING_STALE', 'consumer inputs changed')
        result['subject'] = subject
    except (MetricRefusal, native.Refusal, flow109.Flow109Error, OSError, ValueError,
            TypeError, KeyError, AttributeError, StopIteration) as exc:
        inventory.update(status='NOT_MEASURED', reason=getattr(exc, 'code', 'D10_INVENTORY_UNPROVEN'), detail=str(exc))
        result['obligations'] = [dict(r) for r in observed.get('obligations', [])] + [inventory]
    states = [r['status'] for r in result['obligations']]
    # A non-scan applicability record is not a DFT-port PASS. The existing
    # source-bound declaration must explicitly justify that non-applicability.
    dft_ok = dft.get('status') == 'PASS' or (dft.get('reason') == 'SCAN_NOT_REQUIRED'
        and (dft.get('intent_binding') or {}).get('intent', {}).get('requires_scan') is False
        and bool(dft.get('skip_reason')))
    result['status'] = ('FAIL' if 'FAIL' in states or dft.get('status') == 'FAIL'
                        else 'PASS' if len(states) == 3 and all(s == 'PASS' for s in states) and dft_ok
                        else 'NOT_MEASURED')
    result['reason'] = ('D10_METRICS_AND_PORTS_PASS' if result['status'] == 'PASS'
                        else 'D10_REQUIRED_CHECK_FAILED' if result['status'] == 'FAIL'
                        else inventory.get('reason', 'D10_DFT_PORT_AUTHORITY_UNPROVEN'))
    result['dft_port_consistency'] = dict(dft)
    return result


# D11 consumes retained native lint through the normal requirement/adoption envelope.
D11_STEPS = ('Verilator.Lint', 'Checker.LintTimingConstructs',
             'Checker.LintErrors', 'Checker.LintWarnings')
D11_IDS = ('base_05.required_lint_violations', 'base_05.source_file_coverage')


def d11_subject(project: Path) -> dict:
    """Current approved original population; never infer coverage from lint output."""
    import _cdc_netlist as native
    import _path_layout as layout
    import _specrtl_common as sources
    import p0_tool_frontend_check as frontend
    project = Path(project).resolve()
    subject = d10_adopted_rtl(project)
    path = _safe_project_file(project, 'reports/flow109/default_rows/D10.json')
    row = json.loads(path.read_bytes())
    if (row.get('step_id') != 'D10' or row.get('completed') is not True
            or row.get('component_status') != 'PASS' or row.get('default_row_status') != 'PASS'):
        raise MetricRefusal('D11_D10_NOT_ACCEPTED', 'current canonical D10 required')
    original = row['evidence']['metric_acceptance']['subject']
    binding = native.source_binding(project, frontend._top(project), sources.rtl_source_files(project))
    subject['rtl_inputs'] = binding['files']
    if original != subject:
        raise MetricRefusal('D11_D10_SUBJECT_STALE', 'D10 and current original inputs differ')
    _d10_inventory_authority(project, subject)
    subject['D10'] = {'path': str(path.relative_to(project)), 'sha256': _sha(path.read_bytes())}
    # Include all support files, even unreferenced headers. A newly added header
    # cannot disappear from the source population because a parser ignored it.
    support = [p for p in layout.rtl_dir(project).rglob('*')
               if p.is_file() and p.suffix.lower() in ('.v', '.sv', '.vh', '.svh', '.h')]
    subject['source_files'] = sorted((_d11_file(project, p) for p in support), key=lambda x: x['path'])
    if not subject['source_files']:
        raise MetricRefusal('D11_SOURCE_POPULATION_EMPTY', 'original sources required')
    return subject


def _d11_file(project: Path, path: Path) -> dict:
    relative = str(path.relative_to(project))
    checked = _safe_project_file(project, relative)
    if not checked.is_file():
        raise MetricRefusal('D11_INPUT_MISSING', relative)
    return {'path': relative, 'sha256': _sha(checked.read_bytes())}


def _d11_reopen(project: Path, reference: Mapping) -> Path:
    return project / _d19_ref(project, reference, 'D11 retained input')['path']


def d11_native_sources() -> dict:
    """Bind native execution and verdict semantics, independent of other owner edits."""
    import ast
    import librelane_contract as contract
    import verilator_lint_gate as lint
    modules = [(contract, ('emit_lint_config', 'run_chain', 'validate_step_receipt')),
               (lint, ('judge', '_native_checker_failure'))]
    result = {}
    for module, names in modules:
        text = Path(module.__file__).read_text()
        nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
        for name in names:
            result[Path(module.__file__).name + ':' + name] = _sha(
                ast.get_source_segment(text, nodes[name]).encode())
    return result


def d11_tool_readset() -> dict:
    import inspect
    import shutil
    import librelane.steps.verilator as verilator
    import librelane.steps.checker as checker
    import librelane.common.toolbox as toolbox
    paths = [Path(inspect.getsourcefile(m)) for m in (verilator, checker, toolbox)]
    for name in ('verilator', 'verilator_bin'):
        path = shutil.which(name)
        if not path:
            raise MetricRefusal('D11_TOOL_ABSENT', name)
        paths.append(Path(path))
    return {str(p): _sha(p.read_bytes()) for p in paths}


def d11_consumed_settings(config: Mapping) -> dict:
    """Use the installed lint reader's actual keys; retain raw config separately.

    Electrical CLOCK_PERIOD/die/placement/STA keys are not read by Lint.run or
    the three metric checkers. Tool-purpose qualification must not bind them.
    MACROS is read by the existing Toolbox macro-view selector. New dynamic
    config reads are unsupported until their native semantics are reviewed.
    """
    import ast
    import inspect
    import textwrap
    from librelane.steps.verilator import Lint
    tree = ast.parse(textwrap.dedent(inspect.getsource(Lint.run)))
    keys = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name) and node.value.value.id == 'self'
                and node.value.attr == 'config'):
            if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
                raise MetricRefusal('D11_SETTINGS_UNMAPPED', 'dynamic native config read')
            keys.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == 'self'
                and node.func.value.attr == 'config'):
            if (node.func.attr != 'get' or not node.args or not isinstance(node.args[0], ast.Constant)
                    or not isinstance(node.args[0].value, str)):
                raise MetricRefusal('D11_SETTINGS_UNMAPPED', 'unknown native config accessor')
            keys.add(node.args[0].value)
    # Explicit subject dimensions are separately checked against every native
    # command and independently required source, never dropped from row identity.
    keys.difference_update(('DESIGN_NAME', 'VERILOG_FILES'))
    keys.add('MACROS')
    return {key: config.get(key) for key in sorted(keys)}


def _d11_native(project: Path, reference: Mapping) -> dict:
    """Reopen exact independently adopted original execution, never reseal found logs."""
    import shlex
    import librelane_contract as contract
    import verilator_lint_gate as lint
    if reference.get('project') != str(project):
        raise MetricRefusal('D11_FOREIGN_EXECUTION', 'original canonical project must match')
    files = reference['artifacts']
    if not isinstance(files, list) or not files or len({r['path'] for r in files}) != len(files):
        raise MetricRefusal('D11_EXECUTION_POPULATION_INVALID', 'complete unique artifact readset required')
    for record in files:
        _d11_reopen(project, record)
    bound = {r['path']: r['sha256'] for r in files}
    def retained(path):
        record = _d11_file(project, path)
        if bound.get(record['path']) != record['sha256']:
            raise MetricRefusal('D11_EXECUTION_UNBOUND', record['path'])
        return path
    original = _d11_reopen(project, reference['owner_report'])
    owner = json.loads(original.read_bytes())
    d09 = json.loads((project / reference['subject']['D09']['path']).read_bytes())
    origin = reference.get('origin', 'D09')
    if origin == 'D09':
        owner_bound = (reference['owner_report']['sha256'] == d09['evidence']['phase2_report']['sha256']
                       and owner.get('runner_binding', {}).get('producer') == d09['evidence']['producer'])
    elif origin == 'D11':
        binding = owner.get('runner_binding', {})
        window = owner.get('declared_window', {})
        owner_bound = (binding.get('schema') == 'vibeic.runner_report_binding.v1'
            and binding.get('project') == str(project) and bool(binding.get('invocation_id'))
            and binding.get('report_name') == 'phase2_one_shot.json'
            and str(window.get('entry_step')) == '2' and str(window.get('exit_step')) == '2')
    else:
        owner_bound = False
    if not owner_bound:
        raise MetricRefusal('D11_ORIGINAL_OWNER_UNBOUND', 'actual normal original D09 or D11 owner required')
    producer = owner['runner_binding']['producer']
    producer_path = Path(producer['path'])
    if (not producer_path.is_relative_to(project) or producer_path.is_symlink()
            or _sha(producer_path.read_bytes()) != producer['sha256']):
        raise MetricRefusal('D11_ORIGINAL_PRODUCER_STALE', 'original producer source must reopen unchanged')
    import ast
    text = producer_path.read_text()
    nodes = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)
             and n.name == 'step_rtl_lint_tool']
    if len(nodes) != 1:
        raise MetricRefusal('D11_ORIGINAL_PRODUCER_UNBOUND', 'one actual original lint producer required')
    producer_function = _sha(ast.get_source_segment(text, nodes[0]).encode())
    rows = [r for r in owner['steps'] if r.get('name') == 'rtl_lint_tool']
    if len(rows) != 1 or rows[0].get('extras', {}).get('mode') != 'librelane':
        raise MetricRefusal('D11_OWNER_SHAPE_INVALID', 'normal typed lint result required')
    row = rows[0]
    if origin == 'D11' and row.get('extras', {}).get('native_fresh') is not True:
        raise MetricRefusal('D11_ORIGINAL_OWNER_UNBOUND', 'a reuse wrapper is not original native execution')
    folder = _safe_project_file(project, reference['lint_dir'])
    checks = {sid: _safe_project_file(project, reference['checker_dirs'][sid]) for sid in D11_STEPS[1:]}
    launch = json.loads(_d11_reopen(project, reference['launch']).read_bytes())
    inspected = launch['container_inspect']
    image = next(i for i in launch['image_inspect'] if i['Id'] == inspected['Image'])
    if (launch['cid'] != inspected['Id'] or inspected['State']['Running'] is not True
            or inspected['Config']['Image'] != launch['image']
            or not _HEX.fullmatch(launch['cid']) or image['Id'] != reference['image_id']):
        raise MetricRefusal('D11_ORIGINAL_LAUNCH_UNBOUND', 'root-adopted host launch required')
    failure = None
    if reference.get('native_failure') is not None:
        recorded = json.loads(_d11_reopen(project, reference['native_failure']).read_bytes())
        failure = recorded.get('native_execution_refusal', recorded.get('normal_chain_refusal'))
    steps = {'Verilator.Lint': folder, **checks}
    for sid, directory in steps.items():
        for path in directory.rglob('*'):
            if path.is_file():
                retained(path)
        if sid != 'Verilator.Lint' and failure is not None and not (directory / 'state_out.json').exists():
            # The native failure reader below validates the actual failed
            # step. Unrun successors owe no successful receipt on a FAIL path.
            continue
        receipt = contract.validate_step_receipt(directory, sid)
        fp = receipt['input']
        loc = fp.get('local_image') or {}
        if (fp.get('image') != launch['image'] or loc.get('cid') != launch['cid']
                or loc.get('image_id') != reference['image_id']):
            raise MetricRefusal('D11_NATIVE_LAUNCH_MISMATCH', sid)
    config = json.loads(retained(folder / 'config.json').read_bytes())
    commands = shlex.split(retained(folder / 'COMMANDS').read_text())
    paths = [Path(name) for name in config['VERILOG_FILES']]
    # The raw full fingerprint stays immutable audit lineage. Reopen only
    # files actually used by lint, not unrelated timing/layout/RC/GDS views.
    consumed = {**d11_consumed_settings(config), 'VERILOG_FILES': config['VERILOG_FILES']}
    fp = contract.validate_step_receipt(folder, 'Verilator.Lint')['input']
    include_dirs = {Path(p) for p in config.get('VERILOG_INCLUDE_DIRS') or []}
    for path in contract._walk_paths(consumed):
        if path in include_dirs:
            if not path.is_dir():
                raise MetricRefusal('D11_NATIVE_INPUT_STALE', str(path))
        elif not path.is_file() or fp.get('config_files', {}).get(str(path)) != _sha(path.read_bytes()):
            raise MetricRefusal('D11_NATIVE_INPUT_STALE', str(path))
    source_hashes = {str(p): _sha(p.read_bytes()) for p in paths}
    if source_hashes != row['extras']['input_sha256']:
        raise MetricRefusal('D11_OWNER_SOURCE_STALE', 'typed lint source hashes differ')
    expected = reference['subject']['source_files']
    rtl = [project / r['path'] for r in expected if Path(r['path']).suffix in ('.v', '.sv')]
    if set(paths) != set(rtl) or not rtl or any(commands.count(str(p)) != 1 for p in paths):
        raise MetricRefusal('D11_SOURCE_FILE_DROPPED', 'all independently required original RTL must be read')
    execution_inputs = contract.validate_step_receipt(folder, 'Verilator.Lint')['input']['config_files']
    for item in expected:
        path = project / item['path']
        if path.suffix in ('.vh', '.svh', '.h') and execution_inputs.get(str(path)) != item['sha256']:
            raise MetricRefusal('D11_HEADER_EXECUTION_UNBOUND', item['path'])
    for name in commands:
        if name.startswith('/') and Path(name).is_file() and Path(name).is_relative_to(project):
            if Path(name) not in paths:
                retained(Path(name))
    report = lint.judge(folder, rtl, checker_dirs=checks, native_failure=failure)
    if row['status'] != report['verdict'] or row['extras']['native_checks'] != report.get('native_checks'):
        raise MetricRefusal('D11_NATIVE_OWNER_MISMATCH', 'normal producer/native checkers disagree')
    values = report.get('tool_metrics', {})
    names = ('design__lint_error__count', 'design__lint_timing_construct__count',
             'design__inferred_latch__count', 'design__lint_warning__count')
    counts = [values.get(n) for n in names]
    if any(type(n) is not int or n < 0 for n in counts) or report['verdict'] not in ('PASS', 'FAIL'):
        raise MetricRefusal('D11_NATIVE_INCOMPLETE', 'full native counters/checkers required')
    policy = {'LINTER_ERROR_ON_LATCH': config.get('LINTER_ERROR_ON_LATCH'),
              'warning_blocking': report.get('native_checks', {}).get('Checker.LintWarnings', {}).get('blocking'),
              'LINTER_DISABLE_WARNINGS': config.get('LINTER_DISABLE_WARNINGS'),
              'LINTER_DISABLE_WARNINGS_BLACKBOX': config.get('LINTER_DISABLE_WARNINGS_BLACKBOX')}
    if (policy['LINTER_ERROR_ON_LATCH'] is not True or
            policy['warning_blocking'] is not None and type(policy['warning_blocking']) is not bool):
        raise MetricRefusal('D11_REQUIRED_CHECK_DISABLED', 'latch check required')
    return {'report': report, 'violations': sum(counts[:3]) + (counts[3] if policy['warning_blocking'] else 0),
            'policy': policy, 'config': config, 'commands': commands, 'launch': launch,
            'source_files': expected, 'producer_function_sha256': producer_function, 'reference': dict(reference)}


def _d11_qualification(project: Path, context: Mapping, native: Mapping) -> dict:
    import flow109_admission as admission
    import librelane_contract as contract
    admitted = admission.require_admission(project, context)
    uses = context['resolved_row']['tool_uses']
    if len(uses) != 1 or uses[0]['tool_id'] != 'verilator' or uses[0]['native_steps'] != list(D11_STEPS):
        raise MetricRefusal('D11_QUALIFICATION_SCOPE_INVALID', 'exact native lint/checker use required')
    registry = json.loads((project / context['qualification_registry']).read_bytes())
    record = next(r for r in registry['uses'] if r['use_id'] == uses[0]['use_id'])
    identity = record['identity']
    cfg = json.loads((project / identity['config']['path']).read_bytes())
    ref = native['reference']
    current = contract.local_image_attestation()
    readset = ref['tool_readset']
    if readset != d11_tool_readset():
        raise MetricRefusal('D11_QUALIFICATION_TOOL_CHANGED', 'complete actual native/tool readset required')
    policy = dict(native['policy'])
    if native.get('report', {}).get('verdict') == 'FAIL' and policy.get('warning_blocking') is None:
        policy['warning_blocking'] = cfg.get('policy', {}).get('warning_blocking')
    if (cfg.get('schema') != 'vibeic.flow109.d11-lint-qualification.v1'
            or cfg.get('purpose') != uses[0]['purpose']
            or cfg.get('native_steps') != list(D11_STEPS)
            or cfg.get('checked_metrics') != list(D11_IDS)
            or cfg.get('native_sources') != d11_native_sources()
            or cfg.get('producer_function_sha256') != native['producer_function_sha256']
            or cfg.get('policy') != policy
            or cfg.get('image_id') != ref['image_id'] or current['image_id'] != ref['image_id']
            or cfg.get('tool_readset') != readset or not readset
            or _sha(Path(identity['executable']['path']).read_bytes()) != identity['build_sha256']):
        raise MetricRefusal('D11_QUALIFICATION_SEMANTICS_MISMATCH', 'actual native use differs from reviewed controls')
    settings = d11_consumed_settings(native['config'])
    if cfg.get('settings') != settings:
        raise MetricRefusal('D11_QUALIFICATION_SETTINGS_MISMATCH', 'full native settings changed')
    for name, sha in readset.items():
        if _sha(Path(name).read_bytes()) != sha:
            raise MetricRefusal('D11_QUALIFICATION_TOOL_CHANGED', name)
    controls = cfg.get('controls')
    if not isinstance(controls, dict) or set(controls) != {'positive', 'required_violation', 'latch', 'timing_construct'}:
        raise MetricRefusal('D11_QUALIFICATION_CONTROLS_MISSING', 'positive/error/latch/timing native controls required')
    references = {r['path']: r['sha256'] for r in record['reference_evidence']}
    for name, reference in controls.items():
        if references.get(reference['path']) != reference['sha256']:
            raise MetricRefusal('D11_QUALIFICATION_CONTROL_UNBOUND', name)
        control = json.loads(_d11_reopen(project, reference).read_bytes())
        if (control.get('purpose') != uses[0]['purpose'] or control.get('image_id') != ref['image_id']
                or control.get('native_sources') != cfg['native_sources']
                or control.get('policy') != cfg['policy']
                or control.get('tool_readset') != readset
                or control.get('status') != ('PASS' if name == 'positive' else 'FAIL')
                or type(control.get('required_lint_violations')) is not int
                or (control['required_lint_violations'] != 0 if name == 'positive'
                    else control['required_lint_violations'] <= 0)):
            raise MetricRefusal('D11_QUALIFICATION_CONTROL_INVALID', name)
        if name in ('latch', 'timing_construct'):
            key = ('design__inferred_latch__count' if name == 'latch'
                   else 'design__lint_timing_construct__count')
            counter = control.get('native_metrics', {}).get(key)
            if type(counter) is not int or counter <= 0:
                raise MetricRefusal('D11_QUALIFICATION_CONTROL_INVALID', name + ': no native finding')
        artifacts = control.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts:
            raise MetricRefusal('D11_QUALIFICATION_CONTROL_UNBOUND', name)
        for item in artifacts:
            _d11_reopen(project, item)
    if admission.require_admission(project, context) != admitted:
        raise MetricRefusal('D11_QUALIFICATION_CHANGED', 'per-use evidence changed during consumption')
    return admitted


def _d11_required_population(items, subject) -> bool:
    """Coverage is a complete unique set, not an incidental JSON list order."""
    expected = subject['source_files']
    return (isinstance(items, list) and len(items) == len(expected)
            and {_json_key(item) for item in items} == {_json_key(item) for item in expected})


def d11_fresh_request(project: Path, context: Mapping) -> bool:
    """Only explicit normal root source authority may request a new D11 run."""
    project = Path(project).resolve()
    try:
        authority, body = _approved_authority(project,
            'requirements/base_05/source_file_coverage.json#/required_items', ('path', 'sha256'))
        source = json.loads((project / authority['source']['path']).read_bytes())
        subject = d11_subject(project)
        request = source.get('native_run')
        if request is None:
            return False
        registry = _d11_file(project, project / context['qualification_registry'])
        return (source.get('source_file_coverage') == {'required_items': body['required_items'], 'subject': subject}
            and _d11_required_population(body['required_items'], subject)
            and request == {'purpose': 'D11.default', 'subject': subject, 'qualification_registry': registry})
    except (MetricRefusal, OSError, ValueError, TypeError, KeyError):
        return False


def d11_fresh_admission(project: Path, context: Mapping, config: Mapping, checker_configs: Mapping) -> dict:
    """Qualification/config admission only; this is not an execution or metric."""
    import inspect
    import design_one_shot_runner as design
    import librelane_contract as contract
    if not d11_fresh_request(project, context):
        raise MetricRefusal('D11_FRESH_RUN_NOT_AUTHORIZED', 'normal source request required')
    policy = {'LINTER_ERROR_ON_LATCH': config.get('LINTER_ERROR_ON_LATCH'),
        'warning_blocking': checker_configs['Checker.LintWarnings'].get('ERROR_ON_LINTER_WARNINGS', False),
        'LINTER_DISABLE_WARNINGS': config.get('LINTER_DISABLE_WARNINGS'),
        'LINTER_DISABLE_WARNINGS_BLACKBOX': config.get('LINTER_DISABLE_WARNINGS_BLACKBOX')}
    if (policy['LINTER_ERROR_ON_LATCH'] is not True
            or checker_configs['Checker.LintErrors'].get('ERROR_ON_LINTER_ERRORS', True) is not True
            or checker_configs['Checker.LintTimingConstructs'].get('ERROR_ON_LINTER_TIMING_CONSTRUCTS', True) is not True):
        raise MetricRefusal('D11_REQUIRED_CHECK_DISABLED', 'native checkers must remain enabled')
    prepared = {'reference': {'image_id': contract.local_image_attestation()['image_id'],
                             'tool_readset': d11_tool_readset()},
                'producer_function_sha256': _sha(inspect.getsource(design.step_rtl_lint_tool).rstrip().encode()),
                'config': dict(config), 'policy': policy}
    authority, _ = _approved_authority(project,
        'requirements/base_05/source_file_coverage.json#/required_items', ('path', 'sha256'))
    return {'status': 'PASS', 'scope': 'QUALIFICATION_AND_LAUNCH_ADMISSION_ONLY',
            'source_authority': authority, 'subject': d11_subject(project),
            'qualification': _d11_qualification(project, context, prepared)}


def d11_current_execution(project: Path, context: Mapping, report: Mapping,
                          invocation: Mapping, *, published_current: bool,
                          report_path: Path | None = None) -> dict | None:
    """Bind this real normal owner invocation; never backfill a historical report."""
    import benchmark_dispatch as dispatch
    import flow109
    import os
    project = Path(project).resolve()
    try:
        path = flow109._bound_attempt(project, context,
            os.environ.get(flow109.ATTEMPT_ENV)) / 'phase2_one_shot.json'
        if report_path is not None and Path(report_path) != path:
            return None
        binding = report['runner_binding']
        rows = [r for r in report['steps'] if r.get('name') == 'rtl_lint_tool']
        if (published_current is not True or path.is_symlink() or json.loads(path.read_bytes()) != report
                or set(invocation) != {'invocation_id', 'argv', 'project', 'source'}
                or invocation['project'] != str(project) or not invocation['invocation_id']
                or any(binding[k] != invocation[k] for k in invocation)
                or binding['schema'] != 'vibeic.runner_report_binding.v1'
                or binding['report_name'] != 'phase2_one_shot.json'
                or binding['source'] != dispatch._runner_source_snapshot(
                    binding['argv'], consumer=binding['source']['consumer']['path'])
                or binding['material'] != dispatch._runner_material_snapshot(project)
                or len(rows) != 1 or rows[0]['status'] not in ('PASS', 'FAIL')
                or rows[0]['extras'].get('native_fresh') is not True
                or rows[0]['extras']['context_sha256'] != context['context_sha256']):
            return None
        execution = dict(rows[0]['extras']['native_lint_execution'])
        if execution['subject'] != d11_subject(project) or execution['origin'] != 'D11':
            return None
        execution['owner_report'] = _d11_file(project, path)
        return execution
    except (flow109.Flow109Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def d11_capture_execution(project: Path, context: Mapping, native_base: Path,
                          admission: Mapping, failure_path: Path | None = None) -> dict:
    """Capture this actual producer run; no approval or synthetic success artifact."""
    import librelane_contract as contract
    project = Path(project).resolve()
    if admission['subject'] != d11_subject(project):
        raise MetricRefusal('D11_INPUT_CHANGED', 'original source changed during native execution')
    launch = contract.local_image_attestation()
    original = native_base / 'original-native-launch.json'
    # Preserve the actual host attestation bytes, including its original CID.
    original.write_bytes(Path(launch['attestation_path']).read_bytes())
    directories = {sid: native_base / (f'{i:02d}-' + sid.lower().replace('.', '-'))
                   for i, sid in enumerate(D11_STEPS, 1)}
    result = {'origin': 'D11', 'project': str(project), 'subject': admission['subject'],
        'lint_dir': str(directories['Verilator.Lint'].relative_to(project)),
        'checker_dirs': {sid: str(directory.relative_to(project)) for sid, directory in directories.items()
                         if sid != 'Verilator.Lint'},
        'artifacts': [_d11_file(project, path) for path in sorted(native_base.rglob('*')) if path.is_file()],
        'launch': _d11_file(project, original), 'image_id': launch['image_id'],
        'tool_readset': d11_tool_readset(), 'admission': dict(admission)}
    if failure_path is not None:
        result['native_failure'] = _d11_file(project, failure_path)
    return result


def accept_d11(project: Path, context: Mapping[str, Any], *, current_execution: Mapping | None = None) -> dict:
    """BLOCKING D11: qualified native failure wins; every PASS obligation must be current."""
    import flow109
    import flow109_admission as admission
    import librelane_contract as contract
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D11', 'status': 'NOT_MEASURED',
              'component_status': 'NOT_MEASURED', 'delivery_blocked': True,
              'obligations': [{'id': oid, 'status': 'NOT_MEASURED'} for oid in D11_IDS]}
    try:
        current = flow109.validate_execution_context(context)
        obligations = current['resolved_row']['obligations']
        if (current['resolved_row']['id'] != 'D11' or [r['id'] for r in obligations] != list(D11_IDS)
                or obligations[0]['expectation']['operator'] != 'eq'
                or obligations[0]['expectation']['value'] != 0
                or obligations[1]['expectation'].get('required_set_ref')
                    != 'requirements/base_05/source_file_coverage.json#/required_items'):
            raise MetricRefusal('D11_OBLIGATIONS_UNREGISTERED', 'exact two normal obligations required')
        subject = d11_subject(project)
        if current_execution is None:
            adopted, body = _approved_document(project, 'adopted/base_05/lint_execution.json',
                authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')
            source = json.loads((project / adopted['source']['path']).read_bytes())
            if (not adopted['source']['path'].startswith('input/')
                    or source.get('lint_execution') != {k: body[k] for k in ('reference', 'reference_identity')}
                    or body['reference']['subject'] != subject):
                raise MetricRefusal('D11_EXECUTION_AUTHORITY_STALE', 'independent original execution/subject required')
            _identity_complete(body['reference_identity'])
            if body['reference_identity']['consumed_inputs'] != subject:
                raise MetricRefusal('D11_EXECUTION_AUTHORITY_STALE', 'adopted identity differs')
        else:
            admission_record = current_execution['admission']
            source_ref = admission_record['source_authority']['source']
            source = json.loads(_d11_reopen(project, source_ref).read_bytes())
            expected_request = {'purpose': 'D11.default', 'subject': subject,
                'qualification_registry': _d11_file(project, project / current['qualification_registry'])}
            if (admission_record.get('status') != 'PASS' or admission_record.get('subject') != subject
                    or not source_ref['path'].startswith('input/')
                    or source.get('native_run') != expected_request
                    or set(source.get('source_file_coverage', {})) != {'subject', 'required_items'}
                    or source['source_file_coverage']['subject'] != subject
                    or not _d11_required_population(source['source_file_coverage']['required_items'], subject)
                    or current_execution.get('subject') != subject):
                raise MetricRefusal('D11_FRESH_EXECUTION_UNBOUND', 'normal source request/current owner required')
            body = {'reference': dict(current_execution)}
            adopted = {'kind': 'CURRENT_NORMAL_OWNER_EXECUTION', 'owner_report': current_execution['owner_report']}
        native = _d11_native(project, body['reference'])
        result['native_observation'] = native['report']
        result['component_status'] = native['report']['verdict']
        try:
            qualified = _d11_qualification(project, current, native)
        except (admission.AdmissionRefusal, MetricRefusal, OSError, ValueError, TypeError, KeyError) as exc:
            # An unqualified observation is retained, never a row FAIL/PASS.
            result['component_status'] = 'NOT_MEASURED'
            raise MetricRefusal('D11_TOOL_QUALIFICATION_UNPROVEN', str(exc)) from exc
        identity = {'producer': adopted, 'checker': {'native_sources': d11_native_sources(),
                    'consumer_sha256': _sha(Path(__file__).read_bytes())},
                    'tool_execution': {'original_launch': body['reference']['launch'], 'qualification': qualified},
                    'consumed_inputs': subject, 'requirements': obligations[0]['expectation'],
                    'configuration': {'resolved_config': _d11_file(project,
                        project / body['reference']['lint_dir'] / 'config.json'),
                        'consumed_settings_sha256': _sha(_json_key(d11_consumed_settings(native['config'])).encode()),
                        'native_policy_sha256': _sha(_json_key(native['policy']).encode())}}
        first = result['obligations'][0]
        status, detail = evaluate_operator('eq', {'status': 'MEASURED', 'value': native['violations'],
            'unit': 'count', 'identity': identity}, {'status': 'APPROVED', 'value': 0, 'unit': 'count'})
        first.update(status=status, reason=detail, observed_value=native['violations'], identity=identity)
        try:
            authority, req = _approved_authority(project,
                'requirements/base_05/source_file_coverage.json#/required_items', ('path', 'sha256'))
            original = json.loads((project / authority['source']['path']).read_bytes())
            if (not authority['source']['path'].startswith('input/')
                    or original.get('source_file_coverage') != {'required_items': req['required_items'], 'subject': subject}
                    or not _d11_required_population(req['required_items'], subject)):
                raise MetricRefusal('D11_SOURCE_REQUIREMENTS_STALE', 'independent complete source population required')
            for item in req['required_items']:
                _d11_reopen(project, item)
            status, detail = evaluate_operator('covers_all', {'status': 'MEASURED',
                'value': native['source_files'], 'identity': {**identity, 'requirements': authority}}, authority)
            result['obligations'][1].update(status=status, reason=detail, observed_value=native['source_files'])
        except (MetricRefusal, OSError, ValueError, TypeError, KeyError) as exc:
            result['obligations'][1].update(reason=getattr(exc, 'code', 'D11_COVERAGE_UNPROVEN'), detail=str(exc))
        if (d11_subject(project) != subject
                or (current_execution is None and _approved_document(project, 'adopted/base_05/lint_execution.json',
                    authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')[0] != adopted)
                or _d11_native(project, body['reference']) != native
                or _d11_qualification(project, current, native) != qualified):
            raise MetricRefusal('D11_INPUT_CHANGED', 'consumer inputs changed during acceptance')
        result['subject'] = subject
    except (MetricRefusal, admission.AdmissionRefusal, flow109.Flow109Error, contract.Refusal,
            OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        if 'subject' not in result and any(r['status'] == 'PASS' for r in result['obligations']):
            # Coverage refusal is handled independently above. A later changed
            # native/authority/launch read invalidates this whole observation.
            if getattr(exc, 'code', '') == 'D11_INPUT_CHANGED':
                for item in result['obligations']:
                    item['status'] = 'NOT_MEASURED'
                result['component_status'] = 'NOT_MEASURED'
        result['reason'] = getattr(exc, 'code', 'D11_EVIDENCE_UNPROVEN')
        result['detail'] = str(exc)
    states = [r['status'] for r in result['obligations']]
    result['status'] = ('FAIL' if 'FAIL' in states else 'PASS' if states == ['PASS', 'PASS']
                        and 'subject' in result else 'NOT_MEASURED')
    result.setdefault('reason', 'D11_METRICS_PASS' if result['status'] == 'PASS'
                       else 'D11_REQUIRED_LINT_FAILED' if result['status'] == 'FAIL' else 'D11_COVERAGE_UNPROVEN')
    return result


D12_PURPOSE = 'D12.default.complete_current_early_rtl'
D12_STEPS = ('CDC.RegCrossing', 'CDC.AsyncInput', 'RDC.ResetDependency')
D12_IDS = ('base_06.clock_reset_crossing_census', 'base_06.unresolved_crossings',
           'base_06.cdc_protocol_results')
D12_FIELDS = ('kind', 'name', 'clock', 'detail')


def d12_model_sources() -> dict:
    """The existing decoded model/rule and role consumers, not a new engine."""
    return {name: _sha((HERE / name).read_bytes()) for name in (
        '_cdc_netlist.py', 'ai_signed_judgement.py', 'instrument_calibration.py',
        '_hdl_code_text.py', 'rtl_final_bundle_integrity.py')}


def d12_subject(project: Path) -> dict:
    import _cdc_netlist as native
    project = Path(project).resolve()
    path = _safe_project_file(project, native.NETLIST_REL)
    nl = native.load(path)
    binding = native.require_binding(project, path, nl)
    role_path = _safe_project_file(project, 'reports/audit/ai_judgements/3.json')
    roles = ({'path': role_path.relative_to(project).as_posix(), 'sha256': _sha(role_path.read_bytes())}
             if native.reset_role_candidates(nl) else {'status': 'NO_INTRINSIC_ROLE_CANDIDATES'})
    return {'input': binding['input'], 'graph': {'path': native.NETLIST_REL,
            'sha256': _sha(path.read_bytes())}, 'roles': roles}


def _d12_source(project: Path, name: str, fields: tuple) -> tuple[dict, dict, dict]:
    authority, body = _approved_authority(project,
        'requirements/base_06/' + name + '.json#/required_items', fields)
    source = json.loads(_safe_project_file(project, authority['source']['path']).read_bytes())
    payload = {k: v for k, v in body.items() if k not in ('schema', 'approval')}
    if isinstance(payload.get('validated_absence'), dict):
        absence = dict(payload['validated_absence'])
        if absence.pop('source_reference', None) != authority['source']:
            raise MetricRefusal('D12_ABSENCE_AUTHORITY_MISMATCH', name)
        payload['validated_absence'] = absence
    if (not authority['source']['path'].startswith('input/')
            or source.get('purpose') != D12_PURPOSE or source.get(name) != payload):
        raise MetricRefusal('D12_AUTHORITY_PAYLOAD_MISMATCH', name)
    if len({_json_key(x) for x in body['required_items']}) != len(body['required_items']):
        raise MetricRefusal('D12_REQUIREMENT_DUPLICATE', name)
    return authority, body, source


def _d12_observe(project: Path, source: Mapping) -> dict:
    """Reopen the original native graph; run existing structural readers only."""
    import _cdc_netlist as native
    import ai_signed_judgement as expert
    subject = d12_subject(project)
    path = project / native.NETLIST_REL
    document = json.loads(path.read_bytes())
    nl = native.load(path)
    # Only explicitly supported combinational primitives may stand between
    # decoded state. A dollar-prefixed unknown is not evidence of no storage.
    combinational = {'$and', '$or', '$xor', '$xnor', '$not', '$logic_not', '$logic_and',
        '$logic_or', '$mux', '$pmux', '$buf', '$pos', '$add', '$sub', '$mul', '$neg',
        '$eq', '$ne', '$eqx', '$nex', '$lt', '$le', '$gt', '$ge', '$shl', '$shr',
        '$sshl', '$sshr', '$shift', '$shiftx', '$slice', '$concat', '$reduce_and',
        '$reduce_or', '$reduce_xor', '$reduce_xnor', '$reduce_bool', '$_BUF_', '$_NOT_',
        '$_AND_', '$_OR_', '$_XOR_', '$_XNOR_', '$_MUX_'}
    decoded = {f.name for f in nl.flops}
    if (not decoded or nl.memories or nl.ambiguous_drivers
            or any(n not in decoded and c['type'] not in combinational for n, c in nl.cells.items())
            or any(len(f.d) != len(f.q) or not f.q or len(set(f.q)) != len(f.q) for f in nl.flops)):
        raise MetricRefusal('D12_GRAPH_INCOMPLETE', 'unknown/ambiguous/zero/unsupported sequential population')
    q_of = nl.flop_of_q()
    if len(q_of) != sum(len(f.q) for f in nl.flops):
        raise MetricRefusal('D12_GRAPH_INCOMPLETE', 'duplicate state driver')
    input_bits = {b for _n, (d, bits) in nl.ports.items() if d in ('input', 'inout') for b in bits}
    if (input_bits.intersection(nl.drivers) or any(not cell.get('port_directions')
            or any(isinstance(b, int) and b not in input_bits and b not in nl.drivers
                   for pin, bits in cell['connections'].items()
                   if cell['port_directions'].get(pin) == 'input' for b in bits)
            for cell in nl.cells.values())):
        raise MetricRefusal('D12_GRAPH_INCOMPLETE', 'undriven or ambiguous input cone')
    roles, why = expert.reset_roles(project, nl, path) if native.reset_role_candidates(nl) else ({}, 'native pins')
    domains = source.get('input_domains')
    inputs = {n for n, (direction, _bits) in nl.ports.items() if direction in ('input', 'inout')}
    if (not isinstance(domains, dict) or set(domains) != inputs
            or any(not isinstance(v, dict) or set(v) != {'role', 'clock'}
                   or v['role'] not in ('clock', 'synchronous_data', 'synchronous_reset',
                                        'asynchronous_data', 'inactive')
                   or not isinstance(v['clock'], str) for v in domains.values())):
        raise MetricRefusal('D12_INPUT_DOMAINS_INCOMPLETE', 'every actual input needs independent role/clock')
    population, reset_analysis = {}, {}
    findings = native.judge(nl, 'reg_crossing', metadata=population)
    findings += native.judge(nl, 'async_input', lambda n: domains[n]['role'] == 'asynchronous_data')
    findings += native.judge(nl, 'reset_dependency', metadata=reset_analysis, reset_roles=roles)
    if (population.get('traversal_complete') is not True
            or population.get('source_q_bits_examined') != len(q_of)
            or population.get('destination_d_bits') != sum(len(f.d) for f in nl.flops)
            ):
        raise MetricRefusal('D12_TRAVERSAL_INCOMPLETE', 'complete crossing/reset population required')
    lookup = native._LookupSnapshot(nl)
    for name, declaration in domains.items():
        _direction, bits = nl.ports[name]
        consumers = [f for bit in bits for f, _i, _direct in native._consumers(nl, bit, lookup)]
        loads = [(cell, pin) for cell in nl.cells.values() for pin, conn in cell['connections'].items()
                 if cell.get('port_directions', {}).get(pin) == 'input' and set(bits).intersection(conn)]
        role, clock = declaration['role'], declaration['clock']
        if role == 'inactive' and (loads or clock != 'none'):
            raise MetricRefusal('D12_INACTIVE_INPUT_LOADED', name)
        if role in ('synchronous_data', 'synchronous_reset') and (
                clock not in native.clock_domains(nl) or any(nl.domain(f) != clock for f in consumers)):
            findings.append({'rule': 'D12_INPUT_DOMAIN_MISMATCH', 'severity': 'ERROR', 'port': name})
        if role == 'clock' and (clock != name or name not in native.clock_domains(nl)):
            raise MetricRefusal('D12_CLOCK_ROLE_MISMATCH', name)
    return {'subject': subject, 'producer': native.require_binding(project, path, nl)['producer'],
            'population': population, 'reset_analysis': reset_analysis, 'findings': findings,
            'roles': roles, 'role_detail': why, 'input_domains': domains}


def _d12_census(project: Path, source: Mapping, observed: Mapping) -> list:
    import _cdc_netlist as native
    from _hdl_code_text import strip_hdl_comments_and_strings
    from rtl_final_bundle_integrity import module_blocks
    nl = native.load(project / native.NETLIST_REL)
    if observed['reset_analysis'].get('cycle_detection_complete') is not True:
        raise MetricRefusal('D12_ROLES_UNPROVEN', observed['role_detail'])
    mod = json.loads((project / native.NETLIST_REL).read_bytes())['modules'][nl.top]
    aliases = dict(mod['netnames'])
    bodies = [body for name, body in module_blocks('\n'.join(
        strip_hdl_comments_and_strings((project / name).read_text())
        for name in observed['subject']['input']['rtl_files'])) if name == nl.top]
    for state, net in source.get('state_aliases', {}).items():
        if (state in aliases or not _SAFE.fullmatch(state) or not _SAFE.fullmatch(net)
                or len(bodies) != 1 or net not in aliases
                or not re.search(r'\bassign\s+' + re.escape(net) + r'\s*=\s*'
                                 + re.escape(state) + r'\s*;', bodies[0])):
            raise MetricRefusal('D12_STATE_ALIAS_UNPROVEN', state)
        aliases[state] = aliases[net]
    q_of = nl.flop_of_q()
    required = source['clock_reset_crossing_census']['required_items']
    actual, covered, ports, clocks, resets = [], set(), set(), set(), set()
    for item in required:
        kind, name, clock, detail = (item[k] for k in D12_FIELDS)
        valid = False
        if kind == 'state':
            bits = aliases.get(name, {}).get('bits', [])
            valid = bool(bits) and not covered.intersection(bits) and detail == str(len(bits)) and all(
                b in q_of and nl.domain(q_of[b]) == clock for b in bits)
            if valid:
                covered.update(bits)
        elif kind == 'clock':
            fs = [f for f in nl.flops if nl.domain(f) == name]
            valid = bool(fs) and clock == name and all(
                detail == ('rising' if nl.sample_edge(f) else 'falling') for f in fs)
            valid = valid and observed['input_domains'].get(name) == {'role': 'clock', 'clock': clock}
            if valid:
                clocks.add(name); ports.add(name)
        elif kind == 'reset':
            fs = [f for f in nl.flops if nl.domain(f) == clock]
            def matches(f):
                r = f.arst if f.arst is not None else f.srst
                if r is None or nl.bit_label(nl.root(r)) != name:
                    return False
                if f.arst is not None:
                    return detail == ('asynchronous_active_high' if f.arst_pol else 'asynchronous_active_low')
                if f.srst_origin == 'd_mux_candidate':
                    # Only the current signed semantic reset role admits this mux.
                    cell = nl.cells[nl.drivers[f.d[0]][0]]
                    polarity = all(b == '0' for b in cell['connections']['B'])
                    other_zero = all(b == '0' for b in cell['connections']['A'])
                    return (observed['roles'].get(f.name) == 'synchronous_reset'
                            and (polarity or other_zero) and detail == (
                                'synchronous_active_high' if polarity else 'synchronous_active_low'))
                polarity = native._int(nl.cells[f.name].get('parameters', {}).get('SRST_POLARITY', 1))
                return detail == ('synchronous_active_high' if polarity else 'synchronous_active_low')
            valid = (bool(fs) and all(matches(f) for f in fs)
                     and observed['input_domains'].get(name) == {'role': 'synchronous_reset', 'clock': clock})
            if valid:
                resets.add(name); ports.add(name)
        elif kind == 'input':
            valid = observed['input_domains'].get(name) == {'role': detail, 'clock': clock}
            if valid:
                ports.add(name)
        elif kind == 'output' and name in nl.ports and nl.ports[name][0] == 'output':
            bits = nl.ports[name][1]
            valid = detail == 'registered' and all(b in q_of and nl.domain(q_of[b]) == clock for b in bits)
            if valid:
                ports.add(name)
        if not valid:
            raise MetricRefusal('D12_CENSUS_MAPPING_UNPROVEN', _json_key(item))
        actual.append(dict(item))
    actual_resets = {nl.bit_label(nl.root(r)) for f in nl.flops for r in (f.arst, f.srst)
                     if r is not None and (f.arst is not None or f.srst_origin == 'native_pin'
                         or observed['roles'].get(f.name) == 'synchronous_reset')}
    if (covered != set(q_of) or ports != set(nl.ports)
            or clocks != set(native.clock_domains(nl)) or resets != actual_resets):
        raise MetricRefusal('D12_CENSUS_INCOMPLETE', 'all native state/ports/clocks/resets must be accounted for')
    return actual


def accept_d12(project: Path, context: Mapping[str, Any]) -> dict:
    """Read the current graph and signed roles against the original requirements."""
    import _cdc_netlist as native
    import flow109
    import flow109_admission as admission
    import instrument_calibration
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D12', 'status': 'NOT_MEASURED',
              'qualification': 'NOT_MEASURED', 'component_status': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': [{'id': k, 'status': 'NOT_MEASURED'} for k in D12_IDS]}
    try:
        current = flow109.validate_execution_context(context)
        rows = current['resolved_row']['obligations']
        if (current['resolved_row']['id'] != 'D12' or [r['id'] for r in rows] != list(D12_IDS)
                or rows[1]['expectation']['operator'] != 'eq' or rows[1]['expectation']['value'] != 0
                or rows[1]['expectation']['unit'] != 'count'
                or any(rows[i]['expectation'].get('required_set_ref') != 'requirements/base_06/'
                    + D12_IDS[i].split('.')[1] + '.json#/required_items' for i in (0, 2))):
            raise MetricRefusal('D12_OBLIGATIONS_UNREGISTERED', 'existing three contracts only')
        try:
            _authority, _body, source = _d12_source(project, 'clock_reset_crossing_census', D12_FIELDS)
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError):
            # Either independently approved normal document may bind the
            # shared original source. Missing census coverage cannot erase a
            # qualified blocking reset/crossing observation.
            _authority, _body, source = _d12_source(project, 'cdc_protocol_results',
                                                  ('name', 'from_clock', 'to_clock'))
        observed = _d12_observe(project, source)
        result.update(observed=observed)
        failures = [f for f in observed['findings'] if f.get('rule') != 'RESET_ROLE_UNRESOLVED']
        result['obligations'][1].update(status='FAIL' if failures else 'PASS'
            if observed['reset_analysis'].get('cycle_detection_complete') is True else 'NOT_MEASURED', observed_value=len(failures),
                                         unit='count', findings=failures)
        result['component_status'] = result['obligations'][1]['status']
        try:
            authority, _body, census_source = _d12_source(project, 'clock_reset_crossing_census', D12_FIELDS)
            if census_source != source:
                raise MetricRefusal('D12_AUTHORITY_SUBJECT_MISMATCH', 'census source differs')
            census = _d12_census(project, source, observed)
            result['obligations'][0].update(status='PASS',
                reason='complete native census matches the original required population', observed_value=census)
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            result['obligations'][0].update(reason=getattr(exc, 'code', 'D12_CENSUS_UNPROVEN'), detail=str(exc))
        try:
            proto_auth, proto, proto_source = _d12_source(project, 'cdc_protocol_results',
                                                        ('name', 'from_clock', 'to_clock'))
            if (proto_source != source or proto['required_items'] or len(observed['population']['clock_domains']) != 1
                    or observed['population']['crossings'] or any(
                        v['role'] == 'asynchronous_data' for v in observed['input_domains'].values())):
                raise MetricRefusal('D12_PROTOCOL_PROOF_REQUIRED', 'nonempty/active CDC protocol needs native purpose proof')
            result['obligations'][2].update(status='PASS', observed_value=[], authority=proto_auth)
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            result['obligations'][2].update(reason=getattr(exc, 'code', 'D12_PROTOCOL_UNPROVEN'), detail=str(exc))
        for row in result['obligations']:
            if row['status'] == 'PASS' and row['id'] != D12_IDS[1]:
                name = row['id'].split('.')[1]
                fields = D12_FIELDS if name == 'clock_reset_crossing_census' else ('name', 'from_clock', 'to_clock')
                fresh_auth, _fresh_body, fresh_source = _d12_source(project, name, fields)
                expected_auth = authority if name == 'clock_reset_crossing_census' else proto_auth
                if fresh_source != source or fresh_auth != expected_auth:
                    raise MetricRefusal('D12_INPUT_CHANGED', 'requirement changed during consumption')
        if _d12_observe(project, source) != observed:
            raise MetricRefusal('D12_INPUT_CHANGED', 'source/model/native/authority changed during consumption')
        result['subject'] = observed['subject']
    except (MetricRefusal, native.Refusal, admission.AdmissionRefusal, flow109.Flow109Error,
            instrument_calibration.Uncalibrated,
            OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D12_EVIDENCE_UNPROVEN'), detail=str(exc))
        # Changed currentness invalidates every previously observed conclusion.
        for row in result['obligations']:
            row['status'] = 'NOT_MEASURED'
        result['component_status'] = 'NOT_MEASURED'
    states = [r['status'] for r in result['obligations']]
    result['status'] = 'FAIL' if 'FAIL' in states else ('PASS' if states == ['PASS'] * 3 else 'NOT_MEASURED')
    result['delivery_blocked'] = result['status'] != 'PASS'
    result.setdefault('reason', 'D12_' + result['status'])
    return result


D13_PURPOSE = 'D13.default.retained_early_rtl'
D13_TOOL_STEPS = {
    'verilator': ['Verilator.BinaryScenario', 'Verilator.CoverageSimulation'],
    'iverilog': ['Icarus.CocotbCompile'],
    'vvp': ['Icarus.CocotbRuntime'],
    'python3': ['Cocotb.ArithmeticRandom', 'D13.RetainedReaders'],
    'verilator_coverage': ['VerilatorCoverage.LcovUnion'],
}
D13_IDS = ('base_07.required_function_scenarios', 'base_07.assertion_failures',
           'base_07.coverage_targets')


def d13_model_sources() -> dict:
    import importlib
    return {name: _sha(Path(importlib.import_module(name[:-3]).__file__).read_bytes()) for name in (
        '_l10_execution.py', '_sim_results_bridge.py', 'arith_oracle_tb_gen.py',
        'professional_tb_gen.py', 'verilator_coverage_measure.py',
        'l10_tb_conformance_check.py', 'testbench_gen.py', 'coverage_closure.py')}


def _d13_qualification(project: Path, context: Mapping) -> dict:
    import flow109_admission as admission
    admitted = admission.require_admission(project, context)
    uses = context['runtime_tool_uses']
    if len(uses) != len(D13_TOOL_STEPS) or {u['tool_id'] for u in uses} != set(D13_TOOL_STEPS):
        raise MetricRefusal('D13_QUALIFICATION_SCOPE_INVALID', 'actual required simulation/reader/projection uses')
    for use in uses:
        tool = use['tool_id']
        if use['semantics'] != {'purpose': 'D13.default', 'native_steps': D13_TOOL_STEPS[tool]}:
            raise MetricRefusal('D13_QUALIFICATION_SCOPE_INVALID', tool)
        config = json.loads((project / use['config']['path']).read_bytes())
        if config != {'purpose': D13_PURPOSE, 'tool_id': tool,
                      'native_steps': D13_TOOL_STEPS[tool], 'model_sources': d13_model_sources()}:
            raise MetricRefusal('D13_MODEL_QUALIFICATION_STALE', tool)
    return admitted


def d13_subject(project: Path) -> dict:
    """Reuse complete accepted D09/D10 source identity; do not require D11 execution here."""
    project = Path(project).resolve()
    return {'rtl': d11_subject(project),
            'declaration': _d11_file(project, project / 'plugin_output/declaration.json'),
            'documents': [_d11_file(project, project / ('phase1/generated_docs/' + name))
                          for name in ('L10_TEST_CASES.json', 'L22_VERIFICATION_PLAN.json')]}


def _d13_authority(project: Path, name: str) -> tuple[dict, dict, dict]:
    relative = 'requirements/base_07/' + name + '.json'
    if name == 'required_function_scenarios':
        authority, body = _approved_authority(project, relative + '#/required_items', ('name',))
    else:
        authority, body = _approved_document(project, relative,
            authority='requirements_owner', schema=AUTHORITY_SCHEMA)
    source = json.loads(_safe_project_file(project, authority['source']['path']).read_bytes())
    if (not authority['source']['path'].startswith('input/') or source.get('purpose') != D13_PURPOSE
            or {k: v for k, v in body.items() if k not in ('schema', 'approval')} != source.get(name)):
        raise MetricRefusal('D13_AUTHORITY_PAYLOAD_MISMATCH', name)
    return authority, body, source


def _d13_file(project: Path, record: Mapping, *, external: bool = False) -> Path:
    if not isinstance(record, Mapping) or set(record) != {'path', 'sha256'}:
        raise MetricRefusal('D13_REFERENCE_INVALID', str(record))
    value = record['path']
    if not isinstance(value, str) or not _HEX.fullmatch(str(record['sha256'])):
        raise MetricRefusal('D13_REFERENCE_INVALID', str(record))
    path = Path(value)
    if not path.is_absolute():
        path = _safe_project_file(project, value)
    elif not external:
        try:
            path = _safe_project_file(project, path.relative_to(project).as_posix())
        except ValueError as exc:
            raise MetricRefusal('D13_FOREIGN_ACTUAL_INPUT', value) from exc
    if not path.is_file() or _sha(path.read_bytes()) != record['sha256']:
        raise MetricRefusal('D13_INPUT_STALE', value)
    return path


def _d13_retained(project: Path, execution: Mapping, path: Path) -> Path:
    """Only actual same-project design inputs may feed a measurement."""
    try:
        relative = path.relative_to(project).as_posix()
    except ValueError as exc:
        raise MetricRefusal('D13_FOREIGN_ACTUAL_INPUT', str(path)) from exc
    matches = [r for r in execution['artifacts'] if r['path'] == relative]
    if len(matches) != 1:
        raise MetricRefusal('D13_EXECUTION_INPUT_UNBOUND', relative)
    return _d13_file(project, matches[0])


def _d13_retained_component_owner(project: Path, reference: Mapping, owner: Mapping) -> None:
    """Reopen a real interrupted collector, without recasting its parent as PASS.

    Only an independently approved execution reference selects this origin.
    Functional/coverage verdicts and tool qualification remain the normal D13
    consumers' responsibility; a collector snapshot alone grants no row credit.
    """
    def refuse(detail):
        raise MetricRefusal('D13_RETAINED_COMPONENT_UNBOUND', detail)

    owner_path = _d13_file(project, reference['original_owner'], external=True)
    folder = owner.get('folder')
    if (owner.get('id') != '4' or owner.get('phase') != 'phase2'
            or owner.get('stage') != 'stage1' or owner.get('storage_root') != 'steps'
            or owner.get('status') != 'INTERRUPTED' or owner.get('canonical_pass') is not False
            or owner.get('capture_errors') != [] or not isinstance(folder, str)
            or reference.get('original_invocation') != folder
            or owner_path != _safe_project_file(project, 'steps/' + folder + '/outputs.json')):
        refuse('original interrupted same-project Step4 collector required')
    attempt_path = _d13_file(project, reference['original_collector_attempt'])
    attempt = json.loads(attempt_path.read_bytes())
    if (attempt_path != owner_path.parent / 'attempt.json'
            or any(attempt.get(k) != owner.get(k) for k in ('id', 'folder', 'inputs', 'started_at'))
            or not owner.get('inputs')):
        refuse('original collector attempt/input population required')
    for rel, digest in owner['inputs'].items():
        _d13_file(project, {'path': rel, 'sha256': digest})
    outputs = owner.get('outputs')
    if (not isinstance(outputs, list) or not outputs
            or len({row['rel'] for row in outputs}) != len(outputs)):
        refuse('complete unique collector output population required')
    by_rel = {row['rel']: row for row in outputs}
    for row in outputs:
        current = _d13_file(project, {'path': row['rel'], 'sha256': row['sha256']})
        snapshot = owner_path.parent / row['snapshot']
        if not snapshot.is_relative_to(owner_path.parent) or '..' in Path(row['snapshot']).parts:
            refuse('collector snapshot escaped original folder')
        _d13_file(project, {'path': str(snapshot.relative_to(project)), 'sha256': row['sha256']})
        _d13_retained(project, reference, current)
    launch = json.loads(_d13_file(project, reference['original_launch'], external=True).read_bytes())
    terminal = json.loads(_d13_file(project, reference['original_terminal'], external=True).read_bytes())
    invocation = json.loads(_d13_file(project, reference['original_host_invocation'], external=True).read_bytes())
    source = json.loads(_d13_file(project, reference['original_source_readset'], external=True).read_bytes())
    container = launch.get('container_inspect') or {}
    cid = container.get('Id')
    images = launch.get('image_inspect') or []
    host = container.get('HostConfig') or {}
    if (not isinstance(cid, str) or not re.fullmatch(r'[0-9a-f]{64}', cid)
            or launch.get('cid') != cid or terminal.get('cid') != cid or invocation.get('cid') != cid
            or len(images) != 1 or container.get('Image') != images[0].get('Id')
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(container.get('Image', '')))
            or terminal.get('rc') != 1 or terminal.get('daemon_exit') != 1
            or reference.get('parent_exit_code') != 1
            or host.get('NetworkMode') != 'none' or host.get('NanoCpus') != 2_000_000_000
            or host.get('Memory') != 4_294_967_296 or host.get('MemorySwap') != 4_294_967_296):
        refuse('actual original CID/image/failed terminal/resource capture required')
    events = [json.loads(line) for line in _d13_file(project,
        reference['original_host_events'], external=True).read_text().splitlines() if line.strip()]
    dies = [event for event in events if event.get('Action') == 'die'
            and event.get('Actor', {}).get('ID') == cid]
    if (len(dies) != 1 or dies[0]['Actor']['Attributes'].get('exitCode') != '1'
            or invocation.get('start') != terminal.get('start')
            or not terminal['start'] < terminal['end']):
        refuse('original Docker die event/host interval required')
    argv = invocation.get('native_argv') or []
    import shlex
    entry = _d13_file(project, reference['original_entry_script'], external=True)
    mounts = container.get('Mounts') or []
    if (container.get('Config', {}).get('Cmd') != ['sh', '/run-evidence/entry.sh']
            or container.get('Config', {}).get('Entrypoint') is not None
            or not any(m.get('Type') == 'bind' and m.get('Destination') == '/run-evidence'
                       and entry == Path(m['Source']) / 'entry.sh' for m in mounts)
            or entry.read_text().splitlines()[-1:] != ['exec ' + shlex.join(argv)]):
        refuse('original launched entry script does not bind native argv')
    producer = _d13_file(project, reference['original_producer'], external=True)
    if (len(argv) < 4 or argv[3] != str(project)
            or Path(argv[2]).name != 'phase2_one_shot_runner.py'
            or producer != Path(argv[2]).with_name('design_one_shot_runner.py')
            or invocation.get('source') != source.get('head')):
        refuse('original ordinary producer invocation required')
    for flag, value in (('--entry-step', '4'), ('--exit-step', '4'), ('--execution-mode', 'default')):
        if argv.count(flag) != 1 or argv[argv.index(flag) + 1:argv.index(flag) + 2] != [value]:
            refuse('original simulation-only Default window required')
    files = source.get('files') or []
    if (len({row['path'] for row in files}) != len(files)
            or reference['original_producer'] not in files):
        refuse('original producer source capture required')
    captured = {Path(row['path']).name: row for row in files}
    for name, digest in d13_model_sources().items():
        row = captured.get(name) or {}
        if row.get('sha256') != digest:
            refuse('original/current model differs: ' + name)
        _d13_file(project, row, external=True)
    mounts = container.get('Mounts') or []
    if not any(m.get('Type') == 'bind' and m.get('RW') is False
               and producer.is_relative_to(Path(m['Destination'])) for m in mounts):
        refuse('original producer was not read-only mounted')
    # The attempt's pre-publication stat capture establishes these were written
    # inside the original host invocation, not borrowed from an earlier run.
    before = attempt.get('_before') or {}
    for key in ('scenario_record', 'unit_junit', 'streaming_junit', 'coverage_report'):
        ref = reference[key]
        path = _d13_file(project, ref)
        _d13_retained(project, reference, path)
        stamp = before.get(ref['path'])
        if (not isinstance(stamp, list) or len(stamp) != 3
                or stamp[0] != path.stat().st_size or stamp[1] != path.stat().st_mtime_ns
                or not terminal['start'] * 1e9 <= stamp[1] <= terminal['end'] * 1e9):
            refuse('native output not captured in original invocation: ' + key)
        if key != 'scenario_record' and by_rel.get(ref['path'], {}).get('sha256') != ref['sha256']:
            refuse('native output differs from original collector: ' + key)


def _d13_retained_input_readset(project: Path, reference: Mapping, owner: Mapping) -> dict:
    """Project captured producer inputs without rewriting adopted execution bytes."""
    path = _d13_file(project, reference['scenario_record'])
    native = json.loads(path.read_bytes())
    if (native.get('schema') != 'vibeic.l10_execution.v1'
            or native.get('producer') != 'testbench_gen.run_unit_tbs'
            or not isinstance(native.get('cases'), list) or not native['cases']):
        raise MetricRefusal('D13_NATIVE_INPUT_POPULATION_INVALID', 'normal per-case producer record required')
    bindings = dict(owner['inputs'])
    for row in native['cases']:
        measured = row.get('arithmetic_scenario') or {}
        plan = measured.get('plan') or {}
        if (plan.get('schema') != 'vibeic.arithmetic_scenario.v1'
                or not isinstance(plan.get('binding'), dict) or not plan['binding']
                or not isinstance(measured.get('sources'), dict) or not measured['sources']):
            raise MetricRefusal('D13_NATIVE_INPUT_POPULATION_INVALID', str(row.get('id')))
        for name, digest in [*plan['binding'].items(), *measured['sources'].items()]:
            candidate = Path(name)
            try:
                rel = candidate.relative_to(project).as_posix()
            except ValueError as exc:
                raise MetricRefusal('D13_FOREIGN_ACTUAL_INPUT', name) from exc
            if rel in bindings and bindings[rel] != digest:
                raise MetricRefusal('D13_NATIVE_INPUT_CONFLICT', rel)
            bindings[rel] = digest
    retained = {r['path']: r['sha256'] for r in reference['artifacts']}
    effective = dict(reference)
    artifacts = list(reference['artifacts'])
    for rel, expected in sorted(bindings.items()):
        input_path = _d13_file(project, {'path': rel, 'sha256': expected})
        actual = _sha(input_path.read_bytes())
        if rel in retained and retained[rel] != actual:
            raise MetricRefusal('D13_NATIVE_INPUT_CONFLICT', rel)
        if rel not in retained:
            artifacts.append({'path': rel, 'sha256': actual})
    effective.update(artifacts=artifacts)
    return effective


def _d13_execution(project: Path, source: Mapping, *, case_name: str | None = None) -> dict:
    """Reopen independently adopted original owner/launch; never restamp old execution."""
    relative = ('adopted/base_07/simulation_execution.json' if case_name is None else
                'adopted/base_07/scenario_executions/' + case_name + '.json')
    if case_name is not None and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', case_name):
        raise MetricRefusal('D13_CASE_ID_INVALID', str(case_name))
    authority, adopted = _approved_document(project, relative,
        authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')
    approved_source = json.loads(_safe_project_file(project, authority['source']['path']).read_bytes())
    reference = adopted.get('reference')
    if case_name is not None:
        original_authority, _, current_source = _d13_authority(project, 'required_function_scenarios')
        expected_source = {'purpose': D13_PURPOSE, 'project': str(project),
            'subject': source['subject'], 'case': case_name,
            'source_authority': original_authority['source'], 'execution': reference}
        if approved_source != expected_source or current_source != source:
            raise MetricRefusal('D13_CASE_AUTHORITY_UNBOUND', case_name)
    if ((case_name is None and (approved_source != source or reference != source.get('execution')))
            or reference.get('project') != str(project) or source.get('project') != str(project)
            or source.get('subject') != d13_subject(project)):
        raise MetricRefusal('D13_EXECUTION_SUBJECT_MISMATCH', 'exact current same-project subject required')
    files = reference.get('artifacts')
    if (not isinstance(files, list) or not files or len({r['path'] for r in files}) != len(files)
            or any(Path(r['path']).is_absolute() for r in files)):
        raise MetricRefusal('D13_EXECUTION_POPULATION_INVALID', 'unique project-relative native readset required')
    owner_path = _d13_file(project, reference['original_owner'], external=True)
    owner = json.loads(owner_path.read_bytes())
    if reference.get('origin') not in (None, 'retained_native_components'):
        raise MetricRefusal('D13_EXECUTION_ORIGIN_INVALID', str(reference.get('origin')))
    if reference.get('origin') == 'retained_native_components':
        if case_name is not None:
            raise MetricRefusal('D13_RETAINED_COMPONENT_UNBOUND', 'selected-case owner requires its original native invocation')
        _d13_retained_component_owner(project, reference, owner)
        for record in source.get('source_refs', []):
            _d13_file(project, record)
        if not source.get('source_refs'):
            raise MetricRefusal('D13_SOURCE_AUTHORITY_ABSENT', 'independent original requirements required')
        return _d13_retained_input_readset(project, reference, owner)
    binding = owner.get('runner_binding') or {}
    producer = binding.get('producer')
    if (binding.get('schema') != 'vibeic.runner_report_binding.v1' or binding.get('project') != str(project)
            or binding.get('invocation_id') != reference.get('original_invocation')
            or producer != reference.get('original_producer')):
        raise MetricRefusal('D13_ORIGINAL_OWNER_UNBOUND', 'original invocation/producer must reopen')
    _d13_file(project, producer)
    if case_name is not None:
        import benchmark_dispatch as dispatch
        if (owner.get('subject') != source['subject'] or owner.get('selected_cases') != [case_name]
                or owner.get('model_sources') != d13_model_sources()
                or producer.get('sha256') != d13_model_sources()['testbench_gen.py']
                or owner.get('verdict') not in ('PASS', 'FAIL')
                or owner.get('execution', {}).get('execution_record') !=
                    str(project / reference['scenario_record']['path'])
                or owner['execution'].get('results_xml') != str(project / reference['unit_junit']['path'])
                or owner['execution'].get('tb_total') != 1
                or binding.get('report_name') != 'phase2_one_shot.json'
                or binding.get('source') != dispatch._runner_source_snapshot(binding['argv'],
                    consumer=binding['source']['consumer']['path'])
                or _d13_file(project, binding['source']['runner']) != _d13_file(project, producer)
                or reference.get('original_invocation') == source['execution']['original_invocation']):
            raise MetricRefusal('D13_CASE_OWNER_UNBOUND', case_name)
    for component in ('runner', 'consumer', 'executable'):
        _d13_file(project, binding['source'][component], external=component == 'executable')
    launch = json.loads(_d13_file(project, reference['original_launch'], external=True).read_bytes())
    terminal = json.loads(_d13_file(project, reference['original_terminal'], external=True).read_bytes())
    expected_exit = 0 if case_name is None or owner.get('verdict') == 'PASS' else 1
    if (not re.fullmatch(r'[0-9a-f]{64}', str(launch.get('cid', '')))
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(launch.get('image_id', '')))
            or terminal.get('host_exit_verified') is not True or terminal.get('docker_cli_exit_code') != expected_exit
            or terminal.get('host_die_event_exit_code') != expected_exit or terminal.get('source_unchanged') is not True):
        raise MetricRefusal('D13_ORIGINAL_LAUNCH_UNPROVEN', 'actual original host CID/image/terminal required')
    if case_name is not None:
        old_launch = json.loads(_d13_file(project, source['execution']['original_launch'], external=True).read_bytes())
        if launch['cid'] == old_launch.get('cid') or launch['image_id'] != old_launch.get('image_id'):
            raise MetricRefusal('D13_CASE_BORROWED_EXECUTION', case_name)
        path = _d13_file(project, reference['scenario_record'])
        record = __import__('_l10_execution').load_record(project,
            project / 'phase1/generated_docs/L10_TEST_CASES.json', path=path)
        if (not record.get('available') or record.get('malformed') or set(record.get('rows', {})) != {case_name}
                or record.get('producer') != 'testbench_gen.run_unit_tbs'
                or path.parent != owner_path.parent
                or _d13_file(project, reference['unit_junit']).parent != path.parent
                or Path(record['rows'][case_name]['tb_file']).parent != path.parent / 'tb'
                or Path(record['rows'][case_name].get('arithmetic_scenario', {}).get('transcript', '')).parent
                    != path.parent / case_name):
            raise MetricRefusal('D13_CASE_RECORD_UNPROVEN', case_name)
        summary = __import__('_sim_results_bridge').parse_junit(_d13_file(project, reference['unit_junit']))
        if (not summary or summary['tests'] != 1 or summary['skipped']
                or summary['passed'] + summary['failures'] + summary['errors'] != 1
                or (owner['verdict'] == 'PASS') != (summary['passed'] == 1)):
            raise MetricRefusal('D13_CASE_JUNIT_UNPROVEN', case_name)
        for required in (path, _d13_file(project, reference['unit_junit'])):
            _d13_retained(project, reference, required)
    for record in source.get('source_refs', []):
        _d13_file(project, record)
    if not source.get('source_refs'):
        raise MetricRefusal('D13_SOURCE_AUTHORITY_ABSENT', 'independent original requirements required')
    return dict(reference)


def _d13_scenario(project: Path, name: str, required: Mapping,
                  record: Mapping, execution: Mapping, declared: Mapping) -> dict:
    """One current complete original case; absent proof is not a design counterexample."""
    import _l10_execution as cases
    import arith_oracle_tb_gen as arithmetic
    result = {'name': name, 'status': 'NOT_MEASURED', 'errors': 0}
    row = record.get('rows', {}).get(name)
    if not isinstance(row, dict) or row.get('sim_executed') is not True:
        return {**result, 'reason': 'D13_CASE_NOT_EXECUTED'}
    measured = row.get('arithmetic_scenario')
    if not isinstance(measured, dict):
        return {**result, 'reason': 'D13_CASE_COMPARATORS_UNMEASURED'}
    tb = _d13_retained(project, execution, Path(row['tb_file']))
    transcript = _d13_retained(project, execution, Path(measured['transcript']))
    plan = measured['plan']
    for value, expected in {**plan.get('binding', {}), **measured.get('sources', {})}.items():
        path = _d13_retained(project, execution, Path(value))
        if _sha(path.read_bytes()) != expected:
            raise MetricRefusal('D13_CASE_INPUT_CHANGED', value)
    valid, detail = cases.scenario_tb_identity(name, record)
    observed, _ = arithmetic.capture_arithmetic_scenario_execution(project, tb, transcript, measured['sources'])
    if not valid or observed != measured:
        return {**result, 'reason': 'D13_CASE_EXECUTION_UNBOUND', 'detail': detail}
    for key in ('transactions', 'comparisons', 'errors'):
        if type(measured.get(key)) is not int or measured[key] < 0:
            raise MetricRefusal('D13_CASE_POPULATION_INVALID', name + ':' + key)
    result.update(errors=measured['errors'], measured=measured)
    # A complete native comparator failure wins before missing semantic scope.
    if measured['errors']:
        return {**result, 'status': 'FAIL', 'reason': 'D13_NATIVE_COMPARATOR_FAILED'}
    state, detail = cases.scenario_case_state(name, record)
    if state != 'PASS' or measured.get('complete') is not True:
        return {**result, 'reason': 'D13_CASE_INCOMPLETE', 'detail': detail}
    spec, framing = plan['spec'], plan['framing']
    projection = {'top': spec['top'], 'width': spec['width'], 'operator': spec['operator'],
        'integer_encoding': 'signed_2c' if spec.get('signed') else 'unsigned',
        **{key: framing[key] for key in ('bit_order', 'latency', 'latency_origin',
            'transaction_rearm', 'rearm_reset_cycles', 'parallel_hold')}}
    if (projection != declared or plan.get('scenario') != required.get('scenario')
            or measured['transactions'] < required.get('minimum_transactions', 1)
            or measured['comparisons'] < measured['transactions'] * spec['width']):
        return {**result, 'reason': 'D13_DECLARED_SEMANTICS_UNPROVEN'}
    pairs = plan.get('pairs') or []
    unique = {tuple(pair) for pair in pairs if isinstance(pair, list) and len(pair) == 2}
    if len(unique) < required.get('minimum_distinct_pairs', 1):
        return {**result, 'reason': 'D13_REQUIRED_PAIR_POPULATION_UNMEASURED'}
    if 'operand_values' in required:
        mask = (1 << spec['width']) - 1
        values = {v & mask for v in required['operand_values']}
        if any(not values <= {pair[i] & mask for pair in unique} for i in (0, 1)):
            return {**result, 'reason': 'D13_REQUIRED_OPERAND_CORNERS_UNMEASURED'}
    expected_reset = required.get('reset_observation')
    if expected_reset is not None:
        samples = measured.get('reset_observations')
        if (plan.get('reset_observation') != expected_reset or not isinstance(samples, list)
                or len(samples) != len(expected_reset['required_observations'])):
            return {**result, 'reason': 'D13_RESET_VALUES_NOT_MEASURED'}
        if ([{k: sample.get(k) for k in ('state', 'width', 'expected_value')} for sample in samples
                if isinstance(sample, dict)] != expected_reset['required_observations']):
            return {**result, 'reason': 'D13_RESET_POPULATION_INCOMPLETE'}
        observed_states = {}
        for sample in samples:
            if (not isinstance(sample, dict) or sample.get('state') in observed_states
                    or type(sample.get('samples')) is not int or sample['samples'] <= 0
                    or sample['samples'] != measured.get('held_edges')
                    or any(type(sample.get(k)) is not int for k in ('width', 'expected_value', 'mismatches'))
                    or not 0 <= sample['mismatches'] <= sample['samples']):
                return {**result, 'reason': 'D13_RESET_POPULATION_INCOMPLETE'}
            observed_states[sample['state']] = sample
        if sum(sample['mismatches'] for sample in samples) > measured['errors']:
            return {**result, 'reason': 'D13_RESET_POPULATION_INCOMPLETE'}
        for expected in expected_reset['required_observations']:
            sample = observed_states.get(expected['state'], {})
            if any(sample.get(k) != v for k, v in expected.items()):
                return {**result, 'reason': 'D13_RESET_POPULATION_INCOMPLETE'}
            if sample['mismatches']:
                return {**result, 'status': 'FAIL', 'errors': sample['mismatches'],
                        'reason': 'D13_NATIVE_RESET_VALUE_FAILED'}
    return {**result, 'status': 'PASS', 'reason': 'D13_REQUIRED_SCENARIO_CURRENT'}


def _d13_functions(project: Path, source: Mapping, execution: Mapping) -> list[dict]:
    """Read actual declared cases, including the mandatory cocotb random backend."""
    import _l10_execution as cases
    import professional_tb_gen as professional
    authority, required, approved = _d13_authority(project, 'required_function_scenarios')
    names = [item['name'] for item in required['required_items']]
    if (approved != source or not names or len(names) != len(set(names))
            or set(names) != set(source.get('scenario_requirements') or {})):
        raise MetricRefusal('D13_SCENARIO_POPULATION_UNPROVEN', 'independent complete unique census required')
    l10 = project / 'phase1/generated_docs/L10_TEST_CASES.json'
    document = json.loads(_d13_retained(project, execution, l10).read_bytes())
    declared = document.get('test_cases')
    if (not isinstance(declared, list) or any(not isinstance(c, dict) for c in declared)
            or len({c.get('name') for c in declared}) != len(declared)):
        raise MetricRefusal('D13_SCENARIO_POPULATION_UNPROVEN', 'current L10 case identities are ambiguous')
    declared = {c['name']: c for c in declared}
    path = _d13_file(project, execution['scenario_record'])
    _d13_retained(project, execution, path)
    record = cases.load_record(project, l10)
    if (not record.get('available') or not record.get('l10_binding_ok')
            or record.get('malformed') or record.get('path') != str(path)):
        raise MetricRefusal('D13_CASE_RECORD_UNPROVEN', 'exact current L10-bound record required')
    observed = []
    for name in names:
        try:
            if name not in declared:
                raise MetricRefusal('D13_SCENARIO_POPULATION_UNPROVEN', name)
            row = _d13_scenario(project, name, source['scenario_requirements'][name],
                                record, execution, source['declared'])
            if row['status'] == 'FAIL':
                observed.append(row)
                continue
            supplement = project / ('adopted/base_07/scenario_executions/' + name + '.json')
            if supplement.exists() or supplement.is_symlink():
                if source['scenario_requirements'][name].get('reset_observation') is None:
                    raise MetricRefusal('D13_CASE_SUPPLEMENT_SCOPE_UNSUPPORTED', name)
                selected = _d13_execution(project, source, case_name=name)
                selected_record = cases.load_record(project, l10,
                    path=_d13_file(project, selected['scenario_record']))
                measured = _d13_scenario(project, name, source['scenario_requirements'][name],
                    selected_record, selected, source['declared'])
                # A newly measured mismatch is never hidden by an older PASS;
                # an older real mismatch is never erased by supplementation.
                row = (row if row['status'] == 'FAIL' else measured)
                row['execution'] = selected
            if row['status'] == 'FAIL':
                observed.append(row)
                continue
            # The goal-bound cocotb execution is an independent required
            # comparison population, not the supplemental arithmetic oracle.
            if professional._requested_random_pairs(declared[name]) is not None:
                import _path_layout as layout
                plans = sorted((layout.rtl_dir(project).parent / 'sim_professional').glob('*/verification_plan.json'))
                adopted_plans = sorted(project / r['path'] for r in execution['artifacts']
                                       if Path(r['path']).name == 'verification_plan.json')
                if not plans or plans != adopted_plans:
                    raise MetricRefusal('D13_RANDOM_EXECUTION_UNBOUND', 'exact adopted goal-plan population required')
                for plan in plans:
                    _d13_retained(project, execution, plan)
                    for item in execution['artifacts']:
                        if (project / item['path']).is_relative_to(plan.parent):
                            _d13_file(project, item)
                goal = professional.random_pair_goal_measurement(project, declared[name]) or {}
                if goal.get('achieved_source'):
                    measured = _d13_retained(project, execution, project / goal['achieved_source'])
                    for item in execution['artifacts']:
                        if Path(item['path']).parent == measured.parent.relative_to(project):
                            _d13_file(project, item)
                state = goal.get('verdict', 'NOT_MEASURED')
                row['random_pair_goal'] = goal
                row['status'] = ('FAIL' if 'FAIL' in (row['status'], state) else 'PASS'
                    if row['status'] == state == 'PASS' else 'NOT_MEASURED')
            observed.append(row)
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            observed.append({'name': name, 'status': 'NOT_MEASURED',
                'reason': getattr(exc, 'code', 'D13_SCENARIO_UNPROVEN'), 'detail': str(exc)})
    return observed


def _d13_assertions(project: Path, execution: Mapping, scenarios: list[dict]) -> dict:
    """Count executed native golden/checker failures; uncompiled SVA grants no credit."""
    import _sim_results_bridge as bridge
    measured = []
    for key in ('unit_junit', 'streaming_junit'):
        try:
            path = _d13_file(project, execution[key])
            _d13_retained(project, execution, path)
            summary = bridge.parse_junit(path)
            if (not summary or summary['tests'] <= 0 or summary['skipped']
                    or summary['passed'] + summary['failures'] + summary['errors'] != summary['tests']):
                raise MetricRefusal('D13_ASSERTION_POPULATION_UNMEASURED', key)
            measured.append({'name': key, **summary, 'status': 'FAIL'
                if summary['failures'] or summary['errors'] else 'PASS'})
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            measured.append({'name': key, 'status': 'NOT_MEASURED',
                'reason': getattr(exc, 'code', 'D13_ASSERTIONS_UNPROVEN'), 'detail': str(exc)})
    states = [r['status'] for r in [*scenarios, *measured]]
    count = sum(r.get('errors', 0) + r.get('failures', 0) for r in [*scenarios, *measured])
    return {'id': D13_IDS[1], 'status': 'FAIL' if 'FAIL' in states else 'PASS'
        if states and all(s == 'PASS' for s in states) else 'NOT_MEASURED',
        'observed_value': count, 'unit': 'count', 'native_suites': measured,
        'scope': 'executed required golden/comparator assertions; uncompiled SVA is not execution'}


def _d13_coverage(project: Path, source: Mapping, execution: Mapping, identity: Mapping) -> dict:
    """Actual DUT coverage targets; informational classification never excuses missing data."""
    import verilator_coverage_measure as coverage
    authority, required, approved = _d13_authority(project, 'coverage_targets')
    if (approved != source or type(required.get('acceptance_applicable')) is not bool
            or not isinstance(required.get('reason'), str) or not required['reason'].strip()):
        raise MetricRefusal('D13_COVERAGE_CLASSIFICATION_UNPROVEN', 'independent exact applicability required')
    limits, units = required.get('limits'), required.get('units')
    if (not isinstance(limits, dict) or not limits or set(limits) != set(units or {})
            or not set(limits) <= {'line', 'toggle', 'branch'}
            or any(v != 'percent' for v in units.values())):
        raise MetricRefusal('D13_COVERAGE_BOUNDS_UNPROVEN', 'nonempty declared categories/bounds/units only')
    report = _d13_file(project, execution['coverage_report'])
    _d13_retained(project, execution, report)
    kind, detail, payload = coverage.classify_coverage_artefact(report)
    if kind != 'measured' or payload.get('measurement_scope') != 'union-of-suite':
        raise MetricRefusal('D13_COVERAGE_NOT_MEASURED', detail)
    scope = payload.get('scope_files')
    expected = sorted(str(project / r['path']) for r in source['subject']['rtl']['source_files']
                      if Path(r['path']).suffix.lower() in ('.v', '.sv'))
    if not expected or sorted(scope or []) != expected:
        raise MetricRefusal('D13_COVERAGE_SCOPE_INCOMPLETE', 'complete original DUT RTL scope required')
    for value in scope:
        _d13_retained(project, execution, Path(value))
    benches = payload.get('per_testbench')
    if (not isinstance(benches, dict) or not benches or set(benches) != set(payload.get('testbenches') or [])
            or any(v.get('measured') is not True for v in benches.values())):
        raise MetricRefusal('D13_COVERAGE_POPULATION_INCOMPLETE', 'all declared instrumented runs required')
    dats = []
    for tb, run in benches.items():
        _d13_retained(project, execution, Path(tb))
        dats.append(str(_d13_retained(project, execution, Path(run['coverage_dat']))))
    if len(set(dats)) != len(dats):
        raise MetricRefusal('D13_COVERAGE_POPULATION_INCOMPLETE', 'duplicate run data')
    union = coverage.union_coverage_dats(dats)
    if union.get('unionisable') is not True or union.get('runs_unioned') != len(dats):
        raise MetricRefusal('D13_COVERAGE_POPULATION_INCOMPLETE', 'no partial/unknown raw union')
    scoped = coverage.scope_totals(union, scope)
    info = _d13_retained(project, execution, Path(payload['line_union_cross_check']['lcov_info']))
    crosscheck = coverage.cross_check_line_union(union.get('line_union'),
        coverage.parse_lcov_info(info.read_text()), scope)
    if (crosscheck.get('status') != 'MEASURED' or crosscheck.get('agree') is not True
            or scoped.get('totals') != payload.get('totals')):
        raise MetricRefusal('D13_COVERAGE_RAW_DISAGREEMENT', 'DUT-scoped raw/lcov/report disagree')
    targets = []
    for category, bounds in limits.items():
        total = scoped['totals'][category]
        covered, population = total.get('covered'), total.get('total')
        if (type(covered) is not int or type(population) is not int or population <= 0
                or not 0 <= covered <= population):
            raise MetricRefusal('D13_COVERAGE_POPULATION_INCOMPLETE', category)
        # Judge exact counts, not the report's rounded display percentage.
        value = 100.0 * covered / population
        measured = {'status': 'MEASURED', 'value': value, 'unit': units[category],
                    'identity': {**identity, 'requirements': authority}}
        status, reason = evaluate_operator('within_declared_bounds', measured,
            {'status': 'APPROVED', 'limits': bounds, 'unit': units[category]})
        if status not in ('PASS', 'FAIL'):
            raise MetricRefusal('D13_COVERAGE_BOUNDS_UNPROVEN', category + ': ' + reason)
        targets.append({'category': category, 'status': status, 'reason': reason,
                        'value': value, 'unit': units[category], 'covered': covered, 'total': population})
    return {'id': D13_IDS[2], 'status': 'FAIL' if any(t['status'] == 'FAIL' for t in targets) else 'PASS',
            'measurement_complete': True, 'acceptance_applicable': required['acceptance_applicable'],
            'classification_reason': required.get('reason'), 'authority': authority,
            'targets': targets, 'DUT_totals': scoped['totals'], 'line_union_cross_check': crosscheck}


def accept_d13(project: Path, context: Mapping[str, Any]) -> dict:
    """BLOCKING current functional/assertion evidence and complete source-scoped coverage."""
    import flow109
    import flow109_admission as admission
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D13', 'status': 'NOT_MEASURED',
        'component_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
        'delivery_blocked': True, 'obligations': [{'id': k, 'status': 'NOT_MEASURED'} for k in D13_IDS]}
    try:
        current = flow109.validate_execution_context(context)
        rows = current['resolved_row']['obligations']
        if (current['resolved_row']['id'] != 'D13' or [r['id'] for r in rows] != list(D13_IDS)
                or rows[0]['expectation'].get('required_set_ref') !=
                    'requirements/base_07/required_function_scenarios.json#/required_items'
                or rows[1]['expectation'] != {'operator': 'eq', 'value': 0, 'unit': 'count',
                    'source': 'contract invariant: no unresolved required violations'}
                or rows[2]['expectation'].get('bounds_ref') != 'requirements/base_07/coverage_targets.json#/limits'
                or rows[2]['expectation'].get('unit_ref') != 'requirements/base_07/coverage_targets.json#/units'
                or rows[2]['expectation'].get('applicability_ref') !=
                    'requirements/base_07/coverage_targets.json#/acceptance_applicable'):
            raise MetricRefusal('D13_OBLIGATIONS_UNREGISTERED', 'existing three obligations and source classification only')
        authority, _required, source = _d13_authority(project, 'required_function_scenarios')
        qualified = _d13_qualification(project, current)
        execution = _d13_execution(project, source)
        identity = {'producer': execution['original_producer'], 'checker': d13_model_sources(),
            'tool_execution': qualified, 'consumed_inputs': source['subject'],
            'requirements': authority, 'configuration': source['declared']}
        observed = _d13_functions(project, source, execution)
        states = [r['status'] for r in observed]
        result.update(qualification='PASS', subject=source['subject'], scenarios=observed)
        status, reason = evaluate_operator('covers_all', {'status': 'MEASURED',
            'value': [{'name': r['name']} for r in observed if r['status'] == 'PASS'],
            'identity': identity}, authority)
        result['obligations'][0].update(status='FAIL' if 'FAIL' in states else status
            if observed and all(s == 'PASS' for s in states) else 'NOT_MEASURED',
            reason=reason, observed_value=observed)
        result['obligations'][1] = _d13_assertions(project, execution, observed)
        try:
            result['obligations'][2] = _d13_coverage(project, source, execution, identity)
        except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            result['obligations'][2].update(reason=getattr(exc, 'code', 'D13_COVERAGE_UNPROVEN'), detail=str(exc))
        # Preserve a qualified native failure beside an incomplete coverage
        # measurement. Changed shared authority/model/subject invalidates all.
        if (_d13_execution(project, source) != execution
                or _d13_qualification(project, current) != qualified
                or _d13_authority(project, 'required_function_scenarios')[0] != authority
                or _d13_functions(project, source, execution) != observed
                or _d13_assertions(project, execution, observed) != result['obligations'][1]):
            raise MetricRefusal('D13_INPUT_CHANGED_DURING_READ', 'current original execution/authority/model')
        if result['obligations'][2].get('measurement_complete') is True:
            if _d13_coverage(project, source, execution, identity) != result['obligations'][2]:
                raise MetricRefusal('D13_INPUT_CHANGED_DURING_READ', 'coverage/authority changed')
        # D11 is a row dependency, not permission to replay accepted D09 or its
        # simulation. Bind the accepted lint subject to this complete RTL set.
        try:
            lint, lint_ref = flow109._accepted_row(project, Path('reports/flow109/default_rows/D11.json'), 'D11')
            if lint['metric_acceptance']['subject'] != source['subject']['rtl']:
                raise MetricRefusal('D13_D11_SUBJECT_STALE', 'accepted lint subject differs')
            result['D11'] = lint_ref
        except (flow109.Flow109Error, MetricRefusal, KeyError, TypeError) as exc:
            result.update(dependency='NOT_MEASURED', dependency_reason=getattr(exc, 'code', 'D13_D11_NOT_CURRENT'))
    except (MetricRefusal, admission.AdmissionRefusal, flow109.Flow109Error,
            OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D13_EVIDENCE_UNPROVEN'), detail=str(exc))
        for row in result['obligations']:
            row['status'] = 'NOT_MEASURED'
    functional, assertions, coverage = result['obligations']
    # Target verdicts remain actual PASS/FAIL even for informational targets.
    # Only independently approved applicability may exclude a complete target
    # result from row gating; absence/partial coverage always blocks.
    required = [functional['status'], assertions['status']]
    if coverage.get('measurement_complete') is not True:
        required.append('NOT_MEASURED')
    elif coverage.get('acceptance_applicable') is True:
        required.append(coverage['status'])
    elif coverage.get('acceptance_applicable') is not False:
        required.append('NOT_MEASURED')
    status = ('FAIL' if 'FAIL' in required else 'PASS' if required
        and all(s == 'PASS' for s in required) and result.get('D11') else 'NOT_MEASURED')
    result.update(status=status, component_status=status, delivery_blocked=status != 'PASS')
    result.setdefault('reason', 'D13_' + status)
    return result


def _a01_measurement_intents(project, authority, body, measured):
    """Observe approved, source-bound intent separately from numeric targets.

    Required items alone earn no credit. The existing owner review must call
    the row an explicit intent and cite text still present in its source.
    This is A01 declaration coverage, never a circuit measurement result.
    """
    reviews = body.get('item_review', [])
    citations = body.get('item_citations', [])
    if not isinstance(reviews, list) or not isinstance(citations, list):
        raise MetricRefusal('METRIC_INTENT_INVALID', 'review/citations must be lists')
    observations, readset, seen = [], {}, set()
    blocks = {item['block'] for item in measured['value']}
    required = authority['required_items']
    for review in reviews:
        if not isinstance(review, dict) or review.get('kind') != 'explicit_verification_intent':
            continue
        index, item = review.get('item_index'), review.get('item')
        if (type(index) is not int or not 0 <= index < len(required)
                or index in seen or item != required[index]):
            raise MetricRefusal('METRIC_INTENT_INVALID', 'review does not bind a unique required item')
        seen.add(index)
        evidence = [row for row in citations if isinstance(row, dict)
                    and row.get('item_index') == index and row.get('item') == item]
        if not evidence or item['block'] not in blocks:
            continue
        if len(evidence) != 1 or not isinstance(evidence[0].get('citations'), list):
            raise MetricRefusal('METRIC_INTENT_INVALID', 'intent citations are ambiguous/invalid')
        sources = evidence[0]['citations']
        if not sources:
            continue
        for citation in sources:
            if (not isinstance(citation, dict) or not isinstance(citation.get('path'), str)
                    or Path(citation['path']).is_absolute()
                    or not _HEX.fullmatch(str(citation.get('sha256', '')))):
                raise MetricRefusal('METRIC_INTENT_INVALID', 'invalid source reference')
            path = _safe_project_file(project, citation['path'])
            if not path.is_file() or _sha(path.read_bytes()) != citation['sha256']:
                raise MetricRefusal('METRIC_INTENT_SOURCE_STALE', citation['path'])
            lines = path.read_text(encoding='utf-8').splitlines()
            line, literal = citation.get('line'), citation.get('literal')
            if (type(line) is not int or not 1 <= line <= len(lines)
                    or not isinstance(literal, str) or not literal or literal not in lines[line - 1]):
                raise MetricRefusal('METRIC_INTENT_SOURCE_UNBOUND', citation['path'])
            readset[citation['path']] = citation['sha256']
        observations.append(dict(item))
    result = dict(measured)
    result['value'] = measured['value'] + [item for item in observations if item not in measured['value']]
    result['identity'] = dict(measured['identity'])
    result['identity']['consumed_inputs'] = {
        **measured['identity']['consumed_inputs'], **readset,
        authority['path']: authority['sha256'], authority['source']['path']: authority['source']['sha256']}
    return result


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
            authority, body = _approved_authority(project, binding["authority"], binding["item_fields"])
            measured = dict(measured_by_id[oid])
            if ("native_results" in component and measured.get('status') == 'MEASURED'
                    and measured['identity']['consumed_inputs'].get(
                        str(project / authority['source']['path'])) != authority['source']['sha256']):
                raise MetricRefusal('METRIC_AUTHORITY_FOREIGN_SOURCE', authority['source']['path'])
            if measured.get("status") == "MEASURED":
                if oid == 'base_A1.required_measurements':
                    measured = _a01_measurement_intents(project, authority, body, measured)
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


def d31_model_sources() -> dict:
    """Bind only D31's actually consumed producer/checker definitions."""
    import ast
    import flow109_analog_floorplan as owner
    import flow109
    import analog_hardmacro_check as packages
    import librelane_contract as launch
    modules = [(Path(owner.__file__), ('execute', 'number', 'box', 'bound_file', 'read', 'sha',
        'lef_envelope', 'load_inputs', 'native', 'observe_component', 'consume_default_row_completion')),
        (Path(__file__), ('d31_model_sources', '_d31_upstream', '_d31_original_launch', '_d31_qualification', 'accept_d31')),
        (Path(launch.__file__), ('local_image_attestation',)),
        (Path(flow109.__file__), ('_d23_original_launch',))]
    result = {}
    for path, names in modules:
        text = path.read_text()
        nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
        for name in names:
            result[path.name + ':' + name] = _sha(ast.get_source_segment(text, nodes[name]).encode())
    result['_pad_ring.py'] = _sha((HERE / '_pad_ring.py').read_bytes())
    result['analog_hardmacro_check.py'] = _sha(Path(packages.__file__).read_bytes())
    result['flow109_metric_acceptance.py:D31_BINDINGS'] = _sha(_json_key(D31_BINDINGS).encode())
    return result


def _d31_upstream(project: Path, context: Mapping, component: Mapping) -> dict:
    """Reuse normal accepted predecessors and the existing A17 design audit.

    A neutral library macro has real geometry but is not a design-bound A17
    package. No substitute netlist, upstream PASS or adoption is generated.
    """
    import flow109
    import analog_hardmacro_check as packages
    import _path_layout as layout
    import flow109_analog_floorplan as owner
    selected = {r['id'] for r in flow109.resolve_plan(context['features'], context['step_profiles'])['rows']}
    refs, missing, a17_outputs = {}, [], {}
    for step in context['resolved_row']['acceptance_deps']:
        if step not in selected:
            continue
        try:
            body, ref = flow109._accepted_row(project, Path('reports/flow109/default_rows') / (step + '.json'), step)
            if not body.get('context_sha256'):
                raise MetricRefusal('D31_UPSTREAM_CONTEXT_ABSENT', step)
            original = json.loads((project / 'reports/flow109/requests' / (body['context_sha256'] + '.json')).read_bytes())
            if (original.get('features') != context['features'] or original.get('requested_step') != step
                    or flow109.digest({k: v for k, v in original.items() if k != 'context_sha256'}) != body['context_sha256']):
                raise MetricRefusal('D31_UPSTREAM_SELECTION_FOREIGN', step)
            if step == 'A17':
                rows = [r for r in body.get('native_results', {}).get('steps', []) if r.get('step') == 'A17']
                if not rows or any(r.get('status') != 'PASS' for r in rows):
                    raise MetricRefusal('D31_A17_NATIVE_POPULATION_ABSENT', 'actual accepted package rows required')
                for row in rows:
                    for key in ('input_views', 'output_views'):
                        if not isinstance(row.get(key), dict) or not row[key]:
                            raise MetricRefusal('D31_A17_READSET_ABSENT', key)
                        for name, digest in row[key].items():
                            path = Path(name)
                            path = path if path.is_absolute() else project / path
                            owner.bound_file(project, {'path': str(path.relative_to(project)), 'sha256': digest})
                            if key == 'output_views':
                                a17_outputs[str(path.relative_to(project))] = digest
            elif step == 'D03':
                inputs = body.get('inputs')
                if not isinstance(inputs, list) or not inputs:
                    raise MetricRefusal('D31_D03_READSET_ABSENT', 'native technology inputs required')
                for item in inputs:
                    path = Path(item['path'])
                    path = path if path.is_absolute() else project / path
                    if owner.sha(path) != item['sha256']:
                        raise MetricRefusal('D31_D03_READSET_STALE', str(path))
            refs[step] = ref
        except (flow109.Flow109Error, MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            missing.append({'step': step, 'reason': getattr(exc, 'code', 'D31_UPSTREAM_NOT_CURRENT'), 'detail': str(exc)})
    audit = packages.run_audit(project)
    blocks = set(audit.summary.get('design_bound_blocks', []))
    plan = owner.read(project / owner.PLAN)
    inventory = owner.read(owner.bound_file(project, plan['macro_inventory']))
    logical, physical = {}, {}
    for instance, view in inventory['instances'].items():
        block = view.get('block', view['master'])
        if not isinstance(block, str) or not _SAFE.fullmatch(block):
            missing.append({'instance': instance, 'reason': 'D31_A17_BLOCK_IDENTITY_UNBOUND'})
            continue
        package = layout.hardmacro_dir(project) / block
        expected = {kind: package / (block + '.' + suffix) for kind, suffix in
                    (('gds', 'gds'), ('lef', 'lef'), ('logical', 'v'))}
        if (block not in blocks or any(not p.is_file() for p in expected.values())
                or any(owner.sha(expected[kind]) != view[kind]['sha256'] for kind in ('gds', 'lef'))):
            missing.append({'instance': instance, 'reason': 'D31_DESIGN_BOUND_A17_REFERENCE_ABSENT'})
            continue
        for path in expected.values():
            owner.bound_file(project, {'path': str(path.relative_to(project)), 'sha256': owner.sha(path)})
            if a17_outputs.get(str(path.relative_to(project))) != owner.sha(path):
                raise MetricRefusal('D31_A17_ADOPTED_VIEW_UNBOUND', str(path))
        logical[instance] = {'path': str(expected['logical'].relative_to(project)), 'sha256': owner.sha(expected['logical'])}
        physical[instance] = {kind: dict(view[kind]) for kind in ('gds', 'lef')}
    if len(logical) != len(inventory['instances']) or 'A17' not in refs:
        missing.append({'reason': 'D31_LOGICAL_AND_ADOPTED_VIEW_POPULATION_INCOMPLETE'})
    declared_blocks = {v.get('block', v['master']) for v in inventory['instances'].values()}
    if declared_blocks != blocks:
        missing.append({'reason': 'D31_A17_DESIGN_BLOCK_POPULATION_MISMATCH'})
    return {'status': 'NOT_MEASURED' if missing else 'PASS', 'accepted_dependencies': refs,
            'logical': logical, 'adopted_physical': physical, 'missing': missing,
            'A17_audit': audit.summary}


def _d31_original_launch(original: Mapping, current: Mapping) -> None:
    """Reuse the existing host-retained launch reader, without a same-CID gate.

    This does not adopt or rewrite a launch. The recorded original path/hash,
    CID, immutable image and host inspection must reopen under the same native
    image. Legacy components without an original host receipt stay unmeasured.
    """
    import flow109
    if (not isinstance(original, dict) or not original.get('cid')
            or not isinstance(original.get('attestation_path'), str)
            or not original['attestation_path']):
        raise MetricRefusal('D31_ORIGINAL_LAUNCH_UNBOUND', 'actual original host receipt required; never restamp')
    try:
        flow109._d23_original_launch(original,
            {**current, 'attestation_path': original['attestation_path']})
    except flow109.Flow109Error as exc:
        raise MetricRefusal('D31_ORIGINAL_LAUNCH_UNPROVEN', str(exc)) from exc


def _d31_qualification(project: Path, context: Mapping, observed: Mapping) -> dict:
    """Use the existing per-use inventory; source-owned launch is not qualified."""
    import flow109_admission as admission
    import librelane_contract as launch
    qualified = admission.require_admission(project, context)
    uses = context['runtime_tool_uses']
    if len(uses) != 1 or uses[0]['tool_id'] != 'klayout':
        raise MetricRefusal('D31_QUALIFICATION_SCOPE_INVALID', 'one actual KLayout method use required')
    config = json.loads((project / uses[0]['config']['path']).read_bytes())
    expected = {'purpose': uses[0]['semantics']['purpose'], 'native_steps': ['flow109.D31'],
                'model_sources': d31_model_sources()}
    if config != expected:
        raise MetricRefusal('D31_MODEL_QUALIFICATION_STALE', 'current consumed method/metric model required')
    original = admission.require_admission(project, observed['original_context'])
    if observed['component'].get('launch_admission') != original:
        raise MetricRefusal('D31_ORIGINAL_EXECUTION_UNQUALIFIED', 'original native admission must reopen; never restamp')
    if uses[0]['build_sha256'] != observed['component']['tool']['sha256']:
        raise MetricRefusal('D31_ORIGINAL_TOOL_UNQUALIFIED', 'actual executed binary differs')
    try:
        current_launch = launch.local_image_attestation()
    except launch.Refusal as exc:
        raise MetricRefusal('D31_CURRENT_LAUNCH_UNBOUND', str(exc)) from exc
    _d31_original_launch(observed['component'].get('native_launch'), current_launch)
    return qualified


def accept_d31(project: Path, context: Mapping, component: Mapping) -> dict:
    """Bind the two D31 obligations to current native geometry and its population.

    Observations may be complete on a neutral carrier while logical/adopted
    source authority, accepted dependencies or per-use qualification are absent.
    These remain separate named blockers; no geometry scalar finishes the row.
    """
    import flow109_analog_floorplan as owner
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D31', 'status': 'NOT_MEASURED',
        'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
        'delivery_blocked': True, 'obligations': [],
        'scope': 'D31 placed floorplan geometry only; not routing, G1-G9 or whole die signoff'}
    obligations = context.get('resolved_row', {}).get('obligations', [])
    try:
        if [r.get('id') for r in obligations] != list(D31_BINDINGS) or any(
                r.get('expectation') != D31_BINDINGS[r['id']] for r in obligations):
            raise MetricRefusal('D31_OBLIGATIONS_UNREGISTERED', 'exact two existing obligations required')
        observed = owner.observe_component(project, context, component)
        result['observation'] = observed
        measurement = observed['measurement']
        count = _finite_number(measurement.get('illegal_macro_overlap'), count=True)
        feasibility = measurement.get('floorplan_boundary_pin_feasibility')
        if feasibility not in ('PASS', 'FAIL') or type(measurement.get('violations')) is not list:
            raise MetricRefusal('D31_MEASUREMENT_INCOMPLETE', 'typed native boundary/pin population required')
        native_states = [feasibility, 'PASS' if count == 0 else 'FAIL']
        result['metric_status'] = 'FAIL' if 'FAIL' in native_states else 'PASS'
        result['obligations'] = [{'id': row['id'], 'measurement_complete': True,
            'measurement_status': state, 'status': 'FAIL' if state == 'FAIL' else 'NOT_MEASURED',
            'reason': 'D31_NATIVE_MEASUREMENT_CURRENT_BINDINGS_PENDING'}
            for row, state in zip(obligations, native_states)]
        upstream = _d31_upstream(project, context, component)
        result['upstream'] = upstream
        bindings = {'netlist.logical': upstream['logical'],
            'layout.routed': {'artifacts': component['outputs'], 'scope': 'placed floorplan, not routed-layout acceptance'},
            'constraints.physical': {k: v for k, v in observed['readset'].items()
                if k in (str(owner.PLAN), str(owner.BOUNDS))},
            'technology.models': {k: v for k, v in observed['readset'].items() if k in component['inputs']
                and k not in (str(owner.PLAN), str(owner.BOUNDS))},
            'producer.base_20.execution': observed['component_ref']}
        result['obligations'] = []
        for row in obligations:
            boundary = row['id'] == 'base_20.floorplan_boundary_pin_feasibility'
            actual = feasibility if boundary else ('PASS' if count == 0 else 'FAIL')
            key_bindings = dict(bindings)
            key_bindings['requirements.' + row['id']] = ({'path': str(owner.BOUNDS),
                'sha256': component['inputs'][str(owner.BOUNDS)]} if boundary else D31_BINDINGS[row['id']])
            key_bindings['checker.' + row['id']] = {'model_sources': d31_model_sources(), 'readback': observed['readback']}
            if set(row['binding_keys']) != set(key_bindings):
                raise MetricRefusal('D31_BINDING_KEYS_UNREGISTERED', row['id'])
            complete = upstream['status'] == 'PASS'
            result['obligations'].append({'id': row['id'], 'metric': row['metric'],
                'operator': row['expectation']['operator'], 'measurement_complete': True,
                'measurement_status': actual, 'status': 'FAIL' if actual == 'FAIL' else 'PASS' if complete else 'NOT_MEASURED',
                'observed_value': measurement if boundary else count,
                'unit': owner.read(project / owner.BOUNDS)['units'] if boundary else 'count',
                'bindings': key_bindings, 'binding_status': 'PASS' if complete else 'NOT_MEASURED',
                'reason': 'D31_NATIVE_MEASUREMENT_CURRENT' if complete else 'D31_LOGICAL_OR_ADOPTED_REFERENCE_UNBOUND'})
        states = [r['measurement_status'] for r in result['obligations']]
        result['metric_status'] = 'FAIL' if 'FAIL' in states else 'PASS'
        try:
            qualified = _d31_qualification(project, context, observed)
        except (MetricRefusal, ValueError, OSError, KeyError, TypeError) as exc:
            qualified = {'status': 'NOT_MEASURED', 'reason': getattr(exc, 'code', 'D31_QUALIFICATION_NOT_MEASURED'), 'detail': str(exc)}
        result['qualification'], result['admission'] = qualified['status'], qualified
        result['reason'] = qualified.get('reason', 'D31_REQUIRED_BINDINGS_NOT_MEASURED')
        # Native failure is not erased by a later absent qualification/reference.
        if result['metric_status'] == 'FAIL':
            result.update(status='FAIL', reason='D31_NATIVE_METRIC_FAILURE')
        elif upstream['status'] == qualified['status'] == 'PASS' and all(r['status'] == 'PASS' for r in result['obligations']):
            result.update(status='PASS', delivery_blocked=False, reason='D31_REQUIRED_BINDINGS_CURRENT_AND_QUALIFIED')
        for name, digest in observed['readset'].items():
            if owner.sha(project / name) != digest:
                raise MetricRefusal('D31_INPUT_CHANGED_BEFORE_METRIC_PUBLICATION', name)
        if _d31_upstream(project, context, component) != upstream:
            raise MetricRefusal('D31_ADOPTED_INPUT_CHANGED_BEFORE_METRIC_PUBLICATION', 'current dependencies/design-bound views changed')
        if qualified['status'] == 'PASS' and _d31_qualification(project, context, observed) != qualified:
            raise MetricRefusal('D31_QUALIFICATION_CHANGED_BEFORE_METRIC_PUBLICATION', 'per-use qualification changed')
    except (MetricRefusal, owner.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        failed = result['metric_status'] == 'FAIL'
        reason = (str(exc).partition(':')[0] if isinstance(exc, owner.Refusal)
                  else getattr(exc, 'code', 'D31_METRIC_EVIDENCE_REFUSED'))
        result.update(status='FAIL' if failed else 'NOT_MEASURED',
            metric_status='FAIL' if failed else 'NOT_MEASURED', qualification='NOT_MEASURED', delivery_blocked=True,
            reason=reason, detail=str(exc))
        if not failed:
            result['obligations'] = [{'id': k, 'status': 'NOT_MEASURED',
                'reason': result['reason'], 'detail': result['detail']} for k in D31_BINDINGS]
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

    from flow109_final_lec import INPUT as D44_INPUT
    manifest_record = {"path": D44_INPUT, "sha256": inputs.get(D44_INPUT)}
    _, manifest = _d44_bound_json(project, manifest_record, "D44 input")
    transformations = manifest.get("transformations")
    if transformations == []:
        if component.get("transformation_receipt") is not None:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                                "undeclared physical preparation")
        rtl = manifest.get("rtl")
        if not isinstance(rtl, list) or not rtl:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID", "reference proof views")
        reference_records = []
        reference_paths = []
        for index, record in enumerate(rtl):
            path = _d44_bound_file(project, record, f"reference proof view {index}")
            current = _d44_readset_record(project, inputs, str(path),
                                          f"reference proof view {index}")
            if current["sha256"] != record.get("sha256"):
                raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE",
                                    f"reference proof view {index}")
            reference_records.append(dict(record))
            reference_paths.append(path)
        raw_netlist = manifest.get("adopted_netlist")
        gate_path = _d44_bound_file(project, raw_netlist, "adopted proof view")
        raw_read = _d44_readset_record(project, inputs, str(gate_path),
                                       "adopted proof view")
        if raw_read["sha256"] != raw_netlist.get("sha256"):
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_STALE", "adopted proof view")
        physical_configuration = {"transformations": "NONE_DECLARED",
                                  "reference_views": reference_records,
                                  "gate_view": dict(raw_netlist)}
        top = manifest.get("top")
        interfaces = None
    else:
        if not isinstance(transformations, list) or not transformations:
            raise MetricRefusal("METRIC_EXECUTION_EVIDENCE_INVALID",
                                "D44 transformations")
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
            output_paths[side] = _d44_bound_file(project, outputs[side],
                                                  f"{side} proof view")
            _d44_readset_record(project, inputs, str(output_paths[side]),
                                f"{side} proof view")
        _d44_readset_record(project, inputs, str(preparation_path),
                            "current preparation")
        raw_netlist = preparation.get("raw_adopted_netlist")
        if (not isinstance(raw_netlist, Mapping)
                or not isinstance(raw_netlist.get("path"), str)
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
        reference_paths = [output_paths["gold"]]
        gate_path = output_paths["gate"]
        physical_configuration = {
            "current_preparation": dict(component["transformation_receipt"]),
            "raw_adopted_netlist": dict(raw_netlist),
            "reference_view": dict(outputs["gold"]),
            "gate_view": dict(outputs["gate"]),
        }
        top = preparation.get("top")
        interfaces = preparation.get("functional_interfaces")

    verilog_files = config.get("VERILOG_FILES")
    models = config.get("CELL_VERILOG_MODELS")
    if (not isinstance(verilog_files, list)
            or not all(isinstance(item, str) for item in verilog_files)
            or [Path(item).resolve() for item in verilog_files]
               != [path.resolve() for path in reference_paths]
            or state_in.get("nl") != state_out.get("nl")
            or not isinstance(state_in.get("nl"), str)
            or Path(state_in["nl"]).resolve() != gate_path.resolve()
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
            or (interfaces is not None and interfaces != normalized)
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
        **physical_configuration,
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


def accept_d36(project: Path, context: Mapping[str, Any]) -> dict:
    """BLOCKING D36 map/flush consumer; original execution must be independently adopted."""
    import flow109
    import flow109_scan_physical as native
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D36', 'status': 'NOT_MEASURED',
              'component_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    specs = {
        'scan_physical.chain_map_identity': {'operator': 'matches_adopted_reference',
            'reference_ref': 'adopted/scan_physical/chain_map_identity.json'},
        'scan_physical.scan_flush_errors': {'operator': 'eq', 'value': 0, 'unit': 'count'},
    }
    try:
        current = flow109.validate_execution_context(context)
        if current['resolved_row']['id'] != 'D36':
            raise MetricRefusal('D36_CONTEXT_INVALID', 'not D36')
        declared = current['resolved_row']['obligations']
        if ({o['id'] for o in declared} != set(specs)
                or any(any(o['expectation'].get(k) != v for k, v in specs[o['id']].items()) for o in declared)):
            raise MetricRefusal('D36_OBLIGATIONS_UNREGISTERED', 'existing two contracts only')
        prepared = native.prepare(project, current)
        observed = native.reopen(prepared)
        result.update(component_status=observed['native_status'], qualification='PASS',
                      qualification_scope=native.PURPOSE, execution=observed['execution'],
                      map_reference=observed['map_reference'])
        for oid, spec in specs.items():
            is_map = spec['operator'] == 'matches_adopted_reference'
            relative = (spec['reference_ref'] if is_map else
                        'requirements/scan_physical/scan_flush_errors.json')
            authority, body, source = native.approved(project, relative,
                'vibeic.flow109.adopted-reference.v1' if is_map else AUTHORITY_SCHEMA)
            if (source.get('project') != str(project) or source.get('manifest') != prepared['manifest_ref']
                    or source.get('purpose') != native.PURPOSE):
                raise MetricRefusal('D36_AUTHORITY_SUBJECT_MISMATCH', relative)
            if is_map:
                authority.update(reference=body['reference'], reference_identity=body['reference_identity'])
                value = observed['chain_map']
            else:
                if body.get('value') != 0 or type(body.get('value')) is not int or body.get('unit') != 'count':
                    raise MetricRefusal('D36_FLUSH_EXPECTATION_CHANGED', 'zero errors invariant')
                authority.update(value=0, unit='count')
                value = observed['scan_flush_errors']
            identity = {'producer': native.operation_sources(), 'checker': native.consumer_sources(),
                'tool_execution': observed['execution'],
                'consumed_inputs': {'manifest': prepared['manifest_ref'], 'map': observed['map_reference'],
                                    'upstream': prepared['upstream']},
                'requirements': authority, 'configuration': {'purpose': native.PURPOSE,
                    'tools': prepared['tools'], 'context_sha256': current['context_sha256']}}
            measured = {'status': 'MEASURED', 'value': value, 'identity': identity}
            if not is_map:
                measured['unit'] = 'count'
            status, reason = evaluate_operator(spec['operator'], measured, authority)
            result['obligations'].append({'id': oid, 'status': status, 'reason': reason,
                'measurement': measured, 'authority': authority})
        if native.prepare(project, current) != prepared or native.reopen(prepared) != observed:
            raise MetricRefusal('D36_INPUT_CHANGED_DURING_READ', 'current inputs/execution')
        statuses = [o['status'] for o in result['obligations']]
        status = 'FAIL' if observed['native_status'] == 'FAIL' or 'FAIL' in statuses else (
            'PASS' if len(statuses) == 2 and all(s == 'PASS' for s in statuses) else 'NOT_MEASURED')
        result.update(status=status, delivery_blocked=status != 'PASS',
                      reason='D36_NATIVE_OR_MAP_MISMATCH' if status == 'FAIL' else 'D36_MAP_AND_FLUSH_CURRENT')
    except (MetricRefusal, flow109.Flow109Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D36_NATIVE_BINDING_UNPROVEN'), detail=str(exc))
    if result['component_status'] == 'FAIL':
        result.update(status='FAIL', delivery_blocked=True)
    return result

# D14 deliberately consumes the existing formal artifacts; it never runs a
# solver or upgrades a missing antecedent reachability check to non-vacuity.
D14_BINDINGS = {
    'base_08.unproved_required_properties': {'operator': 'eq', 'value': 0, 'unit': 'count'},
    'base_08.vacuous_required_proofs': {'operator': 'eq', 'value': 0, 'unit': 'count'},
    'base_08.proof_partition_coverage': {'operator': 'covers_all',
        'required_set_ref': 'requirements/base_08/proof_partition_coverage.json#/required_items'},
}



D14_TOOL_STEPS = {
    'sby': ['SymbiYosys.Prove', 'SymbiYosys.Bmc', 'SymbiYosys.Cover'],
    'yosys': ['Yosys.FormalRead', 'Yosys.Prep'],
    'yosys-abc': ['ABC.PDR', 'ABC.BMC3'],
    'yosys-smtbmc': ['SMTBMC.Cover'],
    'yices-smt2': ['Yices.SMT2Cover'],
    'python3': ['formal_harness_gen.generate', 'formal_property_run.run',
                'formal_property_run.run_reachability', 'D14.RetainedReaders'],
}
D14_ENGINES = {'safety': 'abc pdr', 'bmc': 'abc bmc3', 'cover': 'smtbmc yices'}
D14_SMT_TOOL_STEPS = {
    'sby': ['SymbiYosys.Prove', 'SymbiYosys.Cover'],
    'yosys': ['Yosys.FormalRead', 'Yosys.Prep'],
    'yosys-smtbmc': ['SMTBMC.Prove', 'SMTBMC.Cover'],
    'yices-smt2': ['Yices.SMT2Prove', 'Yices.SMT2Cover'],
    'python3': D14_TOOL_STEPS['python3'],
}
D14_SMT_ENGINES = {'safety': 'smtbmc yices', 'cover': 'smtbmc yices'}


def d14_model_sources() -> dict:
    """Existing per-use model binding, scoped to consumed formal functions."""
    import ast
    import formal_property_run as producer
    import formal_harness_gen as generator
    import formal_proof_evidence_check as checker
    modules = [
        (producer, ('run', 'run_reachability', 'reachability_plan', '_reachability_inputs',
                    '_reachability_deck', '_cover_target_identity', 'check_reachability', '_authored_chip_read',
                    'parse_sby_config', 'parse_sby_log', 'build_results', 'fold_prove_arms')),
        (generator, ('generate', 'declaration_obligations', '_timing_semantics', '_provenance_evidence',
                     '_unresolved_declaration_rows')),
        (checker, ('audit', 'binding_dispositions', 'proof_source_staleness')),
    ]
    result = {}
    for module, names in modules:
        text = Path(module.__file__).read_text()
        nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
        for name in names:
            result[Path(module.__file__).name + ':' + name] = _sha(ast.get_source_segment(text, nodes[name]).encode())
    text = Path(__file__).read_text()
    nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    for name in ('_d14_owner_provenance', '_d14_observe', '_d14_qualification', 'accept_d14', 'd14_model_sources'):
        result['flow109_metric_acceptance.py:' + name] = _sha(ast.get_source_segment(text, nodes[name]).encode())
    return result


def _d14_qualification(project: Path, context: Mapping, observed: Mapping) -> dict:
    import flow109_admission as admission
    qualified = admission.require_admission(project, context)
    uses = context['runtime_tool_uses']
    tasks = {p['task']: p for p in observed['replay']['properties']}
    if (set(tasks) == {'safety', 'bmc'} and tasks['safety']['mode'] == 'prove'
            and tasks['bmc']['mode'] == 'bmc'
            and all(tasks[name]['engine'] == D14_ENGINES[name] for name in tasks)):
        steps, engines, purpose = D14_TOOL_STEPS, D14_ENGINES, 'D14.default'
    elif (set(tasks) == {'safety'} and tasks['safety']['mode'] == 'prove'
            and tasks['safety']['engine'] == 'smtbmc yices'):
        steps, engines, purpose = D14_SMT_TOOL_STEPS, D14_SMT_ENGINES, 'D14.default.smt_yices'
    else:
        raise MetricRefusal('D14_ENGINE_MODE_NOT_QUALIFIED', 'unsupported actual proof task/engine population')
    if observed['replay'].get('prove_arms'):
        raise MetricRefusal('D14_ENGINE_MODE_NOT_QUALIFIED', 'unqualified additional proof arms')
    if {u['tool_id'] for u in uses} != set(steps) or len(uses) != len(steps):
        raise MetricRefusal('D14_QUALIFICATION_SCOPE_INVALID', 'exact actual formal/cover tool uses required')
    models = d14_model_sources()
    for use in uses:
        tool = use['tool_id']
        expected = {'purpose': purpose + '.formal_and_reachability', 'tool_id': tool,
                    'native_steps': steps[tool], 'engines': engines,
                    'model_sources': models}
        config = json.loads(_safe_project_file(project, use['config']['path']).read_bytes())
        if (use['semantics'] != {'purpose': purpose, 'native_steps': steps[tool]}
                or config != expected):
            raise MetricRefusal('D14_MODEL_QUALIFICATION_STALE', tool)
    return qualified

def _d14_owner_provenance(project: Path, result: Mapping) -> dict:
    """Reopen real producer bytes; historical reuse needs normal adoption.

    Original source may be older than this consumer. The existing source
    identity reader verifies that retained checkout, never current-main equality.
    Adoption binds the unchanged proof result, source and original execution
    reference. It is not native purpose qualification.
    """
    import formal_property_run as producer
    owners = result.get('program_owner_sha256')
    current = producer.program_owner_identity()
    if (not isinstance(owners, dict) or set(owners) != set(current)
            or any(not _HEX.fullmatch(str(v)) for v in owners.values())):
        raise MetricRefusal('D14_PRODUCER_PROVENANCE_ABSENT', 'original source identity required')
    if owners == current:
        return {'kind': 'current_producer_bytes', 'files': {
            str(HERE / name): digest for name, digest in owners.items()}}
    try:
        authority, body = _approved_document(project, 'adopted/base_08/formal_execution.json',
            authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')
        source = json.loads(_safe_project_file(project, authority['source']['path']).read_bytes())
        reference = body['reference']
        if (not authority['source']['path'].startswith('input/')
                or source != {'purpose': 'D14.original_formal_execution',
                              'project': str(project), 'reference': reference}):
            raise MetricRefusal('D14_ORIGINAL_OWNER_UNBOUND', 'adopted source payload differs')
        import _path_layout as layout
        expected = {'path': (layout.formal_dir(project) / 'results.json').relative_to(project).as_posix(),
                    'sha256': _sha((layout.formal_dir(project) / 'results.json').read_bytes())}
        if reference['result'] != expected:
            raise MetricRefusal('D14_ORIGINAL_OWNER_UNBOUND', 'different original result')
        execution = json.loads(_d13_file(project, reference['original_execution'], external=True).read_bytes())
        if (execution.get('project') != str(project)
                or execution.get('program_owner_sha256') != owners
                or execution.get('result') != expected):
            raise MetricRefusal('D14_ORIGINAL_OWNER_UNBOUND', 'original execution/source/result binding differs')
        import execution_source_identity as identity
        package = Path(reference['source_root']).resolve()
        original = identity.current(package)
        files = {}
        for name, digest in owners.items():
            path = package / 'programs' / name
            original.verify(path)
            if _sha(path.read_bytes()) != digest:
                raise MetricRefusal('D14_ORIGINAL_OWNER_UNBOUND', name)
            files[str(path)] = digest
        original.verify_current()
        return {'kind': 'adopted_original_producer', 'files': files,
                'revision': original.revision, 'tree': original.tree,
                'authority': authority, 'reference': reference}
    except (MetricRefusal, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise MetricRefusal('D14_ORIGINAL_OWNER_UNBOUND', str(exc)) from exc

def _d14_observe(project: Path) -> dict:
    import _path_layout as layout
    import _chip_synth_read as chip
    import formal_property_run as producer
    import formal_proof_evidence_check as checker

    formal = layout.formal_dir(project)
    path = _safe_project_file(project, (formal / 'results.json').relative_to(project).as_posix())
    result = json.loads(path.read_bytes())
    if result.get('program') != 'formal_property_run':
        raise MetricRefusal('D14_PRODUCER_UNBOUND', str(path))
    inputs = {str(path.relative_to(project)): _sha(path.read_bytes())}
    def retain(path):
        relative = path.relative_to(project).as_posix()
        path = _safe_project_file(project, relative)
        inputs[relative] = _sha(path.read_bytes())
        return path
    sby = retain(_safe_project_file(project, result['sby']))
    log = retain(_safe_project_file(project, result['evidence']))
    if (inputs[result['sby']] != result.get('sby_sha256')
            or inputs[result['evidence']] != result.get('evidence_sha256')):
        raise MetricRefusal('D14_PROOF_IDENTITY_STALE', 'deck/transcript/program owners')
    owner_provenance = _d14_owner_provenance(project, result)
    retained_owners = result['program_owner_sha256']
    stale = checker.proof_source_staleness(project, formal, result)
    if stale:
        raise MetricRefusal('D14_PROOF_SOURCE_STALE', '; '.join(stale))
    harnesses = checker._harness_files(project, formal, result)
    harness = next((p for p in harnesses if p.suffix == '.sv'), None)
    rtl = chip.chip_rtl_files(layout.rtl_dir(project))
    # Reuse the producer's admitted canonical read, including defines and
    # observer bindings, rather than interpreting another task script model.
    read = producer._authored_chip_read(project, formal, sby, harness, rtl, result['top'])
    if read != result.get('chip_read'):
        raise MetricRefusal('D14_CHIP_READ_STALE', 'current selected read differs')
    cfg = producer.parse_sby_config(sby.read_text())
    proof_files = (result.get('proof_inputs') or {}).get('files')
    if not isinstance(proof_files, dict) or not proof_files:
        raise MetricRefusal('D14_PROOF_INPUTS_ABSENT', 'no actual source set')
    for name, digest in proof_files.items():
        if Path(name).name != name or not _HEX.fullmatch(str(digest)):
            raise MetricRefusal('D14_PROOF_INPUTS_INVALID', str(name))
        for source in [formal / name] + [formal / f'{sby.stem}_{task}' / 'src' / name for task in cfg]:
            if _sha(retain(source).read_bytes()) != digest:
                raise MetricRefusal('D14_TASK_SOURCE_STALE', str(source))
    if producer.proof_inputs(sby, formal).get('files') != proof_files:
        raise MetricRefusal('D14_PROOF_INPUTS_STALE', 'actual selected source set')
    replay = producer.build_results(result['top'], cfg,
        producer.parse_sby_log(log.read_text(), sby_stem=sby.stem, seed=cfg),
        result['evidence'], result['sby'])
    for key in ('properties', 'prove_arms', 'all_proved', 'proof_strength'):
        if replay.get(key) != result.get(key):
            raise MetricRefusal('D14_TRANSCRIPT_RESULT_MISMATCH', key)
    contract = retain(_safe_project_file(project, result['property_contract']))
    if _sha(contract.read_bytes()) != result.get('property_contract_sha256'):
        raise MetricRefusal('D14_CONTRACT_STALE', str(contract))
    # These existing consumers reopen expert/structural receipts. Retain their
    # inputs too so publication cannot pair a read with a later authoring epoch.
    for name in ('formal_authoring_request.json', 'formal_expert_review.json',
                 'formal_program_discharge.json', 'formal_structural_evidence.json'):
        if (formal / name).exists():
            retain(formal / name)
    refreshed = dict(replay, proof_inputs=result['proof_inputs'])
    producer._attach_property_contract(refreshed, formal, harness)
    count_keys = ('property_denominator', 'authored_property_count', 'covered_property_count',
                  'unresolved_obligations')
    if 'assert_statement_count' in result:
        count_keys += ('assert_statement_count',)
    for key in count_keys:
        if refreshed.get(key) != result.get(key):
            raise MetricRefusal('D14_PROPERTY_MODEL_STALE', key)
    if refreshed.get('structural_refutations', []) != result.get('structural_refutations', []):
        raise MetricRefusal('D14_STRUCTURAL_REFUTATION_UNBOUND', 'current program evidence differs')
    audit = checker.audit(project)
    failed = (replay['verdict'] == 'FAIL' or bool(refreshed.get('structural_refutations')))
    return {'result': result, 'replay': replay, 'audit': audit, 'inputs': inputs,
            'chip_read': read, 'failed': failed, 'owners': producer.program_owner_identity(),
            'retained_owners': retained_owners, 'owner_provenance': owner_provenance,
            'reuse_basis': 'current canonical read/task source/transcript/contract replay; original receipt unchanged'}


def accept_d14(project: Path, context: Mapping[str, Any]) -> dict:
    """Read-only D14 metric seam; absent native vacuity mapping stays unmeasured.

    Partition requirements name existing prove tasks, not assertion counts.
    Even complete safety task evidence cannot establish non-vacuity or full row
    acceptance. No project-provided zero/PASS is accepted for that obligation.
    """
    import flow109
    project = Path(project).resolve()
    answer = {'schema': SCHEMA, 'row_id': 'D14', 'status': 'NOT_MEASURED',
        'metric_status': 'NOT_MEASURED',
        'delivery_blocked': True, 'obligations': [], 'qualification': 'NOT_MEASURED',
        'whole_flow_acceptance': 'NOT_MEASURED'}
    try:
        current = flow109.validate_execution_context(context)
        declared = current['resolved_row']['obligations']
        if (current['resolved_row']['id'] != 'D14'
                or len(declared) != len(D14_BINDINGS)
                or {o['id'] for o in declared} != set(D14_BINDINGS)
                or any(any(o['expectation'].get(k) != v for k, v in D14_BINDINGS[o['id']].items())
                       for o in declared)):
            raise MetricRefusal('D14_OBLIGATIONS_UNREGISTERED', 'existing three contracts only')
        observed = _d14_observe(project)
        answer['evidence'] = observed
        for oid, binding in D14_BINDINGS.items():
            row = {'id': oid, 'status': 'NOT_MEASURED'}
            answer['obligations'].append(row)
            if observed['failed']:
                row.update(status='FAIL' if oid.endswith('unproved_required_properties') else 'NOT_MEASURED',
                           reason='D14_NATIVE_COUNTEREXAMPLE_OR_REFUTATION')
                continue
            try:
                authority, body = _approved_authority(project,
                    D14_BINDINGS['base_08.proof_partition_coverage']['required_set_ref'], ('task',))
                source = json.loads(_safe_project_file(project, authority['source']['path']).read_bytes())
                if (not authority['source']['path'].startswith('input/')
                        or source.get('required_items') != body.get('required_items')):
                    raise MetricRefusal('D14_PARTITION_AUTHORITY_PAYLOAD_MISMATCH', 'required_items')
                required = authority['required_items']
                tasks = observed['replay']['properties']
                proved = [{'task': t['task']} for t in tasks
                          if t['mode'] == 'prove' and t['status'] == 'PASS' and t['bound'] == 'unbounded']
                if (observed['audit'].get('verdict') != 'PASS'
                        or observed['result'].get('resource_stop')
                        or not required or not proved
                        or {t['task'] for t in required} != {t['task'] for t in tasks if t['mode'] == 'prove'}):
                    raise MetricRefusal('D14_REQUIRED_PROOF_INCOMPLETE', 'full declaration and partition mapping required')
                identity = {'producer': {'original_sources': observed['owner_provenance'],
                                         'consumer_sources': observed['owners']},
                    'checker': {'path': 'formal_proof_evidence_check.py',
                                'sha256': _sha((HERE / 'formal_proof_evidence_check.py').read_bytes())},
                    'tool_execution': {'tasks': [{k: t[k] for k in ('task', 'mode', 'engine', 'status', 'bound')}
                                               for t in tasks],
                                       'transcript': observed['result']['evidence_sha256']},
                    'consumed_inputs': observed['inputs'], 'requirements': authority,
                    'configuration': {'chip_read_sha256': flow109.digest(observed['chip_read']),
                                      'context_sha256': current['context_sha256']}}
                measured = {'status': 'MEASURED', 'identity': identity}
                if oid.endswith('vacuous_required_proofs'):
                    import formal_property_run as producer
                    try:
                        import _path_layout as layout
                        if not (layout.formal_dir(project) / 'reachability/results.json').is_file():
                            raise FileNotFoundError('no normal cover result')
                        reach = producer.check_reachability(project)
                    except FileNotFoundError as exc:
                        raise MetricRefusal('D14_PROPERTY_ANTECEDENT_REACHABILITY_MAPPING_ABSENT', str(exc)) from exc
                    if reach['status'] != 'PASS':
                        raise MetricRefusal(reach.get('reason', 'D14_ANTECEDENT_NOT_PROVEN_REACHABLE'), ', '.join(reach['pending']))
                    if producer.check_reachability(project) != reach:
                        raise MetricRefusal('D14_REACHABILITY_CHANGED_DURING_READ', 'cover evidence changed')
                    measured.update(value=0, unit='count')
                    identity['tool_execution']['reachability'] = reach['cover_result_sha256']
                    identity['configuration']['obligation_mapping_sha256'] = flow109.digest(reach['mapping'])
                    authority = {'status': 'APPROVED', 'value': 0, 'unit': 'count'}
                elif binding['operator'] == 'eq':
                    measured.update(value=len({t['task'] for t in required} - {t['task'] for t in proved}), unit='count')
                    authority = {'status': 'APPROVED', 'value': 0, 'unit': 'count'}
                else:
                    measured['value'] = proved
                status, reason = evaluate_operator(binding['operator'], measured, authority)
                row.update(status=status, reason=reason, measurement=measured, authority=authority)
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                row.update(reason=getattr(exc, 'code', 'D14_EVIDENCE_UNPROVEN'), detail=str(exc))
        if _d14_observe(project) != observed:
            raise MetricRefusal('D14_INPUT_CHANGED_DURING_READ', 'proof source/receipts changed')
        if any(o['status'] == 'FAIL' for o in answer['obligations']):
            answer.update(status='FAIL', metric_status='FAIL', reason='D14_MEASURED_PROOF_FAILURE')
        elif all(o['status'] == 'PASS' for o in answer['obligations']):
            answer['metric_status'] = 'PASS'
            import flow109_admission as admission
            try:
                qualified = _d14_qualification(project, current, observed)
            except (admission.AdmissionRefusal, MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                qualified = {'status': 'NOT_MEASURED', 'reason': getattr(exc, 'code', 'D14_QUALIFICATION_UNPROVEN'),
                             'detail': str(exc)}
            answer['admission'] = qualified
            answer['qualification'] = qualified['status']
            if qualified['status'] == 'PASS':
                answer.update(status='PASS', delivery_blocked=False, reason='D14_METRICS_AND_PURPOSE_QUALIFICATION_CURRENT')
            else:
                answer['reason'] = qualified.get('reason', 'D14_PURPOSE_QUALIFICATION_NOT_MEASURED')
        else:
            answer['reason'] = 'D14_REQUIRED_METRICS_NOT_MEASURED'
    except (MetricRefusal, flow109.Flow109Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        answer.update(reason=getattr(exc, 'code', 'D14_EVIDENCE_UNPROVEN'), detail=str(exc))
        answer['obligations'] = [{'id': oid, 'status': 'NOT_MEASURED', 'reason': answer['reason']}
                                 for oid in D14_BINDINGS]
    return answer


def accept_d15(project: Path, context: Mapping, component: Mapping) -> dict:
    """BLOCKING: two existing D15 metrics, with accepted D05/D09 preserved.

    Engineering observations never grant full-UPF or whole-flow qualification.
    Accepted prerequisites and the existing qualified native method complete automatically.
    """
    import flow109
    import flow109_frontend as owner
    result = {'schema': SCHEMA, 'row_id': 'D15', 'status': 'NOT_MEASURED',
              'delivery_blocked': True, 'qualification': 'NOT_MEASURED', 'obligations': [],
              'whole_flow_acceptance': 'NOT_MEASURED'}
    try:
        current = flow109.validate_execution_context(context)
        row = current['resolved_row']
        expected = {'power_verify.required_power_transitions',
                    'power_verify.isolation_retention_behavior_errors'}
        if (row['id'] != 'D15' or {o['id'] for o in row['obligations']} != expected
                or row['acceptance_deps'] != ['D05', 'D09']):
            raise MetricRefusal('D15_OBLIGATIONS_UNREGISTERED', 'existing obligations/prerequisites required')
        observed = owner.consume_d15(project, current, component)
        result.update(obligations=observed['obligations'], native_observation=observed)
        if observed['status'] != 'PASS':
            result.update(status=observed['status'], reason=observed.get('reason', 'D15_OBLIGATION_FAILED'))
            return result
        dependencies = {}
        for step in ('D05', 'D09'):
            body, ref = flow109._accepted_row(Path(project),
                Path('reports/flow109/default_rows') / (step + '.json'), step)
            original, _ = flow109._bound_project_json(Path(project),
                Path('reports/flow109/requests') / (str(body.get('context_sha256')) + '.json'),
                'D15_PREDECESSOR_CONTEXT_ABSENT')
            prior = flow109.validate_execution_context(original)
            if prior['features'] != current['features'] or prior['requested_step'] != step:
                raise MetricRefusal('D15_PREDECESSOR_CONTEXT_FOREIGN', step)
            manifest = owner._d15_json(Path(project) / owner.D15_INPUT)
            if step == 'D05':
                power = owner._d05_prepare(project, prior)
                if body.get('input_sha256') != power['inputs']:
                    raise MetricRefusal('D15_D05_INPUT_STALE', 'accepted native readset differs')
                if power['manifest']['upf'] != manifest['upf']:
                    raise MetricRefusal('D15_D05_UPF_IDENTITY_MISMATCH', 'accepted power intent differs')
            else:
                inventory = body['evidence']['rtl_inventory']
                expected_rtl = {}
                for item in inventory:
                    relative = 'phase2/stage1/rtl/' + item['path']
                    if Path(relative).suffix not in ('.v', '.sv'):
                        continue
                    owner._d15_bound(project, {'path': relative, 'sha256': item['sha256']})
                    if relative in expected_rtl:
                        raise MetricRefusal('D15_D09_RTL_IDENTITY_MISMATCH', 'duplicate adopted RTL')
                    expected_rtl[relative] = item['sha256']
                actual_rtl = {r['path']: r['sha256'] for r in manifest['rtl']}
                if not expected_rtl or expected_rtl != actual_rtl:
                    raise MetricRefusal('D15_D09_RTL_IDENTITY_MISMATCH', 'complete accepted RTL population differs')
            dependencies[step] = ref
        result['accepted_dependencies'] = dependencies
        admitted = owner.d15_native_qualification(project, current, component['tool'])
        if component.get('launch_admission') != admitted:
            raise MetricRefusal('D15_ORIGINAL_EXECUTION_UNQUALIFIED',
                                'qualification must have been consumed before the original native launch')
        result.update(qualification='PASS', qualification_admission=admitted,
                      status=observed['status'], delivery_blocked=False)
        if observed.get('reason'):
            result['reason'] = observed['reason']
    except (flow109.Flow109Error, MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D15_PREDECESSOR_NOT_ACCEPTED'), detail=str(exc))
    return result


def accept_m89(project: Path, context: Mapping, component: Mapping) -> dict:
    """BLOCKING final mixed metrics; qualification remains independently owned."""
    from flow109_mixed_native import bind_metrics
    return bind_metrics(project, context, component)


def accept_d66(project: Path, context: Mapping, component: Mapping) -> dict:
    """Consume current D66 evidence; category coverage cannot imply pad physics."""
    import flow109_final_perc as owner
    project = Path(project).resolve()
    specs = {
        'final_perc.final_esd_supply_topology': {
            'operator': 'covers_all',
            'required_set_ref': 'requirements/final_perc/final_esd_supply_topology.json#/required_items'},
        'final_perc.final_perc_latchup_errors': {
            'operator': 'eq', 'value': 0, 'unit': 'count'},
    }
    result = {'schema': SCHEMA, 'row_id': 'D66', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'delivery_blocked': True, 'obligations': []}
    try:
        declared = context['resolved_row']['obligations']
        if (len(declared) != len(specs) or {r['id'] for r in declared} != set(specs)
                or any(any(r['expectation'].get(k) != v for k, v in specs[r['id']].items())
                       for r in declared)):
            raise MetricRefusal('METRIC_OBLIGATIONS_UNREGISTERED', 'D66')
        measurements = owner.metric_measurements(project, component['receipt'])
        record = owner._read(owner._bound(project, component['receipt'], 'D66 component'))
        if (record.get('execution_context') != context
                or record.get('context_sha256') != context.get('context_sha256')
                or record.get('component_status') != component.get('component_status')):
            raise MetricRefusal('METRIC_EXECUTION_EVIDENCE_INVALID', 'D66 context/result differs')
        for obligation in declared:
            oid = obligation['id']; spec = specs[oid]
            measurement = dict(measurements[oid])
            try:
                if measurement['status'] != 'MEASURED':
                    status, detail = measurement['status'], measurement['reason']
                    authority = None
                else:
                    if spec['operator'] == 'covers_all':
                        authority, _ = _approved_authority(project, spec['required_set_ref'], ('category',))
                    else:
                        authority = {'status': 'APPROVED', 'value': 0, 'unit': 'count',
                                     'source': 'flow109_registry_contract'}
                    measurement['identity'] = {
                        'producer': component['receipt'],
                        'checker': record['outputs'],
                        'tool_execution': record['runtime_image'],
                        'consumed_inputs': record['inputs'],
                        'requirements': authority,
                        'configuration': {'owner': record['operation_sources'],
                                          'consumer_sha256': _sha(Path(__file__).read_bytes())},
                    }
                    status, detail = evaluate_operator(spec['operator'], measurement, authority)
                result['obligations'].append({'id': oid, 'metric': obligation['metric'],
                    'operator': spec['operator'], 'status': status, 'detail': detail,
                    'measurement': measurement, 'authority': authority})
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                result['obligations'].append({'id': oid, 'status': 'NOT_MEASURED',
                    'reason': getattr(exc, 'code', 'METRIC_EXECUTION_EVIDENCE_INVALID'), 'detail': str(exc)})
        statuses = [r['status'] for r in result['obligations']]
        if 'FAIL' in statuses:
            result.update(status='FAIL', metric_status='FAIL')
        elif component.get('component_status') == 'FAIL':
            result['status'] = 'FAIL'
        elif statuses and all(s == 'PASS' for s in statuses):
            result['metric_status'] = 'PASS'
        result['reason'] = 'D66_COMPLETION_DEPENDENCIES_PENDING' if result['metric_status'] == 'PASS' else 'D66_METRIC_BINDINGS_INCOMPLETE'
    except (owner.AdmissionRefusal, MetricRefusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result['reason'] = getattr(exc, 'code', 'METRIC_EXECUTION_EVIDENCE_INVALID')
        result['detail'] = str(exc)
        result['obligations'] = [{'id': oid, 'status': 'NOT_MEASURED',
                                  'reason': result['reason']} for oid in specs]
        if component.get('component_status') == 'FAIL' or getattr(exc, 'status', None) == 'FAIL':
            result['status'] = 'FAIL'
    return result

def accept_d70(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """Read the D70 owner through its existing completion/metric consumer."""
    import flow109_final_electrical as final
    return final.accept_metric_obligations(project, context, component)


def _d0102_read(project: Path, relative: str, reads: dict, *, exact_numbers=False) -> dict:
    import phase1_expert_parse_track as expert
    raw = _safe_project_file(project, relative).read_bytes()
    try:
        value = json.loads(raw, parse_float=Decimal if exact_numbers else float,
                           object_pairs_hook=expert._PointerObject)
    except ArithmeticError as exc:
        raise MetricRefusal('D0102_INPUT_INVALID', relative) from exc
    if not isinstance(value, dict):
        raise MetricRefusal('D0102_INPUT_INVALID', relative)
    reads[relative] = _sha(raw)
    return value


def _d0102_documents(project: Path, reads: dict, *, include_owner_request: bool = False) -> dict:
    """Bind staged originals, not a generated extraction mirror."""
    docs = sorted(p for p in (project / 'input/docs').rglob('*') if p.is_file())
    if not docs:
        docs = [project / name for name in ('input/phase1_prompt.md',
                'input/phase1_structured.yaml') if (project / name).is_file()]
    if not docs:
        docs = sorted(p for p in (project / 'phase1/input_doc').rglob('*') if p.is_file())
    owner_request = project / 'input/owner_request.md'
    if include_owner_request and owner_request.is_file():
        docs.append(owner_request)
    if not docs:
        raise MetricRefusal('D0102_SOURCE_DOCUMENTS_ABSENT', 'staged originals required')
    decisions = project / 'input/feature-decisions.json'
    if decisions.is_file():
        docs.append(decisions)
    result = {p.relative_to(project).as_posix(): _sha(_safe_project_file(
        project, p.relative_to(project).as_posix()).read_bytes()) for p in docs}
    reads.update(result)
    return result


def _d0102_population(project: Path, key: str, metric: str, reads: dict) -> tuple:
    """Read existing approved requirements and the existing expert grammar.

    The input source owns the complete population. Neither checker success nor
    the generated declarations may shrink it or approve their own requirements.
    """
    reference = f'requirements/{key}/{metric}.json#/required_items'
    authority, body = _approved_authority(project, reference, ('id',))
    reads[authority['path']] = authority['sha256']
    source_ref = authority['source']
    if not source_ref['path'].startswith('input/'):
        raise MetricRefusal('D0102_REQUIREMENTS_SOURCE_FOREIGN', source_ref['path'])
    payload = _d0102_read(project, source_ref['path'], reads).get(metric)
    if not isinstance(payload, dict) or payload.get('required_items') != body['required_items']:
        raise MetricRefusal('D0102_SOURCE_POPULATION_DIFFERS', reference)
    refs = payload.get('source_documents')
    documents = _d0102_documents(project, reads, include_owner_request=(
        isinstance(refs, list) and any(isinstance(ref, dict)
            and ref.get('path') == 'input/owner_request.md' for ref in refs)))
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(r, dict) or set(r) != {'path', 'sha256'} for r in refs)
            or len({r['path'] for r in refs}) != len(refs)
            or {r['path']: r['sha256'] for r in refs} != documents):
        raise MetricRefusal('D0102_SOURCE_DOCUMENT_CENSUS_STALE', reference)
    expectations = payload.get('expectations')
    ids = [item['id'] for item in body['required_items']]
    if (not isinstance(expectations, list) or not expectations
            or any(not isinstance(e, dict) or not isinstance(e.get('id'), str) for e in expectations)
            or len(set(ids)) != len(ids)
            or len({e['id'] for e in expectations}) != len(expectations)
            or set(ids) != {e['id'] for e in expectations}):
        raise MetricRefusal('D0102_SOURCE_POPULATION_INCOMPLETE', reference)
    # This is the retained expert pack's path:line/hash/literal citation form.
    evidence_items = list(expectations)
    if key == 'base_01':
        features = payload.get('features')
        if (not isinstance(features, list) or not features
                or any(not isinstance(f, dict) or not isinstance(f.get('feature'), str)
                       or type(f.get('declared')) is not bool for f in features)):
            raise MetricRefusal('D0102_FEATURE_POPULATION_ABSENT', metric)
        evidence_items += [{**f, 'id': f['feature']} for f in features]
    for exp in evidence_items:
        evidence = exp.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise MetricRefusal('D0102_REQUIREMENT_SOURCE_ABSENT', exp['id'])
        for cite in evidence:
            match = re.fullmatch(r'(.+?):(\d+)\s+sha256:([0-9a-f]{64})\s+[—–-]\s+(.+)', str(cite))
            if match is None:
                raise MetricRefusal('D0102_REQUIREMENT_SOURCE_UNSUPPORTED', exp['id'])
            relative, line, digest, literal = match.groups()
            if relative.startswith('docs/'):
                relative = 'input/' + relative
            # The owner's answers file is a source too: it holds the attested delivery route.
            current = (_sha(_safe_project_file(project, relative).read_bytes())
                       if relative == 'input/step_0_5ic_answers.json' else documents.get(relative))
            if current != digest:
                raise MetricRefusal('D0102_REQUIREMENT_SOURCE_STALE', exp['id'])
            lines = (project / relative).read_text().splitlines()
            if not 1 <= int(line) <= len(lines) or literal not in lines[int(line) - 1]:
                raise MetricRefusal('D0102_REQUIREMENT_LITERAL_DIFFERS', exp['id'])
    return authority, payload


def _d0102_dimensionless(project: Path, expectation: dict, reads: dict) -> dict | None:
    import phase1_expert_parse_track as expert
    tokens = expectation.get('expected_tokens')
    if (not isinstance(tokens, list) or expectation.get(expert.SPLIT_KEY) is not None
            or 'qualified_by' in expectation
            or str(expectation.get('id', '')).startswith('qualified_by:')):
        return None
    numbers = [t for t in tokens if t not in ('', '—', '-')]
    quantities = [expert.parse_quantity(token) for token in numbers]
    if not numbers or any(quantity is None or quantity.dimension not in (None, 'dimensionless')
                          for quantity in quantities):
        return None
    explicit_unit = any(t in ('', '—', '-') for t in tokens)
    quantity_fields = ('value', 'target', 'typ', 'min', 'max')
    item = expert.converge_ai_expectation(project, {**expectation, 'expected_tokens': numbers})
    if (item.get('usable') is not True or item.get('layer_present') is not True
            or item.get('layer_in_taxonomy') is False
            or item.get('field_path_status') != 'DECLARED' or item.get('tokens_unaskable')):
        if explicit_unit:
            item.update(usable=False, met=False)
        return item
    try:
        path = expert.resolve_layer_file(project, expectation['layer'])
        document = _d0102_read(project, path.relative_to(project).as_posix(), reads,
                                exact_numbers=True)
        selected = expert._scoped_nodes_at(document, expectation.get('field_path'),
                                           expectation['layer'])
        if not selected:
            raise MetricRefusal('D0102_OBSERVATION_UNRESOLVED', str(expectation))
        values = [node.value for node in selected]
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        item.update(usable=False, met=False, observed=str(exc))
        return item
    unit = expert._record_unit(values[0], selected[0].unit) \
        if len(values) == 1 and isinstance(values[0], dict) else None
    dimensionless = unit in (None, ('dimensionless', 0))
    if not explicit_unit and (len(values) != 1 or not isinstance(values[0], dict)
                             or not dimensionless
                             or not any(key in values[0] for key in quantity_fields)):
        return None
    if (len(values) != 1 or not isinstance(values[0], dict)
            or not dimensionless):
        item.update(usable=False, met=False, observed='Expected a dimensionless quantity record.')
        return item
    observed = {key: values[0][key] for key in quantity_fields
                if type(values[0].get(key)) in (int, float, Decimal)}
    if not observed or any(not Decimal(str(value)).is_finite() for value in observed.values()):
        item.update(usable=False, met=False, observed='Dimensionless quantity has no finite numeric value.')
        return item
    units = expert._haystack_units(observed, selected[0].key, unit)
    missing = [token for token in numbers if not expert.present_in_units(token, units)]
    item.update(met=not missing, missing_tokens=missing,
                observed=f'Dimensionless numeric values {observed} compared with {numbers}.')
    return item


def _d0102_compare(project: Path, payload: dict, reads: dict) -> tuple:
    import phase1_expert_parse_track as expert
    actual, unresolved, unrouted = [], [], []
    for exp in payload['expectations']:
        # The actual comparator discards submitted met/observed/usable fields.
        item = _d0102_dimensionless(project, exp, reads)
        if item is None:
            item = expert.converge_ai_expectation(project, exp)
        if (item.get('usable') is not True
                or item.get('layer_in_taxonomy') is False
                or item.get('tokens_unaskable')):
            unresolved.append(item)
        else:
            # A token found in another field cannot discharge the named route.
            if item.get('layer_present') is False or item.get('field_path_status') == 'UNDECLARED':
                unrouted.append(exp['id'])
            elif item.get('met') is True:
                actual.append({'id': exp['id']})
    for path in expert.emitted_layer_files(project):
        _d0102_read(project, path.relative_to(project).as_posix(), reads)
    return actual, unresolved, unrouted


def _d0102_value(project: Path, item: dict, reads: dict) -> list:
    import phase1_expert_parse_track as expert
    path = (project / item['source'] if item.get('source') == 'input/feature-decisions.json'
            else expert.resolve_layer_file(project, item.get('layer', '')))
    if path is None:
        raise MetricRefusal('D0102_OBSERVATION_ABSENT', str(item))
    doc = _d0102_read(project, path.relative_to(project).as_posix(), reads)
    values = expert.subtree_at(doc, item.get('field_path'), item.get('layer'))
    if not isinstance(values, list) or not values:
        raise MetricRefusal('D0102_OBSERVATION_UNRESOLVED', str(item))
    return values


def _d0102_addresses(expectation: dict) -> set:
    children = expectation.get('sub_expectations')
    if isinstance(children, list) and children:
        return set().union(*(_d0102_addresses(child) for child in children))
    return {(expectation.get('layer'), expectation.get('field_path'))}


def _d0102_submission_lineage(project: Path, record: Mapping, reads: dict) -> dict:
    """Read the original submission producer's preimage and own publication."""
    import step_output_collector as versions
    folder = f"{record.get('storage_root', 'steps')}/{record['folder']}"
    original = _d0102_read(project, folder + '/outputs.json', reads)
    result = original.get('result') or {}
    if (original.get('id') != '0.5ic' or original.get('canonical_pass') is not True
            or original.get('status') != 'PASS' or original.get('capture_errors')
            or result.get('runner') != 'phase1_one_shot_runner'
            or result.get('site') != '_run_step_0_5ic'
            or type(result.get('producer_return')) is not int
            or result.get('producer_return') != 0
            or (result.get('canonical_consumer') or {}).get('status') != 'PASS'):
        raise MetricRefusal('D0102_SUBMISSION_LINEAGE_UNBOUND', folder)
    changed = []
    for relative, expected in original.get('inputs', {}).items():
        current = _sha(_safe_project_file(project, relative).read_bytes())
        if current != expected:
            changed.append(relative)
    answer = 'input/step_0_5ic_answers.json'
    if changed != [answer]:
        raise MetricRefusal('D0102_SUBMISSION_INPUT_CHANGED', str(changed))
    before = next((r for r in original.get('input_files', ()) if r.get('rel') == answer), {})
    after = next((r for r in original.get('written_files', ()) if r.get('rel') == answer), {})
    for entry, expected in ((before, original['inputs'][answer]),
                             (after, _sha(_safe_project_file(project, answer).read_bytes()))):
        if (entry.get('sha256') != expected or not isinstance(entry.get('snapshot'), str)
                or _sha(_safe_project_file(project, folder + '/' + entry['snapshot']).read_bytes()) != expected):
            raise MetricRefusal('D0102_SUBMISSION_PUBLICATION_UNBOUND', answer)
        reads[folder + '/' + entry['snapshot']] = expected
    old_answer = _d0102_read(project, folder + '/' + before['snapshot'], reads)
    new_answer = _d0102_read(project, answer, reads)
    # Only the existing program-owned area publication may extend this input.
    # All owner route/operator answers remain exact values, not inferred limits.
    import copy
    old, new = copy.deepcopy(old_answer), copy.deepcopy(new_answer)
    for value in (old, new):
        value.get('answers', {}).pop('synthesis_area_budget', None)
        value.pop('synthesis_area_budget', None)
        value.get('answer_provenance', {}).pop('synthesis_area_budget', None)
        value.pop('answer_revisions', None)
    if old != new:
        raise MetricRefusal('D0102_SUBMISSION_OWNER_INPUT_CHANGED', answer)
    import area_budget_basis_gen as area
    expected = area.rederive(project, new_answer)
    if (expected.get('answer') != new_answer.get('answers', {}).get(area.KEY)
            or (area.KEY in new_answer and expected.get('answer') != new_answer[area.KEY])
            or expected.get('provenance') != new_answer.get('answer_provenance', {}).get(area.KEY)):
        raise MetricRefusal('D0102_SUBMISSION_AREA_AUTHORITY_STALE', answer)
    for output in original.get('outputs', ()):
        current = _sha(_safe_project_file(project, output['rel']).read_bytes())
        if current != output['sha256']:
            raise MetricRefusal('D0102_CANONICAL_OUTPUTS_STALE', output['rel'])
        reads[output['rel']] = current
    return {'path': folder + '/outputs.json', 'sha256': reads[folder + '/outputs.json']}


def _accept_d0102(project: Path, context: Mapping, step: str) -> dict:
    import flow109
    import _delivery_route as route
    result = {'schema': SCHEMA, 'step_id': step, 'status': 'NOT_MEASURED',
              'qualification': 'NOT_MEASURED', 'delivery_blocked': True,
              'obligations': [], 'reason': 'D0102_EVIDENCE_ABSENT', 'consumed_inputs': {}}
    reads = result['consumed_inputs']
    try:
        project = Path(project).resolve()
        current = flow109.validate_execution_context(context)
        if current['resolved_row']['id'] != step:
            raise MetricRefusal('D0102_CONTEXT_DIFFERS', step)
        key, metric = ('base_01', 'requirements_trace') if step == 'D01' else ('base_02', 'endpoint_delivery_items')
        authority, payload = _d0102_population(project, key, metric, reads)
        actual, unresolved, unrouted = _d0102_compare(project, payload, reads)
        identity = {'producer': {'source_documents': payload['source_documents']},
                    'checker': {name: _sha((HERE / name).read_bytes()) for name in
                                ('flow109_metric_acceptance.py', 'phase1_expert_parse_track.py')},
                    'tool_execution': {'kind': 'retained observations; expert comparator replay'},
                    'consumed_inputs': dict(reads), 'requirements': authority,
                    'configuration': {'step_id': step, 'context_sha256': current['context_sha256']}}
        def add(name, value, operator='eq', approved=None):
            measured = {'status': 'MEASURED', 'value': value, 'identity': identity,
                        **({'unit': 'count'} if operator == 'eq' else {})}
            status, reason = evaluate_operator(operator, measured, approved or {
                'status': 'APPROVED', 'value': 0, 'unit': 'count',
                'source': 'flow109 registry invariant'})
            result['obligations'].append({'id': f'{key}.{name}', 'status': status,
                                         'reason': reason, 'measurement': measured})
        if unresolved:
            result['unresolved_expectations'] = unresolved
            raise MetricRefusal('D0102_UNSUPPORTED_REQUIREMENT', 'existing comparator could not decide')
        add(metric, actual, 'covers_all', authority)
        route_label = route.report_label(project)
        endpoint = route_label.get('deliverable')
        if endpoint not in ('DIE', 'HARDMACRO', 'SOFT_IP', 'RTL'):
            raise MetricRefusal('D0102_ROUTE_UNRESOLVED', str(endpoint))
        expected_route = ('IC' if current['features'].get('ic') else
                          'IP' if current['features'].get('ip') else 'RTL')
        if route_label.get('delivery_route') != expected_route:
            result['status'] = 'FAIL'
            raise MetricRefusal('D0102_ROUTE_CONTRADICTION', f'{route_label} vs {expected_route}')
        if step == 'D01':
            # Every source-owned requirement must have a usable owning route.
            add('unresolved_route_facts', len(unrouted))
            features = payload.get('features')
            if (not isinstance(features, list) or not features
                    or any(not isinstance(f, dict) or not isinstance(f.get('feature'), str) for f in features)
                    or len({f['feature'] for f in features}) != len(features)):
                raise MetricRefusal('D0102_FEATURE_POPULATION_ABSENT', metric)
            mismatches = []
            for item in features:
                declared, observed = current['features'].get(item['feature']), _d0102_value(project, item, reads)
                if type(declared) is not bool or len(observed) != 1 or type(observed[0]) is not bool:
                    raise MetricRefusal('D0102_FEATURE_UNRESOLVED', item['feature'])
                if observed[0] != item['declared'] or declared != item['declared']:
                    mismatches.append({'feature': item['feature'], 'declared': item['declared'],
                                       'selected': declared, 'observed': observed[0]})
            result['feature_mismatches'] = mismatches
            add('observed_vs_declared_features', len(mismatches))
        else:
            _, requirements = _d0102_population(project, 'base_01', 'requirements_trace', reads)
            required = {e['id'] for e in requirements['expectations']}
            assignments = payload.get('assignments')
            if not isinstance(assignments, list) or any(not isinstance(a, dict) for a in assignments):
                raise MetricRefusal('D0102_ASSIGNMENTS_UNOBSERVED', metric)
            ids = [a.get('id') for a in assignments]
            if len(set(ids)) != len(ids) or any(i not in required for i in ids):
                raise MetricRefusal('D0102_ASSIGNMENTS_INVALID', metric)
            assigned = set()
            for item in assignments:
                owner = next(e for e in requirements['expectations'] if e['id'] == item['id'])
                if (item.get('layer'), item.get('field_path')) not in _d0102_addresses(owner):
                    raise MetricRefusal('D0102_ASSIGNMENT_FOREIGN', item['id'])
                values = _d0102_value(project, item, reads)
                if any(v in (None, '', 'NOT_DETERMINED', 'UNKNOWN', [], {}) for v in values):
                    raise MetricRefusal('D0102_ASSIGNMENT_UNRESOLVED', item['id'])
                if item.get('endpoint') == endpoint:
                    assigned.add(item['id'])
            add('unassigned_requirements', len(required - assigned))
        result['metric_status'] = 'FAIL' if any(o['status'] == 'FAIL' for o in result['obligations']) else 'PASS'
        result['qualification'] = result['metric_status']
        result['status'] = result['metric_status']
        result['reason'] = 'D0102_CURRENT_METRICS_' + result['status']
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D0102_EVIDENCE_UNAVAILABLE'), detail=str(exc))
    if any(o['status'] == 'FAIL' for o in result['obligations']):
        result['status'] = 'FAIL'
    try:
        for relative, digest in reads.items():
            if _sha(_safe_project_file(project, relative).read_bytes()) != digest:
                raise MetricRefusal('D0102_INPUT_CHANGED_DURING_READ', relative)
    except (OSError, MetricRefusal) as exc:
        result.update(status='NOT_MEASURED', qualification='NOT_MEASURED', reason=str(exc))
    result['delivery_blocked'] = result['status'] != 'PASS'
    return result


def accept_d01(project: Path, context: Mapping[str, Any]) -> dict:
    """Complete existing Step 1 metrics from current source-owned observations."""
    return _accept_d0102(project, context, 'D01')


def accept_d02(project: Path, context: Mapping[str, Any]) -> dict:
    """Complete existing Step 2 metrics without regenerating its inputs."""
    return _accept_d0102(project, context, 'D02')


def d38_target_binding(project: Path) -> dict:
    """Bind approved planning targets to CTS requirements before execution.

    ABI matches clock-plan PR3762 head9f72f92d: the requirements source is the
    exact planning-targets file, and its two max limits equal those targets.
    No CTS PASS or planning-row PASS is required to bind this forward input.
    """
    project = Path(project).resolve()
    source = 'input/flow109/D34/clock_planning_targets.json'
    relative = 'requirements/base_25/clock_skew_insertion_drv.json'
    authority, body = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
    target = _safe_project_file(project, source)
    raw = target.read_bytes()
    reference = {'path': source, 'sha256': _sha(raw)}
    requirement = _safe_project_file(project, relative)
    if authority['source'] != reference or _sha(requirement.read_bytes()) != authority['sha256']:
        raise MetricRefusal('D38_TARGET_SOURCE_UNBOUND', source)
    plan = json.loads(raw)
    keys = {'clock_skew_ns', 'insertion_delay_ns'}
    drv = {'design__max_slew_violation__count', 'design__max_cap_violation__count',
           'design__max_fanout_violation__count'}
    limits, units = body['limits'], body['units']
    if (not isinstance(plan, dict) or not isinstance(plan.get('targets'), dict)
            or not isinstance(limits, dict) or not isinstance(units, dict)
            or set(limits) != set(units) or not keys <= set(limits) <= keys | drv
            or set(plan.get('targets', {})) != keys or plan.get('units') != {k: 'ns' for k in keys}):
        raise MetricRefusal('D38_TARGET_SHAPE_UNSUPPORTED', relative)
    for key in keys:
        _finite_number(plan['targets'][key])
        if (not isinstance(limits[key], dict) or not set(limits[key]) <= {'min', 'max'}
                or limits[key].get('max') != plan['targets'][key] or units[key] != plan['units'][key]):
            raise MetricRefusal('D38_TARGET_LIMITS_DIFFER', key)
        for value in limits[key].values():
            _finite_number(value)
        if limits[key].get('min', limits[key]['max']) > limits[key]['max']:
            raise MetricRefusal('D38_TARGET_LIMITS_DIFFER', key)
    for key in set(limits) & drv:
        if (not isinstance(limits[key], dict) or not limits[key]
                or not set(limits[key]) <= {'min', 'max'} or units[key] != 'count'):
            raise MetricRefusal('D38_DRV_BOUNDS_INVALID', key)
        for value in limits[key].values():
            _finite_number(value, count=True)
        if limits[key].get('min', 0) > limits[key].get('max', limits[key].get('min', 0)):
            raise MetricRefusal('D38_DRV_BOUNDS_INVALID', key)
    clock_path = 'phase3/stage3/cts/clock_plan.json'
    clock_raw = _safe_project_file(project, clock_path).read_bytes()
    clocks = [entry['name'] for entry in json.loads(clock_raw)['clocks']]
    if not clocks or len(set(clocks)) != len(clocks) or any(not isinstance(c, str) or not c for c in clocks):
        raise MetricRefusal('D38_CLOCK_POPULATION_ABSENT', clock_path)
    return json.loads(json.dumps({'targets': reference, 'requirements': authority,
        'limits': limits, 'units': units, 'clock_plan': {'path': clock_path, 'sha256': _sha(clock_raw)},
        'clocks': clocks}))

def _d38_clock_network_latency(text: str, required_clocks: list[str]) -> dict:
    """Read OpenSTA clock.rpt network latency, excluding SDC source latency.

    The native report prints separate source/network/total latency rows. Only
    the network rows are physical insertion measurements. Missing clocks are
    retained as missing by the caller, never assigned zero.
    """
    blocks = re.split(r'(?m)^Clock:\s*([^\n]+)\s*$', text)
    result = {}
    number = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    for name, block in zip(blocks[1::2], blocks[2::2]):
        name = name.strip()
        if name not in required_clocks or name in result:
            raise MetricRefusal('D38_CLOCK_REPORT_FOREIGN', name)
        if 'report_clock_latency' not in block or 'report_clock_min_period' not in block:
            continue
        section = block.partition('report_clock_latency')[2].partition('report_clock_min_period')[0]
        values = [float(v) for v in re.findall(r'^\s*(' + number + r')\s+network latency\s+\S+\s*$', section, re.M)]
        if values and len(values) % 2 == 0:
            for value in values:
                _finite_number(value)
            result[name] = max(values)
    return result

def _d38_sink_roster(text: str) -> dict:
    """Read the complete native post-load census, including unclocked pins."""
    import _physical_current as native_census
    if (text.splitlines().count('CLOCK_PLAN_ROSTER_BEGIN') != 1
            or text.splitlines().count('CLOCK_PLAN_DONE') != 1):
        raise MetricRefusal('D38_SINK_ROSTER_INCOMPLETE', 'native census did not close exactly once')
    lines = text.splitlines()
    start, end = lines.index('CLOCK_PLAN_ROSTER_BEGIN'), lines.index('CLOCK_PLAN_DONE')
    if end <= start:
        raise MetricRefusal('D38_SINK_ROSTER_INCOMPLETE', 'native census order')
    body = '\n'.join(lines[start + 1:end])
    clocks = re.findall(r'^CLOCK_PLAN_NATIVE ([^|\n]+)\|([^|\n]+)\|([^\n]+)$', body, re.M)
    names = [name for name, _, _ in clocks]
    if not names or len(set(names)) != len(names):
        raise MetricRefusal('D38_SINK_CLOCK_POPULATION_INVALID', 'native clock identities')
    for name, period, sources in clocks:
        if not name.strip() or _finite_number(float(period)) <= 0 or not sources.strip():
            raise MetricRefusal('D38_SINK_CLOCK_POPULATION_INVALID', name)
    all_pins = re.findall(r'^CLOCK_PLAN_ALL_SINK ([^\n]+)$', body, re.M)
    counts = re.findall(r'^CLOCK_PLAN_ALL_SINK_COUNT (\d+)$', body, re.M)
    if (len(counts) != 1 or int(counts[0]) != len(all_pins)
            or len(set(all_pins)) != len(all_pins) or any(not p.strip() for p in all_pins)):
        raise MetricRefusal('D38_SINK_UNIVERSE_INCOMPLETE', 'all native register clock pins')
    counted = re.findall(r'^CLOCK_PLAN_SINK_COUNT ([^|\n]+)\|(\d+)$', body, re.M)
    if len(counted) != len(names) or len({name for name, _ in counted}) != len(names):
        raise MetricRefusal('D38_SINK_ROSTER_INCOMPLETE', 'per-clock census')
    domains = native_census.clock_plan_sinks(body, names)
    reached = {pin for pins in domains.values() for pin in pins}
    if not reached <= set(all_pins):
        raise MetricRefusal('D38_SINK_UNIVERSE_INCOMPLETE', 'clock member outside native pin universe')
    return {'clocks': domains, 'unclocked': sorted(set(all_pins) - reached),
            'all_pins': sorted(all_pins)}


def _d38_sink_authority(project: Path, specification: dict, read) -> tuple[dict, dict]:
    """Bind the existing required set to D34's independently adopted census."""
    import flow109_clock_plan as planning
    reference = specification['expectation']['required_set_ref']
    if reference != 'requirements/base_25/clock_tree_sink_coverage.json#/required_items':
        raise MetricRefusal('D38_SINK_CONTRACT_CHANGED', reference)
    adopted, body = _approved_document(project, planning.SINK_REFERENCE,
        authority='requirements_owner', schema='vibeic.flow109.adopted-reference.v1')
    read(planning.SINK_REFERENCE, adopted['sha256'])
    _, raw_source = read(planning.SINK_SOURCE, adopted['source']['sha256'])
    if (adopted['source']['path'] != planning.SINK_SOURCE
            or json.loads(raw_source).get('clock_sink_inventory') !=
                {k: v for k, v in body.items() if k not in ('schema', 'approval')}):
        raise MetricRefusal('D38_SINK_REFERENCE_SOURCE_UNBOUND', planning.SINK_SOURCE)
    census = body.get('reference')
    if (not isinstance(census, dict) or set(census) != {'clocks', 'unclocked'}
            or not isinstance(census['clocks'], dict) or not census['clocks']
            or not isinstance(census['unclocked'], list)
            or any(not isinstance(c, str) or not c or not isinstance(pins, list)
                   or len(set(pins)) != len(pins) or any(not isinstance(p, str) or not p for p in pins)
                   for c, pins in census['clocks'].items())
            or any(not isinstance(p, str) or not p for p in census['unclocked'])):
        raise MetricRefusal('D38_SINK_REFERENCE_SHAPE', planning.SINK_REFERENCE)
    _identity_complete(body.get('reference_identity'))
    for name, digest in body['reference_identity']['consumed_inputs'].items():
        read(name, digest, external=True)
    authority, requirement = _approved_authority(project, reference, ('clock', 'pin'))
    read(authority['path'], authority['sha256'])
    read(authority['source']['path'], authority['source']['sha256'])
    allowed = [adopted['source'], {'path': planning.SINK_REFERENCE, 'sha256': adopted['sha256']}]
    expected = [{'clock': clock, 'pin': pin} for clock, pins in sorted(census['clocks'].items()) for pin in sorted(pins)]
    if (authority['source'] not in allowed
            or sorted(authority['required_items'], key=_json_key) != sorted(expected, key=_json_key)):
        raise MetricRefusal('D38_SINK_REQUIRED_SET_NOT_ADOPTED', 'exact independent D34 clock/pin population')
    if not requirement['required_items']:
        absence = requirement['validated_absence']['source_reference']
        read(absence['path'], absence['sha256'])
    return authority, census


def accept_d38(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """BLOCKING CTS metric readback against the exact prelaunch authority.

    The actual per-corner native session emits every clock-reached sink pin
    and the full register-clock-pin universe. Compare with independently
    adopted D34 requirements, then reuse existing admission. Planning targets
    never substitute for actual skew/network-insertion/DRV measurements.
    """
    import flow109
    import inspect
    import gzip
    import librelane_contract as ll
    import _librelane_cts_hold_evidence as reader

    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D38', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    reads = {}

    def read(name, digest=None, external=False):
        path = Path(name)
        path = path if path.is_absolute() else project / path
        if path.is_symlink() or not path.is_file() or (not external and not path.resolve().is_relative_to(project)):
            raise MetricRefusal('D38_INPUT_UNBOUND', str(path))
        raw = path.read_bytes()
        actual = _sha(raw)
        if digest is not None and digest != actual:
            raise MetricRefusal('D38_INPUT_CHANGED', str(path))
        key = str(path.relative_to(project)) if path.is_relative_to(project) else str(path)
        if key in reads and reads[key] != actual:
            raise MetricRefusal('D38_INPUT_CHANGED_DURING_READ', key)
        reads[key] = actual
        return path, raw

    def document(name, digest=None):
        path, raw = read(name, digest)
        return path, json.loads(raw)

    try:
        current = flow109.validate_execution_context(context)
        row = current['resolved_row']
        if (row['id'] != 'D38' or [o['metric'] for o in row['obligations']] !=
                ['clock_tree_sink_coverage', 'clock_skew_insertion_drv']
                or row['obligations'][0]['expectation'].get('operator') != 'covers_all'
                or row['obligations'][1]['expectation'] != {
                    'operator': 'within_declared_bounds',
                    'bounds_ref': 'requirements/base_25/clock_skew_insertion_drv.json#/limits',
                    'unit_ref': 'requirements/base_25/clock_skew_insertion_drv.json#/units', 'missing_bounds': 'BLOCKED'}):
            raise MetricRefusal('D38_CONTRACT_CHANGED', 'CTS obligations')
        numerical = {'id': row['obligations'][1]['id'], 'status': 'NOT_MEASURED', 'measurements': []}
        coverage = {'id': row['obligations'][0]['id'], 'status': 'NOT_MEASURED'}
        result['obligations'] = [coverage, numerical]
        binding = d38_target_binding(project)
        if component.get('flow109_d38_targets') != binding:
            raise MetricRefusal('D38_PRELAUNCH_TARGET_BINDING_ABSENT', 'producer binding')
        for ref in [binding['targets'], binding['requirements'], binding['clock_plan']]:
            read(ref['path'], ref['sha256'])
        _, handoff = document('reports/phase3/librelane_cts_handoff.json')
        corners = handoff['corners']
        ids = ['OpenROAD.CTS', 'Vibeic.ClockPathDriveSizing', 'Vibeic.ExternalCaptureLaunchRetap']
        if (handoff.get('flow109_d38_targets') != binding or handoff['image'] != component.get('native_image')
                or not component.get('native_image') or not isinstance(corners, list) or not corners
                or any(not isinstance(c, str) or not c or '/' in c for c in corners)
                or len(set(corners)) != len(corners) or handoff['steps'] != ids + ['OpenROAD.STAMidPNR'] * len(corners)):
            raise MetricRefusal('D38_NATIVE_CHAIN_UNBOUND', 'CTS handoff')
        previous, _ = read(handoff['initial_state'], handoff['initial_sha256'])
        base = project / 'phase3/librelane/execution-backend-19'
        states, executions, ns_libraries, selected_configs = [], [], [], []
        configs = handoff.get('step_configs')
        if configs is not None and len(configs) != len(handoff['steps']):
            raise MetricRefusal('D38_CONFIG_POPULATION_CHANGED', 'selected native configs')
        for index, step in enumerate(handoff['steps'], 1):
            folder = base / (f'{index:02d}-' + step.lower().replace('.', '-'))
            receipt = ll.validate_step_receipt(folder, step)
            read(folder / 'vibeic_receipt.json')
            for name, digest in receipt['sha256'].items():
                read(folder / name, digest)
            fp = receipt['input']
            if fp['image'] != component['native_image'] or fp['step'] != step:
                raise MetricRefusal('D38_EXECUTION_CHANGED', step)
            if step.startswith(ll.PLUGIN_STEP_PREFIX) and fp.get('plugin') != ll._plugin_digests(step):
                raise MetricRefusal('D38_PRODUCER_SOURCE_CHANGED', step)
            read(previous, fp['state'])
            suffix = '@' + corners[index - 4] if index > 3 else ''
            cfgroot = project / 'phase3/librelane/execution-backend-19-config'
            if configs is not None:
                config_path, config = document(configs[index - 1]['path'], configs[index - 1]['sha256'])
                if config_path.parent != cfgroot or configs[index - 1]['sha256'] != fp['config']:
                    raise MetricRefusal('D38_CONFIG_POPULATION_CHANGED', step)
            else:
                # Older partial receipts can retain numerical readback. They
                # still cannot manufacture the newly required native roster.
                _, config = document(cfgroot / (step + suffix + '.json'), fp['config'])
            selected_configs.append(config)
            if (config.get('STA_CORNERS') != corners or (index > 3 and config.get('PNR_CORNERS') != [corners[index - 4]])):
                raise MetricRefusal('D38_CORNER_POPULATION_CHANGED', step)
            before = json.loads(previous.read_bytes())
            inputs = {str(p): _sha(p.read_bytes()) for p in ll._walk_paths({k: v for k, v in before.items() if k != 'metrics'})}
            if not inputs or inputs != fp['state_files']:
                raise MetricRefusal('D38_STATE_POPULATION_CHANGED', step)
            for name, digest in inputs.items():
                read(name, digest)
            _, pdk = document(folder / 'pdk_root.json')
            mounts = pdk['mounts_under_it']
            if not fp['config_files'] or ll.config_file_hashes(config, mounts) != fp['config_files']:
                raise MetricRefusal('D38_MODEL_POPULATION_CHANGED', step)
            for name, digest in fp['config_files'].items():
                path = Path(name)
                for host, guest in sorted(mounts, key=lambda m: len(m[1]), reverse=True):
                    if path.is_relative_to(guest):
                        path = Path(host) / path.relative_to(guest)
                        break
                _, raw = read(path, digest, external=True)
                if str(path).endswith(('.lib', '.lib.gz')):
                    text = (gzip.decompress(raw) if str(path).endswith('.gz') else raw).decode()
                    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
                    units = re.findall(r'\btime_unit\s*:\s*"([^"\n]+)"\s*;', text)
                    ns_libraries.append(bool(units) and all(unit == '1ns' for unit in units))
            previous, state = document(folder / 'state_out.json', receipt['sha256']['state_out.json'])
            states.append(state)
            executions.append({'step': step, 'input': fp,
                'receipt_sha256': _sha((folder / 'vibeic_receipt.json').read_bytes())})
        final, _ = read(handoff['measured_state'], handoff['measured_state_sha256'])
        if final != previous:
            raise MetricRefusal('D38_HANDOFF_FOREIGN', 'terminal native measurement')
        for view, name in [('def', 'post_cts.def'), ('odb', 'post_cts.odb')]:
            ref = handoff['views']['post_cts_' + view]
            src, _ = read(ref['source'], ref['source_sha256'])
            dest, _ = read(ref['dest'], ref['dest_sha256'])
            if (states[2].get(view) != str(src) or any(s.get(view) != str(src) for s in states[3:])
                    or dest != project / 'phase3/stage3/pnr' / name or ref['source_sha256'] != ref['dest_sha256']):
                raise MetricRefusal('D38_HANDOFF_FOREIGN', view)
        identity = {'producer': executions, 'checker': {'program': 'accept_d38',
            'sha256': _sha(inspect.getsource(accept_d38).encode()),
            'latency_reader_sha256': _sha(inspect.getsource(_d38_clock_network_latency).encode())},
            'tool_execution': executions, 'consumed_inputs': dict(reads), 'requirements': binding['requirements'],
            'configuration': {'context_sha256': current['context_sha256'], 'targets': binding['targets']}}

        failures = (MetricRefusal, ll.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError)
        try:
            def judge(field, values, complete, unit):
                entry = {'field': field, 'status': 'NOT_MEASURED'}
                numerical['measurements'].append(entry)
                if not values or field not in binding['limits']:
                    entry['reason'] = 'D38_NATIVE_VALUE_OR_APPROVED_BOUND_ABSENT'
                    return
                for value in values:
                    _finite_number(value, count=unit == 'count')
                measured = {'status': 'MEASURED', 'value': max(values), 'unit': unit, 'identity': identity}
                status, reason = evaluate_operator('within_declared_bounds', measured,
                    {'status': 'APPROVED', 'limits': binding['limits'][field], 'unit': binding['units'][field]})
                entry.update(status=status if complete or status == 'FAIL' else 'NOT_MEASURED',
                             reason=reason, measurement=measured, population_complete=complete)

            skews, latencies = [], []
            for index, corner in enumerate(corners):
                ev = {'corners': [corner], 'metrics': states[index + 3].get('metrics', {})}
                for key in ('clock__skew__worst_setup', 'clock__skew__worst_hold'):
                    value = reader.per_corner(ev, key)[corner]
                    if value is not None:
                        skews.append(abs(_finite_number(value)))
            judge('clock_skew_ns', skews, len(skews) == 2 * len(corners), 'ns')
            for field in ('design__max_slew_violation__count', 'design__max_cap_violation__count', 'design__max_fanout_violation__count'):
                values = [s.get('metrics', {}).get(field) for s in states[3:]]
                judge(field, [v for v in values if v is not None], all(v is not None for v in values), 'count')
            for index, corner in enumerate(corners):
                folder = base / (f'{index + 4:02d}-openroad-stamidpnr')
                _, log = read(folder / 'invocation.log')
                propagation = log.decode().lower()
                if 'unpropagating all clocks' in propagation or 'propagating all clocks' not in propagation:
                    raise MetricRefusal('D38_PROPAGATED_CLOCK_MEASUREMENT_UNPROVEN', corner)
                _, raw = read(folder / corner / 'clock.rpt')
                if not ns_libraries or not all(ns_libraries):
                    raise MetricRefusal('D38_CLOCK_REPORT_TIME_UNIT_UNSUPPORTED', corner)
                measured = _d38_clock_network_latency(raw.decode(), binding['clocks'])
                latencies.extend(measured.values())
            judge('insertion_delay_ns', latencies, len(latencies) == len(corners) * len(binding['clocks']), 'ns')
            numerical['status'] = ('FAIL' if any(v['status'] == 'FAIL' for v in numerical['measurements']) else
                'PASS' if all(v['status'] == 'PASS' for v in numerical['measurements']) else 'NOT_MEASURED')
        except failures as exc:
            numerical['status'] = ('FAIL' if any(v['status'] == 'FAIL' for v in numerical['measurements']) else 'NOT_MEASURED')
            numerical.update(reason=getattr(exc, 'code', 'D38_NUMERICAL_UNMEASURED'), detail=str(exc))
        try:
            import execution_backend_producers as producer
            rosters = []
            for index, corner in enumerate(corners):
                folder = base / (f'{index + 4:02d}-openroad-stamidpnr')
                callback = selected_configs[index + 3].get('STA_EXTRA_CORNER_TCL_FILE')
                expected = project / 'phase3/librelane/execution-backend-19-config/cts_sink_roster.tcl'
                path, script = read(callback) if isinstance(callback, str) else (None, b'')
                if path != expected or script.decode() != producer._d38_sink_report_tcl():
                    raise MetricRefusal('D38_NATIVE_SINK_EMITTER_UNBOUND', corner)
                _, log = read(folder / 'invocation.log')
                rosters.append(_d38_sink_roster(log.decode()))
            coverage['observed_rosters'] = dict(zip(corners, rosters))
            authority, reference = _d38_sink_authority(project, row['obligations'][0], read)
            measurements = []
            coverage['measurements'] = measurements
            for corner, roster in zip(corners, rosters):
                values = [{'clock': clock, 'pin': pin} for clock, pins in sorted(roster['clocks'].items()) for pin in pins]
                measurement = {'status': 'MEASURED', 'value': values, 'unit': 'set',
                    'identity': {**identity, 'requirements': authority, 'consumed_inputs': dict(reads),
                        'configuration': {**identity['configuration'], 'corner': corner}}}
                status, reason = evaluate_operator('covers_all', measurement, authority)
                required_clocks = {pin: {c for c, pins in reference['clocks'].items() if pin in pins}
                                   for pin in {p for pins in reference['clocks'].values() for p in pins}}
                observed_clocks = {pin: {c for c, pins in roster['clocks'].items() if pin in pins}
                                   for pin in required_clocks}
                # The registered operator is covers_all. Keep the complete
                # observation (including unused tied-off spare clock pins),
                # without promoting extra observed pins into requirements.
                if (set(roster['clocks']) != set(reference['clocks'])
                        or set(roster['clocks']) != set(binding['clocks'])
                        or reference['unclocked'] or observed_clocks != required_clocks):
                    status, reason = 'FAIL', 'required native clock association/unreached pin differs from adopted reference'
                measurements.append({'corner': corner, 'status': status, 'reason': reason, 'measurement': measurement})
            statuses = [m['status'] for m in measurements]
            coverage['status'] = 'FAIL' if 'FAIL' in statuses else 'PASS' if statuses and all(s == 'PASS' for s in statuses) else 'NOT_MEASURED'
        except failures as exc:
            coverage.update(reason=getattr(exc, 'code', 'D38_SINK_ROSTER_UNMEASURED'), detail=str(exc))
        if d38_target_binding(project) != binding:
            raise MetricRefusal('D38_TARGETS_CHANGED_DURING_READ', 'approved targets')
        for name, digest in reads.items():
            read(name, digest, external=True)
        identity['consumed_inputs'] = dict(reads)
        result['readset'] = dict(reads)
    except (MetricRefusal, flow109.Flow109Error, ll.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D38_NATIVE_BINDING_UNPROVEN'), detail=str(exc))
        for obligation in result['obligations']:
            if obligation['status'] == 'PASS':
                obligation.update(status='NOT_MEASURED', reason='D38_BINDING_INCOMPLETE')
    if component.get('verdict') == 'FAIL' or any(
            o['status'] == 'FAIL' or any(v['status'] == 'FAIL' for v in o.get('measurements', [])) for o in result['obligations']):
        result['status'] = result['metric_status'] = 'FAIL'
        for obligation in result['obligations']:
            if any(v['status'] == 'FAIL' for v in obligation.get('measurements', [])):
                obligation['status'] = 'FAIL'
    elif result['obligations'] and all(o['status'] == 'PASS' for o in result['obligations']):
        result['metric_status'] = 'PASS'
        import flow109_admission as admission
        try:
            result['qualification_receipt'] = admission.require_admission(project, current)
            result.update(status='PASS', qualification='PASS', delivery_blocked=False)
        except admission.AdmissionRefusal as exc:
            result.update(reason=exc.code, qualification_receipt=exc.report)
    return result


def accept_d39(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """BLOCKING readback of the existing post-CTS resizer and per-corner STA.

    Re-read native state and complete repair history against current approved
    limits. Reuse existing per-use admission; never execute tools or author
    qualification authority. Missing evidence cannot erase a measured FAIL.
    """
    import flow109
    import inspect
    import librelane_contract as ll
    import execution_backend_producers as native_producer

    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D39', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    reads = {}

    def _d39_read(name, digest=None, *, external=False):
        path = Path(name)
        path = path if path.is_absolute() else project / path
        if (path.is_symlink() or not path.is_file()
                or (not external and not path.resolve().is_relative_to(project))):
            raise MetricRefusal('D39_INPUT_UNBOUND', str(path))
        raw = path.read_bytes()
        actual = _sha(raw)
        if digest is not None and actual != digest:
            raise MetricRefusal('D39_INPUT_CHANGED', str(path))
        key = str(path.relative_to(project)) if path.is_relative_to(project) else str(path)
        if key in reads and reads[key] != actual:
            raise MetricRefusal('D39_INPUT_CHANGED_DURING_READ', key)
        reads[key] = actual
        return path, raw

    def _d39_json(name, digest=None):
        path, raw = _d39_read(name, digest)
        return path, json.loads(raw)

    try:
        current = flow109.validate_execution_context(context)
        row = current['resolved_row']
        names = ('post_cts_setup_hold_drv', 'repair_stagnation_iterations')
        if (row['id'] != 'D39' or tuple(o['metric'] for o in row['obligations']) != names
                or any(o['expectation'].get('operator') != 'within_declared_bounds'
                       or o['expectation'].get('bounds_ref') !=
                       f"requirements/base_26/{o['metric']}.json#/limits"
                       or o['expectation'].get('unit_ref') !=
                       f"requirements/base_26/{o['metric']}.json#/units"
                       for o in row['obligations'])):
            raise MetricRefusal('D39_CONTRACT_CHANGED', 'post-CTS repair obligations')
        timing = {'id': row['obligations'][0]['id'], 'status': 'NOT_MEASURED', 'measurements': []}
        history = {'id': row['obligations'][1]['id'], 'status': 'NOT_MEASURED'}
        result['obligations'] = [timing, history]
        _, handoff = _d39_json('reports/phase3/librelane_cts_hold_handoff.json')
        corners = handoff['corners']
        repair = 'OpenROAD.ResizerTimingPostCTS'
        sta = 'OpenROAD.STAMidPNR'
        steps = [repair] + [sta] * len(corners)
        if (not isinstance(corners, list) or not corners
                or any(not isinstance(c, str) or not c or '/' in c for c in corners)
                or len(set(corners)) != len(corners)
                or handoff['program'] != 'execution_backend_producers._cts_split'
                or handoff['image'] != component.get('native_image')
                or not component.get('native_image') or handoff['steps'] != steps):
            raise MetricRefusal('D39_CHAIN_UNBOUND', 'selected native repair/corners')
        _, area = _d39_json('reports/phase3/pnr/hold_area.json')
        previous, _ = _d39_read(area['sources']['before'])
        base = project / 'phase3/librelane/execution-backend-20'
        states, executions = [], []
        for index, step in enumerate(steps, 1):
            folder = base / (f'{index:02d}-' + step.lower().replace('.', '-'))
            receipt = ll.validate_step_receipt(folder, step)
            _d39_read(folder / 'vibeic_receipt.json')
            for name, digest in receipt['sha256'].items():
                _d39_read(folder / name, digest)
            fp = receipt['input']
            if fp['step'] != step or fp['image'] != component['native_image']:
                raise MetricRefusal('D39_EXECUTION_CHANGED', step)
            _d39_read(previous, fp['state'])
            suffix = '@' + corners[index - 2] if index > 1 else ''
            config_path, config = _d39_json(
                'phase3/librelane/execution-backend-20-config/' + step + suffix + '.json', fp['config'])
            if (config.get('STA_CORNERS') != corners or config.get('meta', {}).get('step') != step
                    or (index > 1 and config.get('PNR_CORNERS') != [corners[index - 2]])):
                raise MetricRefusal('D39_CORNER_POPULATION_CHANGED', str(config_path))
            input_state = json.loads(previous.read_bytes())
            actual_inputs = {str(p): _sha(p.read_bytes()) for p in ll._walk_paths(
                {k: v for k, v in input_state.items() if k != 'metrics'})}
            if not actual_inputs or fp['state_files'] != actual_inputs:
                raise MetricRefusal('D39_STATE_POPULATION_CHANGED', step)
            for name, digest in fp['state_files'].items():
                _d39_read(name, digest)
            _, pdk = _d39_json(folder / 'pdk_root.json')
            mounts = pdk['mounts_under_it']
            if not fp['config_files'] or ll.config_file_hashes(config, mounts) != fp['config_files']:
                raise MetricRefusal('D39_MODEL_POPULATION_CHANGED', step)
            for name, digest in fp['config_files'].items():
                path = Path(name)
                for host, guest in sorted(mounts, key=lambda m: len(m[1]), reverse=True):
                    if path.is_relative_to(guest):
                        path = Path(host) / path.relative_to(guest)
                        break
                _d39_read(path, digest, external=True)
            previous, state = _d39_json(folder / 'state_out.json', receipt['sha256']['state_out.json'])
            states.append(state)
            executions.append({'step': step, 'input': fp,
                'receipt_sha256': _sha((folder / 'vibeic_receipt.json').read_bytes())})
        final, _ = _d39_read(handoff['measured_state'], handoff['measured_state_sha256'])
        if (final != previous or handoff['chain'][repair] != str(base.relative_to(project) / '01-openroad-resizertimingpostcts')
                or handoff['chain'][sta] != str(previous.parent.relative_to(project))
                or project / area['sources']['after'] != base / '01-openroad-resizertimingpostcts/state_out.json'):
            raise MetricRefusal('D39_HANDOFF_FOREIGN', 'terminal measurement or repaired state')
        for view, name in [('def', 'post_hold.def'), ('odb', 'post_hold.odb')]:
            ref = handoff['views']['post_hold_' + view]
            source, _ = _d39_read(ref['source'], ref['source_sha256'])
            dest, _ = _d39_read(ref['dest'], ref['dest_sha256'])
            if (states[0].get(view) != str(source)
                    or dest != project / 'phase3/stage3/pnr' / name
                    or ref['source_sha256'] != ref['dest_sha256']
                    or any(s.get(view) != str(source) for s in states[1:])):
                raise MetricRefusal('D39_HANDOFF_FOREIGN', view)
        identity = {'producer': executions, 'tool_execution': executions,
            'checker': {'program': 'flow109_metric_acceptance.accept_d39',
                        'sha256': _sha(inspect.getsource(accept_d39).encode()),
                        'producer_sha256': _sha(inspect.getsource(native_producer._cts_split).encode())},
            'consumed_inputs': dict(reads), 'requirements': None,
            'configuration': {'context_sha256': current['context_sha256'], 'corners': corners}}
        failures = (MetricRefusal, ll.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError)
        try:
            relative = 'requirements/base_26/post_cts_setup_hold_drv.json'
            auth, body = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
            _d39_read(relative, auth['sha256'])
            _d39_read(auth['source']['path'], auth['source']['sha256'])
            limits, units = body['limits'], body['units']
            if not isinstance(limits, dict) or not limits or set(limits) != set(units):
                raise MetricRefusal('D39_BOUNDS_INVALID', relative)
            drv = {'design__max_slew_violation__count', 'design__max_cap_violation__count',
                   'design__max_fanout_violation__count'}
            fields = {f'timing__{kind}__ws__corner:{corner}': states[index + 1]
                      for index, corner in enumerate(corners) for kind in ('setup', 'hold')}
            fields.update({key: states[-1] for key in drv})
            identity['requirements'] = auth
            for field, bounds in limits.items():
                entry = {'field': field, 'status': 'NOT_MEASURED'}
                timing['measurements'].append(entry)
                expected_unit = 'count' if field in drv else 'ns'
                value = fields.get(field, {}).get('metrics', {}).get(field)
                if field not in fields or value is None or units[field] != expected_unit:
                    entry['reason'] = 'D39_NATIVE_FIELD_OR_UNIT_UNAVAILABLE'
                    continue
                _finite_number(value, count=field in drv)
                measurement = {'status': 'MEASURED', 'value': value, 'unit': expected_unit, 'identity': identity}
                status, reason = evaluate_operator('within_declared_bounds', measurement,
                    {'status': 'APPROVED', 'limits': bounds, 'unit': expected_unit})
                entry.update(status=status, reason=reason, measurement=measurement)
            statuses = [v['status'] for v in timing['measurements']]
            timing['status'] = ('FAIL' if 'FAIL' in statuses else 'PASS'
                if set(fields) <= set(limits) and all(s == 'PASS' for s in statuses) else 'NOT_MEASURED')
        except failures as exc:
            timing.update(reason=getattr(exc, 'code', 'D39_TIMING_UNBOUND'), detail=str(exc))
            timing['status'] = ('FAIL' if any(m['status'] == 'FAIL' for m in timing['measurements'])
                                else 'NOT_MEASURED')
        try:
            reference = handoff['repair_history']
            if reference.get('path') != 'reports/phase3/pnr/post_cts_repair_history.json':
                raise MetricRefusal('D39_HISTORY_FOREIGN', 'canonical producer output path')
            _, record = _d39_json(reference['path'], reference['sha256'])
            folder = base / '01-openroad-resizertimingpostcts'
            native_receipt = folder / 'vibeic_receipt.json'
            before = project / area['sources']['before']
            config = project / 'phase3/librelane/execution-backend-20-config' / (repair + '.json')
            expected_sources = {str(p.relative_to(project)): _sha(_d39_read(p)[1])
                                for p in (before, config, folder / 'invocation.log', folder / 'state_out.json')}
            if (record.get('schema') != 'vibeic.post-cts-repair-history.v1'
                    or record.get('program') != 'execution_backend_producers._d39_capture_repair_history'
                    or record.get('native_step') != repair
                    or record.get('native_receipt') != {'path': str(native_receipt.relative_to(project)),
                                                        'sha256': executions[0]['receipt_sha256']}
                    or record.get('input') != executions[0]['input']
                    or record.get('sources') != expected_sources
                    or executions[0]['input'].get('openroad_init') != ['set_debug_level RSZ repair_hold 1']):
                raise MetricRefusal('D39_HISTORY_FOREIGN', 'native repair receipt/input/log population')
            observation = native_producer._d39_parse_repair_history(
                _d39_read(folder / 'invocation.log')[1].decode())
            if record.get('observation') != observation or observation.get('status') != 'MEASURED':
                raise MetricRefusal('D39_HISTORY_INCOMPLETE', observation.get('reason', 'history changed'))
            relative = 'requirements/base_26/repair_stagnation_iterations.json'
            auth, body = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
            _d39_read(relative, auth['sha256'])
            _d39_read(auth['source']['path'], auth['source']['sha256'])
            if body.get('units') != 'count':
                raise MetricRefusal('D39_HISTORY_UNIT_INVALID', relative)
            _finite_number(observation['value'], count=True)
            measurement = {'status': 'MEASURED', 'value': observation['value'], 'unit': 'count',
                'identity': {**identity, 'requirements': auth, 'consumed_inputs': dict(reads),
                    'history': reference}}
            history['measurement'] = measurement
            history['status'], history['reason'] = evaluate_operator('within_declared_bounds', measurement,
                {'status': 'APPROVED', 'limits': body['limits'], 'unit': 'count'})
        except failures as exc:
            history.update(reason=getattr(exc, 'code', 'D39_HISTORY_UNBOUND'), detail=str(exc))
        for name, digest in reads.items():
            _d39_read(name, digest, external=True)
        result['readset'] = dict(reads)
    except (MetricRefusal, flow109.Flow109Error, ll.Refusal, OSError, ValueError,
            KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D39_NATIVE_BINDING_UNPROVEN'), detail=str(exc))
        for obligation in result['obligations']:
            if obligation['status'] == 'PASS':
                obligation.update(status='NOT_MEASURED', reason='D39_BINDING_INCOMPLETE')
    if component.get('verdict') == 'FAIL' or any(
            o['status'] == 'FAIL' or any(v['status'] == 'FAIL' for v in o.get('measurements', []))
            for o in result['obligations']):
        result['status'] = result['metric_status'] = 'FAIL'
        for obligation in result['obligations']:
            if any(v['status'] == 'FAIL' for v in obligation.get('measurements', [])):
                obligation['status'] = 'FAIL'
    elif result['obligations'] and all(o['status'] == 'PASS' for o in result['obligations']):
        result['metric_status'] = 'PASS'
        import flow109_admission as admission
        try:
            result['qualification_receipt'] = admission.require_admission(project, current)
            result.update(status='PASS', qualification='PASS', delivery_blocked=False)
        except admission.AdmissionRefusal as exc:
            result.update(reason=exc.code, qualification_receipt=exc.report)
    return result



def _d41_native_basis(project, image):
    """Read the existing adopted Step32 chain; no actuator or measurement runs."""
    import librelane_postroute_repair as repair
    import librelane_contract as ll
    import librelane_signoff as signoff
    import postroute_timing_repair_decision as decision
    reads = {}
    ctx = {}
    def read(value, digest=None, *, external=False):
        path = Path(value)
        if not path.is_absolute():
            path = project / path
        if ctx:
            path = repair._resume_host_path(project, ctx, str(path))
        if path.is_symlink() or not path.is_file() or (not external and not path.resolve().is_relative_to(project)):
            raise MetricRefusal('D41_INPUT_UNBOUND', str(path))
        raw = path.read_bytes(); actual = _sha(raw)
        key = str(path.relative_to(project)) if path.is_relative_to(project) else str(path)
        if (digest is not None and actual != digest) or (key in reads and reads[key] != actual):
            raise MetricRefusal('D41_INPUT_CHANGED', str(path))
        reads[key] = actual
        return path, raw
    def document(value, digest=None):
        path, raw = read(value, digest)
        return path, json.loads(raw)
    root = Path(repair.DECLARED_REPAIR_REL)
    _, original = document(root / 'postroute_timing_repair_decision.json')
    decision.verify_receipt(project, original)
    if original.get('source_report') != repair.REPORT_REL or original.get('recorded_by') == decision.CANONICAL_RECORDER:
        raise MetricRefusal('D41_PRODUCER_FOREIGN', 'original Step32 decision')
    _, report = document(repair.REPORT_REL, original['source_report_sha256'])
    _, canonical = document(root / 'postroute_timing_repair_decision.canonical.json')
    decision.verify_receipt(project, canonical)
    if (canonical.get('decision_scope') != 'step32_native' or report.get('step') != '32'
            or report.get('image') != image or report.get('mode') not in ('librelane', 'dual')
            or report.get('verdict') not in ('PASS', 'FAIL')):
        raise MetricRefusal('D41_PRODUCER_FOREIGN', 'native scope/image/mode')
    for record in (original, canonical):
        for ref in record.get('inputs', []):
            read(ref['path'], ref['sha256'])
    arm = project / repair.ARM_REL
    arm_report = report
    if report.get('mode') == 'dual':
        selected = report.get('selected_arm')
        if selected not in ('postdrt', 'pregrt', 'pregrt_postdrt') or report.get('selection', {}).get('selection') != selected:
            raise MetricRefusal('D41_ARM_UNBOUND', 'selected dual arm')
        if any(report.get(key) != report['arms'][selected].get(key) for key in ('final', 'adopted', 'candidates', 'closure')):
            raise MetricRefusal('D41_ARM_UNBOUND', 'selected report differs')
        arm_report = report['arms'][selected]
        arm /= selected
    _, context = document(arm / repair.IMPL_DIR / repair.CONTEXT)
    ctx.update(context)
    _, current = document(arm / repair.IMPL_DIR / repair.CURRENT)
    if (ctx.get('image') != image or current.get('candidate') != report.get('adopted')
            or current.get('measurement') != report.get('final')):
        raise MetricRefusal('D41_ADOPTION_UNBOUND', 'current pointer/report')
    corners = ctx['corners']
    _, sta_config = document(ctx['configs']['OpenROAD.STAPostPNR'])
    if (not isinstance(corners, list) or not corners or len(set(corners)) != len(corners)
            or report.get('corners') != corners or sta_config.get('STA_CORNERS') != corners):
        raise MetricRefusal('D41_CORNERS_UNBOUND', 'complete declared population')
    executions = []
    bound = {}
    measurements = [('baseline', report['baseline']), ('final', report['final'])]
    for role, measured in measurements:
        sta_path, sta_state = document(measured['sta_state'], measured['sta_state_sha256'])
        lane = sta_path.parent.parent
        if lane.parent != project / 'phase3/librelane' or not lane.name.startswith(ctx['lane'] + '-'):
            raise MetricRefusal('D41_FOREIGN_CHAIN', str(lane))
        required = (repair.REPAIR_STEP, *repair.MEASURE_STEPS)
        folders = [lane / (f'{i:02d}-' + step.lower().replace('.', '-')) for i, step in enumerate(required, 1)]
        first_receipt = ll.validate_step_receipt(folders[0], required[0])
        if role == 'baseline' or not report.get('adopted'):
            input_path = arm_report['input_state']
        else:
            selected_rows = [c for c in report['candidates'] if c.get('candidate') == report['adopted']]
            if len(selected_rows) != 1:
                raise MetricRefusal('D41_ADOPTION_UNBOUND', 'candidate population')
            origin = selected_rows[0].get('from')
            origins = [c for c in report['candidates'] if c.get('candidate') == origin]
            input_path = arm_report['input_state'] if origin is None else origins[0]['repair_state'] if len(origins) == 1 else None
            if input_path is None:
                raise MetricRefusal('D41_ADOPTION_UNBOUND', 'candidate predecessor')
        previous, before = document(input_path, first_receipt['input']['state'])
        configs = {}
        repair_state = None
        for index, (step, folder) in enumerate(zip(required, folders)):
            receipt = ll.validate_step_receipt(folder, step)
            read(folder / 'vibeic_receipt.json')
            for name, digest in receipt['sha256'].items():
                read(folder / name, digest)
            fp = receipt['input']
            if fp.get('image') != image or fp.get('step') != step:
                raise MetricRefusal('D41_IMAGE_CHANGED', step)
            if step == repair.REPAIR_STEP and fp.get('plugin') != ll._plugin_digests(step):
                raise MetricRefusal('D41_PRODUCER_CHANGED', step)
            _, incoming = document(previous, fp['state'])
            if fp.get('state_files') != {str(p): _sha(read(p)[1]) for p in ll._walk_paths(
                    {k:v for k,v in incoming.items() if k != 'metrics'})}:
                raise MetricRefusal('D41_STATE_POPULATION_CHANGED', step)
            if index == 0:
                matches = [p for p in (project / 'phase3/librelane/32-config').glob('*.json')
                    if p.is_file() and not p.is_symlink() and _sha(p.read_bytes()) == fp['config']]
                if not matches:
                    raise MetricRefusal('D41_CONFIG_UNBOUND', step)
                config_path = matches[0]
            else:
                config_path = ctx['configs'][step]
            _, config = document(config_path, fp['config'])
            if config.get('meta', {}).get('step') != step:
                raise MetricRefusal('D41_CONFIG_UNBOUND', step)
            _, mapping = document(folder / 'pdk_root.json')
            mounts = mapping['mounts_under_it']
            ll._current_config_material(config, mounts)
            if fp.get('config_files') != ll.config_file_hashes(config, mounts):
                raise MetricRefusal('D41_CONFIG_POPULATION_CHANGED', step)
            for field in ('config_files', 'rcx_pdk_files', 'liberty_files'):
                if field not in fp:
                    if (step, field) in (('OpenROAD.RCX', 'rcx_pdk_files'), ('OpenROAD.STAPostPNR', 'liberty_files')):
                        raise MetricRefusal('D41_MODELS_UNBOUND', step)
                    continue
                for name, digest in fp[field].items():
                    if not _HEX.fullmatch(str(digest)):
                        raise MetricRefusal('D41_MODELS_UNBOUND', str(name))
                    read(name, digest, external=True)
            if step == 'OpenROAD.RCX' and fp['rcx_pdk_files'] != ll._rcx_pdk_input_hashes(config, project, mounts):
                raise MetricRefusal('D41_RCX_MODELS_CHANGED', step)
            if step == 'OpenROAD.STAPostPNR' and fp['liberty_files'] != ll._sta_liberty_input_hashes(config, project, mounts):
                raise MetricRefusal('D41_LIBERTY_CHANGED', step)
            previous, state = document(folder / 'state_out.json', receipt['sha256']['state_out.json'])
            for path in ll._walk_paths({k:v for k,v in state.items() if k != 'metrics'}):
                read(path)
            configs[step] = config
            executions.append({'role':role, 'step':step, 'input':fp, 'receipt_sha256':_sha(read(folder / 'vibeic_receipt.json')[1])})
            if index == 0:
                repair_state = previous
        if previous != sta_path:
            raise MetricRefusal('D41_MEASUREMENT_FOREIGN', role)
        # Reuse the RCX owner; this binds the actual ODB, every RC scene,
        # extracted SPEF, ruleset and native extraction receipt.
        rcx = signoff.bind_rcx_spefs(folders[2], repair_state, corners)
        if measured.get('rcx_binding') != rcx:
            raise MetricRefusal('D41_RCX_BINDING_CHANGED', role)
        bound[role] = {'measurement':measured, 'state':sta_state, 'repair_state':repair_state,
            'input_state':before, 'folders':folders, 'configs':configs}
    selected_path, selected = document(report['adopted_state'])
    if repair._resume_host_path(project, ctx, current['repair_state']) != selected_path:
        raise MetricRefusal('D41_ADOPTION_UNBOUND', 'selected State')
    measured_odb = bound['final']['measurement']['native_odb_sha256']
    if _sha(read(selected['odb'])[1]) != measured_odb:
        raise MetricRefusal('D41_ADOPTION_UNBOUND', 'selected ODB differs from measurement')
    # Current routed views may be the selected repair's downstream native
    # tail. Use the existing in-chain owner instead of pretending they must
    # equal the pre-tail repair DEF.
    if report.get('site') == 'after_route':
        import execution_backend_producers as producer
        actual, why = producer._runner_context()._postroute_repair_in_chain(project)
        if actual is None or actual.get('final') != report['final']:
            raise MetricRefusal('D41_ROUTE_HANDOFF_UNBOUND', why)
        _, handoff = document('reports/phase3/librelane_route_handoff.json')
        for ref in handoff['views'].values():
            read(ref['source'], ref['source_sha256']); read(ref['dest'], ref['dest_sha256'])
    elif report.get('site') == 'after_direct_route':
        repair._validate_resume_subject(project, current, ctx)
        _, handoff = document('reports/phase3/librelane_postroute_repair_handoff.json')
        for ref in handoff['views'].values():
            read(ref['source'], ref['source_sha256']); read(ref['dest'], ref['dest_sha256'])
    else:
        raise MetricRefusal('D41_SITE_UNBOUND', str(report.get('site')))
    return {'read':read, 'reads':reads, 'document':document, 'report':report, 'context':ctx,
        'current':current, 'arm':arm, 'corners':corners, 'bound':bound, 'selected':selected,
        'executions':executions}


def _d41_timing_values(basis, snapshot):
    import _native_postroute_timing as native
    import librelane_postroute_repair as repair
    read = basis['read']
    final = basis['bound']['final']
    measured = basis['report']['final']
    state = json.loads(read(final['repair_state'])[1])
    folder = Path(measured['native_timing_dir'])
    if folder != final['folders'][0] / 'native_signoff':
        raise MetricRefusal('D41_TIMING_REPORT_FOREIGN', str(folder))
    read(state['sdc'], measured['native_sdc_sha256'])
    scene = folder / 'measurement_scene.sdc'
    read(scene, measured['native_measurement_sdc_sha256'])
    config = final['configs']['OpenROAD.RCX']
    values = {}
    for corner in basis['corners']:
        paths = [folder / ('sta_' + corner + suffix) for suffix in ('.rpt', '.tcl', '.log')]
        texts = []
        for path in paths:
            key = str(path.relative_to(Path(basis['context']['project'])))
            digest = snapshot['inputs'].get(key)
            if not digest:
                raise MetricRefusal('D41_TIMING_REPORT_UNBOUND', key)
            texts.append(read(path, digest)[1].decode())
        body, script, log = texts
        slacks = native._SLACK.findall(body)
        ocv = native._OCV_BASIS.findall(body)
        if (len(slacks) != 2 or {k for k,v in slacks} != {'min','max'} or len(ocv) != 1
                or ocv[0] != measured['ocv_applied']['mode'] or not log.strip()
                or repair._CRASH_SIGNATURE.search(log) or re.search(r'^\[ERROR\b', log, re.M)):
            raise MetricRefusal('D41_TIMING_REPORT_INCOMPLETE', corner)
        libs = native._one(config.get('LIB', config.get('CELL_LIBS')), corner, 'cell liberty')
        pads = native._one(config['PAD_LIBS'], corner, 'pad liberty') if config.get('PAD_LIBS') else []
        for path in [*libs, *pads]:
            read(path, external=True)
        expected = [f'read_db {native._q(state["odb"])}',
            *[f'read_liberty {native._q(lib)}' for lib in [*libs,*pads]],
            f'read_sdc {native._q(scene)}',
            f'read_spef {native._q(measured["rcx_binding"]["scenes"][corner]["path"])}',
            'set_propagated_clock [all_clocks]',
            *native._ocv_tcl(paths[0], *basis['context']['derate'], basis['context'].get('aocv_table')),
            f'report_worst_slack -max -digits 6 >> {native._q(paths[0])}',
            f'report_worst_slack -min -digits 6 >> {native._q(paths[0])}', 'exit']
        if script != '\n'.join(expected) + '\n':
            raise MetricRefusal('D41_TIMING_SCRIPT_CHANGED', corner)
        for kind, value in slacks:
            number = _finite_number(float(value))
            semantic = 'setup' if kind == 'max' else 'hold'
            if measured[semantic + '_ws'].get(corner) != number:
                raise MetricRefusal('D41_TIMING_SUMMARY_CHANGED', corner)
            values[f'timing__{semantic}__ws__corner:{corner}'] = (number, 'ns')
        for kind in ('slew','cap','fanout'):
            key = f'design__max_{kind}_violation__count__corner:{corner}'
            value = final['state'].get('metrics', {}).get(key)
            _finite_number(value, count=True)
            if measured['drv'][kind].get(corner) != value:
                raise MetricRefusal('D41_DRV_SUMMARY_CHANGED', key)
            values[key] = (value, 'count')
    # The existing reader verifies every corner's complete DRV table/counters.
    summary = repair.summarize(final['state']['metrics'], basis['corners'])
    pins = repair.drv_pin_census(final['folders'][-1], summary, basis['corners'],
        classifier=repair._drv_classifier(basis['context'], final['folders'][-1]))
    for ref in pins['drv_pin_checks_sources'].values():
        read(ref['path'], ref['sha256'])
    if pins['drv_pin_checks_state'] != 'PASS' or pins['drv_pin_checks'] != measured.get('drv_pin_checks'):
        raise MetricRefusal('D41_DRV_PIN_POPULATION_INCOMPLETE', str(pins['drv_pin_checks_missing']))
    return values


def _d41_filler_errors(basis, snapshot):
    import fnmatch
    import librelane_postroute_repair as repair
    read = basis['read']; final = basis['bound']['final']
    after = json.loads(read(final['repair_state'])[1])
    before = final['input_state']
    for role, state in [('before',before),('after',after)]:
        if snapshot[role + '_odb'] != {'path':state['odb'], 'sha256':_sha(read(state['odb'])[1])}:
            raise MetricRefusal('D41_FILLER_SUBJECT_CHANGED', role)
    config = final['configs'][repair.REPAIR_STEP]
    patterns = [p.replace("'", '') for key in ('FILL_CELLS','DECAP_CELLS') for p in config.get(key) or []]
    if snapshot['patterns'] != patterns or snapshot['filler']['status'] != 'MEASURED':
        raise MetricRefusal('D41_FILLER_NOT_MEASURED', str(snapshot['filler']))
    metrics = after.get('metrics', {})
    count = metrics.get('vibeic__prr__input_fillers')
    _finite_number(count)
    if count < 0 or int(count) != count:
        raise MetricRefusal('D41_FILLER_CENSUS_UNBOUND', 'non-integral native metric')
    count = int(count)
    log = read(final['folders'][0] / 'invocation.log')[1].decode()
    census = re.findall(r'^PRR: input instances=\d+ fillers=(\d+)\s*$', log, re.M)
    if len(census) != 1 or int(census[0]) != count:
        raise MetricRefusal('D41_FILLER_CENSUS_UNBOUND', 'native input count/log')
    if snapshot['filler']['method'] == 'UNCHANGED_NATIVE_ODB':
        if snapshot['before_odb']['sha256'] != snapshot['after_odb']['sha256'] or metrics.get('vibeic__prr__changed') != 0:
            raise MetricRefusal('D41_FILLER_SUBJECT_CHANGED', 'no-op ODB')
        return 0
    if snapshot['filler']['method'] != 'NATIVE_ODB_ROSTER':
        raise MetricRefusal('D41_FILLER_NOT_MEASURED', 'unsupported readback')
    before_rows, after_rows = snapshot['filler']['before'], snapshot['filler']['after']
    if (len({r['instance'] for r in before_rows}) != len(before_rows)
            or len({r['instance'] for r in after_rows}) != len(after_rows)
            or sum(r['type'] == 'CORE_SPACER' for r in before_rows) != count):
        raise MetricRefusal('D41_FILLER_CENSUS_UNBOUND', 'complete native rosters')
    survivors = {r['instance']:r for r in before_rows if r['type'] != 'CORE_SPACER' or r['status'] == 'LOCKED'}
    actual = {r['instance']:r for r in after_rows}
    errors = sum(actual.get(name) != row for name,row in survivors.items())
    restored = [r for r in after_rows if r['instance'] not in survivors]
    errors += sum(r['status'] not in ('PLACED','FIRM','LOCKED') or not any(
        fnmatch.fnmatchcase(r['master'], p) for p in patterns) for r in restored)
    placed = re.findall(r'^\[INFO DPL-0001\] Placed (\d+) filler instances\.\s*$', log, re.M)
    if count > 0 and not placed:
        raise MetricRefusal('D41_FILLER_RESTORE_UNMEASURED', 'native filler completion absent')
    if placed:
        errors += abs(sum(map(int,placed)) - len(restored))
    elif restored:
        raise MetricRefusal('D41_FILLER_RESTORE_UNMEASURED', 'unreported restored population')
    return errors


def _d41_history(basis):
    """Count original retained attempts/iterations; never reset a budget."""
    from _ppa import closure
    import librelane_postroute_repair as repair
    document, read, report = basis['document'], basis['read'], basis['report']
    registry = closure.load_registry()
    read(registry.path, external=True)
    runs, candidates = report.get('closure'), report.get('candidates')
    if not isinstance(runs,list) or not isinstance(candidates,list):
        raise MetricRefusal('D41_HISTORY_INCOMPLETE', 'controller/candidate population')
    trigger = repair.measured_repair_trigger(report['baseline'])
    if trigger != report.get('repair_trigger'):
        raise MetricRefusal('D41_HISTORY_CHANGED', 'original trigger')
    ledger_path = basis['arm'] / repair.LEDGER
    if ledger_path.is_file():
        _, ledger = document(ledger_path)
        recorded = ledger['candidates']
    elif trigger['action'] == 'SKIP' and not candidates and not runs and report.get('adopted') is None:
        recorded = []
    elif not candidates and runs and all(run.get('outcome') == 'NOT_TRIGGERED' and not run.get('iterations') for run in runs):
        recorded = []
    else:
        raise MetricRefusal('D41_HISTORY_INCOMPLETE', 'original ledger absent')
    annotations = {'controller','closure_decision','closure_reason'}
    if recorded != [{k:v for k,v in row.items() if k not in annotations} for row in candidates]:
        raise MetricRefusal('D41_HISTORY_CHANGED', 'original candidate ledger')
    names = [row['candidate'] for row in candidates]
    if len(names) != len(set(names)):
        raise MetricRefusal('D41_HISTORY_CHANGED', 'duplicate attempts')
    iterations, adopted = 0, 0
    incomplete = []; failed = []
    for run in runs:
        cid = run.get('controller')
        if cid not in repair.CONTROLLERS or run.get('registry_digest') != registry.digest():
            raise MetricRefusal('D41_POLICY_CHANGED', str(cid))
        if run.get('digest') != closure.cj.digest_of({k:v for k,v in run.items() if k not in ('digest','refused_candidates')}):
            raise MetricRefusal('D41_HISTORY_CHANGED', 'original controller digest')
        policy = registry.controllers[cid]
        acts = [it for it in run['iterations'] if it.get('argv')]
        indices = [it['index'] for it in run['iterations']]
        if len(indices) != len(set(indices)) or any(type(i) is not int or i < 0 or i >= policy.max_iterations for i in indices):
            raise MetricRefusal('D41_HISTORY_CHANGED', 'declared iteration indices')
        iterations += len(acts)
        adopted += run['promoted']
        own = [row for row in candidates if row.get('controller') == cid and not row.get('retry_of')]
        if len(own) != len(acts):
            raise MetricRefusal('D41_HISTORY_INCOMPLETE', 'actuation/candidate population')
        outcome = run.get('outcome')
        if (run.get('schema') != closure.SCHEMA_RUN or type(run.get('closed_loop_success')) is not bool
                or not isinstance(run.get('collateral_regressions'), list)):
            raise MetricRefusal('D41_HISTORY_INCOMPLETE', 'original closed-loop result')
        if (run['collateral_regressions'] or outcome in ('PLATEAU','BUDGET_EXHAUSTED','HANDOFF_REQUIRED')):
            failed.append({'controller':cid,'outcome':outcome,'reason':run.get('reason'),
                'collateral_regressions':run['collateral_regressions']})
        elif outcome not in ('CONVERGED','NOT_TRIGGERED') or not run['closed_loop_success']:
            incomplete.append({'controller':cid,'outcome':outcome,'reason':run.get('reason')})
    if runs and [run['controller'] for run in runs] != list(repair.CONTROLLERS):
        raise MetricRefusal('D41_HISTORY_INCOMPLETE', 'full declared controller population')
    for row in candidates:
        if row.get('retry_of') and row['retry_of'] not in names:
            raise MetricRefusal('D41_HISTORY_CHANGED', 'retry predecessor absent')
        if row.get('config'):
            document(row['config'])
        if row.get('measurement'):
            measured = row['measurement']
            document(measured['sta_state'], measured['sta_state_sha256'])
            document(row['repair_state'])
        else:
            matches = re.findall(r'(/[^;\s]+/invocation\.log)', row.get('reason',''))
            for path in matches:
                read(path)
            if not matches:
                incomplete.append({'candidate':row['candidate'],'reason':'failed attempt native log absent'})
        if row.get('decision') == 'ACTUATOR_FAILED' or row.get('measurement_status') == 'NOT_MEASURED':
            incomplete.append({'candidate':row['candidate'],'reason':row.get('reason')})
    if report.get('adopted') is not None and not any(row['candidate'] == report['adopted']
            and row.get('closure_decision') == 'PROMOTED' for row in candidates):
        raise MetricRefusal('D41_ADOPTION_UNBOUND', 'no promoted original attempt')
    return {'candidate_attempts':len(candidates), 'controller_iterations':iterations,
            'adoptions':adopted, 'not_measured':incomplete, 'failed':failed,
            'registry_digest':registry.digest(), 'outcomes':[run.get('outcome') for run in runs]}


def accept_d41(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """BLOCKING D41 readback of adopted native values; never run repair/RCX/STA.

    Approved requirements and existing admission remain independent. Missing
    filler/history/corner evidence is unmeasured; measured FAIL survives later NI.
    """
    import flow109
    import librelane_contract as ll
    import inspect
    import execution_backend_producers as producer
    project = Path(project).resolve()
    result = {'schema':SCHEMA, 'row_id':'D41', 'status':'NOT_MEASURED', 'metric_status':'NOT_MEASURED',
        'qualification':'NOT_MEASURED', 'delivery_blocked':True, 'obligations':[]}
    failures = (MetricRefusal, flow109.Flow109Error, ll.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError)
    try:
        current = flow109.validate_execution_context(context)
        specs = current['resolved_row']['obligations']
        if current['resolved_row']['id'] != 'D41' or tuple(o['metric'] for o in specs) != (
                'post_repair_timing_drv','filler_restore_errors','repair_iteration_budget'):
            raise MetricRefusal('D41_CONTRACT_CHANGED', 'obligations')
        for index,spec in enumerate(specs):
            expect = spec['expectation']
            if index == 1:
                if (expect.get('operator'),expect.get('value'),expect.get('unit')) != ('eq',0,'count'):
                    raise MetricRefusal('D41_CONTRACT_CHANGED',spec['id'])
            elif (expect.get('operator') != 'within_declared_bounds'
                    or expect.get('bounds_ref') != f"requirements/base_28/{spec['metric']}.json#/limits"
                    or expect.get('unit_ref') != f"requirements/base_28/{spec['metric']}.json#/units"):
                raise MetricRefusal('D41_CONTRACT_CHANGED',spec['id'])
        basis = _d41_native_basis(project, component.get('native_image'))
        read, reads = basis['read'], basis['reads']
        path, raw = read('reports/phase3/execution-backend-32.json')
        snapshot = json.loads(raw)
        result['native_readback'] = {'path':str(path.relative_to(project)),'sha256':_sha(raw)}
        if (snapshot.get('schema') != 'vibeic.d41-native-readback.v1'
                or snapshot.get('program') != 'execution_backend_producers._d41_capture_native'
                or snapshot.get('image') != component.get('native_image')
                or snapshot.get('checker_sha256') != _sha(inspect.getsource(producer._d41_filler_roster).encode())
                or snapshot.get('source_report_sha256') != reads['reports/phase3/librelane_postroute_repair.json']):
            raise MetricRefusal('D41_READBACK_FOREIGN','producer snapshot')
        for name,digest in snapshot['inputs'].items():
            read(name,digest,external=True)
        identity = {'producer':basis['executions'],'tool_execution':basis['executions'],
            'checker':{'program':'flow109_metric_acceptance.accept_d41',
                'source_sha256':_sha(inspect.getsource(accept_d41).encode()),
                'native_reader_sha256':_sha(inspect.getsource(_d41_native_basis).encode()),
                'timing_reader_sha256':_sha(inspect.getsource(_d41_timing_values).encode()),
                'filler_reader_sha256':_sha(inspect.getsource(_d41_filler_errors).encode()),
                'history_reader_sha256':_sha(inspect.getsource(_d41_history).encode())},
            'consumed_inputs':reads,'requirements':None,
            'configuration':{'context_sha256':current['context_sha256'], 'corners':basis['corners'],
                'signoff_scene':{'derate':basis['context']['derate'],'ocv_applied':basis['report']['final']['ocv_applied']},
                'native_readback':result['native_readback']}}
        timing = {'id':specs[0]['id'],'status':'NOT_MEASURED','measurements':[]}
        result['obligations'].append(timing)
        try:
            auth, body = _approved_document(project,'requirements/base_28/post_repair_timing_drv.json',authority='requirements_owner',schema=AUTHORITY_SCHEMA)
            read(auth['path'],auth['sha256']);read(auth['source']['path'],auth['source']['sha256'])
            if body.get('modes'):
                raise MetricRefusal('D41_MODE_POPULATION_UNAVAILABLE','existing producer has one signoff SDC scene, not an additional mode roster')
            limits, units = body['limits'],body['units']
            if not isinstance(limits,dict) or not limits or set(limits) != set(units):
                raise MetricRefusal('D41_BOUNDS_INVALID','timing/DRV')
            values = _d41_timing_values(basis,snapshot)
            for field,bounds in limits.items():
                item={'field':field,'status':'NOT_MEASURED'};timing['measurements'].append(item)
                value,unit = values.get(field,(None,None))
                if value is None or unit != units[field]:
                    item['reason']='D41_NATIVE_FIELD_OR_UNIT_UNAVAILABLE';continue
                observation={'status':'MEASURED','value':value,'unit':unit,'identity':{**identity,'requirements':auth}}
                status,reason = evaluate_operator('within_declared_bounds',observation,{'status':'APPROVED','limits':bounds,'unit':unit})
                item.update(status=status,reason=reason,measurement=observation)
            statuses=[v['status'] for v in timing['measurements']]
            timing['status']=('FAIL' if 'FAIL' in statuses else 'PASS' if set(values) <= set(limits)
                and all(s=='PASS' for s in statuses) else 'NOT_MEASURED')
        except failures as exc:
            timing.update(reason=getattr(exc,'code','D41_TIMING_UNBOUND'),detail=str(exc))
            if any(v['status']=='FAIL' for v in timing['measurements']):timing['status']='FAIL'
        filler={'id':specs[1]['id'],'status':'NOT_MEASURED'};result['obligations'].append(filler)
        try:
            count=_d41_filler_errors(basis,snapshot)
            authority={'status':'APPROVED','value':0,'unit':'count','source':'canonical base_28 filler restore invariant'}
            measurement={'status':'MEASURED','value':count,'unit':'count','identity':{**identity,'requirements':authority}}
            filler['status'],filler['reason']=evaluate_operator('eq',measurement,authority)
            filler['measurement']=measurement
        except failures as exc:
            filler.update(reason=getattr(exc,'code','D41_FILLER_UNBOUND'),detail=str(exc))
        budget={'id':specs[2]['id'],'status':'NOT_MEASURED'};result['obligations'].append(budget)
        try:
            history=_d41_history(basis);budget['history']=history
            auth,body=_approved_document(project,'requirements/base_28/repair_iteration_budget.json',authority='requirements_owner',schema=AUTHORITY_SCHEMA)
            read(auth['path'],auth['sha256']);read(auth['source']['path'],auth['source']['sha256'])
            selector=body.get('basis')
            if selector not in ('candidate_attempts','controller_iterations','adoptions') or body.get('units')!='count':
                raise MetricRefusal('D41_BUDGET_BASIS_OR_UNIT_UNAVAILABLE',str(selector))
            measurement={'status':'MEASURED','value':history[selector],'unit':'count','identity':{**identity,'requirements':auth}}
            budget['status'],budget['reason']=evaluate_operator('within_declared_bounds',measurement,{'status':'APPROVED','limits':body['limits'],'unit':'count'})
            budget['measurement']=measurement
            if history['failed']:
                budget.update(status='FAIL',reason='D41_ORIGINAL_CONTROLLER_UNCLOSED')
            elif history['not_measured'] and budget['status']!='FAIL':
                budget.update(status='NOT_MEASURED',reason='D41_ORIGINAL_ATTEMPT_UNMEASURED')
        except failures as exc:
            budget.update(reason=getattr(exc,'code','D41_HISTORY_UNBOUND'),detail=str(exc))
        for path,digest in list(reads.items()):read(path,digest,external=True)
        result['readset']=dict(reads)
    except failures as exc:
        result.update(reason=getattr(exc,'code','D41_NATIVE_BINDING_UNPROVEN'),detail=str(exc))
        for o in result['obligations']:
            if o['status']=='PASS':o.update(status='NOT_MEASURED',reason='D41_BINDING_INCOMPLETE')
    if component.get('verdict')=='FAIL' or any(o['status']=='FAIL' for o in result['obligations']):
        result['status']=result['metric_status']='FAIL'
    elif len(result['obligations'])==3 and all(o['status']=='PASS' for o in result['obligations']):
        result['metric_status']='PASS'
        import flow109_admission as admission
        try:
            result['qualification_receipt']=admission.require_admission(project,current)
            result.update(status='PASS',qualification='PASS',delivery_blocked=False)
        except admission.AdmissionRefusal as exc:
            result.update(reason=exc.code,qualification_receipt=exc.report)
    return result



def _digital_floorplan_readback(project, component):
    """Reopen only the selected default Step15 chain, including its real configs."""
    import librelane_contract as ll
    import execution_backend_producers as producer
    reads = {}
    def read(path, digest=None, *, external=False):
        path = Path(path)
        if not path.is_absolute():
            path = project / path
        if path.is_symlink() or not path.is_file() or (not external and not path.resolve().is_relative_to(project)):
            raise MetricRefusal('DIGITAL_FLOORPLAN_INPUT_UNBOUND', str(path))
        raw = path.read_bytes()
        actual = _sha(raw)
        key = str(path.relative_to(project)) if path.is_relative_to(project) else str(path)
        if (digest is not None and actual != digest) or (key in reads and actual != reads[key]):
            raise MetricRefusal('DIGITAL_FLOORPLAN_INPUT_CHANGED', str(path))
        reads[key] = actual
        return raw
    chain = json.loads(read('reports/phase3/execution-backend-15.json'))
    steps = chain['ordered_steps']
    if (not steps or len(steps) != len(set(steps)) or len(steps) != len(chain['states'])
            or steps[0] != 'Yosys.JsonHeader' or 'OpenROAD.Floorplan' not in steps
            or 'OpenROAD.GeneratePDN' not in steps or chain['image'] != component.get('native_image')):
        raise MetricRefusal('DIGITAL_FLOORPLAN_CHAIN_UNBOUND', 'normal Step15')
    previous = Path(chain['initial_state'])
    read(previous, chain['initial_sha256'])
    states, configs, executions, lefs = {}, {}, [], set()
    for step, ref in zip(steps, chain['states']):
        path = Path(ref['state'])
        if ref['step'] != step or path.parent.parent not in (
                project / 'phase3/librelane/15-floorplan', project / 'phase3/librelane/execution-backend-15'):
            raise MetricRefusal('DIGITAL_FLOORPLAN_FOREIGN_ROUTE', step)
        state = json.loads(read(path, ref['sha256']))
        receipt = ll.validate_step_receipt(path.parent, step)
        read(path.parent / 'vibeic_receipt.json')
        for name, digest in receipt['sha256'].items():
            read(path.parent / name, digest)
        fp = receipt['input']
        if fp.get('step') != step or fp.get('image') != component.get('native_image'):
            raise MetricRefusal('DIGITAL_FLOORPLAN_IMAGE_CHANGED', step)
        if step.startswith(ll.PLUGIN_STEP_PREFIX) and fp.get('plugin') != ll._plugin_digests(step):
            raise MetricRefusal('DIGITAL_FLOORPLAN_SOURCE_CHANGED', step)
        before = json.loads(read(previous, fp['state']))
        expected_state = {str(p): _sha(read(p)) for p in ll._walk_paths(
            {k: v for k, v in before.items() if k != 'metrics'})}
        config = json.loads(read(ref['config'], ref['config_sha256']))
        if fp.get('config') != ref['config_sha256'] or config.get('meta', {}).get('step') != step:
            raise MetricRefusal('DIGITAL_FLOORPLAN_CONFIG_CHANGED', step)
        mounts = json.loads(read(path.parent / 'pdk_root.json'))['mounts_under_it']
        ll._current_config_material(config, mounts)
        expected_config = ll.config_file_hashes(config, mounts)
        if fp.get('state_files') != expected_state or fp.get('config_files') != expected_config:
            raise MetricRefusal('DIGITAL_FLOORPLAN_POPULATION_CHANGED', step)
        for name, digest in expected_config.items():
            source = Path(name)
            for host, guest in sorted(mounts, key=lambda m: len(m[1]), reverse=True):
                if source.is_relative_to(guest):
                    source = Path(host) / source.relative_to(guest)
                    break
            read(source, digest, external=True)
            if source.suffix.lower() == '.lef':
                lefs.add(source)
        states[step], configs[step] = (path, state), config
        executions.append({'step': step, 'input': fp, 'receipt_sha256': _sha(read(path.parent / 'vibeic_receipt.json'))})
        previous = path
    portable = chain['portable_state']
    read(portable['path'], portable['sha256'])
    record = producer._read_step15_bounded_state(project)['record']
    if (record['raw_state_sha256'] != _sha(read(previous))
            or record['raw_pdn_state_sha256'] != _sha(read(states['OpenROAD.GeneratePDN'][0]))):
        raise MetricRefusal('DIGITAL_FLOORPLAN_HANDOFF_FOREIGN', 'selected terminal/PDN')
    # The existing portable owner validates these refs; include every byte in
    # this consumer's currentness readset as well.
    for ref in [record['native_state'], record['pdn_state'], record['handoff'],
                record['upstream_sdc'], *record['views'].values()]:
        read(ref['path'], ref['sha256'])
    terminal = states[steps[-1]][1]
    for view in ('def', 'odb'):
        source = record['handoff_views'][view]
        if terminal.get(view) != source['source']:
            raise MetricRefusal('DIGITAL_FLOORPLAN_HANDOFF_FOREIGN', view)
        read(source['source'], source['source_sha256'])
    return read, reads, states, configs, executions, sorted(lefs)


def _digital_def_geometry(text, lefs):
    """Measure declared DEF geometry; reject truncated or ambiguous populations."""
    import _pad_ring as pr
    import pad_bterm_coincidence_check as pins
    def section(name):
        matches = list(re.finditer(r'^\s*' + name + r'\s+(\d+)\s*;(.*?)^\s*END\s+' + name + r'\s*$', text, re.M | re.S))
        if len(matches) != 1:
            raise MetricRefusal('DIGITAL_DEF_POPULATION_UNAVAILABLE', name)
        declared, body = matches[0].groups()
        records = [s.strip() for s in body.split(';') if s.strip()]
        names = [re.match(r'-\s+(\S+)', s) for s in records]
        if (len(records) != int(declared) or any(m is None for m in names)
                or len({m[1] for m in names}) != len(names)):
            raise MetricRefusal('DIGITAL_DEF_POPULATION_INVALID', name)
        return records
    components, pin_records = section('COMPONENTS'), section('PINS')
    for name in ('NETS', 'SPECIALNETS'):
        if re.search(r'^\s*' + name + r'\s', text, re.M):
            section(name)
    if not re.search(r'^\s*END DESIGN\s*$', text, re.M):
        raise MetricRefusal('DIGITAL_DEF_TRUNCATED', 'END DESIGN')
    d = pr.parse_def(text)
    if (len(d.components) != len(components) or len(d.diearea) != 2
            or not re.search(r'UNITS\s+DISTANCE\s+MICRONS\s+\d+\s*;', text)):
        raise MetricRefusal('DIGITAL_DEF_GEOMETRY_UNAVAILABLE', 'components/die/units')
    sizes, classes = {}, {}
    for lef in lefs:
        raw = lef.read_text()
        for target, values in [(sizes, pr.parse_lef_macros(raw)), (classes, pr.parse_lef_macro_classes(raw))]:
            for key, value in values.items():
                if key in target and target[key] != value:
                    raise MetricRefusal('DIGITAL_LEF_AMBIGUOUS', key)
                target[key] = value
    die = tuple(d.box)
    if d.units <= 0 or die[0] >= die[2] or die[1] >= die[3]:
        raise MetricRefusal('DIGITAL_DEF_GEOMETRY_UNAVAILABLE', 'nonpositive die/units')
    def outside(box):
        return box[0] < die[0] or box[1] < die[1] or box[2] > die[2] or box[3] > die[3]
    boxes, macros, unplaced = {}, {}, 0
    for name, comp in d.components.items():
        if comp.master not in sizes or comp.master not in classes:
            raise MetricRefusal('DIGITAL_LEF_MASTER_UNAVAILABLE', comp.master)
        if not comp.placed:
            if classes[comp.master].startswith('BLOCK'):
                unplaced += 1
            continue
        w, h = pr.footprint(sizes[comp.master], comp.orient, d.units)
        box = (comp.x, comp.y, comp.x + w, comp.y + h)
        boxes[name] = box
        if classes[comp.master].startswith('BLOCK'):
            macros[name] = box
    parsed_pins = pins.def_pins(text)
    if len(parsed_pins) != len(pin_records):
        raise MetricRefusal('DIGITAL_PIN_GEOMETRY_UNAVAILABLE', 'rectangular BTerm population')
    for raw in pin_records:
        name = re.match(r'-\s+(\S+)', raw)[1]
        use = re.search(r'\+\s*USE\s+(\w+)', raw)
        pin = parsed_pins[name]
        pin['use'] = use[1] if use else 'SIGNAL'
        rectangles = list(pins._LAYER_RE.finditer(raw))
        placements = list(pins._PLACE_RE.finditer(raw))
        # Native PDN BTerms contain many rectangles in one placed port. Keep
        # every rectangle; signal access still requires its single shape.
        if (len(rectangles) != len(re.findall(r'\+\s*LAYER\b', raw))
                or len(placements) != len(re.findall(r'\+\s*(?:PLACED|FIXED|COVER)\b', raw))
                or len(placements) > 1 or len(re.findall(r'\+\s*PORT\b', raw)) > 1
                or re.search(r'\+\s*(?:POLYGON|VIA)\b', raw)
                or len(rectangles) > 1 and pin['use'] not in ('POWER', 'GROUND')):
            raise MetricRefusal('DIGITAL_PIN_GEOMETRY_UNAVAILABLE', name)
        pin['rects'] = []
        if not rectangles or not placements:
            continue
        x, y, orient = pin['placement']
        for rectangle in rectangles:
            relative = tuple(int(rectangle.group(k)) for k in ('x1', 'y1', 'x2', 'y2'))
            if relative[0] >= relative[2] or relative[1] >= relative[3]:
                raise MetricRefusal('DIGITAL_PIN_GEOMETRY_UNAVAILABLE', name)
            try:
                a, b, c, e = pr.orient_rect(relative, orient, (0, 0))
            except KeyError as exc:
                raise MetricRefusal('DIGITAL_PIN_ORIENTATION_UNAVAILABLE', orient) from exc
            pin['rects'].append([a+x, b+y, c+x, e+y])
        pin['rect'] = pin['rects'][0]
    def overlap(a, b):
        return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])
    macro_boxes = list(macros.values())
    values = {'die_width_um': ((die[2] - die[0]) / d.units, 'um'),
        'die_height_um': ((die[3] - die[1]) / d.units, 'um'),
        'macro_boundary_errors': (sum(outside(b) for b in macro_boxes), 'count'),
        'unplaced_macros': (unplaced, 'count'),
        'pin_boundary_errors': (sum(any(outside(box) for box in p['rects']) for p in parsed_pins.values()), 'count'),
        'unplaced_pins': (sum(p['rect'] is None for p in parsed_pins.values()), 'count'),
        'illegal_macro_overlap': (sum(overlap(a, b) for i, a in enumerate(macro_boxes) for b in macro_boxes[i+1:]), 'count')}
    return d, boxes, parsed_pins, values


def _accept_digital_floorplan(project, context, component, row_id):
    import flow109
    import librelane_contract as ll
    import inspect
    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': row_id, 'status': 'NOT_MEASURED',
        'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
        'delivery_blocked': True, 'obligations': []}
    failures = (MetricRefusal, flow109.Flow109Error, ll.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError)
    try:
        current = flow109.validate_execution_context(context)
        specs = current['resolved_row']['obligations']
        names = ('floorplan_boundary_pin_feasibility', 'illegal_macro_overlap') if row_id == 'D31' else (
            'pad_io_esd_pg_inventory', 'pg_supply_connectivity_errors', 'pad_access_spacing')
        if current['resolved_row']['id'] != row_id or tuple(s['metric'] for s in specs) != names:
            raise MetricRefusal('DIGITAL_FLOORPLAN_CONTRACT_CHANGED', row_id)
        base = 'base_20' if row_id == 'D31' else 'base_21'
        for spec in specs:
            expect = spec['expectation']
            op = ('eq' if spec['metric'] in ('illegal_macro_overlap', 'pg_supply_connectivity_errors')
                  else 'covers_all' if spec['metric'] == 'pad_io_esd_pg_inventory' else 'within_declared_bounds')
            if expect['operator'] != op or (op == 'eq' and (expect.get('value'), expect.get('unit')) != (0, 'count')):
                raise MetricRefusal('DIGITAL_FLOORPLAN_CONTRACT_CHANGED', spec['id'])
            if op == 'within_declared_bounds' and (expect.get('bounds_ref') != f"requirements/{base}/{spec['metric']}.json#/limits"
                    or expect.get('unit_ref') != f"requirements/{base}/{spec['metric']}.json#/units"):
                raise MetricRefusal('DIGITAL_FLOORPLAN_CONTRACT_CHANGED', spec['id'])
        read, reads, states, configs, executions, lefs = _digital_floorplan_readback(project, component)
        terminal = list(states.values())[-1][1]
        d, boxes, pin_records, observations = _digital_def_geometry(read(terminal['def']).decode(), lefs)
        identity = {'producer': executions, 'tool_execution': executions,
            'checker': {'program': 'flow109_metric_acceptance.accept_' + row_id.lower() + '_digital',
                'source_sha256': _sha(inspect.getsource(_accept_digital_floorplan).encode()),
                'geometry_sha256': _sha(inspect.getsource(_digital_def_geometry).encode()),
                'binding_sha256': _sha(inspect.getsource(_digital_floorplan_readback).encode())},
            'consumed_inputs': reads, 'configuration': {'context_sha256': current['context_sha256']},
            'requirements': {'source': 'canonical zero-count invariant'}}
        def numeric(spec, values, required):
            entry = {'id': spec['id'], 'status': 'NOT_MEASURED', 'measurements': []}
            result['obligations'].append(entry)
            try:
                relative = f"requirements/{base}/{spec['metric']}.json"
                auth, body = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
                read(relative, auth['sha256']); read(auth['source']['path'], auth['source']['sha256'])
                limits, units = body['limits'], body['units']
                if not isinstance(limits, dict) or not limits or set(limits) != set(units):
                    raise MetricRefusal('DIGITAL_FLOORPLAN_BOUNDS_INVALID', relative)
                for key, bound in limits.items():
                    value, unit = values.get(key, (None, None))
                    item = {'field': key, 'status': 'NOT_MEASURED'}
                    entry['measurements'].append(item)
                    if value is None or unit != units[key]:
                        item['reason'] = 'DIGITAL_NATIVE_FIELD_OR_UNIT_UNAVAILABLE'
                        continue
                    _finite_number(value, count=unit == 'count')
                    measurement = {'status': 'MEASURED', 'value': value, 'unit': unit,
                        'identity': {**identity, 'requirements': auth}}
                    status, reason = evaluate_operator('within_declared_bounds', measurement,
                        {'status': 'APPROVED', 'limits': bound, 'unit': unit})
                    item.update(status=status, reason=reason, measurement=measurement)
                statuses = [v['status'] for v in entry['measurements']]
                entry['status'] = ('FAIL' if 'FAIL' in statuses else 'PASS'
                    if set(required) <= set(limits) and all(s == 'PASS' for s in statuses) else 'NOT_MEASURED')
            except failures as exc:
                entry.update(reason=getattr(exc, 'code', 'DIGITAL_BOUNDS_UNAVAILABLE'), detail=str(exc))
                if any(v['status'] == 'FAIL' for v in entry['measurements']):
                    entry['status'] = 'FAIL'
        def invariant(spec, value, reason=None):
            measurement = {'status': 'MEASURED' if value is not None else 'NOT_MEASURED',
                'value': value, 'unit': 'count', 'identity': identity, 'reason': reason}
            status, why = evaluate_operator('eq', measurement, {'status': 'APPROVED', 'value': 0, 'unit': 'count'})
            result['obligations'].append({'id': spec['id'], 'status': status, 'reason': why, 'measurement': measurement})
        if row_id == 'D31':
            invariant(specs[1], observations['illegal_macro_overlap'][0])
            header = terminal.get('json_h')
            if not header:
                raise MetricRefusal('DIGITAL_PIN_POPULATION_UNAVAILABLE', 'native Yosys.JsonHeader')
            modules = json.loads(read(header))['modules']
            top = configs['Yosys.JsonHeader'].get('DESIGN_NAME')
            ports = modules[top]['ports']
            expected_pins = set()
            for name, port in ports.items():
                width = len(port['bits'])
                if width < 1:
                    raise MetricRefusal('DIGITAL_PIN_POPULATION_UNAVAILABLE', name)
                if width == 1:
                    expected_pins.add(name)
                else:
                    offset = port.get('offset', 0)
                    expected_pins.update(f'{name}[{i}]' for i in range(offset, offset + width))
            actual_pins = set(pin_records)
            observations['pin_population_errors'] = (len(expected_pins ^ actual_pins), 'count')
            numeric(specs[0], observations, set(observations) - {'illegal_macro_overlap'})
        else:
            if 'OpenROAD.PadRing' not in states:
                raise MetricRefusal('DIGITAL_PADRING_NOT_SELECTED', row_id)
            pad_path, pad_state = states['OpenROAD.PadRing']
            handoff = json.loads(read('reports/phase3/librelane_padring_handoff.json'))
            if Path(handoff['state']) != pad_path or handoff['state_sha256'] != _sha(read(pad_path)):
                raise MetricRefusal('DIGITAL_PADRING_HANDOFF_FOREIGN', row_id)
            # Inventory roles are declared by independent policy, never
            # inferred from a master name. Physical instances/terminals are
            # reopened from this native final DEF and selected LEFs.
            import _pad_ring as pr
            import pad_bterm_coincidence_check as coincidence
            actual_nets = coincidence.def_net_terminals(read(terminal['def']).decode())
            roles = {}
            for lef in lefs:
                for master, pins in pr.parse_lef_pin_roles(read(lef, external=True).decode()).items():
                    for pin, role in pins.items():
                        key = (master, pin)
                        if key in roles and roles[key] != role:
                            raise MetricRefusal('DIGITAL_LEF_AMBIGUOUS', str(key))
                        roles[key] = role
            inv = {'id': specs[0]['id'], 'status': 'NOT_MEASURED'}
            result['obligations'].append(inv)
            required = []
            result['native_inventory'] = [{'instance': n, 'master': c.master, 'placed': c.placed}
                for n, c in sorted(d.components.items())]
            try:
                relative = 'requirements/base_21/pad_io_esd_pg_inventory.json'
                auth, body = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
                read(relative, auth['sha256']); read(auth['source']['path'], auth['source']['sha256'])
                required = body['required_items']
                if (not isinstance(required, list) or not required or any(not isinstance(i, dict)
                        or i.get('kind') not in ('io', 'esd', 'power', 'ground')
                        or set(i) != ({'kind', 'instance', 'master', 'pin', 'net'} if i['kind'] in ('power', 'ground')
                                      else {'kind', 'instance', 'master'}) for i in required)):
                    raise MetricRefusal('DIGITAL_PAD_INVENTORY_UNSUPPORTED', relative)
                observed = []
                for item in required:
                    name, master, kind = item['instance'], item['master'], item['kind']
                    if name not in boxes or d.components[name].master != master:
                        continue
                    if kind in ('power', 'ground'):
                        net, pin = item['net'], item['pin']
                        declared = configs['OpenROAD.GeneratePDN'].get('VDD_NETS' if kind == 'power' else 'GND_NETS') or []
                        # A PSM-clean core grid alone cannot certify an
                        # unconnected IO supply pad. Bind the exact native
                        # terminal/net and its selected LEF USE as well.
                        if (net not in declared or roles.get((master, pin), (None, None))[1] != kind.upper()
                                or not any(i in (name, '*') and p == pin for i, p in actual_nets.get(net, []))):
                            continue
                    observed.append(item)
                measurement = {'status': 'MEASURED', 'value': observed, 'identity': {**identity, 'requirements': auth}}
                inv['status'], inv['reason'] = evaluate_operator('covers_all', measurement,
                    {'status': 'APPROVED', 'required_items': required})
                inv['measurement'] = measurement
                if inv['status'] == 'PASS' and {i['kind'] for i in required} != {'io', 'esd', 'power', 'ground'}:
                    inv.update(status='NOT_MEASURED', reason='DIGITAL_PAD_ESD_PG_POPULATION_UNDECLARED')
            except failures as exc:
                inv.update(reason=getattr(exc, 'code', 'DIGITAL_PAD_INVENTORY_UNAVAILABLE'), detail=str(exc))
            pdn_path, pdn = states['OpenROAD.GeneratePDN']
            config = configs['OpenROAD.GeneratePDN']
            power, ground = config.get('VDD_NETS'), config.get('GND_NETS')
            pg, why = None, 'DIGITAL_PG_PHYSICAL_EVIDENCE_UNAVAILABLE'
            values = pdn.get('metrics', {})
            total = values.get('design__power_grid_violation__count')
            if total is not None:
                _finite_number(total, count=True)
                if total > 0:
                    pg = total
            invariant(specs[1], pg, why)
            pg_entry = result['obligations'][-1]
            nets = power + ground if isinstance(power, list) and isinstance(ground, list) else []
            if nets and power and ground and len(nets) == len(set(nets)):
                counts = [values.get('design__power_grid_violation__count__net:' + net) for net in nets]
                for count in counts:
                    if count is not None:
                        _finite_number(count, count=True)
                positives = sum(v for v in counts if v is not None)
                if positives:
                    pg = max(pg or 0, positives)
                    pg_entry.update(status='FAIL', reason='native per-net connectivity errors',
                        measurement={'status': 'MEASURED', 'value': pg, 'unit': 'count', 'identity': identity})
                log = read(pdn_path.parent / 'invocation.log').decode()
                reports = {p.name for p in pdn_path.parent.glob('*-grid-errors.rpt')}
                expected = {n + '-grid-errors.rpt' for n in nets}
                pg_receipt = ll.validate_step_receipt(pdn_path.parent, 'OpenROAD.GeneratePDN')
                if reports == expected and expected <= pg_receipt['sha256'].keys():
                    for net in nets:
                        name = net + '-grid-errors.rpt'
                        read(pdn_path.parent / name, pg_receipt['sha256'][name])
                    if (total == 0 and all(v == 0 for v in counts)
                            and all(re.search(r'\[INFO PSM-0040\]\s+All shapes on net ' + re.escape(net) + r' are connected\.', log) for net in nets)
                            and not re.search(r'\[(?:ERROR|WARNING).*?(?:PSM-|Grid check)', log)):
                        pg = 0
            if pg is not None:
                pg_entry.update(status='FAIL' if pg else 'PASS',
                    measurement={'status': 'MEASURED', 'value': pg, 'unit': 'count', 'identity': identity})
            lef_text = '\n'.join(read(p, external=True).decode() for p in lefs)
            rc, access = coincidence.run(read(terminal['def']).decode(), lef_text, lefs)
            signals = {name for name, pin in pin_records.items() if pin['use'] not in ('POWER', 'GROUND')}
            rows = {r['pin']: r for r in access['nets']}
            access_errors = (sum(rows[n]['verdict'] == 'NOT_CONNECTED' for n in signals) if signals
                and signals <= rows.keys() and not any(rows[n]['verdict'] == 'UNDECIDED'
                    or pin_records[n]['placement'] is None or pin_records[n]['placement'][2] != 'N' for n in signals) else None)
            def gap(a, b):
                dx, dy = max(a[0]-b[2], b[0]-a[2], 0), max(a[1]-b[3], b[1]-a[3], 0)
                return math.hypot(dx, dy) / d.units
            io = [boxes[i['instance']] for i in required if i.get('kind') == 'io' and i.get('instance') in boxes]
            pad_gaps = [gap(a, b) for i, a in enumerate(io) for b in io[i+1:]]
            pin_gaps = [gap(a['rect'], b['rect']) for i, (n, a) in enumerate(sorted(pin_records.items()))
                for m, b in sorted(pin_records.items())[i+1:] if n in signals and m in signals and a['rect'] is not None and b['rect'] is not None and a['layer'] == b['layer']]
            spacing = {'min_pad_spacing_um': (min(pad_gaps) if pad_gaps else None, 'um'),
                'min_pin_access_spacing_um': (min(pin_gaps) if pin_gaps else None, 'um'),
                'pin_access_errors': (access_errors, 'count')}
            numeric(specs[2], spacing, spacing.keys())
        for path, digest in list(reads.items()):
            read(path, digest, external=True)
        result['readset'] = dict(reads)
    except failures as exc:
        result.update(reason=getattr(exc, 'code', 'DIGITAL_FLOORPLAN_UNBOUND'), detail=str(exc))
        for obligation in result['obligations']:
            if obligation['status'] == 'PASS':
                obligation.update(status='NOT_MEASURED', reason='DIGITAL_BINDING_INCOMPLETE')
    if component.get('verdict') == 'FAIL' or any(o['status'] == 'FAIL' for o in result['obligations']):
        result['status'] = result['metric_status'] = 'FAIL'
    elif len(result['obligations']) == (2 if row_id == 'D31' else 3) and all(o['status'] == 'PASS' for o in result['obligations']):
        result['metric_status'] = 'PASS'
        import flow109_admission as admission
        try:
            result['qualification_receipt'] = admission.require_admission(project, current)
            result.update(status='PASS', qualification='PASS', delivery_blocked=False)
        except admission.AdmissionRefusal as exc:
            result.update(reason=exc.code, qualification_receipt=exc.report)
    return result


def accept_d31_digital(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    return _accept_digital_floorplan(project, context, component, 'D31')


def accept_d32_digital(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    return _accept_digital_floorplan(project, context, component, 'D32')


def _d35_selected_congestion(text):
    """Read the normal GPL pass and explicit revert, without borrowing GRT.

    OpenROAD 89df516 src/gpl/src/routeBase.cpp emits GPL-0040/0055.
    Weighted congestion is dimensionless; it is not routing overflow.
    """
    number = r'([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)'
    pass_re = re.compile(r'\[INFO GPL-0040\] Routability pass (\d+): weighted congestion '
        + number + r' \(target ' + number + r'\), (\d+) of (\d+) actionable tiles overflowed \('
        + number + r'%\)\.')
    revert_re = re.compile(r'\[INFO GPL-0055\] Reverting inflation and target density to the pass with the '
        r'minimum observed routing congestion \(' + number + r'\), target density ' + number + r'\.')
    passes, selected = [], None
    for line in text.splitlines():
        match = pass_re.fullmatch(line.strip())
        if match:
            _, value, _, count, population, percent = match.groups()
            value, percent, count, population = float(value), float(percent), int(count), int(population)
            if count > population or not 0 <= percent <= 100 or (population and abs(percent - 100*count/population) > .051):
                raise MetricRefusal('D35_CONGESTION_INVALID', line)
            selected = (value, count, percent)
            passes.append(selected)
        elif revert_re.fullmatch(line.strip()):
            minimum = float(revert_re.fullmatch(line.strip())[1])
            matches = {entry for entry in passes if entry[0] == minimum}
            # A rounded minimum identifying multiple populations cannot bind
            # their tile counts. The weighted value itself is still explicit.
            selected = next(iter(matches)) if len(matches) == 1 else (minimum, None, None)
        elif '[INFO GPL-0040]' in line or '[INFO GPL-0055]' in line:
            raise MetricRefusal('D35_CONGESTION_UNSUPPORTED', line)
    if selected is None:
        return {}
    return {key: {'metric': key, 'status': 'MEASURED', 'value': value, 'unit': unit,
            'scope': {'stage': 'global_placement'}, 'source': 'GPL-0040/0055 selected native pass'}
        for key, value, unit in [
            ('route.congestion.weighted', selected[0], '1'),
            ('route.congestion.overflowed_tiles.count', selected[1], '1'),
            ('route.congestion.overflowed_tiles.pct', selected[2], '%')] if value is not None}


def accept_d35(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """BLOCKING metric readback of the existing placement chain, without EDA replay.

    Component completion does not qualify the tool or close the Flow109 row.
    Bounds remain requirements-owner inputs; missing metrics remain unmeasured.
    """
    import flow109
    import librelane_contract as ll
    import placement_legality_check as legality
    from _ppa.backends import openroad as placement_metrics
    import inspect
    import execution_backend_producers as native_producer

    project = Path(project).resolve()
    names = ('placement_legality_errors', 'pre_cts_setup_drv_targets', 'congestion_targets')
    result = {'schema': SCHEMA, 'row_id': 'D35', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    reads = {}

    def _d35_bound(path, digest=None):
        path = Path(path)
        if not path.is_absolute():
            path = project / path
        if (path.is_symlink() or not path.resolve().is_relative_to(project)
                or not path.is_file()):
            raise MetricRefusal('D35_INPUT_UNBOUND', str(path))
        raw = path.read_bytes()
        sha = _sha(raw)
        if digest is not None and sha != digest:
            raise MetricRefusal('D35_INPUT_CHANGED', str(path))
        reads[str(path.relative_to(project))] = sha
        return path, raw

    def _d35_document(path, digest=None):
        path, raw = _d35_bound(path, digest)
        return path, json.loads(raw)

    try:
        current = flow109.validate_execution_context(context)
        row = current['resolved_row']
        if row['id'] != 'D35' or tuple(o['metric'] for o in row['obligations']) != names:
            raise MetricRefusal('D35_CONTRACT_CHANGED', 'placement obligations')
        specs = row['obligations']
        if (specs[0]['expectation'].get('operator') != 'eq'
                or specs[0]['expectation'].get('value') != 0
                or specs[0]['expectation'].get('unit') != 'count'
                or any(o['expectation'].get('operator') != 'within_declared_bounds'
                       or o['expectation'].get('bounds_ref') !=
                       f"requirements/base_23/{o['metric']}.json#/limits"
                       or o['expectation'].get('unit_ref') !=
                       f"requirements/base_23/{o['metric']}.json#/units"
                       for o in specs[1:])):
            raise MetricRefusal('D35_CONTRACT_CHANGED', 'placement expectations')
        _, chain = _d35_document('reports/phase3/execution-backend-17.json')
        steps = chain['ordered_steps']
        if (not isinstance(steps, list) or len(set(steps)) != len(steps)
                or steps[0] != 'OpenROAD.GlobalPlacement'
                or steps[-1] != 'OpenROAD.DetailedPlacement'
                or 'OpenROAD.RepairDesignPostGPL' not in steps
                or len(chain['states']) != len(steps)):
            raise MetricRefusal('D35_CHAIN_UNBOUND', 'selected native placement chain')
        previous, _ = _d35_bound(chain['initial_state'], chain['initial_sha256'])
        executions = []
        congestion = {}
        for step, state_ref in zip(steps, chain['states']):
            state_path, state = _d35_document(state_ref['state'], state_ref['sha256'])
            if state_ref['step'] != step:
                raise MetricRefusal('D35_CHAIN_UNBOUND', step)
            folder = state_path.parent
            if folder.parent != project / 'phase3/librelane/execution-backend-17':
                raise MetricRefusal('D35_FOREIGN_ROUTE', str(folder))
            receipt = ll.validate_step_receipt(folder, step)
            _d35_bound(folder / 'vibeic_receipt.json')
            for name, sha in receipt['sha256'].items():
                _d35_bound(folder / name, sha)
            fp = receipt['input']
            if fp.get('image') != component.get('native_image') or not fp.get('image'):
                raise MetricRefusal('D35_IMAGE_CHANGED', step)
            if step.startswith(ll.PLUGIN_STEP_PREFIX) and fp.get('plugin') != ll._plugin_digests(step):
                raise MetricRefusal('D35_PRODUCER_SOURCE_CHANGED', step)
            _d35_bound(previous, fp['state'])
            config_path = state_ref.get('config') or project / 'phase3/librelane/execution-backend-17-config' / (step + '.json')
            _, selected_config = _d35_document(config_path, fp['config'])
            if state_ref.get('config_sha256', fp['config']) != fp['config'] or selected_config.get('meta', {}).get('step') != step:
                raise MetricRefusal('D35_CONFIG_CHANGED', step)
            _, input_state = _d35_document(previous, fp['state'])
            actual_state_files = {str(p): _sha(_d35_bound(p)[1]) for p in ll._walk_paths(
                {k: v for k, v in input_state.items() if k != 'metrics'})}
            if fp.get('state_files') != actual_state_files:
                raise MetricRefusal('D35_INPUT_POPULATION_CHANGED', step)
            if not fp.get('state_files') or not fp.get('config_files'):
                raise MetricRefusal('D35_INPUT_POPULATION_ABSENT', step)
            for path, sha in fp['state_files'].items():
                _d35_bound(path, sha)
            # Reopen actual model/deck bytes through the native owner's mount map.
            _, mapping = _d35_document(folder / 'pdk_root.json')
            mounts = mapping['mounts_under_it']
            ll._current_config_material(selected_config, mounts)
            if fp['config_files'] != ll.config_file_hashes(selected_config, mounts):
                raise MetricRefusal('D35_CONFIG_POPULATION_CHANGED', step)
            for path, sha in fp['config_files'].items():
                source = Path(path)
                for host, guest in sorted(mounts, key=lambda m: len(m[1]), reverse=True):
                    if source.is_relative_to(guest):
                        source = Path(host) / source.relative_to(guest)
                        break
                if source.resolve().is_relative_to(project):
                    _d35_bound(source, sha)
                elif (source.is_symlink() or not source.is_file()
                      or _sha(source.read_bytes()) != sha):
                    raise MetricRefusal('D35_MODEL_CHANGED', str(source))
                else:
                    reads[str(source)] = sha
            executions.append({'step': step, 'input': fp,
                               'receipt_sha256': _sha((folder / 'vibeic_receipt.json').read_bytes())})
            if step == 'OpenROAD.GlobalPlacement':
                log, _ = _d35_bound(folder / 'invocation.log', receipt['sha256']['invocation.log'])
                congestion = {record['metric']: record for record in placement_metrics.parse_log(log).records
                              if record['metric'].startswith('route.congestion.')
                              and record.get('scope', {}).get('stage') == 'global_placement'}
                congestion.update(_d35_selected_congestion(log.read_text()))
            previous = state_path
        _, handoff = _d35_document('reports/phase3/librelane_placement_handoff.json')
        handed_state, _ = _d35_bound(handoff['state'], handoff['state_sha256'])
        if handed_state != previous:
            raise MetricRefusal('D35_HANDOFF_FOREIGN', 'not the terminal placement state')
        for view, dest in (('def', 'placed.def'), ('odb', 'librelane_placed.odb')):
            record = handoff['views'][view]
            source, _ = _d35_bound(record['source'], record['source_sha256'])
            target, _ = _d35_bound(record['dest'], record['dest_sha256'])
            if (target != project / 'phase3/stage3/pnr' / dest
                    or state.get(view) != str(source)
                    or record['source_sha256'] != record['dest_sha256']):
                raise MetricRefusal('D35_HANDOFF_FOREIGN', view)
        # Bind the existing reader's complete log/density input population.
        reader_paths = set(legality._verdict_logs(project))
        for relative in legality._DENSITY_JSON_CANDIDATES:
            if (project / relative).is_file():
                reader_paths.add(project / relative)
        for path in sorted(reader_paths):
            _d35_bound(path)
        # Use the existing semantic reader, not the wrapper's rc or PASS label.
        verdict, _, findings, summary = legality.inspect(project)
        result['component_status'] = verdict
        measured = {'status': 'MEASURED' if verdict == 'PASS' else
                    'FAIL' if verdict == 'FAIL' else 'NOT_MEASURED',
                    'unit': 'count', 'reason': verdict, 'findings': findings}
        if verdict == 'PASS':
            measured['value'] = 0
        authority = {'status': 'APPROVED', 'value': 0, 'unit': 'count',
                     'source': 'canonical base_23.placement_legality_errors invariant'}
        identity = {'producer': executions, 'checker': {'program': 'placement_legality_check.inspect',
                    'sha256': _sha(Path(legality.__file__).read_bytes()),
                    'congestion_parser_sha256': _sha(Path(placement_metrics.__file__).read_bytes()),
                    'selected_congestion_parser_sha256': _sha(inspect.getsource(_d35_selected_congestion).encode()),
                    'metric_reader_sha256': _sha(inspect.getsource(accept_d35).encode()),
                    'producer_sha256': _sha(inspect.getsource(native_producer.produce_pnr).encode())},
                    'tool_execution': executions, 'consumed_inputs': dict(reads),
                    'requirements': authority, 'configuration': {'context_sha256': current['context_sha256']}}
        measured['identity'] = identity
        status, reason = evaluate_operator('eq', measured, authority)
        result['obligations'].append({'id': specs[0]['id'], 'status': status,
                                     'reason': reason, 'measurement': measured})
        # Do not invent numeric selectors, units or bounds. The requirements
        # owner names native state metric fields in limits/units dictionaries.
        for spec in specs[1:]:
            obligation = {'id': spec['id'], 'status': 'NOT_MEASURED'}
            result['obligations'].append(obligation)
            values = []
            try:
                relative = spec['expectation']['bounds_ref'].split('#/')[0]
                auth, body = _approved_document(project, relative, authority='requirements_owner',
                                               schema=AUTHORITY_SCHEMA)
                _d35_bound(relative, auth['sha256'])
                _d35_bound(auth['source']['path'], auth['source']['sha256'])
                limits, units = body['limits'], body['units']
                if (not isinstance(limits, dict) or not limits or set(limits) != set(units)
                        or any(not isinstance(k, str) for k in limits)):
                    raise MetricRefusal('D35_BOUNDS_INVALID', relative)
                for field, bounds in limits.items():
                    if spec['metric'] == 'congestion_targets':
                        record = congestion.get(field) or {}
                        value = record.get('value') if record.get('status') == 'MEASURED' else None
                        unit = record.get('unit')
                    else:
                        if not (re.fullmatch(r'timing__setup__(?:ws|tns)(?:__corner:[^\s]+)?', field) or
                                field in ('design__max_slew_violation__count', 'design__max_cap_violation__count',
                                          'design__max_fanout_violation__count')):
                            raise MetricRefusal('D35_NATIVE_FIELD_UNSUPPORTED', field)
                        value = state.get('metrics', {}).get(field)
                        unit = 'count' if field.endswith('__count') else 'ns'
                        if value is not None and unit == 'count':
                            _finite_number(value, count=True)
                    if value is None or unit != units[field]:
                        values.append({'field': field, 'status': 'NOT_MEASURED',
                                       'reason': 'native metric absent or unit differs'})
                        continue
                    observation = {'status': 'MEASURED', 'value': value, 'unit': units[field],
                                   'identity': {**identity, 'requirements': auth}}
                    field_status, field_reason = evaluate_operator('within_declared_bounds', observation,
                        {'status': 'APPROVED', 'limits': bounds, 'unit': units[field]})
                    values.append({'field': field, 'status': field_status,
                                   'reason': field_reason, 'measurement': observation})
                statuses = [v['status'] for v in values]
                obligation.update(status='FAIL' if 'FAIL' in statuses else
                                  'PASS' if all(s == 'PASS' for s in statuses) else 'NOT_MEASURED',
                                  measurements=values, authority=auth)
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                obligation['reason'] = str(exc)
                if any(value['status'] == 'FAIL' for value in values):
                    obligation.update(status='FAIL', measurements=values)
        if set(legality._verdict_logs(project)) != set(p for p in reader_paths if p.suffix == '.log'):
            raise MetricRefusal('D35_INPUT_CHANGED_DURING_READ', 'placement log population')
        for path, sha in reads.items():
            actual = Path(path) if Path(path).is_absolute() else project / path
            if actual.is_symlink() or _sha(actual.read_bytes()) != sha:
                raise MetricRefusal('D35_INPUT_CHANGED_DURING_READ', path)
        result['readset'] = reads
        statuses = [o['status'] for o in result['obligations']]
        result['metric_status'] = ('FAIL' if 'FAIL' in statuses else
                                   'PASS' if all(s == 'PASS' for s in statuses) else 'NOT_MEASURED')
    except (MetricRefusal, flow109.Flow109Error, ll.Refusal,
            OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D35_NATIVE_BINDING_UNPROVEN'), detail=str(exc), metric_status='NOT_MEASURED')
    # A measured failure survives a later missing/tampered sibling input.
    if component.get('verdict') == 'FAIL' or result.get('component_status') == 'FAIL' or any(
            o['status'] == 'FAIL' for o in result['obligations']):
        result['status'] = result['metric_status'] = 'FAIL'
    elif result['metric_status'] == 'PASS':
        import flow109_admission as admission
        try:
            result['qualification_receipt'] = admission.require_admission(project, current)
            result.update(status='PASS', qualification='PASS', delivery_blocked=False)
        except admission.AdmissionRefusal as exc:
            result.update(reason=exc.code, qualification_receipt=exc.report)
    return result


def accept_d37(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """Read the original spare insertion census and current DEF; never remove spares.

    Existing coverage/tie readers own their semantics and density floor.
    Missing external bounds/qualification remain unmeasured.
    """
    import flow109
    import librelane_contract as ll
    import spare_cell_coverage_check as coverage
    import inspect

    project = Path(project).resolve()
    result = {'schema': SCHEMA, 'row_id': 'D37', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    reads = {}

    def _d37_bound(path, digest=None):
        path = Path(path)
        if not path.is_absolute():
            path = project / path
        if path.is_symlink() or not path.resolve().is_relative_to(project) or not path.is_file():
            raise MetricRefusal('D37_INPUT_UNBOUND', str(path))
        raw = path.read_bytes()
        sha = _sha(raw)
        if digest is not None and digest != sha:
            raise MetricRefusal('D37_INPUT_CHANGED', str(path))
        reads[str(path.relative_to(project))] = sha
        return path, raw

    def _d37_document(path, digest=None):
        path, raw = _d37_bound(path, digest)
        return path, json.loads(raw)

    try:
        current = flow109.validate_execution_context(context)
        row = current['resolved_row']
        specs = row['obligations']
        if (row['id'] != 'D37' or [s['id'] for s in specs] != [
                'base_24.required_spare_distribution', 'base_24.spare_tie_connectivity_errors']
                or specs[0]['expectation'].get('operator') != 'within_declared_bounds'
                or specs[0]['expectation'].get('bounds_ref') !=
                    'requirements/base_24/required_spare_distribution.json#/limits'
                or specs[0]['expectation'].get('unit_ref') !=
                    'requirements/base_24/required_spare_distribution.json#/units'
                or any(specs[1]['expectation'].get(k) != v for k, v in
                       {'operator': 'eq', 'value': 0, 'unit': 'count'}.items())):
            raise MetricRefusal('D37_CONTRACT_CHANGED', 'existing spare obligations only')
        _, chain = _d37_document('reports/phase3/execution-backend-18.json')
        step = 'Vibeic.InsertSpareCells'
        if chain['ordered_steps'] != [step] or len(chain['states']) != 1:
            raise MetricRefusal('D37_CHAIN_UNBOUND', 'single native insertion')
        initial, _ = _d37_bound(chain['initial_state'], chain['initial_sha256'])
        reference = chain['states'][0]
        state_path, state = _d37_document(reference['state'], reference['sha256'])
        if reference['step'] != step:
            raise MetricRefusal('D37_CHAIN_UNBOUND', step)
        folder = state_path.parent
        receipt = ll.validate_step_receipt(folder, step)
        _d37_bound(folder / 'vibeic_receipt.json')
        for relative, sha in receipt['sha256'].items():
            _d37_bound(folder / relative, sha)
        fp = receipt['input']
        if (fp.get('image') != component.get('native_image') or not fp.get('image')
                or fp.get('plugin') != ll._plugin_digests(step)):
            raise MetricRefusal('D37_PRODUCER_CHANGED', 'image or consumed plugin sources')
        _d37_bound(initial, fp['state'])
        _d37_bound(project / 'phase3/librelane/execution-backend-18-config' / (step + '.json'), fp['config'])
        if not fp.get('state_files') or not fp.get('config_files'):
            raise MetricRefusal('D37_INPUT_POPULATION_ABSENT', step)
        for path, sha in fp['state_files'].items():
            _d37_bound(path, sha)
        mounts = json.loads((folder / 'pdk_root.json').read_text())['mounts_under_it']
        for path, sha in fp['config_files'].items():
            source = Path(path)
            for host, guest in sorted(mounts, key=lambda m: len(m[1]), reverse=True):
                if source.is_relative_to(guest):
                    source = Path(host) / source.relative_to(guest)
                    break
            if source.resolve().is_relative_to(project):
                _d37_bound(source, sha)
            elif source.is_symlink() or not source.is_file() or _sha(source.read_bytes()) != sha:
                raise MetricRefusal('D37_MODEL_CHANGED', str(source))
            else:
                reads[str(source)] = sha
        _, handoff = _d37_document('reports/phase3/librelane_spare_handoff.json')
        handed, _ = _d37_bound(handoff['state'], handoff['state_sha256'])
        if handed != state_path:
            raise MetricRefusal('D37_HANDOFF_FOREIGN', 'native insertion state')
        for view, name in (('def', 'post_spare.def'), ('odb', 'post_spare.odb')):
            rec = handoff['views'][view]
            source, _ = _d37_bound(rec['source'], rec['source_sha256'])
            dest, _ = _d37_bound(rec['dest'], rec['dest_sha256'])
            if (dest != project / 'phase3/stage3/pnr' / name or state.get(view) != str(source)
                    or rec['source_sha256'] != rec['dest_sha256']):
                raise MetricRefusal('D37_HANDOFF_FOREIGN', view)
        native_plans = [p for p in receipt['sha256'] if Path(p).name == 'spare_cells.json']
        if len(native_plans) != 1:
            raise MetricRefusal('D37_NATIVE_PLAN_UNBOUND', 'unique receipt-owned native plan required')
        _, plan = _d37_document(folder / native_plans[0], receipt['sha256'][native_plans[0]])
        _d37_bound('phase3/stage3/pnr/spare_cells.json', receipt['sha256'][native_plans[0]])
        native = plan['measured']
        count = _finite_number(native['inserted'], count=True)
        placed = _finite_number(native['placed_cells'], count=True)
        if count == 0:
            result['component_status'] = 'FAIL'
            raise MetricRefusal('D37_NO_SPARES_INSERTED', 'requires_spares remains selected')
        inputs = native['tieoff_inputs']
        if (not placed or not count or count != plan['count'] or count != len(plan['instances'])
                or not isinstance(inputs, list) or not inputs
                or inputs != plan['tie_off']['inputs']
                or plan['actual_density'] != count / placed):
            raise MetricRefusal('D37_NATIVE_CENSUS_INCOMPLETE', 'producer-owned DB census required')
        observed = coverage.audit(project, post_spare_def=True)
        result['component_status'] = observed['verdict']
        identity = {'producer': {'receipt': _sha((folder / 'vibeic_receipt.json').read_bytes()),
                                'native_input': fp},
                    'checker': {'coverage_sha256': _sha(Path(coverage.__file__).read_bytes()),
                                'metric_reader_sha256': _sha(inspect.getsource(accept_d37).encode())},
                    'tool_execution': {'image': fp['image'], 'state_sha256': reference['sha256']},
                    'consumed_inputs': dict(reads), 'requirements': 'bound per obligation',
                    'configuration': {'context_sha256': current['context_sha256']}}
        # The complete pin population is produced from every non-supply input
        # ITerm of the native DB, including CLOCK pins, by the bound plugin.
        connectivity_ok = (observed['tie_off_ok'] and observed['inserted_def']['verdict'] == 'PASS'
                           and _finite_number(native['pg_unconnected'], count=True) == 0)
        measured = {'status': 'MEASURED' if connectivity_ok else 'FAIL', 'unit': 'count',
                    'identity': identity, 'reason': 'native per-pin and DEF connectivity',
                    'pin_census': inputs, 'checker': observed}
        if connectivity_ok:
            measured['value'] = 0
        status, reason = evaluate_operator('eq', measured, {'status': 'APPROVED', 'value': 0, 'unit': 'count'})
        result['obligations'].append({'id': specs[1]['id'], 'status': status,
                                     'reason': reason, 'measurement': measured})
        distribution = {'id': specs[0]['id'], 'status': 'NOT_MEASURED'}
        result['obligations'].append(distribution)
        if not observed['density_ok'] or not observed['distribution_ok']:
            distribution.update(status='FAIL', reason='existing density/distribution reader rejects native pool')
        else:
            values = {'actual_density': (count / placed, 'ratio'),
                      'distribution_fraction': (observed['distinct_positions'] / count, 'ratio'),
                      'distinct_positions': (observed['distinct_positions'], 'count'), 'count': (count, 'count')}
            field_results = []
            try:
                relative = 'requirements/base_24/required_spare_distribution.json'
                auth, body = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
                _d37_bound(relative, auth['sha256'])
                _d37_bound(auth['source']['path'], auth['source']['sha256'])
                limits, units = body['limits'], body['units']
                if not isinstance(limits, dict) or not limits or set(limits) != set(units) or not set(limits) <= set(values):
                    raise MetricRefusal('D37_BOUNDS_INVALID', relative)
                for field, bounds in limits.items():
                    value, unit = values[field]
                    measurement = {'status': 'MEASURED', 'value': value, 'unit': unit,
                                   'identity': {**identity, 'requirements': auth}}
                    s, reason = evaluate_operator('within_declared_bounds', measurement,
                        {'status': 'APPROVED', 'limits': bounds, 'unit': units[field]})
                    field_results.append({'field': field, 'status': s, 'reason': reason, 'measurement': measurement})
                statuses = [f['status'] for f in field_results]
                distribution.update(status='FAIL' if 'FAIL' in statuses else
                                    'PASS' if all(s == 'PASS' for s in statuses) else 'NOT_MEASURED',
                                    measurements=field_results, authority=auth)
            except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
                distribution['reason'] = str(exc)
                if any(f['status'] == 'FAIL' for f in field_results):
                    distribution.update(status='FAIL', measurements=field_results)
        for relative, sha in reads.items():
            path = Path(relative) if Path(relative).is_absolute() else project / relative
            if path.is_symlink() or _sha(path.read_bytes()) != sha:
                raise MetricRefusal('D37_INPUT_CHANGED_DURING_READ', relative)
        result['readset'] = reads
        statuses = [o['status'] for o in result['obligations']]
        result['metric_status'] = 'FAIL' if 'FAIL' in statuses else 'PASS' if all(s == 'PASS' for s in statuses) else 'NOT_MEASURED'
    except (MetricRefusal, flow109.Flow109Error, ll.Refusal,
            OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(reason=getattr(exc, 'code', 'D37_NATIVE_BINDING_UNPROVEN'), detail=str(exc))
    if component.get('verdict') == 'FAIL' or result.get('component_status') == 'FAIL' or any(
            o['status'] == 'FAIL' for o in result['obligations']):
        result['status'] = result['metric_status'] = 'FAIL'
    return result


def accept_a02(project: Path, context: Mapping, component: Mapping) -> dict:
    """Read the existing smoke logs against an independently declared population."""
    import analog_native_flow as native
    import flow109_analog_model_check as checker
    import flow109_analog_a02 as models
    import shutil
    project = Path(project).resolve()
    answer = {"schema": SCHEMA, "step_id": "A02", "status": "NOT_MEASURED",
              "metrics": {}, "scope": "model smoke metrics only; qualification separate"}
    readset = {}
    def bound(value, views):
        path = Path(value)
        path = path if path.is_absolute() else project / path
        relative = str(path.relative_to(project))
        path = _safe_project_file(project, relative)
        digest = views.get(str(path))
        if not _HEX.fullmatch(str(digest or "")) or _sha(path.read_bytes()) != digest:
            raise MetricRefusal("A02_NATIVE_INPUT_UNBOUND", relative)
        readset[str(path)] = digest
        return path
    def document(path):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise MetricRefusal("A02_DUPLICATE_JSON_KEY", key)
                result[key] = value
            return result
        return json.loads(path.read_bytes(), object_pairs_hook=unique)
    try:
        invocation = component.get("a02_invocation")
        if not isinstance(invocation, dict) or not invocation.get("inputs") or not invocation.get("sources"):
            raise MetricRefusal("A02_INVOCATION_READSET_ABSENT", "consumed bytes were not captured before launch")
        for value in invocation["inputs"]:
            if not Path(value).is_relative_to(project / "requirements"):
                bound(value, invocation["inputs"])
        from execution_provider_catalog import source_closure
        import analog_native_front as front
        current_sources = {str(path): _sha(path.read_bytes()) for path in source_closure({
            Path(native.__file__), Path(__file__), Path(front.__file__), Path(checker.__file__)})}
        if invocation["sources"] != current_sources:
            raise MetricRefusal("A02_PRODUCER_SOURCE_STALE", "source closure")
        tool = invocation["tool"]
        tool_path = Path(tool["path"])
        if (not tool_path.is_file() or _sha(tool_path.read_bytes()) != tool["sha256"]
                or Path(shutil.which("ngspice") or "").resolve() != tool_path):
            raise MetricRefusal("A02_TOOL_STALE", str(tool_path))
        report = component["native_results"]
        if report.get("image") != invocation.get("image") or not invocation.get("image"):
            raise MetricRefusal("A02_IMAGE_MISMATCH", "selected execution image")
        attempt = Path(report["attempt"])
        if not attempt.is_relative_to(project / "reports/analog_native"):
            raise MetricRefusal("A02_NATIVE_ATTEMPT_FOREIGN", str(attempt))
        stored_path = _safe_project_file(project, str((attempt / "result.json").relative_to(project)))
        stored = document(stored_path)
        if report != stored or report.get("source_sha256") != _sha(Path(native.__file__).read_bytes()):
            raise MetricRefusal("A02_NATIVE_ATTEMPT_STALE", str(attempt))
        readset[str(stored_path)] = _sha(stored_path.read_bytes())
        blocks = native._declared_blocks(project)
        names = sorted(b.get("name") or b.get("block") for b in blocks)
        rows = [row for row in report["steps"] if row.get("step") == "A02"]
        if not names or sorted(row["block"] for row in rows) != names:
            raise MetricRefusal("A02_BLOCK_POPULATION_MISMATCH", str(names))
        observed, errors = [], 0
        for row in rows:
            views = row["input_views"]
            if any(invocation["inputs"].get(path) != digest for path, digest in views.items()):
                raise MetricRefusal("A02_CONSUMED_INPUT_CHANGED", row["block"])
            if not views or not row.get("output_views"):
                raise MetricRefusal("A02_NATIVE_READSET_ABSENT", row["block"])
            if any(views.get(key) != digest for key, digest in native._input_views(project, row["block"], "A02").items()):
                raise MetricRefusal("A02_NATIVE_READSET_STALE", row["block"])
            for value in views:
                bound(value, views)
            for value in row["output_views"]:
                bound(value, row["output_views"])
            producer = row["producer_context"]
            if (not report.get("image") or producer.get("image") != report["image"]
                    or producer.get("driver_sha256") != report["source_sha256"]):
                raise MetricRefusal("A02_NATIVE_EXECUTION_IDENTITY_ABSENT", row["block"])
            config = document(bound(project / "input/analog_flow.json", views))
            cfg = (config.get("blocks") or {}).get(row["block"], {})
            smokes = cfg.get("model_smokes", config.get("model_smokes"))
            if smokes is None:
                smokes = document(bound(project / "input/flow109/A02.json", views))["smokes"]
            if not isinstance(smokes, list) or not smokes:
                raise MetricRefusal("A02_SMOKE_DECLARATIONS_ABSENT", row["block"])
            executions = row["executions"]
            needs, receipts, ids, temperatures = [], [], set(), {}
            for smoke in smokes:
                ident = smoke["id"]
                if ident in ids:
                    raise MetricRefusal("A02_DUPLICATE_SMOKE", ident)
                ids.add(ident)
                model, deck = (bound(smoke[key]["path"] if isinstance(smoke[key], dict) else smoke[key], views)
                               for key in ("model", "deck"))
                for key, path in (("model", model), ("deck", deck)):
                    if isinstance(smoke[key], dict) and smoke[key].get("sha256") != readset[str(path)]:
                        raise MetricRefusal("A02_SMOKE_DECLARATION_STALE", ident)
                need = {key: smoke[key] for key in ("id", "device", "corner", "required_measurements")}
                need.update(model={"path": str(model.relative_to(project)), "sha256": readset[str(model)]},
                            deck={"path": str(deck.relative_to(project)), "sha256": readset[str(deck)]})
                declared_temperatures = re.findall(r"(?im)^\s*\.temp\s+(" + checker.NUMBER + r")\s*$", deck.read_text())
                if len(declared_temperatures) != 1:
                    raise MetricRefusal("A02_SMOKE_TEMPERATURE_UNDECLARED", ident)
                temperature = _finite_number(float(declared_temperatures[0]))
                temperatures[ident] = format(temperature, "g")
                declared = {Path(value): {"path": str(Path(value).relative_to(project)), "sha256": digest}
                            for value, digest in views.items() if Path(value).is_relative_to(project)}
                closure = models._deck_contract(project, need, model, deck, declared)
                for entry in closure["files"]:
                    bound(project / entry["path"], views)
                matches = [ex for ex in executions if ex.get("program") == "@ngspice"
                           and ex.get("args", [])[-1:] == [str(deck)]]
                if len(matches) != 1:
                    raise MetricRefusal("A02_SMOKE_EXECUTION_UNBOUND", ident)
                execution = matches[0]
                if (execution.get("argv") != ["ngspice", *execution["args"]]
                        or execution.get("cwd") != str(project)):
                    raise MetricRefusal("A02_NATIVE_INVOCATION_MISMATCH", ident)
                if execution.get("missing_outputs"):
                    raise MetricRefusal("A02_SMOKE_OUTPUT_ABSENT", ident)
                args = execution["args"]
                if len(args) != 4 or args[:2] != ["-b", "-o"]:
                    raise MetricRefusal("A02_SMOKE_INVOCATION_INVALID", ident)
                log = bound(args[2], execution["outputs"])
                bound(execution["log"], {execution["log"]: execution["log_sha256"]})
                needs.append(need)
                receipts.append({**need, "returncode": execution["returncode"],
                                 "log": {"path": str(log.relative_to(project)), "sha256": readset[str(log)]}})
            checked = checker.consume(project, {"required_smokes": needs}, {"smokes": receipts})
            if checked["verdict"] != "PASS":
                errors += 1
            for item in checked["smokes"]:
                log_text = (project / item["log"]["path"]).read_text()
                native_temperatures = re.findall(r"(?im)Doing analysis at TEMP\s*=\s*(" + checker.NUMBER + r")", log_text)
                if (not native_temperatures or any(format(float(value), "g") != temperatures[item["id"]]
                                                   for value in native_temperatures)):
                    raise MetricRefusal("A02_NATIVE_TEMPERATURE_UNBOUND", item["id"])
                observed.append({"block": row["block"], "device": item["device"], "corner": item["corner"],
                                 "temperature_c": temperatures[item["id"]]})
        answer["metrics"]["device_model_load_errors"] = {
            "status": "FAIL" if errors else "PASS", "value": errors, "unit": "count"}
        relative = "requirements/base_A2/model_corner_statistics_coverage.json"
        authority_path = _safe_project_file(project, relative)
        bound(authority_path, invocation["inputs"])
        document(authority_path)
        authority, _ = _approved_authority(project, relative + "#/required_items", ("block", "device", "corner", "temperature_c"))
        readset[str(authority_path)] = authority["sha256"]
        bound(project / authority["source"]["path"], invocation["inputs"])
        required = authority["required_items"]
        if not required or len({_json_key(item) for item in required}) != len(required):
            raise MetricRefusal("A02_REQUIRED_POPULATION_INVALID", relative)
        missing = [item for item in required if item not in observed]
        answer["metrics"]["model_corner_statistics_coverage"] = {
            "status": "FAIL" if missing else "PASS", "value": observed,
            "required_items": required, "missing": missing, "authority": authority}
        if any(_sha(Path(path).read_bytes()) != digest for path, digest in readset.items()):
            raise MetricRefusal("A02_INPUT_CHANGED_DURING_ACCEPTANCE", "readset")
        answer.update(status="FAIL" if errors or missing else "PASS", reason="A02_NATIVE_METRICS_EVALUATED",
                      input_views=readset)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer.update(status="FAIL" if any(row.get("status") == "FAIL" for row in answer["metrics"].values())
                      else "NOT_MEASURED", reason=getattr(exc, "code", "A02_METRIC_INPUT_UNAVAILABLE"), detail=str(exc))
    if component.get("component_status") == "FAIL":
        answer["status"] = "FAIL"
    return answer



def accept_a05(project: Path, context: Mapping, component: Mapping) -> dict:
    """Read connectivity findings and native OP values without claiming performance."""
    import analog_native_flow as native
    import analog_native_front as front
    from analog_native_sim import _included_paths
    import flow109_analog_model_check as model_checker
    import _prose_polarity
    project = Path(project).resolve()
    answer = {"schema": SCHEMA, "step_id": "A05", "status": "NOT_MEASURED",
              "metrics": {}, "scope": "connectivity and operating point only; performance NOT_MEASURED"}
    def bound(value, views):
        path = Path(value)
        path = path if path.is_absolute() else project / path
        relative = str(path.relative_to(project))
        path = _safe_project_file(project, relative)
        if not path.is_file() or views.get(str(path)) != _sha(path.read_bytes()):
            raise MetricRefusal("A05_NATIVE_FILE_UNBOUND", relative)
        return path
    def document(path):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise MetricRefusal("A05_DUPLICATE_JSON_KEY", key)
                result[key] = value
            return result
        return json.loads(path.read_bytes(), object_pairs_hook=unique)
    try:
        invocation = component.get("a05_invocation")
        if not invocation or native._a05_invocation(project) != invocation:
            raise MetricRefusal("A05_INVOCATION_INPUT_CHANGED_OR_ABSENT", "captured input/source/tool readset")
        blocks = [b.get("name") or b.get("block") for b in native._declared_blocks(project)]
        rows, readset = native._a18_current_rows(project, component["native_results"], "A05", blocks, invocation["image"])
        config = document(bound(project / "input/analog_flow.json", invocation["inputs"]))
        values, connectivity_errors = {}, 0
        for row in rows:
            name = row["block"]
            executions = row["executions"]
            checks = [ex for ex in executions if ex.get("program") == "analog_netlist_connectivity_check.py"]
            if len(checks) != 1:
                raise MetricRefusal("A05_CONNECTIVITY_EXECUTION_ABSENT", name)
            check = checks[0]
            if check.get("returncode") != 0 or check.get("missing_outputs"):
                raise MetricRefusal("A05_CONNECTIVITY_EXECUTION_INCOMPLETE", name)
            args = check["args"]
            if args[:3] != [str(project), "--block", name] or len(args) != 5 or args[3] != "--json":
                raise MetricRefusal("A05_CONNECTIVITY_INVOCATION_MISMATCH", name)
            report = bound(args[4], check["outputs"])
            audit = document(report)
            summary = audit.get("summary", {})
            if (audit.get("program") != "analog_netlist_connectivity_check"
                    or summary.get("skipped") is not False
                    or type(summary.get("files_with_subckt")) is not int or summary["files_with_subckt"] < 1
                    or not isinstance(audit.get("findings"), list)):
                raise MetricRefusal("A05_CONNECTIVITY_POPULATION_ABSENT", name)
            connectivity_errors += sum(item["severity"] == "ERROR" for item in audit["findings"])
            cfg = (config.get("blocks") or {}).get(name, {})
            bdir = project / "phase3/analog" / name
            net = bound(bdir / (name + ".sp"), invocation["inputs"])
            ops = [ex for ex in executions if ex.get("program") == "@ngspice"]
            if len(ops) != 1:
                raise MetricRefusal("A05_OP_EXECUTION_ABSENT", name)
            op = ops[0]
            argv = op["args"]
            if (len(argv) != 4 or argv[:2] != ["-b", "-o"]
                    or op.get("argv") != ["ngspice", *argv] or op.get("cwd") != str(bdir)
                    or op.get("returncode") != 0 or op.get("missing_outputs")):
                raise MetricRefusal("A05_OP_EXECUTION_INCOMPLETE", name)
            deck = bound(argv[3], op["outputs"])
            if cfg.get("op_deck"):
                if deck != bound(cfg["op_deck"], invocation["inputs"]):
                    raise MetricRefusal("A05_OP_DECK_MISMATCH", name)
            else:
                tb = bound(bdir / ("tb_" + name + ".sp"), invocation["inputs"])
                if deck.read_text() != front._op_deck(tb.read_text()):
                    raise MetricRefusal("A05_OP_DECK_MISMATCH", name)
            included = _included_paths(deck)
            if net.resolve() not in included:
                raise MetricRefusal("A05_OP_DUT_NOT_INCLUDED", name)
            for path in included - {deck}:
                bound(path, invocation["inputs"])
            log = bound(argv[2], op["outputs"])
            text = log.read_text()
            if model_checker._fatal_diagnostic(text, _prose_polarity):
                answer["metrics"]["operating_point_targets"] = {"status": "FAIL", "reason": "A05_NATIVE_OP_FAILED"}
                continue
            observed = front._op_values(text)
            if not observed:
                raise MetricRefusal("A05_OP_VALUES_ABSENT", name)
            values[name] = observed
        answer["metrics"]["netlist_connectivity_errors"] = {
            "status": "FAIL" if connectivity_errors else "PASS", "value": connectivity_errors, "unit": "count"}
        relative = "requirements/base_A4/operating_point_targets.json"
        document(bound(project / relative, invocation["inputs"]))
        authority, bounds = _approved_document(project, relative, authority="requirements_owner", schema=AUTHORITY_SCHEMA)
        bound(project / authority["source"]["path"], invocation["inputs"])
        limits, units = bounds.get("limits"), bounds.get("units")
        if not isinstance(limits, dict) or not isinstance(units, dict) or set(limits) != set(blocks) or set(units) != set(blocks):
            raise MetricRefusal("A05_REQUIRED_TARGET_POPULATION_ABSENT", relative)
        targets = []
        for name in blocks:
            if not isinstance(limits[name], dict) or not limits[name] or set(limits[name]) != set(units[name]):
                raise MetricRefusal("A05_REQUIRED_TARGET_POPULATION_INVALID", name)
            for node, limit in limits[name].items():
                if node not in values.get(name, {}):
                    targets.append({"block": name, "node": node, "status": "NOT_MEASURED", "reason": "A05_TARGET_NOT_OBSERVED"})
                    continue
                unit = "A" if node.endswith("#branch") else "V"
                identity = {"producer": invocation["sources"], "checker": "analog_native_front._op_values",
                            "tool_execution": invocation["tools"], "consumed_inputs": invocation["inputs"],
                            "requirements": authority, "configuration": {"image": invocation["image"]}}
                state, reason = evaluate_operator("within_declared_bounds",
                    {"status": "MEASURED", "value": values[name][node], "unit": unit, "identity": identity},
                    {"status": "APPROVED", "limits": limit, "unit": units[name][node]})
                targets.append({"block": name, "node": node, "value": values[name][node], "unit": unit,
                                "status": state, "reason": reason})
        previous = answer["metrics"].get("operating_point_targets", {})
        answer["metrics"]["operating_point_targets"] = {
            "status": "FAIL" if previous.get("status") == "FAIL" else native._aggregate(targets), "targets": targets}
        if native._a05_invocation(project) != invocation:
            raise MetricRefusal("A05_INPUT_CHANGED_DURING_ACCEPTANCE", "readset")
        readset.update(invocation["inputs"])
        answer.update(status=native._aggregate(list(answer["metrics"].values())),
                      input_views=readset, reason="A05_NATIVE_METRICS_EVALUATED")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer.update(status="FAIL" if any(row.get("status") == "FAIL" for row in answer["metrics"].values())
                      else "NOT_MEASURED", reason=getattr(exc, "code", "A05_METRIC_INPUT_UNAVAILABLE"), detail=str(exc))
    if component.get("component_status") == "FAIL":
        answer["status"] = "FAIL"
    return answer


def _a04_topology_facts(name, ir):
    """Observe explicit IR fields, never topology prose or device/net names.

    The loop_declaration schema-1 contract is documented in
    docs/flow109/A04-analog-topology.md. Absent or malformed fields produce
    no corresponding fact; they cannot satisfy a required constraint.
    """
    facts = []

    def add(kind, value):
        facts.append({'block': name, 'kind': kind, 'value': value})

    for kind, value in (("block_type", ir.get("block_type")), ("selected_topology", ir.get("topology"))):
        if not isinstance(value, str) or not value:
            raise MetricRefusal("A04_TOPOLOGY_FACT_ABSENT", name + ":" + kind)
        add(kind, value)
    for role in sorted({device["role"] for device in ir["devices"]}):
        add('device_role', role)
    for port in ir.get('ports', []):
        add('port', port)
    loop = ir.get('loop_declaration')
    if not isinstance(loop, dict) or type(loop.get('schema')) is not int or loop['schema'] != 1:
        return facts
    family = loop.get('family')
    if isinstance(family, str) and family.strip():
        add('loop_family', family)
    order = loop.get('order')
    if type(order) is int and order > 0:
        add('loop_order', str(order))
    else:
        order = None
    def path_valid(path):
        if (not isinstance(path, dict)
                or any(not isinstance(path.get(field), str) or not path[field].strip()
                       for field in ('kind', 'source', 'destination', 'capacitor'))
                or isinstance(path.get('gain'), bool)
                or not isinstance(path.get('gain'), (int, float))
                or not math.isfinite(path['gain'])):
            return False
        if path['kind'] == 'dac':
            stage, delay = path.get('destination_stage'), path.get('delay_clocks')
            return (type(stage) is int and stage > 0 and (order is None or stage <= order)
                    and type(delay) is int and delay >= 0)
        if path['kind'] == 'k0':
            return type(path.get('delay_clocks')) is int and path['delay_clocks'] == 1
        return True

    paths = loop.get('paths')
    if isinstance(paths, list) and all(path_valid(path) for path in paths):
        compensation = loop.get('k0_path')
        if (path_valid(compensation) and compensation['kind'] == 'k0'
                and compensation not in paths):
            paths = [*paths, compensation]
        for key, kind, kinds in [
                ('feedforward_paths', 'feedforward_path', {'feedforward', 'input_feedforward'}),
                ('feedback_paths', 'feedback_path', {'dac', 'k0', 'zero_feedback'})]:
            selected = [path for path in paths if path['kind'] in kinds]
            serialized = [json.dumps(path, sort_keys=True, separators=(',', ':')) for path in selected]
            if len(serialized) != len(set(serialized)):
                continue
            add(key, json.dumps(selected, sort_keys=True, separators=(',', ':')))
            for value in serialized:
                add(kind, value)
    stages = loop.get('dac_stages')
    if (order is not None and isinstance(stages, list)
            and all(type(stage) is int and 1 <= stage <= order for stage in stages)
            and len(stages) == len(set(stages))):
        add('dac_injection_stages', json.dumps(sorted(stages), separators=(',', ':')))
        for stage in sorted(stages):
            add('dac_injection_stage', str(stage))
    count = loop.get('quantizer_levels')
    if type(count) is int and count >= 2:
        add('quantizer_levels', str(count))
        if count & (count - 1) == 0:
            add('quantizer_bits', str(count.bit_length() - 1))
    delay = loop.get('D')
    if type(delay) is int and delay >= 0:
        add('timing_D', str(delay))
        add('feedback_delay', 'D=' + str(delay))
    return facts


def _a04_budget_bounds(limits, units, name, path=()):
    """Require identical nested populations for bound limits and their units."""
    if not isinstance(limits, dict) or not limits:
        raise MetricRefusal('A04_BUDGET_LIMIT_POPULATION_INVALID', name)
    if isinstance(units, str):
        if not units.strip() or not set(limits).issubset({'min', 'max'}):
            raise MetricRefusal('A04_BUDGET_LIMIT_POPULATION_INVALID', name)
        return {path: (limits, units)}
    if not isinstance(units, dict) or set(limits) != set(units):
        raise MetricRefusal('A04_BUDGET_LIMIT_POPULATION_INVALID', name)
    leaves = {}
    for key, child in limits.items():
        leaves.update(_a04_budget_bounds(child, units[key], name, (*path, key)))
    return leaves


def accept_a04(project: Path, context: Mapping, component: Mapping) -> dict:
    """Compare current topology facts and allocated design budgets with source authority."""
    import analog_native_flow as native
    import flow109_analog_a04 as topology
    project = Path(project).resolve()
    answer = {"schema": SCHEMA, "step_id": "A04", "status": "NOT_MEASURED", "metrics": {},
              "scope": "source-authorized topology and allocated budgets; native performance NOT_MEASURED"}
    if component.get("component_status") == "FAIL":
        return {**answer, "status": "FAIL", "reason": "A04_NATIVE_COMPONENT_FAILED"}
    try:
        invocation = component.get("a04_invocation")
        if not invocation or native._a04_invocation(project) != invocation:
            raise MetricRefusal("A04_INVOCATION_INPUT_CHANGED_OR_ABSENT", "readset")
        blocks = native._declared_blocks(project)
        names = [row.get("name") or row.get("block") for row in blocks]
        rows, readset = native._a18_current_rows(project, component["native_results"], "A04", names, invocation["image"])
        facts, irs = [], {}
        for row in rows:
            name = row["block"]
            path = project / "phase3/analog" / name / "topology.json"
            if row["output_views"].get(str(path)) != _sha(path.read_bytes()):
                raise MetricRefusal("A04_TOPOLOGY_OUTPUT_UNBOUND", name)
            ir = topology._read(path)
            if (ir.get("block") != name or not isinstance(ir.get("devices"), list) or not ir["devices"]
                    or (ir.get("_provenance") or {}).get("producer") != "analog_a2_topology_emit"):
                raise MetricRefusal("A04_TOPOLOGY_POPULATION_INVALID", name)
            irs[name] = ir
            facts.extend(_a04_topology_facts(name, ir))
        authority, _ = _approved_authority(project,
            "requirements/base_A3/topology_constraints.json#/required_items", ("block", "kind", "value"))
        required = authority["required_items"]
        if not required or len({_json_key(item) for item in required}) != len(required):
            raise MetricRefusal("A04_REQUIRED_CONSTRAINTS_INVALID", "required_items")
        missing = [item for item in required if item not in facts]
        answer["metrics"]["topology_constraints"] = {
            "status": "FAIL" if missing else "PASS", "value": facts, "missing": missing, "authority": authority,
            "observations": [{**item, 'status': 'NOT_OBSERVED' if item in missing else 'OBSERVED'}
                             for item in required]}
        manifest = topology._read(project / topology.INPUT)
        _path, _body, allocations = topology._approved_requirements(project, manifest)
        if set(allocations) != set(names):
            raise MetricRefusal("A04_ALLOCATION_BLOCK_POPULATION_MISMATCH", "blocks")
        bound_authority, bounds = _approved_document(project,
            "requirements/base_A3/allocated_gain_noise_power_budgets.json",
            authority="requirements_owner", schema=AUTHORITY_SCHEMA)
        limits, units = bounds.get("limits"), bounds.get("units")
        if (not isinstance(limits, dict) or not isinstance(units, dict)
                or set(limits) != set(names) or set(units) != set(names)):
            raise MetricRefusal("A04_BUDGET_LIMIT_POPULATION_ABSENT", "limits/units")
        measured = []
        for name in names:
            allocation, ir = allocations[name], irs[name]
            roles = sorted({device["role"] for device in ir["devices"]})
            if (allocation["selected_topology"] != ir["topology"]
                    or allocation["block_type"] != ir["block_type"]
                    or sorted(allocation["required_device_roles"]) != roles):
                answer["metrics"]["topology_constraints"]["status"] = "FAIL"
            allocations_by_path = dict(topology.budget_leaves(allocation['budgets'], name))
            bounds_by_path = _a04_budget_bounds(limits[name], units[name], name)
            if set(bounds_by_path) != set(allocations_by_path):
                raise MetricRefusal("A04_BUDGET_LIMIT_POPULATION_INVALID", name)
            for path, budget in allocations_by_path.items():
                bounds, unit = bounds_by_path[path]
                identity = {"producer": invocation["sources"], "checker": "flow109_analog_a04._approved_requirements",
                            "tool_execution": invocation["tools"], "consumed_inputs": invocation["inputs"],
                            "requirements": bound_authority, "configuration": {"image": invocation["image"]}}
                state, reason = evaluate_operator("within_declared_bounds", {
                    "status": "MEASURED", "value": budget["limit"], "unit": budget["unit"], "identity": identity}, {
                    "status": "APPROVED", "limits": bounds, "unit": unit})
                measured.append({"block": name, "budget": '/'.join(path), 'budget_path': list(path), "value": budget["limit"],
                                 "unit": budget["unit"], "status": state, "reason": reason})
                answer["metrics"]["allocated_gain_noise_power_budgets"] = {
                    "status": native._aggregate(measured), "allocations": measured}
        if native._a04_invocation(project) != invocation:
            raise MetricRefusal("A04_INPUT_CHANGED_DURING_ACCEPTANCE", "readset")
        readset.update(invocation["inputs"])
        answer.update(status=native._aggregate(list(answer["metrics"].values())),
                      input_views=readset, reason="A04_SOURCE_ALLOCATIONS_AND_NATIVE_TOPOLOGY_EVALUATED")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        if getattr(exc, 'code', None) == 'A04_BUDGET_UNBOUND':
            answer['metrics']['allocated_gain_noise_power_budgets'] = {
                'status': 'FAIL', 'reason': 'A04_BUDGET_UNBOUND'}
        answer.update(status="FAIL" if any(row.get("status") == "FAIL" for row in answer["metrics"].values())
                      else "NOT_MEASURED", reason=getattr(exc, "code", "A04_METRIC_INPUT_UNAVAILABLE"), detail=str(exc))
    return answer


def accept_a06(project: Path, context: Mapping, component: Mapping) -> dict:
    """Reopen native study values and compare bench calibration with an independent reference."""
    import analog_native_flow as native
    import analog_native_sim as sim
    import analog_bound_measurements as studies
    import analog_real_corner_sweep as sweep
    project = Path(project).resolve()
    answer = {"schema": SCHEMA, "step_id": "A06", "status": "NOT_MEASURED", "metrics": {},
              "scope": "measurement-bench calibration only; no on-chip trim or whole-flow claim"}
    if component.get("component_status") == "FAIL":
        return {**answer, "status": "FAIL", "reason": "A06_NATIVE_COMPONENT_FAILED"}
    def bound(value, views):
        path = Path(value)
        path = path if path.is_absolute() else project / path
        if path.is_relative_to(project):
            path = _safe_project_file(project, str(path.relative_to(project)))
        elif not any(tool["path"] == str(path.resolve()) and tool["sha256"] == views.get(str(path))
                     for tool in invocation["tools"].values()):
            raise MetricRefusal("A06_FOREIGN_INPUT", str(path))
        if not path.is_file() or views.get(str(path)) != _sha(path.read_bytes()):
            raise MetricRefusal("A06_INPUT_OR_NATIVE_OUTPUT_UNBOUND", str(path))
        return path
    try:
        invocation = component.get("a06_invocation")
        if not invocation or native._a06_invocation(project) != invocation:
            raise MetricRefusal("A06_INVOCATION_INPUT_CHANGED_OR_ABSENT", "readset")
        report = component["native_results"]
        attempt = Path(report["attempt"])
        stored = project / "reports/analog_native"
        if not attempt.is_relative_to(stored):
            raise MetricRefusal("A06_NATIVE_ATTEMPT_FOREIGN", str(attempt))
        stored_path = _safe_project_file(project, str((attempt / "result.json").relative_to(project)))
        if (json.loads(stored_path.read_bytes()) != report or report.get("image") != invocation["image"]
                or report.get("source_sha256") != _sha(Path(native.__file__).read_bytes())):
            raise MetricRefusal("A06_NATIVE_ATTEMPT_STALE", str(attempt))
        names = [b.get("name") or b.get("block") for b in native._declared_blocks(project)]
        rows = [row for row in report["steps"] if row.get("step") == "A06"]
        if not names or sorted(row["block"] for row in rows) != sorted(names):
            raise MetricRefusal("A06_BLOCK_POPULATION_MISMATCH", "blocks")
        values, value_units, result_paths = {}, {}, set()
        windows, mismatches, unit_complete = 0, 0, True
        for row in rows:
            name = row["block"]
            if (row.get("producer_context", {}).get("image") != invocation["image"]
                    or row["producer_context"].get("driver_sha256") != report["source_sha256"]):
                raise MetricRefusal("A06_PRODUCER_CONTEXT_STALE", name)
            for key in ("input_views", "output_views"):
                if not row.get(key):
                    raise MetricRefusal("A06_NATIVE_READSET_ABSENT", name)
                for path in row[key]:
                    bound(path, row[key])
            if any(row["input_views"].get(path) != digest for path, digest in native._input_views(project, name, "A06").items()):
                raise MetricRefusal("A06_NATIVE_INPUT_POPULATION_CHANGED", name)
            spec = json.loads(bound(project / "phase3/analog" / name / "spec.json", invocation["inputs"]).read_bytes())
            expected_units = {sweep.normalize_spec_label(item["name"]) or item["name"].casefold(): item.get("unit")
                              for item in spec.get("specs", []) if isinstance(item, dict) and item.get("name")}
            native_studies = (row.get("metrics") or {}).get("native_measurement_studies")
            if not isinstance(native_studies, list) or not native_studies:
                raise MetricRefusal("A06_CURRENT_NATIVE_CALIBRATION_STUDY_ABSENT", name)
            values[name], value_units[name] = {}, {}
            for study in native_studies:
                path = bound(study["result"], row["output_views"])
                result_paths.add(path)
                record = json.loads(path.read_bytes())
                current, reason = studies.validate_consumed_inputs(project, record.get("native_inputs"))
                if not current:
                    raise MetricRefusal("A06_NATIVE_STUDY_INPUTS_STALE", reason)
                for view in record["native_inputs"].values():
                    bound(view["path"], {view["path"]: view["sha256"]})
                binary = record["native_inputs"].get("native_binary")
                if (not isinstance(binary, dict) or str(Path(binary["path"]).resolve()) != invocation["tools"]["ngspice"]["path"]
                        or binary["sha256"] != invocation["tools"]["ngspice"]["sha256"]):
                    raise MetricRefusal("A06_NATIVE_TOOL_IDENTITY_ABSENT", name)
                bindings_path = bound(study["bindings_path"], invocation["inputs"])
                bindings = json.loads(bindings_path.read_bytes())
                actual_bindings = record["native_inputs"].get("bindings", {})
                if (record.get("bindings") != bindings or actual_bindings.get("path") != str(bindings_path)
                        or actual_bindings.get("sha256") != _sha(bindings_path.read_bytes())
                        or record["native_inputs"].get("netlist", {}).get("path")
                        != str(project / "phase3/analog" / name / (name + ".sp"))):
                    raise MetricRefusal("A06_NATIVE_STUDY_BINDINGS_STALE", name)
                executions = record.get("executions")
                if not executions:
                    raise MetricRefusal("A06_NATIVE_STUDY_EXECUTION_ABSENT", name)
                transcript = []
                for execution in executions:
                    log = bound(execution["log"], {execution["log"]: execution["log_sha256"]})
                    transcript.append(log.read_text())
                    expected_argv = [binary["path"], "-b", record["native_inputs"]["deck"]["path"]]
                    if (execution.get("returncode") != 0 or execution.get("missing_outputs")
                            or execution.get("argv") != expected_argv):
                        raise MetricRefusal("A06_NATIVE_STUDY_EXECUTION_INCOMPLETE", name)
                text = "\n".join(transcript)
                if any(sweep._scan_analysis_failures(text)):
                    raise MetricRefusal("A06_NATIVE_STUDY_DIAGNOSTIC_FAILED", name)
                parsed = {key.casefold(): value for key, value in sweep.native_meas_rows(text).items()}
                for match in sweep._MEAS_LINE_RE.finditer(text):
                    for key, value in sweep._KV_RE.findall(match.group(1)):
                        parsed.setdefault(key.casefold(), float(value))
                for label, value in record.get("measurements", {}).items():
                    _finite_number(value)
                    if parsed.get(label) != value or label in values[name]:
                        raise MetricRefusal("A06_NATIVE_VALUE_UNBOUND_OR_DUPLICATE", label)
                    binding = bindings["measurements"][label]
                    key = sweep.normalize_spec_label(binding.get("spec_key", label)) or binding.get("spec_key", label).casefold()
                    actual_unit, expected_unit = binding.get("unit"), expected_units.get(key)
                    if not actual_unit or not expected_unit:
                        unit_complete = False
                    elif actual_unit.replace("µ", "u").replace("μ", "u") != expected_unit.replace("µ", "u").replace("μ", "u"):
                        mismatches += 1
                    values[name][label], value_units[name][label] = value, actual_unit
                deck = Path(record["native_inputs"]["deck"]["path"])
                template = Path(record["native_inputs"]["testbench"]["path"])
                expected_deck = studies.emit_deck(studies.contextual_template(template.read_text(), template.parent), bindings,
                                                 deck.parent / "curve.dat")
                if deck.read_text() != expected_deck:
                    raise MetricRefusal("A06_NATIVE_DECK_DERIVATION_MISMATCH", name)
                ready, reason, _ = sim._validate_deck(Path(record["native_inputs"]["netlist"]["path"]), deck,
                    {"required_measurements": list(bindings["measurements"])})
                if ready != "PASS":
                    raise MetricRefusal("A06_NATIVE_MEASUREMENT_DECK_INVALID", reason)
                span = sweep.measurement_span(sim._deck_text(deck))
                stop = span.get("declared_stop_s")
                windows += sum(stop is not None and item["end_s"] > stop for item in span["windowed"])
            answer["metrics"]["measurement_window_errors"] = {
                "status": "FAIL" if windows else "PASS", "value": windows, "unit": "count"}
            answer["metrics"]["unit_mismatches"] = {"status": "FAIL" if mismatches else "PASS" if unit_complete else "NOT_MEASURED",
                                                      "value": mismatches if mismatches or unit_complete else None, "unit": "count"}
        relative = "requirements/base_A5/known_stimulus_calibration.json"
        bound(project / relative, invocation["inputs"])
        authority, requirement = _approved_document(project, relative, authority="requirements_owner", schema=AUTHORITY_SCHEMA)
        reference = requirement.get("reference")
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise MetricRefusal("A06_INDEPENDENT_REFERENCE_ABSENT", relative)
        known_path = bound(project / reference["path"], invocation["inputs"])
        if _sha(known_path.read_bytes()) != reference["sha256"] or known_path in result_paths:
            raise MetricRefusal("A06_INDEPENDENT_REFERENCE_UNBOUND", reference["path"])
        known = json.loads(known_path.read_bytes())
        if set(known.get("measurements", {})) != set(names) or set(known.get("units", {})) != set(names):
            raise MetricRefusal("A06_REFERENCE_BLOCK_POPULATION_MISMATCH", "reference")
        limits = requirement.get("limits", {}).get("ideal_model_sqnr_error_db")
        unit = requirement.get("units", {}).get("ideal_model_sqnr_error_db")
        if (not isinstance(limits, dict) or limits.get("max") != 1.0
                or set(limits) - {"min", "max"} or limits.get("min", 0.0) != 0.0 or unit != "dB"):
            raise MetricRefusal("A06_APPROVED_CALIBRATION_DECISION_MISMATCH", relative)
        calibrated = []
        for name in names:
            expected = known["measurements"][name]
            if not isinstance(expected, dict) or not expected or set(expected) != set(known["units"][name]):
                raise MetricRefusal("A06_REFERENCE_MEASUREMENT_POPULATION_INVALID", name)
            for label, independent in expected.items():
                _finite_number(independent)
                if label not in values[name] or value_units[name][label] != "dB" or known["units"][name][label] != "dB":
                    raise MetricRefusal("A06_CALIBRATION_VALUE_OR_UNIT_ABSENT", name + ":" + label)
                delta = values[name][label] - independent
                calibrated.append({"block": name, "measurement": label, "measured": values[name][label],
                    "independent_known": independent, "signed_delta_db": delta, "absolute_error_db": abs(delta),
                    "status": "PASS" if abs(delta) <= 1.0 else "FAIL"})
                answer["metrics"]["known_stimulus_calibration"] = {
                    "status": native._aggregate(calibrated), "comparisons": calibrated,
                    "reference": reference, "authority": authority}
        if native._a06_invocation(project) != invocation:
            raise MetricRefusal("A06_INPUT_CHANGED_DURING_ACCEPTANCE", "readset")
        answer.update(status=native._aggregate(list(answer["metrics"].values())),
                      input_views=invocation["inputs"], reason="A06_CURRENT_BENCH_CALIBRATION_METRICS_EVALUATED")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer.update(status="FAIL" if any(row.get("status") == "FAIL" for row in answer["metrics"].values())
                      else "NOT_MEASURED", reason=getattr(exc, "code", "A06_METRIC_INPUT_UNAVAILABLE"), detail=str(exc))
    return answer


def _a0708_file(project, path, digest, invocation):
    """Reopen a selected-row input/output; foreign files require invocation binding."""
    path = Path(path)
    path = (path if path.is_absolute() else project / path).resolve()
    if path.is_relative_to(project):
        path = _safe_project_file(project, str(path.relative_to(project)))
    elif invocation['inputs'].get(str(path)) != digest and not any(
            tool['path'] == str(path) and tool['sha256'] == digest
            for tool in invocation['tools'].values()):
        raise MetricRefusal('A0708_FOREIGN_NATIVE_INPUT', str(path))
    if not path.is_file() or _sha(path.read_bytes()) != digest:
        raise MetricRefusal('A0708_NATIVE_INPUT_CHANGED', str(path))
    return path


def _a0708_rows(project, context, component, step):
    import analog_native_flow as native
    invocation = component.get(step.lower() + '_invocation')
    current = getattr(native, '_' + step.lower() + '_invocation')(project)
    if not invocation or current != invocation:
        raise MetricRefusal(step + '_INVOCATION_CHANGED_OR_ABSENT', 'inputs/models/bounds/method/tool/source')
    report = component['native_results']
    attempt = Path(report['attempt']).resolve()
    if not attempt.is_relative_to(project / 'reports/analog_native'):
        raise MetricRefusal(step + '_NATIVE_ATTEMPT_FOREIGN', str(attempt))
    stored = _safe_project_file(project, str((attempt / 'result.json').relative_to(project)))
    if (json.loads(stored.read_bytes()) != report or report.get('image') != invocation['image']
            or report.get('source_sha256') != _sha(Path(native.__file__).read_bytes())):
        raise MetricRefusal(step + '_NATIVE_REPORT_STALE', str(attempt))
    names = [b.get('name') or b.get('block') for b in native._declared_blocks(project)]
    rows = [row for row in report['steps'] if row.get('step') == step]
    if not names or sorted(row['block'] for row in rows) != sorted(names):
        raise MetricRefusal(step + '_BLOCK_POPULATION_MISMATCH', 'blocks')
    for row in rows:
        owner = row.get('producer_context', {})
        if owner.get('image') != invocation['image'] or owner.get('driver_sha256') != report['source_sha256']:
            raise MetricRefusal(step + '_PRODUCER_CONTEXT_STALE', row['block'])
        for key in ['input_views', 'output_views']:
            if key == 'input_views' and not row.get(key):
                raise MetricRefusal(step + '_READSET_ABSENT', row['block'])
            for path, digest in row.get(key, {}).items():
                _a0708_file(project, path, digest, invocation)
        if any(row['input_views'].get(path) != digest for path, digest in
               native._input_views(project, row['block'], step).items()):
            raise MetricRefusal(step + '_INPUT_POPULATION_CHANGED', row['block'])
    return invocation, rows


def _a0708_transcript(project, executions, deck, invocation, *, temperature_c=None):
    import analog_native_sim as sim
    import analog_real_corner_sweep as sweep
    if not executions:
        raise MetricRefusal('A0708_NATIVE_EXECUTION_ABSENT', str(deck))
    texts = []
    for execution in executions:
        log = _a0708_file(project, execution['log'], execution['log_sha256'], invocation)
        argv = execution.get('argv')
        if (not isinstance(argv, list) or len(argv) not in (3, 5) or argv[1:3] != ['-b', str(deck)]
                or argv[0] not in ('ngspice', invocation['tools']['ngspice']['path'])
                or execution.get('returncode') != 0 or execution.get('missing_outputs')):
            raise MetricRefusal('A0708_NATIVE_EXECUTION_INCOMPLETE', str(deck))
        texts.append(log.read_text())
        if len(argv) == 5:
            # The nominal producer's live native stream is separate from the
            # executor transcript. Bind both to their recorded output bytes.
            native_log = execution.get('stdout_path')
            digest = (execution.get('outputs') or {}).get(native_log)
            if argv[3] != '-o' or argv[4] != native_log or not digest:
                raise MetricRefusal('A0708_NATIVE_EXECUTION_INCOMPLETE', str(deck))
            texts.append(_a0708_file(project, native_log, digest, invocation).read_text())
    text = '\n'.join(texts)
    if any(sweep._scan_analysis_failures(text)):
        raise MetricRefusal('A0708_NATIVE_ANALYSIS_FAILED', str(deck))
    if temperature_c is not None:
        import analog_declared_pvt as declared
        if not declared.temperature_matches(text, temperature_c):
            raise MetricRefusal('A08_DECLARED_NATIVE_TEMPERATURE_MISMATCH', str(deck))
    parsed = {key.casefold(): value for key, value in sweep.native_meas_rows(text).items()}
    for match in sweep._MEAS_LINE_RE.finditer(text):
        for key, value in sweep._KV_RE.findall(match.group(1)):
            parsed.setdefault(key.casefold(), float(value))
    return parsed


def _a07_declared_deck(project, row, name, config, invocation):
    """The deck a declared testbench rendered for this row, proven by re-rendering it."""
    import analog_native_sim as sim
    if sim._testbench_inputs_path(project, name, config) is None:
        return None
    view = (row.get('native_inputs') or {}).get('testbench')
    if not isinstance(view, dict):
        raise MetricRefusal('A07_DECLARED_TESTBENCH_DECK_ABSENT', name)
    deck = _a0708_file(project, view['path'], view['sha256'], invocation)
    if deck.read_text() != sim._declared_testbench(project, name, config, deck.parent)[0]:
        raise MetricRefusal('A07_DECLARED_TESTBENCH_DECK_CHANGED', name)
    return deck


def _a0708_nominal_observation(project, row, invocation):
    """Read the existing direct/study producers; never launch or invent a result."""
    import analog_native_sim as sim
    import analog_native_flow as native
    import analog_bound_measurements as studies
    import analog_real_corner_sweep as sweep
    name = row['block']
    config = sim._config({'config': native._read(project / 'input/analog_flow.json', {})}, {'name': name}, 'A07')
    if config.get('nominal_testbench'):
        config = {**config, 'testbench': config['nominal_testbench']}
    netlist, template, spec_path = sim._inputs(project, name, config)
    spec = json.loads(spec_path.read_bytes())
    units = {sweep.normalize_spec_label(s['name']) or s['name'].casefold(): s.get('unit')
             for s in spec.get('specs', []) if isinstance(s, dict) and s.get('name')}
    records = (row.get('metrics') or {}).get('native_measurement_studies')
    observations = {}
    if records:
        for study in records:
            if not study.get('bindings_path'):
                observed = _a07_incremental_observation(project, name, config, invocation)
                if set(observed) & set(observations):
                    raise MetricRefusal('A07_DUPLICATE_NATIVE_MEASUREMENT', name)
                observations.update(observed)
                continue
            result_path = Path(study['result'])
            _a0708_file(project, result_path, row['output_views'][str(result_path)], invocation)
            record = json.loads(result_path.read_bytes())
            current, reason = studies.validate_consumed_inputs(project, record.get('native_inputs'))
            if not current:
                raise MetricRefusal('A07_NATIVE_STUDY_CLOSURE_STALE', reason)
            for view in record['native_inputs'].values():
                _a0708_file(project, view['path'], view['sha256'], invocation)
            binding_path = Path(study['bindings_path'])
            _a0708_file(project, binding_path, invocation['inputs'][str(binding_path)], invocation)
            bindings = json.loads(binding_path.read_bytes())
            binary = record['native_inputs'].get('native_binary')
            if (record.get('bindings') != bindings or binary != invocation['tools']['ngspice']
                    or record['native_inputs']['netlist']['path'] != str(netlist.resolve())):
                raise MetricRefusal('A07_NATIVE_STUDY_METHOD_OR_TOOL_CHANGED', name)
            deck = Path(record['native_inputs']['deck']['path'])
            expected = studies.emit_deck(studies.contextual_template(template.read_text(), template.parent),
                                        bindings, deck.parent / 'curve.dat')
            if deck.read_text() != expected:
                # Each study owns its actual template, which may differ from the nominal default.
                study_template = Path(record['native_inputs']['testbench']['path'])
                expected = studies.emit_deck(studies.contextual_template(study_template.read_text(), study_template.parent),
                                            bindings, deck.parent / 'curve.dat')
                if deck.read_text() != expected:
                    raise MetricRefusal('A07_NATIVE_STUDY_DECK_CHANGED', name)
            parsed = _a0708_transcript(project, record['executions'], deck, invocation)
            for label, value in record.get('measurements', {}).items():
                if parsed.get(label) != value:
                    raise MetricRefusal('A07_NATIVE_VALUE_UNBOUND', label)
                definition = bindings['measurements'][label]
                key = sweep.normalize_spec_label(definition.get('spec_key', label)) or definition.get('spec_key', label).casefold()
                if key in observations:
                    raise MetricRefusal('A07_DUPLICATE_NATIVE_MEASUREMENT', key)
                observations[key] = {'value': _finite_number(value), 'unit': definition.get('unit'),
                                     'method': definition, 'analysis': bindings['analysis']}
    else:
        template = _a07_declared_deck(project, row, name, config, invocation) or template
        ready, reason, required = sim._validate_deck(netlist, template, config)
        if ready != 'PASS':
            raise MetricRefusal('A07_NATIVE_DECK_INVALID', reason)
        for view in studies.consumed_input_views(project, template).values():
            if row['input_views'].get(view['path']) != view['sha256']:
                raise MetricRefusal('A07_NATIVE_MODEL_READSET_INCOMPLETE', view['path'])
        parsed = _a0708_transcript(project, row['executions'], template, invocation)
        for label in required:
            key = sweep.normalize_spec_label(label) or label.casefold()
            if key in ('enob', 'sinad', 'sndr', 'snr'):
                raise MetricRefusal('A07_COMPLETE_SAMPLED_DYNAMIC_METHOD_REQUIRED', key)
            if label in parsed:
                if (row.get('metrics') or {}).get(label) != parsed[label]:
                    raise MetricRefusal('A07_NATIVE_VALUE_UNBOUND', label)
                observations[key] = {'value': _finite_number(parsed[label]), 'unit': units.get(key),
                                     'method': {'native_measurement': label, 'deck': str(template)}}
    # Use the existing source-analysis selector: supply/load conditions are
    # not silently added to the required performance measurement population.
    required = sim._source_measurement_coverage(spec_path, [])['required']
    if not required:
        required = sorted(set(observations) & set(units))
    return observations, {key: units.get(key) for key in required}


def _a07_incremental_observation(project, name, config, invocation):
    """Reopen the normal complete-series score through its existing CPU reader."""
    import analog_incremental_capture as capture
    import analog_bound_measurements as bound
    entries = config.get('measurement_studies')
    if entries is None:
        entries = json.loads((project / 'phase3/analog' / name / 'measurement_studies.json').read_bytes())
        entries = entries.get('studies', []) if isinstance(entries, dict) else entries
    selected = [v for v in entries if v.get('kind') == 'incremental_capture']
    if len(selected) != 1:
        raise MetricRefusal('A07_INCREMENTAL_METHOD_POPULATION_INVALID', name)
    entry = selected[0]
    score = Path(entry['result'])
    score = score if score.is_absolute() else project / score
    settings = Path(entry['settings'])
    settings = settings if settings.is_absolute() else project / settings
    for path in [score, settings]:
        _a0708_file(project, path, invocation['inputs'][str(path)], invocation)
    common = json.loads(settings.read_bytes())
    common.setdefault('threads', 1)
    common.setdefault('openmp_wait_policy', 'PASSIVE')
    saved = json.loads(score.read_bytes())
    points = saved.get('points', [])
    if not points or len(points) != common['series_length']:
        raise MetricRefusal('A07_COMPLETE_INCREMENTAL_POINT_POPULATION_REQUIRED', name)
    phases = set()
    for reference in points:
        path = _a0708_file(project, reference['path'], reference['sha256'], invocation)
        point = json.loads(path.read_bytes())
        phase = point['settings']['phase_index']
        if point['settings'] != capture.phase_settings(common, phase) or phase in phases or point.get('image') != invocation['image']:
            raise MetricRefusal('A07_INCREMENTAL_POINT_METHOD_CHANGED', str(phase))
        phases.add(phase)
        views = point['native_inputs']
        current, why = bound.validate_consumed_inputs(project, views)
        if not current or not capture.declared_dut_consumed(views):
            raise MetricRefusal('A07_INCREMENTAL_POINT_MODEL_UNBOUND', why)
        for view in views.values():
            _a0708_file(project, view['path'], view['sha256'], invocation)
        _a0708_transcript(project, point['executions'], Path(views['deck']['path']), invocation)
    if phases != set(range(common['series_length'])):
        raise MetricRefusal('A07_INCREMENTAL_PHASE_POPULATION_INCOMPLETE', name)
    replay = capture.replay_score(score)
    if replay.get('status') not in ('PASS', 'FAIL') or not replay.get('measurements'):
        raise MetricRefusal('A07_INCREMENTAL_SCORE_NOT_MEASURED', replay.get('detail', name))
    return {label: {'value': _finite_number(value), 'unit': 'bit' if label == 'enob' else 'dB',
                    'method': {'settings': str(settings), 'score': str(score), 'series_length': common['series_length']}}
            for label, value in replay['measurements'].items()}


def _a0708_compare(observations, limits, units, *, reference=None):
    """Grade every point, retaining a measured violation beside missing points."""
    comparisons = []
    for block, expected in limits.items():
        if not isinstance(expected, dict) or not expected:
            comparisons.append({'block': block, 'status': 'NOT_MEASURED', 'reason': 'A0708_BOUND_POPULATION_EMPTY'})
            continue
        for label, edges in expected.items():
            item = {'block': block, 'measurement': label}
            try:
                observation = observations.get(block, {}).get(label)
                if not observation:
                    raise MetricRefusal('A0708_REQUIRED_NATIVE_POINT_ABSENT', block + ':' + label)
                unit = units.get(block, {}).get(label)
                if not unit or not observation.get('unit'):
                    raise MetricRefusal('A0708_NATIVE_UNIT_ABSENT', label)
                compatible = observation['unit'].replace('µ', 'u').replace('μ', 'u') == unit.replace('µ', 'u').replace('μ', 'u')
                if not isinstance(edges, dict) or not edges or set(edges) - {'min', 'max'}:
                    raise MetricRefusal('A0708_BOUND_INVALID', label)
                for limit in edges.values():
                    _finite_number(limit)
                value = _finite_number(observation['value'])
                if reference is not None:
                    known = _finite_number(reference['measurements'][block][label])
                    if reference['units'][block][label] != unit:
                        raise MetricRefusal('A0708_REFERENCE_UNIT_MISMATCH', label)
                    compared = abs(value - known)
                else:
                    known, compared = None, value
                failed = not compatible or any((edge == 'min' and compared < bound) or
                    (edge == 'max' and compared > bound) for edge, bound in edges.items())
                item.update(value=value, unit=observation['unit'], reference=known, compared_value=compared,
                            bounds=edges, status='FAIL' if failed else 'PASS')
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                item.update(status='NOT_MEASURED', reason=getattr(exc, 'code', 'A0708_POINT_INPUT_ABSENT'), detail=str(exc))
            comparisons.append(item)
    return comparisons


def accept_a07(project: Path, context: Mapping, component: Mapping) -> dict:
    """BLOCKING nominal binding; current complete metrics still require row qualification."""
    import analog_native_flow as native
    project = Path(project).resolve()
    answer = {'schema': SCHEMA, 'step_id': 'A07', 'status': 'NOT_MEASURED', 'metrics': {},
              'scope': 'native nominal metrics only; no qualification or whole-IC credit'}
    failed = component.get('component_status') == 'FAIL'
    try:
        invocation, rows = _a0708_rows(project, context, component, 'A07')
        observations, declared_units = {}, {}
        for row in rows:
            observations[row['block']], declared_units[row['block']] = _a0708_nominal_observation(project, row, invocation)
        answer['native_observation'] = observations
        for metric in ['nominal_performance', 'early_model_correlation']:
            try:
                relative = 'requirements/base_A6/' + metric + '.json'
                authority, requirement = _approved_document(project, relative, authority='requirements_owner', schema=AUTHORITY_SCHEMA)
                limits, units = requirement['limits'], requirement['units']
                reference = None
                if metric == 'early_model_correlation':
                    ref = requirement['reference']
                    path = _a0708_file(project, ref['path'], ref['sha256'], invocation)
                    if invocation['inputs'].get(str(path)) != ref['sha256']:
                        raise MetricRefusal('A07_INDEPENDENT_REFERENCE_UNBOUND', str(path))
                    reference = json.loads(path.read_bytes())
                comparisons = _a0708_compare(observations, limits, units, reference=reference)
                # Every declared source measurement is required; no narrower authority population earns PASS.
                required = {(block, label) for block, values in declared_units.items() for label in values}
                actual = {(row['block'], row['measurement']) for row in comparisons}
                status = 'FAIL' if any(row['status'] == 'FAIL' for row in comparisons) else 'PASS' if actual == required and actual and set(limits) == set(units) == set(observations) and all(row['status'] == 'PASS' for row in comparisons) else 'NOT_MEASURED'
                answer['metrics'][metric] = {'status': status, 'comparisons': comparisons, 'authority': authority}
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                answer['metrics'][metric] = {'status': 'NOT_MEASURED', 'reason': getattr(exc, 'code', 'A07_AUTHORITY_OR_POINT_ABSENT'), 'detail': str(exc)}
        if native._a07_invocation(project) != invocation:
            raise MetricRefusal('A07_INPUT_CHANGED_DURING_ACCEPTANCE', 'readset')
        answer.update(status='FAIL' if failed or any(v['status'] == 'FAIL' for v in answer['metrics'].values())
                      else native._aggregate(list(answer['metrics'].values())), input_views=invocation['inputs'],
                      reason='A07_CURRENT_NATIVE_NOMINAL_METRICS_EVALUATED')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer.update(status='FAIL' if failed or any(v['status'] == 'FAIL' for v in answer['metrics'].values())
                      else 'NOT_MEASURED', reason=getattr(exc, 'code', 'A07_NATIVE_METRIC_INPUT_ABSENT'), detail=str(exc))
    return answer


def _a08_selected(project, name):
    """Use the A08 sidecar/config precedence of the existing native dispatcher."""
    import analog_native_flow as native
    import analog_native_sim as sim
    try:
        return sim._selected_config(project, {'config': native._read(project / 'input/analog_flow.json', {})},
                                    {'name': name}, 'A08')
    except (OSError, ValueError) as exc:
        raise MetricRefusal('A08_PVT_INPUTS_INVALID', str(exc)) from exc


def _a08_declared_observation(project, row, selected, declaration, invocation):
    """Read/re-render every corner without writes; trustworthy scalar FAIL survives gaps."""
    import analog_declared_pvt as declared
    import analog_bound_measurements as bound
    import analog_native_flow as native
    import analog_native_sim as sim
    import analog_real_corner_sweep as sweep
    name = row['block']
    metrics = row.get('metrics') or {}
    spec_path = sim._inputs(project, name, selected)[2]
    required = sim._source_measurement_coverage(spec_path, [])['required']
    if set(required) & {'enob', 'snr', 'sinad', 'sndr'}:
        raise MetricRefusal('A08_COMPLETE_SAMPLED_DYNAMIC_METHOD_REQUIRED', name)
    limits = sim._bounds(spec_path, selected, required)
    spec = json.loads(spec_path.read_bytes())
    units = {sweep.normalize_spec_label(v['name']) or v['name'].casefold(): v.get('unit', v.get('units'))
             for v in spec.get('specs', []) if isinstance(v, dict) and v.get('name')}
    answer = {'status': 'NOT_MEASURED', 'corners': [], 'gaps': [], 'required': required,
              'units': {key: units.get(key) for key in required}}
    recorded_corners = metrics.get('corners') or []
    expected = declared.coordinates(declaration)
    wanted = {declared.corner_label(section, temperature) for section, temperature in expected}
    corners = {}
    for recorded in recorded_corners:
        if (not isinstance(recorded, dict) or not isinstance(recorded.get('name'), str)
                or recorded['name'] in corners):
            answer['gaps'].append('A08_DECLARED_CORNER_POPULATION_INCOMPLETE')
            continue
        corners[recorded.get('name')] = recorded
    if (metrics.get('stage') != 'PRE' or metrics.get('kind') != 'declared_testbench'
            or len(recorded_corners) != len(expected) or set(corners) != wanted
            or metrics.get('total_corners') != len(expected) or metrics.get('corners_executed') != len(expected)
            or metrics.get('required') != required):
        answer['gaps'].append('A08_DECLARED_CORNER_POPULATION_INCOMPLETE')
    for section, temperature in expected:
        label = declared.corner_label(section, temperature)
        recorded = corners.get(label)
        corner = {'name': label, 'status': 'NOT_MEASURED', 'observations': {}, 'complete': False}
        try:
            if (not recorded or recorded.get('process') != section
                    or isinstance(recorded.get('temperature_c'), bool) or recorded.get('temperature_c') != temperature):
                raise MetricRefusal('A08_DECLARED_CORNER_ABSENT_OR_MISMATCHED', label)
            deck = _a0708_file(project, recorded['deck'], row['output_views'][recorded['deck']], invocation)
            dut = _a0708_file(project, recorded['netlist'], row['output_views'][recorded['netlist']], invocation)
            if deck.name != 'tb_' + name + '.sp' or dut != deck.parent / (name + '.sp'):
                raise MetricRefusal('A08_DECLARED_CORNER_DECK_CHANGED', label)
            deck_text, dut_text, source_views = declared.render_corner(project, name, selected, deck.parent,
                list(declaration['process_sections']), section, temperature)
            if dut_text != dut.read_text() or deck_text != deck.read_text():
                raise MetricRefusal('A08_DECLARED_CORNER_DECK_CHANGED', label)
            # Source authorization precedes interpreting values. Rebuild the actual
            # consumed closure instead of trusting the row's self-reported subset.
            for view in source_views.values():
                if invocation.get('inputs', {}).get(view['path']) != view['sha256']:
                    raise MetricRefusal('A08_DECLARED_SOURCE_READSET_INCOMPLETE', view['path'])
                _a0708_file(project, view['path'], view['sha256'], invocation)
            expected_views = {**source_views, **bound.consumed_input_views(project, deck),
                              'deck': {'path': str(deck), 'sha256': bound.sha(deck)}}
            recorded_views = {key[len(label) + 1:]: value for key, value in (row.get('native_inputs') or {}).items()
                              if key.startswith(label + ':')}
            if recorded_views != expected_views:
                raise MetricRefusal('A08_DECLARED_MODEL_READSET_INCOMPLETE', label)
            for view in expected_views.values():
                if row['input_views'].get(view['path']) != view['sha256']:
                    raise MetricRefusal('A08_DECLARED_MODEL_READSET_INCOMPLETE', view['path'])
                _a0708_file(project, view['path'], view['sha256'], invocation)
            execution = recorded['execution']
            if Path(execution.get('cwd') or '').resolve() != deck.parent:
                raise MetricRefusal('A08_DECLARED_EXECUTION_CWD_MISMATCH', label)
            _environment, startup = native._local_ngspice_startup(project, None, invocation['image'])
            if execution.get('native_init') != startup:
                raise MetricRefusal('A08_DECLARED_NATIVE_STARTUP_MISMATCH', label)
            if startup:
                if invocation['inputs'].get(startup['path']) != startup['sha256']:
                    raise MetricRefusal('A08_DECLARED_NATIVE_STARTUP_UNBOUND', label)
                _a0708_file(project, startup['path'], startup['sha256'], invocation)
            parsed = _a0708_transcript(project, [execution], deck, invocation, temperature_c=temperature)
            for key in required:
                if recorded.get('measurements', {}).get(key) != parsed.get(key):
                    answer['gaps'].append('A08_DECLARED_VALUE_UNBOUND: ' + label + ':' + key)
                    continue
                if key in parsed:
                    try:
                        corner['observations'][key] = {'value': _finite_number(parsed[key]), 'unit': units.get(key)}
                    except (TypeError, ValueError) as exc:
                        answer['gaps'].append(str(exc))
            missing, malformed, breach = declared.measurement_state(required, limits,
                {key: value['value'] for key, value in corner['observations'].items()})
            corner['status'] = 'FAIL' if breach else 'NOT_MEASURED' if missing or malformed or not required else 'PASS'
            corner['complete'] = bool(required) and not missing and not malformed
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            if getattr(exc, 'code', '') == 'A0708_NATIVE_ANALYSIS_FAILED':
                corner['status'] = 'FAIL'
            corner['detail'] = str(exc)
            answer['gaps'].append(str(exc))
        answer['corners'].append(corner)
    if any(not corner['complete'] for corner in answer['corners']):
        answer['gaps'].append('A08_COMPLETE_CURRENT_POINT_AND_CORNER_POPULATION_REQUIRED')
    answer['status'] = ('FAIL' if any(corner['status'] == 'FAIL' for corner in answer['corners']) else
                        'NOT_MEASURED' if answer['gaps'] else 'PASS')
    return answer


def _a08_incremental_observation(project, row, invocation):
    """Replay the selected producer; retained native FAIL precedes later gaps.

    This is a reader of the existing manifest/collector, never a simulator or
    an enrollment path for historical results without pre-execution identity.
    """
    import analog_incremental_pvt as pvt
    import analog_incremental_capture as capture
    import analog_native_sim as sim
    import analog_real_corner_sweep as sweep
    if not callable(getattr(capture, 'validate_execution_identity', None)):
        raise MetricRefusal('A08_PREEXEC_PRODUCER_DEPENDENCY_ABSENT', 'analog_incremental_capture.validate_execution_identity')
    name = row['block']
    selected = _a08_selected(project, name)
    declaration = selected.get('pvt') or {}
    if declaration.get('kind') == 'declared_testbench':
        return _a08_declared_observation(project, row, selected, declaration, invocation)
    if declaration.get('kind') != 'incremental_capture':
        raise MetricRefusal('A08_PER_CORNER_EXECUTABLE_ARGV_AND_PREEXEC_MODEL_READSET_ABSENT', name)
    reference = declaration['manifest']
    path, manifest = sim._incremental_source_manifest(project, name, selected,
        {'image': invocation['image']}, reference, 'incremental_capture_pvt')
    if invocation['inputs'].get(str(path)) != reference['sha256']:
        raise MetricRefusal('A08_SELECTED_MANIFEST_UNBOUND', str(path))
    contexts = pvt._validate_manifest(manifest)
    replayed = pvt.collect(manifest)  # existing non-launching native consumer
    values = replayed.get('metrics') or {}
    answer = {'status': replayed['status'], 'corners': [], 'gaps': [], 'required': [],
              'manifest': {'path': str(path), 'sha256': reference['sha256']}}
    try:
        candidates = [Path(p) for p in row.get('outputs', []) if Path(p).name == 'pvt-studies.json']
        if len(candidates) != 1:
            raise MetricRefusal('A08_SELECTED_RESULT_POPULATION_INVALID', name)
        result_path = candidates[0]
        _a0708_file(project, result_path, row['output_views'][str(result_path)], invocation)
        stored = json.loads(result_path.read_bytes())
        recorded = {k: v for k, v in stored.get('metrics', {}).items() if k != 'execution_budget'}
        if (stored.get('status') != replayed['status'] or recorded != values
                or row.get('metrics') != stored.get('metrics')
                or stored.get('native_inputs', {}).get('pvt_manifest') != answer['manifest']):
            raise MetricRefusal('A08_SELECTED_RESULT_DIFFERS_FROM_REPLAY', name)
        for role, view in replayed.get('native_inputs', {}).items():
            if stored.get('native_inputs', {}).get(role) != view:
                raise MetricRefusal('A08_RESULT_READSET_INCOMPLETE', role)
            _a0708_file(project, view['path'], view['sha256'], invocation)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer['gaps'].append(str(exc))
    spec_path = Path(manifest['native_inputs']['spec']['path'])
    required = sim._source_measurement_coverage(spec_path, [])['required']
    spec = json.loads(spec_path.read_bytes())
    units = {sweep.normalize_spec_label(v['name']) or v['name'].casefold(): v.get('unit', v.get('units'))
             for v in spec.get('specs', []) if isinstance(v, dict) and v.get('name')}
    # The existing incremental decimator reports ENOB in bits, independently
    # of a source document's spelling of that algorithm's output dimension.
    units['enob'] = 'bit'
    answer.update(required=required, units={key: units.get(key) for key in required})
    indexed = {(v['process'], v['temperature_c']): v for v in values.get('contexts', [])}
    if len(indexed) != len(contexts) or len(values.get('contexts', [])) != len(contexts):
        answer['gaps'].append('A08_REPLAY_CORNER_POPULATION_MISMATCH')
    for context in contexts:
        coordinate = (context['process'], context['temperature_c'])
        label = context['process'] + '_' + str(context['temperature_c']).replace('-', 'm')
        observed = indexed.get(coordinate, {})
        corner = {'name': label, 'status': observed.get('status', 'NOT_MEASURED'),
                  'observations': {}, 'complete': False, 'score': context['score'], 'points_validated': 0}
        try:
            expected = json.loads(Path(context['settings']['path']).read_bytes())
            score_path = Path(context['score'])
            score = json.loads(score_path.read_bytes()) if score_path.is_file() else {}
            entries = score.get('points') or []
            phases = set()
            for entry in entries:
                point_path = _a0708_file(project, entry['path'], entry['sha256'], invocation)
                point = json.loads(point_path.read_bytes())
                current, why = capture.validate_execution_identity(point)
                if not current:
                    raise MetricRefusal('A08_POINT_EXECUTION_IDENTITY_UNAVAILABLE', why)
                phase = point['settings']['phase_index']
                if (phase in phases or point['settings'] != capture.phase_settings(expected, phase)
                        or point.get('image') != invocation['image']
                        or point.get('native_inputs', {}).get('native_binary') != invocation['tools']['ngspice']):
                    raise MetricRefusal('A08_POINT_METHOD_TOOL_OR_IMAGE_CHANGED', str(point_path))
                phases.add(phase)
                corner['points_validated'] += 1
            complete = (len(entries) == expected['series_length'] and phases == set(range(expected['series_length']))
                and set(observed.get('measured_outputs', [])) == set(required) and bool(required)
                and corner['status'] in ('PASS', 'FAIL'))
            for key in observed.get('measured_outputs', []):
                if key in required and key in observed.get('measurements', {}):
                    corner['observations'][key] = {'value': _finite_number(observed['measurements'][key]),
                                                  'unit': units.get(key)}
            corner['complete'] = complete
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            corner['detail'] = str(exc)
        answer['corners'].append(corner)
    if (values.get('stage') != 'PRE' or values.get('total_corners') != len(contexts)
            or values.get('corners_executed') != len(contexts) or values.get('full_pvt_sweep_executed') is not True
            or values.get('design_traceable') is not True or values.get('gaps')
            or any(not corner['complete'] for corner in answer['corners'])):
        answer['gaps'].append('A08_COMPLETE_CURRENT_POINT_AND_CORNER_POPULATION_REQUIRED')
    if answer['status'] != 'FAIL' and answer['gaps']:
        answer['status'] = 'NOT_MEASURED'
    return answer


def accept_a08(project: Path, context: Mapping, component: Mapping) -> dict:
    """BLOCKING selected incremental PVT metrics; qualification stays separate."""
    import analog_native_flow as native
    project = Path(project).resolve()
    answer = {'schema': SCHEMA, 'step_id': 'A08', 'status': 'NOT_MEASURED', 'metrics': {},
              'scope': 'selected current incremental PVT metrics; no qualification or whole-IC credit'}
    failed = component.get('component_status') == 'FAIL'
    observations, gaps = {}, []
    invocation = component.get('a08_invocation') or {}
    # Collect before checking unrelated authority/readset gaps. The existing
    # producer validates actual DUT/model identity and preserves numerical FAIL
    # beside missing points; changed approved documents cannot cancel that FAIL.
    for row in component.get('native_results', {}).get('steps', []):
        if row.get('step') != 'A08':
            continue
        try:
            value = _a08_incremental_observation(project, row, invocation)
            failed = failed or value['status'] == 'FAIL'
            if row['block'] in observations:
                raise MetricRefusal('A08_DUPLICATE_BLOCK', row['block'])
            observations[row['block']] = value
            gaps.extend(value['gaps'])
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            gaps.append(str(exc))
    answer['native_observation'] = observations
    try:
        invocation, rows = _a0708_rows(project, context, component, 'A08')
        if not observations and all((_a08_selected(project, row['block']).get('pvt') or {}).get('kind')
                                   not in ('incremental_capture', 'declared_testbench') for row in rows):
            # Preserve the existing unselected legacy summary diagnostics;
            # the selected producer repair does not qualify that old route.
            required, _ = _approved_authority(project, 'requirements/base_A7/pvt_load_modes.json#/required_items', ('block', 'name'))
            wanted = {(v['block'], v['name']) for v in required['required_items']}
            if not wanted:
                raise MetricRefusal('A08_EMPTY_PVT_POPULATION', 'required_items')
            observed = set()
            for row in rows:
                for path in row.get('outputs', []):
                    if Path(path).name == 'corner_results.json':
                        record = json.loads(Path(path).read_bytes())
                        observed.update((row['block'], corner['name']) for corner in record.get('corners', [])
                            if isinstance(corner, dict) and corner.get('_provenance') == 'real_ngspice')
            answer['metrics']['pvt_load_modes'] = {'status': 'NOT_MEASURED', 'required': sorted(wanted),
                'observed': sorted(observed), 'missing': sorted(wanted - observed), 'authority': required}
            answer['metrics']['prelayout_performance'] = {'status': 'NOT_MEASURED',
                'reason': 'A08_PER_CORNER_EXECUTABLE_ARGV_AND_PREEXEC_MODEL_READSET_ABSENT',
                'producer': 'analog_real_corner_sweep.py::_run_ngspice/_run_block',
                'source_output': 'phase3/analog/<block>/corner_results.json#/corners'}
            answer.update(status='FAIL' if failed else 'NOT_MEASURED',
                reason='A08_MEASURED_NATIVE_FAILURE_PRESERVED' if failed else
                       'A08_PER_CORNER_EXECUTABLE_ARGV_AND_PREEXEC_MODEL_READSET_ABSENT')
            return answer
        if set(observations) != {row['block'] for row in rows}:
            raise MetricRefusal('A08_SELECTED_BLOCK_POPULATION_INCOMPLETE', '; '.join(gaps))
        expected = {(block, corner['name']) for block, value in observations.items() for corner in value['corners']}
        observed = {(block, corner['name']) for block, value in observations.items() for corner in value['corners'] if corner['complete']}
        try:
            required, _ = _approved_authority(project, 'requirements/base_A7/pvt_load_modes.json#/required_items', ('block', 'name'))
            wanted = {(v['block'], v['name']) for v in required['required_items']}
            complete = (bool(expected) and wanted == expected == observed
                and len(wanted) == len(required['required_items']) and not gaps)
            answer['metrics']['pvt_load_modes'] = {'status': 'PASS' if complete else 'NOT_MEASURED',
                'required': sorted(wanted), 'observed': sorted(observed), 'missing': sorted(wanted - observed),
                'unexpected': sorted(expected - wanted), 'authority': required}
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            answer['metrics']['pvt_load_modes'] = {'status': 'NOT_MEASURED', 'detail': str(exc)}
        try:
            authority, document = _approved_document(project, 'requirements/base_A7/prelayout_performance.json',
                authority='requirements_owner', schema=AUTHORITY_SCHEMA)
            limits, units = document['limits'], document['units']
            comparisons = []
            population = set(limits) == set(units) == set(observations)
            for block, value in observations.items():
                population = population and set(limits.get(block, {})) == set(units.get(block, {})) == set(value['required']) and bool(value['required'])
                for corner in value['corners']:
                    checked = _a0708_compare({block: corner['observations']}, {block: limits.get(block, {})}, {block: units.get(block, {})})
                    comparisons.extend({**item, 'corner': corner['name']} for item in checked)
            violated = any(v['status'] == 'FAIL' for v in comparisons)
            answer['metrics']['prelayout_performance'] = {'status': 'FAIL' if violated or failed else
                'PASS' if population and comparisons and not gaps and all(v['status'] == 'PASS' for v in comparisons) else 'NOT_MEASURED',
                'comparisons': comparisons, 'authority': authority}
            failed = failed or violated
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            answer['metrics']['prelayout_performance'] = {'status': 'FAIL' if failed else 'NOT_MEASURED', 'detail': str(exc)}
        if native._a08_invocation(project) != invocation:
            raise MetricRefusal('A08_INPUT_CHANGED_DURING_ACCEPTANCE', 'readset')
        answer.update(status='FAIL' if failed else native._aggregate(list(answer['metrics'].values())),
            input_views=invocation['inputs'], gaps=gaps, reason='A08_CURRENT_SELECTED_INCREMENTAL_PVT_METRICS_EVALUATED')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        answer.update(status='FAIL' if failed else 'NOT_MEASURED',
            reason=getattr(exc, 'code', 'A08_NATIVE_PVT_INPUT_ABSENT'), detail=str(exc), gaps=gaps)
    return answer


def _d40_routed_population(path: Path) -> tuple[list[dict], list[dict]]:
    """Read every signal NETS record; reject truncation/duplicates/unknown syntax.

    Reuse the existing DEF-net reader. SPECIALNETS and a wire keyword without
    coordinates are not routed signal nets. An explicit empty section is data;
    only the requirements owner can validate its applicability/absence.
    """
    from drc_feedback_repair import _def_nets
    text = path.read_text()
    sections = list(re.finditer(r'^NETS\s+(\d+)\s*;(.*?)^END NETS\s*$', text, re.M | re.S))
    if len(sections) != 1 or not re.search(r'^END DESIGN\s*$', text, re.M):
        raise MetricRefusal('D40_DEF_POPULATION_UNREADABLE', str(path))
    section = sections[0]
    body = section[2]
    records = list(re.finditer(r'(?:^|\n)\s*-\s+(\S+)(.*?)\s*;', body, re.S))
    remainder = re.sub(r'(?:^|\n)\s*-\s+(\S+)(.*?)\s*;', '', body, flags=re.S)
    if (remainder.strip() or len(records) != int(section[1])
            or len({r[1] for r in records}) != len(records)):
        raise MetricRefusal('D40_DEF_POPULATION_INCOMPLETE', str(path))
    if not records:
        return [], []
    _, nets = _def_nets(path)
    if set(nets) != {r[1] for r in records}:
        raise MetricRefusal('D40_DEF_POPULATION_INCOMPLETE', str(path))
    observed, routed = [], []
    for name, route in nets.items():
        geometry = re.search(r'\+\s+(?:ROUTED|FIXED|COVER)\s+\S+\s+\(\s*(?:-?\d+|\*)\s+(?:-?\d+|\*)\s*\)', route) is not None
        observed.append({'net': name, 'routed': geometry})
        if geometry:
            routed.append({'net': name})
    return observed, routed


def accept_d40(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """BLOCKING current step21 route readback, then existing per-use admission.

    Bind the complete native chain and views. Coverage uses only the approved
    independent required set. DRC uses the receipt-bound rerouter's actual
    terminal marker metric, corroborated by its raw report and route transcript.
    Unknown/missing data is NOT_MEASURED; a measured FAIL survives later NI.
    This function runs no tool and authors no approval/qualification authority.
    """
    import inspect
    import flow109
    import flow109_admission as admission
    import librelane_contract as ll
    import librelane_route as route
    import phase3_one_shot_runner as R
    import execution_backend_producers as native

    project = Path(project).resolve()
    reads = {}
    result = {'schema': SCHEMA, 'row_id': 'D40', 'status': 'NOT_MEASURED',
        'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
        'delivery_blocked': True, 'obligations': []}

    def read(name, digest=None, *, external=False):
        path = Path(name)
        path = path if path.is_absolute() else project / path
        if (path.is_symlink() or not path.is_file()
                or (not external and not path.resolve().is_relative_to(project))
                or any(p.is_symlink() for p in path.parents if p.is_relative_to(project))):
            raise MetricRefusal('D40_INPUT_UNBOUND', str(path))
        raw = path.read_bytes()
        actual = _sha(raw)
        key = str(path.relative_to(project)) if path.is_relative_to(project) else str(path)
        if digest is not None and digest != actual or key in reads and reads[key] != actual:
            raise MetricRefusal('D40_INPUT_CHANGED', key)
        reads[key] = actual
        return path, raw

    def document(name, digest=None):
        path, raw = read(name, digest)
        return path, json.loads(raw)

    failures = (MetricRefusal, flow109.Flow109Error, ll.Refusal, OSError, ValueError,
                KeyError, TypeError, AttributeError)
    try:
        current = flow109.validate_execution_context(context)
        row = current['resolved_row']
        specs = row['obligations']
        if (row['id'] != 'D40' or tuple(o['metric'] for o in specs) !=
                ('routed_net_coverage', 'routing_drc_errors')
                or specs[0]['expectation'] != {'operator': 'covers_all',
                    'required_set_ref': 'requirements/base_27/routed_net_coverage.json#/required_items',
                    'empty_set_policy': 'requires validated absence/applicability evidence'}
                or specs[1]['expectation'].get('operator') != 'eq'
                or specs[1]['expectation'].get('value') != 0
                or specs[1]['expectation'].get('unit') != 'count'):
            raise MetricRefusal('D40_CONTRACT_CHANGED', 'routing obligations')
        coverage, drc = ({'id': spec['id'], 'status': 'NOT_MEASURED'} for spec in specs)
        result['obligations'] = [coverage, drc]
        _, chain = document('reports/phase3/execution-backend-21.json')
        steps = chain['ordered_steps']
        if (not isinstance(steps, list) or len(set(steps)) != len(steps)
                or steps[0] != 'OpenROAD.GlobalRouting' or steps[-1] != 'OpenROAD.FillInsertion'
                or route.DRT not in steps or route.NVR not in steps
                or steps.index(route.NVR) != steps.index(route.DRT) + 1
                or len(chain['states']) != len(steps)):
            raise MetricRefusal('D40_CHAIN_UNBOUND', 'selected routing chain')
        cfgroot = project / 'phase3/librelane/execution-backend-21-config'
        read(cfgroot / 'flow_gates.json')
        gated = ll.flow_gated_off(cfgroot)
        if 'OpenROAD.RepairAntennas' not in steps and 'OpenROAD.RepairAntennas' not in gated:
            raise MetricRefusal('D40_CHAIN_UNBOUND', 'antenna stage neither executed nor source-gated')
        if any(step in gated for step in steps):
            raise MetricRefusal('D40_CHAIN_UNBOUND', 'executed population conflicts with flow gates')
        previous, _ = read(chain['initial_state'], chain['initial_sha256'])
        executions, states, folders, logs = [], {}, {}, []
        working_report = None
        for index, (step, ref) in enumerate(zip(steps, chain['states']), 1):
            state_path, state = document(ref['state'], ref['sha256'])
            expected = project / 'phase3/librelane/execution-backend-21' / (
                f'{index:02d}-' + step.lower().replace('.', '-'))
            if ref['step'] != step or state_path.parent != expected:
                raise MetricRefusal('D40_CHAIN_UNBOUND', step)
            receipt = ll.validate_step_receipt(expected, step)
            read(expected / 'vibeic_receipt.json')
            for name, digest in receipt['sha256'].items():
                read(expected / name, digest)
            fp = receipt['input']
            if fp.get('step') != step or not fp.get('image') or fp['image'] != component.get('native_image'):
                raise MetricRefusal('D40_EXECUTION_CHANGED', step)
            if step.startswith(ll.PLUGIN_STEP_PREFIX) and fp.get('plugin') != ll._plugin_digests(step):
                raise MetricRefusal('D40_PRODUCER_SOURCE_CHANGED', step)
            read(previous, fp['state'])
            input_state = json.loads(previous.read_bytes())
            actual = {str(p): _sha(p.read_bytes()) for p in ll._walk_paths(
                {k: v for k, v in input_state.items() if k != 'metrics'})}
            if not actual or actual != fp.get('state_files') or not any(Path(p).suffix == '.sdc' for p in actual):
                raise MetricRefusal('D40_STATE_POPULATION_CHANGED', step)
            for name, digest in actual.items():
                read(name, digest)
            # Strict timing, cell policy and NVR select derived configs. The
            # existing producer records the actual path, not a guessed name.
            config_path, config = document(ref['config'], ref['config_sha256'])
            if (config_path.parent != cfgroot or ref['config_sha256'] != fp['config']
                    or config.get('meta', {}).get('step') != step):
                raise MetricRefusal('D40_CONFIG_CHANGED', step)
            _, pdk = document(expected / 'pdk_root.json')
            mounts = pdk['mounts_under_it']
            config_inputs, recorded_inputs = dict(config), dict(fp.get('config_files') or {})
            if step == route.NVR and 'VIBEIC_NVR_REPORT_PATH' in config:
                # Native NamedViolationReroute overwrites this working OUTPUT
                # from its bound DRT report before reading it. The generic
                # fingerprint may include a prior file here; it is not an
                # immutable input. All other config material remains exact.
                working_report = Path(config_inputs.pop('VIBEIC_NVR_REPORT_PATH'))
                if working_report != cfgroot / 'nvr/execution-backend-21' / R.ROUTER_DRC_REPORT_NAME:
                    raise MetricRefusal('D40_WORKING_OUTPUT_FOREIGN', str(working_report))
                recorded_inputs.pop(str(working_report), None)
            if not recorded_inputs or ll.config_file_hashes(config_inputs, mounts) != recorded_inputs:
                raise MetricRefusal('D40_CONFIG_POPULATION_CHANGED', step)
            for name, digest in recorded_inputs.items():
                path = Path(name)
                for host, guest in sorted(mounts, key=lambda m: len(m[1]), reverse=True):
                    if path.is_relative_to(guest):
                        path = Path(host) / path.relative_to(guest)
                        break
                read(path, digest, external=True)
            for log in sorted(expected.glob('*.log')):
                read(log)
                logs.append('# ' + str(expected.relative_to(project)) + '/' + log.name + '\n' +
                            log.read_text(errors='replace') + '\n')
            executions.append({'step': step, 'input': fp,
                'receipt_sha256': _sha((expected / 'vibeic_receipt.json').read_bytes())})
            states[step], folders[step], previous = state, expected, state_path
        _, handoff = document('reports/phase3/execution-backend-execution-backend-21-handoff.json')
        final, _ = read(handoff['state'], handoff['state_sha256'])
        if final != previous:
            raise MetricRefusal('D40_HANDOFF_FOREIGN', 'terminal routing state')
        for view, target in (('def', 'routed.def'), ('odb', 'routed.odb'),
                             ('nl', str(ll._def_design_name(Path(state['def']))) + '_pnr.v')):
            ref = handoff['views'][view]
            source, _ = read(ref['source'], ref['source_sha256'])
            dest, _ = read(ref['dest'], ref['dest_sha256'])
            if (state.get(view) != str(source) or dest != project / 'phase3/stage3/pnr' / target
                    or ref['source_sha256'] != ref['dest_sha256']):
                raise MetricRefusal('D40_HANDOFF_FOREIGN', view)
        invariant = {'status': 'APPROVED', 'value': 0, 'unit': 'count',
            'source': 'canonical base_27.routing_drc_errors invariant'}
        identity = {'producer': executions, 'tool_execution': executions,
            'checker': {'program': 'flow109_metric_acceptance.accept_d40',
                'sha256': _sha(inspect.getsource(accept_d40).encode()),
                'def_reader_sha256': _sha(inspect.getsource(_d40_routed_population).encode()),
                'producer_sha256': _sha(inspect.getsource(native.produce_pnr).encode())},
            'consumed_inputs': dict(reads), 'requirements': invariant,
            'configuration': {'context_sha256': current['context_sha256']}}
        # Judge a bound positive native count before any later reporting or
        # requirements refusal; no report/admission NI may erase that FAIL.
        try:
            key = 'vibeic__route__named_reroute__markers_after'
            value = states[route.NVR]['metrics'][key]
            _finite_number(value, count=True)
            measurement = {'status': 'MEASURED', 'value': value, 'unit': 'count', 'identity': identity}
            drc['measurement'] = measurement
            drc['status'], drc['reason'] = evaluate_operator('eq', measurement, invariant)
            if states[steps[-1]].get('metrics', {}).get(key) != value:
                raise MetricRefusal('D40_NATIVE_METRIC_CHANGED', key)
            _, raw_log = read('phase3/stage3/pnr/openroad.log')
            if raw_log.decode() != ''.join(logs):
                raise MetricRefusal('D40_LOG_POPULATION_CHANGED', 'native chain transcript')
            native_log = read(folders[route.DRT] / 'invocation.log')[1].decode()
            if not R._detail_route_completed(native_log) or not R._detail_route_completed(raw_log.decode()):
                raise MetricRefusal('D40_ROUTER_INCOMPLETE', 'native terminal marker absent')
            _, native_report = read(folders[route.NVR] / 'named_viol_after.drc')
            if working_report is not None and read(working_report)[1] != native_report:
                raise MetricRefusal('D40_WORKING_OUTPUT_CHANGED', str(working_report))
            _, published_report = read('phase3/stage3/pnr/' + R.ROUTER_DRC_REPORT_NAME)
            report_count = len(R._router_drc_report_records(project / 'phase3/stage3/pnr'))
            if (native_report != published_report or (native_report.strip() and not report_count)
                    or report_count != value or R._drt_final_violations(raw_log.decode()) != value):
                raise MetricRefusal('D40_ROUTER_REPORT_MISMATCH', 'native metric/report/transcript disagree')
            _, receipt = document('phase3/stage3/pnr/' + R.ROUTER_DRC_RECEIPT_NAME)
            expected = {'schema': 'vibeic.router_drc_receipt.v1',
                'producer': 'phase3_one_shot_runner.step_pnr', 'report': R.ROUTER_DRC_REPORT_NAME,
                'report_sha256': _sha(published_report), 'log': 'openroad.log',
                'log_sha256': _sha(raw_log), 'routed_def': 'routed.def',
                'routed_def_sha256': reads['phase3/stage3/pnr/routed.def'],
                'final_drt_count': value, 'route_completed': True, 'current_invocation_count': value}
            if receipt != expected:
                raise MetricRefusal('D40_ROUTER_RECEIPT_CHANGED', 'current route/report binding')
        except failures as exc:
            if drc['status'] != 'FAIL':
                drc['status'] = 'NOT_MEASURED'
            drc.update(reason=getattr(exc, 'code', 'D40_ROUTER_UNMEASURED'), detail=str(exc))
        try:
            observed, routed = _d40_routed_population(project / 'phase3/stage3/pnr/routed.def')
            coverage['observed_population'] = observed
            auth, body = _approved_authority(project, specs[0]['expectation']['required_set_ref'], ('net',))
            read(auth['path'], auth['sha256'])
            read(auth['source']['path'], auth['source']['sha256'])
            if not body['required_items']:
                absence = body['validated_absence']['source_reference']
                read(absence['path'], absence['sha256'])
                if observed:
                    raise MetricRefusal('D40_EMPTY_AUTHORITY_CONTRADICTED', 'observed signal nets exist')
            measurement = {'status': 'MEASURED', 'value': routed, 'unit': 'set',
                'identity': {**identity, 'requirements': auth, 'consumed_inputs': dict(reads)}}
            coverage['measurement'] = measurement
            coverage['status'], coverage['reason'] = evaluate_operator('covers_all', measurement, auth)
        except failures as exc:
            coverage.update(reason=getattr(exc, 'code', 'D40_COVERAGE_UNMEASURED'), detail=str(exc))
        for name, digest in reads.items():
            read(name, digest, external=True)
        identity['consumed_inputs'] = dict(reads)
        result['readset'] = dict(reads)
    except failures as exc:
        result.update(reason=getattr(exc, 'code', 'D40_NATIVE_BINDING_UNPROVEN'), detail=str(exc))
        for obligation in result['obligations']:
            if obligation['status'] == 'PASS':
                obligation.update(status='NOT_MEASURED', reason='D40_BINDING_INCOMPLETE')
    statuses = [o['status'] for o in result['obligations']]
    if component.get('verdict') == 'FAIL' or 'FAIL' in statuses:
        result['status'] = result['metric_status'] = 'FAIL'
    elif statuses and all(s == 'PASS' for s in statuses):
        result['metric_status'] = 'PASS'
        try:
            result['qualification_receipt'] = admission.require_admission(project, current)
            result.update(status='PASS', qualification='PASS', delivery_blocked=False)
        except admission.AdmissionRefusal as exc:
            result.update(reason=exc.code, qualification_receipt=exc.report)
    return result
