"""D45 adopted-netlist CDC/RDC adapter over the existing native consumers.

The supported subset is structural crossing/reset analysis plus correlation of
current SDC exceptions. Protocol checks are not applicable to a decoded
single-domain design with no crossings; multi-domain/crossing protocol proof,
reset sequencing and metastability MTBF remain explicitly NOT_MEASURED.
"""
from __future__ import annotations

from dataclasses import asdict
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
import _cdc_netlist as native
import cdc_crossing_check
import sdc_exception_correlation_check

SCHEMA = "vibeic.flow109.netlist-cdc.v1"
COMPLETION_SCHEMA = "vibeic.flow109.default-row-completion.v1"
INPUT = "input/flow109/D45.json"
REQUIRED_COMPLETION_CHECKS = (
    "implemented_crossing_census",
    "new_unexplained_crossings",
    "reset_dependency",
    "exception_reconciliation",
    "protocol_semantics",
)
REQUIRED_COMPLETION_OBLIGATIONS = (
    "netlist_cdc.implemented_crossing_census",
    "netlist_cdc.new_unexplained_crossings",
    "netlist_cdc.exception_reconciliation",
)


class Refusal(RuntimeError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("D45_INPUT_ABSENT", str(path)) from exc
    if not isinstance(value, dict):
        raise Refusal("D45_INPUT_INVALID", str(path))
    return value


def _bound(project, value):
    if not isinstance(value, dict) or not value.get("path") or not value.get("sha256"):
        raise Refusal("D45_INPUT_UNBOUND", str(value))
    path = Path(value["path"])
    path = path if path.is_absolute() else project / path
    if not path.is_file() or _sha(path) != value["sha256"]:
        raise Refusal("D45_INPUT_STALE_OR_MISSING", str(path))
    return path.resolve()


def operation_sources():
    from execution_provider_catalog import source_closure
    files = source_closure({Path(__file__), HERE / "_cdc_netlist.py",
                            HERE / "cdc_crossing_check.py",
                            HERE / "sdc_exception_correlation_check.py"})
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(files)}


