#!/usr/bin/env python3
"""Run native PPA searches and retain completed native physical views.

LibreLane synthesis candidates use minimum synthesis area ordering, not a
claim of optimal final PPA. AutoTuner supplies its own PPAImprov ordering.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import vibeic_temp as _vtmp
from typing import Literal, Mapping
import uuid

Arm = Literal["librelane-synthesis", "librelane-optimizing", "orfs-autotuner"]
ARMS = ("librelane-synthesis", "librelane-optimizing", "orfs-autotuner")


@dataclass(frozen=True)
class Orfs:
    root: Path
    platform: str
    native_space: Path


@dataclass(frozen=True)
class Budget:
    samples: int = 200
    jobs: int = 8
    threads: int = 2


@dataclass(frozen=True)
class NativeBest:
    index: Path
    run: Path


@dataclass(frozen=True)
class Incomplete:
    status: Literal["FAIL", "NOT_MEASURED"]
    reason: str
    reports: tuple[Path, ...] = ()


class _Unavailable(Exception):
    pass


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _files(value) -> list[Path]:
    if isinstance(value, Mapping):
        return list(dict.fromkeys(p for item in value.values() for p in _files(item)))
    if isinstance(value, (list, tuple)):
        return list(dict.fromkeys(p for item in value for p in _files(item)))
    return [Path(str(value))] if value is not None and str(value) else []


def _command(argv: list[str], cwd: Path, log: Path, env: dict | None = None):
    from _watchdog import run_host_supervised

    with _vtmp.TemporaryDirectory(prefix="level3-") as temporary:
        child_env = dict(os.environ)
        child_env.update(env or {})
        child_env["TMPDIR"] = temporary
        result = run_host_supervised(argv, cwd=str(cwd), env=child_env, log_path=log)
    log.write_text(result.out + result.err)
    return result


def _snapshot(project: Path, destination: Path) -> None:
    for relative in ("input", "phase1/generated_docs", "phase2/stage1/rtl"):
        source = project / relative
        if source.is_dir():
            shutil.copytree(source, destination / relative,
                            ignore=shutil.ignore_patterns("flow109", "__pycache__"))
    sdc = project / "phase3/stage3/pnr/constraint.sdc"
    if sdc.is_file():
        target = destination / sdc.relative_to(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sdc, target)
    declaration = project / "plugin_output/declaration.json"
    if declaration.is_file():
        top = _load(declaration).get("top_module")
        if top:
            _write(destination / "plugin_output/declaration.json", {"top_module": top})


def _prepare(project: Path, route: str, pdk_root: Path):
    import flow_config
    from librelane.flows import Flow

    os.environ["PDK_ROOT"] = str(pdk_root)
    core = flow_config.build_config(project, route=route)
    l19 = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    fields = _load(l19).get("fields", {}) if l19.is_file() else {}
    fixed = flow_config._settings(fields, core["PDK"])
    fixed.update({key: core[key] for key in ("CLOCK_PORT", "CLOCK_PERIOD", "DIE_AREA", "CORE_AREA")
                  if key in core})
    config = flow_config.build_native_config(project, route=route)
    owner = Flow.factory.get("Chip" if route == "ic" else "Classic")(
        config, design_dir=str(project), pdk_root=str(pdk_root))
    owner.config = flow_config.native_defaults(owner.config)
    return owner, fixed


def _declared_checks(project: Path, config, metrics) -> None:
    from flow_config import _settings, declared_fanout_checks, declared_power_checks
    import fnmatch

    l19 = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    fields = _load(l19).get("fields", {}) if l19.is_file() else {}
    declared = _settings(fields, config.get("PDK", ""))
    checks = [*declared_fanout_checks(project, config=config, metrics=metrics),
              *declared_power_checks(project, config=config, metrics=metrics)]
    for key, metric in (("MAX_TRANSITION_CONSTRAINT", "design__max_slew_violation__count*"),
                        ("MAX_CAPACITANCE_CONSTRAINT", "design__max_cap_violation__count*")):
        if key in declared:
            checks.append({"metric": metric, "operator": "==", "limit": 0,
                           "declaration": f"{key}={declared[key]}"})
    for check in checks:
        if check.get("applicable") is False:
            raise _Unavailable(check["reason"])
        values = [Decimal(str(value)) for key, value in metrics.items()
                  if fnmatch.fnmatch(key, check["metric"]) and value is not None]
        if not values:
            raise _Unavailable(f"No native metric for declared limit {check['metric']}")
        bounds = check["limit"]
        if check["operator"] == "==":
            failed = any(value != Decimal(str(bounds)) for value in values)
        else:
            failed = any(("max" in bounds and (value > bounds["max"] or
                         value == bounds["max"] and bounds.get("max_exclusive"))) or
                         ("min" in bounds and (value < bounds["min"] or
                         value == bounds["min"] and bounds.get("min_exclusive"))) for value in values)
        if failed:
            raise RuntimeError(f"Native {check['metric']} violates original limit {check.get('declaration', bounds)}")


def _native_violation_checks(metrics) -> None:
    for name in ("design__max_slew_violation__count", "design__max_cap_violation__count",
                 "design__max_fanout_violation__count", "timing__setup_vio__count",
                 "timing__hold_vio__count"):
        values = {key: value for key, value in metrics.items()
                  if key == name or key.startswith(name + "__corner:")}
        if not values or any(value is None for value in values.values()):
            raise _Unavailable(f"No native metric for {name}")
        for key, value in values.items():
            if Decimal(str(value)) > 0:
                raise RuntimeError(f"Native {key}={value} violates original limit (violation count > 0)")


def _export(completed: dict, original: Path, destination: Path, run_dir: Path) -> NativeBest:
    groups = {key: _files(completed.get(key)) for key in
              ("settings", "odb", "def", "netlist", "sdc", "liberty", "spef", "reports", "metrics")}
    for key, paths in groups.items():
        if not paths or any(not path.is_file() for path in paths):
            raise _Unavailable(f"Native completion lacks {key} files")
    if any(len(groups[key]) != 1 for key in ("odb", "def", "netlist")):
        raise _Unavailable("Native completion must identify one final ODB, DEF and netlist")
    documents = [path for directory in (original / "input", original / "phase1/generated_docs")
                 for path in sorted(directory.rglob("*")) if path.is_file()
                 and "flow109" not in path.relative_to(original).parts]
    declared_sdc = original / "phase3/stage3/pnr/constraint.sdc"
    if declared_sdc.is_file():
        documents.append(declared_sdc)
    if not documents:
        raise _Unavailable("Original design documents are absent")
    index = {"documents": []}
    for source in documents:
        relative = Path("documents") / source.relative_to(original)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        index["documents"].append(str(relative))
    for key, paths in groups.items():
        copied = []
        for source in paths:
            relative = Path(key) / source.resolve().relative_to(source.resolve().anchor)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(str(relative))
        index[key] = copied[0] if key in ("odb", "def", "netlist") else copied
    _write(destination / "job.json", {"keep_run": True})
    _write(destination / "index.json", index)
    return NativeBest(destination / "index.json", run_dir)


def _ll_complete(owner, config, project: Path, root: Path) -> dict:
    closure = type(owner)(config, design_dir=str(project))
    state = closure.start(_force_run_dir=str(root))
    raw = state.to_raw_dict()
    _native_violation_checks(raw["metrics"])
    _declared_checks(project, closure.config, raw["metrics"])
    settings = root / "resolved.json"
    _write(settings, closure.config.to_raw_dict())
    metrics = root / "metrics.json"
    _write(metrics, raw["metrics"])
    return {"settings": [settings], "odb": raw.get("odb"), "def": raw.get("def"),
            "netlist": raw.get("pnl") or raw.get("nl"), "sdc": raw.get("sdc"), "spef": raw.get("spef"),
            "liberty": [*_files(closure.config.get("LIB")),
                        *_files(closure.config.get("PAD_LIBS")), *_files(raw.get("lib"))],
            "reports": [path for path in root.rglob("*") if path.is_file()
                        and path.suffix in {".rpt", ".log", ".xml", ".lyrdb"}],
            "metrics": [metrics, *root.rglob("or_metrics_out.json")]}


def _librelane(owner, fixed: dict, project: Path, tool: str, root: Path) -> dict:
    from librelane.flows import Flow

    incompatible = set(fixed) & ({"SYNTH_STRATEGY", "FP_CORE_UTIL"} if tool == "Optimizing"
                                  else {"SYNTH_STRATEGY"})
    if incompatible:
        raise _Unavailable(f"Native {tool} forcibly varies document-fixed {', '.join(sorted(incompatible))}")
    search = Flow.factory.get(tool)(owner.config)
    search.start(_force_run_dir=str(root / "search"))
    if tool == "Optimizing":
        selected = [step for step in search.step_objects if step.id.startswith("gpl-")
                    and step.state_out is not None][-1:]
        criterion = "Native Optimizing minimum synthesis area, then native utilization fallback."
    else:
        selected = sorted((step for step in search.step_objects if step.id.startswith("sta-")
                           and step.state_out is not None),
                          key=lambda step: step.state_out.metrics["design__instance__area"])
        criterion = "Minimum synthesis area from native SynthesisExploration; final PPA is not its objective."
    _write(root / "selection.json", {"criterion": criterion,
           "candidates": [step.id for step in selected]})
    if not selected:
        raise _Unavailable(f"Native {tool} returned no successful candidate State")
    errors = []
    for number, candidate in enumerate(selected):
        try:
            result = _ll_complete(owner, owner.config.copy(
                **{key: candidate.config[key] for key in ("SYNTH_STRATEGY", "FP_CORE_UTIL")
                   if key in candidate.config}), project, root / f"completion-{number}")
            result["settings"].append(root / "selection.json")
            result["reports"].extend(path for path in (root / "search").rglob("*")
                                     if path.is_file() and path.suffix in {".rpt", ".log"})
            return result
        except _Unavailable as exc:
            errors.append(("NOT_MEASURED", f"{candidate.id}: {exc}"))
        except Exception as exc:
            errors.append(("FAIL", f"{candidate.id}: {exc}"))
    if any(status == "NOT_MEASURED" for status, _ in errors):
        raise _Unavailable("; ".join(reason for _, reason in errors))
    raise RuntimeError("; ".join(reason for _, reason in errors))


def _mk(value) -> str:
    text = " ".join(map(str, value)) if isinstance(value, (tuple, list)) else str(value)
    if any(character in text for character in ("\n", "\r", "#", "$")):
        raise _Unavailable("Native make settings contain unsupported make metacharacters")
    return text


def _tcl(value) -> str:
    if isinstance(value, Mapping):
        return "[dict create " + " ".join(_tcl(item) for pair in value.items() for item in pair) + "]"
    if isinstance(value, (list, tuple)):
        return "[list " + " ".join(_tcl(item) for item in value) + "]"
    if isinstance(value, bool):
        return str(int(value))
    return "{" + str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}") + "}"


ORFS_SETTINGS = {"FP_CORE_UTIL": ("CORE_UTILIZATION", 1),
                 "PL_TARGET_DENSITY_PCT": ("PLACE_DENSITY", .01)}


def _orfs_sdc(original: Path, declared: dict, destination: Path) -> None:
    from flow_chip_inputs import _electrical_sdc

    electrical = _electrical_sdc(declared)
    if not electrical:
        shutil.copy2(original, destination)
        return
    preserved = destination.with_name("constraint-original.sdc")
    shutil.copy2(original, preserved)
    # OpenSTA setters replace same-object bounds.
    prefix = '''namespace eval ::level3_sdc {
  variable original [dict create]
  variable merge 0
  proc limit {command code result op} {
    variable original
    variable merge
    if {$code != 0} {return}
    set key [list [namespace tail [lindex $command 0]] {*}[lrange $command 1 2]]
    set value [lindex $command 3]
    if {!$merge} {
      dict set original $key $value
    } elseif {[dict exists $original $key] && [dict get $original $key] < $value} {
      namespace eval ::sta [lreplace $command 3 3 [dict get $original $key]]
    }
  }
}
foreach command {set_cell_fanout_limit set_slew_limit_cell set_pin_capacitance_limit} {
  trace add execution ::sta::$command leave ::level3_sdc::limit
}
try {
'''
    suffix = '''
} finally {
  foreach command {set_cell_fanout_limit set_slew_limit_cell set_pin_capacitance_limit} {
    trace remove execution ::sta::$command leave ::level3_sdc::limit
  }
  namespace delete ::level3_sdc
}
'''
    destination.write_text(prefix + f"source {_tcl(preserved)}\nset ::level3_sdc::merge 1\n" +
                           "\n".join(electrical) + suffix)


def _orfs_inputs(owner, fixed: dict, install: Orfs, root: Path) -> tuple[Path, Path, list[Path]]:
    from librelane.common import Toolbox

    if not re.fullmatch(r"[\w.-]+", install.platform):
        raise _Unavailable("ORFS platform must name one explicit installed platform")
    if "SYNTH_STRATEGY" in fixed:
        raise _Unavailable("ORFS has no translation for document-fixed LibreLane SYNTH_STRATEGY")
    native = root / "native"
    shutil.copytree(install.root / "flow", native / "flow", symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "designs", "logs", "reports", "results", "objects"))
    shutil.copytree(install.root / "tools/AutoTuner", native / "tools/AutoTuner", symlinks=True)
    for directory in (native, *[path for path in native.rglob("*") if path.is_dir() and not path.is_symlink()]):
        directory.chmod(directory.stat().st_mode | 0o700)
    if (install.root / "tools/install").is_dir():
        (native / "tools/install").symlink_to(install.root / "tools/install", target_is_directory=True)
    platform = native / "flow/platforms" / install.platform
    if not (platform / "config.mk").is_file():
        raise _Unavailable(f"ORFS installed platform is missing: {install.platform}")
    config = owner.config
    top = str(config["DESIGN_NAME"])
    if not re.fullmatch(r"[\w.-]+", top):
        raise _Unavailable("ORFS design name cannot be represented as a native path")
    directory = native / "flow/designs" / install.platform / top
    directory.mkdir(parents=True, exist_ok=True)
    toolbox = Toolbox(str(root / "tool_tmp"))
    lib = toolbox.filter_views(config, config["LIB"])
    tech = toolbox.filter_views(config, config["TECH_LEFS"])
    cell_lefs = _files(config["CELL_LEFS"])
    if not cell_lefs:
        raise _Unavailable("Selected native library has no cell LEF")
    values = {"DESIGN_NAME": top, "VERILOG_FILES": config["VERILOG_FILES"],
              "VERILOG_INCLUDE_DIRS": config.get("VERILOG_INCLUDE_DIRS") or [],
              "TECH_LEF": tech, "SC_LEF": cell_lefs[0], "ADDITIONAL_LEFS": cell_lefs[1:], "LIB_FILES": lib,
              "PLACE_SITE": config["PLACE_SITE"]}
    cdls = [*_files(config.get("CELL_CDLS")), *_files(config.get("PAD_CDLS")),
            *_files(config.get("EXTRA_CDLS"))]
    if cdls:
        values["CDL_FILE"] = cdls
    for source, target in (("SYNTH_FA_MAP", "ADDER_MAP_FILE"),
                           ("SYNTH_LATCH_MAP", "LATCH_MAP_FILE")):
        if config.get(source):
            values[target] = config[source]
    for source, target in (("SYNTH_TIEHI_CELL", "TIEHI_CELL_AND_PORT"),
                           ("SYNTH_TIELO_CELL", "TIELO_CELL_AND_PORT"),
                           ("SYNTH_BUFFER_CELL", "MIN_BUF_CELL_AND_PORTS")):
        if config.get(source):
            values[target] = str(config[source]).replace("/", " ")
    if config.get("SYNTH_DRIVING_CELL"):
        values["ABC_DRIVER_CELL"] = str(config["SYNTH_DRIVING_CELL"]).split("/")[0]
    for source, target in (("DIE_AREA", "DIE_AREA"), ("CORE_AREA", "CORE_AREA")):
        if config.get(source) is not None:
            values[target] = config[source]
    for key, (target, scale) in ORFS_SETTINGS.items():
        if key in fixed:
            values[target] = Decimal(str(fixed[key])) * Decimal(str(scale))
    if "DIE_AREA" in values:
        values["CORE_UTILIZATION"] = ""
    sdc = config.get("PNR_SDC_FILE")
    if sdc:
        _orfs_sdc(Path(sdc), fixed, directory / "constraint.sdc")
    else:
        from flow_chip_inputs import _ports, _sdc
        from librelane.state import DesignFormat, State
        from librelane.steps import Step
        header = Step.factory.get("Yosys.JsonHeader")(config, State())
        state = header.start(step_dir=str(root / "ports"), toolbox=toolbox)
        ports = _ports(_load(Path(state[DesignFormat.JSON_HEADER])), top)
        sdc = root / "document-constraints.sdc"
        sdc.write_text(_sdc(Path(config["DESIGN_DIR"]), config, ports))
        shutil.copy2(sdc, directory / "constraint.sdc")
    values["SDC_FILE"] = directory / "constraint.sdc"
    if any(key.startswith("PDN_") for key in fixed):
        raise _Unavailable("ORFS platform PDN cannot translate document-fixed native PDN settings")
    mk = directory / "config.mk"
    mk.write_text("\n".join(f"override export {key} = {_mk(value)}" for key, value in values.items()) + "\n")
    if config.get("PAD_SOUTH") or config.get("PAD_NORTH"):
        _orfs_chip(owner, directory, values)
    mk.write_text("\n".join(f"override export {key} = {_mk(value)}" for key, value in values.items()) + "\n")
    space = _load(install.native_space)
    for key, (target, _) in ORFS_SETTINGS.items():
        if key in fixed:
            space.pop(target, None)
    if "MAX_FANOUT_CONSTRAINT" in fixed:
        space.pop("MAX_FANOUT", None)
    if "CLOCK_PERIOD" in fixed:
        space.pop("_SDC_CLK_PERIOD", None)
    if "DIE_AREA" in values:
        space.pop("CORE_UTILIZATION", None)
        space.pop("CORE_ASPECT_RATIO", None)
    if any(key.startswith("_SDC_") for key in space):
        raise _Unavailable("AutoTuner SDC mutations cannot preserve the original declared SDC")
    space["_SDC_FILE_PATH"] = os.path.relpath(directory / "constraint.sdc", root)
    if "_FR_FILE_PATH" in space:
        shutil.copy2(install.native_space.parent / space["_FR_FILE_PATH"], root / "fastroute-original.tcl")
        space["_FR_FILE_PATH"] = "fastroute-original.tcl"
    search_space = root / "native-space.json"
    _write(search_space, space)
    return native, search_space, [*_files(config["LIB"]), *_files(config.get("PAD_LIBS"))]


def _orfs_chip(owner, directory: Path, values: dict) -> None:
    import librelane
    from librelane.common import Toolbox
    from librelane.state import State
    from librelane.steps import Step, TclStep

    config = owner.config
    preparation = _load(Path(config["DESIGN_DIR"]) / "work/flow/chip/preparation.json")
    wrapper = Path(config["VERILOG_FILES"][-1])
    unpowered = directory / "wrapper.v"
    result = _command(["iverilog", "-g2012", "-E", "-o", str(unpowered), str(wrapper)],
                      directory, directory / "preprocess.log")
    if result.rc:
        raise _Unavailable("Native preprocessor could not prepare the physical wrapper")
    text = unpowered.read_text()
    for instance, entry in preparation["pads"].items():
        pins = set(entry.get("power_connections", {})) | set(entry.get("supply_connections", {}))
        pattern = re.compile(r"(" + re.escape(entry["master"]) + r"\s+" + re.escape(instance)
                             + r"\s*\()(.*?)(\)\s*;)", re.S)
        def functional(match):
            ports = re.findall(r"\.(\w+)\s*\(([^()]*)\)", match[2])
            return match[1] + ", ".join(f".{pin}({net})" for pin, net in ports if pin not in pins) + match[3]
        text = pattern.sub(functional, text)
    supplies = {entry["port"] for entry in preparation["pads"].values() if entry.get("is_supply_pad")}
    start, end = text.index("("), text.index(");")
    ports = [port for port in text[start + 1:end].split(",")
             if not any(re.search(r"\b" + re.escape(name) + r"\b", port) for name in supplies)]
    text = (text[:start + 1] + ",".join(ports) + text[end:end + 2] +
            ("\nwire " + ", ".join(sorted(supplies)) + ";\n" if supplies else "") + text[end + 2:])
    unpowered.write_text(text)
    values["VERILOG_FILES"] = [*config["VERILOG_FILES"][:-1], unpowered]
    toolbox = Toolbox(str(directory / "tool_tmp"))
    step = Step.factory.get("OpenROAD.GeneratePDN")(config, State())
    step.toolbox = toolbox
    step.step_dir = str(directory)
    env = step.prepare_env({}, State())
    env.update({key: TclStep.value_to_tcl(value) for key, value in config.items()
                if key.startswith("PAD_") and value is not None})
    scripts = Path(librelane.__file__).parent / "scripts"
    env_script = directory / "native-env.tcl"
    env_script.write_text("\n".join(f"set ::env({key}) {_tcl(value)}" for key, value in env.items()
                                   if key not in {"SCRIPTS_DIR"}) + "\n")
    prefix = ["set _orfs_scripts $::env(SCRIPTS_DIR)", f"source {_tcl(env_script)}",
              f"set ::env(SCRIPTS_DIR) {_tcl(scripts)}"]
    pads = []
    global_connections = []
    from flow_chip_inputs import _library
    roles = _library(config)["roles"]
    for instance, entry in preparation["pads"].items():
        if entry.get("is_supply_pad") or entry.get("is_ring_connector"):
            pads.append(f"if {{[[ord::get_db_block] findInst {_tcl(instance)}] == \"NULL\"}} {{"
                        f"odb::dbInst_create [ord::get_db_block] [[ord::get_db] findMaster {_tcl(entry['master'])}] {_tcl(instance)}}}")
        for pin, net in {**entry.get("power_connections", {}), **entry.get("supply_connections", {})}.items():
            kind = roles.get(entry["master"], {}).get(pin, (None, None))[1]
            option = " -ground" if kind == "GROUND" else " -power" if kind == "POWER" else ""
            global_connections.append(f"add_global_connection -net {_tcl(net)} -inst_pattern {_tcl('^' + re.escape(instance) + '$')}"
                                      f" -pin_pattern {_tcl('^' + re.escape(pin) + '$')}{option}")
    for site, dimensions in (config.get("PAD_FAKE_SITES") or {}).items():
        pads.append(f"make_fake_io_site -name {_tcl(site)} -width {dimensions[0]} -height {dimensions[1]}")
    io = directory / "io.tcl"
    io.write_text("\n".join(prefix + pads + global_connections + [f"source {_tcl(scripts / 'openroad/common/set_power_nets.tcl')}",
        f"source {_tcl(config.get('PAD_CFG') or scripts / 'openroad/common/pad_cfg.tcl')}",
        "set ::env(SCRIPTS_DIR) $_orfs_scripts"]) + "\n")
    flow = directory.parents[2]
    variables = ("PDN_TCL", "PWR_NETS_VOLTAGES", "GND_NETS_VOLTAGES")
    platform = _command(["make", "-s", "-C", str(flow), f"DESIGN_CONFIG={directory / 'config.mk'}",
        f"PLATFORM={directory.parent.name}", *["print-" + key for key in variables]], flow,
        directory / "platform.log")
    defaults = {key: value.strip() for line in platform.out.splitlines()
                for key, separator, value in [line.partition(":")] if separator and key in variables}
    if platform.rc or not all(defaults.get(key) for key in variables):
        raise _Unavailable("ORFS platform did not resolve its native PDN and supply defaults")
    native_pdn = Path(defaults["PDN_TCL"])
    if not native_pdn.is_absolute():
        native_pdn = flow / native_pdn
    text = native_pdn.read_text()
    for variable, native_key in (("PWR_NETS_VOLTAGES", "VDD_NETS"), ("GND_NETS_VOLTAGES", "GND_NETS")):
        supply = defaults[variable].split()
        if len(supply) != 2 or len(config[native_key]) != 1:
            raise _Unavailable("ORFS platform PDN requires an explicit supported supply-domain translation")
        old, voltage = supply
        net = str(config[native_key][0])
        text = re.sub(r"(-(?:net|power|ground)\s+)(?:\{" + re.escape(old) + r"\}|" + re.escape(old)
                      + r")(?=\s|$)", lambda match: match[1] + _tcl(net), text)
        values[variable] = [net, voltage]
    pdn = directory / "pdn.tcl"
    pdn.write_text("\n".join(global_connections) + "\n" + text)
    values.update(ADDITIONAL_LEFS=[*values["ADDITIONAL_LEFS"], *_files(config.get("PAD_LEFS"))],
                  ADDITIONAL_GDS=_files(config.get("PAD_GDS")),
                  LIB_FILES=[*values["LIB_FILES"], *toolbox.filter_views(config, config["PAD_LIBS"])],
                  FOOTPRINT_TCL=io, PDN_TCL=pdn)


def _orfs_verdict(project: Path, config, logs: Path, reports: Path, results: Path, metrics: Path):
    import klayout.db as db

    report = logs / "6_report.log"
    if not report.is_file():
        raise _Unavailable("No native ORFS final report")
    text = report.read_text(errors="replace")
    for name in ("setup", "hold", "max slew", "max cap", "max fanout"):
        matches = re.findall(re.escape(name) + r" violation count\s+(\d+)", text)
        if not matches:
            raise _Unavailable(f"Native ORFS final report has no {name} violation count")
        if int(matches[-1]):
            raise RuntimeError(f"Native ORFS {name} violations: {matches[-1]}")
    drc = reports / "6_drc_count.rpt"
    if not drc.is_file():
        raise _Unavailable("No native ORFS KLayout DRC count")
    if int(drc.read_text().strip()):
        raise RuntimeError("Native ORFS KLayout DRC violations")
    lvs = results / "6_lvs.lvsdb"
    if not lvs.is_file() or lvs.read_bytes().startswith(b"LVS not supported"):
        raise _Unavailable("No native ORFS KLayout LVS comparison")
    database = db.LayoutVsSchematic()
    database.read(str(lvs))
    pairs = list(database.xref().each_circuit_pair())
    if not pairs:
        raise _Unavailable("Native ORFS KLayout LVS comparison has no circuit results")
    if any(pair.status not in (db.NetlistCrossReference.Match, db.NetlistCrossReference.MatchWithWarning)
           for pair in pairs):
        raise RuntimeError("Native ORFS KLayout LVS mismatch")
    stages = _load(metrics)
    final = dict(stages.get("finish", {}))
    final["design__max_fanout_violation__count"] = int(re.findall(
        r"max fanout violation count\s+(\d+)", text)[-1])
    if "power__total" in final:
        final[f"power__total__corner:{config['DEFAULT_CORNER']}"] = final["power__total"]
    _declared_checks(project, config, final)


def _orfs(owner, fixed: dict, project: Path, install: Orfs, budget: Budget, root: Path) -> dict:
    threads = min(8, budget.threads)
    launcher = shutil.which("autotuner-python")
    if not launcher:
        raise _Unavailable("Missing autotuner-python launcher and isolated native AutoTuner dependencies")
    checked = _command([launcher, "-c", "import ray, hyperopt, optuna, ax"], root,
                       root / "autotuner-import.log")
    if checked.rc:
        raise _Unavailable("Native AutoTuner dependency import failed; see autotuner-import.log")
    native, space, liberty = _orfs_inputs(owner, fixed, install, root)
    flow = native / "flow"
    top = str(owner.config["DESIGN_NAME"])
    design = f"designs/{install.platform}/{top}/config.mk"
    work = flow
    common = ["make", "-C", str(flow), f"DESIGN_CONFIG={design}", f"PLATFORM={install.platform}",
              f"WORK_HOME={work}", f"NUM_CORES={threads}", "SHELL=bash"]
    for tool in ("OPENROAD", "YOSYS"):
        executable = shutil.which(tool.lower())
        if executable:
            common.append(f"{tool}_EXE={executable}")
    stock = _command([*common, "FLOW_VARIANT=level3-stock", "finish"], flow, root / "stock.log")
    if stock.rc:
        raise RuntimeError(f"Native ORFS stock reference failed with exit {stock.rc}")
    def metric(variant: str) -> tuple[Path, Path, Path, Path]:
        tail = Path(install.platform) / top / variant
        logs, reports, results = [work / part / tail for part in ("logs", "reports", "results")]
        target = logs / "metrics.json"
        command = _command([sys.executable, str(flow / "util/genMetrics.py"), "-x", "-v", variant,
            "-d", top, "-p", install.platform, "--logs", str(logs), "--reports", str(reports),
            "--results", str(results), "-o", str(target)], flow, logs / "collect.log")
        if command.rc or not target.is_file():
            raise _Unavailable(f"Native ORFS metrics absent for {variant}")
        return logs, reports, results, target
    reference = metric("level3-stock")[-1]
    experiment = "level3-" + uuid.uuid4().hex[:12]
    env = {"PYTHONPATH": str(native / "tools/AutoTuner/src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    for tool in ("OPENROAD", "YOSYS"):
        executable = shutil.which(tool.lower())
        if executable:
            env[f"{tool}_EXE"] = executable
    tuner = _command([launcher, "-m", "autotuner.distributed", "--design", top,
        "--platform", install.platform, "--config", str(space), "--experiment", experiment,
        "--work-dir", str(work), "--stop_stage", "finish", "--jobs", str(budget.jobs),
        "--openroad_threads", str(threads), "tune", "--algorithm", "hyperopt",
        "--eval", "ppa-improv", "--reference", str(reference), "--samples", str(budget.samples),
        "--seed", "42"], native / "tools/AutoTuner", root / "autotuner.log", env)
    if tuner.rc:
        raise RuntimeError(f"Native AutoTuner failed with exit {tuner.rc}")
    trial_root = native / "flow/logs" / install.platform / top / experiment
    trials = []
    for path in sorted(trial_root.glob("variant-PPAImprov-*-ray/result.json")):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if rows:
            last = rows[-1]
            score = last.get("metric")
            if isinstance(score, (int, float)) and math.isfinite(score) and score < 9e99:
                trials.append((score, last, path))
    errors = []
    for _, trial, path in sorted(trials, key=lambda row: row[0]):
        trial_id = trial["trial_id"]
        iteration = int(trial["training_iteration"]) - 1
        variant = f"{experiment}/variant-PPAImprov-{trial_id}-or-{iteration}"
        try:
            settings = path.parent / "params.json"
            import shlex
            parameters_file = path.parent / "parameters.json"
            parsed = _command([launcher, "-c", (
                "import json,sys; from pathlib import Path; from autotuner.utils import parse_config; "
                "params,base,platform,sdc,fr,out=sys.argv[1:]; "
                "options=parse_config(json.loads(Path(params).read_text()),base,platform,"
                "Path(sdc).read_text(),'constraint.sdc',Path(fr).read_text() if Path(fr).is_file() else '',"
                "'fastroute.tcl',str(Path(out).parent)); "
                "Path(out).write_text(json.dumps(options))"), str(settings), str(native),
                install.platform, str((flow / design).with_name("constraint.sdc")), str(root / "fastroute-original.tcl"),
                str(parameters_file)], path.parent, path.parent / "parameters.log", env)
            if parsed.rc:
                raise _Unavailable("Native AutoTuner could not decode exact trial settings")
            parameters = json.loads(parameters_file.read_text())
            finished = _command([*common, f"FLOW_VARIANT={variant}", *shlex.split(parameters),
                                 "finish", "drc", "lvs"], flow, path.parent / "closure.log")
            if finished.rc:
                raise RuntimeError(f"Native ORFS completion exit {finished.rc}")
            logs, reports, results, metrics = metric(variant)
            _orfs_verdict(project, owner.config, logs, reports, results, metrics)
            return {"settings": [flow / design, space, settings], "odb": results / "6_final.odb",
                    "def": results / "6_final.def", "netlist": results / "6_final.v",
                    "sdc": sorted(results.glob("6_final*.sdc")), "liberty": liberty,
                    "spef": sorted(results.glob("6_final*.spef")),
                    "reports": [results / "6_lvs.lvsdb", *[p for base in (logs, reports)
                                  for p in base.rglob("*") if p.is_file()]],
                    "metrics": [metrics, reference]}
        except _Unavailable as exc:
            errors.append(("NOT_MEASURED", f"{trial_id}: {exc}"))
        except Exception as exc:
            errors.append(("FAIL", f"{trial_id}: {exc}"))
    if not trials:
        raise _Unavailable("Native AutoTuner left no scored trial result records")
    if any(status == "NOT_MEASURED" for status, _ in errors):
        raise _Unavailable("; ".join(reason for _, reason in errors))
    raise RuntimeError("; ".join(reason for _, reason in errors))


def _native(job: Path) -> int:
    data = _load(job)
    root, project = Path(data["root"]), Path(data["project"])
    try:
        owner, fixed = _prepare(project, data["route"], Path(data["pdk_root"]))
        if data["arm"] == "orfs-autotuner":
            install = data["orfs"]
            completed = _orfs(owner, fixed, project, Orfs(Path(install["root"]), install["platform"],
                Path(install["native_space"])), Budget(**data["budget"]), root)
        else:
            completed = _librelane(owner, fixed, project,
                "Optimizing" if data["arm"] == "librelane-optimizing" else "SynthesisExploration", root)
        _write(root / "completed.json", completed)
        return 0
    except (ImportError, FileNotFoundError, _Unavailable) as exc:
        status, reason = "NOT_MEASURED", str(exc)
    except Exception as exc:
        status, reason = "FAIL", str(exc)
    _write(root / "incomplete.json", {"status": status, "reason": reason})
    return 2 if status == "NOT_MEASURED" else 1


def run(project: Path, *, output: Path, route: Literal["ic", "ip"], pdk_root: Path,
        orfs: Orfs | None = None, budget: Budget = Budget()) -> Mapping[Arm, NativeBest | Incomplete]:
    project, output, pdk_root = Path(project).resolve(), Path(output).resolve(), Path(pdk_root).resolve()
    allowed = (_vtmp.root() / "runs").resolve()
    if not output.is_relative_to(allowed):
        raise ValueError(f"Level 3 output must be under {allowed}")
    if route not in {"ic", "ip"} or min(budget.samples, budget.jobs, budget.threads) < 1:
        raise ValueError("Use route ic or ip and positive native search budgets")
    root = output / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-level3-" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    _write(root / "job.json", {"keep_run": True})
    results = {}
    for arm in ARMS:
        if arm == "orfs-autotuner" and orfs is None:
            results[arm] = Incomplete("NOT_MEASURED", "No explicit ORFS installation, platform and native search space")
            continue
        directory = root / arm
        directory.mkdir()
        copied = directory / "project"
        _snapshot(project, copied)
        job = directory / "job.json"
        _write(job, {"keep_run": True, "root": directory, "project": copied, "route": route,
            "pdk_root": pdk_root, "arm": arm, "orfs": asdict(orfs) if orfs else None,
            "budget": asdict(budget)})
        result = _command([sys.executable, str(Path(__file__).resolve()), "--native-job", str(job)],
                          directory, directory / "native.log", {"PDK_ROOT": str(pdk_root),
                          "_OPENLANE_MAX_CORES": str(min(8, budget.jobs * budget.threads))})
        failure = directory / "incomplete.json"
        try:
            if result.rc == 0 and (directory / "completed.json").is_file():
                results[arm] = _export(_load(directory / "completed.json"), project,
                                       directory / "handoff", directory)
            elif failure.is_file():
                failed = _load(failure)
                results[arm] = Incomplete(failed["status"], failed["reason"], (directory / "native.log", failure))
            else:
                results[arm] = Incomplete("FAIL" if result.rc else "NOT_MEASURED",
                    f"Native child exit {result.rc}, no native completion", (directory / "native.log",))
        except _Unavailable as exc:
            results[arm] = Incomplete("NOT_MEASURED", str(exc), (directory / "native.log",))
    _write(root / "results.json", {arm: asdict(result) for arm, result in results.items()})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-job", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--route", choices=("ic", "ip"))
    parser.add_argument("--pdk-root", type=Path)
    parser.add_argument("--orfs-root", type=Path)
    parser.add_argument("--platform")
    parser.add_argument("--native-space", type=Path)
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if args.native_job:
        return _native(args.native_job)
    if not all((args.project, args.output, args.route, args.pdk_root)):
        parser.error("--project, --output, --route and --pdk-root are required")
    if any((args.orfs_root, args.platform, args.native_space)) and not all((args.orfs_root, args.platform, args.native_space)):
        parser.error("ORFS requires --orfs-root, --platform and --native-space together")
    install = Orfs(args.orfs_root.resolve(), args.platform, args.native_space.resolve()) if args.orfs_root else None
    results = run(args.project, output=args.output, route=args.route, pdk_root=args.pdk_root,
                  orfs=install, budget=Budget(args.samples, args.jobs, args.threads))
    print(json.dumps({arm: asdict(result) for arm, result in results.items()}, indent=2, default=str))
    return 0 if any(isinstance(result, NativeBest) for result in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
