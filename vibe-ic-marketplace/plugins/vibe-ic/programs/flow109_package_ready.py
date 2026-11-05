#!/usr/bin/env python3
"""D75 consumes the run's pad, package, CVC and test interface results."""
from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pad_ring
import _submission_template as submission
import _tapeout_declaration as declaration
import dft_atpg_coverage_check
import pad_bterm_coincidence_check
import pad_side_constraint_check
import perc_signoff_check
import provider_bond_pad_edge
import tapeout_readiness_check
import librelane_contract as contract
from _staged_pdk_tech_lef import discover_staged_tech_lefs, select_staged_tech_lef

SCHEMA = "vibeic.flow109.package-ready.v1"
STEP = "D75"
NATIVE_STEP = "flow109.D75"
DECLARATION = Path(declaration.DECLARATION_REL)
OPERATOR_ANSWERS = Path("input/submission_template/operator_answers.json")
DESIGN_ANSWERS = Path(submission.DESIGN_ANSWERS_REL)
IO_REPORT = Path("reports/phase3/io_pad_chip_top.json")
PAD_DEF = Path(_pad_ring.PADRING_DEF_REL)
PROVIDER_TARGET = Path("input/submission_template/provider_target.json")
D67_REPORT = Path("reports/flow109/components/D67.json")


class D75Refusal(ValueError):
    def __init__(self, code, detail, *, failed=False):
        self.code, self.detail, self.failed = code, detail, failed
        super().__init__(f"{code}: {detail}")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path))


def _record(project, path):
    path = contract.project_path(project, path)
    if not path.is_file():
        raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path))
    return {"path": str(path.relative_to(project)) if path.is_relative_to(project) else str(path),
            "sha256": _sha(path), "bytes": path.stat().st_size}


def operation_sources():
    return {"programs/" + path.name: _sha(path) for path in
            (Path(__file__), Path(provider_bond_pad_edge.__file__),
             Path(pad_bterm_coincidence_check.__file__))}


def _native_folder(project):
    from librelane_postroute import STEP23_RECORD
    path = project / STEP23_RECORD
    if not path.is_file():
        return None
    return contract.project_path(project, _read(path)["sta_state"]).parent


def _pdk_path(project, raw, folder, config):
    path = contract.project_path(project, raw)
    if path.is_file():
        return path
    receipt = folder / "vibeic_receipt.json"
    fingerprint = _read(receipt) if receipt.is_file() else None
    selected = contract.resolve_state_pdk_asset(raw, pdk=config.get("PDK"), fingerprint=fingerprint)
    if selected is None:
        raise D75Refusal("D75_PDK_ASSET_ABSENT", str(raw))
    return selected


def _io_lefs(project, report):
    folder = _native_folder(project)
    config = _read(folder / "config.json") if folder else {}
    values = config.get("PAD_LEFS") or report.get("io_library_lefs")
    if not isinstance(values, list) or not values:
        raise D75Refusal("D75_IO_LIBRARY_UNBOUND", str(IO_REPORT))
    return list(dict.fromkeys(_pdk_path(project, raw, folder, config) if folder
                             else contract.project_path(project, raw) for raw in values))


def _tech_lef(project):
    root = project / "input/pdk"
    selected = select_staged_tech_lef(root, discover_staged_tech_lefs(root))
    if selected is None:
        raise D75Refusal("D75_TECH_LEF_UNBOUND", str(root))
    return selected.path


def _current_native_geometry(project, io_lefs):
    """Use the DEF and technology named by this run's final STA State."""
    folder = _native_folder(project)
    if folder is None:
        return None
    state, config = _read(folder / "state_out.json"), _read(folder / "config.json")
    current_def = contract.project_path(project, state["def"])
    corner = config.get("DEFAULT_CORNER", "")
    choices = [raw for pattern, raw in config.get("TECH_LEFS", {}).items()
               if fnmatch.fnmatch(corner, pattern)]
    if len(choices) != 1:
        raise D75Refusal("D75_TECH_LEF_UNBOUND", str(choices))
    tech = _pdk_path(project, choices[0], folder, config)
    inputs = [_record(project, current_def), _record(project, tech)]
    detail = {"source": str(folder / "state_out.json"), "top": config.get("DESIGN_NAME"),
              "def": inputs[0], "tech": inputs[1]}
    result = {"def": current_def, "tech": tech, "inputs": inputs, "detail": detail}
    for key, state_key in (("odb", "odb"), ("netlist", "nl")):
        if state.get(state_key):
            result[key] = contract.project_path(project, state[state_key])
            detail[key] = _record(project, result[key])
    return result