def prepare(project, context):
    if context.get("requested_step") != "D45" or context.get("native_step_id") != "flow109.D45":
        raise Refusal("D45_CONTEXT_MISMATCH", "adopted-netlist CDC/RDC component only")
    row = context.get("resolved_row") or {}
    dispatch = ((row.get("profile") or {}).get("dispatch") or {})
    if row.get("id") != "D45" or dispatch.get("adapter") != "flow109_netlist_cdc":
        raise Refusal("D45_CONTEXT_MISMATCH", "source-owned D45 dispatch required")
    manifest = _read(project / INPUT)
    top = manifest.get("top")
    if manifest.get("schema") != SCHEMA or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", str(top or "")):
        raise Refusal("D45_INPUT_INVALID", "schema/top")
    sdcs = manifest.get("sdc")
    if not isinstance(sdcs, list) or not sdcs:
        raise Refusal("D45_SDC_ABSENT", "nonempty current SDC population required")
    paths = {"netlist": _bound(project, manifest.get("adopted_netlist")),
             "sdc": [_bound(project, item) for item in sdcs],
             "sta_config": _bound(project, manifest.get("sta_config")),
             "sta_receipt": _bound(project, manifest.get("sta_receipt"))}
    config, receipt = _read(paths["sta_config"]), _read(paths["sta_receipt"])
    if (receipt.get("sha256", {}).get("config.json") != _sha(paths["sta_config"])
            or receipt.get("input", {}).get("image") != manifest.get("image")):
        raise Refusal("D45_LIBRARY_CLOSURE_STALE", "STA config/receipt/image binding differs")
    corner = config.get("DEFAULT_CORNER")
    if not isinstance(corner, str) or not corner:
        raise Refusal("D45_LIBRARY_CLOSURE_INVALID", "DEFAULT_CORNER absent")
    declared = []
    for role in ("CELL_LIBS", "PAD_LIBS", "EXTRA_LIBS"):
        value = config.get(role) or {}
        if isinstance(value, dict):
            for pattern, group in value.items():
                if (not isinstance(pattern, str) or not isinstance(group, list)
                        or any(not isinstance(item, str) or not item for item in group)):
                    raise Refusal("D45_LIBRARY_CLOSURE_INVALID", role)
                if fnmatch.fnmatch(corner, pattern):
                    declared.extend((role, item) for item in group)
        elif isinstance(value, list):
            if any(not isinstance(item, str) or not item for item in value):
                raise Refusal("D45_LIBRARY_CLOSURE_INVALID", role)
            declared.extend((role, item) for item in value)
        else:
            raise Refusal("D45_LIBRARY_CLOSURE_INVALID", role)
    if config.get("MACROS"):
        raise Refusal("D45_LIBRARY_CLOSURE_UNSUPPORTED",
                      "nonempty MACROS need their declared timing-model closure")
    library_files = manifest.get("library_files")
    required = {item for _role, item in declared}
    if (not required or not isinstance(library_files, dict)
            or set(library_files) != required):
        raise Refusal("D45_LIBRARY_CLOSURE_INCOMPLETE",
                      f"declared={sorted(required)} supplied={sorted(library_files or {})}")
    paths["liberties"] = []
    config_files = receipt.get("input", {}).get("config_files") or {}
    for role, item in declared:
        path = _bound(project, library_files[item])
        if config_files.get(item) != _sha(path):
            raise Refusal("D45_LIBRARY_CLOSURE_STALE", f"{role}: {item}")
        paths["liberties"].append(path)
    if manifest.get("clock_reset_intent") is not None:
        paths["intent"] = _bound(project, manifest["clock_reset_intent"])
    yosys = shutil.which("yosys")
    if not yosys:
        raise Refusal("D45_NATIVE_TOOL_UNAVAILABLE", "yosys")
    inputs = {INPUT: _sha(project / INPUT)}
    for value in paths.values():
        for path in value if isinstance(value, list) else [value]:
            inputs[str(path)] = _sha(path)
    sources = operation_sources()
    return {"manifest": manifest, "paths": paths, "inputs": inputs,
            "sources": sources, "yosys": Path(yosys).resolve(),
            "yosys_sha256": _sha(Path(yosys).resolve())}


def _unchanged(project, prepared):
    if operation_sources() != prepared["sources"]:
        raise Refusal("D45_OPERATION_SOURCE_CHANGED", "source changed before consumer")
    for name, digest in prepared["inputs"].items():
        path = project / name if not Path(name).is_absolute() else Path(name)
        if not path.is_file() or _sha(path) != digest:
            raise Refusal("D45_INPUT_STALE_OR_MISSING", name)
    if _sha(prepared["yosys"]) != prepared["yosys_sha256"]:
        raise Refusal("D45_NATIVE_TOOL_CHANGED", str(prepared["yosys"]))


