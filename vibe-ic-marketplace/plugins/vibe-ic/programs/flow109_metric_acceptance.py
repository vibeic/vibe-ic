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
                or approval.get("authority") != "requirements_owner"):
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


def accept_d19(project: Path, context: Mapping[str, Any], component: Mapping[str, Any]) -> dict:
    """Reopen the actual producer's existing contracts and all consumed files.

    The exception obligation stays unimplemented until independently measured;
    passing these two plan metrics cannot qualify the row or scan timing.
    """
    result = {"schema": SCHEMA, "row_id": "D19", "status": "NOT_MEASURED",
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
        if statuses and all(status == "PASS" for status in statuses):
            result.update(status="PASS", delivery_blocked=False)
        elif "FAIL" in statuses:
            result["status"] = "FAIL"
        result["reason"] = "D19_PLAN_METRICS_ONLY_NATIVE_CONTROLS_NOT_QUALIFIED"
    except (MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        result.update(reason=getattr(exc, "code", "D19_METRIC_REFUSED"), detail=str(exc))
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
                groups = config.get(field) or {}
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


def _d12_qualification(project: Path, context: Mapping) -> dict:
    import flow109_admission as admission
    admitted = admission.require_admission(project, context)
    uses = context['runtime_tool_uses']
    if (len(uses) != 1 or uses[0]['tool_id'] != 'python3'
            or uses[0]['semantics'] != {'purpose': 'D12.default', 'native_steps': list(D12_STEPS)}):
        raise MetricRefusal('D12_QUALIFICATION_SCOPE_INVALID', 'existing three structural rules only')
    config = json.loads((project / uses[0]['config']['path']).read_bytes())
    if config != {'purpose': D12_PURPOSE, 'native_steps': list(D12_STEPS),
                  'model_sources': d12_model_sources()}:
        raise MetricRefusal('D12_MODEL_QUALIFICATION_STALE', 'model/role/rule source changed')
    return admitted


def _d12_observe(project: Path, source: Mapping) -> dict:
    """Reopen the original native graph; run existing structural readers only."""
    import _cdc_netlist as native
    import ai_signed_judgement as expert
    subject = d12_subject(project)
    if source.get('subject') != subject:
        raise MetricRefusal('D12_SUBJECT_STALE', 'original source/graph/roles differ from authority')
    for reference in source.get('source_refs', []):
        if (set(reference) != {'path', 'sha256'}
                or _sha(_safe_project_file(project, reference['path']).read_bytes()) != reference['sha256']):
            raise MetricRefusal('D12_SOURCE_REFERENCE_STALE', str(reference))
    if not source.get('source_refs'):
        raise MetricRefusal('D12_SOURCE_REFERENCES_ABSENT', 'independent original design authority required')
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
    """Three normal D12 obligations; qualified native failure survives missing protocols."""
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
        qualified = _d12_qualification(project, current)
        observed = _d12_observe(project, source)
        result.update(qualification='PASS', observed=observed)
        failures = [f for f in observed['findings'] if f.get('severity') in ('ERROR', 'FATAL')
                    and f.get('rule') != 'RESET_ROLE_UNRESOLVED']
        result['obligations'][1].update(status='FAIL' if failures else 'PASS'
            if observed['reset_analysis'].get('cycle_detection_complete') is True else 'NOT_MEASURED', observed_value=len(failures),
                                         unit='count', findings=failures)
        result['component_status'] = 'FAIL' if failures else 'PASS'
        try:
            authority, _body, census_source = _d12_source(project, 'clock_reset_crossing_census', D12_FIELDS)
            if census_source != source:
                raise MetricRefusal('D12_AUTHORITY_SUBJECT_MISMATCH', 'census source differs')
            census = _d12_census(project, source, observed)
            status, reason = evaluate_operator('covers_all', {'status': 'MEASURED', 'value': census,
                'identity': {'producer': {'path': native.NETLIST_MANIFEST_REL,
                    'sha256': _sha((project / native.NETLIST_MANIFEST_REL).read_bytes())}, 'checker': d12_model_sources(),
                    'tool_execution': qualified, 'consumed_inputs': observed['subject'],
                    'requirements': authority, 'configuration': source['input_domains']}}, authority)
            result['obligations'][0].update(status=status, reason=reason, observed_value=census)
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
        if (_d12_observe(project, source) != observed or _d12_qualification(project, current) != qualified):
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
    for key in ('property_denominator', 'authored_property_count', 'covered_property_count',
                'unresolved_obligations'):
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
