#!/usr/bin/env python3
"""A18 macro-only chip producer. Missing declarations/views are BLOCKING.

L9 owns macros, instances, pad_instances, connections, placement and ties;
0.5ic owns the core name, rectangles and pad order/map; L21 owns rail kinds
and power/return pairs. No circuit, pad master or supply is inferred by name.
Generation is not physical verification or Flow109 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import _tapeout_declaration as td
from _atomic_artefact import write_json
from hardmacro_supply_intent import lef_all_pins, lef_macro_classes
from librelane_contract import Refusal, declaration_config, DECLARATION_REL

DEST = "phase3/analog_top"
RECORD = "reports/phase3/analog_macro_top.json"
PAD_RECORD = "reports/phase3/io_pad_chip_top.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise Refusal("A18_IDENTIFIER_INVALID", f"{label}: {value!r}")
    return value


def require(condition, code, detail):
    if not condition:
        raise Refusal(code, detail)


def generate(project):
    project = Path(project).resolve()
    inputs = {str(path): sha(path) for path in
              (Path(__file__).resolve(), Path(__file__).with_name("analog_macro_top_run.py").resolve())}

    def read(path):
        path = Path(path)
        require(path.is_file(), "A18_DECLARATION_ABSENT", str(path))
        inputs[str(path)] = sha(path)
        value = json.loads(path.read_text())
        require(isinstance(value, dict), "A18_DECLARATION_INVALID", f"object required: {path}")
        return value

    docs = project / "phase1/generated_docs"
    l9 = read(docs / "L9_INTEGRATION_SPEC.json")
    l21 = read(docs / "L21_POWER_INTENT.json")
    declaration = read(project / DECLARATION_REL)
    config, sources = declaration_config(project)
    core = identifier(l9.get("top_module"), "L9.top_module")
    require(config.get("DESIGN_NAME") == core and core != "chip_top",
            "A18_CORE_TOP_MISMATCH", "0.5ic top_cell must name L9.top_module, not chip_top")
    require(td.answer(declaration, "deliverable") == td.DELIVERABLE_DIE,
            "A18_DIE_DECLARATION_REQUIRED", "macro-only chip top requires a DIE declaration")
    require(config.get("FP_SIZING") == "absolute" and all(k in config for k in ("DIE_AREA", "CORE_AREA")),
            "A18_GEOMETRY_ABSENT", "declare absolute die_area_um and core_area_um")
    order = td.answer(declaration, "pad_order_by_side")
    signal_map = td.answer(declaration, "pad_signal_map")
    require(isinstance(order, dict) and set(order) == {"south", "east", "north", "west"}
            and all(isinstance(v, list) for v in order.values()),
            "A18_PAD_ORDER_ABSENT", "0.5ic pad_order_by_side")
    pad_names = [identifier(n, "pad_order_by_side") for side in order.values() for n in side]
    require(pad_names and len(set(pad_names)) == len(pad_names)
            and isinstance(signal_map, dict) and set(signal_map) == set(pad_names),
            "A18_PAD_MAP_INVALID", "pad order and pad_signal_map must name the same unique instances")
    for key in ("PAD_SITE_NAME", "PAD_CORNER_SITE_NAME", "PAD_CORNER", "PAD_FILLERS",
                "PAD_EDGE_SPACING", "PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL", "PAD_ROTATION_CORNER"):
        require(key in config, "A18_PAD_DECLARATION_ABSENT", key)

    ports = l9.get("ports")
    require(isinstance(ports, list) and ports and all(isinstance(p, dict) for p in ports),
            "A18_PORTS_ABSENT", "L9.ports")
    port_dirs = {}
    for port in ports:
        name = identifier(port.get("name"), "L9.ports.name")
        direction = port.get("direction")
        require(name not in port_dirs and direction in ("input", "output", "inout")
                and port.get("width", 1) == 1, "A18_PORT_INVALID", name)
        port_dirs[name] = direction
    require(set(signal_map.values()) == set(port_dirs), "A18_PAD_PORT_COVERAGE",
            "every L9 port must reach a declared pad; no extra pad ports")

    fields = l21.get("fields", {})
    require(isinstance(fields, dict), "A18_RAILS_ABSENT", "L21.fields must be an object")
    domains = fields.get("power_domains")
    require(isinstance(domains, list) and domains and all(isinstance(d, dict) for d in domains),
            "A18_RAILS_ABSENT", "L21.fields.power_domains")
    rails = {}
    for domain in domains:
        for key, kind in (("power_net", "POWER"), ("ground_net", "GROUND")):
            net = identifier(domain.get(key), f"L21.power_domains.{key}")
            require(net not in rails or rails[net] == kind, "A18_RAIL_KIND_CONFLICT", net)
            rails[net] = kind
    for rail in fields.get("power_rails", []):
        require(isinstance(rail, dict), "A18_RAIL_INVALID", repr(rail))
        net = identifier(rail.get("name") or rail.get("rail"), "L21.power_rails")
        kind = str(rail.get("kind", "")).upper()
        require(kind in ("POWER", "GROUND") and (net not in rails or rails[net] == kind),
                "A18_RAIL_KIND_CONFLICT", net)
        rails[net] = kind
    missing_returns = {n for n, kind in rails.items() if kind == "GROUND"} - set(port_dirs)
    require(not missing_returns, "A18_GROUND_PAD_ABSENT", repr(sorted(missing_returns)))
    ties = l9.get("ties", {})
    require(isinstance(ties, dict), "A18_TIE_INVALID", "L9.ties must map output ports to declared rails")
    for net, rail in ties.items():
        require(port_dirs.get(net) == "output" and rails.get(rail) in ("POWER", "GROUND"),
                "A18_TIE_INVALID", f"{net}: {rail}")

    macro_declarations = l9.get("macros")
    instances = l9.get("instances")
    pads = l9.get("pad_instances")
    require(isinstance(instances, list) and instances and isinstance(pads, list)
            and all(isinstance(i, dict) for i in instances + pads)
            and isinstance(macro_declarations, dict), "A18_INSTANCES_ABSENT",
            "L9.macros, L9.instances and L9.pad_instances must declare the implementation")
    require({p.get("name") for p in pads} == set(pad_names) and len(pads) == len(pad_names),
            "A18_PAD_INSTANCE_MISMATCH", "L9.pad_instances vs 0.5ic pad order")
    macros, interfaces, uses, sizes = {}, {}, {}, {}
    all_rows = instances + pads
    for master in dict.fromkeys(identifier(i.get("master"), "L9 instance master") for i in all_rows):
        views = macro_declarations.get(master, {})
        require(isinstance(views, dict), "A18_MACRO_VIEW_ABSENT", f"{master}: views")
        selected = {}
        for view in ("gds", "lef", "spice"):
            raw = views.get(view)
            require(isinstance(raw, str) and raw, "A18_MACRO_VIEW_ABSENT", f"{master}: {view}")
            path = (project / raw).resolve()
            require(path.is_file() and path.stat().st_size > 0,
                    "A18_MACRO_VIEW_ABSENT", f"{master}: {view}: {path}")
            inputs[str(path)] = sha(path)
            selected[view] = [str(path)]
        lef = Path(selected["lef"][0]).read_text()
        require(lef_macro_classes(lef).get(master) in ("BLOCK", "PAD", "RING"),
                "A18_MACRO_CLASS_INVALID", master)
        pins = [p for p in lef_all_pins(lef) if p["master"] == master]
        require(pins and all(p["use"] in ("POWER", "GROUND", "SIGNAL", "CLOCK", "ANALOG") for p in pins),
                "A18_MACRO_PIN_USE_ABSENT", master)
        spice = re.sub(r"\n\s*\+", " ", Path(selected["spice"][0]).read_text())
        matches = re.findall(r"(?im)^\s*\.subckt\s+" + re.escape(master) + r"\s+([^\n]+)", spice)
        require(len(matches) == 1, "A18_MACRO_SPICE_INTERFACE_INVALID", master)
        pin_order = matches[0].split()
        for pin in pin_order:
            identifier(pin, f"{master} pin")
        require(len(set(pin_order)) == len(pin_order) and set(pin_order) == {p["pin"] for p in pins},
                "A18_MACRO_VIEW_PIN_MISMATCH", master)
        interfaces[master] = pin_order
        uses[master] = {p["pin"]: p["use"] for p in pins}
        body = re.search(r"(?ms)^\s*MACRO\s+" + re.escape(master) + r"\s+(.*?)^\s*END\s+" + re.escape(master) + r"\s*$", lef)
        size = re.search(r"\bSIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", body[1]) if body else None
        require(size is not None, "A18_MACRO_SIZE_ABSENT", master)
        sizes[master] = tuple(map(float, size.groups()))
        macros[master] = {**selected, "instances": {}}

    # PadRing creates filler/corner instances after netlist import. Their
    # library pins still need explicit L21 bindings; broad SCL patterns would
    # merge rails which the design declared separately.
    pad_masters = {p["master"] for p in pads}
    pad_lefs = list(dict.fromkeys(macros[m]["lef"][0] for m in pad_masters))
    pad_gds = list(dict.fromkeys(macros[m]["gds"][0] for m in pad_masters))
    auxiliary_supplies = {}
    for master in config["PAD_FILLERS"] + config["PAD_CORNER"]:
        identifier(master, "pad auxiliary master")
        libraries = [Path(p).read_text() for p in pad_lefs]
        require(any(master in lef_macro_classes(s) for s in libraries),
                "A18_MACRO_VIEW_ABSENT", f"{master}: lef (pad auxiliary)")
        pg = {p["pin"]: p["use"] for s in libraries for p in lef_all_pins(s)
              if p["master"] == master and p["use"] in ("POWER", "GROUND")}
        bound = {}
        for pin, kind in pg.items():
            choices = {r.get("rail") for r in fields.get("hard_macro_supplies", [])
                       if r.get("master") == master and r.get("pin") == pin}
            require(len(choices) == 1 and rails.get(next(iter(choices))) == kind,
                    "A18_AUX_SUPPLY_ABSENT", f"{master}.{pin}: declare L21 hard_macro_supplies.rail")
            bound[pin] = (choices.pop(), kind)
        auxiliary_supplies[master] = bound

    seen, physical, core_rows, pad_rows = set(), [], [], []
    core_box = config["CORE_AREA"]
    for is_pad, rows in ((False, instances), (True, pads)):
        for row in rows:
            name = identifier(row.get("name"), "L9 instance name")
            require(name not in seen, "A18_INSTANCE_DUPLICATE", name)
            seen.add(name)
            master = row["master"]
            connections = row.get("connections")
            require(isinstance(connections, dict) and set(connections) == set(interfaces[master]),
                    "A18_CONNECTIVITY_INCOMPLETE", f"{name} ({master})")
            connections = {pin: identifier(net, f"{name}.{pin}") for pin, net in connections.items()}
            for pin, net in connections.items():
                kind = uses[master][pin]
                if kind in ("POWER", "GROUND"):
                    require(rails.get(ties.get(net, net)) == kind,
                            "A18_SUPPLY_UNDECLARED", f"{name}.{pin}: {net} ({kind})")
            target = name if is_pad else "u_core__" + name
            item = {"name": target, "master": master,
                    "connections": {p: ties.get(n, n) for p, n in connections.items()}}
            physical.append(item)
            if is_pad:
                terminal = identifier(row.get("terminal"), f"{name}.terminal")
                require(connections.get(terminal) == signal_map[name],
                        "A18_PAD_TERMINAL_MISMATCH", name)
                require(all(n in port_dirs or n in rails for p, n in connections.items() if p != terminal),
                        "A18_PAD_CORE_NET_UNEXPOSED", name)
                pad_rows.append({**row, "connections": connections, "port": signal_map[name]})
            else:
                placement = row.get("placement", {})
                loc, orient = placement.get("location"), placement.get("orientation")
                require(isinstance(loc, list) and len(loc) == 2
                        and all(type(v) in (int, float) and math.isfinite(v) for v in loc)
                        and orient in ("N", "S", "E", "W", "FN", "FS", "FE", "FW"),
                        "A18_MACRO_PLACEMENT_ABSENT", name)
                w, h = sizes[master]
                if orient in ("E", "W", "FE", "FW"):
                    w, h = h, w
                require(core_box[0] <= loc[0] and core_box[1] <= loc[1]
                        and loc[0] + w <= core_box[2] and loc[1] + h <= core_box[3],
                        "A18_MACRO_OUTSIDE_CORE", name)
                macros[master]["instances"][target] = placement
                core_rows.append({**row, "connections": connections})

    # External bond nets and internal core nets must be different nodes except
    # for explicit supplies/ties. A pad's other terminals name L9 nets directly.
    connected_ports = {n for r in instances for n in r["connections"].values()}
    connected_ports.update(ties)
    require(set(port_dirs) - set(rails) <= connected_ports,
            "A18_CORE_PORT_UNCONNECTED", repr(sorted(set(port_dirs) - set(rails) - connected_ports)))
    internal_map = {n: (n if n in rails else "core__" + n) for n in port_dirs}
    core_internal = {n for r in core_rows for n in r["connections"].values()} - set(port_dirs) - set(rails)
    require(not (set(internal_map.values()) - set(rails)) & (set(port_dirs) | core_internal),
            "A18_NET_NAMESPACE_COLLISION", "core__ prefix collides with a declared net")
    for row in physical[len(instances):]:
        original = next(p for p in pad_rows if p["name"] == row["name"])
        row["connections"] = {p: (n if p == original["terminal"] else internal_map.get(ties.get(n, n), ties.get(n, n)))
                              for p, n in original["connections"].items()}
    for row in physical[:len(instances)]:
        row["connections"] = {p: internal_map.get(n, n) for p, n in row["connections"].items()}

    destination = project / DEST
    destination.mkdir(parents=True, exist_ok=True)
    logical = destination / "chip_top.v"
    flat = destination / "chip_top.physical.v"
    spice = destination / "chip_top.spice"
    pdn = destination / "pdn.tcl"
    sdc = destination / "analog.sdc"

    def verilog_module(name, directions, rows, assignments=None):
        lines = [f"module {name} ({', '.join(directions)});"]
        lines += [f"  {d} {p};" for p, d in directions.items()]
        nets = {n for r in rows for n in r["connections"].values()} - set(directions)
        nets.update(n for n in (assignments or {}).values() if n not in directions)
        lines += [f"  wire {n};" for n in sorted(nets)]
        lines += [f"  assign {n} = {v};" for n, v in (assignments or {}).items()]
        for row in rows:
            conns = ", ".join(f".{p}({n})" for p, n in row["connections"].items())
            lines.append(f"  {row['master']} {row['name']} ({conns});")
        return "\n".join(lines + ["endmodule", ""])

    wrapper_rows = [{"master": core, "name": "u_core", "connections": internal_map}]
    wrapper_rows += physical[len(instances):]
    logical.write_text(verilog_module(core, port_dirs, core_rows, ties) + "\n"
                       + verilog_module("chip_top", port_dirs, wrapper_rows))
    flat.write_text(verilog_module("chip_top", port_dirs, physical))
    spice_lines = ["* A18 declared logical connectivity; physical verification is separate."]
    spice_lines += [f'.include "{p}"' for p in dict.fromkeys(m["spice"][0] for m in macros.values())]
    spice_lines += [".subckt chip_top " + " ".join(port_dirs)]
    for row in physical:
        spice_lines.append("X" + row["name"] + " " + " ".join(
            row["connections"][p] for p in interfaces[row["master"]]) + " " + row["master"])
    spice_lines.append(".ends chip_top")
    spice.write_text("\n".join(spice_lines) + "\n")
    sdc.write_text("# Pure analog macro interconnect: no synthesized clock tree or digital timing target.\n")
    # Preserve every PG connection, including multiple rails on one macro.
    # Disable the PDK's broad global patterns: they can short distinct supplies.
    pdn_lines = []
    for row in physical:
        for pin, net in row["connections"].items():
            kind = uses[row["master"]][pin]
            if kind in ("POWER", "GROUND"):
                pdn_lines.append(f"add_global_connection -net {{{net}}} -inst_pattern {{^{row['name']}$}} "
                                 f"-pin_pattern {{^{pin}$}} -{kind.lower()}")
    for master, bindings in auxiliary_supplies.items():
        pdn_lines += ["foreach inst [[ord::get_db_block] getInsts] {",
                      f"  if {{[[$inst getMaster] getName] eq {{{master}}}}} {{"]
        for pin, (net, kind) in bindings.items():
            pdn_lines += [f"    set supply [[ord::get_db_block] findNet {{{net}}}]",
                          f"    $supply setSigType {kind}", "    $supply setSpecial",
                          f"    [$inst findITerm {{{pin}}}] connect $supply"]
        pdn_lines += ["  }", "}"]
    pdn_lines += ["global_connect",
                  "set a18_power_nets $::env(VDD_NETS)", "set a18_ground_nets $::env(GND_NETS)",
                  # The native recipe iterates both arrays together. Pad with
                  # their existing primary rail so an unequal domain population
                  # cannot create an empty net or invent another return.
                  "while {[llength $::env(VDD_NETS)] < [llength $::env(GND_NETS)]} {",
                  "  lappend ::env(VDD_NETS) [lindex $a18_power_nets 0]", "}",
                  "while {[llength $::env(GND_NETS)] < [llength $::env(VDD_NETS)]} {",
                  "  lappend ::env(GND_NETS) [lindex $a18_ground_nets 0]", "}",
                  "source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl",
                  "set ::env(VDD_NETS) $a18_power_nets", "set ::env(GND_NETS) $a18_ground_nets"]
    pdn.write_text("\n".join(pdn_lines) + "\n")
    config.update(DESIGN_NAME="chip_top", MACROS={m: v for m, v in macros.items() if m not in pad_masters},
                  PAD_LEFS=pad_lefs, PAD_GDS=pad_gds,
                  PAD_PLACE_IO_TERMINALS=sorted({p["master"] + "/" + p["terminal"] for p in pad_rows}),
                  PAD_BONDPAD_NAME=None,
                  VDD_NETS=[n for n, k in rails.items() if k == "POWER"],
                  GND_NETS=[n for n, k in rails.items() if k == "GROUND"],
                  PDN_CFG=str(pdn), PDN_ENABLE_GLOBAL_CONNECTIONS=False,
                  PDN_CONNECT_MACROS_TO_GRID=False, PDN_ENABLE_RAILS=False,
                  PDN_CORE_RING=True, PDN_CORE_RING_CONNECT_TO_PADS=True,
                  PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
    # Explicit process/tool selection is execution input, never a circuit guess.
    settings_path = project / "input/analog_flow.json"
    settings = read(settings_path).get("analog_top", {}) if settings_path.is_file() else {}
    execution = {k: settings[k] for k in ("pdk", "pdk_root", "scl", "pad") if k in settings}
    cfg_path = destination / "librelane.json"
    write_json(cfg_path, config)
    pad_record = {"producer": "analog_macro_top_gen", "verdict": "WROTE",
                  "core_module": core, "chip_top_module": "chip_top",
                  "chip_top_verilog": str(logical.relative_to(project)),
                  "pad_instances": {p["name"]: {k: p[k] for k in ("master", "port", "terminal")} for p in pad_rows}}
    write_json(project / PAD_RECORD, pad_record)
    write_json(project / "phase3/stage3/pnr/pad_assignment.json",
               {**{k: v for k, v in config.items() if k.startswith("PAD_")}, "SIGNAL_MAP": signal_map})
    outputs = [cfg_path, logical, flat, spice, pdn, sdc, project / PAD_RECORD,
               project / "phase3/stage3/pnr/pad_assignment.json"]
    record = {"producer": "analog_macro_top_gen", "verdict": "WROTE",
              "core_module": core, "chip_top_module": "chip_top", "execution": execution,
              "config": str(cfg_path), "netlist": str(flat), "spice": str(spice),
              "inputs": inputs, "outputs": {str(p): sha(p) for p in outputs},
              "declaration_sources": sources, "stand_in": settings.get("stand_in", False),
              "flow109_acceptance": "NOT_MEASURED", "delivery_accepted": False}
    write_json(project / RECORD, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.project)
    except (Refusal, OSError, ValueError, TypeError, KeyError) as exc:
        result = {"producer": "analog_macro_top_gen", "verdict": "REFUSED",
                  "reason": getattr(exc, "code", "A18_DECLARATION_INVALID"), "detail": str(exc)}
        write_json(args.project / RECORD, result)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "WROTE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