def _check(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def _aggregate(checks):
    statuses = [row.get("status") for row in checks]
    return ("FAIL" if "FAIL" in statuses else "NOT_MEASURED"
            if not statuses or any(s not in ("PASS", "NOT_APPLICABLE") for s in statuses) else "PASS")


def validate(project, component):
    if component.get("schema") != SCHEMA or component.get("step_id") != STEP:
        raise D75Refusal("D75_COMPONENT_INVALID", "schema/step")
    if component.get("component_status") != _aggregate(component.get("checks") or []):
        raise D75Refusal("D75_COMPONENT_INVALID", "native check statuses disagree")


def execute(project, context):
    project = Path(project).resolve()
    checks, inputs = [], []
    try:
        features = context.get("features") or {}
        doc = _read(project / DECLARATION)
        delivery = declaration.answer(doc, "deliverable")
        if delivery != declaration.DELIVERABLE_DIE:
            raise D75Refusal("D75_DELIVERY_FORM_UNSUPPORTED", str(delivery))
        checks.append(_check("declared_delivery_form", "PASS", delivery))
        io = _read(project / IO_REPORT)
        if io.get("verdict") != "WROTE":
            raise D75Refusal("D75_PAD_INTERFACE_ABSENT", str(IO_REPORT))
        io_lefs = _io_lefs(project, io)
        native = _current_native_geometry(project, io_lefs)
        def_path, tech = ((native["def"], native["tech"]) if native else
                          (project / PAD_DEF, _tech_lef(project)))
        inputs.extend(_record(project, path) for path in (def_path, tech, *io_lefs))
        side = pad_side_constraint_check.check(project, def_path)
        checks.append(_check("pad_side_constraint_check", side.get("verdict", "NOT_MEASURED"), side))
        rc, pads = pad_bterm_coincidence_check.run(def_path.read_text(), tech.read_text(), io_lefs)
        pad_status = ("FAIL" if pads.get("not_connected_nets") else "NOT_MEASURED"
                      if rc or pads.get("undecided_nets") or not pads.get("connected_nets") else "PASS")
        checks.append(_check("pad_bterm_coincidence_check", pad_status, pads))
        slots = list((project / submission.SLOTS_DIR_REL).glob("*.yaml"))
        provider = project / PROVIDER_TARGET
        operator = doc.get("operator_template") or {}
        independent = (not slots and not provider.exists()
                       and isinstance(operator.get("absent_reason"), str)
                       and bool(operator["absent_reason"].strip()))
        if independent:
            checks.append(_check("provider_bond_pad_edge", "NOT_APPLICABLE",
                                 {"contract": str(DECLARATION), "reason": operator["absent_reason"]}))
        else:
            layouts = tapeout_readiness_check.discover_layouts(project)
            if len(layouts) != 1:
                raise D75Refusal("D75_FINAL_GEOMETRY_UNBOUND", str(layouts))
            edge = provider_bond_pad_edge.measure(project, layouts[0], top=io.get("chip_top_module") or "")
            checks.append(_check("provider_bond_pad_edge", edge.get("verdict", "NOT_MEASURED"), edge))
        if features.get("requires_dft"):
            dft = dft_atpg_coverage_check.audit(project)
            checks.append(_check("dft_atpg_coverage_check", dft.get("verdict", "NOT_MEASURED"), dft))
        else:
            checks.append(_check("test_access_applicability", "NOT_APPLICABLE",
                                 "Flow109 manifest features.requires_dft is false"))
        if features.get("requires_perc"):
            path = project / "reports/phase3/perc_equivalent.json"
            perc = _read(path) if path.is_file() else {}
            cvc = perc.get("native_cvc")
            if isinstance(cvc, dict):
                checks.append(_check("perc_signoff_check", cvc.get("native_result", "NOT_MEASURED"), cvc))
            else:
                perc = perc_signoff_check.audit(project)
                checks.append(_check("perc_signoff_check", perc.get("verdict", "NOT_MEASURED"), perc))
        else:
            checks.append(_check("perc_signoff_check", "NOT_APPLICABLE", "Flow109 manifest features.requires_perc is false"))
        if features.get("package_model_required"):
            package = _read(project / D67_REPORT)
            checks.append(_check("package_electrical_feedback", package.get("default_row_status", package.get("component_status", "NOT_MEASURED")), package))
        else:
            checks.append(_check("package_electrical_feedback", "NOT_APPLICABLE", "Flow109 manifest features.package_model_required is false"))
    except (D75Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        checks.append(_check("missing_input", "NOT_MEASURED", str(exc)))
    status = _aggregate(checks)
    result = {"schema": SCHEMA, "step_id": STEP, "program": "flow109_package_ready",
            "context_sha256": context.get("context_sha256"), "component_status": status,
            "checks": checks, "inputs": inputs, "native_started": bool(checks),
            "reason": "D75_PACKAGE_TEST_INTERFACE_" + status,
            "whole_flow_acceptance": "NOT_MEASURED", "delivery_accepted": False}
    return consume_default_row_completion(project, context, result)


def consume_default_row_completion(project, context, component):
    validate(project, component)
    status = _aggregate(component.get("checks") or [])
    if component.get("default_row_status") == "FAIL":
        status = "FAIL"
    return {**component, "default_row_status": status, "flow109_acceptance": status,
            "metric_acceptance_status": status, "completed": status == "PASS"}
