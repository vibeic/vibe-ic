"""Bounded D08/M03/M04 adapters over the existing macro and mixed owners.

These are component receipts only.  In particular M03 keeps physical LVS as
NOT_MEASURED when the neutral merge fixture has no foundry PDK, and none of
the three receipts implements the still-unbound Flow109 metrics or G1--G9.
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
from flow109_admission import AdmissionRefusal, require_launch_admission
import ip_integration_check as ip_check
import mixed_signal_top_lvs_run as m1
import mixed_signal_power_domain_run as m2
import power_domain_crossing_check as crossing_check
import level_shifter_required_check as level_check
import isolation_cell_required_check as isolation_check
import power_domain_signal_crossing_check as signal_crossing_check

SCHEMA = "vibeic.flow109.macro-mixed-component.v1"
ROWS = {"D08", "M03", "M04"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operation_sources() -> dict[str, str]:
    paths = (Path(__file__), HERE / "flow109.py", HERE / "flow109_admission.py",
             Path(ip_check.__file__), Path(m1.__file__),
             Path(m2.__file__), Path(crossing_check.__file__), Path(level_check.__file__),
             Path(isolation_check.__file__), Path(signal_crossing_check.__file__))
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in paths}


def _read(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project: Path, record: object, code: str) -> Path:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise AdmissionRefusal(code, str(record))
    raw = record.get("path")
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        raise AdmissionRefusal(code, str(raw))
    path = (project / raw).resolve()
    if not path.is_relative_to(project) or path.is_symlink() or not path.is_file():
        raise AdmissionRefusal(code, str(path))
    if record.get("sha256") != _sha(path):
        raise AdmissionRefusal(code, str(path))
    return path


def _record(project: Path, path: Path) -> dict[str, str]:
    return {"path": str(path.resolve().relative_to(project)), "sha256": _sha(path)}


def _selected_steps(context: dict) -> set[str]:
    """Re-evaluate the validated plan; producer_selected is plan state."""
    import flow109
    plan = flow109.resolve_plan(context["features"], context["step_profiles"])
    return {row["id"] for row in plan["rows"]}


def _prepare(project: Path, context: dict) -> tuple[str, dict, dict[str, str]]:
    row = context.get("requested_step")
    if row not in ROWS or context.get("native_step_id") != "flow109." + str(row):
        raise AdmissionRefusal("MACRO_MIXED_CONTEXT_MISMATCH", str(row))
    require_launch_admission(project, "flow109." + row, {"flow109_context": context})
    sources = operation_sources()
    uses = context.get("runtime_tool_uses")
    if uses is not None:
        for use in uses:
            if (use.get("semantics") or {}).get("operation_sources") != sources:
                raise AdmissionRefusal("QUALIFICATION_OPERATION_SOURCE_MISMATCH", use.get("use_id", ""))
    manifest_path = project / f"input/flow109/{row}.json"
    manifest = _read(manifest_path, row + "_INPUT_INVALID")
    if manifest.get("schema") != SCHEMA or manifest.get("step_id") != row:
        raise AdmissionRefusal(row + "_INPUT_INVALID", str(manifest_path))
    inputs = {str(manifest_path): _sha(manifest_path)}
    records = manifest.get("inputs")
    if not isinstance(records, list) or not records:
        raise AdmissionRefusal(row + "_INPUT_POPULATION_ABSENT", str(manifest_path))
    for record in records:
        path = _bound(project, record, row + "_STALE_OR_MISSING_INPUT")
        inputs[str(path)] = record["sha256"]
    selected = _selected_steps(context)
    needs_predecessor = row == "M04" or row == "M03" and "D08" in selected
    if needs_predecessor:
        dep_id = "M03" if row == "M04" else "D08"
        dep = _bound(project, manifest.get("predecessor"), row + "_PREDECESSOR_STALE")
        receipt = _read(dep, row + "_PREDECESSOR_INVALID")
        if (receipt.get("schema") != SCHEMA or receipt.get("step_id") != dep_id
                or receipt.get("component_status") != "PASS"
                or receipt.get("flow109_acceptance") != "NOT_MEASURED"):
            raise AdmissionRefusal(row + "_PREDECESSOR_NOT_COMPONENT_PASS", str(dep))
        if row == "M04" and receipt.get("subject_top") != manifest.get("top"):
            raise AdmissionRefusal("M04_PREDECESSOR_SUBJECT_MISMATCH", str(dep))
        inputs[str(dep)] = _sha(dep)
    return row, manifest, inputs


def _before(project: Path, context: dict, inputs: dict[str, str]) -> None:
    require_launch_admission(project, "flow109." + context["requested_step"],
                             {"flow109_context": context})
    for name, digest in inputs.items():
        path = Path(name)
        if not path.is_file() or path.is_symlink() or _sha(path) != digest:
            raise AdmissionRefusal(context["requested_step"] + "_INPUT_CHANGED", name)


def _d08(project: Path, context: dict, manifest: dict, inputs: dict[str, str], attempt: Path) -> dict:
    _before(project, context, inputs)
    report = ip_check.audit(project)
    write_json(attempt / "ip_integration_check.json", report)
    if report.get("verdict") == "FAIL":
        raise AdmissionRefusal("D08_MACRO_VIEW_SET_INCOMPLETE", "ip_integration_check", status="FAIL")
    if report.get("verdict") not in ("PASS", "PASS_WITH_REVIEW") or not report.get("macros"):
        raise AdmissionRefusal("D08_MACRO_VIEW_POPULATION_UNMEASURED", str(report.get("verdict")))
    return {"macro_view_audit": _record(project, attempt / "ip_integration_check.json"),
            "macro_count": len(report["macros"]), "review_findings": report.get("findings", []),
            "scope": "current LEF/GDS/Liberty view-set component; no chip or timing signoff"}


def _m03(project: Path, context: dict, manifest: dict, inputs: dict[str, str], attempt: Path) -> dict:
    top = manifest.get("top")
    if not isinstance(top, str) or not top:
        raise AdmissionRefusal("M03_TOP_UNBOUND", str(top))
    _before(project, context, inputs)
    native = m1.run(project, top, "host", manifest.get("pdk"),
                    pdk_source="Flow109 M03 manifest")
    receipt = project / "phase3/mixed_signal/m1_merge_receipt.json"
    if native.get("verdict") == "FAIL":
        raise AdmissionRefusal("M03_NATIVE_MERGE_FAIL", str(native), status="FAIL")
    # The legacy M1 owner checks KLayout before it invalidates an earlier
    # receipt.  Therefore file presence alone is not evidence of this call:
    # only the receipt digest returned by the current native invocation may
    # authorize the downstream macro-view consumer.
    returned_receipt_sha = native.get("m1_receipt_sha256")
    if (not receipt.is_file() or receipt.is_symlink()
            or not isinstance(returned_receipt_sha, str)
            or returned_receipt_sha != _sha(receipt)):
        raise AdmissionRefusal("M03_NATIVE_MERGE_NOT_MEASURED", str(native))
    gate_path = attempt / "macro_view_consumer.json"
    _before(project, context, inputs)
    gate = ip_check.audit(project)
    write_json(gate_path, gate)
    if gate.get("verdict") == "FAIL":
        raise AdmissionRefusal("M03_MACRO_VIEW_CONSUMER_FAIL", str(gate), status="FAIL")
    if gate.get("verdict") not in ("PASS", "PASS_WITH_REVIEW") or not gate.get("macros"):
        raise AdmissionRefusal("M03_MACRO_VIEW_CONSUMER_UNMEASURED", str(gate.get("verdict")))
    return {"subject_top": top, "native_merge": _record(project, receipt),
            "macro_view_consumer": _record(project, gate_path),
            "physical_lvs_endpoint": ("PASS" if native.get("verdict") == "PASS" else "NOT_MEASURED"),
            "physical_lvs_reason": native.get("reason"),
            "scope": "actual macro instance merge and current consumer; physical LVS remains endpoint-distinct"}


def _m04(project: Path, context: dict, manifest: dict, inputs: dict[str, str], attempt: Path) -> dict:
    top = manifest.get("top")
    if not isinstance(top, str) or not top:
        raise AdmissionRefusal("M04_TOP_UNBOUND", str(top))
    producer_path = attempt / "producer.json"
    _before(project, context, inputs)
    rc = m2.main([str(project), "--top", top, "--container", "host", "--json", str(producer_path)])
    producer = _read(producer_path, "M04_PRODUCER_INVALID")
    if rc != 0 or producer.get("verdict") != "PASS":
        status = "FAIL" if producer.get("verdict") == "FAIL" else "NOT_MEASURED"
        raise AdmissionRefusal("M04_POWER_DOMAIN_PRODUCER_" + status, str(producer), status=status)
    gates = []
    specs = ((m2, [str(project), "--check-only", "--json", str(attempt / "native_check.json")]),
             (crossing_check, [str(project), "--json", str(attempt / "crossing.json")]),
             (level_check, [str(project), "--json", str(attempt / "level.json")]),
             (isolation_check, [str(project), "--json", str(attempt / "isolation.json")]),
             (signal_crossing_check, [str(project), "--json", str(attempt / "signal_crossing.json")]))
    for module, argv in specs:
        _before(project, context, inputs)
        gate_rc = module.main(argv)
        path = Path(argv[-1])
        gate = _read(path, "M04_CONSUMER_INVALID")
        verdict = gate.get("verdict")
        if verdict is None and "passed" in gate:
            verdict = "PASS" if gate.get("passed") is True else "FAIL"
        if gate_rc != 0 or verdict != "PASS":
            raise AdmissionRefusal("M04_DOWNSTREAM_CONSUMER_FAIL", Path(module.__file__).stem,
                                   status="FAIL")
        gates.append(_record(project, path))
    return {"subject_top": top, "producer": _record(project, producer_path), "consumers": gates,
            "scope": "actual Yosys power-domain connectivity plus existing crossing consumers"}


def execute(project, context):
    project = Path(project).resolve()
    row = str(context.get("requested_step"))
    parent = project / "reports/flow109/attempts"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix=row + "-", dir=parent))
    result = {"schema": SCHEMA, "step_id": row, "native_step_id": "flow109." + row,
              "component_status": "NOT_MEASURED", "flow109_acceptance": "NOT_MEASURED",
              "metric_acceptance_status": "UNIMPLEMENTED", "native_started": False,
              "context_sha256": context.get("context_sha256"),
              "gate_layers": {f"G{i}": "NOT_MEASURED" for i in range(1, 10)}}
    try:
        row, manifest, inputs = _prepare(project, context)
        result["native_started"] = True
        details = {"D08": _d08, "M03": _m03, "M04": _m04}[row](
            project, context, manifest, inputs, attempt)
        _before(project, context, inputs)
        result.update(component_status="PASS", reason=row + "_CURRENT_COMPONENT_MEASURED",
                      inputs=inputs, operation_sources=operation_sources(), **details)
    except AdmissionRefusal as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except Exception as exc:
        result.update(component_status="NOT_MEASURED", reason=row + "_NATIVE_UNAVAILABLE_OR_UNSUPPORTED",
                      detail=f"{type(exc).__name__}: {exc}")
    write_json(attempt / "component.json", result)
    result["receipt"] = _record(project, attempt / "component.json")
    return result
