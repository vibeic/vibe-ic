#!/usr/bin/env python3
"""Measure pad-side and bond-terminal geometry from native physical views."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pad_ring
import _submission_template as submission
import _tapeout_declaration as declaration
import pad_bterm_coincidence_check
import pad_side_constraint_check
import librelane_contract as contract

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


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path))


def _native_folder(project):
    from librelane_postroute import STEP23_RECORD
    path = project / STEP23_RECORD
    if not path.is_file():
        return None
    return contract.project_path(project, _read(path)["sta_state"]).parent


def _io_lefs(project, report):
    folder = _native_folder(project)
    config = _read(folder / "config.json") if folder else {}
    values = config.get("PAD_LEFS") or report.get("io_library_lefs")
    if not isinstance(values, list) or not values:
        raise D75Refusal("D75_IO_LIBRARY_UNBOUND", str(IO_REPORT))
    return list(dict.fromkeys(contract.project_path(project, raw) for raw in values))


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
    tech = contract.project_path(project, choices[0])
    inputs = [str(current_def), str(tech)]
    detail = {"source": str(folder / "state_out.json"), "top": config.get("DESIGN_NAME"),
              "def": inputs[0], "tech": inputs[1]}
    result = {"def": current_def, "tech": tech, "inputs": inputs, "detail": detail}
    for key, state_key in (("odb", "odb"), ("netlist", "nl")):
        if state.get(state_key):
            result[key] = contract.project_path(project, state[state_key])
            detail[key] = str(result[key])
    return result


def _check(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def _aggregate(checks):
    statuses = [row.get("status") for row in checks]
    return ("FAIL" if "FAIL" in statuses else "NOT_MEASURED"
            if not statuses or any(s not in ("PASS", "NOT_APPLICABLE") for s in statuses) else "PASS")


def execute(project, context=None, *, def_path=None, tech_lef=None, io_lefs=None):
    """Measure pad-side and signal bond-terminal geometry from native views."""
    project = Path(project).resolve()
    checks = []
    try:
        if not def_path or not tech_lef or not io_lefs:
            raise ValueError("Pad readiness needs native DEF, technology LEF and IO LEFs")
        side = pad_side_constraint_check.check(project, Path(def_path))
        checks.append(_check("pad_side_constraint_check", side.get("verdict", "NOT_MEASURED"), side))
        rc, pads = pad_bterm_coincidence_check.run(
            Path(def_path).read_text(), Path(tech_lef).read_text(), list(map(Path, io_lefs)))
        pad_status = ("FAIL" if pads.get("not_connected_nets") else "NOT_MEASURED"
                      if rc or pads.get("undecided_nets") or not pads.get("connected_nets") else "PASS")
        checks.append(_check("pad_bterm_coincidence_check", pad_status, pads))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks.append(_check("missing_input", "NOT_MEASURED", str(exc)))
    status = _aggregate(checks)
    result = {"schema": SCHEMA, "step_id": STEP, "program": "flow109_package_ready",
              "component_status": status, "checks": checks,
              "native_started": any(row["check"] != "missing_input" for row in checks),
              "reason": "Native pad geometry: " + status,
              "whole_flow_acceptance": "NOT_MEASURED", "delivery_accepted": False}
    return consume_default_row_completion(project, context, result)


def consume_default_row_completion(project, context, component):
    status = _aggregate(component.get("checks") or [])
    if component.get("default_row_status") == "FAIL":
        status = "FAIL"
    return {**component, "default_row_status": status, "flow109_acceptance": status,
            "metric_acceptance_status": status, "completed": status == "PASS"}
