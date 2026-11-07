#!/usr/bin/env python3
"""Generate native Chip inputs from the elaborated core and active PDK."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import vibeic_temp as tempfile
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


def netlist_area(config, state, toolbox, directory, on_tool_run=None):
    """Read OpenROAD's area with the floorplanner's native netlist/library inputs."""
    from librelane.steps import Step, StepError, StepException

    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "area.tcl"
    script.write_text("source $::env(SCRIPTS_DIR)/openroad/common/io.tcl\n"
        "read_pnr_libs\nread_lefs\nread_current_netlist\nreport_design_area_metrics\n")
    step = Step.factory.get("OpenROAD.Floorplan")(config, state)
    step.get_script_path = lambda: str(script)
    started = time.monotonic()
    code, ran, status, detail = None, False, "NOT_MEASURED", ""
    try:
        step.start(toolbox=toolbox, step_dir=str(directory))
        area = json.loads((directory / "or_metrics_out.json").read_text()).get("design__instance__area")
        code, ran, status = 0, True, "PASS" if area is not None else "NOT_MEASURED"
        return area
    except (StepException, FileNotFoundError) as exc:
        code, ran, status, detail = None, False, "NOT_MEASURED", str(exc)
        raise
    except StepError as exc:
        code, ran, status, detail = getattr(getattr(exc, "underlying_error", None), "returncode", 1) or 1, True, "FAIL", str(exc)
        raise
    except Exception as exc:
        detail = str(exc)
        raise
    finally:
        if on_tool_run is not None:
            on_tool_run({"name": "OpenROAD.ReportDesignArea", "ran": ran, "exit_code": code,
                "status": status, "tool_seconds": time.monotonic() - started,
                "detail": detail, "reports": str(directory)})


def _native_core(project: Path, core_config: dict, destination: Path, on_tool_run=None):
    from flow_config import explore_synthesis, native_defaults
    from librelane.common import Toolbox
    from librelane.flows import Flow
    from librelane.state import DesignFormat, State
    from librelane.steps import Step, StepError, StepException

    os.environ["_OPENLANE_MAX_CORES"] = "8"
    owner = Flow.factory.get("Chip")(core_config, design_dir=str(project),
                                     pdk_root=os.environ.get("PDK_ROOT"))
    owner.config = native_defaults(owner.config)
    native = owner.config.to_raw_dict()
    run_root = Path(tempfile.mkdtemp(prefix="core_", dir=tempfile.current_run() / "core_inputs"))
    toolbox = Toolbox(str(run_root / "tool_tmp"))
    state = State()
    runs = []
    def observed(run):
        runs.append({"name": run["name"], "tool_seconds": run["tool_seconds"]})
        if on_tool_run is not None:
            on_tool_run(run)
    try:
        for name in ("Yosys.JsonHeader", "Yosys.Synthesis"):
            if name == "Yosys.Synthesis" and "SYNTH_STRATEGY" not in core_config:
                strategy = explore_synthesis(owner.config, state, run_root / "synthesis_exploration", observed)
                if strategy is not None:
                    owner.config = owner.config.copy(SYNTH_STRATEGY=strategy)
                    native = owner.config.to_raw_dict()
            step = Step.factory.get(name)(owner.config, state)
            directory = run_root / name.lower().replace(".", "_")
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            cwd = Path.cwd()
            code, ran, status, detail = None, False, "NOT_MEASURED", ""
            try:
                os.chdir(directory)
                state = step.start(toolbox=toolbox, step_dir=str(directory))
                code, ran, status = 0, True, "PASS"
            except StepException as exc:
                detail = str(exc)
                raise
            except StepError as exc:
                code = getattr(getattr(exc, "underlying_error", None), "returncode", None)
                ran, status, detail = True, "FAIL", str(exc)
                raise
            except Exception as exc:
                detail = str(exc)
                raise
            finally:
                os.chdir(cwd)
                elapsed = time.monotonic() - started
                observed({"name": name, "ran": ran, "exit_code": code,
                          "status": status, "tool_seconds": elapsed,
                          "detail": detail, "reports": str(directory)})
        area = netlist_area(owner.config, state, toolbox, run_root / "openroad_area", observed)
    finally:
        (destination / "sizing.json").write_text(json.dumps({"runs": runs,
            "top": core_config["DESIGN_NAME"], "state_out": str(run_root / "yosys_synthesis/state_out.json"),
            "tool_seconds": sum(run["tool_seconds"] for run in runs)}, indent=2) + "\n")
    header = json.loads(Path(str(state[DesignFormat.JSON_HEADER])).read_text())
    if area is None or float(area) <= 0:
        raise FileNotFoundError("Missing native OpenROAD design__instance__area")
    return native, _ports(header, core_config["DESIGN_NAME"]), float(area), runs


def _side_ports(project: Path, ports: list[dict]):
    placement, params, unreadable, scanned = placement_docs.read_project_placement(project)
    if unreadable:
        raise ValueError(f"Unreadable pad placement documents: {unreadable}")
    by_name = {port["name"]: _bits(port) for port in ports}
    available = {bit for bits in by_name.values() for bit in bits}
    sides = {side: [] for side in SIDES}
    if placement is not None:
        declared, unresolved = placement_docs.expand_side_ports(placement, params)
        if unresolved:
            raise ValueError(f"Unresolved pad placement: {unresolved}")
        groups, records = placement_docs.resolve_declared_pad_groups(
            placement, ports, params=params, project=project)
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


def _selected_slot(project: Path):
    """Read the selected operator slot; its published rectangles are inputs."""
    import _submission_template as submission
    import yaml

    root = project / submission.SLOTS_DIR_REL
    files = sorted([*root.glob("*.yaml"), *root.glob("*.yml"), *root.glob("*.json")])
    if not files:
        return None
    report = project / submission.REPORT_REL
    declared = (json.loads(report.read_text()).get("ingest", {}).get("declared_slot")
                if report.is_file() else None)
    answers = project / submission.DESIGN_ANSWERS_REL
    if answers.is_file():
        operator = json.loads(answers.read_text()).get("operator_template") or {}
        selected = operator.get("slot")
        if declared and selected and declared != selected:
            raise ValueError(f"Conflicting selected operator slots: {declared!r}, {selected!r}")
        declared = selected or declared
    if not declared:
        raise ValueError("Operator slots are supplied but no slot is selected in the design inputs")
    records = []
    for path in files:
        try:
            value = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"Unreadable operator slot: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Unreadable operator slot: {path}")
        record = value
        if "die_area" not in value:
            _, name = submission._first_key(value, submission.SLOT_NAME_KEYS)
            record = {"slot": name or path.stem,
                      "die_area": submission._rect_field(value, submission.DIE_AREA_KEY),
                      "core_area": submission._rect_field(value, submission.CORE_AREA_KEY),
                      "pads": submission._pad_lists(value, set())}
        if record.get("slot") == declared:
            records.append(record)
    if len(records) != 1:
        raise ValueError(f"Selected operator slot {declared!r} has {len(records)} matching records")
    return records[0]


def _slot_geometry(native: dict, slot: dict) -> dict:
    import _submission_template as submission

    native = dict(native)
    for field, key in (("die_area", "DIE_AREA"), ("core_area", "CORE_AREA")):
        value = slot.get(field)
        if value is None and field == "core_area":
            continue
        rect = submission.parse_rect((value or {}).get("rect") or (value or {}).get("raw"))
        if rect is None or min(submission.rect_wh(rect)) <= 0:
            raise ValueError(f"Selected operator slot {slot['slot']!r} has no usable {key}")
        native[key] = [float(number) for number in rect]
    return native


def _slot_pads(project: Path, chosen: dict, ordered: dict, slot: dict):
    """Resolve the slot's pad instances against this generated wrapper."""
    lists = (slot.get("pads") or {}).get("lists") or []
    if not lists:
        return chosen, ordered
    sides = {side: [] for side in SIDES}
    reverse_sides = {"PAD_" + name: side for side, name in SIDES.items()}
    for entry in lists:
        key = str(entry["key"]).upper()
        if key not in reverse_sides:
            raise ValueError(f"Operator slot pad list {key!r} names no die side")
        sides[reverse_sides[key]] = entry["raw"]
    by_port = {}
    for instance, entry in chosen.items():
        if entry.get("port"):
            by_port.setdefault(entry["port"], []).append(instance)
    bound = electrical._bind_side_names(project, sides, list(by_port))
    result, used = {}, set()
    for side, names in sides.items():
        for name, port in zip(names, bound[side]):
            candidates = [name] if name in chosen else by_port.get(port, [])
            if len(candidates) != 1 or candidates[0] in used or name in result:
                raise ValueError(f"Operator slot pad {name!r} does not resolve to one unused wrapper pad")
            original = candidates[0]
            result[name] = chosen[original]
            used.add(original)
    if used != set(chosen):
        raise ValueError(f"Operator slot omits wrapper pads: {sorted(set(chosen) - used)}")
    return result, sides


