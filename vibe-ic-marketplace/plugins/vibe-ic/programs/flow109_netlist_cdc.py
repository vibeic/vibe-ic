"""Native netlist CDC/RDC and SDC exception correlation.

The caller supplies the netlist, timing libraries and constraints produced by
the tools. Structural observations do not establish protocol or MTBF coverage.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from _atomic_artefact import write_json
import _cdc_netlist as native
import cdc_crossing_check
import sdc_exception_correlation_check

SCHEMA = "vibeic.flow109.netlist-cdc.v1"



class Refusal(RuntimeError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _path(project, value):
    path = Path(value)
    path = path if path.is_absolute() else project / path
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def prepare(project, context):
    project = Path(project).resolve()
    top = context.get("top")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", str(top or "")):
        raise ValueError("The native netlist top module is required")
    paths = {"netlist": _path(project, context["netlist"]),
             "liberties": [_path(project, p) for p in context["liberties"]],
             "sdc": [_path(project, p) for p in context["sdc"]]}
    if not paths["liberties"] or not paths["sdc"]:
        raise ValueError("Native timing libraries and SDC constraints are required")
    if context.get("intent"):
        paths["intent"] = _path(project, context["intent"])
    yosys = shutil.which("yosys")
    if not yosys:
        raise FileNotFoundError("yosys")
    return {"top": top, "paths": paths, "yosys": Path(yosys)}



def _word(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _native_model(project, prepared, attempt):
    output = attempt / "adopted-netlist.json"
    script = attempt / "adopted-netlist.ys"
    script.write_text("\n".join([
        *("read_liberty -ignore_miss_func -ignore_miss_dir " + _word(path)
          for path in prepared["paths"]["liberties"]),
        "read_verilog -sv " + _word(prepared["paths"]["netlist"]),
        "hierarchy -check -top " + prepared["top"],
        "flatten", "proc", "opt_clean", "write_json " + _word(output), "",
    ]))
    argv = [str(prepared["yosys"]), "-Q", "-T", "-s", str(script)]
    process = subprocess.run(argv, capture_output=True, text=True)
    log = attempt / "adopted-netlist.yosys.log"
    log.write_text(process.stdout + process.stderr)
    if process.returncode or not output.is_file():
        raise Refusal("D45_NATIVE_MODEL_FAILED", f"yosys rc={process.returncode}; {log}")
    model = native.load(output, prepared["top"])
    if not model.flops:
        raise Refusal("D45_ADOPTED_SEQUENTIAL_MODEL_UNSUPPORTED", "native model has zero decoded flops")
    return model, {"invocation": {"argv": argv, "returncode": process.returncode},
                   "script": str(script),
                   "log": str(log),
                   "model": str(output)}


def _stage_consumers(project, prepared, attempt, crossing):
    stage = attempt / "consumer-stage"
    constraints = stage / "phase2/stage2/constraints"
    constraints.mkdir(parents=True)
    copied = {}
    for index, source in enumerate(prepared["paths"]["sdc"]):
        target = constraints / f"{index:02d}-{source.name}"
        shutil.copyfile(source, target)
        copied[str(target.relative_to(project))] = str(target)
    intent = prepared["paths"].get("intent")
    if intent:
        target = stage / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
        target.parent.mkdir(parents=True)
        shutil.copyfile(intent, target)
        copied[str(target.relative_to(project))] = str(target)
    report = stage / "reports/phase2/cdc/crossing.json"
    report.parent.mkdir(parents=True)
    write_json(report, crossing)
    copied[str(report.relative_to(project))] = str(report)
    cdc = asdict(cdc_crossing_check.audit_cdc(stage))
    exceptions = sdc_exception_correlation_check.audit(stage)
    return cdc, exceptions, copied


def execute(project, context):
    project = Path(project).resolve()
    attempt = project / "reports/phase2/cdc/native-netlist" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {"schema": SCHEMA, "step_id": "D45", "component_status": "NOT_MEASURED",
              "native_started": False,
              "scope": "adopted-netlist structural CDC/RDC and current SDC exception correlation"}
    try:
        prepared = prepare(project, context)
        record["tool"] = str(prepared["yosys"])
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
                      reports={"native": native_evidence, "staged": staged})
    except Refusal as exc:
        record.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError, native.Refusal) as exc:
        record.update(component_status="NOT_MEASURED",
                      reason="D45_NATIVE_UNAVAILABLE_OR_UNSUPPORTED", detail=str(exc))
    write_json(attempt / "component.json", record)
    return record
