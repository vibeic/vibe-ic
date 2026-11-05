"""Native macro view, mixed GDS merge and power-domain engineering tools."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile

from _atomic_artefact import write_json
import ip_integration_check as ip_check
import mixed_signal_top_lvs_run as m1
import mixed_signal_power_domain_run as m2
import power_domain_crossing_check as crossing_check
import level_shifter_required_check as level_check
import isolation_cell_required_check as isolation_check
import power_domain_signal_crossing_check as signal_crossing_check


class NativeError(ValueError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _read(path, code):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise NativeError(code, str(path)) from exc
    if not isinstance(value, dict):
        raise NativeError(code, str(path))
    return value


def _record(project, path):
    return str(Path(path).resolve().relative_to(project))


def _d08(project: Path, context: dict, manifest: dict, inputs: dict[str, str], attempt: Path) -> dict:
    report = ip_check.audit(project)
    write_json(attempt / "ip_integration_check.json", report)
    if report.get("verdict") == "FAIL":
        raise NativeError("D08_MACRO_VIEW_SET_INCOMPLETE", "ip_integration_check", status="FAIL")
    if report.get("verdict") not in ("PASS", "PASS_WITH_REVIEW") or not report.get("macros"):
        raise NativeError("D08_MACRO_VIEW_POPULATION_UNMEASURED", str(report.get("verdict")))
    return {"macro_view_audit": _record(project, attempt / "ip_integration_check.json"),
            "macro_count": len(report["macros"]), "review_findings": report.get("findings", []),
            "scope": "current LEF/GDS/Liberty view-set component; no chip or timing signoff"}


def _m04(project: Path, context: dict, manifest: dict, inputs: dict[str, str], attempt: Path) -> dict:
    top = manifest.get("top")
    if not isinstance(top, str) or not top:
        raise NativeError("M04_TOP_UNBOUND", str(top))
    producer_path = attempt / "producer.json"
    rc = m2.main([str(project), "--top", top, "--container", "host", "--json", str(producer_path)])
    producer = _read(producer_path, "M04_PRODUCER_INVALID")
    if rc != 0 or producer.get("verdict") != "PASS":
        status = "FAIL" if producer.get("verdict") == "FAIL" else "NOT_MEASURED"
        raise NativeError("M04_POWER_DOMAIN_PRODUCER_" + status, str(producer), status=status)
    gates = []
    specs = ((m2, [str(project), "--check-only", "--json", str(attempt / "native_check.json")]),
             (crossing_check, [str(project), "--json", str(attempt / "crossing.json")]),
             (level_check, [str(project), "--json", str(attempt / "level.json")]),
             (isolation_check, [str(project), "--json", str(attempt / "isolation.json")]),
             (signal_crossing_check, [str(project), "--json", str(attempt / "signal_crossing.json")]))
    for module, argv in specs:
        gate_rc = module.main(argv)
        path = Path(argv[-1])
        gate = _read(path, "M04_CONSUMER_INVALID")
        verdict = gate.get("verdict")
        if verdict is None and "passed" in gate:
            verdict = "PASS" if gate.get("passed") is True else "FAIL"
        if gate_rc != 0 or verdict != "PASS":
            raise NativeError("M04_DOWNSTREAM_CONSUMER_FAIL", Path(module.__file__).stem,
                                   status="FAIL")
        gates.append(_record(project, path))
    return {"subject_top": top, "producer": _record(project, producer_path), "consumers": gates,
            "scope": "actual Yosys power-domain connectivity plus existing crossing consumers"}


def _m03(project, context, manifest, inputs, attempt):
    top = manifest.get("top")
    if not isinstance(top, str) or not top:
        raise NativeError("M03_TOP_ABSENT", str(top))
    native = m1.run(project, top, context.get("container", "host"), manifest.get("pdk"),
                    pdk_source="native tool configuration")
    if native.get("verdict") == "FAIL":
        raise NativeError("M03_NATIVE_MERGE_FAIL", str(native), status="FAIL")
    if native.get("verdict") != "PASS":
        raise NativeError("M03_NATIVE_MERGE_NOT_MEASURED", str(native))
    gate = ip_check.audit(project)
    write_json(attempt / "macro_view_consumer.json", gate)
    if gate.get("verdict") == "FAIL":
        raise NativeError("M03_MACRO_VIEW_CONSUMER_FAIL", str(gate), status="FAIL")
    if gate.get("verdict") not in ("PASS", "PASS_WITH_REVIEW") or not gate.get("macros"):
        raise NativeError("M03_MACRO_VIEW_CONSUMER_UNMEASURED", str(gate))
    return {"subject_top": top, "native_merge": native, "macro_view_consumer": gate}


def execute(project, context):
    project = Path(project).resolve()
    row = str(context.get("step_id") or context.get("requested_step") or "")
    methods = {"D08": _d08, "M03": _m03, "M04": _m04}
    if row not in methods:
        raise ValueError("Choose D08 macro views, M03 merge, or M04 power-domain verification")
    parent = project / "reports/native_tools/macro_mixed"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix=row + "-", dir=parent))
    try:
        details = methods[row](project, context, context, {}, attempt)
        result = {"component_status": "PASS", **details}
    except NativeError as exc:
        result = {"component_status": exc.status, "reason": exc.code, "detail": str(exc)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"component_status": "NOT_MEASURED", "reason": str(exc)}
    write_json(attempt / "result.json", result)
    return result
