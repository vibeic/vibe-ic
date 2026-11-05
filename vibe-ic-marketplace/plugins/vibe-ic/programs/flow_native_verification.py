from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time


def eqy_partitions(scratch):
    scratch = Path(scratch)
    listing = scratch / "partition.list"
    reports = [listing] if listing.is_file() else []
    heads = [line.partition(":")[0].split()
             for line in listing.read_text().splitlines() if line.strip()] if reports else []
    declared = [head[1] for head in heads if len(head) >= 2]
    xbits = [head[1] for head in heads if len(head) >= 2 and "xbits" in head[2:]]
    parts = {}
    for path in sorted((scratch / "strategies").glob("*/*/status")):
        words = path.read_text().split()
        parts.setdefault(path.parent.parent.name, []).append(words[0] if words else "")
        reports.append(path)
    failed = [name for name, words in parts.items() if "FAIL" in words]
    if failed:
        return "FAIL", len(failed), f"EQY disproved {len(failed)} partition(s).", reports
    complete = (bool(declared) and len(declared) == len(heads)
                and len(set(declared)) == len(declared) and set(declared) == set(parts))
    if not complete:
        return "NOT_MEASURED", None, "EQY partition declarations or strategy statuses are incomplete.", reports
    unknown = [name for name, words in parts.items() if "PASS" not in words]
    if unknown or xbits:
        return ("NOT_MEASURED", None,
                f"EQY has {len(unknown)} undecided and {len(xbits)} gold-x partition(s).", reports)
    return "PASS", 0, f"EQY proved all {len(declared)} partition(s).", reports


def reset_boundary(project):
    from l8_clock_reset_waveform_emit import _records, _scopes

    clocks, resets = set(), set()
    for pattern in ("L8*.json", "L9*.json"):
        for path in sorted((Path(project) / "phase1/generated_docs").glob(pattern)):
            document = json.loads(path.read_text())
            for scope in _scopes(document):
                containers = [scope]
                if isinstance(scope.get("clock_and_reset_waveform"), dict):
                    containers.append(scope["clock_and_reset_waveform"])
                for container in containers:
                    for row in _records(container, "clocks", "clock_domains"):
                        name, edge = row.get("source_pin") or row.get("name"), row.get("edge")
                        if name and edge in {"posedge", "negedge"}:
                            clocks.add((name, edge))
                    for row in _records(container, "resets", "reset_domains"):
                        name, polarity = row.get("name"), row.get("polarity")
                        if name and polarity in {"active_low", "active_high"}:
                            resets.add((name, polarity))
    if len(clocks) != 1 or len(resets) != 1:
        return None
    clock, reset = next(iter(clocks)), next(iter(resets))
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", item[0]) for item in (clock, reset)):
        return None
    return clock, reset


def reset_script(script, boundary):
    script = script.replace("setundef -init -zero\n", "")
    if boundary:
        (clock, edge), (reset, polarity) = boundary
        clock_option = "-clock" if edge == "posedge" else "-clockn"
        reset_option = "-resetn" if polarity == "active_low" else "-reset"
        replay = f"sim {clock_option} {clock} {reset_option} {reset} -rstlen 1 -n 1 -w -a\n"
        script = script.replace("async2sync\n", replay + "async2sync\n", 1)
    return script