def _library(native: dict):
    root, pdk = str(_required(native, "PDK_ROOT")), str(_required(native, "PDK"))
    lefs = _paths(_required(native, "PAD_LEFS"))
    libs = _paths(_required(native, "PAD_LIBS"))
    configs = pads.discover_io_library_configs(root, pdk)
    sizes, classes, roles, sources, pin_ports = {}, {}, {}, {}, {}
    for path in lefs:
        text = path.read_text()
        sizes.update(pads.parse_lef_macros(text))
        classes.update(pads.parse_lef_macro_classes(text))
        roles.update(pads.parse_lef_pin_roles(text))
        pin_ports.update(pads.parse_lef_pin_ports(text))
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
            "pg_pins": pg_pins, "pin_ports": pin_ports}


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
    def resolve(connectors=()):
        return electrical.resolve_supply_pad_pair(
            library["classes"], library["sizes"], library["roles"], library["prefix"],
            power, ground, library["sources"], library["terminals"],
            liberty_texts=lambda: [path.read_text() for path in library["libs"]],
            netlist_texts=lambda: [path.read_text() for path in pads.discover_io_netlists(
                library["root"], library["pdk"])],
            core_liberty_text=lambda: core_libs[0].read_text(),
            ring_implementation={"connector_masters": list(connectors)},
            verilog_texts=library["verilog"])

    pair, plan, _ = resolve()
    unbound = set(plan.get("ring_rails_without_bond", []))
    connectors = {master for text in library["verilog"]
                  for master, bridges in pads.parse_verilog_rail_bridges(text).items()
                  if library["classes"].get(master, "").upper() in ("PAD AREAIO", "PAD SPACER")
                  and (not library["prefix"] or master.startswith(library["prefix"]))
                  and any(a in unbound or b in unbound for a, b in bridges)}
    if connectors:
        pair, plan, _ = resolve(sorted(connectors))
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


