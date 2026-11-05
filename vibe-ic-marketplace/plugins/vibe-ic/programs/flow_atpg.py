"""Run the existing ATPG programs on native State views."""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


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


def stuck_at(project, directory, *, state, config):
    from flow_native_adapters import Commands
    from flow_dft_steps import replay, scan_intent
    from librelane.state import State
    from librelane.steps import StepError, StepException

    state, config = state or {}, config or {}
    clock = config.get("CLOCK_PORT")
    clocks = [clock] if isinstance(clock, str) else clock or []
    models = [Path(str(path)) for path in config.get("CELL_VERILOG_MODELS") or []]
    primitives = [path.parent / "primitives.v" for path in models if (path.parent / "primitives.v").is_file()]
    models = list(dict.fromkeys([*primitives, *models]))
    if (not state.get("nl") or len(clocks) != 1 or not models
            or any(not path.is_file() for path in models)):
        return {"ran": False, "exit_code": None,
                "detail": "Final ATPG needs the native netlist, one functional clock and simulation models."}
    commands = Commands(directory)
    report = directory / "fault_atpg_run.json"
    try:
        _, reset = scan_intent(project)
    except StepException as exc:
        return {"ran": False, "exit_code": None, "detail": str(exc)}
    argv = [sys.executable, Path(__file__).with_name("fault_atpg_run.py"), project,
        "--netlist", os.path.relpath(state["nl"], project), "--clock", clocks[0], "--pdk", "custom",
        "--reset", reset["signal"], "--cell-model-path", " ".join(map(str, models)), "--json", report]
    if reset["shift_value"] == 1:
        argv.append("--reset-active-low")
    process = commands.run(argv)
    data = json.loads(report.read_text()) if report.is_file() else {}
    metrics = {key: data[key] for key in ("coverage_pct", "test_coverage_pct", "faults_total", "faults_detected")
               if data.get(key) is not None}
    if data.get("faults_total", 0) > 0 and data.get("coverage_pct") is not None:
        metrics["final_test_pattern_coverage"] = data["coverage_pct"]
    result = commands.result(metrics, [report] if report.is_file() else [],
        "Raw stuck-at fault coverage is compared with the original target; derived test coverage is separate.")
    missing = process is None or process.returncode == 2
    status = "NOT_MEASURED" if missing else "FAIL" if process.returncode else "PASS"
    result["native_steps"] = [{"name": "fault_atpg_run", "ran": process is not None,
                               "exit_code": process.returncode if process else None, "status": status}]
    before = time.perf_counter()
    try:
        if not state.get("odb") or not Path(str(state["odb"])).is_file():
            raise StepException("Native scan ODB is missing for protocol replay")
        metrics.update(replay(SimpleNamespace(config=config, step_dir=str(directory)),
                              State.load(dict(state)), "test_protocol_errors"))
        protocol = {"name": "Icarus scan protocol", "ran": True, "exit_code": 0, "status": "PASS"}
    except StepException as exc:
        protocol = {"name": "Icarus scan protocol", "ran": False, "exit_code": None,
                    "status": "NOT_MEASURED", "detail": str(exc)}
    except StepError as exc:
        protocol = {"name": "Icarus scan protocol", "ran": True, "exit_code": 1,
                    "status": "FAIL", "detail": str(exc)}
    result["tool_seconds"] += time.perf_counter() - before
    result["native_steps"].append(protocol)
    result["metrics"] = metrics
    result["reports"] += [str(path) for path in directory.glob("scan_*") if path.is_file()]
    return result
