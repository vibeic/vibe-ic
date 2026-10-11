"""Derive DRV populations and pin classes from fresh OpenSTA census files."""
from __future__ import annotations

import re
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drv_signoff_judge import KINDS, _NUM, _liberty_limits, port_to_pad
from drv_signoff_annotation import _is_physical_pin, _lef_pin_models


def _pins(path: Path) -> dict[str, dict]:
    pins = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 14 or not fields[0] or fields[0] in pins:
            raise ValueError("OpenSTA pin census malformed or duplicated")
        (name, kind, direction, driver, instance, cell, cell_pin, net,
         origin, rise, fall, clock, logic, ideal) = fields
        if (kind not in ("pin", "port") or driver not in ("0", "1") or
                clock not in ("0", "1") or logic not in ("0", "1", "X") or
                ideal not in ("0", "1")):
            raise ValueError("OpenSTA pin census type invalid")
        pins[name] = {"kind": kind, "direction": direction,
                      "driver": driver == "1", "instance": instance,
                      "cell": cell, "cell_pin": cell_pin, "net": net,
                      "origin": origin, "clock": clock == "1",
                      "logic": logic, "ideal": ideal == "1",
                      "slew_rise_ns": float(rise), "slew_fall_ns": float(fall)}
        if not all(math.isfinite(pins[name][axis]) and pins[name][axis] >= 0
                   for axis in ("slew_rise_ns", "slew_fall_ns")):
            raise ValueError("OpenSTA pin slew census is not finite")
    if not pins:
        raise ValueError("OpenSTA pin census empty")
    return pins


def _nets(path: Path) -> dict[str, dict]:
    nets = {}
    raw_blocks = {}
    for block in re.split(r"(?m)^Net ", path.read_text())[1:]:
        name, _, rest = block.partition("\n")
        # OpenSTA enumerates Verilog aliases but report_net prints the same
        # canonical net for each. Only byte-identical repetitions are benign;
        # conflicting or truncated repetitions are refused, never combined.
        if name in raw_blocks and block.strip() == raw_blocks[name]:
            continue
        cap = re.search(r"(?m)^ Total capacitance:\s*(\S+)", rest)
        loads = re.search(r"(?ms)^Load pins\n(.*?)(?:\n\n|\Z)", rest)
        drivers = re.search(r"(?ms)^Driver pins\n(.*?)(?:\n\n|\Z)", rest)
        counts = {kind: re.search(rf"(?m)^ Number of {kind}:[ \t]*(\d+)[ \t]*$", rest)
                  for kind in ("drivers", "loads", "pins")}
        if not cap or not all(counts.values()) or name in nets:
            raise ValueError("OpenSTA net census malformed")
        populations = {kind: int(count.group(1)) for kind, count in counts.items()}
        load_names = ([line.strip().split()[0] for line in loads.group(1).splitlines()
                       if line.strip()] if loads is not None else [])
        driver_names = ([line.strip().split()[0] for line in drivers.group(1).splitlines()
                         if line.strip()] if drivers is not None else [])
        if len(load_names) != populations["loads"]:
            raise ValueError("OpenSTA net load count differs from raw report")
        if len(driver_names) != populations["drivers"]:
            raise ValueError("OpenSTA net driver count differs from raw report")
        if (len(set(load_names)) != len(load_names) or
                len(set(driver_names)) != len(driver_names) or
                len(set(driver_names + load_names)) != populations["pins"]):
            raise ValueError("OpenSTA net pin count differs from raw report")
        # report_net prints a min-max capacitance range when the linked
        # process has distinct rise/fall values.  Retain the larger endpoint
        # for a conservative excluded-pin check.
        cap_range = re.fullmatch(rf"({_NUM})(?:-({_NUM}))?", cap.group(1))
        if cap_range is None:
            raise ValueError("OpenSTA net capacitance grammar invalid")
        cap_pf = max(float(value) for value in cap_range.groups() if value is not None)
        if not math.isfinite(cap_pf) or cap_pf < 0:
            raise ValueError("OpenSTA net capacitance census is not finite")
        nets[name] = {"cap_pf": cap_pf, "loads": load_names, "drivers": driver_names}
        raw_blocks[name] = block.strip()
    return nets