def _floorplan(native: dict, chosen: dict, ordered: dict, library: dict, area: float, placement, pdn_geometry=None):
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
    supply_count = len(native["VDD_NETS"]) + len(native["GND_NETS"])
    if native.get("PDN_CORE_RING"):
        envelope = max(float(_required(native, f"PDN_CORE_RING_{axis}OFFSET"))
            + supply_count * float(_required(native, f"PDN_CORE_RING_{axis}WIDTH"))
            + (supply_count - 1) * float(_required(native, f"PDN_CORE_RING_{axis}SPACING")) for axis in ("V", "H"))
    inset = snap(edge + max(depth, corner) + envelope)
    spans = {side: sum(sizes[chosen[inst]["master"]][0] for inst in instances)
             for side, instances in ordered.items()}
    minimum_gap = placement.min_pad_distance_um if placement else None
    minimum_gap = float(minimum_gap or 0)
    minimum = {side: spans[side] + max(len(ordered[side]) - 1, 0) * minimum_gap
               + 2 * (corner + edge) for side in SIDES}
    required_width, required_height = math.sqrt(area / util / aspect), math.sqrt(area / util * aspect)
    minimum_core = {}
    for axis in ("V", "H"):
        keys = [f"PDN_{axis}{suffix}" for suffix in ("OFFSET", "WIDTH", "SPACING")]
        if pdn_geometry and all(native.get(key) is not None for key in keys):
            offset, width, spacing = (float(native[key]) for key in keys)
            minimum_core[axis] = offset + supply_count * width + (supply_count - 1) * spacing
    required_width = max(required_width, minimum_core.get("V", 0), minimum_core.get("H", 0) / aspect)
    required_height = required_width * aspect
    explicit_die, explicit_core = native.get("DIE_AREA"), native.get("CORE_AREA")
    width = max(minimum["N"], minimum["S"], required_width + 2 * inset)
    height = max(minimum["E"], minimum["W"], required_height + 2 * inset)
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
            or (core[2] - core[0]) * (core[3] - core[1]) < area / util
            or core[2] - core[0] < minimum_core.get("V", 0)
            or core[3] - core[1] < minimum_core.get("H", 0)):
        raise ValueError("Declared geometry cannot fit mapped core area/utilization and native pad/PDN inset")
    return die, core, {"mapped_cell_area_um2": area, "core_utilization_percent": util * 100,
                       "pad_depth_um": depth, "corner_um": corner, "edge_spacing_um": edge,
                       "pdn_envelope_um": envelope, "core_inset_um": inset,
                       "pad_side_widths_um": spans, "manufacturing_grid_um": grid}


