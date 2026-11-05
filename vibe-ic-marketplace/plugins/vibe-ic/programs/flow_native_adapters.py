from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


class Commands:
    def __init__(self, directory):
        self.directory = directory
        self.records = []
        self.seconds = 0.0

    def run(self, argv, cwd=None):
        started = time.perf_counter()
        try:
            completed = subprocess.run([str(a) for a in argv], cwd=cwd or self.directory,
                                       capture_output=True, text=True)
        except FileNotFoundError:
            return None
        self.seconds += time.perf_counter() - started
        log = self.directory / f"command_{len(self.records) + 1}.log"
        log.write_text(completed.stdout + completed.stderr)
        self.records.append({"command": list(map(str, argv)), "exit_code": completed.returncode,
                             "log": str(log)})
        return completed

    def result(self, metrics=None, reports=(), detail=""):
        failed = next((r["exit_code"] for r in self.records if r["exit_code"]), 0)
        return {"ran": bool(self.records), "exit_code": failed if self.records else None,
                "metrics": metrics or {}, "reports": [r["log"] for r in self.records] + list(map(str, reports)),
                "tool_seconds": self.seconds, "detail": detail}


def inputs(project, tool):
    from flow_config import resolve_rtl_inputs
    files = [Path(p) if Path(p).is_absolute() else project / p for p in tool.get("rtl", [])]
    top = tool.get("top")
    if files and top:
        return files, top
    produced, declared = resolve_rtl_inputs(project)
    return files or produced, top or declared


def cdc(project, directory, tool, commands):
    import _cdc_netlist as native
    from cdc_async_input_check import is_probable_async_port
    files, top = inputs(project, tool)
    if not files or not top:
        return commands.result(detail="Produced RTL and the declared top module are required.")
    raw, graph = directory / "graph_raw.json", directory / "graph.json"
    script = directory / "elaborate.ys"
    script.write_text(native.yosys_script(files, top, raw) + "\n")
    built = commands.run(["yosys", "-s", script])
    if built is None or built.returncode or not raw.is_file():
        return commands.result(reports=[script], detail="Native CDC elaboration did not produce its graph.")
    script = directory / "normalize.ys"
    script.write_text(native.normalization_script(raw, graph) + "\n")
    normalized = commands.run(["yosys", "-s", script])
    if normalized is None or normalized.returncode or not graph.is_file():
        return commands.result(reports=[raw, script], detail="Native CDC graph normalization did not complete.")
    netlist = native.load(graph, top)
    crossing, reset = {}, {}
    findings = native.judge(netlist, "reg_crossing", metadata=crossing, calibrate=False)
    findings += native.judge(netlist, "async_input", is_probable_async_port, calibrate=False)
    findings += native.judge(netlist, "reset_dependency", metadata=reset, calibrate=False)
    unresolved = [r for r in findings if r.get("rule") == "RESET_ROLE_UNRESOLVED"]
    violations = [r for r in findings if r.get("rule") != "RESET_ROLE_UNRESOLVED"]
    report = directory / "cdc.json"
    report.write_text(json.dumps({"findings": findings, "crossings": crossing, "resets": reset}, indent=2) + "\n")
    metrics = {}
    if crossing.get("traversal_complete") and reset.get("cycle_detection_complete") and not unresolved:
        metrics["unresolved_crossings"] = len(violations)
    return commands.result(metrics, [graph, report],
                           "Decoded structural CDC/RDC; protocol and MTBF require their own native proof.")


def testbenches(project, tool):
    if tool.get("testbenches"):
        return [Path(p) if Path(p).is_absolute() else project / p for p in tool["testbenches"]]
    paths = []
    for name in ("sim", "sim_unit", "sim_full_stack", "sim_professional"):
        root = project / "phase2/stage1" / name
        for pattern in ("tb*.v", "tb*.sv", "tb*.py"):
            paths.extend(p for p in sorted(root.rglob(pattern))
                         if not any(part in {"build", "obj_dir", "sim_build", "cov_build"} for part in p.parts))
    return list(dict.fromkeys(paths))