def eqy(project, directory, tool, commands, *, state, config):
    from librelane_eqy import eqy_script
    from sdf_gate_sim import netlist_used_cells, verilog_model_closure
    from lec_post_layout_check import _LIB_CELL_RE

    project, directory = Path(project), Path(directory)
    top, netlist = config.get("DESIGN_NAME"), state.get("nl") if state is not None else None
    rtl = [Path(p) if Path(p).is_absolute() else project / p for p in config.get("VERILOG_FILES") or []]
    if not top or not netlist or not Path(netlist).is_file() or not rtl or any(not path.is_file() for path in rtl):
        return commands.result(detail="EQY needs produced RTL, State netlist and the configured corner's Liberty models.")
    used = set().union(*(netlist_used_cells(path.read_text()) for path in [*rtl, Path(netlist)]))
    corner = config.get("DEFAULT_CORNER", "")
    liberty, external_liberty = [], []
    for key in ("CELL_LIBS" if config.get("CELL_LIBS") else "LIB", "PAD_LIBS", "EXTRA_LIBS"):
        libraries = config.get(key) or []
        groups = ([paths for pattern, paths in libraries.items() if fnmatch.fnmatchcase(corner, pattern)]
                  if isinstance(libraries, dict) else [libraries])
        for paths in groups:
            values = [str(path) for path in (paths if isinstance(paths, (list, tuple)) else [paths])]
            if key in {"PAD_LIBS", "EXTRA_LIBS"}:
                values = [path for path in values if not Path(path).is_file()
                          or used.intersection(_LIB_CELL_RE.findall(Path(path).read_text()))]
            liberty.extend(values)
            if key in {"PAD_LIBS", "EXTRA_LIBS"}:
                external_liberty.extend(values)
    liberty = list(dict.fromkeys(liberty))
    if not liberty or any(not Path(path).is_file() for path in liberty):
        return commands.result(detail="EQY needs produced RTL, State netlist and the configured corner's Liberty models.")
    declared = [Path(path) if Path(path).is_absolute() else project / path
                for key in ("PAD_VERILOG_MODELS", "EXTRA_VERILOG_MODELS")
                for path in config.get(key) or []]
    missing = [str(path) for path in declared if not path.is_file()]
    if missing:
        return commands.result(detail="EQY declared pad/extra models are unavailable: " + ", ".join(missing))
    for library in external_liberty:
        declared.extend(sorted((Path(library).parent.parent / "verilog").glob("*.v")))
    models = []
    if declared:
        from pdk_udp_synth_shim_gen import _strip_specials
        for index, path in enumerate(map(Path, verilog_model_closure(declared, used)["files"])):
            source = path.read_text()
            prepared = _strip_specials(source)
            if prepared != source:
                output = directory / f"model_{index + 1}" / path.name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(prepared)
                path = output
            models.append(path)
    script = directory / "equivalence.eqy"
    script.write_text(reset_script(eqy_script(top, rtl, Path(netlist), liberty[0],
        synthesis=config, views=directory, liberty_files=list(map(Path, liberty)), model_verilog=models),
        reset_boundary(project)))
    completed = commands.run(["eqy", "-j", "8", "-f", "-d", directory / "scratch", script])
    if completed is None:
        return commands.result(reports=[script], detail="The native EQY executable is unavailable.")
    status, count, detail, reports = eqy_partitions(directory / "scratch")
    if status == "NOT_MEASURED":
        logs = list((directory / "scratch/strategies").glob("*/*/*/logfile.txt"))
        witness_error = any("yosys-witness" in (text := path.read_text(errors="replace"))
                            and ("bad interpreter" in text or "No such file or directory" in text)
                            for path in logs)
        witness = shutil.which("yosys-witness")
        if (witness_error and witness and not Path("/usr/bin/env").exists()
                and Path(witness).read_text(errors="replace").splitlines()[0].startswith("#!/usr/bin/env")):
            detail += " Native yosys-witness cannot execute: its /usr/bin/env shebang interpreter is absent."
        reports.extend(logs)
    metrics = {}
    if count is not None:
        metrics = dict.fromkeys({"unproved_equivalence", "final_lec_unproved",
                                tool.get("metric", "unproved_equivalence")}, count)
    result = commands.result(metrics, [script, *reports], detail)
    result["native_steps"] = [{"name": "Yosys.EQY", "ran": True,
                               "exit_code": completed.returncode, "status": status}]
    return result


def xor(project, directory, tool, commands, *, state, config):
    if tool.get("scope") == "finishing" or tool.get("metric") == "unexplained_stream_xor":
        return finishing_xor(project, directory, tool, commands, state=state, config=config)
    metric = "design__xor_difference__count"
    value = state.metrics.get(metric) if state is not None else None
    if value is not None:
        result = commands.result({metric: value, tool.get("metric", metric): value},
                                 tool.get("reports", []), "Reused the native KLayout stream XOR count from State.")
        result.update(ran=True, exit_code=0)
        return result
    if state is None or state.get("mag_gds") is None or state.get("klayout_gds") is None:
        return commands.result(detail="KLayout.XOR needs the Magic and KLayout GDS views in State.")
    from librelane.steps.klayout import XOR
    return layout_step(directory, tool, commands, state, config, XOR, metric,
                       {"KLAYOUT_XOR_THREADS": 8}, "xor.xml")


