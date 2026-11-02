#!/usr/bin/env python3
"""Run a block's declared nominal bench at every process/temperature coordinate.

Each corner differs from the delivered DUT and the rendered A07 bench only in its
process model section and temperature card. Limits and acceptance stay with callers.
"""
from __future__ import annotations

import itertools
from pathlib import Path
import shlex

import analog_bound_measurements as bound
import analog_incremental_pvt as pvt
import analog_native_sim as sim
import analog_real_corner_sweep as sweep

RESULT = "pvt-studies.json"


def coordinates(declaration):
    """Return (section, temperature) pairs; three process sections times the PVT temperatures."""
    process = pvt._coordinates(list(declaration.get("process_sections") or []))
    return [(section, temperature)
            for section, (_label, temperature, _offset) in itertools.product(process, sweep.PVT_TEMPS)]


def corner_label(section, temperature):
    return section + "_" + str(temperature).replace("-", "m")


def corner_netlist(netlist, sections, section):
    """The delivered DUT text with its one process card moved to `section`."""
    lines, moved = [], 0
    for line in bound.contextual_template(netlist.read_text(), netlist.parent).splitlines():
        tokens = shlex.split(line) if line.strip() and not line.lstrip().startswith("*") else []
        if tokens and tokens[0].casefold() == ".lib" and len(tokens) == 3 and tokens[2] in sections:
            line, moved = ".lib " + tokens[1] + " " + section, moved + 1
        lines.append(line)
    if moved != 1:
        raise ValueError("DECLARED_PVT_PROCESS_CARD_NOT_SINGLE: " + str(moved))
    return "\n".join(lines) + "\n"


def write_corner(project, name, config, destination, sections, section, temperature):
    """Materialize one corner's DUT and bench; the bench is re-rendered from its declaration."""
    netlist = sim._inputs(project, name, config)[0]
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / ("tb_" + name + ".nominal.sp")
    text, views = sim._declared_testbench(project, name, config, destination)
    if text is None:
        raise ValueError("DECLARED_PVT_TESTBENCH_ABSENT: " + name)
    source.write_text(text)
    dut = destination / (name + ".sp")
    dut.write_text(corner_netlist(netlist, sections, section))
    deck = destination / ("tb_" + name + ".sp")
    deck.write_text(pvt._template(source, netlist, dut, temperature))
    return deck, dut, views


def run(project, name, config, declaration, attempt, native):
    """Execute all nine corners and return the row result; never reuses another attempt."""
    pairs = coordinates(declaration)
    sections = list(declaration["process_sections"])
    spec_path = sim._inputs(project, name, config)[2]
    required = sim._source_measurement_coverage(spec_path, [])["required"]
    limits = sim._bounds(spec_path, config, required)
    corners, executions, outputs, inputs, violated = [], [], [], {}, []
    for section, temperature in pairs:
        label = corner_label(section, temperature)
        deck, dut, views = write_corner(project, name, config, attempt / label, sections, section, temperature)
        inputs.update({label + ":" + role: view for role, view in views.items()})
        inputs.update({label + ":" + role: view
                       for role, view in bound.consumed_input_views(project, deck).items()})
        log = attempt / label / "ngspice.log"
        execution = {**native("@ngspice", ["-b", str(deck), "-o", str(log)], cwd=deck.parent, outputs=[str(log)]),
                     "stdout_path": str(log)}
        text = log.read_text(errors="replace") if log.is_file() else ""
        measured = {key.casefold(): value for key, value in sweep.native_meas_rows(text).items()}
        for match in sweep._MEAS_LINE_RE.finditer(text):
            for key, value in sweep._KV_RE.findall(match.group(1)):
                measured.setdefault(key.casefold(), float(value))
        failed = execution.get("returncode") != 0 or any(sweep._scan_analysis_failures(text))
        missing = [key for key in required if key not in measured]
        breach = [key for key in required if key in measured and isinstance(limits.get(key), dict) and (
            limits[key].get("min") is not None and measured[key] < limits[key]["min"]
            or limits[key].get("max") is not None and measured[key] > limits[key]["max"])]
        violated += [label + ":" + key for key in breach]
        state = "FAIL" if failed or breach else "NOT_MEASURED" if missing else "PASS"
        corners.append({"name": label, "process": section, "temperature_c": temperature, "status": state,
                        "measurements": measured, "missing": missing, "deck": str(deck), "netlist": str(dut),
                        "execution": execution})
        executions.append(execution)
        outputs += [str(deck), str(dut), str(log)]
    states = [corner["status"] for corner in corners]
    status = "FAIL" if "FAIL" in states else "PASS" if all(state == "PASS" for state in states) else "NOT_MEASURED"
    detail = ("declared bench measured at every process/temperature corner" if status == "PASS"
              else "declared bench corners: " + ", ".join(violated or
                   [corner["name"] + "=" + corner["status"] for corner in corners if corner["status"] != "PASS"]))
    return {"status": status, "detail": detail, "outputs": outputs, "executions": executions,
            "native_inputs": inputs,
            "metrics": {"stage": "PRE", "kind": "declared_testbench", "required": required, "corners": corners,
                        "total_corners": len(pairs), "corners_executed": len(corners)}}
