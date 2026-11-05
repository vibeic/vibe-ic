"""Flow109 M05 read-only seam over the existing mixed-interface SI evidence.

Open Default has no qualified PDK substrate extractor/model.  The inherited
consumer is still run so a real measured failure remains FAIL; ordinary wire-RC
or advisory capacitive screening can never become M05 PASS.
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
import mixed_signal_interface_si_check as si_check
import mixed_signal_m3_run as m3

SCHEMA = "vibeic.flow109.substrate-supply-coupling.v1"
INPUT = "input/flow109/M05.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operation_sources():
    from execution_provider_catalog import source_closure
    paths = source_closure({Path(__file__), Path(si_check.__file__), Path(m3.__file__),
                            HERE / "_mixed_signal_native.py", HERE / "flow109.py",
                            HERE / "flow109_admission.py"})
    return {str(p.relative_to(HERE.parent)): _sha(p) for p in sorted(paths)}


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal("M05_INPUT_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal("M05_INPUT_INVALID", str(path))
    return value


def _record(project, path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(project)), "sha256": _sha(path)}


def execute(project, context):
    project = Path(project).resolve()
    context = validate_execution_context(context)
    if context["requested_step"] != "M05" or context["native_step_id"] != "flow109.M05":
        raise Flow109Error("FLOW109_M05_WRONG_COMPONENT", str(context["requested_step"]))
    require_launch_admission(project, "flow109.M05", {"flow109_context": context})
    sources = operation_sources()
    manifest_path = project / INPUT
    manifest = _read(manifest_path)
    unavailable = {"applicable": False,
                   "reason": "no qualified open substrate extraction/model"}
    if manifest != {"schema": SCHEMA, "basis": "open_default_capability_probe",
                    "substrate_model": unavailable}:
        raise AdmissionRefusal("M05_RUNTIME_SCOPE_MISMATCH",
                               "unsupported capability probe must not claim a substrate model")
    parent = project / "reports/flow109/attempts"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="M05-", dir=parent))
    output = attempt / "interface-si-consumer.json"
    rc = si_check.main([str(project), "--require-current-production", "--json", str(output)])
    try:
        consumer = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal("M05_CONSUMER_RECEIPT_INVALID", str(output)) from exc
    # The existing reader can establish a real violation but its timing/noise/
    # crosstalk report has no foundry-calibrated substrate-network dimension.
    rules = {row.get("rule") for row in consumer.get("findings", [])
             if isinstance(row, dict)}
    measured_fail = bool(rules & {"FAILED_MEASUREMENT", "NATIVE_EXECUTION_FAILED"})
    status = "FAIL" if measured_fail else "NOT_MEASURED"
    reason = ("M05_MEASURED_INTERFACE_FAIL" if status == "FAIL" else
              "M05_SUBSTRATE_SUPPLY_MODEL_UNSUPPORTED_OPEN_DEFAULT")
    report = {"schema": SCHEMA, "step_id": "M05", "native_step_id": "flow109.M05",
              "context_sha256": context["context_sha256"], "component_status": status,
              "reason": reason, "flow109_acceptance": "NOT_MEASURED",
              "whole_flow_acceptance": "NOT_MEASURED", "consumer": consumer,
              "consumer_returncode": rc,
              "capability_input": _record(project, manifest_path),
              "qualification_status": "NOT_MEASURED",
              "operation_sources": sources, "metric_acceptance_status": "UNIMPLEMENTED",
              "unsupported_scope": ("no qualified PDK substrate extraction/model; ordinary SPEF "
                                    "wire RC and advisory crosstalk are insufficient"),
              "unimplemented_obligations": [x["id"] for x in context["resolved_row"]["obligations"]],
              "gate_layers": {f"G{i}": "NOT_MEASURED" for i in range(1, 10)}}
    write_json(attempt / "component.json", report)
    return report