def finishing_xor(project, directory, tool, commands, *, state, config):
    if state is None or state.get("gds") is None:
        return commands.result(detail="Finishing XOR needs the current GDS view in State.")
    primary = config.get("PRIMARY_GDSII_STREAMOUT_TOOL")
    pre = (tool.get("pre_gds") or config.get("VIBEIC_FINISHING_PRE_GDS")
           or state.get({"magic": "mag_gds", "klayout": "klayout_gds"}.get(primary, "")))
    sealed = tool.get("sealed_gds") or config.get("VIBEIC_FINISHING_SEALED_GDS")
    core = (config.get("VIBEIC_FINISHING_CORE_AREA") or config.get("CORE_AREA")
            or state.metrics.get("design__core__bbox"))
    if not pre or core is None:
        return commands.result(detail="Finishing XOR needs the native pre-finishing stream and core rectangle.")
    if state.metrics.get("design__seal_ring__verified") == 1 and not sealed:
        return commands.result(detail="Finishing XOR needs the native seal-ring output as well as the finished GDS.")
    from librelane_plugins.librelane_plugin_vibeic.signoff import FinishingXOR
    core = core.replace(",", " ").split() if isinstance(core, str) else list(core)
    if len(core) != 4:
        return commands.result(detail="Finishing XOR has no four-coordinate native core rectangle.")
    overrides = {"VIBEIC_FINISHING_PRE_GDS": str(pre),
                 "VIBEIC_FINISHING_CORE_AREA": ",".join(map(str, core)),
                 "VIBEIC_FINISHING_SEALED_GDS": str(sealed) if sealed else None,
                 "VIBEIC_FINISHING_XOR_THREADS": 8}
    return layout_step(directory, tool, commands, state, config, FinishingXOR,
                       "vibeic__finishing_xor__defect__count", overrides, "finishing_xor.xml")


def layout_step(directory, tool, commands, state, config, step_class, metric, overrides, report):
    from librelane.config import Config
    from librelane.steps import StepError, StepException

    class Observed(step_class):
        def run_subprocess(self, cmd, *args, **kwargs):
            started, code, log = time.perf_counter(), None, None
            try:
                result = super().run_subprocess(cmd, *args, **kwargs)
                code = result["returncode"]
                log = result["log_path"]
                return result
            except subprocess.CalledProcessError as exc:
                code = exc.returncode
                raise
            finally:
                commands.seconds += time.perf_counter() - started
                if code is not None:
                    commands.records.append({"command": list(map(str, cmd)), "exit_code": code,
                                             "log": str(log or directory / (self.id.lower().replace(".", "-") + ".log"))})

    native = Observed(Config(config).copy(**overrides), state)
    detail, status = f"Native {step_class.id} on its actual GDS inputs.", "PASS"
    try:
        output = native.start(step_dir=str(directory))
    except StepError as exc:
        return commands.result(reports=list(directory.glob("*.log")), detail=str(exc))
    except (StepException, FileNotFoundError) as exc:
        return commands.result(detail=str(exc))
    value = output.metrics.get(metric)
    metrics = dict(output.metrics)
    if value is not None:
        metrics[tool.get("metric", metric)] = value
    if value is None:
        detail, status = f"{step_class.id} left no native difference count.", "NOT_MEASURED"
    elif value:
        status = "FAIL"
    result = commands.result(metrics, [directory / report], detail)
    result["native_steps"] = [{"name": step_class.id, "ran": bool(commands.records),
                               "exit_code": result["exit_code"], "status": status}]
    return result