def simulation(project, directory, tool, commands):
    import verilator_coverage_measure as coverage
    from _sim_results_bridge import parse_junit
    files, top = inputs(project, tool)
    benches = testbenches(project, tool)
    if not files or not benches:
        return commands.result(detail="Produced RTL and a program-generated testbench are required.")
    reports, dats, assertions = [], [], []
    for index, tb in enumerate(benches):
        run = directory / f"testbench_{index + 1}"
        run.mkdir()
        if tb.suffix == ".py":
            if not top or not shutil.which("cocotb-config"):
                return commands.result(reports=reports, detail="Cocotb and the declared top are required.")
            makefile = run / "simulation.mk"
            flags = " ".join(coverage.COVERAGE_INSTRUMENTATION_FLAGS)
            sources = " ".join(str(f.resolve()) for f in files)
            includes = " ".join(dict.fromkeys(str(f.parent.resolve()) for f in files))
            makefile.write_text(
                "SIM = verilator\nTOPLEVEL_LANG = verilog\n"
                f"VERILOG_SOURCES = {sources}\nTOPLEVEL = {top}\nMODULE = {tb.stem}\n"
                f"VERILOG_INCLUDE_DIRS = {includes}\n"
                f"COMPILE_ARGS += --timing {flags} -Wno-fatal -Wno-lint\n"
                "SIM_BUILD = build\nCOCOTB_RESULTS_FILE = results.xml\n"
                f"export PYTHONPATH := {tb.parent.resolve()}:$(PYTHONPATH)\n"
                "include $(shell cocotb-config --makefiles)/Makefile.sim\n")
            completed = commands.run(["make", "-f", makefile, "-j8"], cwd=run)
            report = run / "results.xml"
            if report.is_file():
                summary = parse_junit(report)
                if summary and summary["tests"] > 0 and not summary["skipped"]:
                    assertions.append(summary["failures"] + summary["errors"])
                reports.append(report)
            if completed is None or completed.returncode:
                return commands.result(reports=reports, detail="Native cocotb simulation did not complete.")
            data = run / "coverage.dat"
            if data.is_file():
                dats.append(data)
        else:
            def invoke(argv, cwd):
                completed = commands.run(argv, cwd)
                return ((completed.returncode, completed.stdout, completed.stderr) if completed is not None
                        else (127, "", "Native executable is absent."))
            try:
                data = coverage.verilate_tb_and_run(list(map(str, files)), str(tb),
                    str(run / "build"), str(run), exec_fn=invoke, build_jobs=8)
            except SystemExit as exc:
                return commands.result(reports=reports, detail=str(exc))
            dats.append(Path(data))
        reports.extend(dats[-1:])
    metrics = {}
    if commands.records and not any(r["exit_code"] for r in commands.records):
        metrics["simulation_exit_code"] = 0
    if len(assertions) == len(benches):
        metrics["assertion_failures"] = sum(assertions)
    if dats:
        merged = directory / "coverage.dat"
        completed = commands.run(["verilator_coverage", "--write", merged, *dats])
        if completed is not None and not completed.returncode and merged.is_file():
            parsed = coverage.parse_coverage_dat(str(merged))
            scoped = coverage.scope_totals(parsed, list(map(str, files)))
            if scoped:
                for category, counts in scoped["totals"].items():
                    if counts["total"] > 0:
                        metrics[f"coverage_{category}_pct"] = 100.0 * counts["covered"] / counts["total"]
            reports.append(merged)
    return commands.result(metrics, reports)


