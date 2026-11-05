"""Run functional activity and native vector power on a captured State.

Native compile/simulation/OpenSTA failures are FAIL. Missing inputs, a missing
waveform, unannotated activity or an absent power report are NOT_MEASURED.
This measures the first matching functional scenario at the configured default
corner; it does not replace final post-route power analysis or its limits.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
import re
import shutil


def _paths(value, project, corner):
    if isinstance(value, dict):
        return [path for pattern, group in value.items()
                if fnmatch.fnmatchcase(corner, pattern)
                for path in _paths(group, project, corner)]
    if isinstance(value, (list, tuple)):
        return [path for item in value for path in _paths(item, project, corner)]
    if value is None:
        return []
    path = Path(str(value))
    return [path if path.is_absolute() else project / path]


def _word(value):
    return "{" + str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}") + "}"


def execute(project, directory, tool, route, *, state=None, config=None):
    from flow_native_adapters import Commands, testbenches
    from sdf_gate_sim import netlist_used_cells, verilog_model_closure
    import sim_activity_dump
    from _ppa.power import parse_power_report

    project, directory = Path(project).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config, state = config or {}, state or {}
    commands = Commands(directory)

    def result(status, detail, metrics=None, reports=()):
        value = commands.result(metrics, reports, detail)
        value["native_steps"] = [{"name": Path(row["command"][0]).name,
            "ran": True, "exit_code": row["exit_code"],
            "status": "FAIL" if row["exit_code"] else "PASS"}
            for row in commands.records]
        if status != "PASS":
            value["native_steps"].append({"name": "functional_activity", "ran": False,
                "exit_code": None, "status": status, "detail": detail})
        return value

    try:
        top, corner = config.get("DESIGN_NAME"), config.get("DEFAULT_CORNER", "")
        netlist = _paths(state.get("nl"), project, corner)
        libraries = list(dict.fromkeys(path
            for key in ("CELL_LIBS" if config.get("CELL_LIBS") else "LIB", "PAD_LIBS", "EXTRA_LIBS")
            for path in _paths(config.get(key), project, corner)))
        sdc = _paths(config.get("SIGNOFF_SDC_FILE") or config.get("PNR_SDC_FILE")
                     or state.get("sdc") or config.get("FALLBACK_SDC"), project, corner)
        models = [path for key in ("CELL_VERILOG_MODELS", "PAD_VERILOG_MODELS", "EXTRA_VERILOG_MODELS")
                  for path in _paths(config.get(key), project, corner)]
        if (not top or not corner or len(netlist) != 1 or not libraries or len(sdc) != 1
                or any(not path.is_file() for path in [*netlist, *libraries, *sdc, *models])):
            return result("NOT_MEASURED", "Activity needs the State netlist, configured top/default corner, "
                          "Liberty libraries, SDC and declared functional cell models.")
        benches = [bench for bench in testbenches(project, tool)
                   if bench.is_file() and bench.suffix in {".v", ".sv"}
                   and sim_activity_dump.dut_instance(bench.read_text(), top)]
        if not benches:
            return result("NOT_MEASURED", f"No functional HDL scenario instantiates the State top {top}.")
        absent = [name for name in ("iverilog", "vvp", "sta") if not shutil.which(name)]
        if absent:
            return result("NOT_MEASURED", "Activity executables unavailable: " + ", ".join(absent))
        closure = verilog_model_closure(models, netlist_used_cells(netlist[0].read_text()))
        if closure["unresolved"] or closure["blackboxed"] or closure["clashes"]:
            return result("NOT_MEASURED", "Activity functional cell models are incomplete: " + str(closure))

        def simulate(argv, cwd):
            completed = commands.run(argv, cwd=cwd)
            return completed.returncode, completed.stdout, completed.stderr

        activity = sim_activity_dump.dump([str(netlist[0]), *closure["files"]],
            [str(path) for path in benches], top, directory / "activity", simulate)
        if any(row["exit_code"] for row in commands.records):
            return result("FAIL", activity.get("reason", "Native functional simulation failed."))
        if activity.get("status") != "PASS":
            return result("NOT_MEASURED", activity.get("reason", "No DUT-scoped activity waveform."))
        spef = _paths(state.get("spef"), project, corner)
        if len(spef) > 1 or any(not path.is_file() for path in spef):
            return result("NOT_MEASURED", "The State has no unique readable SPEF for the default corner.")
        script = directory / "power.tcl"
        lines = [*("read_liberty " + _word(path) for path in libraries),
                 "read_verilog " + _word(netlist[0]), "link_design " + _word(top),
                 "read_sdc " + _word(sdc[0]),
                 *("read_spef " + _word(path) for path in spef),
                 "read_vcd -scope " + _word(activity["scope"]) + " " + _word(activity["vcd"]),
                 'puts "POWER_ANALYSIS_MODE: vector_vcd"',
                 "report_activity_annotation -report_annotated", "report_power -digits 9"]
        script.write_text("if {[catch {\n" + "\n".join(lines)
                          + "\n} error]} {puts stderr $error; exit 1}\n")
        completed = commands.run(["sta", "-no_init", "-exit", script])
        text = completed.stdout + completed.stderr
        report = directory / "power.rpt"
        report.write_text(text)
        reports = [script, report, directory / "activity" / sim_activity_dump.MANIFEST]
        if completed.returncode or re.search(r"^Error(?:\s+\d+)?:", text, re.M):
            return result("FAIL", "Native OpenSTA activity/power command failed.", reports=reports)
        parsed = parse_power_report(text)
        annotated = parsed["activity"]["annotated_pin_activities"]
        total = parsed.get("total_row")
        if not annotated or total is None:
            return result("NOT_MEASURED", "OpenSTA left no annotated activity or power Total row.", reports=reports)
        metrics = {"activity__annotated_pin_count": annotated,
                   **{f"power__{category}__corner:{corner}": total[category + "_w"]
                      for category in ("internal", "switching", "leakage", "total")}}
        return result("PASS", f"Vector activity from {activity['tb']} at {corner}; "
                      f"scope {activity['scope']}. Other mission scenarios are not measured; "
                      "final post-route power remains a separate analysis.", metrics, reports)
    except (OSError, ValueError, KeyError) as exc:
        return result("NOT_MEASURED", str(exc))
