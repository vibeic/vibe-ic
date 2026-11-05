#!/usr/bin/env python3
"""Generate native Chip inputs from the elaborated core and active PDK."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any

import _l_doc_pad_placement as placement_docs
import _pad_ring as pads
import io_pad_chip_top_gen as electrical


SIDES = {"N": "NORTH", "E": "EAST", "S": "SOUTH", "W": "WEST"}


def _required(config: dict, key: str):
    value = config.get(key)
    if value is None or value == [] or value == {} or value == "":
        raise FileNotFoundError(f"Missing {key}")
    return value


def _ports(header: dict, top: str) -> list[dict]:
    result = []
    for name, port in header["modules"][top]["ports"].items():
        direction = port["direction"]
        if direction not in {"input", "output"}:
            raise ValueError(f"Unsupported inout port {name!r}: missing output-enable behavior")
        width = len(port["bits"])
        low = int(port.get("offset", 0))
        high = low + width - 1
        msb, lsb = (low, high) if port.get("upto") else (high, low)
        result.append({"name": name, "direction": direction, "width": width,
                       "msb": msb, "lsb": lsb,
                       "indexed": width > 1 or bool(low) or "upto" in port})
    return result


def _bits(port: dict) -> list[str]:
    if not port["indexed"]:
        return [port["name"]]
    step = 1 if port["msb"] < port["lsb"] else -1
    return [f"{port['name']}[{i}]" for i in range(port["msb"], port["lsb"] + step, step)]


def _native_core(project: Path, core_config: dict, destination: Path):
    from librelane.common import Toolbox
    from librelane.flows import Flow
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    os.environ["_OPENLANE_MAX_CORES"] = "8"
    owner = Flow.factory.get("Chip")(core_config, design_dir=str(project),
                                     pdk_root=os.environ.get("PDK_ROOT"))
    native = owner.config.to_raw_dict()
    toolbox = Toolbox(str(destination / "tool_tmp"))
    state = State()
    runs = []
    try:
        for name in ("Yosys.JsonHeader", "Yosys.Synthesis"):
            step = Step.factory.get(name)(owner.config, state)
            directory = destination / name.lower().replace(".", "_")
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            cwd = Path.cwd()
            try:
                os.chdir(directory)
                state = step.start(toolbox=toolbox, step_dir=str(directory))
            finally:
                os.chdir(cwd)
                runs.append({"name": name, "tool_seconds": time.monotonic() - started})
    finally:
        (destination / "sizing.json").write_text(json.dumps({"runs": runs,
            "tool_seconds": sum(run["tool_seconds"] for run in runs)}, indent=2) + "\n")
    header = json.loads(Path(str(state[DesignFormat.JSON_HEADER])).read_text())
    area = state.metrics.get("design__instance__area")
    if area is None or float(area) <= 0:
        raise FileNotFoundError("Missing native Yosys mapped design__instance__area")
    return native, _ports(header, core_config["DESIGN_NAME"]), float(area), runs


def _side_ports(project: Path, ports: list[dict]):
    placement, params, unreadable, scanned = placement_docs.read_project_placement(project)
    if unreadable:
        raise ValueError(f"Unreadable pad placement documents: {unreadable}")
    by_name = {port["name"]: _bits(port) for port in ports}
    available = {bit for bits in by_name.values() for bit in bits}
    sides = {side: [] for side in SIDES}
    if placement is not None:
        renames = placement_docs.declared_renames(project)
        declared, unresolved = placement_docs.expand_renamed_side_ports(
            placement, params, ports, renames,
            exact_carriers=placement_docs.input_delegated_rename_names(project, renames))
        if unresolved:
            raise ValueError(f"Unresolved pad placement: {unresolved}")
        groups, records = placement_docs.resolve_declared_pad_groups(
            placement, ports, renames=renames, params=params)
        if any(not record["resolved_nets"] for record in records):
            raise ValueError(f"Unresolved pad placement groups: {records}")
        for side in SIDES:
            for name in [*declared.get(side, []), *groups.get(side, [])]:
                sides[side].extend(by_name.get(name, [name]))
    assigned = [bit for side in sides.values() for bit in side]
    if len(set(assigned)) != len(assigned):
        raise ValueError("Conflicting pad placement: a signal occurs more than once")
    unknown = set(assigned) - available
    if unknown:
        raise ValueError(f"Unknown pad placement signals: {sorted(unknown)}")
    for port in ports:
        for bit in _bits(port):
            if bit not in assigned:
                side = min(SIDES, key=lambda item: len(sides[item]))
                sides[side].append(bit)
    return sides, placement, scanned


def _paths(value) -> list[Path]:
    if isinstance(value, dict):
        return list(dict.fromkeys(path for group in value.values() for path in _paths(group)))
    if isinstance(value, (str, os.PathLike)):
        return [Path(str(value))]
    return [Path(str(path)) for path in value or []]


def _library(native: dict):
    root, pdk = str(_required(native, "PDK_ROOT")), str(_required(native, "PDK"))
    lefs = _paths(_required(native, "PAD_LEFS"))
    libs = _paths(_required(native, "PAD_LIBS"))
    configs = pads.discover_io_library_configs(root, pdk)
    sizes, classes, roles, sources = {}, {}, {}, {}
    for path in lefs:
        text = path.read_text()
        sizes.update(pads.parse_lef_macros(text))
        classes.update(pads.parse_lef_macro_classes(text))
        roles.update(pads.parse_lef_pin_roles(text))
        for master in pads.parse_lef_macros(text):
            sources.setdefault(master, []).append(path)
    corners = _required(native, "PAD_CORNER")
    if isinstance(corners, str):
        corners = [corners]
    prefix = corners[0].split("__", 1)[0] + "__" if "__" in corners[0] else None
    terminals = pads.io_terminals(configs, prefix)
    cells, conflicts = electrical.merge_liberty_pad_cells(libs)
    verilog = [path.read_text() for path in pads.discover_io_verilog(root, pdk)]
    supply_views = [pads.parse_liberty_supply_view(path.read_text()) for path in libs]
    pg_pins = {master: set(cell["pg_pins"]) for view in supply_views
               for master, cell in view["cells"].items()}
    return {"sizes": sizes, "classes": classes, "roles": roles, "sources": sources,
            "prefix": prefix, "terminals": terminals, "cells": cells,
            "conflicts": conflicts, "lefs": lefs, "libs": libs,
            "configs": configs, "root": root, "pdk": pdk, "verilog": verilog,
            "pg_pins": pg_pins}


def _ring(project: Path, native: dict, ports: list[dict], library: dict):
    sides, placement, scanned = _side_ports(project, ports)
    directions = {bit: port["direction"] for port in ports for bit in _bits(port)}
    chosen, ordered = {}, {side: [] for side in SIDES}
    for side, bits in sides.items():
        for bit in bits:
            master, _, _ = electrical._select_master(directions[bit], library["classes"],
                library["sizes"], library["prefix"], library["terminals"])
            instance = f"u_pad_signal_{len(chosen)}"
            chosen[instance] = {"port": bit, "master": master,
                                "direction": directions[bit]}
            ordered[side].append(instance)
    power = str((native.get("VDD_NETS") or [_required(native, "VDD_PIN")])[0])
    ground = str((native.get("GND_NETS") or [_required(native, "GND_PIN")])[0])
    core_libs = _paths(_required(native, "LIB"))
    pair, plan, _ = electrical.resolve_supply_pad_pair(
        library["classes"], library["sizes"], library["roles"], library["prefix"],
        power, ground, library["sources"], library["terminals"],
        liberty_texts=lambda: [path.read_text() for path in library["libs"]],
        netlist_texts=lambda: [path.read_text() for path in pads.discover_io_netlists(
            library["root"], library["pdk"])],
        core_liberty_text=lambda: core_libs[0].read_text(),
        verilog_texts=library["verilog"])
    supply = pair + list(plan.get("supplemental_supply_pads") or []) + list(plan.get("ring_connectors") or [])
    electrical.connect_bonded_ring_rails(supply, plan, library["roles"], power, ground,
                                        signal_pads=list(chosen.values()))
    side = min(SIDES, key=lambda item: sum(library["sizes"][chosen[inst]["master"]][0]
                                         for inst in ordered[item]))
    for index, entry in enumerate(supply):
        instance = f"u_pad_supply_{index}"
        chosen[instance] = {key: value for key, value in entry.items() if key != "source_lefs"}
        ordered[side].append(instance)
    declared = electrical.declared_aux_levels([project / path for path in scanned])
    for instance, entry in chosen.items():
        if entry.get("supply_connections"):
            continue
        master = entry["master"]
        if master in library["conflicts"]:
            raise ValueError(f"Conflicting Liberty for {master}: {library['conflicts'][master]}")
        pins = library["cells"].get(master)
        if pins is None:
            raise FileNotFoundError(f"Missing pad Liberty cell {master}")
        core_power_pins = [pin for pin, net in entry.get("power_connections", {}).items() if net == power]
        faces = pads.pad_cell_faces(pins, entry["direction"], declared.get(entry["port"]),
                                    master=master, core_power_pins=core_power_pins)
        if faces.refused:
            raise ValueError(f"Cannot connect {entry['port']} through {master}: {faces.refused}")
        entry.update(terminal=faces.terminal, core_pin=faces.core_pin,
                     ties=faces.ties, tie_reasons=faces.reasons,
                     local_tie_sources=electrical._local_pad_tie_sources(
                         pins, faces.ties, entry.get("power_connections", {})))
    supplies = list(dict.fromkeys(str(entry["port"]) for entry in supply if entry.get("is_supply_pad")))
    return chosen, ordered, supplies, power, ground, placement


def _floorplan(native: dict, chosen: dict, ordered: dict, library: dict, area: float, placement):
    sizes = library["sizes"]
    corners = _required(native, "PAD_CORNER")
    if isinstance(corners, str):
        corners = [corners]
    corner = max(max(sizes[name]) for name in corners)
    fillers = [sizes[name][0] for name in _required(native, "PAD_FILLERS")]
    edge = float(_required(native, "PAD_EDGE_SPACING"))
    site_library = pads.IoLibrary(library["lefs"], pads.discover_io_site_declarations(
        library["root"], library["pdk"]))
    site = site_library.resolve_site(str(_required(native, "PAD_SITE_NAME")))
    if site is None:
        raise FileNotFoundError("Missing PAD_SITE_NAME dimensions")
    site_width = float(site["size"][0])
    tech = "\n".join(path.read_text() for path in _paths(_required(native, "TECH_LEFS")))
    dbu_match = re.search(r"DATABASE\s+MICRONS\s+(\d+)", tech)
    grid_match = re.search(r"MANUFACTURINGGRID\s+([\d.]+)", tech)
    if not dbu_match or not grid_match:
        raise FileNotFoundError("Missing PDK LEF DATABASE MICRONS or MANUFACTURINGGRID")
    units, grid = int(dbu_match[1]), float(grid_match[1])
    snap = lambda value: math.ceil((value - 1e-9) / grid) * grid
    util = float(_required(native, "FP_CORE_UTIL")) / 100
    if not 0 < util <= 1:
        raise ValueError("FP_CORE_UTIL must be a percentage greater than zero and at most 100")
    aspect = float(_required(native, "FP_ASPECT_RATIO"))
    if aspect <= 0:
        raise ValueError("FP_ASPECT_RATIO must be positive")
    depth = max(sizes[entry["master"]][1] for entry in chosen.values())
    envelope = 0.0
    if native.get("PDN_CORE_RING"):
        envelope = max(float(_required(native, f"PDN_CORE_RING_{axis}OFFSET"))
            + float(_required(native, f"PDN_CORE_RING_{axis}WIDTH"))
            + float(_required(native, f"PDN_CORE_RING_{axis}SPACING")) for axis in ("V", "H"))
    inset = snap(edge + max(depth, corner) + envelope)
    spans = {side: sum(sizes[chosen[inst]["master"]][0] for inst in instances)
             for side, instances in ordered.items()}
    minimum_gap = placement.min_pad_distance_um if placement else None
    minimum_gap = float(minimum_gap or 0)
    minimum = max(spans[side] + max(len(ordered[side]) - 1, 0) * minimum_gap
                  + 2 * (corner + edge) for side in SIDES)
    required_width, required_height = math.sqrt(area / util / aspect), math.sqrt(area / util * aspect)
    explicit_die, explicit_core = native.get("DIE_AREA"), native.get("CORE_AREA")
    width = max(minimum, required_width + 2 * inset)
    height = max(minimum, required_height + 2 * inset)
    if explicit_core:
        width = max(width, float(explicit_core[2]) + inset)
        height = max(height, float(explicit_core[3]) + inset)
    if explicit_die:
        die = [float(value) for value in explicit_die]
    else:
        die = [0.0, 0.0, snap(width), snap(height)]
    filler_units = [round(value * units) for value in fillers]
    site_units = round(site_width * units)
    filler_gcd = math.gcd(*filler_units)
    # Native spacing repeats after these whole-micron/site/filler periods.
    base_period = math.lcm(site_units, filler_gcd, units)
    for axis, edges in ((2, ("N", "S")), (3, ("E", "W"))):
        periods = [2 * (len(ordered[side]) + 1) * base_period for side in edges]
        period = math.lcm(*periods)
        seen = set()
        while True:
            available = round((die[axis] - die[axis - 2] - 2 * (corner + edge)) * units)
            legal = True
            gaps = []
            for side in edges:
                count, total = len(ordered[side]), round(spans[side] * units)
                if not count:
                    side_gaps = [available]
                else:
                    spacing = pads.side_spacing(total, count, available, site_units, units=units)
                    if spacing is None:
                        legal = False
                        continue
                    between, start = spacing
                    side_gaps = [start, available - total - start - between * (count - 1)]
                    if count > 1:
                        side_gaps.append(between)
                        legal &= between >= minimum_gap * units
                gaps.extend(side_gaps)
                legal &= all(pads.gap_is_fillable(gap, filler_units) for gap in side_gaps)
            if legal:
                break
            if explicit_die:
                raise ValueError(f"Declared DIE_AREA cannot fit the pad ring on {edges}")
            conductor = max(filler_units) ** 2 // filler_gcd
            if available - max(round(spans[side] * units) for side in edges) >= (
                    max(len(ordered[side]) for side in edges) + 1) * (conductor + base_period):
                residue = available % period
                if residue in seen:
                    raise ValueError(f"PDK pad site/filler geometry cannot close the ring on {edges}")
                seen.add(residue)
            die[axis] = snap(die[axis] + grid)
    core = ([float(value) for value in explicit_core] if explicit_core else
            [die[0] + inset, die[1] + inset, die[2] - inset, die[3] - inset])
    if (core[0] < die[0] + inset or core[1] < die[1] + inset
            or core[2] > die[2] - inset or core[3] > die[3] - inset
            or (core[2] - core[0]) * (core[3] - core[1]) < area / util):
        raise ValueError("Declared geometry cannot fit mapped core area/utilization and native pad/PDN inset")
    return die, core, {"mapped_cell_area_um2": area, "core_utilization_percent": util * 100,
                       "pad_depth_um": depth, "corner_um": corner, "edge_spacing_um": edge,
                       "pdn_envelope_um": envelope, "core_inset_um": inset,
                       "pad_side_widths_um": spans, "manufacturing_grid_um": grid}


def _identifier(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", name) else "\\" + name.lstrip("\\") + " "


def _wrapper(core: str, top: str, ports: list[dict], chosen: dict, ordered: dict,
             supplies: list[str], native: dict, library: dict) -> str:
    ties = {}
    for level, key in ((1, "SYNTH_TIEHI_CELL"), (0, "SYNTH_TIELO_CELL")):
        master, pin = str(_required(native, key)).rsplit("/", 1)
        ties[level] = {"master": master, "pin": pin}
    aux, used = electrical._auxiliary_pin_signal_connections(chosen, ties)
    ranges = lambda port: f"[{port['msb']}:{port['lsb']}] " if port["indexed"] else ""
    declarations = [f"    inout wire {ranges(port)}{_identifier(port['name'])}" for port in ports]
    declarations += [f"    inout wire {_identifier(name)}" for name in supplies]
    lines = [f"module {_identifier(top)} (", ",\n".join(declarations), ");"]
    net_for_bit = {}
    core_connections = []
    for index, port in enumerate(ports):
        net = f"_core_port_{index}"
        lines.append(f"    wire {ranges(port)}{net};")
        core_connections.append(f".{_identifier(port['name'])}({net})")
        for bit in _bits(port):
            suffix = bit[len(port["name"]):]
            net_for_bit[bit] = net + suffix
    internal = {str(net) for entry in chosen.values() for key in ("supply_connections", "power_connections")
                for net in entry.get(key, {}).values()} - set(supplies)
    internal |= {str(tie["net"]) for tie in used.values()}
    lines.extend(f"    wire {_identifier(net)};" for net in sorted(internal))
    for tie in used.values():
        if tie.get("source") != "pad":
            lines.append(f"    {tie['master']} {tie['instance']} (.{tie['pin']}({tie['net']}));")
    buses = electrical.io_bus_ports(library["verilog"])
    for instances in ordered.values():
        for instance in instances:
            entry = chosen[instance]
            pairs = dict(entry.get("supply_connections") or entry.get("power_connections") or {})
            if entry.get("core_pin"):
                port = entry["port"]
                match = next((p for p in ports if port in _bits(p)), None)
                suffix = port[len(match["name"]):]
                pairs[entry["terminal"]] = _identifier(match["name"]) + suffix
                pairs[entry["core_pin"]] = net_for_bit[port]
            pairs.update(aux.get(instance, {}))
            pairs.update({tie["pin"]: tie["net"] for tie in used.values()
                          if tie.get("source") == "pad" and tie["instance"] == instance})
            pg = library["pg_pins"].get(entry["master"], set())
            regular = electrical._named_connections(instance, entry["master"],
                [(pin, net) for pin, net in pairs.items() if pin not in pg], buses)
            power = [f".{pin}({_identifier(net)})" for pin, net in pairs.items() if pin in pg]
            lines.extend([f"    {entry['master']} {instance} (", "        " + ", ".join(regular)])
            if power:
                lines.extend(["`ifdef USE_POWER_PINS", ("        , " if regular else "        ") + ", ".join(power), "`endif"])
            lines.append("    );")
    lines.extend([f"    {_identifier(core)} u_core ({', '.join(core_connections)});", "endmodule", ""])
    return "\n".join(lines)


def _sdc(project: Path, config: dict, ports: list[dict]) -> str:
    directions = {bit: port["direction"] for port in ports for bit in _bits(port)}
    collection = lambda names: "[get_ports -regexp {^(" + "|".join(re.escape(name) for name in names) + ")$}]"
    original = config.get("PNR_SDC_FILE")
    if original:
        text = Path(str(original)).read_text()
        inputs = [bit for bit, value in directions.items() if value == "input"]
        outputs = [bit for bit, value in directions.items() if value == "output"]
        clocks = config.get("CLOCK_PORT") or []
        clocks = [clocks] if isinstance(clocks, str) else clocks
        text = text.replace("[all_inputs]", collection(inputs))
        text = text.replace("[all_inputs -no_clocks]", collection([name for name in inputs if name not in clocks]))
        return text.replace("[all_outputs]", collection(outputs))
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    document = json.loads(path.read_text())
    delay = document.get("constraints", {}).get("io_delay", {}).get("default_fraction_percent")
    if delay is None:
        raise FileNotFoundError("Missing L19.constraints.io_delay.default_fraction_percent")
    clocks = _required(config, "CLOCK_PORT")
    if isinstance(clocks, str):
        clocks = [clocks]
    period = float(_required(config, "CLOCK_PERIOD"))
    budget = period * float(delay) / 100
    if any(clock not in directions or directions[clock] != "input" for clock in clocks):
        raise ValueError("CLOCK_PORT must name an elaborated core input")
    # -regexp with anchored escaped names keeps bus brackets literal in OpenSTA.
    lines = ["set_units -time ns"]
    for index, clock in enumerate(clocks):
        lines.append(f"create_clock -name core_clock_{index} -period {period:g} {collection([clock])}")
        for direction, command in (("input", "set_input_delay"), ("output", "set_output_delay")):
            names = [bit for bit, value in directions.items() if value == direction and bit not in clocks]
            if names:
                additive = " -add_delay" if index else ""
                lines.append(f"{command} {budget:g} -clock core_clock_{index}{additive} {collection(names)}")
    return "\n".join(lines) + "\n"


def prepare(project: Path, core_config: dict[str, Any]) -> dict[str, Any]:
    """Return a native Chip config, with all generated inputs under work/flow/chip."""
    project = Path(project).resolve()
    destination = project / "work/flow/chip"
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    native, ports, area, runs = _native_core(project, core_config, destination)
    library = _library(native)
    chosen, ordered, supplies, power, ground, placement = _ring(project, native, ports, library)
    die, core, geometry = _floorplan(native, chosen, ordered, library, area, placement)
    top = core_config["DESIGN_NAME"] + "_chip"
    wrapper = destination / "wrapper.v"
    wrapper.write_text(_wrapper(core_config["DESIGN_NAME"], top, ports, chosen, ordered,
                                supplies, native, library))
    sdc = destination / "constraints.sdc"
    sdc.write_text(_sdc(project, core_config, ports))
    result = dict(core_config)
    for axis in ("VERTICAL", "HORIZONTAL"):
        key = f"PDN_CORE_{axis}_LAYER"
        if result.get(key) == native.get(f"PDN_{axis}_LAYER"):
            result.pop(key, None)
    result.update(DESIGN_NAME=top, VERILOG_FILES=[*core_config["VERILOG_FILES"], str(wrapper)],
                  FP_SIZING="absolute", DIE_AREA=die, CORE_AREA=core,
                  PDN_ENABLE_PINS=False, MAGIC_EXT_USE_GDS=True,
                  VDD_NETS=[power], GND_NETS=[ground], PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
    result.update({"PAD_" + full: ordered[side] for side, full in SIDES.items()})
    tool_seconds = sum(run["tool_seconds"] for run in runs)
    report = {"ports": ports, "pads": chosen, "pad_sides": ordered,
              "geometry": geometry, "die_area_um": die, "core_area_um": core,
              "sizing_runs": runs, "tool_seconds": tool_seconds,
              "program_seconds": time.monotonic() - started - tool_seconds,
              "assumptions": [
                  "The explicit IC route delivers a bare die when no package is declared.",
                  "The pad wrapper preserves the elaborated core functional interface.",
                  "Unassigned signal bits use the least populated edge; documented sides take precedence.",
                  "One PDK-derived bonded supply pair is the initial ring population; native IR signoff measures adequacy.",
              ]}
    (destination / "preparation.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (destination / "config.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result