def gls(project, directory, tool, commands, *, state, config):
    import sdf_gate_sim as native
    from _sim_results_bridge import parse_junit
    from flow_native_adapters import testbenches

    project, directory = Path(project), Path(directory)
    top = config.get("DESIGN_NAME")
    netlist = state.get("nl") if state is not None else None
    sdfs = state.get("sdf") if state is not None else None
    if not top or not netlist or not Path(netlist).is_file() or not sdfs:
        return commands.result(detail="GLS needs the declared top, native State netlist and corner SDF files.")
    sdfs = sdfs if isinstance(sdfs, dict) else {"default": sdfs}
    requested = tool.get("corners")
    if requested == "all":
        selected = list(sdfs)
    elif requested is not None:
        selected = [requested] if isinstance(requested, str) else list(requested)
    else:
        selected = [config.get("DEFAULT_CORNER") or next(iter(sdfs))]
        if len(sdfs) == 1 and "default" in sdfs:
            selected = ["default"]
    if not selected or any(corner not in sdfs for corner in selected):
        return commands.result(detail=f"GLS selected SDF corners are unavailable: {selected}; native corners: {list(sdfs)}.")
    unmeasured = [corner for corner in sdfs if corner not in selected]
    sdfs = {corner: sdfs[corner] for corner in selected}
    missing = [str(path) for path in sdfs.values() if not path or not Path(path).is_file()]
    if missing:
        return commands.result(detail="Native SDF files are absent: " + ", ".join(missing))
    benches = testbenches(project, tool)
    if not benches:
        reused = native.find_reusable_testbench(project, top)
        benches = [reused["path"]] if reused else []
    if not benches or any(not path.is_file() for path in benches):
        return commands.result(detail="GLS needs the existing functional self-checking testbench suite.")
    executables = ["iverilog", "vvp"] + (["cocotb-config", "make"] if any(p.suffix == ".py" for p in benches) else [])
    absent = [name for name in executables if not shutil.which(name)]
    if absent:
        return commands.result(detail="GLS executables are unavailable: " + ", ".join(absent))
    text = Path(netlist).read_text()
    declared = [Path(path) for key in ("CELL_VERILOG_MODELS", "PAD_VERILOG_MODELS")
                for path in config.get(key) or []]
    if any(not path.is_file() for path in declared):
        return commands.result(detail="GLS needs the configured PDK's functional and timing cell models.")
    used = native.netlist_used_cells(text)
    closure = native.verilog_model_closure(declared, used)
    model_text = "\n".join(Path(path).read_text() for path in closure["files"])
    stubs = native.missing_empty_cell_stubs(text, used, model_text)
    unresolved = sorted(set(closure["unresolved"]) - set(stubs))
    if unresolved or closure["clashes"]:
        return commands.result(detail=f"GLS cell models incomplete: unresolved={unresolved}, "
            f"clashes={closure['clashes']}.")
    stub_file = directory / "physical_cells.v"
    stub_file.write_text("\n".join(f"module {name} (); endmodule" for name in stubs) + "\n")
    rows, reports = [], [stub_file]
    for corner, sdf in sdfs.items():
        for bench in benches:
            work = directory / ("corner_" + str(len(rows) + 1))
            work.mkdir(parents=True, exist_ok=True)
            row = {"corner": corner, "testbench": str(bench), "status": "NOT_MEASURED",
                   "ran": False, "exit_code": None}
            models = [str(netlist), *closure["files"], str(stub_file)]
            flags = shlex.split(native._IVERILOG_FLAGS)
            for parent in dict.fromkeys([str(bench.parent), *(str(Path(p).parent) for p in models)]):
                flags.extend(["-I", parent])
            if bench.suffix == ".py":
                from _specrtl_common import parse_rtl_ports
                _, ports = parse_rtl_ports(text, top)
                if not ports or any(type(port.width) is not int or port.width < 1 for port in ports):
                    row["detail"] = "The native netlist's top port dimensions are unavailable for the cocotb shim."
                    rows.append(row)
                    continue
                shim = work / "annotation.v"
                declarations = []
                for port in ports:
                    kind = {"input": "reg", "output": "wire", "inout": "tri"}[port.direction]
                    width = f"[{port.width - 1}:0] " if port.width > 1 else ""
                    declarations.append(f"{kind} {width}{port.name};")
                connections = ",".join(f".{port.name}({port.name})" for port in ports)
                wrapper = ("module flow_sdf_tb;\n" + "\n".join(declarations)
                           + f"\n{top} dut({connections});\nendmodule\n")
                shim.write_text(native.inject_sdf_annotation(wrapper, "flow_sdf_tb", "dut", str(sdf)))
                makefile = work / "simulation.mk"
                sources = " ".join(shlex.quote(path).replace("$", "$$") for path in [*models, str(shim)])
                compile_flags = " ".join(shlex.quote(flag).replace("$", "$$") for flag in flags)
                module = shlex.quote(bench.stem).replace("$", "$$")
                makefile.write_text("SIM = icarus\nTOPLEVEL_LANG = verilog\n"
                    f"VERILOG_SOURCES = {sources}\nCOCOTB_TOPLEVEL = flow_sdf_tb\n"
                    f"COCOTB_TEST_MODULES = {module}\n"
                    f"COMPILE_ARGS += {compile_flags}\n"
                    "COCOTB_PLUSARGS += -sdf-info\nSIM_BUILD = build\nCOCOTB_RESULTS_FILE = results.xml\n"
                    f"export PYTHONPATH := {str(bench.parent).replace('$', '$$')}:$(PYTHONPATH)\n"
                    "include $(shell cocotb-config --makefiles)/Makefile.sim\n")
                completed = commands.run(["make", "-f", makefile, "-j8"], cwd=work)
                summary = parse_junit(work / "results.xml")
                functional = (summary if summary and summary["tests"] > 0 and not summary["skipped"] else None)
                failures = functional["failures"] + functional["errors"] if functional else None
                passed = functional["passed"] if functional else None
                total = functional["tests"] if functional else None
                reports.extend([shim, makefile, work / "results.xml"])
            else:
                tb_text = native.strip_comments(bench.read_text())
                module, instance = native._TB_MODULE_RE.search(tb_text), native._tb_dut_instance(tb_text, top)
                if not module or not instance:
                    row["detail"] = "The testbench does not instantiate the native netlist top."
                    rows.append(row)
                    continue
                injected = work / "annotated_tb.v"
                injected.write_text(native.inject_sdf_annotation(tb_text, module[1], instance, str(sdf)))
                built = commands.run(["iverilog", *flags, "-s", module[1], "-o", work / "sim.vvp",
                                      injected, *models], cwd=work)
                reports.append(injected)
                completed = (commands.run(["vvp", work / "sim.vvp", "-sdf-info"], cwd=work)
                             if built is not None and not built.returncode else built)
                transcript = completed.stdout + completed.stderr if completed is not None else ""
                functional = native.parse_l10_case_stdout(transcript)
                passed, total = functional["passed"], functional["total"]
                failures = total - passed if functional["verdict"] else None
            if completed is None:
                row["detail"] = "The native Icarus or cocotb executable is unavailable."
                rows.append(row)
                continue
            transcript = completed.stdout + completed.stderr
            applied = len(native._SDF_APPLIED_RE.findall(transcript))
            errors = len(native._SDF_ERROR_RE.findall(transcript))
            status = ("FAIL" if completed.returncode or errors or failures else
                      "PASS" if applied and failures == 0 else "NOT_MEASURED")
            detail = ("Icarus reported no applied SDF delay records. " if not applied else "")
            if failures is None:
                detail += "No native self-check or complete JUnit functional verdict was produced. "
            row.update(ran=True, exit_code=completed.returncode, status=status, tests=total,
                       passed=passed, failures=failures, sdf_delays_applied=applied, sdf_errors=errors,
                       detail=detail + "Icarus does not implement SDF timing checks; setup/hold remain STA checks.")
            rows.append(row)
    summary = directory / "gls.json"
    summary.write_text(json.dumps({"runs": rows, "cell_models": closure,
        "selected_corners": selected, "unmeasured_corners": unmeasured,
        "corner_selection": "explicit tool selection" if requested is not None else "direct owner single-SDF default"},
        indent=2) + "\n")
    metrics = {"sdf_delays_applied": sum(row.get("sdf_delays_applied", 0) for row in rows),
               "sdf_annotation_errors": sum(row.get("sdf_errors", 0) for row in rows)} if any(row["ran"] for row in rows) else {}
    if rows and all(row["status"] in {"PASS", "FAIL"} for row in rows):
        failures = sum((row.get("failures") or 0) + row.get("sdf_errors", 0)
                       + int(bool(row["exit_code"]) and not row.get("failures")) for row in rows)
        metrics.update(dict.fromkeys({"gls_failures", "final_gls_function_timing_errors",
                                     tool.get("metric", "gls_failures")}, failures))
    result = commands.result(metrics, [*reports, summary],
        f"Selected GLS corners: {selected}; other native SDF corners unmeasured: {unmeasured}. "
        "The full existing suite is replayed; no timing annotation means NOT_MEASURED.")
    result["native_steps"] = [{"name": "Icarus.GLS", **row} for row in rows]
    return result
