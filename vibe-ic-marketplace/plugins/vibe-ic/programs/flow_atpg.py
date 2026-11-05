"""Run the existing ATPG programs on native State views."""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import sys


def transition(project, directory, *, state, config):
    from flow_native_adapters import Commands

    state, config = state or {}, config or {}
    netlist = state.get("nl")
    clock = config.get("CLOCK_PORT")
    clocks = [clock] if isinstance(clock, str) else clock or []
    libraries = [path for pattern, paths in (config.get("LIB") or {}).items()
                 if fnmatch.fnmatchcase(config.get("DEFAULT_CORNER", ""), pattern) for path in paths]
    if not netlist or len(clocks) != 1 or not libraries:
        return {"ran": False, "exit_code": None,
                "detail": "Transition ATPG needs the native netlist, one functional clock and corner Liberty."}
    commands = Commands(directory)
    report = directory / "transition_fault_atpg_run.json"
    relative = lambda path: os.path.relpath(path, project)
    process = commands.run([sys.executable, Path(__file__).with_name("transition_fault_atpg_run.py"),
        project, "--netlist", relative(netlist), "--clock", clocks[0], "--top", config["DESIGN_NAME"],
        "--liberty", libraries[0], "--cut-netlist", relative(directory / "cut_netlist.v"),
        "--json", report])
    data = json.loads(report.read_text()) if report.is_file() else {}
    metrics = {key: data[key] for key in ("tdf_test_coverage_pct", "tdf_fault_coverage_pct",
               "tdf_faults_total", "tdf_faults_sampled", "tdf_faults_graded", "detected", "redundant", "aborted")
               if data.get(key) is not None}
    if data.get("tdf_test_coverage_pct") is not None:
        metrics["early_fault_coverage"] = data["tdf_test_coverage_pct"]
    result = commands.result(metrics, [report] if report.is_file() else [],
        "LOC logic test coverage excludes redundant faults; raw fault coverage is reported separately. "
        + "; ".join(data.get("reasons", [])))
    missing = (process is None or process.returncode == 2 or data.get("verdict") in
               {"NOT_APPLICABLE", "NOT_MEASURED", "ENGINE_LIMITED", "BLOCKED"}
               or process.returncode == 0 and "early_fault_coverage" not in metrics)
    status = "NOT_MEASURED" if missing else "FAIL" if process.returncode else "PASS"
    result["native_steps"] = [{"name": "transition_fault_atpg_run", "ran": process is not None,
                               "exit_code": process.returncode if process else None, "status": status}]
    return result
