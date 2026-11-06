from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import vibeic_temp as tempfile
import time


def _word(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


class Commands:
    def __init__(self, directory):
        self.directory = directory
        self.records = []
        self.seconds = 0.0

    def run(self, argv, cwd=None, *, input_text=None):
        started = time.perf_counter()
        argv = list(map(str, argv))
        log = self.directory / f"command_{len(self.records) + 1}.log"
        input_stream = tempfile.TemporaryFile() if input_text is not None else None
        try:
            if input_stream is not None:
                input_stream.write(input_text.encode())
                input_stream.seek(0)
            with log.open("wb") as output:
                with subprocess.Popen(argv, cwd=cwd or self.directory, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, stdin=input_stream,
                                      text=True) as process, selectors.DefaultSelector() as selector:
                    captured = {process.stdout: bytearray(), process.stderr: bytearray()}
                    for pipe in captured:
                        selector.register(pipe, selectors.EVENT_READ)
                    while selector.get_map():
                        for key, _ in selector.select():
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            captured[key.fileobj].extend(chunk)
                            output.write(chunk)
                            output.flush()
                    streams = [data.decode(pipe.encoding).replace("\r\n", "\n").replace("\r", "\n")
                               for pipe, data in captured.items()]
                    completed = subprocess.CompletedProcess(argv, process.wait(), *streams)
        except FileNotFoundError:
            log.unlink(missing_ok=True)
            return None
        finally:
            if input_stream is not None:
                input_stream.close()
        self.seconds += time.perf_counter() - started
        self.records.append({"command": argv, "exit_code": completed.returncode,
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


def cdc(project, directory, tool, commands, *, state=None, config=None):
    import _cdc_netlist as native
    from cdc_async_input_check import is_probable_async_port
    implemented = tool.get("adapter") == "implemented_cdc"
    native_top = (config or {}).get("DESIGN_NAME") if implemented else None
    files, top = ([], native_top) if native_top else inputs(project, tool)
    if not top or (not implemented and not files):
        return commands.result(detail="Produced RTL and the declared top module are required.")
    raw, graph = directory / "graph_raw.json", directory / "graph.json"
    script = directory / "elaborate.ys"
    if implemented:
        import fnmatch
        from lec_post_layout_check import _LIB_CELL_RE
        from sdf_gate_sim import missing_empty_cell_stubs, netlist_used_cells
        netlist = state.get("nl") if state is not None else None
        if not netlist or not Path(netlist).is_file():
            return commands.result(detail="Implemented CDC needs the native State netlist and Liberty models.")
        text = Path(netlist).read_text()
        used = netlist_used_cells(text)
        liberty, pad_liberty, functional_liberty = [], set(), set()
        for key in ("CELL_LIBS" if config.get("CELL_LIBS") else "LIB", "PAD_LIBS", "EXTRA_LIBS"):
            libraries = config.get(key) or []
            groups = ([paths for pattern, paths in libraries.items()
                       if fnmatch.fnmatchcase(config.get("DEFAULT_CORNER", ""), pattern)]
                      if isinstance(libraries, dict) else [libraries])
            for paths in groups:
                values = [Path(p) for p in (paths if isinstance(paths, (list, tuple)) else [paths])]
                if key in {"PAD_LIBS", "EXTRA_LIBS"}:
                    values = [path for path in values if not path.is_file()
                              or used.intersection(_LIB_CELL_RE.findall(path.read_text()))]
                liberty.extend(values)
                (pad_liberty if key == "PAD_LIBS" else functional_liberty).update(values)
        liberty = list(dict.fromkeys(liberty))
        pad_liberty.difference_update(functional_liberty)
        if not liberty:
            return commands.result(detail="Implemented CDC needs the native State netlist and Liberty models.")
        defined = {name for path in liberty if path.is_file()
                   for name in _LIB_CELL_RE.findall(path.read_text())}
        stubs = missing_empty_cell_stubs(text, used - defined, "")
        models = []
        if stubs:
            physical = directory / "physical_cells.v"
            physical.write_text("\n".join(f"module {name} (); endmodule" for name in stubs) + "\n")
            models.append("read_verilog -lib " + _word(physical))
        script.write_text("\n".join([
            *["read_liberty" + (" -lib" if path in pad_liberty else "")
              + " -ignore_miss_func -ignore_miss_dir " + _word(path) for path in liberty],
            *models,
            "read_verilog -sv " + _word(netlist), "hierarchy -check -top " + top,
            "flatten", "proc", "opt_clean", "write_json " + _word(raw), ""]))
    else:
        script.write_text(native.yosys_script(files, top, raw) + "\n")
    built = commands.run(["yosys", "-s", script])
    if built is None or built.returncode or not raw.is_file():
        return commands.result(reports=[script], detail="Native CDC elaboration did not produce its graph.")
    script = directory / "normalize.ys"
    script.write_text(native.normalization_script(raw, graph) + "\n")
    normalized = commands.run(["yosys", "-s", script])
    if normalized is None or normalized.returncode or not graph.is_file():
        return commands.result(reports=[raw, script], detail="Native CDC graph normalization did not complete.")
    try:
        netlist = native.load(graph, top)
    except native.Refusal as exc:
        return commands.result(reports=[raw, graph, script], detail=str(exc))
    native._load_latched_clock_gates(netlist)
    crossing, reset = {}, {}
    findings = native.judge(netlist, "reg_crossing", metadata=crossing, calibrate=False)
    findings += native.judge(netlist, "async_input", is_probable_async_port, calibrate=False)
    findings += native.judge(netlist, "reset_dependency", metadata=reset, calibrate=False,
                             require_reset_roles=False)
    unresolved = [r for r in findings if r.get("rule") == "RESET_ROLE_UNRESOLVED"]
    violations = [r for r in findings if r.get("rule") != "RESET_ROLE_UNRESOLVED"]
    report = directory / "cdc.json"
    report.write_text(json.dumps({"findings": findings, "crossings": crossing, "resets": reset}, indent=2) + "\n")
    metrics = {}
    if crossing.get("traversal_complete") and reset.get("cycle_detection_complete") and not unresolved:
        metrics["unresolved_crossings"] = len(violations)
        if tool.get("adapter") == "implemented_cdc":
            metrics["new_unexplained_crossings"] = len(violations)
    return commands.result(metrics, [graph, report],
                           "Decoded structural CDC/RDC; protocol and MTBF require their own native proof.")


def testbenches(project, tool):
    if tool.get("testbenches"):
        return [Path(p) if Path(p).is_absolute() else project / p for p in tool["testbenches"]]
    from testbench_gen import is_unit_tb
    paths = []
    for name in ("sim", "sim_unit", "sim_full_stack", "sim_professional"):
        root = project / "phase2/stage1" / name
        for pattern in ("*.v", "*.sv", "tb*.py"):
            paths.extend(p for p in sorted(root.rglob(pattern))
                         if not any(part in {"build", "obj_dir", "sim_build", "cov_build"} for part in p.parts)
                         and (p.name.startswith("tb") or is_unit_tb(p)))
    return list(dict.fromkeys(paths))


_INCLUDE_RE = re.compile(r'(?<![\w$])`include\s+"([^"]+)"')
_ORACLE_DIR_NAMES = frozenset({"golden", "tb", "dv", "verif"})


def staged_rtl_sources(project: Path) -> list[Path]:
    sources = []
    extensions = (".v", ".sv", ".vh", ".svh")
    base = project / "input/design_src"
    if base.is_dir():
        for extension in extensions:
            sources.extend(path for path in base.rglob(f"*{extension}")
                           if "rtl" in {parent.name for parent in path.parents})
    vendor = project / "input/vendor_rtl"
    if vendor.is_dir():
        for extension in extensions:
            sources.extend(path for path in vendor.rglob(f"*{extension}")
                           if not _ORACLE_DIR_NAMES & {parent.name for parent in path.parents})
    return sorted(set(sources))


def simulation_sources(project, files, top, benches):
    from catalog_glue_closure_resolver import (
        _gather, _macro_body_module_refs, _strip_comments, build_index, resolve_closure,
    )
    from testbench_gen import package_first_order
    from verilator_coverage_measure import _tb_top_module

    files = [path.resolve() for path in files]
    hdl_benches = [path.resolve() for path in benches if path.suffix in (".v", ".sv")]
    sources = _gather(project / "phase2/stage1/rtl")
    for path in [*staged_rtl_sources(project), *files, *hdl_benches]:
        sources[path] = _strip_comments(path.read_text(errors="replace"))
    include_order = {parent: index for index, parent in enumerate(dict.fromkeys(
        path.parent for path in [*benches, *files, *sources]))}
    included_names = {Path(name).name for text in sources.values()
                      for name in _INCLUDE_RE.findall(text)}
    relative_includes = {Path(name).name for text in sources.values()
                         for name in _INCLUDE_RE.findall(text) if Path(name).name != name}
    headers = {}
    for path in sources:
        if ((path.suffix in {".vh", ".svh"} or path.name in included_names)
                and path.name not in relative_includes):
            headers.setdefault(path.name, []).append(path)
    for providers in headers.values():
        selected = min(providers, key=lambda path: include_order[path.parent])
        for path in providers:
            if path != selected:
                del sources[path]
    index = build_index(sources)
    # Selected RTL wins, then staged sources, then supplied dependencies.
    for kind in ("mod_def", "pkg_def", "macro_def"):
        for name, providers in index[kind].items():
            selected = [path for path in providers if path in files]
            index[kind][name] = selected or providers[:1]
    index["macro_refs"] = {name: set().union(*(
        _macro_body_module_refs(sources[path]).get(name, set()) for path in providers))
        for name, providers in index["macro_def"].items()}
    reachable = set()
    for root in [top, *(_tb_top_module(path) for path in hdl_benches)]:
        closure, _ = resolve_closure(root, sources, index)
        reachable.update(closure)
    selected = list(dict.fromkeys([*files, *(path for path in sources
        if path in reachable and path not in hdl_benches)]))
    return (package_first_order([path for path in selected if path.suffix in (".v", ".sv")]),
            list(dict.fromkeys(path.parent for path in [*benches, *selected])))


def cocotb_run(directory, tb, files, top, commands, simulator, include_dirs):
    import verilator_coverage_measure as coverage
    directory.mkdir()
    makefile = directory / "simulation.mk"
    flags = " ".join(coverage.COVERAGE_INSTRUMENTATION_FLAGS)
    includes = " ".join(str(path.resolve()) for path in include_dirs)
    makefile.write_text(
        f"SIM = {simulator}\nTOPLEVEL_LANG = verilog\n"
        f"VERILOG_SOURCES = {' '.join(str(f.resolve()) for f in files)}\n"
        f"TOPLEVEL = {top}\nMODULE = {tb.stem}\nVERILOG_INCLUDE_DIRS = {includes}\n"
        + (f"COMPILE_ARGS += --timing {flags} -Wno-fatal -Wno-lint\n" if simulator == "verilator" else "")
        + "SIM_BUILD = build\nCOCOTB_RESULTS_FILE = results.xml\n"
        f"export PYTHONPATH := {tb.parent.resolve()}:$(PYTHONPATH)\n"
        "include $(shell cocotb-config --makefiles)/Makefile.sim\n")
    return commands.run(["make", "-f", makefile, "-j8"], cwd=directory)


def simulation(project, directory, tool, commands):
    import verilator_coverage_measure as coverage
    from _sim_results_bridge import parse_junit
    from sdf_gate_sim import parse_l10_case_stdout, parse_sim_stdout
    files, top = inputs(project, tool)
    if files:
        from testbench_gen import emit_unit_tbs
        scenarios = {}
        emitted = emit_unit_tbs(project, top=top, report=scenarios, scaffold=False, case_stated=True)
        if emitted == -2 or scenarios.get("arithmetic_scenario_requests"):
            return commands.result(detail="Declared scenario producer needs author input: "
                                   + json.dumps(scenarios))
    benches = testbenches(project, tool)
    if files and emitted > 0 and tool.get("testbenches"):
        from testbench_gen import is_unit_tb
        unit_dir = project / "phase2/stage1/sim/tb"
        benches = list(dict.fromkeys([*benches, *(path for pattern in ("*.v", "*.sv")
            for path in sorted(unit_dir.glob(pattern)) if is_unit_tb(path))]))
    if files and not benches:
        from arith_oracle_tb_gen import generate as arithmetic
        from professional_tb_gen import _detect_ic_class
        arithmetic(project, _detect_ic_class(project))
        benches = testbenches(project, tool)
    producer_report = project / "reports/phase2/gates/professional_tb.json"
    professional = project / "phase2/stage1/sim_professional" / str(top)
    managed = (professional / "verification_plan.json").is_file() and any(
        bench.parent == professional for bench in benches)
    if files and (not benches or managed):
        from professional_tb_gen import generate
        generated = generate(project, rtl=files, top=top)
        producer_report.parent.mkdir(parents=True, exist_ok=True)
        producer_report.write_text(json.dumps({**generated, "status": "INCOMPLETE",
            "reason": generated.get("reason") or "Native functional verification has not completed."}, indent=2) + "\n")
        handoff = generated.get("reference_model_handoff")
        if handoff:
            Path(handoff["artifact_path"]).parent.mkdir(parents=True, exist_ok=True)
            return commands.result(reports=[producer_report], detail=
                "The existing professional testbench producer requires its reference model: "
                + json.dumps(handoff))
        benches = testbenches(project, tool)
    if not files or not benches:
        return commands.result(reports=[producer_report] if producer_report.is_file() else [],
            detail="Produced RTL and a program-generated testbench are required.")
    silicon_files = files
    files, include_dirs = simulation_sources(project, files, top, benches)
    reports, dats, assertions, native_steps = [], [], [], []
    frontend_failures = set()
    coverage_run = None

    def invoke(argv, cwd):
        nonlocal coverage_run
        if argv[0] == "verilator":
            argv = [argv[0], *["-I" + str(path) for path in include_dirs
                              if "-I" + str(path) not in argv], *argv[1:]]
        completed = commands.run(argv, cwd)
        if argv[0] != "verilator":
            coverage_run = completed
        return ((completed.returncode, completed.stdout, completed.stderr) if completed is not None
                else (127, "", "Native executable is absent."))

    for index, tb in enumerate(benches):
        run = directory / f"testbench_{index + 1}"
        run.mkdir()
        failures = None
        coverage_run = None
        simulator = "Icarus"
        frontend_record = len(commands.records)
        if tb.suffix == ".py":
            if not top or not shutil.which("cocotb-config"):
                return commands.result(reports=reports, detail="Cocotb and the declared top are required.")
            functional = cocotb_run(run / "functional", tb, files, top, commands, "icarus", include_dirs)
            report = run / "functional/results.xml"
            summary = parse_junit(report)
            elaborated = (run / "functional/build/sim.vvp").is_file()
            if summary and summary["tests"] > 0 and not summary["skipped"]:
                failures = summary["failures"] + summary["errors"]
            completed = cocotb_run(run / "coverage", tb, files, top, commands, "verilator", include_dirs)
            fallback = parse_junit(run / "coverage/results.xml")
            if not elaborated and fallback and fallback["tests"] > 0:
                simulator, functional = "Verilator", completed
                failures = (fallback["failures"] + fallback["errors"]
                            if not fallback["skipped"] else None)
                frontend_failures.add(frontend_record)
            data = run / "coverage/coverage.dat"
            if report.is_file():
                reports.append(report)
            if (run / "coverage/results.xml").is_file():
                reports.append(run / "coverage/results.xml")
            if data.is_file():
                dats.append(data)
        else:
            executable = run / "functional.vvp"
            compiled = commands.run(["iverilog", "-g2012", "-s", coverage._tb_top_module(tb),
                "-o", executable, *["-I" + str(path) for path in include_dirs], *files, tb])
            elaborated = compiled is not None and compiled.returncode == 0
            functional = (commands.run(["vvp", executable], cwd=tb.parent)
                          if compiled is not None and compiled.returncode == 0 else compiled)
            if functional is not None and compiled is not None and compiled.returncode == 0:
                parsed = parse_l10_case_stdout(functional.stdout + functional.stderr)
                if parsed["verdict"] is None:
                    parsed = parse_sim_stdout(functional.stdout + functional.stderr)
                if parsed["verdict"] is not None and parsed["total"] > 0:
                    failures = parsed["total"] - parsed["passed"]
            try:
                data = coverage.verilate_tb_and_run(list(map(str, files)), str(tb),
                    str(run / "build"), str(run), exec_fn=invoke, build_jobs=8)
                dats.append(Path(data))
                completed = True
            except SystemExit:
                completed = None
            if not elaborated and coverage_run is not None:
                simulator, functional = "Verilator", coverage_run
                frontend_failures.add(frontend_record)
                parsed = parse_l10_case_stdout(functional.stdout + functional.stderr)
                if parsed["verdict"] is None:
                    parsed = parse_sim_stdout(functional.stdout + functional.stderr)
                if parsed["verdict"] is not None and parsed["total"] > 0:
                    failures = parsed["total"] - parsed["passed"]
        if failures is not None:
            assertions.append(failures)
        native_steps.extend([
            {"name": simulator + ".Functional", "ran": functional is not None,
             "exit_code": functional.returncode if functional is not None else None,
             "status": ("FAIL" if functional.returncode or failures
                        else "PASS" if failures == 0 else "NOT_MEASURED") if functional is not None else "NOT_MEASURED"},
            {"name": "Verilator.Coverage", "ran": completed is not None,
             "exit_code": (getattr(completed, "returncode", 0) if completed is not None else None),
             "status": "PASS" if completed is not None and not getattr(completed, "returncode", 0)
                       else "NOT_MEASURED"}])
        reports.extend(dats[-1:])
    metrics = {}
    if commands.records and not any(r["exit_code"] for i, r in enumerate(commands.records)
                                   if i not in frontend_failures):
        metrics["simulation_exit_code"] = 0
    if len(assertions) == len(benches):
        metrics["assertion_failures"] = sum(assertions)
    if dats:
        merged = directory / "coverage.dat"
        completed = commands.run(["verilator_coverage", "--write", merged, *dats])
        if completed is not None and not completed.returncode and merged.is_file():
            parsed = (coverage.parse_coverage_dat(str(merged)) if len(dats) == 1
                      else coverage.union_coverage_dats(list(map(str, dats))))
            line_map, info = coverage.lcov_line_union([str(merged)], str(directory), exec_fn=invoke)
            if line_map is not None:
                parsed["line_union"] = line_map
                reports.append(Path(info))
            scoped = coverage.scope_totals(parsed, list(map(str, silicon_files)))
            if scoped:
                for category, counts in scoped["totals"].items():
                    if (category != "line" or scoped["line_metric"] == "executable_line_union"
                            or (line_map is not None and counts["total"] == 0)):
                        metrics[f"coverage_{category}_points"] = counts["total"]
                        if counts["total"] > 0:
                            metrics[f"coverage_{category}_pct"] = 100.0 * counts["covered"] / counts["total"]
            reports.append(merged)
    result = commands.result(metrics, reports)
    result["exit_code"] = next((r["exit_code"] for i, r in enumerate(commands.records)
                                if i not in frontend_failures and r["exit_code"]),
                               0 if commands.records else None)
    result["native_steps"] = native_steps
    return result


def formal(project, directory, tool, commands):
    from formal_property_run import (
        _ensure_expert_observers_bound, _model_texts, frontend_aborted_the_read, resolve_include_headers,
    )
    from formal_harness_gen import _resolve_top

    authored = {}
    declared_top = _resolve_top([], tool.get("top"), project)
    configured = tool.get("properties", [])
    paths = [Path(p) if Path(p).is_absolute() else project / p for p in configured]
    if not paths:
        paths = sorted((project / "phase2/stage1/formal").glob("*.sby"))
    if not paths:
        from formal_harness_gen import generate
        from formal_property_run import emit_invariant_sby, parse_harness_pragmas
        files, top = inputs(project, tool)
        authored = generate(project=project, top=top, rtl=files)
        report = directory / "formal_authoring.json"
        report.write_text(json.dumps(authored, indent=2) + "\n")
        harness = Path(authored["harness_path"]) if authored.get("harness_path") else None
        if harness and harness.is_file():
            pragmas = parse_harness_pragmas(harness.read_text())
            path = harness.with_suffix(".sby")
            path.write_text(emit_invariant_sby(list(map(str, files)), str(harness),
                authored["harness_module"], pragmas["connects"], pragmas["chparams"],
                tasks=pragmas["tasks"] or None))
            paths = [path]
    if not paths or any(not path.is_file() for path in paths):
        return commands.result(detail="The owner program has not emitted a native formal .sby input.")
    statuses, covers, reports, required, observed, native_steps, scope, proof_scopes = [], [], [], [], [], [], [], []
    frontend_failures = set()
    unmodeled_inputs = set()

    def cover_model(output, key, options, *, inspect_only=False):
        model, cells = output / "model/design.il", output / "model/cover_inputs.json"
        if not model.is_file():
            native_steps.append({"name": key + ".Cover.Input", "ran": False,
                "exit_code": None, "status": "NOT_MEASURED", "detail": "The native formal model is absent."})
            return None
        compiled = commands.run(["yosys", "-Q", "-T", "-p",
            f"read_rtlil {_word(model)}; write_json {_word(cells)}"])
        reports.append(cells)
        if compiled is None or compiled.returncode or not cells.is_file():
            native_steps.append({"name": key + ".Cover.Input", "ran": compiled is not None,
                "exit_code": compiled.returncode if compiled is not None else None, "status": "NOT_MEASURED"})
            return None
        conditional, assertions, explicit, subjects = [], 0, 0, set()
        modules = json.loads(cells.read_text())["modules"]
        missing = []
        for module, body in modules.items():
            for kind in ("anyseq", "anyconst"):
                free = {bit for cell in body.get("cells", {}).values() if cell["type"] == "$" + kind
                        for bit in cell["connections"].get("Y", []) if isinstance(bit, int)}
                if kind == "anyseq":
                    free.update(bit for port in body.get("ports", {}).values() if port["direction"] == "input"
                                for bit in port["bits"])
                for name, wire in body.get("netnames", {}).items():
                    if str(wire.get("attributes", {}).get(kind, 0)).strip("0"):
                        lost = sum(bit not in free for bit in wire["bits"])
                        if lost:
                            missing.append(f"{module}.{name}: {lost}/{len(wire['bits'])} {kind} bits lack native free-input drivers")
        if missing:
            detail = "Native formal model lost declared free inputs: " + "; ".join(missing)
            unmodeled_inputs.add(key)
            scope.append(detail)
            native_steps.append({"name": key + ".Cover.Input", "ran": True,
                "exit_code": compiled.returncode, "status": "NOT_MEASURED", "detail": detail})
            return None
        if inspect_only:
            return 0
        for module, body in modules.items():
            for name, cell in body.get("cells", {}).items():
                if cell["type"] == "$scopeinfo" and "." not in name:
                    subject = cell.get("attributes", {}).get("module")
                    if subject:
                        subjects.add(subject)
                kind = (cell.get("parameters", {}).get("FLAVOR") if cell["type"] == "$check"
                        else cell["type"].removeprefix("$"))
                if kind == "assert":
                    assertions += 1
                    if cell["connections"].get("EN") != ["1"]:
                        conditional.append(module + "/" + name)
                elif kind == "cover":
                    explicit += 1
        proof_scopes.append({"task": key, "harness_modules": sorted(modules), "subjects": sorted(subjects),
            "proves_declared_top": (authored.get("proves_declared_top") is True if authored else
                                    bool(declared_top and declared_top in subjects))})
        scope.append(f"{key}: {assertions} native assertions, {len(conditional)} conditional enables, {explicit} existing covers.")
        if not conditional and not explicit:
            return assertions
        selected, deck = output / "cover_inputs.txt", output / "cover.sby"
        selected.write_text("\n".join(conditional) + "\n")
        native_options = re.sub(r"(?m)^mode[ \t]+\S+[ \t]*$", "mode cover", options)
        native_options = re.sub(r"(?m)^aigsmt[ \t]+[^\n]*\n?", "", native_options)
        deck.write_text("[options]\n" + native_options + "\n[engines]\nsmtbmc yices\n"
            "[script]\nread_rtlil design.il\n"
            + ("select -read cover_inputs.txt\nchformal -assert -coverenable\nselect *\n" if conditional else "")
            + "[files]\ndesign.il " + str(model) + "\ncover_inputs.txt " + str(selected) + "\n")
        destination = output / "cover"
        result = commands.run(["sby", "-f", "-d", destination, deck], cwd=output)
        status_file = destination / "status"
        words = status_file.read_text().split() if status_file.is_file() else []
        status = words[0] if words else ""
        covers.append(status)
        required.append(key + ":cover")
        if status in {"PASS", "FAIL"}:
            observed.append(key + ":cover")
        native_steps.append({"name": key + ".Cover", "ran": result is not None,
            "exit_code": result.returncode if result is not None else None,
            "status": status if status in {"PASS", "FAIL"} else "NOT_MEASURED"})
        reports.extend([cells, selected, deck, *sorted(destination.rglob("status"))])
        return assertions

    for index, source in enumerate(paths):
        model_text = _model_texts(source, source.parent, None)
        _ensure_expert_observers_bound(source, source.parent,
                                      harness_text=model_text)
        native_source = source
        body = source.read_text()
        if "$global_clock" in model_text and not re.search(r"(?m)^(?:\w+:[ \t]*)?multiclock[ \t]+", body):
            native_source = directory / f"native_input_{index + 1}.sby"
            native_source.write_text(body.replace("[options]\n", "[options]\nmulticlock on\n", 1))
            reports.append(native_source)
        listing = commands.run(["sby", "--dumptasks", native_source], cwd=source.parent)
        if listing is None:
            return commands.result(reports=reports, detail="SymbiYosys is unavailable.")
        if listing.returncode:
            result = commands.result(reports=reports, detail="SymbiYosys could not read its task input.")
            result["native_steps"] = [{"name": "SymbiYosys.Input", "ran": True,
                "exit_code": listing.returncode, "status": "NOT_MEASURED"}]
            return result
        for task_index, task in enumerate(listing.stdout.split() or [""]):
            key = f"{source.name}:{task}"
            required.append(key)
            output = directory / f"proof_{index + 1}_{task_index + 1}"
            first_read = len(commands.records)
            completed = commands.run(["sby", "-f", "-d", output, native_source, *([task] if task else [])], cwd=source.parent)
            if completed is None:
                return commands.result(reports=reports, detail="SymbiYosys is unavailable.")
            config = output / "config.sby"
            if frontend_aborted_the_read(completed.stdout + completed.stderr) and config.is_file():
                body = config.read_text()
                original_body = body
                reads = list(re.finditer(r"(?m)^read_verilog[ \t]+-formal[ \t]+-sv[ \t]+([^\n]+)", body))
                converted = None
                read_error = ""
                if len(reads) == 1:
                    arguments = shlex.split(reads[0][1])
                    sources = [output / "src" / path for path in arguments
                               if (output / "src" / path).is_file()]
                    supplied = staged_rtl_sources(project)
                    for header in resolve_include_headers(sources, [output / "src", source.parent,
                            *(path.parent for path in sources), *(path.parent for path in supplied)]):
                        destination = output / "src" / header.name
                        if not destination.exists():
                            shutil.copyfile(header, destination)
                            reports.append(destination)
                    argv = ["sv2v", "--exclude=Assert", "--exclude=SeverityTask",
                            "-DFORMAL", "-DYOSYS", "-I.", *arguments]
                    converted = commands.run(argv, cwd=output / "src")
                    if converted is not None and converted.returncode:
                        read_error = next(iter((converted.stderr or converted.stdout).strip().splitlines()), "")
                if converted is not None and converted.returncode == 0:
                    lowered = output / "sv_frontend.v"
                    lowered.write_text(converted.stdout)
                    body = body[:reads[0].start()] + "read_verilog -formal -sv " + _word(lowered) + body[reads[0].end():]
                    body = body.replace("[files]\n", "[files]\n" + str(lowered) + "\n", 1)
                    retry = output / "sv_frontend.sby"
                    retry.write_text(body)
                    destination = output / "sv_frontend"
                    alternate = commands.run(["sby", "-f", "-d", destination, retry], cwd=source.parent)
                    if alternate is not None:
                        frontend_failures.add(first_read)
                        reports.extend([lowered, retry, output / "status"])
                        output, completed = destination, alternate
                missing_include = converted is not None and "Could not find file" in converted.stdout + converted.stderr
                if len(reads) == 1 and not missing_include and not (output / "model/design.il").is_file():
                    top_match = re.search(r"(?m)^(?:prep|hierarchy)\b[^\n]*[ \t]-top[ \t]+(\S+)", original_body)
                    native_read = "read_slang --single-unit --no-synthesis-define -DFORMAL "
                    if top_match:
                        native_read += "--top " + top_match[1] + " "
                    native_read += "-I " + _word(config.parent / "src") + " " + reads[0][1]
                    native_read += ("\nsetundef -undriven -anyseq a:anyseq>0"
                                    "\nsetundef -undriven -anyconst a:anyconst>0")
                    retry = config.parent / "slang_frontend.sby"
                    retry.write_text(original_body[:reads[0].start()] + native_read + original_body[reads[0].end():])
                    destination = config.parent / "slang_frontend"
                    retry_index = len(commands.records)
                    alternate = commands.run(["sby", "-f", "-d", destination, retry], cwd=source.parent)
                    if alternate is not None:
                        frontend_failures.update(range(first_read, retry_index))
                        reports.extend([retry, output / "status"])
                        output, completed = destination, alternate
                if not (output / "model/design.il").is_file():
                    errors = [line for line in (completed.stdout + completed.stderr).splitlines()
                              if "ERROR:" in line or "error:" in line or "Source line " in line]
                    scope.append(" ".join(part for part in [read_error, *errors[:2]] if part))
            native = sorted(output.rglob("status"))
            config = output / "config.sby"
            word = (output / "status").read_text().strip().split() if (output / "status").is_file() else []
            status = word[0] if word else ""
            mode = ""
            if config.is_file():
                body = config.read_text()
                mode_match = re.search(r"^mode\s+(\S+)\s*$", body, re.M)
                mode = mode_match[1] if mode_match else ""
            row = {"name": f"SymbiYosys.{task}", "ran": True,
                   "exit_code": completed.returncode,
                   "status": status if status in {"PASS", "FAIL"} else "NOT_MEASURED"}
            native_steps.append(row)
            if mode in {"prove", "bmc"}:
                options = re.search(r"(?ms)^\[options\]\s*\n(.*?)(?=^\[|\Z)", body)
                assertions = cover_model(output, key, options[1] if options else "mode cover\n")
                if assertions is None and (status == "PASS" or key in unmodeled_inputs):
                    status = "NOT_MEASURED"
                    row["status"] = status
                    row["detail"] = ("The native model lacks declared free inputs." if key in unmodeled_inputs
                                     else "The native formal model's cover targets could not be read.")
                if mode == "prove":
                    statuses.append(status)
            elif mode == "cover":
                cover_model(output, key, "", inspect_only=True)
                if key in unmodeled_inputs:
                    status = "NOT_MEASURED"
                    row["status"] = status
                    row["detail"] = "The native model lacks declared free inputs."
                covers.append(status)
            if status in {"PASS", "FAIL"}:
                observed.append(key)
            reports.extend(native)
    metrics = {}
    if statuses and all(word in {"PASS", "FAIL"} for word in statuses):
        metrics["unproved_required_properties"] = sum(word == "FAIL" for word in statuses)
    if covers and all(word in {"PASS", "FAIL"} for word in covers):
        metrics["vacuous_required_proofs"] = sum(word == "FAIL" for word in covers)
    if required and all(row["status"] in {"PASS", "FAIL"} for row in native_steps):
        metrics["proof_partition_coverage"] = {"required": required, "observed": observed}
    cover_detail = ("Native SBY cover tasks use existing covers and conditional assertion enables." if covers else
        "No native cover targets were present; no vacuity count is reported."
        if scope and not any(row["name"].endswith(".Cover.Input") for row in native_steps) else
        "Native cover target scope is unmeasured.")
    proves_top = bool(proof_scopes) and all(row["proves_declared_top"] for row in proof_scopes)
    scope_report = directory / "formal_scope.json"
    scope_report.write_text(json.dumps({"declared_top": declared_top, "proves_declared_top": proves_top,
        "tasks": proof_scopes, "authoring": {key: authored[key] for key in (
            "top", "declared_top", "descended_to_leaf", "proves_declared_top", "selection") if key in authored},
        "scope": "Properties of the actual harness subjects only; top-level function uses simulation, ISA suites and GLS."}, indent=2) + "\n")
    result = commands.result(metrics, [*reports, scope_report], " ".join([*scope, cover_detail,
        f"proves_declared_top={str(proves_top).lower()}; scope is the actual harness subjects in {scope_report}."]))
    result["exit_code"] = next((r["exit_code"] for i, r in enumerate(commands.records)
                                if i not in frontend_failures and r["exit_code"]),
                               0 if commands.records else None)
    result["native_steps"] = native_steps
    return result


def macro_views(project, directory, tool, commands, route=None):
    """Use the existing pre-netlist macro integration component's own verdict."""
    from ip_integration_check import audit
    from flow_macro_views import produce
    try:
        produced = produce(project, directory, commands, route or {})
    except (OSError, ValueError, ImportError) as exc:
        return {**commands.result(detail=str(exc)), "ran": False, "exit_code": None}
    if produced is not None:
        return produced
    started = time.perf_counter()
    report = audit(project)
    path = directory / "macro_views.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    ran = report["rc"] != 2
    return {"ran": ran, "exit_code": report["rc"] if ran else None,
            "metrics": {"macro_count": len(report.get("macros", {}))} if ran else {},
            "reports": [str(path)], "tool_seconds": time.perf_counter() - started,
            "detail": report.get("reason", "Existing macro view-set integration audit; native PV and STA remain separate.")}


def technology(project, directory, tool, commands):
    from flow109_technology_qualification import execute
    return execute(project, directory)


def physical_declarations(project, directory, tool, commands, route):
    """Evaluate physical declarations; conflicting IC/IP claims fail the row."""
    import _tapeout_declaration as declaration
    from flow_engine import read_json

    answers = read_json(project / "input/step_0_5ic_answers.json")
    operator = answers.get("operator_template") or {}
    if not operator:
        for path in sorted((project / "phase1/generated_docs").glob("L*.json")):
            doc = read_json(path)
            operator = doc.get("operator_template") or doc.get("fields", {}).get("operator_template") or {}
            if operator:
                break
    try:
        if (declaration.bought_slot_hardmacro(project)
                or route["delivery_target"] == "ip_hardmacro" and any(
                    isinstance(operator.get(key), str) and operator[key].strip() for key in ("path", "slot"))):
            raise declaration.DeliveryRouteContradiction(declaration.BOUGHT_SLOT_HARDMACRO_MESSAGE)
        die_owed = declaration.die_outputs_owed(project)
        pads_owed = declaration.requests_pad_ring(project)
    except declaration.DeliveryRouteContradiction as exc:
        return {"ran": True, "exit_code": 1, "detail": str(exc)}
    if route["delivery_target"] == "ip_hardmacro":
        return {"ran": True, "exit_code": 0,
                "metrics": {"slot_owed": False, "pad_ring_owed": False, "die_outputs_owed": False},
                "detail": "Pure hard IP owes no shuttle slot, pad ring or die outputs."}
    slots = sorted((project / declaration.SLOTS_REL).glob("*.yaml")) + sorted(
        (project / declaration.SLOTS_REL).glob("*.yml"))
    template = operator.get("path")
    if not template and not slots:
        return {"ran": True, "exit_code": 0,
                "metrics": {"operator_template_present": False, "slot_files": 0,
                            "die_outputs_owed": die_owed, "pad_ring_owed": pads_owed},
                "detail": "No operator template or slots supplied; generate die and pads from design documents and the PDK."}
    ingest = [sys.executable, str(Path(__file__).with_name("submission_template_ingest.py")), str(project)]
    if template:
        path = Path(template)
        ingest += ["--template", str(path if path.is_absolute() else project / path)]
    if operator.get("slot"):
        ingest += ["--slot", str(operator["slot"])]
    completed = commands.run(ingest)
    if completed is None or completed.returncode:
        return commands.result(detail="Operator template ingestion did not complete.")
    source = project / "input/step_0_5ic_answers.json"
    if operator and operator != answers.get("operator_template"):
        source = directory / "declarations.json"
        source.write_text(json.dumps({**answers, "operator_template": operator}) + "\n")
    argv = [sys.executable, str(Path(__file__).with_name("tapeout_declaration_gen.py")), str(project)]
    if source.is_file():
        argv += ["--answers", str(source)]
    commands.run(argv)
    return commands.result({"operator_template_present": bool(template), "slot_files": len(list(
        (project / declaration.SLOTS_REL).glob("*.yaml")))},
        [project / "reports/phase1/submission_template.json", project / declaration.REPORT_REL],
        "Supplied operator template and declarations evaluated; unanswered declarations do not require manual answers.")


ADAPTERS = {"cdc": cdc, "simulation": simulation, "formal": formal, "technology": technology, "macro_views": macro_views}


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


def _simulation_in_runtime(project, work, tool):
    import _eda_pin

    container = os.environ.get("EDA_CONTAINER") or _eda_pin.default_container_name()
    transport = work / "runtime"
    transport.mkdir()
    commands = Commands(transport)
    inspected = commands.run(["docker", "inspect", "--format", "{{json .Mounts}}", container])
    if inspected is None or inspected.returncode:
        return {**commands.result(detail="The declared simulation runtime could not be opened."),
                "ran": False, "exit_code": None}
    mounts = [(str(Path(mount["Source"]).resolve()), mount["Destination"])
              for mount in json.loads(inspected.stdout) if mount["Type"] == "bind"]

    def mapped(value, pairs):
        if isinstance(value, str):
            for source, destination in sorted(pairs, key=lambda pair: len(pair[0]), reverse=True):
                if value == source or value.startswith(source.rstrip("/") + "/"):
                    return destination.rstrip("/") + value[len(source):]
        elif isinstance(value, list):
            return [mapped(item, pairs) for item in value]
        elif isinstance(value, dict):
            return {key: mapped(item, pairs) for key, item in value.items()}
        return value

    result_path = work / "simulation_result.json"
    code = """import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from flow_native_adapters import Commands, simulation
project, work = map(Path, sys.argv[2:4])
commands = Commands(work)
try:
    result = simulation(project, work, json.loads(sys.argv[4]), commands)
except (OSError, ValueError, KeyError) as exc:
    result = commands.result(detail=str(exc))
Path(sys.argv[5]).write_text(json.dumps(result))
"""
    argv = ["python3", "-c", code, str(Path(__file__).resolve().parent),
            str(project), str(work), json.dumps(mapped(tool, mounts)), str(result_path)]
    options = ["-w", mapped(str(work), mounts)]
    for key, value in tempfile.configure().items():
        options.extend(["-e", key + "=" + mapped(value, mounts)])
    completed = commands.run(["docker", "exec", *options, container, "bash", "-lc",
                              "exec " + shlex.join(mapped(argv, mounts))])
    if completed is None or completed.returncode or not result_path.is_file():
        return {**commands.result(detail="The declared simulation runtime did not return a result."),
                "ran": False, "exit_code": None}
    result = mapped(json.loads(result_path.read_text()), [(target, source) for source, target in mounts])
    result["reports"] = commands.result()["reports"] + result.get("reports", [])
    return result


def execute(project, directory, tool, route, *, state=None, config=None):
    project, directory = Path(project).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    parent = tempfile.current_run("adapter", directory.name) / directory.name
    work = Path(tempfile.mkdtemp(prefix="native_", dir=parent))
    commands = Commands(work)
    if tool.get("adapter") == "macro_views":
        return macro_views(project, work, tool, commands, route)
    if tool.get("adapter") == "path_delay_atpg":
        from flow_atpg import path_delay
        return path_delay(project, work, state=state, config=config)
    if tool.get("adapter") == "small_delay_atpg":
        from flow_atpg import small_delay
        return small_delay(project, work, config=config)
    if tool.get("adapter") == "final_patterns":
        from flow_atpg import final_patterns
        return final_patterns(project, work, state=state, config=config)
    if tool.get("adapter") in {"security_requirements", "implemented_security"}:
        from flow_security import requirements
        return requirements(project, work, tool)
    if tool.get("adapter") == "safety_injection":
        from flow_safety import injection
        return injection(project, work, tool)
    if tool.get("adapter") == "safety_case":
        from flow_safety import safety_case
        return safety_case(project, work, tool)
    if tool.get("adapter") == "system_scenarios":
        from flow_system_scenarios import execute as system_scenarios
        return system_scenarios(project, work, tool)
    if tool.get("adapter") == "power_intent":
        from flow_power import intent
        return intent(project, work, tool)
    if tool.get("adapter") == "power_simulation":
        from flow_power import simulation
        return simulation(project, work, tool)
    if tool.get("adapter") == "implemented_power_intent":
        from flow_power import implemented
        return implemented(project, work, state=state, config=config)
    if tool.get("adapter") == "transition_atpg":
        from flow_atpg import transition
        return transition(project, work, state=state, config=config)
    if tool.get("adapter") == "final_atpg":
        from flow_atpg import stuck_at
        return stuck_at(project, work, state=state, config=config)
    if tool.get("adapter") == "design_release":
        from foundry_handoff_pack_gen import execute as release
        return release(project, work, tool, route, state=state, config=config)
    if tool.get("adapter") == "package_readiness":
        from fnmatch import fnmatch
        import flow109_package_ready
        config = config or {}
        tech = [path for pattern, path in config.get("TECH_LEFS", {}).items()
                if fnmatch(config.get("DEFAULT_CORNER", ""), pattern)]
        started = time.perf_counter()
        result = flow109_package_ready.execute(project,
            def_path=state.get("def") if state is not None else None,
            tech_lef=tech[0] if len(tech) == 1 else None, io_lefs=config.get("PAD_LEFS"))
        report = work / "pad_readiness.json"
        report.write_text(json.dumps(result, indent=2) + "\n")
        pads = next((row["detail"] for row in result["checks"]
                     if row["check"] == "pad_bterm_coincidence_check"), {})
        metrics = {"pad_" + key + "_count": len(pads[key])
                   for key in ("connected_nets", "not_connected_nets", "undecided_nets") if key in pads}
        return {"ran": result["native_started"],
                "exit_code": 1 if result["component_status"] == "FAIL" else 0 if result["native_started"] else None,
                "metrics": metrics, "reports": [str(report)],
                "tool_seconds": time.perf_counter() - started, "detail": result["reason"],
                "native_steps": [{"name": row["check"], "status": row["status"],
                    "ran": row["check"] != "missing_input",
                    "exit_code": 1 if row["status"] == "FAIL" else 0,
                    "detail": row["detail"]} for row in result["checks"]]}
    if tool.get("adapter") in {"analog", "mixed"}:
        import importlib
        native = importlib.import_module("flow_native_" + tool["adapter"])
        return native.execute(project, work, tool, commands, state=state, config=config or {}, route=route)
    if tool.get("adapter") == "ip_release_docs":
        from ip_release_docs_gen import execute as release_docs
        return release_docs(project, work, tool, route, state=state, config=config)
    if tool.get("adapter") == "dfm":
        from dfm_screen_check import execute as dfm
        return dfm(project, work, tool, route, state=state, config=config)
    if tool.get("adapter") == "ir_drop":
        from flow_ir_corners import execute as ir_drop
        return ir_drop(project, work, tool, route, state=state, config=config)
    if tool.get("adapter") == "tapeout_precheck":
        import tapeout_precheck
        if state is None or not state.get("gds"):
            return commands.result(detail="Tapeout precheck needs the final GDS in native State.")
        started = time.perf_counter()
        result = tapeout_precheck.execute(project, gds=state.get("gds"),
                                          config=config or {}, directory=work)
        code = result.get("exit_code")
        metrics = result.get("measurement") or {}
        return {"ran": code is not None, "exit_code": code, "metrics": metrics,
                "reports": [str(path) for path in work.rglob("*") if path.is_file()],
                "tool_seconds": time.perf_counter() - started,
                "detail": result.get("reason", ""),
                "native_steps": [{"name": "KLayout tapeout precheck", "ran": code is not None,
                                  "exit_code": code, "status": result["verdict"],
                                  "checks": result.get("checks", [])}]}
    if tool.get("adapter") == "physical_declarations":
        return physical_declarations(project, work, tool, commands, route)
    if tool.get("adapter") == "functional_activity":
        from flow_activity import execute as activity
        return activity(project, work, tool, route, state=state, config=config)
    if tool.get("adapter") in {"eqy", "xor", "gls"}:
        import flow_native_verification
        return getattr(flow_native_verification, tool["adapter"])(
            project, work, tool, commands, state=state, config=config or {})
    if tool.get("adapter") == "implemented_cdc":
        return cdc(project, work, tool, commands, state=state, config=config or {})
    adapter = ADAPTERS.get(tool.get("adapter"))
    if adapter is None:
        return commands.result(detail=f"No native adapter for {tool.get('adapter')!r}.")
    try:
        if tool.get("adapter") == "simulation":
            from _container_exec import no_container_route
            if not no_container_route():
                return _simulation_in_runtime(project, work, tool)
        return adapter(project, work, tool, commands)
    except (OSError, ValueError, KeyError) as exc:
        return commands.result(detail=str(exc))
