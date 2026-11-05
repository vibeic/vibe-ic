from __future__ import annotations

from decimal import Decimal
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
    if unknown:
        return ("NOT_MEASURED", None,
                f"EQY has {len(unknown)} undecided and {len(xbits)} gold-x partition(s).", reports)
    return "PASS", 0, f"EQY proved all {len(declared)} partition(s), including {len(xbits)} gold-x partition(s).", reports


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
                        name, polarity = row.get("source_pin") or row.get("name"), row.get("polarity")
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


def eqy_pad_views(directory, top, script, pads, models, commands, boundary):
    from flow109_netlist_cdc import _word

    core = directory / "core"
    core.mkdir()
    gold, remainder = script.split("[gate]", 1)
    gate, preparation = remainder.split("[script]", 1)
    defines = " ".join("-D" + str(value) for value in pads["defines"])
    includes = " ".join("-I " + _word(path) for path in pads["include_dirs"])
    reads = [f"read_verilog -lib -nooverwrite -sv {defines} {includes} " + _word(path) for path in models]
    reads += ["read_liberty -lib -nooverwrite -ignore_miss_func -ignore_miss_dir " + _word(path)
              for path in pads["liberty"]]
    views, reports = {}, []
    for side, source in (("gold", gold.replace("[gold]", "")), ("gate", gate)):
        path = directory / f"{side}_pads.ys"
        path.write_text("\n".join(reads) + "\n" + source + "\n"
            + f"hierarchy -check -top {top}\nproc\nflatten\n"
            + f"write_json {_word(directory / (side + '.before-normalization.json'))}\n"
            + f"select -set terminals {top}/i:* {top}/o:* %i\n"
            + "\n".join(f"expose -evert {top}/t:{master}"
                         for master in sorted(pads["types"])) + "\n"
            + f"select -set pad_terminals {top}/i:* {top}/o:* %i @terminals %d\n"
            + "delete -output @terminals\ndelete -input @pad_terminals\n"
            + f"write_json {_word(core / (side + '.json'))}\n"
            + f"write_verilog -noattr {_word(core / (side + '.v'))}\n")
        completed = commands.run(["yosys", "-s", path])
        reports.append(path)
        if completed is None or completed.returncode:
            return None, None, reports, "Pad-boundary elaboration did not complete."
        views[side] = json.loads((directory / f"{side}.before-normalization.json").read_text())["modules"][top]
        module = views[side]
        core_connections = {bit for cell in module["cells"].values() if cell["type"] not in pads["types"]
                            for bits in cell["connections"].values() for bit in bits}
        connected = {bit for port in module["ports"].values() for bit in port["bits"]}
        connected.update(core_connections)
        connected_ports = {f"{instance}.{pin}" for instance, cell in module["cells"].items()
                           if cell["type"] in pads["types"] for pin, bits in cell["connections"].items()
                           if bits and (cell["port_directions"].get(pin) == "input"
                                        or connected.intersection(bits) or set(bits).intersection({"0", "1"}))}
        exposed = json.loads((core / f"{side}.json").read_text())["modules"][top]
        disconnected = [f"{top}/{name}" for name, port in exposed["ports"].items()
                        if port["direction"] == "output" and name not in module["ports"]
                        and name not in connected_ports]
        pad_terminals = {bit for cell in module["cells"].values() if cell["type"] in pads["types"]
                         for pin, bits in cell["connections"].items()
                         if cell["port_directions"].get(pin) == "inout" for bit in bits}
        package_inputs = {bit for port in module["ports"].values() if port["direction"] in {"input", "inout"}
                          for bit in port["bits"]}
        package_outputs = [f"{top}/{name}" for name, port in module["ports"].items()
                           if port["direction"] == "output" and port["bits"]
                           and all(type(bit) is int and bit in pad_terminals
                                   and bit not in core_connections and bit not in package_inputs for bit in port["bits"])]
        projection = []
        if package_outputs:
            projection.extend(["expose -input " + " ".join(package_outputs),
                               "delete -output " + " ".join(package_outputs)])
        if disconnected:
            projection.append("delete -port " + " ".join(disconnected))
        if projection:
            path = directory / f"{side}_core.ys"
            path.write_text(f"read_json {_word(core / (side + '.json'))}\n"
                + "\n".join(projection) + "\n"
                + f"hierarchy -top {top}\nclean -purge\n"
                + f"write_json {_word(core / (side + '.json'))}\n"
                + f"write_verilog -noattr {_word(core / (side + '.v'))}\n")
            completed = commands.run(["yosys", "-s", path])
            reports.append(path)
            if completed is None or completed.returncode:
                return None, None, reports, "Pad-free core elaboration did not complete."
        reports.extend([directory / f"{side}.before-normalization.json", core / f"{side}.json"])

    def wrapper(module):
        instances = {name: cell for name, cell in module["cells"].items()
                     if cell["type"] in pads["types"]}
        nets = {}
        for name, port in module["ports"].items():
            for index, bit in enumerate(port["bits"]):
                nets.setdefault(bit, []).append(f"port:{name}:{index}")
        for name, cell in instances.items():
            for pin, bits in cell["connections"].items():
                for index, bit in enumerate(bits):
                    nets.setdefault(bit, []).append(f"pad:{name}:{pin}:{index}")
        return {"instances": {name: {key: cell[key] for key in ("type", "parameters", "port_directions")}
                              for name, cell in instances.items()},
                "connections": sorted(sorted(labels + (["constant:" + bit] if isinstance(bit, str) else []))
                                      for bit, labels in nets.items())}

    signatures = {side: wrapper(module) for side, module in views.items()}
    differences = [key for key in signatures["gold"] if signatures["gold"][key] != signatures["gate"][key]]
    report = directory / "wrapper.json"
    report.write_text(json.dumps({"views": signatures, "differences": differences,
        "scope": "Pad instances, types and terminal connectivity. Core-side behavior is proved by pad-free EQY."},
        indent=2) + "\n")
    reports.append(report)
    if boundary:
        module = json.loads((core / "gold.json").read_text())["modules"][top]
        gold = views["gold"]
        consumers = {bit for cell in gold["cells"].values() if cell["type"] not in pads["types"]
                     for pin, bits in cell["connections"].items()
                     if cell["port_directions"].get(pin) == "input" for bit in bits}
        rebound = []
        for name, sense in boundary:
            terminal = set(gold["ports"].get(name, {}).get("bits", []))
            ports = []
            for instance, cell in gold["cells"].items():
                if cell["type"] not in pads["types"] or not any(
                        terminal.intersection(bits) and cell["port_directions"].get(pin) in {"input", "inout"}
                        for pin, bits in cell["connections"].items()):
                    continue
                ports.extend(f"{instance}.{pin}" for pin, bits in cell["connections"].items()
                             if cell["port_directions"].get(pin) == "output" and consumers.intersection(bits)
                             and module["ports"].get(f"{instance}.{pin}", {}).get("direction") == "input")
            rebound.append((ports[0] if len(ports) == 1 else name, sense))
        boundary = tuple(rebound)
    prepared = (f"[gold]\nread_verilog -formal -sv {_word(core / 'gold.v')}\n"
                f"[gate]\nread_verilog -formal -sv -icells {_word(core / 'gate.v')}\n"
                "[script]" + preparation.replace(str(directory) + "/", str(core) + "/"))
    return reset_script(prepared, boundary), len(differences), reports, "Pads are black boxes on both sides."


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
    liberty, external_liberty, pad_liberty = [], [], []
    for key in ("CELL_LIBS" if config.get("CELL_LIBS") else "LIB", "PAD_LIBS", "EXTRA_LIBS"):
        libraries = config.get(key) or []
        groups = ([paths for pattern, paths in libraries.items() if fnmatch.fnmatchcase(corner, pattern)]
                  if isinstance(libraries, dict) else [libraries])
        for paths in groups:
            values = [str(path) for path in (paths if isinstance(paths, (list, tuple)) else [paths])]
            if key in {"PAD_LIBS", "EXTRA_LIBS"}:
                values = [path for path in values if not Path(path).is_file()
                          or used.intersection(_LIB_CELL_RE.findall(Path(path).read_text()))]
            if key == "PAD_LIBS":
                pad_liberty.extend(values)
            else:
                liberty.extend(values)
            if key == "EXTRA_LIBS":
                external_liberty.extend(values)
    liberty = list(dict.fromkeys(liberty))
    if not liberty or any(not Path(path).is_file() for path in liberty):
        return commands.result(detail="EQY needs produced RTL, State netlist and the configured corner's Liberty models.")
    pad_models = [Path(path) if Path(path).is_absolute() else project / path
                  for path in config.get("PAD_VERILOG_MODELS") or []]
    declared = [Path(path) if Path(path).is_absolute() else project / path
                for path in config.get("EXTRA_VERILOG_MODELS") or []]
    missing = [str(path) for path in [*declared, *pad_models, *map(Path, pad_liberty)] if not path.is_file()]
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
    pad_types = set().union(*(_LIB_CELL_RE.findall(Path(path).read_text()) for path in pad_liberty))
    from lec_post_layout_check import _NETLIST_MODULE_RE
    pad_types.update(match["name"] for path in pad_models
                     for match in _NETLIST_MODULE_RE.finditer(path.read_text()))
    pad_types &= used
    script = directory / "equivalence.eqy"
    source = eqy_script(top, rtl, Path(netlist), liberty[0], synthesis=config,
        views=directory, liberty_files=list(map(Path, liberty)), model_verilog=models)
    wrapper_count, wrapper_reports, wrapper_detail = None, [], ""
    if pad_types:
        from pdk_udp_synth_shim_gen import _strip_specials
        prepared_models = []
        for index, path in enumerate(pad_models):
            prepared = directory / f"pad_model_{index + 1}.v"
            prepared.write_text(_strip_specials(path.read_text()))
            prepared_models.append(prepared)
        source, wrapper_count, wrapper_reports, wrapper_detail = eqy_pad_views(directory, top, source,
            {"liberty": pad_liberty, "types": pad_types, "defines": config.get("VERILOG_DEFINES") or [],
             "include_dirs": sorted({path.parent for path in pad_models})},
            prepared_models, commands, reset_boundary(project))
        if source is None:
            return commands.result(reports=wrapper_reports, detail=wrapper_detail)
    else:
        source = reset_script(source, reset_boundary(project))
    script.write_text(source)
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
    if count is not None or wrapper_count:
        metrics = dict.fromkeys({"unproved_equivalence", "final_lec_unproved",
                                tool.get("metric", "unproved_equivalence")}, count or wrapper_count or 0)
    if wrapper_count:
        wrapper_detail += f" Native wrapper views disagree in {wrapper_count} connection/instance field(s)."
    result = commands.result(metrics, [script, *reports, *wrapper_reports], (detail + " " + wrapper_detail).strip())
    result["native_steps"] = [{"name": "Yosys.EQY.Core" if pad_types else "Yosys.EQY", "ran": True,
                               "exit_code": completed.returncode, "status": status}]
    if wrapper_count is not None:
        result["native_steps"].append({"name": "Yosys.Wrapper", "ran": True,
            "exit_code": 0, "status": "FAIL" if wrapper_count else "PASS"})
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
        seal_state = Path(project) / "steps/seal_ring_and_die_identification/state_out.json"
        if seal_state.is_file():
            sealed = json.loads(seal_state.read_text()).get("gds")
        if not sealed:
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