def _word(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _native_model(project, prepared, attempt):
    output = attempt / "adopted-netlist.json"
    script = attempt / "adopted-netlist.ys"
    script.write_text("\n".join([
        *("read_liberty -ignore_miss_func -ignore_miss_dir " + _word(path)
          for path in prepared["paths"]["liberties"]),
        "read_verilog -sv " + _word(prepared["paths"]["netlist"]),
        "hierarchy -check -top " + prepared["manifest"]["top"],
        "flatten", "proc", "opt_clean", "write_json " + _word(output), "",
    ]))
    _unchanged(project, prepared)
    argv = [str(prepared["yosys"]), "-Q", "-T", "-s", str(script)]
    process = subprocess.run(argv, capture_output=True, text=True)
    log = attempt / "adopted-netlist.yosys.log"
    log.write_text(process.stdout + process.stderr)
    if process.returncode or not output.is_file():
        raise Refusal("D45_NATIVE_MODEL_FAILED", f"yosys rc={process.returncode}; {log}")
    _unchanged(project, prepared)
    model = native.load(output, prepared["manifest"]["top"])
    if not model.flops:
        raise Refusal("D45_ADOPTED_SEQUENTIAL_MODEL_UNSUPPORTED", "native model has zero decoded flops")
    return model, {"invocation": {"argv": argv, "returncode": process.returncode},
                   "script": {"path": str(script), "sha256": _sha(script)},
                   "log": {"path": str(log), "sha256": _sha(log)},
                   "model": {"path": str(output), "sha256": _sha(output)}}


def _stage_consumers(project, prepared, attempt, crossing):
    stage = attempt / "consumer-stage"
    constraints = stage / "phase2/stage2/constraints"
    constraints.mkdir(parents=True)
    copied = {}
    for index, source in enumerate(prepared["paths"]["sdc"]):
        target = constraints / f"{index:02d}-{source.name}"
        shutil.copyfile(source, target)
        copied[str(target.relative_to(project))] = _sha(target)
    intent = prepared["paths"].get("intent")
    if intent:
        target = stage / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
        target.parent.mkdir(parents=True)
        shutil.copyfile(intent, target)
        copied[str(target.relative_to(project))] = _sha(target)
    report = stage / "reports/phase2/cdc/crossing.json"
    report.parent.mkdir(parents=True)
    write_json(report, crossing)
    copied[str(report.relative_to(project))] = _sha(report)
    _unchanged(project, prepared)
    cdc = asdict(cdc_crossing_check.audit_cdc(stage))
    exceptions = sdc_exception_correlation_check.audit(stage)
    return cdc, exceptions, copied


def execute(project, context):
    project = Path(project).resolve()
    attempt = project / "reports/flow109/D45" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {"schema": SCHEMA, "step_id": "D45", "component_status": "NOT_MEASURED",
              "flow109_acceptance": "NOT_MEASURED", "native_started": False,
              "context_sha256": context.get("context_sha256"),
              "scope": "adopted-netlist structural CDC/RDC and current SDC exception correlation"}
    try:
        prepared = prepare(project, context)
        record.update(source_sha256=prepared["sources"], input_sha256=prepared["inputs"],
                      tool={"path": str(prepared["yosys"]),
                            "sha256": prepared["yosys_sha256"]})
        record["native_started"] = True
        model, native_evidence = _native_model(project, prepared, attempt)
        domains = native.clock_domains(model)
        crossings = native.reg_crossing_findings(model)
        reset_meta = {}
        resets = native.reset_dependency_findings(model, metadata=reset_meta)
        crossing_errors = [item for item in crossings if item.get("severity") == "ERROR"]
        crossing_warnings = [item for item in crossings if item.get("severity") != "ERROR"]
        if crossing_errors:
            crossing_report = {"verdict": "FAIL", "front_end": "adopted-netlist",
                               "clocks_found": domains, "crossings": crossings}
        elif len(domains) <= 1:
            crossing_report = {"verdict": "PASS", "front_end": "adopted-netlist",
                               "clocks_found": domains, "crossings": [],
                               "evidence": "single clock domain in current adopted native netlist; no clock-domain crossings exist"}
        else:
            crossing_report = {"verdict": "SKIPPED-CONDITION", "front_end": "adopted-netlist",
                               "clocks_found": domains, "crossings": crossings,
                               "reason": "structural census found no blocking crossing; protocol semantics remain unsupported"}
        cdc_consumer, exception_consumer, staged = _stage_consumers(
            project, prepared, attempt, crossing_report)
        exception_categories = {item.get("category") for item in exception_consumer.get("findings", [])}
        inconsistent = exception_categories & {"SDC_EXCEPTION_UNJUSTIFIED",
            "SDC_EXCEPTION_UNVERIFIABLE", "SDC_EXCEPTION_TOO_BROAD",
            "SDC_MULTICYCLE_SUSPECT", "SDC_EXCEPTION_EVIDENCE_UNREAD"}
        reset_errors = [item for item in resets if item.get("severity") == "ERROR"]
        checks = {
            "implemented_crossing_census": {"status": "FAIL" if crossing_errors else
                "NOT_MEASURED" if crossing_warnings or len(domains) > 1 else "PASS",
                "clock_domains": domains, "findings": crossings},
            "new_unexplained_crossings": {"status": "FAIL" if crossing_errors else
                "NOT_MEASURED" if crossing_warnings or len(domains) > 1 else "PASS",
                "value": len(crossing_errors), "unit": "count"},
            "reset_dependency": {"status": "FAIL" if reset_errors else "PASS",
                                 "findings": resets, "metadata": reset_meta},
            "exception_reconciliation": {"status": "FAIL" if inconsistent else "PASS",
                "categories": sorted(x for x in exception_categories if x),
                "consumer_verdict": exception_consumer.get("verdict")},
            "protocol_semantics": ({"status": "PASS",
                "reason": "D45_PROTOCOL_SEMANTICS_NOT_APPLICABLE_SINGLE_DOMAIN",
                "detail": "one decoded clock domain and no structural crossing requires no crossing protocol"}
                if len(domains) <= 1 and not crossings else
                {"status": "NOT_MEASURED",
                 "reason": "D45_PROTOCOL_SEMANTICS_UNSUPPORTED",
                 "detail": "multi-bit handshake/FIFO correctness, reset sequencing and MTBF need protocol-specific proof"}),
        }
        if not cdc_consumer.get("passed") and not crossing_errors:
            checks["implemented_crossing_census"] = {"status": "FAIL",
                "reason": "D45_CDC_CONSUMER_REFUSED", "consumer": cdc_consumer}
        statuses = [item["status"] for item in checks.values()]
        status = "FAIL" if "FAIL" in statuses else "NOT_MEASURED" if "NOT_MEASURED" in statuses else "PASS"
        reason = ("D45_EXCEPTION_INCONSISTENT" if inconsistent else
                  "D45_CROSSING_UNEXPLAINED" if crossing_errors else
                  "D45_RESET_DEPENDENCY" if reset_errors else
                  "D45_PROTOCOL_SEMANTICS_UNSUPPORTED" if status == "NOT_MEASURED" else None)
        record.update(component_status=status, reason=reason, checks=checks,
                      metrics={"clock_domain_count": len(domains),
                               "decoded_flop_count": len(model.flops),
                               "decoded_async_reset_flop_count": sum(
                                   flop.arst is not None for flop in model.flops),
                               "decoded_sync_reset_flop_count": sum(
                                   flop.srst is not None for flop in model.flops),
                               "new_unexplained_crossings": len(crossing_errors),
                               "exception_finding_count": len(inconsistent)},
                      consumers={"cdc_crossing_check": cdc_consumer,
                                 "sdc_exception_correlation_check": exception_consumer},
                      evidence_sha256={"native": native_evidence, "staged": staged})
    except Refusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, native.Refusal) as exc:
        record.update(component_status="NOT_MEASURED",
                      reason="D45_NATIVE_UNAVAILABLE_OR_UNSUPPORTED", detail=str(exc))
    record["receipt"] = {"path": str((attempt / "component.json").relative_to(project))}
    write_json(attempt / "component.json", record)
    return record


