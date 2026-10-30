#!/usr/bin/env python3
"""D06 Default adapter for the existing pad/package-interface producers.

This adapter runs the source-owned ``pad_assignment_gen`` front door and then
checks the current ``io_pad_chip_top_gen`` record.  It never substitutes the
post-assembly packaging intake check for pre-tapeout planning.  Missing owner
load, escape, or test-access facts remain NOT_MEASURED. BLOCKING: only the
source-bound bare-die functional interface can complete this row; physical
package and pending post-DFT access retain their unresolved scope.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Mapping
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pad_assignment_gen
import sim_activity_dump

STEP = "D06"
NATIVE_STEP = "flow109.D06"
SCHEMA = "vibeic.flow109.package-plan-component.v1"
IO_REPORT = Path("reports/phase3/io_pad_chip_top.json")
L7_REPORT = Path("phase1/generated_docs/L7_TEST_DEBUG.json")
L8_REPORT = Path("phase1/generated_docs/L8_TIMING_WAVEFORM.json")
L10_REPORT = Path("phase1/generated_docs/L10_TEST_CASES.json")
L20_REPORT = Path("phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json")
TAPEOUT_DECLARATION = Path("input/submission_template/tapeout_declaration.json")
CURRENT_REPAIR = Path("reports/phase3/librelane_postroute_repair.json")


class D06Refusal(ValueError):
    def __init__(self, code: str, detail: str, *, failed: bool = False):
        self.code, self.detail, self.failed = code, detail, failed
        super().__init__(f"{code}: {detail}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operation_sources() -> dict[str, str]:
    paths = (Path(__file__), HERE / "pad_assignment_gen.py",
             HERE / "io_pad_chip_top_gen.py", HERE / "sim_activity_dump.py")
    return {"programs/" + path.name: _sha(path) for path in paths}


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", str(path))
    return value


def _record(project: Path, path: Path) -> dict:
    path = path.resolve(strict=True)
    return {"path": str(path.relative_to(project)), "sha256": _sha(path)}


def _bound_json(project: Path, rel: Path) -> tuple[dict, dict]:
    """Read one canonical evidence file and bind the bytes actually parsed."""
    path = project / rel
    if path.is_symlink():
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", str(rel))
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", str(rel)) from exc
    if not isinstance(value, dict):
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", str(rel))
    return value, {"path": rel.as_posix(),
                   "sha256": hashlib.sha256(raw).hexdigest()}


def _project_path(project: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise D06Refusal("D06_CURRENT_STA_INPUT_INVALID", label)
    path = Path(raw)
    if path.is_absolute():
        try:
            path = project / path.relative_to("/project")
        except ValueError as exc:
            raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", f"{label}: {raw}") from exc
    else:
        path = project / path
    try:
        relative = path.relative_to(project)
    except ValueError as exc:
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", f"{label}: {raw}") from exc
    candidates = (project / relative, *(project / relative).parents)
    if any(item.is_symlink() for item in candidates if item != project.parent):
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", f"{label}: symlink")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise D06Refusal("D06_EVIDENCE_ABSENT_OR_INVALID", f"{label}: {raw}") from exc


def _expanded_outputs(ports: list[dict]) -> list[str]:
    result = []
    for port in ports:
        if port.get("direction") != "output":
            continue
        name, width, packed = port.get("name"), port.get("width"), port.get("packed")
        if not isinstance(name, str) or not isinstance(width, int) or width < 1:
            raise D06Refusal("D06_CURRENT_NETLIST_PORTS_INVALID", str(port))
        if width == 1:
            result.append(name)
            continue
        match = re.fullmatch(r"\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]", str(packed))
        if not match or abs(int(match[1]) - int(match[2])) + 1 != width:
            raise D06Refusal("D06_CURRENT_NETLIST_PORTS_INVALID", str(port))
        left, right = int(match[1]), int(match[2])
        step = -1 if left > right else 1
        result.extend(f"{name}[{index}]" for index in range(left, right + step, step))
    return sorted(result)


def _current_bare_die_load(project: Path, io: Mapping) -> tuple[dict, list[dict]]:
    """Bind the load scene consumed by the current STA state to current IO pads."""
    if not (project / TAPEOUT_DECLARATION).is_file():
        raise D06Refusal("D06_DELIVERY_SCOPE_OWNER_FACT_MISSING",
                         str(TAPEOUT_DECLARATION))
    declaration, declaration_ref = _bound_json(project, TAPEOUT_DECLARATION)
    provenance = (declaration.get("answer_provenance") or {}).get("deliverable")
    if (declaration.get("schema") != "vibe-ic/tapeout_declaration/1"
            or (declaration.get("answers") or {}).get("deliverable") != "DIE"
            or not isinstance(provenance, Mapping)
            or provenance.get("answered_by") != "owner"
            or not isinstance(provenance.get("citation"), str)
            or not provenance["citation"].strip()):
        raise D06Refusal("D06_DELIVERY_SCOPE_OWNER_FACT_MISSING",
                         str(TAPEOUT_DECLARATION))

    repair, repair_ref = _bound_json(project, CURRENT_REPAIR)
    final = repair.get("final")
    if repair.get("verdict") != "PASS" or not isinstance(final, Mapping):
        raise D06Refusal("D06_CURRENT_STA_AUTHORITY_INVALID", str(CURRENT_REPAIR))
    state_path = _project_path(project, final.get("sta_state"), "current STA state")
    expected = final.get("sta_state_sha256")
    if not isinstance(expected, str) or _sha(state_path) != expected:
        raise D06Refusal("D06_CURRENT_STA_AUTHORITY_STALE", str(state_path))
    state = _read(state_path)
    config_path = state_path.parent / "config.json"
    config = _read(config_path)
    sdc_path = _project_path(project, state.get("sdc"), "current STA SDC")
    netlist_path = _project_path(project, state.get("nl"), "current STA netlist")
    top = config.get("DESIGN_NAME")
    if not isinstance(top, str) or not top or config.get("PDK") != _current_pdk(project):
        raise D06Refusal("D06_CURRENT_STA_AUTHORITY_INVALID", str(config_path))

    try:
        ports = sim_activity_dump.module_ports(netlist_path, top)
    except (OSError, ValueError) as exc:
        raise D06Refusal("D06_CURRENT_NETLIST_PORTS_INVALID", str(exc)) from exc
    outputs = _expanded_outputs(ports)
    pad_rows = io.get("pad_instances")
    io_outputs = sorted(str(row.get("port")) for row in pad_rows.values()
                        if isinstance(row, Mapping) and row.get("direction") == "output"
                        and row.get("port")) if isinstance(pad_rows, Mapping) else []
    if not outputs or outputs != io_outputs:
        raise D06Refusal("D06_OUTPUT_LOAD_PAD_COVERAGE_MISMATCH",
                         f"netlist={outputs}, io={io_outputs}")

    sdc = sdc_path.read_text(encoding="utf-8")
    active = "\n".join(line.partition("#")[0] for line in sdc.splitlines())
    loads = re.findall(r"(?m)^\s*set_load\s+([0-9.eE+-]+)\s+\[all_outputs\]\s*$", active)
    delays = re.findall(
        r"(?m)^\s*set_output_delay\s+([0-9.eE+-]+)\s+-clock\s+([A-Za-z_][A-Za-z0-9_$]*)\s+\[all_outputs\]\s*$",
        active)
    if len(loads) != 1 or len(delays) != 1:
        raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_UNRESOLVED",
                         "one formal all-output load and delay are required")
    load, delay = float(loads[0]), float(delays[0][0])
    if not math.isfinite(load) or load <= 0 or not math.isfinite(delay) or delay <= 0:
        raise D06Refusal("D06_BARE_DIE_LOAD_INTERFACE_INVALID", str((load, delay)))

    evidence = [declaration_ref, repair_ref, _record(project, state_path),
                _record(project, config_path), _record(project, sdc_path),
                _record(project, netlist_path)]
    return {
        "scope": "owner-attested bare-die interface; not physical package RLC/escape",
        "deliverable": "DIE", "deliverable_authority": dict(provenance),
        "sta_state": evidence[2], "sdc": evidence[4], "netlist": evidence[5],
        "output_ports": outputs, "output_port_count": len(outputs),
        "capacitance_library_units": load, "output_delay_ns": delay,
        "load_selector": "all_outputs", "physical_package_model_consumed": False,
    }, evidence


def _l20_selected_architecture(l20: Mapping) -> bool:
    fields = l20.get("fields")
    if not isinstance(fields, Mapping):
        raise D06Refusal("D06_DFT_INTENT_UNKNOWN", "L20.fields absent")
    positive = (fields.get("dft_present") is True
                or bool(fields.get("scan_chains")) or bool(fields.get("bist_mbist"))
                or fields.get("jtag_tap") is not None
                or fields.get("test_compression") is not None)
    if positive and fields.get("dft_present") is False:
        raise D06Refusal("D06_DFT_INTENT_CONTRADICTION",
                         "L20 says dft_present=false but carries DFT architecture")
    return positive


def _early_test_access(project: Path, context: Mapping,
                       io: Mapping) -> tuple[dict, list[dict]]:
    """Qualify the early D06 boundary without requiring a post-DFT receipt."""
    evidence = []
    docs = {}
    for name, rel in (("l7", L7_REPORT), ("l8", L8_REPORT),
                      ("l10", L10_REPORT), ("l20", L20_REPORT)):
        docs[name], bound = _bound_json(project, rel)
        evidence.append(bound)
    l7, l8, l10, l20 = (docs[k] for k in ("l7", "l8", "l10", "l20"))
    if (l7.get("schema_version") != 2 or l7.get("doc_class") != "test_debug"
            or l10.get("schema_version") != 2 or l20.get("doc_id") != "L20"):
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", "canonical L7/L10/L20 identity")

    features = context.get("resolved_features") or context.get("features")
    if not isinstance(features, Mapping):
        raise D06Refusal("D06_DFT_INTENT_UNKNOWN", "resolved Flow109 features absent")
    dft_values = (features.get("requires_dft"), features.get("requires_scan"))
    if any(type(value) is not bool for value in dft_values):
        raise D06Refusal("D06_DFT_INTENT_UNKNOWN", "requires_dft/requires_scan unresolved")
    selected = any(dft_values)
    l20_positive = _l20_selected_architecture(l20)
    scan = io.get("scan_interface")
    selected_scan = scan.get("selected_scan_netlist") if isinstance(scan, Mapping) else None
    if selected != l20_positive and (selected or l20_positive):
        raise D06Refusal("D06_DFT_INTENT_CONTRADICTION",
                         f"features selected={selected}, L20 selected={l20_positive}")

    if selected:
        chains = l20["fields"].get("scan_chains")
        required = ("name", "scan_in", "scan_out", "scan_enable")
        if (not isinstance(chains, list) or not chains
                or any(not isinstance(chain, Mapping)
                       or any(not chain.get(key) for key in required)
                       for chain in chains)):
            raise D06Refusal("D06_SELECTED_DFT_ARCHITECTURE_MISSING",
                             "L20 scan chain protocol needs name/in/out/enable")
        return {"mode": "selected_dft_architecture", "scan_chains": len(chains),
                "post_dft_physical_access_pending": selected_scan is not True}, evidence

    if selected_scan is not False:
        raise D06Refusal("D06_DFT_INTENT_CONTRADICTION",
                         "unscanned Flow109 route conflicts with current IO selection")
    l7_cases, l10_cases = l7.get("test_scenarios"), l10.get("test_cases")
    keys = ("name", "kind", "stimulus", "expected")
    if (not isinstance(l7_cases, list) or not isinstance(l10_cases, list)
            or not l7_cases or any(not isinstance(row, Mapping)
                                   for row in l7_cases + l10_cases)):
        raise D06Refusal("D06_FUNCTIONAL_TEST_PLAN_MISMATCH", "L7/L10 cases")
    # The normal L7 owner adds named prose scenarios after the shared table
    # cases; L10 owns the shared cases, not that additional verification prose.
    # Retain and source-bind the extra plan instead of demanding a fabricated
    # L10 executable case for it. Shared case population and values stay exact.
    named = [row for row in l7_cases if row.get("kind") == "named_scenario"]
    shared = [row for row in l7_cases if row.get("kind") != "named_scenario"]
    if any(row.get("extraction_strategy") != "named_scenario_list"
           or any(not isinstance(row.get(key), str) or not row[key].strip()
                  for key in ("name", "stimulus", "expected", "evidence")) for row in named):
        raise D06Refusal("D06_FUNCTIONAL_TEST_PLAN_MISMATCH", "unbound named L7 scenario")
    normalized = lambda rows: [{key: row.get(key) for key in keys} for row in rows]
    if (normalized(shared) != normalized(l10_cases)
            or not any(row.get("kind") == "functional_vector" for row in l10_cases)):
        raise D06Refusal("D06_FUNCTIONAL_TEST_PLAN_MISMATCH", "L7/L10 cases")
    l7_sources = l7.get("source_documents")
    if (not isinstance(l7_sources, list) or not l7_sources
            or any(not isinstance(row.get("evidence"), str)
                   or not any(row["evidence"].startswith(source) for source in l7_sources)
                   for row in shared)
            or not set(l7_sources).issubset(set(l10.get("source_documents") or []))):
        raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", "L7/L10 source documents")

    for row in named:
        sources = [source for source in l7_sources
                   if row["evidence"] == source or row["evidence"] == Path(source).name]
        if len(sources) != 1:
            raise D06Refusal("D06_EVIDENCE_WRONG_SOURCE", "named L7 scenario source")
        source = _project_path(project, sources[0], "named L7 scenario source")
        evidence.append(_record(project, source))

    waveform = l8.get("clock_and_reset_waveform")
    if not isinstance(waveform, Mapping):
        raise D06Refusal("D06_FUNCTIONAL_ACCESS_INCOMPLETE", "clock/reset plan absent")
    clocks = {str(row.get("name")) for row in waveform.get("clocks", [])
              if isinstance(row, Mapping) and row.get("name")}
    resets = {str(row.get("name")) for row in waveform.get("resets", [])
              if isinstance(row, Mapping) and row.get("name")}
    pads = io.get("pad_instances")
    pad_rows = list(pads.values()) if isinstance(pads, Mapping) else []
    input_ports = {str(row.get("port")) for row in pad_rows
                   if isinstance(row, Mapping) and row.get("direction") == "input"}
    output_ports = {str(row.get("port")) for row in pad_rows
                    if isinstance(row, Mapping) and row.get("direction") == "output"}
    stimulus = sorted(input_ports - clocks - resets)
    observe = sorted(output_ports)
    if not clocks or not resets or not clocks.issubset(input_ports) \
            or not resets.issubset(input_ports) or not stimulus or not observe:
        raise D06Refusal("D06_FUNCTIONAL_ACCESS_INCOMPLETE",
                         "clock/reset/stimulus/observe pads are required")
    return {"mode": "functional_unscanned", "functional_cases": len(l10_cases),
            "additional_named_verification_scenarios": [dict(row) for row in named],
            "clock_pads": sorted(clocks), "reset_pads": sorted(resets),
            "stimulus_pads": stimulus, "observe_pads": observe,
            "authority": "resolved Flow109 no-DFT route + matched L7/L10 + native IO map"}, evidence


def _current_pdk(project: Path, *, evidence: list | None = None) -> str:
    """Read PDK from the one current native state owner, not the old IO log."""
    candidates = []
    repair = project / "reports/phase3/librelane_postroute_repair.json"
    if repair.is_file():
        body = _read(repair)
        final = body.get("final")
        raw = final.get("sta_state") if isinstance(final, Mapping) else None
        expected = final.get("sta_state_sha256") if isinstance(final, Mapping) else None
        if body.get("verdict") == "PASS" and isinstance(raw, str) and raw \
                and isinstance(expected, str) and expected:
            state = Path(raw)
            if state.is_absolute():
                try:
                    state = project / state.relative_to("/project")
                except ValueError:
                    state = Path("")
            else:
                state = project / state
            if state.is_file() and _sha(state) == expected:
                config = state.parent / "config.json"
                if config.is_file():
                    pdk = _read(config).get("PDK")
                    if isinstance(pdk, str) and pdk:
                        candidates.append(pdk)
    for rel, key in (("reports/phase3/ir_drop.json", "tool_state"),
                     ("reports/phase3/sta_postpnr_signoff.json", "sta_state")):
        path = project / rel
        if not path.is_file():
            continue
        raw = _read(path).get(key)
        if not isinstance(raw, str) or not raw:
            continue
        state = Path(raw)
        if state.is_absolute():
            parts = state.parts
            matches = [i for i, part in enumerate(parts)
                       if part in ("phase3", "reports", "steps")]
            relocated = [project.joinpath(*parts[i:]) for i in matches]
            present = [item for item in relocated if item.is_file()]
            if len(present) != 1:
                continue
            state = present[0]
        else:
            state = project / state
        config = state.parent / "config.json"
        if config.is_file():
            pdk = _read(config).get("PDK")
            if isinstance(pdk, str) and pdk:
                candidates.append(pdk)
    # D06 precedes STA/IR too: consume the current normal D03 publication,
    # retaining its producer/config/file bindings instead of requiring a later row.
    d03_path = Path("reports/flow109/default_rows/D03.json")
    if (project / d03_path).exists():
        d03, d03_ref = _bound_json(project, d03_path)
        if (d03.get("schema") != "vibeic.flow109.technology-qualification.v1"
                or d03.get("program") != "flow109_technology_qualification"
                or d03.get("step_id") != "D03"
                or d03.get("component_status") != "PASS"
                or d03.get("default_row_status") != "PASS"
                or d03.get("completed") is not True):
            raise D06Refusal("D06_CURRENT_D03_AUTHORITY_INVALID", str(d03_path))
        inputs = d03.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            raise D06Refusal("D06_CURRENT_D03_AUTHORITY_INVALID", "D03 input bindings")
        bound = []
        for item in inputs:
            if (not isinstance(item, Mapping) or not isinstance(item.get("path"), str)
                    or not item["path"] or not isinstance(item.get("sha256"), str)):
                raise D06Refusal("D06_CURRENT_D03_AUTHORITY_INVALID", "D03 input binding")
            path = Path(item["path"])
            if not path.is_absolute():
                path = project / path
            if not path.is_file() or _sha(path) != item["sha256"]:
                raise D06Refusal("D06_CURRENT_D03_AUTHORITY_STALE", str(path))
            bound.append({"path": str(path), "sha256": item["sha256"]})
        hashes = {item["path"]: item["sha256"] for item in bound}
        producer = HERE / "flow109_technology_qualification.py"
        config = project / "phase3/librelane/config.json"
        resolved = project / "reports/flow109/D03/resolved.json"
        if (not any(Path(item["path"]).name == producer.name
                    and item["sha256"] == _sha(producer) for item in bound)
                or not config.is_file() or hashes.get(str(config)) != _sha(config)
                or not resolved.is_file() or hashes.get(str(resolved)) != _sha(resolved)):
            raise D06Refusal("D06_CURRENT_D03_AUTHORITY_INVALID", "D03 producer/config binding")
        pdk = _read(resolved).get("PDK")
        if not isinstance(pdk, str) or not pdk or _read(config).get("PDK") != pdk:
            raise D06Refusal("D06_CURRENT_D03_AUTHORITY_INVALID", "D03 PDK binding")
        candidates.append(pdk)
        if evidence is not None:
            evidence.extend([d03_ref, *bound])
    if len(set(candidates)) != 1:
        raise D06Refusal("D06_CURRENT_PDK_AUTHORITY_UNRESOLVED",
                         f"current PDK candidates: {candidates}")
    return candidates[0]


def execute(project: Path, context: Mapping) -> dict:
    project = Path(project).resolve(strict=True)
    attempt = project / "reports/flow109/D06" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    record = {
        "schema": SCHEMA, "step_id": STEP, "native_step_id": NATIVE_STEP,
        "context_sha256": context.get("context_sha256"),
        "component_status": "NOT_MEASURED", "native_started": False,
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
        "metric_acceptance_status": "IMPLEMENTED_BARE_DIE_NATIVE",
        "delivery_accepted": False,
        "producer": "pad_assignment_gen",
        "consumer": "io_pad_chip_top_gen report + owner fact checks",
        "inputs": [], "checks": [],
    }
    try:
        row = context.get("resolved_row") or {}
        if (context.get("requested_step") != STEP or row.get("id") != STEP
                or context.get("native_step_id") != NATIVE_STEP
                or not context.get("context_sha256")):
            raise D06Refusal("D06_CONTEXT_INVALID", "current D06 context required")
        pdk = _current_pdk(project, evidence=record["inputs"])
        pdk_root = os.environ.get("PDK_ROOT", "/foss/pdks")
        sources = operation_sources()
        record["operation_sources"] = sources
        report_path = attempt / "pad_assignment.json"
        assignment = project / "phase3/stage3/pnr/pad_assignment.json"
        before = _sha(report_path) if report_path.is_file() else None
        rc = pad_assignment_gen.main([
            str(project), "--json", str(report_path), "--out", str(assignment),
            "--pdk-root", pdk_root, "--pdk", pdk,
        ])
        record["native_started"] = report_path.is_file() and _sha(report_path) != before
        producer = _read(report_path)
        if operation_sources() != sources:
            raise D06Refusal("D06_OPERATION_SOURCE_CHANGED", "producer boundary")
        record["producer_result"] = producer
        record["inputs"].append(_record(project, report_path))
        verdict = producer.get("verdict")
        record["checks"].append({"check": "pad_assignment_gen",
                                  "status": ("PASS" if rc == 0 and verdict == "WROTE"
                                             else "FAIL" if rc == 1
                                             else "NOT_MEASURED"),
                                  "verdict": verdict, "rc": rc})
        if rc == 1:
            raise D06Refusal("D06_PAD_ASSIGNMENT_PRODUCER_REFUSED",
                             str(producer.get("reason")), failed=True)
        if rc != 0 or verdict != "WROTE":
            raise D06Refusal("D06_PAD_ASSIGNMENT_OWNER_FACT_MISSING",
                             str(producer.get("reason")))

        io_path = project / IO_REPORT
        io = _read(io_path)
        record["inputs"].append(_record(project, io_path))
        if io.get("program") != "io_pad_chip_top_gen" or io.get("verdict") != "WROTE":
            raise D06Refusal("D06_PAD_PIN_PRODUCER_INVALID", str(IO_REPORT), failed=True)
        if not isinstance(io.get("pad_instances"), dict) or not io["pad_instances"]:
            raise D06Refusal("D06_PAD_PIN_PLAN_EMPTY", str(IO_REPORT), failed=True)
        record["checks"].append({"check": "io_pad_chip_top_gen", "status": "PASS",
                                  "pad_instances": len(io["pad_instances"])})

        test = io.get("test_access")
        if not isinstance(test, Mapping) or not test:
            test, early_inputs = _early_test_access(project, context, io)
            record["inputs"].extend(early_inputs)
        record["checks"].append({"check": "test_access_plan", "status": "PASS",
                                  "detail": dict(test)})

        features = context.get("resolved_features") or context.get("features") or {}
        if features.get("package_interface") is not True:
            raise D06Refusal("D06_PACKAGE_INTERFACE_CONTEXT_INVALID", str(features))
        try:
            load, load_inputs = _current_bare_die_load(project, io)
        except D06Refusal as bare_die_error:
            # A selected physical-package route still needs its real owner model;
            # the generic profile flag is deliberately not package-scope authority.
            declaration = project / TAPEOUT_DECLARATION
            body = _read(declaration) if declaration.is_file() else {}
            authority = (body.get("answer_provenance") or {}).get("deliverable")
            declared = (body.get("answers") or {}).get("deliverable")
            physical_owner_scope = (
                body.get("schema") == "vibe-ic/tapeout_declaration/1"
                and isinstance(declared, str) and declared and declared != "DIE"
                and isinstance(authority, Mapping)
                and authority.get("answered_by") == "owner"
                and isinstance(authority.get("citation"), str)
                and bool(authority["citation"].strip()))
            if physical_owner_scope and bare_die_error.code == "D06_DELIVERY_SCOPE_OWNER_FACT_MISSING":
                model = project / "input/package/package_model.json"
                if not model.is_file():
                    raise D06Refusal("D06_PACKAGE_LOAD_ESCAPE_OWNER_FACT_MISSING", str(model))
                record["inputs"].append(_record(project, model))
                raise D06Refusal("D06_PACKAGE_LOAD_ESCAPE_CONSUMER_UNIMPLEMENTED", str(model))
            raise
        record["inputs"].extend(load_inputs)
        record["checks"].append({"check": "bare_die_external_load_interface",
                                  "status": "PASS", "detail": load,
                                  "profile_package_model_required":
                                      features.get("package_model_required"),
                                  "profile_flag_is_owner_scope_authority": False})
        l1, l1_ref = _bound_json(project, Path("phase1/generated_docs/L1_DATASHEET.json"))
        record["inputs"].append(l1_ref)
        if l1.get("no_package_in_input") is not True or l1.get("package_info") is not None:
            raise D06Refusal("D06_PHYSICAL_PACKAGE_SCOPE_UNRESOLVED",
                             "bare-die metrics require the design's explicit absence of a package")
        if any(_sha(project / item["path"]) != item["sha256"]
               for item in record["inputs"]):
            raise D06Refusal("D06_EVIDENCE_CHANGED_DURING_CONSUMPTION", "input readset")
        # The early functional route owns its own complete L7/L8/L10/L20
        # readset. A late scan record or an arbitrary IO test_access object
        # cannot inherit this functional-only metric completion.
        bound = {item["path"] for item in record["inputs"]}
        if (test.get("mode") != "functional_unscanned"
                or not {str(p) for p in (L7_REPORT, L8_REPORT, L10_REPORT, L20_REPORT)} <= bound):
            raise D06Refusal("D06_TEST_ACCESS_METRIC_SCOPE_UNRESOLVED",
                             "bare-die functional access requires its source-bound early plan")
        record["metrics"] = {
            "pad_bump_interface_constraints": {
                "status": "PASS", "scope": "bare-die pad interface; no bumps",
                "pad_assignment": record["inputs"][0],
                "pad_instances": len(io["pad_instances"])},
            "package_escape_feasibility": {"status": "PASS", **load},
            "test_access_plan": {"status": "PASS", **test},
        }
        record.update(component_status="PASS", default_row_status="PASS",
                      flow109_acceptance="PASS", completed=True,
                      reason="D06_BARE_DIE_NATIVE_METRICS_PASS",
                      scope="bare-die pad, external-load and functional-test-access feasibility",
                      unsupported_scope="physical package RLC/escape/bumps and post-DFT access")
    except D06Refusal as exc:
        record["component_status"] = "FAIL" if exc.failed else "NOT_MEASURED"
        record["reason"] = exc.code
        record["detail"] = exc.detail
    (attempt / "component.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record