def gls_signal_netlist(directory, netlist, text, used, closure, config, commands):
    import sdf_gate_sim as native
    from _pad_ring import parse_lef_pin_roles, parse_verilog_rail_bridges
    from _specrtl_common import parse_rtl_ports
    from flow_chip_inputs import _paths
    from flow109_netlist_cdc import _word

    roles, connections, removed = {}, {}, set()
    for key in ("PAD_LEFS", "CELL_LEFS", "EXTRA_LEFS"):
        for path in _paths(config.get(key)):
            if path.is_file():
                roles.update(parse_lef_pin_roles(path.read_text()))
    for instance in native._INSTANCE_STMT_RE.finditer(text):
        connections.setdefault(instance[1], set()).update(
            pin for pin, _ in native._CONN_RE.findall(instance[3]))
    for path in closure["files"]:
        code = native.strip_comments(Path(path).read_text())
        bridges = parse_verilog_rail_bridges(code)
        for module in native._MODULE_BODY_RE.finditer(code):
            name = module[2]
            if name not in bridges or name not in used or name not in roles:
                continue
            if "`" in code[:module.end()]:
                continue
            _, ports = parse_rtl_ports(module[0], name)
            names = {port.name for port in ports}
            if (ports and connections.get(name, set()) - names
                    and all(port.direction == "inout" and roles[name].get(port.name, ("", ""))[1]
                            in {"POWER", "GROUND"} for port in ports)):
                removed.add(name)
    if not removed:
        return Path(netlist), [], []
    signal, projection = directory / "signal_netlist.v", directory / "signal_netlist.ys"
    projection.write_text(f"read_verilog -sv -icells {_word(netlist)}\n"
        + "\n".join("delete t:" + name for name in sorted(removed))
        + f"\nwrite_verilog -noattr {_word(signal)}\n")
    projected = commands.run(["yosys", "-s", projection])
    reports = [projection, signal]
    if projected is None or projected.returncode or not signal.is_file():
        return Path(netlist), [], reports
    return signal, sorted(removed), reports


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
    native_sdfs = [Path(path) for path in sdfs.values() if path]
    sdc = state.get("sdc") or config.get("SIGNOFF_SDC_FILE") or config.get("PNR_SDC_FILE")
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
    signal_netlist, physical, projection_reports = gls_signal_netlist(
        directory, netlist, text, used, closure, config, commands)
    signal_text = signal_netlist.read_text()
    model_text = "\n".join(Path(path).read_text() for path in closure["files"])
    stubs = native.missing_empty_cell_stubs(signal_text, used, model_text)
    unresolved = sorted(set(closure["unresolved"]) - set(stubs))
    if unresolved or closure["clashes"]:
        return commands.result(detail=f"GLS cell models incomplete: unresolved={unresolved}, "
            f"clashes={closure['clashes']}.")
    stub_file = directory / "physical_cells.v"
    stub_file.write_text("\n".join(f"module {name} (); endmodule" for name in stubs) + "\n")
    rows, reports = [], [stub_file, *projection_reports]
    for corner, sdf in sdfs.items():
        for bench in benches:
            work = directory / ("corner_" + str(len(rows) + 1))
            work.mkdir(parents=True, exist_ok=True)
            row = {"corner": corner, "testbench": str(bench), "status": "NOT_MEASURED",
                   "ran": False, "exit_code": None}
            clock_unmeasured = False
            models = [str(signal_netlist), *closure["files"], str(stub_file)]
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
                if sdc:
                    try:
                        clocks = native.declared_sdc_clocks(Path(sdc), [Path(sdf).read_text()])
                    except (OSError, ValueError) as exc:
                        row["detail"] = str(exc)
                        rows.append(row)
                        continue
                    if clocks["clocks_s"]:
                        periods = {name: format(Decimal(str(value)) / Decimal("1e-9"), "f")
                                   for name, value in clocks["clocks_s"].items()}
                        entry = work / "flow_clocked_suite.py"
                        entry.write_text("from decimal import Decimal\nfrom importlib import import_module\n"
                            f"suite = import_module({bench.stem!r})\nperiods = {periods!r}\n"
                            "clock = getattr(suite, 'CLK', None)\n"
                            "if (clock in periods and hasattr(suite, 'HALF_NS')\n"
                            "        and callable(getattr(suite, '_start_clock', None))):\n"
                            "    suite.HALF_NS = Decimal(periods[clock]) / 2\n"
                            "    print(f'COCOTB_CLOCK_NS {clock}={periods[clock]}', flush=True)\n"
                            "else:\n    clock = None\n"
                            "if set(periods) != ({clock} if clock else set()):\n"
                            "    print('COCOTB_CLOCK_UNBOUND: suite has no supported clock setting', flush=True)\n"
                            "globals().update({name: value for name, value in vars(suite).items()\n"
                            "                  if not name.startswith('__')})\n")
                        module = entry.stem
                        row["clock"] = clocks
                        reports.append(entry)
                makefile.write_text("SIM = icarus\nTOPLEVEL_LANG = verilog\n"
                    f"VERILOG_SOURCES = {sources}\nCOCOTB_TOPLEVEL = flow_sdf_tb\n"
                    f"COCOTB_TEST_MODULES = {module}\n"
                    f"COMPILE_ARGS += {compile_flags}\n"
                    "COCOTB_PLUSARGS += -sdf-info\nSIM_BUILD = build\nCOCOTB_RESULTS_FILE = results.xml\n"
                    f"export PYTHONPATH := {str(work).replace('$', '$$')}:{str(bench.parent).replace('$', '$$')}:$(PYTHONPATH)\n"
                    "include $(shell cocotb-config --makefiles)/Makefile.sim\n")
                completed = commands.run(["make", "-f", makefile, "-j8"], cwd=work)
                clock_unmeasured = (completed is not None and "COCOTB_CLOCK_UNBOUND:" in
                                    completed.stdout + completed.stderr)
                summary = parse_junit(work / "results.xml")
                functional = (summary if summary and summary["tests"] > 0 and not summary["skipped"] else None)
                failures = functional["failures"] + functional["errors"] if functional else None
                passed = functional["passed"] if functional else None
                total = functional["tests"] if functional else None
                reports.extend([shim, makefile, work / "results.xml"])
            else:
                import arith_oracle_tb_gen as arithmetic
                tb_text = native.strip_comments(bench.read_text())
                module = native._TB_MODULE_RE.search(tb_text)
                plan = arithmetic._scenario_header(bench)
                manifest = bench.parent / "arith_oracle_manifest.json"
                sample = json.loads(manifest.read_text()) if manifest.is_file() else {}
                generated = (sample.get("topology") == "serial_parallel"
                             and project / sample.get("tb", "") == bench)
                try:
                    if module and (plan or generated):
                        from _specrtl_common import parse_rtl_ports
                        _, ports = parse_rtl_ports(text, top)
                        inout_ports = {port.name for port in ports if port.direction == "inout"}
                        if not sdc:
                            raise ValueError("The generated arithmetic bench needs the native timing SDC.")
                        if plan:
                            spec = plan["spec"]
                        else:
                            from professional_tb_gen import _detect_ic_class
                            spec, why = arithmetic.extract_serial_arith_spec(project, _detect_ic_class(project))
                            if spec is None:
                                raise ValueError(why)
                        logical_top = spec["top"]
                        binding = ({"dut_module": top, "rebound": top != logical_top, "port_map": {}}
                                   if not (project / native.CHIP_TOP_RECORD_REL).is_file()
                                   else native.declared_dut_binding(project, logical_top, text))
                        clocks = native.declared_sdc_clocks(Path(sdc), [Path(sdf).read_text()])
                        clock = binding["port_map"].get(spec["clk"], spec["clk"]) if binding.get("port_map") else spec["clk"]
                        period = clocks["clocks_s"][clock] / 1e-9
                        folder = Path(sdf).parent.parent
                        if plan and (project / native.CHIP_TOP_RECORD_REL).is_file() and binding["rebound"]:
                            _, observation = native._bound_arithmetic_case(project,
                                {"path": bench, "text": tb_text, "module": module[1]}, logical_top,
                                binding, closure["files"], netlist=Path(netlist), sdc=Path(sdc),
                                sdfs=native_sdfs, sta_step_dir=folder, existing_plan=plan)
                            plan["observation"] = observation
                        else:
                            timed_plan = plan or {"spec": spec, "observation": {"clock_period_ns": period}}
                            deadline = native._postlayout_output_deadline(project, timed_plan, binding,
                                Path(netlist), Path(sdc), native_sdfs, sta_step_dir=folder)
                            observation = {**timed_plan["observation"], "top": top,
                                "sample_offset_ns": deadline["sample_offset_ns"], "postlayout_deadline": deadline}
                            if plan:
                                plan["observation"] = observation
                                if plan.get("reset_observation") and top != logical_top:
                                    sources = [Path(p) if Path(p).is_absolute() else project / p
                                               for p in config.get("VERILOG_FILES") or []]
                                    cores = [name for source in sources
                                             for name, (master, _) in native._instances(
                                                 native.strip_comments(source.read_text())).items()
                                             if master == logical_top]
                                    if len(cores) != 1:
                                        raise ValueError("The arithmetic reset observer needs the declared core instance.")
                                    observation["reset_state_targets"] = arithmetic.mapped_reset_state_targets(
                                        plan, text, cores[0])
                        port_map = binding.get("port_map") or {}
                        spec = json.loads(json.dumps(spec))
                        for key in ("parallel", "serial_in", "serial_out", "clk", "rst"):
                            spec[key] = port_map.get(spec[key], spec[key])
                        for port in spec["ports"]:
                            port["name"] = port_map.get(port["name"], port["name"])
                        if plan:
                            plan["spec"] = spec
                            tb_text = arithmetic.emit_arithmetic_scenario_module(module[1], plan,
                                dut_module=top, inout_ports=inout_ports)
                        else:
                            tb_text = arithmetic.emit_serial_oracle_module(module[1], spec,
                                arithmetic.select_operand_pairs(spec, "mixed"), dut_module=top,
                                clock_period_ns=period, sample_offset_ns=observation["sample_offset_ns"],
                                inout_ports=inout_ports)
                        row["observation"] = observation
                    instance = native._tb_dut_instance(tb_text, top)
                    if sdc and instance and not (plan or generated):
                        clocks = native.declared_sdc_clocks(Path(sdc), [Path(sdf).read_text()])
                        tb_text, row["clock"] = native.bind_bench_clock(tb_text, instance, clocks)
                except (OSError, ValueError, KeyError) as exc:
                    row["detail"] = str(exc)
                    rows.append(row)
                    continue
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
                      "PASS" if applied and failures == 0 and not clock_unmeasured else "NOT_MEASURED")
            detail = ("Icarus reported no applied SDF delay records. " if not applied else "")
            if clock_unmeasured:
                detail += "The Python suite has no supported setting for every native SDC clock. "
            if failures is None:
                detail += "No native self-check or complete JUnit functional verdict was produced. "
            row.update(ran=True, exit_code=completed.returncode, status=status, tests=total,
                       passed=passed, failures=failures, sdf_delays_applied=applied, sdf_errors=errors,
                       detail=detail + "Icarus does not implement SDF timing checks; setup/hold remain STA checks.")
            rows.append(row)
    summary = directory / "gls.json"
    summary.write_text(json.dumps({"runs": rows, "cell_models": closure,
        "physical_only_types_omitted": physical,
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
        f"Signal simulation omits physical-only cell types: {physical}. "
        "The full existing suite is replayed; no timing annotation means NOT_MEASURED.")
    result["native_steps"] = [{"name": "Icarus.GLS", **row} for row in rows]
    return result
