"""Flow109 M02 adapter for the existing bounded native M3 producer.

M02 accepts only the declared-model, pre-layout portion of ``mixed_signal_m3_run``.
The producer's physical SI result is deliberately not used here.  This module
does not manufacture a digital wrapper for SPICE-only blocks and never turns a
component result into Flow109 or whole-IC acceptance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109 import Flow109Error, validate_execution_context
from flow109_admission import AdmissionRefusal, require_launch_admission
import mixed_signal_cosim_check as cosim_check
import mixed_signal_m3_run as m3

SCHEMA = "vibeic.flow109.mixed-prelayout.v1"
INPUT = "input/flow109/M02.json"
NATIVE_CONTRACT = "input/mixed_signal/native.json"
REQUIRED_PREDECESSORS = ("M01",)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code="M02_INPUT_INVALID"):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project, record, code="M02_STALE_OR_MISSING_INPUT"):
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise AdmissionRefusal("M02_UNBOUND_INPUT", str(record))
    rel = Path(str(record.get("path", "")))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise AdmissionRefusal("M02_UNBOUND_INPUT", str(record))
    path = (project / rel).resolve()
    if (not path.is_relative_to(project) or not path.is_file()
            or path.is_symlink() or _sha(path) != record.get("sha256")):
        raise AdmissionRefusal(code, str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(project)), "sha256": _sha(path)}


def operation_sources():
    from execution_provider_catalog import source_closure
    roots = {Path(__file__), Path(m3.__file__), Path(cosim_check.__file__),
             HERE / "_mixed_signal_native.py", HERE / "_mixed_signal_receiver_noise.py",
             HERE / "_mixed_signal_current.py", HERE / "flow109.py",
             HERE / "flow109_admission.py"}
    paths = source_closure({p for p in roots if p.is_file()})
    return {str(p.relative_to(HERE.parent)): _sha(p) for p in sorted(paths)}


def _predecessors(project, manifest):
    rows = manifest.get("predecessor_receipts")
    if not isinstance(rows, list) or len(rows) != len(REQUIRED_PREDECESSORS):
        raise AdmissionRefusal("M02_PREDECESSOR_SET_INVALID", str(rows))
    bound = []
    observed = set()
    for record in rows:
        path = _bound(project, record, "M02_PREDECESSOR_STALE")
        body = _read(path, "M02_PREDECESSOR_INVALID")
        step = body.get("step_id")
        if step not in REQUIRED_PREDECESSORS or step in observed:
            raise AdmissionRefusal("M02_PREDECESSOR_SET_INVALID", str(step))
        observed.add(step)
        status = body.get("component_status", body.get("verdict"))
        if status == "FAIL":
            raise AdmissionRefusal("M02_PREDECESSOR_FAILED", str(step))
        if status != "PASS":
            raise AdmissionRefusal("M02_PREDECESSOR_NOT_MEASURED", str(step))
        bound.append(_record(project, path))
    if observed != set(REQUIRED_PREDECESSORS):
        raise AdmissionRefusal("M02_PREDECESSOR_SET_INVALID", str(sorted(observed)))
    return bound


def prepare(project, context):
    project = Path(project).resolve()
    context = validate_execution_context(context)
    if context["requested_step"] != "M02" or context["native_step_id"] != "flow109.M02":
        raise Flow109Error("FLOW109_M02_WRONG_COMPONENT", str(context["requested_step"]))
    require_launch_admission(project, "flow109.M02", {"flow109_context": context})
    sources = operation_sources()
    manifest_path = project / INPUT
    manifest = _read(manifest_path)
    if manifest.get("schema") != SCHEMA or manifest.get("basis") != "current_pre_layout_partition":
        raise AdmissionRefusal("M02_BASIS_UNSUPPORTED", str(manifest.get("basis")))
    contract_path = _bound(project, manifest.get("native_contract"))
    plan_path = _bound(project, manifest.get("scenario_plan"))
    if contract_path != (project / NATIVE_CONTRACT).resolve():
        raise AdmissionRefusal("M02_NATIVE_CONTRACT_PATH_INVALID", str(contract_path))
    native = _read(contract_path)
    top = manifest.get("top")
    if (native.get("schema") != "vibeic.mixed_signal.native_inputs.v1"
            or native.get("top") != top or native.get("scope") != "declared_model_component"):
        raise AdmissionRefusal("M02_PRELAYOUT_PARTITION_UNSUPPORTED",
                               "an actual declared-model wrapper/SPICE partition is required")
    if plan_path.name != "L22_VERIFICATION_PLAN.json" or not m3.plan(project):
        raise AdmissionRefusal("M02_SCENARIO_PLAN_ABSENT", str(plan_path))
    predecessors = _predecessors(project, manifest)
    inputs = m3.inputs(project, top)
    inputs[str(Path(INPUT))] = _sha(manifest_path)
    for record in predecessors:
        inputs[record["path"]] = record["sha256"]
    return {"top": top, "container": manifest.get("container", "host"),
            "inputs": inputs, "sources": sources, "predecessors": predecessors}


def _before(project, context, prepared):
    require_launch_admission(project, "flow109.M02", {"flow109_context": context})
    if operation_sources() != prepared["sources"]:
        raise AdmissionRefusal("M02_OPERATION_SOURCE_CHANGED", "before native consumer")
    current = m3.inputs(project, prepared["top"])
    for name, digest in prepared["inputs"].items():
        path = project / name
        actual = current.get(name, _sha(path) if path.is_file() else None)
        if actual != digest:
            raise AdmissionRefusal("M02_STALE_OR_MISSING_INPUT", name)


def _literal_measured_failures(project):
    """Return simulation error counters that cannot be a successful M02 result.

    Scenario-specific voltage limits remain owned by L22.  In contrast, a
    sampled wrapper with response errors or unknown observations did not
    successfully correlate, even if an incomplete criteria list allowed the
    scenario's self-verdict to say PASS.
    """
    try:
        body = m3.read(project / m3.COSIM)
    except m3.Refusal:
        return []
    failures = []
    for row in body.get("scenarios", []) if isinstance(body.get("scenarios"), list) else []:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for name in ("response_mismatches", "response_errors", "unknown_samples"):
            value = metrics.get(name)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and value > 0):
                failures.append({"scenario": row.get("id"), "metric": name,
                                 "measured": value, "required": 0})
    return failures


def execute(project, context):
    project = Path(project).resolve()
    prepared = prepare(project, context)
    parent = project / "reports/flow109/attempts"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="M02-", dir=parent))
    status, reason, producer, audit = "NOT_MEASURED", "M02_NOT_MEASURED", None, None
    literal_failures = []
    reused = False
    try:
        _before(project, context, prepared)
        if (project / m3.RECEIPT).is_file():
            audit = m3.audit(project, "cosim")
            if (audit.get("verdict") == "FAIL"
                    or (audit.get("verdict") == "PASS" and audit.get("passed") is True)):
                producer = m3.read(project / m3.RECEIPT)
                reused = True
        if not reused:
            producer = m3.produce(project, prepared["top"], prepared["container"])
            audit = m3.audit(project, "cosim")
        gate_path = attempt / "cosim-consumer.json"
        gate_rc = cosim_check.main([str(project), "--require-current-production",
                                    "--json", str(gate_path)])
        gate = _read(gate_path, "M02_CONSUMER_RECEIPT_INVALID")
        literal_failures = _literal_measured_failures(project)
        measured_fail = (producer.get("cosim_verdict") == "FAIL"
                         or audit.get("verdict") == "FAIL" or gate_rc == 1
                         or bool(literal_failures))
        if measured_fail:
            status, reason = "FAIL", "M02_MEASURED_FAIL"
        elif (producer.get("cosim_verdict") == "PASS" and audit.get("verdict") == "PASS"
              and gate_rc == 0 and gate.get("passed") is True):
            status, reason = "PASS", "M02_CURRENT_NATIVE_COSIM_COMPONENT_PASS"
        else:
            reason = "M02_NATIVE_COSIM_INCOMPLETE"
    except (m3.Refusal, AdmissionRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        rule = getattr(exc, "rule", "M02_INVALID_EVIDENCE")
        status = "FAIL" if rule in ("FAILED_MEASUREMENT", "NATIVE_EXECUTION_FAILED") else "NOT_MEASURED"
        reason = rule + ": " + str(exc)
    _before(project, context, prepared)
    report = {"schema": SCHEMA, "step_id": "M02", "native_step_id": "flow109.M02",
              "context_sha256": context["context_sha256"], "component_status": status,
              "reason": reason, "flow109_acceptance": "NOT_MEASURED",
              "whole_flow_acceptance": "NOT_MEASURED", "inputs": prepared["inputs"],
              "predecessors": prepared["predecessors"], "operation_sources": prepared["sources"],
              "producer_receipt": producer, "cosim_audit": audit,
              "reused_current_native": reused,
              "literal_measured_failures": literal_failures,
              "qualification_status": "NOT_MEASURED",
              "metric_acceptance_status": "UNIMPLEMENTED",
              "unimplemented_obligations": [x["id"] for x in context["resolved_row"]["obligations"]],
              "gate_layers": {f"G{i}": "NOT_MEASURED" for i in range(1, 10)},
              "scope": "declared pre-layout mixed component; physical SI and whole ADC NOT_MEASURED"}
    write_json(attempt / "component.json", report)
    return report