def _completion_refusal(context, code, detail, *, status="NOT_MEASURED"):
    return {
        "schema": COMPLETION_SCHEMA,
        "step_id": "D45",
        "default_row_status": status,
        "completed": False,
        "reason": code,
        "detail": detail,
        "context_sha256": context.get("context_sha256"),
        "supported_scope": (
            "single decoded clock domain with no structural crossing; adopted-netlist "
            "CDC/RDC and current SDC exception correlation"
        ),
        "required_checks": list(REQUIRED_COMPLETION_CHECKS),
        "selected_obligations": list(REQUIRED_COMPLETION_OBLIGATIONS),
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "whole_ic_acceptance": "NOT_MEASURED",
    }


def _current_record(project, record, label):
    if not isinstance(record, dict) or not record.get("path") or not record.get("sha256"):
        raise Refusal("D45_COMPLETION_EVIDENCE_MISSING", label)
    path = Path(record["path"])
    path = path if path.is_absolute() else project / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(project)
    except (OSError, ValueError) as exc:
        raise Refusal("D45_COMPLETION_EVIDENCE_MISSING", label) from exc
    if not resolved.is_file() or _sha(resolved) != record["sha256"]:
        raise Refusal("D45_COMPLETION_EVIDENCE_STALE", label)
    return resolved


