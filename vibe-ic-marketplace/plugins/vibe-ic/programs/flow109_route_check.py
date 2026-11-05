"""Run LibreLane post-route checks on the selected native routed State.

This adapter does not route, repair, extract, or infer connectivity from DEF
geometry. Its result covers the existing native post-route checkers.  The selected wire reporter/checker also executes, but
an absent PDK threshold is the native checker's explicit NOT_APPLICABLE skip,
never a measured wire-limit PASS.  D42 is not Flow109 or whole-IC acceptance.
``Checker.TrDRC`` exposes a total routed-DRC count, not
marker subtypes, so D42 conservatively requires the total to be zero for its
short/overlap obligation. ``Checker.DisconnectedPins`` measures LibreLane's
critical-pin classification, not arbitrary unused outputs.  Wire length uses
the PDK-resolved threshold and never invents a universal limit.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
import librelane_contract as contract

class RouteCheckError(ValueError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


SCHEMA = "vibeic.flow109.route-check.v1"
STEPS = ["Checker.TrDRC", "Odb.ReportDisconnectedPins",
         "Checker.DisconnectedPins", "Odb.ReportWireLength",
         "Checker.WireLength"]
METRICS = {"route_short_overlap_errors": "route__drc_errors",
           "disconnected_required_pins": "design__critical_disconnected_pin__count"}
CAPABILITY_LIMITS = {
    "route_short_overlap_errors": "LibreLane exposes total routed DRC; zero is conservative",
    "disconnected_required_pins": (
        "LibreLane critical disconnected pins; the native checker owns inactive-cell "
        "classification and D42 does not waive its result"),
    "wire_length": "PDK threshold checker; not foundry signoff DRC",
}


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RouteCheckError("D42_EVIDENCE_ABSENT", str(path)) from exc
    if not isinstance(value, dict):
        raise RouteCheckError("D42_EVIDENCE_INVALID", str(path))
    return value


def _project_path(project: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RouteCheckError("D42_VIEW_UNAVAILABLE", label)
    return contract.project_path(project, value)


def _inside(project: Path, value: object, label: str) -> Path:
    path = _project_path(project, value, label)
    if not path.is_file():
        raise RouteCheckError("D42_SUBJECT_MISSING", f"{label}: {path}")
    return path


def _ref(project: Path, path: Path) -> dict[str, str]:
    return {"path": str(path.resolve().relative_to(project))}


def _adopted_subject(project: Path, state_path=None) -> dict:
    from _prestream_native import final_state
    state_path = Path(state_path) if state_path else final_state(project)
    if state_path is None:
        raise RouteCheckError("D42_ROUTED_STATE_ABSENT", str(project))
    state_path = contract.project_path(project, state_path)
    state = _read(state_path)
    views = {name: _inside(project, state.get(name), f"routed {name}")
             for name in ("odb",)}
    config_path = state_path.parent / "config.json"
    config = _read(config_path)
    pdk = config.get("PDK")
    if (not isinstance(pdk, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", pdk)
            or not config.get("STD_CELL_LIBRARY")):
        raise RouteCheckError("D42_PDK_UNSUPPORTED", str(pdk))
    return {"state": state, "state_path": state_path,
            "views": views, "config": config, "pdk": pdk}


def prepare(project: Path, context: dict) -> dict:
    project = Path(project).resolve()
    subject = _adopted_subject(project, context.get("state_path"))
    image = contract.resolve_image(project)
    pdk_root = contract.resolve_pdk_root(project, subject["pdk"], image=image)
    if not pdk_root:
        raise RouteCheckError("D42_PDK_ROOT_UNAVAILABLE", subject["pdk"])
    return {**subject, "image": image, "pdk_root": Path(pdk_root)}


def _count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RouteCheckError("D42_METRIC_INVALID", label)
    return value


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RouteCheckError("D42_METRIC_INVALID", label) from exc
    if not result.is_finite() or result < 0:
        raise RouteCheckError("D42_METRIC_INVALID", label)
    return result


_RESULT_FIELDS = frozenset({"step", "case", "config", "status", "metrics", "scope", "log"})
_NATIVE_FAILURE_METRICS = {
    "Checker.TrDRC": ("route__drc_errors", "Routing DRC errors"),
    "Checker.DisconnectedPins": (
        "design__critical_disconnected_pin__count", "critical disconnected pins"),
    "Checker.WireLength": ("route__wirelength__max", "Threshold-surpassing long wires"),
}


def _native_checker_failure(step: str, state: dict, config: dict, log: str) -> str | None:
    """Recognise a native checker classification, never an arbitrary rc != 0."""
    metric, description = _NATIVE_FAILURE_METRICS.get(step, (None, None))
    if metric is None:
        return None
    value = (state.get("metrics") or {}).get(metric)
    if value is None:
        missing = f"metric was not found ({metric}): NOT_MEASURED"
        return "MISSING_METRIC" if missing in log else None
    if step == "Checker.WireLength":
        threshold = config.get("WIRE_LENGTH_THRESHOLD")
        if threshold is None or _decimal(value, metric) <= _decimal(threshold, metric):
            return None
    elif _decimal(value, metric) <= 0:
        return None
    pattern = rf"\b{re.escape(str(value))}\s+{re.escape(description)} found\."
    return step if re.search(pattern, log) else None


def _step_result(source: Path | dict, step: str, project: Path) -> dict:
    """Normalize native folders and custom steps to one result shape."""
    if isinstance(source, dict):
        missing = _RESULT_FIELDS - source.keys()
        if (missing or source.get("step") != step
                or source.get("status") not in {"PASS", "FAIL", "NOT_RUN", "NOT_MEASURED"}
                or not isinstance(source.get("metrics"), dict)):
            raise RouteCheckError("D42_STEP_RESULT_INVALID", f"{step}: {sorted(missing)}")
        return dict(source)
    folder = Path(source).resolve()
    relative = str(folder.relative_to(project))
    config_path, log_path = folder / "config.json", folder / "invocation.log"
    base = {"step": step, "case": relative,
            "config": (_ref(project, config_path) if config_path.is_file() else None),
            "metrics": {}, "scope": "librelane_native_step",
            "log": (_ref(project, log_path) if log_path.is_file() else None)}
    if not folder.is_dir() or not log_path.is_file() or not log_path.stat().st_size:
        return {**base, "status": "NOT_RUN"}
    config = _read(config_path)
    if config.get("meta", {}).get("step") != step:
        raise RouteCheckError("D42_STEP_RESULT_INVALID", f"{step}: config identity")
    if not (folder / "state_out.json").is_file():
        state_path = folder / "state_in.json"
        if not state_path.is_file():
            return {**base, "status": "NOT_MEASURED"}
        state = _read(state_path)
        reason = _native_checker_failure(
            step, state, config, log_path.read_text(errors="replace"))
        if reason is None:
            return {**base, "status": "NOT_MEASURED",
                    "metrics": state.get("metrics") or {}}
        return {**base, "status": "FAIL", "metrics": state.get("metrics") or {},
                "reason": reason}
    state = _read(folder / "state_out.json")
    return {**base, "status": "PASS", "metrics": state.get("metrics") or {}}


def _consume(project: Path, step_results: list[dict], configs: dict[str, Path],
             prepared: dict) -> dict:
    if (len(step_results) != len(STEPS)
            or [row.get("step") for row in step_results] != STEPS):
        raise RouteCheckError("D42_NATIVE_OUTPUT_INCOMPLETE", str(len(step_results)))
    failed_rows = [row for row in step_results if row.get("status") == "FAIL"]
    if failed_rows:
        obligations = []
        for row in failed_rows:
            if row["step"] == "Checker.TrDRC":
                obligations.append("route_check.route_short_overlap_errors")
            elif row["step"] == "Checker.DisconnectedPins":
                obligations.append("route_check.disconnected_required_pins")
            elif row["step"] == "Checker.WireLength":
                obligations.append("route_check.wire_length_threshold")
        return {"status": "FAIL", "reason": "D42_NATIVE_CHECK_FAILED",
                "failed_obligations": obligations,
                "measurements": {key: value for row in step_results
                                 for key, value in row.get("metrics", {}).items()},
                "wire_length_check": {"status": "FAIL" if any(
                    row["step"] == "Checker.WireLength" for row in failed_rows)
                    else "NOT_RUN"},
                "native_steps": step_results,
                "outputs": {}}
    if any(row.get("status") != "PASS" for row in step_results):
        states = {row["step"]: row.get("status") for row in step_results}
        raise RouteCheckError("D42_NATIVE_OUTPUT_INCOMPLETE", str(states))
    folders = [project / row["case"] for row in step_results]
    states = {}
    for step, folder in zip(STEPS, folders):
        states[step] = _read(folder / "state_out.json")
    table = folders[1] / "full_disconnected_pins_table.txt"
    wires = folders[3] / "wire_lengths.csv"
    if not table.is_file() or not table.read_text(errors="replace").strip():
        raise RouteCheckError("D42_DISCONNECTED_REPORT_EMPTY", str(table))
    if not wires.is_file() or not wires.read_text(errors="replace").strip():
        raise RouteCheckError("D42_WIRE_REPORT_EMPTY", str(wires))
    route = _count(states["Checker.TrDRC"].get("metrics", {}).get(METRICS[
        "route_short_overlap_errors"]), "route__drc_errors")
    disconnected = _count(states["Checker.DisconnectedPins"].get("metrics", {}).get(METRICS[
        "disconnected_required_pins"]), "design__critical_disconnected_pin__count")
    reported_disconnected = _count(states["Odb.ReportDisconnectedPins"].get(
        "metrics", {}).get("design__disconnected_pin__count"),
        "design__disconnected_pin__count")
    reported_critical = _count(states["Odb.ReportDisconnectedPins"].get(
        "metrics", {}).get(METRICS["disconnected_required_pins"]),
        "reporter design__critical_disconnected_pin__count")
    if reported_critical != disconnected:
        raise RouteCheckError("D42_NATIVE_METRIC_DISAGREEMENT",
                               f"reporter={reported_critical}, checker={disconnected}")
    required_disconnected = disconnected
    wire_max = _decimal(states["Checker.WireLength"].get("metrics", {}).get(
        "route__wirelength__max"), "route__wirelength__max")
    wire_config = _read(configs["Checker.WireLength"])
    threshold_raw = wire_config.get("WIRE_LENGTH_THRESHOLD")
    if threshold_raw is None:
        invocation = folders[4] / "invocation.log"
        invocation_text = " ".join(invocation.read_text(errors="replace").split())
        if ("Threshold for Threshold-surpassing long wires" not in invocation_text
                or "is not set. The checker will be skipped." not in invocation_text):
            raise RouteCheckError("D42_WIRE_CHECK_STATUS_UNBOUND", str(invocation))
        threshold = None
        wire_check = {"status": "NOT_APPLICABLE",
                      "reason": "PDK-resolved WIRE_LENGTH_THRESHOLD is unset; native checker skipped"}
    else:
        threshold = _decimal(threshold_raw, "WIRE_LENGTH_THRESHOLD")
        wire_check = {"status": "FAIL" if wire_max > threshold else "PASS",
                      "threshold_um": str(threshold)}
    measurements = {"route_short_overlap_errors": route,
                    "native_disconnected_pins": reported_disconnected,
                    "native_critical_disconnected_pins": disconnected,
                    "disconnected_required_pins": required_disconnected,
                    "wire_length_max_um": str(wire_max),
                    "wire_length_threshold_um": str(threshold) if threshold is not None else None}
    failed = []
    if route:
        failed.append("route_check.route_short_overlap_errors")
    if required_disconnected:
        failed.append("route_check.disconnected_required_pins")
    if threshold is not None and wire_max > threshold:
        failed.append("route_check.wire_length_threshold")
    outputs = {step: {"folder": str(folder.relative_to(project)),
                      "state": str((folder / "state_out.json").relative_to(project))}
               for step, folder in zip(STEPS, folders)}
    outputs["Odb.ReportDisconnectedPins"]["report"] = str(table.relative_to(project))
    outputs["Odb.ReportWireLength"]["report"] = str(wires.relative_to(project))
    return {"status": "FAIL" if failed else "PASS",
            "reason": "D42_NATIVE_CHECK_FAILED" if failed else "D42_NATIVE_CHECKS_PASS",
            "failed_obligations": failed, "measurements": measurements,
            "wire_length_check": wire_check, "native_steps": step_results, "outputs": outputs}


def execute(project, context):
    project = Path(project).resolve()
    attempt = project / "reports/flow109/D42" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {"schema": SCHEMA, "step_id": "D42", "native_step_id": "flow109.D42",
              "component_status": "NOT_MEASURED", "native_started": False,
              "capability_limits": CAPABILITY_LIMITS}
    try:
        prepared = prepare(project, context)
        result.update(state=str(prepared["state_path"]), pdk=prepared["pdk"],
                      image=prepared["image"])
        overlay = {
            "ERROR_ON_TR_DRC": (True, "D42 requires native routed-DRC failure semantics"),
            "ERROR_ON_DISCONNECTED_PINS": (
                True, "D42 requires native critical-disconnected-pin failure semantics"),
            "ERROR_ON_LONG_WIRE": (True, "D42 requires native PDK wire-limit semantics"),
            "ERROR_ON_MISSING_METRIC": (True, "D42 refuses absent native metrics"),
        }
        configs = contract.resolve_step_configs(
            project, prepared["image"], prepared["pdk"], STEPS,
            pdk_root=prepared["pdk_root"], folder="D42-config-" + attempt.name[:12],
            overlay=overlay)
        result["native_started"] = True
        lane = "D42-route-check-" + attempt.name[:12]
        try:
            folders = contract.run_chain(
                project, prepared["image"],
                [(step, configs[step], prepared["state_path"]) for step in STEPS],
                mounts=[(prepared["pdk_root"], "/pdk")], lane=lane, pdk_root="/pdk")
        except contract.Refusal as exc:
            if exc.code != "LL_STEP_FAILED":
                raise
            root = project / "phase3/librelane" / lane
            folders = [root / f"{index:02d}-{step.lower().replace('.', '-')}"
                       for index, step in enumerate(STEPS, 1)]
        step_results = [_step_result(folder, step, project)
                        for step, folder in zip(STEPS, folders)]
        consumed = _consume(project, step_results, configs, prepared)
        result.update(component_status=consumed["status"],
                      reason=consumed["reason"],
                      failed_obligations=consumed["failed_obligations"],
                      measurements=consumed["measurements"],
                      wire_length_check=consumed["wire_length_check"],
                      native_steps=consumed["native_steps"], outputs=consumed["outputs"])
    except RouteCheckError as exc:
        result.update(component_status="FAIL" if exc.status == "FAIL" else "NOT_MEASURED",
                      reason=exc.code, detail=str(exc))
    except contract.Refusal as exc:
        result.update(reason=exc.code, detail=str(exc))
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        result.update(reason="D42_EXECUTION_INCOMPLETE", detail=f"{type(exc).__name__}: {exc}")
    write_json(attempt / "result.json", result)
    result["report"] = _ref(project, attempt / "result.json")
    return result
