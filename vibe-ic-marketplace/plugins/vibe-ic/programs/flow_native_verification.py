from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import re
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

    project, directory = Path(project), Path(directory)
    top, netlist = config.get("DESIGN_NAME"), state.get("nl") if state is not None else None
    rtl = [Path(p) if Path(p).is_absolute() else project / p for p in config.get("VERILOG_FILES") or []]
    corner = config.get("DEFAULT_CORNER", "")
    libraries = config.get("CELL_LIBS") or config.get("LIB") or {}
    liberty = list(dict.fromkeys(str(path) for pattern, paths in libraries.items()
        if fnmatch.fnmatchcase(corner, pattern)
        for path in (paths if isinstance(paths, (list, tuple)) else [paths])))
    pad_liberty = list(dict.fromkeys(Path(path) for pattern, paths in (config.get("PAD_LIBS") or {}).items()
        if fnmatch.fnmatchcase(corner, pattern)
        for path in (paths if isinstance(paths, (list, tuple)) else [paths])))
    if (not top or not netlist or not Path(netlist).is_file() or not rtl
            or any(not path.is_file() for path in rtl) or not liberty
            or any(not Path(path).is_file() for path in [*liberty, *pad_liberty])):
        return commands.result(detail="EQY needs produced RTL, State netlist and the configured corner's Liberty models.")
    script = directory / "equivalence.eqy"
    script.write_text(reset_script(eqy_script(top, rtl, Path(netlist), " ".join(liberty),
                                 synthesis=config, views=directory, pad_liberty=pad_liberty), reset_boundary(project)))
    completed = commands.run(["eqy", "-j", "8", "-f", "-d", directory / "scratch", script])
    if completed is None:
        return commands.result(reports=[script], detail="The native EQY executable is unavailable.")
    status, count, detail, reports = eqy_partitions(directory / "scratch")
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