def formal(project, directory, tool, commands):
    configured = tool.get("properties", [])
    paths = [Path(p) if Path(p).is_absolute() else project / p for p in configured]
    if not paths:
        paths = sorted((project / "phase2/stage1/formal").glob("*.sby"))
    if not paths or any(not path.is_file() for path in paths):
        return commands.result(detail="The owner program has not emitted a native formal .sby input.")
    statuses, reports = [], []
    for index, source in enumerate(paths):
        listing = commands.run(["sby", "--dumptasks", source], cwd=source.parent)
        if listing is None:
            return commands.result(reports=reports, detail="SymbiYosys is unavailable.")
        if listing.returncode:
            return commands.result(reports=reports, detail="SymbiYosys could not read its task input.")
        for task_index, task in enumerate(listing.stdout.split() or [""]):
            output = directory / f"proof_{index + 1}_{task_index + 1}"
            completed = commands.run(["sby", "-f", "-d", output, source, *([task] if task else [])], cwd=source.parent)
            if completed is None:
                return commands.result(reports=reports, detail="SymbiYosys is unavailable.")
            native = sorted(output.rglob("status"))
            config = output / "config.sby"
            if config.is_file() and re.search(r"^mode\s+prove\s*$", config.read_text(), re.M):
                for report in native:
                    word = report.read_text().strip().split()
                    statuses.append(word[0] if word else "")
            reports.extend(native)
    metrics = {}
    if statuses and all(word in {"PASS", "FAIL"} for word in statuses):
        metrics["unproved_required_properties"] = sum(word == "FAIL" for word in statuses)
    return commands.result(metrics, reports,
        "Native property proofs only. Antecedent reachability is measured only when its cover tasks exist.")


ADAPTERS = {"cdc": cdc, "simulation": simulation, "formal": formal}


def declared_electrical_checks(project):
    """Read explicit final electrical goals that the document emitter retained as prose."""
    project = Path(project)
    documents = sorted(p for p in (project / "input/docs").rglob("*")
                       if p.suffix.lower() in {".md", ".txt"})
    prompt = project / "input/phase1_prompt.md"
    if prompt.is_file():
        documents.append(prompt)
    checks = {}
    for path in documents:
        for line_number, text in enumerate(path.read_text().splitlines(), 1):
            threshold = re.search(r"(?:<=|≤|=|:|\|)\s*\*{0,2}(\d+)\s*(?:viols?|violations?|errors?)\b", text, re.I)
            if threshold:
                for pattern, metric in ((r"\b(?:max\s+)?(?:slew|transition)\b", "design__max_slew_violation__count__corner:*"),
                                        (r"\b(?:max\s+)?cap(?:acitance)?\b", "design__max_cap_violation__count__corner:*"),
                                        (r"\b(?:max\s+)?fanout\b", "design__max_fanout_violation__count__corner:*")):
                    if re.search(pattern, text, re.I):
                        check = {"metric": metric, "operator": "<=", "limit": int(threshold[1]),
                                 "unit": "count", "source": {"file": str(path.relative_to(project)), "line": line_number}}
                        checks[(metric, check["limit"])] = check
            slack = re.search(r"(?:>=|≥)\s*\*{0,2}(-?\d+(?:\.\d+)?)", text)
            if slack and (float(slack[1]) == 0 or re.search(r"\bns\b", text[slack.end():], re.I)):
                for kind in ("setup", "hold"):
                    if re.search(r"\b" + kind + r"\b", text, re.I):
                        metric = f"timing__{kind}__ws__corner:*"
                        check = {"metric": metric, "operator": ">=", "limit": float(slack[1]),
                                 "unit": "ns", "source": {"file": str(path.relative_to(project)), "line": line_number}}
                        checks[(metric, check["limit"])] = check
    return list(checks.values())


def execute(project, directory, tool, route):
    project, directory = Path(project).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="native_", dir=directory))
    commands = Commands(work)
    adapter = ADAPTERS.get(tool.get("adapter"))
    if adapter is None:
        return commands.result(detail=f"No native adapter for {tool.get('adapter')!r}.")
    try:
        return adapter(project, work, tool, commands)
    except (OSError, ValueError, KeyError) as exc:
        return commands.result(detail=str(exc))