def sized_floorplan(project: Path, native: dict, settings: dict, area: float) -> dict:
    from flow_config import _load

    path = project / "work/flow/chip/preparation.json"
    prepared = _load(path)
    fields = _load(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").get("fields", {})
    native = {**native, **settings, "DIE_AREA": fields.get("die_area_um"),
              "CORE_AREA": fields.get("core_area_um")}
    slot = _selected_slot(project)
    if slot is not None:
        native = _slot_geometry(native, slot)
    _, placement, _ = _side_ports(project, prepared["ports"])
    die, core, geometry = _floorplan(native, prepared["pads"], prepared["pad_sides"],
        _library(native), area, placement, settings)
    prepared.update(geometry=geometry, die_area_um=die, core_area_um=core)
    path.write_text(json.dumps(prepared, indent=2, default=str) + "\n")
    return {"DIE_AREA": die, "CORE_AREA": core}


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
    # Receiver ports must accept the pad model's bidirectional connection.
    # Logical outputs stay outputs; they have no external timing driver.
    bidirectional = {entry["port"] for entry in chosen.values() if entry.get("core_pin")
                     and library["cells"][entry["master"]][entry["terminal"]]["direction"] == "inout"}
    declarations = [f"    {'inout' if port['direction'] == 'input' and bidirectional.intersection(_bits(port)) else port['direction']} wire "
                    f"{ranges(port)}{_identifier(port['name'])}" for port in ports]
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
            lines.append(f"    {tie['master']} {_identifier(tie['instance'])} (.{tie['pin']}({tie['net']}));")
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
            # Every selected pad is a physical ring instance, including a
            # receiver whose core-side output is unused after optimization.
            lines.append("    (* keep = 1 *)")
            lines.extend([f"    {entry['master']} {_identifier(instance)} (", "        " + ", ".join(regular)])
            if power:
                lines.extend(["`ifdef USE_POWER_PINS", ("        , " if regular else "        ") + ", ".join(power), "`endif"])
            lines.append("    );")
    lines.extend([f"    {_identifier(core)} u_core ({', '.join(core_connections)});", "endmodule", ""])
    return "\n".join(lines)


def _tcl_word(value):
    return "".join({"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(char,
        "\\" + char if char in '\\ $;{}[]"' else char) for char in str(value))


def _clock_periods(project: Path, config: dict) -> dict:
    from flow_config import declared_clocks, clock_period_ns
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    document = json.loads(path.read_text()) if path.is_file() else {}
    override = document.get('fields', {}).get('clock_target', {}).get('period_ns')
    clocks = declared_clocks(project, config['PDK'])
    return {clock.get('source_pin') or clock.get('name'):
            override if override is not None and len(clocks) == 1 else clock_period_ns(clock)
            for clock in clocks}


def _pad_sdc(chosen: dict, library: dict) -> str:
    """Model DC bonds, using PDK supply roles and native output constants."""
    lines = []
    for instance, entry in chosen.items():
        if not entry.get("port"):
            continue
        port = _tcl_word(entry["port"])
        bond = f"[get_ports [list [[[sta::top_instance] cell] find_port {port}]]]"
        if entry.get("is_supply_pad"):
            use = library["roles"][entry["master"]][entry["terminal"]][1]
            if use in {"POWER", "GROUND"}:
                lines.append(f"set_case_analysis {int(use == 'POWER')} {bond}")
        elif entry.get("direction") == "output":
            pin = _tcl_word(instance + "/" + entry["core_pin"])
            # A fixed output pad drives its bond from this pin. Dynamic
            # values remain X and receive no case analysis.
            lines.extend((
                f"set _chip_pad_value [sta::pin_sim_logic_value [sta::find_pin {pin}]]",
                "if {$_chip_pad_value in {0 1}} {",
                f"  set_case_analysis $_chip_pad_value {bond}",
                "}"))
    return "\n".join(lines) + "\n" if lines else ""


def _electrical_sdc(config: dict) -> list[str]:
    lines = []
    for key, command in (("MAX_FANOUT_CONSTRAINT", "set_max_fanout"),
                         ("MAX_TRANSITION_CONSTRAINT", "set_max_transition")):
        if config.get(key) is not None:
            value = f"{float(config[key]):g}"
            if key == "MAX_TRANSITION_CONSTRAINT":
                value = f"[sta::time_sta_ui [expr {{{value} * 1e-9}}]]"
            lines.append(f"{command} {value} [current_design]")
    if config.get("MAX_CAPACITANCE_CONSTRAINT") is not None:
        lines.extend((
            "set _chip_bond_nets [dict create]",
            "foreach _chip_port [get_ports *] {",
            "  set _chip_net [[[sta::get_port_pin $_chip_port] term] net]",
            '  if {$_chip_net ne "NULL" && $_chip_net ne ""} {',
            "    set _chip_net [$_chip_net highest_connected_net]",
            "    dict set _chip_bond_nets [get_full_name $_chip_net] 1",
            "  }",
            "}",
            "set _chip_core_pins [list]",
            "foreach _chip_pin [get_pins -hierarchical *] {",
            "  foreach _chip_net [get_nets -of_objects $_chip_pin] {",
            '    if {$_chip_net eq "NULL" || $_chip_net eq ""} {continue}',
            "    set _chip_net [$_chip_net highest_connected_net]",
            "    if {![dict exists $_chip_bond_nets [get_full_name $_chip_net]]} {",
            "      lappend _chip_core_pins $_chip_pin",
            "    }",
            "  }",
            "}",
            "if {[llength $_chip_core_pins]} {",
            f"  set_max_capacitance [sta::capacitance_sta_ui [expr {{{float(config['MAX_CAPACITANCE_CONSTRAINT']):g} * 1e-12}}]] $_chip_core_pins",
            "}"))
    return lines


def _sdc(project: Path, config: dict, ports: list[dict]) -> str:
    directions = {bit: port["direction"] for port in ports for bit in _bits(port)}
    def collection(names):
        ports = ["[[[sta::top_instance] cell] find_port " + _tcl_word(name) + "]" for name in names]
        return "[get_ports [list " + " ".join(ports) + "]]"
    original = config.get("PNR_SDC_FILE")
    if original:
        text = Path(str(original)).read_text()
        core = config.get("DESIGN_NAME")
        if core:
            name = re.escape(core)
            text = re.sub(r"(?m)^([ \t]*current_design[ \t]+)(?:" + name +
                          r"|\{" + name + r"\}|\"" + name + r"\")(?=[ \t]*(?:;|$))",
                          lambda match: match[1] + _tcl_word(core + "_chip"), text)
        inputs = [bit for bit, value in directions.items() if value == "input"]
        outputs = [bit for bit, value in directions.items() if value == "output"]
        clocks = config.get("CLOCK_PORT") or []
        clocks = [clocks] if isinstance(clocks, str) else clocks
        text = text.replace("[all_inputs]", collection(inputs))
        text = text.replace("[all_inputs -no_clocks]", collection([name for name in inputs if name not in clocks]))
        return text.replace("[all_outputs]", collection(outputs))
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    document = json.loads(path.read_text()) if path.is_file() else {}
    delay = document.get("constraints", {}).get("io_delay", {}).get("default_fraction_percent")
    if delay is None:
        delay = _required(config, "IO_DELAY_CONSTRAINT")
    clocks = _required(config, "CLOCK_PORT")
    if isinstance(clocks, str):
        clocks = [clocks]
    periods = _clock_periods(project, config)
    if any(clock not in directions or directions[clock] != "input" for clock in clocks):
        raise ValueError("CLOCK_PORT must name an elaborated core input")
    lines = []
    for index, clock in enumerate(clocks):
        period = float(periods.get(clock) or _required(config, "CLOCK_PERIOD"))
        budget = period * float(delay) / 100
        lines.append(f"create_clock -name core_clock_{index} -period [sta::time_sta_ui [expr {{{period:g} * 1e-9}}]] {collection([clock])}")
        for key, command in (("CLOCK_UNCERTAINTY_CONSTRAINT", "set_clock_uncertainty"),
                             ("CLOCK_TRANSITION_CONSTRAINT", "set_clock_transition")):
            if config.get(key) is not None:
                lines.append(f"{command} [sta::time_sta_ui [expr {{{float(config[key]):g} * 1e-9}}]] [get_clocks core_clock_{index}]")
        for direction, command in (("input", "set_input_delay"), ("output", "set_output_delay")):
            names = [bit for bit, value in directions.items() if value == direction and bit not in clocks]
            if names:
                additive = " -add_delay" if index else ""
                lines.append(f"{command} [sta::time_sta_ui [expr {{{budget:g} * 1e-9}}]] -clock core_clock_{index}{additive} {collection(names)}")
    lines.extend(_electrical_sdc(config))
    if config.get("TIME_DERATING_CONSTRAINT") is not None:
        fraction = float(config["TIME_DERATING_CONSTRAINT"]) / 100
        lines.extend((f"set_timing_derate -early {1 - fraction:.17g}",
                      f"set_timing_derate -late {1 + fraction:.17g}"))
    outputs = [bit for bit, value in directions.items() if value == "output"]
    if outputs and config.get("OUTPUT_CAP_LOAD") is not None:
        lines.append(f"set_load [sta::capacitance_sta_ui [expr {{{float(config['OUTPUT_CAP_LOAD']):g} * 1e-15}}]] {collection(outputs)}")
    # Core driving cells model block interfaces, not an off-chip bond-pad driver.
    # Without a documented edge, leave the native STA input defaults in place.
    from sdc_environment import _design_input_transition
    declared_edge = _design_input_transition(project)
    if declared_edge:
        inputs = [bit for bit, value in directions.items() if value == "input"]
        if inputs:
            lines.append(f"set_input_transition [sta::time_sta_ui [expr {{{declared_edge[0]} * 1e-9}}]] {collection(inputs)}")
    return "\n".join(lines) + "\n"


def prepare(project: Path, core_config: dict[str, Any], on_tool_run=None) -> dict[str, Any]:
    """Return a native Chip config, with all generated inputs under work/flow/chip."""
    project = Path(project).resolve()
    destination = project / "work/flow/chip"
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    native, ports, area, runs = _native_core(project, core_config, destination, on_tool_run)
    slot = _selected_slot(project)
    if slot is not None:
        native = _slot_geometry(native, slot)
    library = _library(native)
    chosen, ordered, supplies, power, ground, placement = _ring(project, native, ports, library)
    if slot is not None:
        chosen, ordered = _slot_pads(project, chosen, ordered, slot)
    from flow_pdn_current import current_settings
    native.update(VDD_NETS=[power], GND_NETS=[ground])
    die, _, _ = _floorplan(native, chosen, ordered, library, area, placement)
    pdn_settings = current_settings(project, native, max(die[2] - die[0], die[3] - die[1]))
    native.update(pdn_settings)
    die, core, geometry = _floorplan(native, chosen, ordered, library, area, placement, pdn_settings)
    top = core_config["DESIGN_NAME"] + "_chip"
    wrapper = destination / "wrapper.v"
    wrapper.write_text(_wrapper(core_config["DESIGN_NAME"], top, ports, chosen, ordered,
                                supplies, native, library))
    sdc = destination / "constraints.sdc"
    sdc.write_text(_sdc(project, {**native, **core_config}, ports)
                   + _pad_sdc(chosen, library))
    result = dict(core_config)
    result.update(pdn_settings)
    from flow_clock_geometry import clock_settings
    result.update(clock_settings(native))
    for axis in ("VERTICAL", "HORIZONTAL"):
        key = f"PDN_CORE_{axis}_LAYER"
        if result.get(key) == native.get(f"PDN_{axis}_LAYER"):
            result.pop(key, None)
    result.update(DESIGN_NAME=top, VERILOG_FILES=[*core_config["VERILOG_FILES"], str(wrapper)],
                  FP_SIZING="absolute", DIE_AREA=die, CORE_AREA=core,
                  PDN_ENABLE_PINS=False, MAGIC_EXT_USE_GDS=True,
                  VDD_NETS=[power], GND_NETS=[ground], FALLBACK_SDC=str(sdc),
                  PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
    if native.get("MAGICRC"):
        magicrc = destination / "pad-extraction.magicrc"
        if Path(native["MAGICRC"]) != magicrc:
            # Magic reads its rc before LibreLane's wrapper loads the step environment.
            # Preload pad LEFs only for extraction; other Magic steps keep full views.
            magicrc.write_text("if {[info exists ::env(_TCL_ENV_IN)]} {source $::env(_TCL_ENV_IN)}\n"
                + "source " + _tcl_word(native["MAGICRC"]) + "\n" + r'''
if {[info exists ::env(STEP_ID)] && $::env(STEP_ID) eq "Magic.SpiceExtraction"
    && [info exists ::env(PAD_LEFS)]} {
    foreach lef $::env(PAD_LEFS) {lef read $lef}
    gds noduplicates true
}
''')
        result["MAGICRC"] = str(magicrc)
    if native.get("PDN_CORE_RING") and native.get("PDN_CORE_RING_CONNECT_TO_PADS"):
        ring_layers = {native.get(f"PDN_CORE_{axis}_LAYER") or native[f"PDN_{axis}_LAYER"]
                       for axis in ("VERTICAL", "HORIZONTAL")}
        connected_layers = ring_layers | {native[f"PDN_{axis}_LAYER"]
                                         for axis in ("VERTICAL", "HORIZONTAL")}
        if native.get("PDN_ENABLE_RAILS"):
            connected_layers.add(native["PDN_RAIL_LAYER"])
        access_layers = {layer for entry in chosen.values()
                         for key in ("power_connections", "supply_connections")
                         for pin, net in entry.get(key, {}).items()
                         if net in (power, ground)
                         and library["roles"].get(entry["master"], {}).get(pin, (None, None))[1]
                         in ("POWER", "GROUND")
                         for layer, _ in library["pin_ports"].get(entry["master"], {}).get(pin, [])}
        access_layers -= connected_layers
        if access_layers:
            text = Path(str(_required(native, "PDN_CFG"))).read_text()
            for layer in sorted(access_layers):
                for ring_layer in sorted(ring_layers):
                    command = "add_pdn_connect -grid stdcell_grid -layers {" + layer + " " + ring_layer + "}"
                    reverse = "add_pdn_connect -grid stdcell_grid -layers {" + ring_layer + " " + layer + "}"
                    if command not in text and reverse not in text:
                        text += "\n" + command + "\n"
            pdn = destination / "pdn_cfg.tcl"
            pdn.write_text(text)
            result["PDN_CFG"] = str(pdn)
    result.update({"PAD_" + full: ordered[side] for side, full in SIDES.items()})
    tool_seconds = sum(run["tool_seconds"] for run in runs)
    report = {"ports": ports, "pads": chosen, "pad_sides": ordered,
              "operator_slot": slot.get("slot") if slot else None,
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
