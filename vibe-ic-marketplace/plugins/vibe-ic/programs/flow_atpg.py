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


def path_delay(project, directory, *, state, config):
    import path_delay_fault_atpg_run as producer
    from lec_post_layout_check import _LIB_CELL_RE
    from sdf_gate_sim import netlist_used_cells

    state, config = state or {}, config or {}
    corner = config.get("DEFAULT_CORNER", "")
    clock = config.get("CLOCK_PORT")
    clocks = [clock] if isinstance(clock, str) else clock or []
    spef = state.get("spef") or {}
    if isinstance(spef, dict):
        spef = next((path for pattern, path in spef.items() if fnmatch.fnmatchcase(corner, pattern)), None)

    def libraries(value):
        groups = [paths for pattern, paths in value.items() if fnmatch.fnmatchcase(corner, pattern)] if isinstance(value, dict) else [value]
        return [str(path) for group in groups for path in (group if isinstance(group, (list, tuple)) else [group]) if path]

    main = libraries(config.get("CELL_LIBS") or config.get("LIB") or [])
    if not state.get("nl") or not state.get("sdc") or not spef or not main or len(clocks) != 1:
        return {"ran": False, "exit_code": None,
                "detail": "Path-delay ATPG needs native NL, SDC, SPEF, one clock and the selected corner's Liberty."}
    used = netlist_used_cells(Path(state["nl"]).read_text())
    extra = libraries(config.get("PAD_LIBS") or []) + libraries(config.get("EXTRA_LIBS") or [])
    selected = main + [path for path in extra if not Path(path).is_file()
                       or used.intersection(_LIB_CELL_RE.findall(Path(path).read_text()))]
    if any(not Path(path).is_file() for path in selected):
        return {"ran": False, "exit_code": None, "detail": "A selected native timing Liberty is missing."}
    relative = lambda path: os.path.relpath(path, project)
    started = time.perf_counter()
    code, data = producer.run_pdf_atpg(project, netlist_rel=relative(state["nl"]),
        cut_rel=relative(directory / "cut_netlist.v"), flat_rel=relative(directory / "flat_core.v"),
        sta_netlist=relative(state["nl"]), sdc=relative(state["sdc"]), spef=relative(spef),
        liberty=main[0], top=config["DESIGN_NAME"], clock=clocks[0], dff_cells=None,
        k=producer.DEFAULT_K, floor=producer.PDF_FLOOR_DEFAULT,
        timing_fraction=producer.TIMING_FRACTION_DEFAULT, pdk_dir=None,
        timing_source={"corner": corner, "liberties": selected})
    report = directory / "path_delay_coverage.json"
    report.write_text(json.dumps(data, indent=2) + "\n")
    canonical = project / "reports/phase2/dft/path_delay_coverage.json"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(report.read_text())
    metrics = {key: data[key] for key in ("pdf_sensitised_coverage_pct", "pdf_robust_coverage_pct",
               "pdf_sensitised_fault_coverage_pct", "graded_paths", "testable_paths", "sensitised_paths",
               "robust_paths", "false_or_held_paths", "at_speed_meaningful_paths") if data.get(key) is not None}
    if data.get("pdf_sensitised_coverage_pct") is not None:
        metrics["path_fault_coverage"] = data["pdf_sensitised_coverage_pct"]
    status = "NOT_MEASURED" if code == 2 or data.get("verdict") in {"NOT_APPLICABLE", "NOT_MEASURED", "BLOCKED"} else "FAIL" if code else "PASS"
    return {"ran": True, "exit_code": code, "metrics": metrics, "reports": [str(report)],
            "tool_seconds": time.perf_counter() - started,
            "native_steps": [{"name": "path_delay_fault_atpg_run", "ran": True, "exit_code": code, "status": status}],
            "detail": f"Native endpoint-anchored path sensitisation at {corner}; "
                      f"at-speed meaningful paths={data.get('at_speed_meaningful_paths', 'NOT_MEASURED')}. "
                      + "; ".join(data.get("reasons", []))}


def small_delay(project, directory, *, config):
    import sdd_atpg_run as producer

    source = project / "reports/phase2/dft/path_delay_coverage.json"
    clock = (config or {}).get("CLOCK_PORT")
    clocks = [clock] if isinstance(clock, str) else clock or []
    if not source.is_file() or len(clocks) != 1:
        return {"ran": False, "exit_code": None,
                "detail": "Small-delay grading needs the native path-delay report and one functional clock."}
    args = SimpleNamespace(clock=clocks[0], top=config["DESIGN_NAME"], dt2_json=str(source),
        dt1_json=None, no_run_dt1=True, margin_fraction=producer.SDD_MARGIN_FRACTION_DEFAULT, margin_ns=None)
    started = time.perf_counter()
    code, data = producer.run_sdd_atpg(project, args, None)
    report = directory / "sdd_coverage.json"
    report.write_text(json.dumps(data, indent=2) + "\n")
    canonical = project / "reports/phase2/dft/sdd_coverage.json"
    canonical.write_text(report.read_text())
    metrics = {key: data[key] for key in ("graded_faults", "strong", "weak", "undetected_at_speed",
               "sdd_binary_strong_coverage_pct", "sdd_slack_weighted_coverage_pct", "margin_ns", "clock_period_ns")
               if data.get(key) is not None}
    if data.get("sdd_slack_weighted_coverage_pct") is not None:
        metrics["sdd_graded_fault_coverage"] = data["sdd_slack_weighted_coverage_pct"]
    status = "NOT_MEASURED" if code == 2 or data.get("verdict") in {"NOT_APPLICABLE", "NOT_MEASURED", "BLOCKED"} else "FAIL" if code else "PASS"
    return {"ran": True, "exit_code": code, "metrics": metrics, "reports": [str(source), str(report)],
            "tool_seconds": time.perf_counter() - started,
            "native_steps": [{"name": "sdd_atpg_run", "ran": True, "exit_code": code, "status": status}],
            "detail": "Native descriptive SDD grade; optional absent DT1 context is not regenerated. "
                      + "; ".join(data.get("reasons", []))}