def _disabled(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        words = line.split()
        if len(words) >= 4 and words[3] in ("constraint", "constant"):
            for port in words[1:3]:
                result[words[0] + "/" + port] = (
                    "disabled" if words[3] == "constraint" else "constant")
    return result


def port_connectivity(pins: dict, nets: dict, pad_cells: set) -> dict[str, bool]:
    """Prove the port class from BOTH complete OpenSTA pin and net censuses.

    A partial report cannot prove absence of a core load. Reconcile every
    endpoint with the independent pin inventory, including drivers and ports.
    Unknown, duplicate, omitted or extra endpoints keep the port counted.
    """
    # A link-time port-width mismatch can leave the core input disconnected
    # while report_net still looks IO-only. Such unresolved inputs cannot be
    # used as proof of absence. Retain the measured port rows conservatively.
    unresolved = any(p["kind"] == "pin" and p.get("direction") in ("input", "inout")
                     and not p.get("net") and p.get("cell") not in pad_cells
                     for p in pins.values())
    result = {}
    for name, pin in pins.items():
        if pin["kind"] != "port":
            continue
        net_name = pin.get("net")
        net = nets.get(net_name) or {}
        endpoints = net.get("drivers", []) + net.get("loads", [])
        inventory = {p for p, item in pins.items() if item.get("net") == net_name}
        complete = (bool(net_name) and name in endpoints and
                    len(endpoints) == len(set(endpoints)) and
                    set(endpoints) == inventory)
        result[name] = complete and not unresolved and port_to_pad(
            name, endpoints, lambda p: (pins[p]["kind"] == "pin" and
                                        pins[p].get("cell") in pad_cells))
    return result


def _core_only_kinds(body: str, core_cells: set[str], *,
                     ignore_port_limits: bool = False) -> set[str]:
    """Recognize the existing emitter's literal core-master limit block.

    A non-core missing row is inapplicable only if its Liberty has no limit
    and the generated SDC supplies none outside this verified core scope.
    Unknown expressions/scopes remain unproven, not silently accepted.
    """
    checked = False
    block = re.compile(
        r"foreach\s+_vibeic_core_master\s+\[list ([^\n]+)\]\s*\{\s*"
        r"foreach\s+_vibeic_core_cell\s+\[get_lib_cells -quiet \*/\$_vibeic_core_master\]\s*\{"
        r"(.*?)\n\s*\}\s*\}", re.S)
    def remove(match):
        nonlocal checked
        names = re.findall(r"\{([^{}]+)\}", match[1])
        if (not names or not set(names).issubset(core_cells) or
                re.sub(r"\{[^{}]+\}", "", match[1]).strip()):
            return match[0]
        commands = [line.strip() for line in match[2].splitlines() if line.strip()]
        if not commands or any(not re.fullmatch(
                rf"set_max_(?:fanout|capacitance|transition)\s+{_NUM}\s+"
                r"\[\$_vibeic_core_cell cell\]", line) for line in commands):
            return match[0]
        checked = True
        return ""
    rest = block.sub(remove, body)
    if not checked:
        return set()
    if ignore_port_limits:
        # Port constraints do not turn a verified core-cell block into a
        # design-wide constraint. The caller resolves them per actual port.
        rest = re.sub(
            rf"(?m)^\s*set_max_(?:fanout|capacitance|transition)\s+{_NUM}\s+"
            r"\[get_ports[^\n;]*\]\s*$", "", rest)
    return {kind for kind in KINDS if not re.search(
        rf"(?m)^\s*set_{kind.replace('max_slew', 'max_transition')}\b", rest)}


def derive(scene_dir: Path, linked_liberties: list[dict],
           all_rows: dict[str, list[dict]],
           linked_lefs: list[dict] | None = None, *,
           allow_unproven: bool = False, signoff_sdc: Path | None = None,
           core_liberty: str | None = None) -> dict:
    """Reconcile reported rows with pin and net identities from one STA run."""
    pins = _pins(scene_dir / "pin_census.tsv")
    nets = _nets(scene_dir / "net_census.rpt")
    disabled = _disabled(scene_dir / "disabled_edges.rpt")
    libs = []
    for item in linked_liberties:
        limits = _liberty_limits(Path(item["path"]).read_text())
        libs.append((item["name"], limits))
    core_cells = {cell for name, limits in libs if name == core_liberty
                  for cell in limits["cells"]}
    core_only = (_core_only_kinds(signoff_sdc.read_text(), core_cells)
                 if signoff_sdc is not None and core_cells else set())
    lef_models = _lef_pin_models(linked_lefs) if linked_lefs else {}
    lef_uses = {key: model["use"] for key, model in lef_models.items()
                if "use" in model}
    modeled_cells = {cell for _, limits in libs for cell in limits["cells"]}
    lib_pins = {(cell, cell_pin): props for _, limits in libs
                for cell, pins_in_cell in limits["cells"].items()
                for cell_pin, props in pins_in_cell.items()}
    pad_cells = set().union(*(limits["pad_cells"] for _, limits in libs)) if libs else set()
    port_classes = port_connectivity(pins, nets, pad_cells)
    metadata = {}
    for name, pin in pins.items():
        if pin["kind"] == "port":
            cell_class = "port"
            liberty = None
        elif pin["direction"] == "internal" and not pin["net"]:
            cell_class = "internal"
            liberty = None
        else:
            matches = [(lib_name, limits) for lib_name, limits in libs
                       if pin["cell"] in limits["cells"] and
                       pin["cell_pin"] in limits["cells"][pin["cell"]]]
            if not matches and _is_physical_pin(pin, lef_models, modeled_cells):
                liberty, cell_class = None, "physical"
            elif len(matches) != 1:
                raise ValueError(f"OpenSTA instance {name} lacks unique linked Liberty pin")
            else:
                liberty, limits = matches[0]
                cell_class = "IO" if pin["cell"] in limits["pad_cells"] else "std"
        net_class = ("constant" if pin["logic"] in ("0", "1") else
                     "clock" if pin["clock"] else
                     "IO" if cell_class in ("IO", "port") else "data")
        metadata[name] = {"kind": pin["kind"],
                          "net_class": net_class, "cell_class": cell_class,
                          "cell": pin["cell"] or None,
                          "cell_pin": pin["cell_pin"] or None,
                          "liberty": liberty,
                          "driver_pin": name if pin["driver"] else None,
                          "driver_cell": pin["cell"] or None,
                          "net": pin["net"] or None}
        if pin["kind"] == "port":
            # R-0928-DRV-IC: a port whose net reaches nothing but IO-cell pins
            # (the port-to-PAD net) is off-chip; the judge reads it by the IO
            # Liberty on the pad pin, never by the std-cell margin. Proven from
            # OpenSTA's own net census (driver and load pins), else False.
            metadata[name]["port_to_pad"] = port_classes[name]
    drivers = {name for name, pin in pins.items() if pin["driver"]}
    all_names = {kind: {row["pin"] for row in all_rows[kind]} for kind in KINDS}
    if any(not names.issubset(pins) for names in all_names.values()):
        raise ValueError("OpenSTA DRV report contains pin outside netlist census")
    excluded = []
    unproven = []
    omitted = ((drivers - all_names["max_fanout"]) |
               (drivers - all_names["max_capacitance"]) |
               (set(pins) - all_names["max_slew"]))
    for name in sorted(omitted):
        pin = pins[name]
        kinds = [kind for kind in KINDS if name not in all_names[kind] and
                 (kind == "max_slew" or pin["driver"])]
        meta = metadata[name]
        limit_lib = next((limits for lib_name, limits in libs
                          if lib_name == meta["liberty"]), None)
        unbounded = (meta["cell_class"] == "port" or
                     (limit_lib is not None and meta["liberty"] != core_liberty))
        no_limit = unbounded and all(kind in core_only and
            (limit_lib is None or
             (limit_lib["cells"][pin["cell"]][pin["cell_pin"]].get(kind) is None and
              limit_lib["defaults"].get(kind) is None)) for kind in kinds)
        key = (pin["cell"], pin["cell_pin"])
        pg_without_arc = (lef_uses.get(key) in ("POWER", "GROUND") and
                          key in lib_pins and not lib_pins[key]["has_timing_arc"])
        reason = ("lef_physical_no_liberty_arc" if metadata[name]["cell_class"] == "physical" else
                  "lef_pg_no_liberty_arc" if pg_without_arc else
                  "unconnected_no_net" if not pin["net"] else
                  "constant" if pin["logic"] in ("0", "1") else
                  (disabled.get(name) or ("ideal" if pin["ideal"] else
                   "no_applicable_limit" if no_limit else None)))
        if reason not in ("constant", "disabled", "ideal", "lef_pg_no_liberty_arc",
                          "lef_physical_no_liberty_arc",
                          "no_applicable_limit",
                          "unconnected_no_net"):
            if not allow_unproven:
                raise ValueError(f"OpenSTA omitted driver {name} without exclusion proof")
            reason = "unproven"
            unproven.append(name)
        net = nets.get(pin["net"])
        if pin["net"] and net is None:
            raise ValueError(f"OpenSTA net {pin['net']} absent for excluded pin")
        fanout = 0.0
        for load_name in ((net or {}).get("loads", []) if pin["driver"] else []):
            load = pins.get(load_name)
            if load is None:
                raise ValueError(f"OpenSTA load {load_name} absent from pin census")
            if load["kind"] == "port":
                continue
            matches = [limits for _, limits in libs if load["cell"] in limits["cells"]
                       and load["cell_pin"] in limits["cells"][load["cell"]]]
            if len(matches) != 1:
                if metadata[load_name]["cell_class"] == "physical":
                    # OpenSTA CheckFanouts::fanoutLoad adds one when a load
                    # has no Liberty port. Keep that load in the fanout.
                    fanout += 1.0
                    continue
                raise ValueError(f"OpenSTA load {load_name} lacks unique Liberty pin")
            limit = matches[0]
            load_weight = limit["cells"][load["cell"]][load["cell_pin"]].get(
                "fanout_load")
            if load_weight is None:
                load_weight = limit.get("default_fanout_load")
            fanout += load_weight if load_weight is not None else 0.0
        excluded.append({"pin": name, "reason": reason, "excluded_kinds": kinds,
                         "fanout": fanout,
                         "cap_pf": (net or {}).get("cap_pf", 0.0),
                         "slew_rise_ns": pin["slew_rise_ns"],
                         "slew_fall_ns": pin["slew_fall_ns"]})
    expected_fanout = drivers - {item["pin"] for item in excluded
                                 if "max_fanout" in item["excluded_kinds"]}
    if expected_fanout != all_names["max_fanout"]:
        raise ValueError("OpenSTA driver census disagrees with all-limits fanout rows")
    expected_cap = drivers - {item["pin"] for item in excluded
                              if "max_capacitance" in item["excluded_kinds"]}
    if all_names["max_capacitance"] != expected_cap:
        raise ValueError("OpenSTA driver census disagrees with all-limits cap rows")
    slew_pins = set(pins) - {item["pin"] for item in excluded
                             if "max_slew" in item["excluded_kinds"]}
    if all_names["max_slew"] != slew_pins:
        raise ValueError("OpenSTA pin census disagrees with all-limits slew rows")
    return {"pins": metadata, "excluded": excluded,
            "unproven": unproven,
            "clock_network_pins": sorted(name for name, pin in pins.items() if pin["clock"]),
            "driver_pins": sorted(drivers),
            "population": {"max_slew": len(slew_pins),
                           "max_capacitance": len(expected_cap),
                           "max_fanout": len(expected_fanout)}}