def consume_default_row_completion(project, context, component):
    """Consume D45's current native receipt into a bounded Default-row result.

    This is deliberately D45-specific.  It does not grant Flow109 or whole-IC
    acceptance and it does not infer coverage outside the declared single-domain
    supported subset.
    """
    project = Path(project).resolve()
    base = _completion_refusal(context, "D45_COMPLETION_NOT_MEASURED", "not consumed")
    try:
        if (context.get("requested_step") != "D45"
                or context.get("native_step_id") != "flow109.D45"):
            raise Refusal("D45_COMPLETION_CONTEXT_MISMATCH", "D45 caller required")
        row = context.get("resolved_row")
        obligations = row.get("obligations") if isinstance(row, dict) else None
        obligation_ids = [item.get("id") for item in obligations or []
                          if isinstance(item, dict)]
        if tuple(obligation_ids) != REQUIRED_COMPLETION_OBLIGATIONS:
            raise Refusal("D45_COMPLETION_OBLIGATIONS_MISMATCH", str(obligation_ids))
        if not isinstance(component, dict):
            raise Refusal("D45_COMPLETION_RECEIPT_MISSING", "component result absent")
        receipt = component.get("receipt")
        if not isinstance(receipt, dict) or not receipt.get("path"):
            raise Refusal("D45_COMPLETION_RECEIPT_MISSING", "raw component receipt absent")
        raw_path = (project / receipt["path"]).resolve()
        try:
            raw_path.relative_to((project / "reports/flow109/D45").resolve())
        except ValueError as exc:
            raise Refusal("D45_COMPLETION_RECEIPT_INVALID", str(raw_path)) from exc
        if raw_path.name != "component.json" or not raw_path.is_file():
            raise Refusal("D45_COMPLETION_RECEIPT_MISSING", str(raw_path))
        raw = _read(raw_path)
        if raw != component:
            raise Refusal("D45_COMPLETION_RECEIPT_STALE", "caller result differs from raw receipt")
        if (raw.get("schema") != SCHEMA or raw.get("step_id") != "D45"
                or raw.get("context_sha256") != context.get("context_sha256")
                or raw.get("flow109_acceptance") != "NOT_MEASURED"):
            raise Refusal("D45_COMPLETION_RECEIPT_INVALID", "schema/step/context/scope mismatch")

        if raw.get("source_sha256") != operation_sources():
            raise Refusal("D45_COMPLETION_SOURCE_STALE", "operation source closure changed")
        inputs = raw.get("input_sha256")
        if not isinstance(inputs, dict) or not inputs:
            raise Refusal("D45_COMPLETION_INPUTS_MISSING", "bound input population absent")
        for name, expected in inputs.items():
            path = Path(name)
            path = path if path.is_absolute() else project / path
            if not path.is_file() or _sha(path) != expected:
                raise Refusal("D45_COMPLETION_INPUT_STALE", str(name))
        tool = raw.get("tool")
        if not isinstance(tool, dict) or not tool.get("path") or not tool.get("sha256"):
            raise Refusal("D45_COMPLETION_TOOL_MISSING", "Yosys identity absent")
        tool_path = Path(tool["path"]).resolve()
        if (not tool_path.is_file() or _sha(tool_path) != tool["sha256"]
                or not shutil.which("yosys")
                or tool_path != Path(shutil.which("yosys")).resolve()):
            raise Refusal("D45_COMPLETION_TOOL_STALE", str(tool_path))

        evidence = raw.get("evidence_sha256", {}).get("native")
        if not isinstance(evidence, dict):
            raise Refusal("D45_COMPLETION_EVIDENCE_MISSING", "native evidence absent")
        invocation = evidence.get("invocation")
        argv = invocation.get("argv") if isinstance(invocation, dict) else None
        if (not raw.get("native_started") or not isinstance(argv, list) or not argv
                or Path(argv[0]).resolve() != tool_path
                or invocation.get("returncode") != 0):
            raise Refusal("D45_COMPLETION_NATIVE_INVOCATION_INVALID", str(invocation))
        native_records = {}
        for label in ("script", "log", "model"):
            native_records[label] = _current_record(project, evidence.get(label), label)
        staged = raw.get("evidence_sha256", {}).get("staged")
        if not isinstance(staged, dict) or not staged:
            raise Refusal("D45_COMPLETION_EVIDENCE_MISSING", "consumer-stage population absent")
        for name, expected in staged.items():
            path = (project / name).resolve()
            try:
                path.relative_to(project)
            except ValueError as exc:
                raise Refusal("D45_COMPLETION_EVIDENCE_MISSING", name) from exc
            if not path.is_file() or _sha(path) != expected:
                raise Refusal("D45_COMPLETION_EVIDENCE_STALE", name)

        status = raw.get("component_status")
        if status == "FAIL":
            return {**base, "default_row_status": "FAIL",
                    "reason": raw.get("reason") or "D45_NATIVE_COMPONENT_FAILED",
                    "detail": "current native component reported FAIL",
                    "component_receipt": {"path": str(raw_path.relative_to(project)),
                                          "sha256": _sha(raw_path)}}
        if status != "PASS":
            raise Refusal(raw.get("reason") or "D45_COMPLETION_NOT_MEASURED",
                          "native component did not pass")

        checks = raw.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(REQUIRED_COMPLETION_CHECKS):
            raise Refusal("D45_COMPLETION_CHECK_SET_INVALID", str(sorted(checks or {})))
        if any(not isinstance(checks[name], dict) or checks[name].get("status") != "PASS"
               for name in REQUIRED_COMPLETION_CHECKS):
            raise Refusal("D45_COMPLETION_CHECK_FAILED", "required supported check did not pass")
        census = checks["implemented_crossing_census"]
        if census.get("clock_domains") is None or len(census["clock_domains"]) != 1 \
                or census.get("findings") != []:
            raise Refusal("D45_COMPLETION_SCOPE_UNSUPPORTED",
                          "completion requires exactly one decoded domain and no crossing")
        if checks["new_unexplained_crossings"].get("value") != 0:
            raise Refusal("D45_COMPLETION_CHECK_FAILED", "unexplained crossing count is nonzero")
        protocol = checks["protocol_semantics"]
        if protocol.get("reason") != "D45_PROTOCOL_SEMANTICS_NOT_APPLICABLE_SINGLE_DOMAIN":
            raise Refusal("D45_COMPLETION_SCOPE_UNSUPPORTED", "protocol absence is not validated")
        consumers = raw.get("consumers")
        if (not isinstance(consumers, dict)
                or consumers.get("cdc_crossing_check", {}).get("passed") is not True
                or consumers.get("sdc_exception_correlation_check", {}).get("verdict") != "PASS"):
            raise Refusal("D45_COMPLETION_CONSUMER_REFUSED", "current consumer verdict is not PASS")

        return {
            **base,
            "default_row_status": "PASS",
            "completed": True,
            "reason": "D45_SUPPORTED_DEFAULT_ROW_COMPLETE",
            "detail": "all declared D45 supported-subset checks passed current native consumption",
            "component_receipt": {"path": str(raw_path.relative_to(project)),
                                  "sha256": _sha(raw_path)},
            "native_evidence": {name: {"path": str(path.relative_to(project)),
                                       "sha256": _sha(path)}
                                for name, path in native_records.items()},
            "source_sha256": raw["source_sha256"],
            "input_sha256": inputs,
            "tool": tool,
        }
    except Refusal as exc:
        return {**base, "default_row_status": exc.status, "reason": exc.code,
                "detail": str(exc)}
