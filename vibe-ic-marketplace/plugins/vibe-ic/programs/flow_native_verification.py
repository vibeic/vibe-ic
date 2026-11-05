from __future__ import annotations

import fnmatch
from pathlib import Path
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
    if (not top or not netlist or not Path(netlist).is_file() or not rtl
            or any(not path.is_file() for path in rtl) or not liberty
            or any(not Path(path).is_file() for path in liberty)):
        return commands.result(detail="EQY needs produced RTL, State netlist and the configured corner's Liberty models.")
    script = directory / "equivalence.eqy"
    script.write_text(eqy_script(top, rtl, Path(netlist), " ".join(liberty),
                                 synthesis=config, views=directory))
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
    metric = "design__xor_difference__count"
    value = state.metrics.get(metric) if state is not None else None
    if value is not None:
        result = commands.result({metric: value, tool.get("metric", metric): value},
                                 tool.get("reports", []), "Reused the native KLayout stream XOR count from State.")
        result.update(ran=True, exit_code=0)
        return result
    if state is None or state.get("mag_gds") is None or state.get("klayout_gds") is None:
        return commands.result(detail="KLayout.XOR needs the Magic and KLayout GDS views in State.")
    from librelane.config import Config
    from librelane.steps import StepError, StepException
    from librelane.steps.klayout import XOR

    class NativeXOR(XOR):
        def run_subprocess(self, cmd, *args, **kwargs):
            started, code = time.perf_counter(), None
            try:
                result = super().run_subprocess(cmd, *args, **kwargs)
                code = result["returncode"]
                return result
            except subprocess.CalledProcessError as exc:
                code = exc.returncode
                raise
            finally:
                commands.seconds += time.perf_counter() - started
                if code is not None:
                    commands.records.append({"command": list(map(str, cmd)), "exit_code": code,
                                             "log": str(directory / "klayout-xor.log")})

    native = NativeXOR(Config(config).copy(KLAYOUT_XOR_THREADS=8), state)
    detail, status = "Native KLayout stream XOR.", "PASS"
    try:
        output = native.start(step_dir=str(directory))
    except StepError as exc:
        return commands.result(reports=list(directory.glob("*.log")), detail=str(exc))
    except (StepException, FileNotFoundError) as exc:
        return commands.result(detail=str(exc))
    value = output.metrics.get(metric)
    metrics = {} if value is None else {metric: value, tool.get("metric", metric): value}
    if value is None:
        detail, status = "KLayout.XOR left no native difference count.", "NOT_MEASURED"
    elif value:
        status = "FAIL"
    result = commands.result(metrics, [directory / "xor.xml"], detail)
    result["native_steps"] = [{"name": "KLayout.XOR", "ran": bool(commands.records),
                               "exit_code": result["exit_code"], "status": status}]
    return result
