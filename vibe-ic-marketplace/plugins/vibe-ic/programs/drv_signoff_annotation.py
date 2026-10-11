"""Reconcile OpenSTA's unannotated names with Liberty, LEF and route evidence."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drv_signoff_judge import _liberty_limits


def _lef_pin_models(paths: list[dict]) -> dict[tuple[str, str], dict]:
    models: dict[tuple[str, str], dict] = {}
    classes: dict[str, str] = {}
    for item in paths:
        macro = pin = None
        for raw in Path(item["path"]).read_text().splitlines():
            line = raw.strip()
            match = re.fullmatch(r"MACRO\s+(\S+)", line, re.I)
            if match:
                macro, pin = match.group(1), None
                continue
            match = re.fullmatch(r"PIN\s+(\S+)", line, re.I)
            if match and macro:
                pin = match.group(1)
                models.setdefault((macro, pin), {})
                continue
            match = re.fullmatch(r"CLASS\s+([^;]+)\s*;", line, re.I)
            if match and macro and not pin:
                value = " ".join(match.group(1).upper().split())
                if macro in classes and classes[macro] != value:
                    raise ValueError(f"LEF CLASS conflicts for {macro}")
                classes[macro] = value
                continue
            match = re.fullmatch(
                r"(USE|DIRECTION)\s+([A-Z]+(?:\s+[A-Z]+)?)\s*;", line, re.I)
            if match and macro and pin:
                key = (macro, pin)
                field = match.group(1).lower()
                value = " ".join(match.group(2).upper().split())
                if field == "use" and value not in (
                        "POWER", "GROUND", "SIGNAL", "CLOCK", "ANALOG", "SCAN"):
                    continue
                if field in models[key] and models[key][field] != value:
                    raise ValueError(f"LEF {field.upper()} conflicts for {macro}/{pin}")
                models[key][field] = value
                continue
            match = re.fullmatch(r"END\s+(\S+)", line, re.I)
            if match:
                if pin and match.group(1) == pin:
                    pin = None
                elif macro and match.group(1) == macro:
                    macro, pin = None, None
    if not any("use" in model for model in models.values()):
        raise ValueError("linked LEF pin USE census empty")
    for (macro, _), model in models.items():
        model["class"] = classes.get(macro)
    return models


def _lef_uses(paths: list[dict]) -> dict[tuple[str, str], str]:
    return {key: model["use"] for key, model in _lef_pin_models(paths).items()
            if "use" in model}


def _is_physical_pin(pin: dict, models: dict, modeled_cells: set[str]) -> bool:
    """A passive LEF corner, spacer or supply master can lack a Liberty cell.

    Keep it in the pin inventory; only its absent timing check is inapplicable.
    A missing model on a logic cell, clock or actual driver is still an error.
    """
    model = models.get((pin.get("cell"), pin.get("cell_pin")), {})
    master_class = model.get("class") or ""
    physical = (master_class == "PAD SPACER" or
                master_class.split()[:1] == ["ENDCAP"])
    if master_class in ("PAD POWER", "PAD AREAIO"):
        # AREAIO alone also denotes functional IO. Require the complete LEF
        # to describe an INOUT-only supply master, with typed power/ground.
        macro_pins = [item for (cell, _), item in models.items()
                      if cell == pin.get("cell")]
        physical = (bool(macro_pins) and
                    all(item.get("direction") == "INOUT" for item in macro_pins) and
                    any(item.get("use") in ("POWER", "GROUND") for item in macro_pins))
    return (pin.get("kind") == "pin" and pin.get("cell") not in modeled_cells
            and not pin.get("driver") and not pin.get("clock")
            and pin.get("direction") in ("unknown", "inout")
            and model.get("direction") == "INOUT"
            and physical)


def _unannotated(body: str) -> list[str]:
    found = []
    pattern = re.compile(r"(?m)^Found\s+(\d+)\s+((?:partially\s+)?unannotated)\s+drivers\.\s*$")
    matches = list(pattern.finditer(body))
    if not matches:
        raise ValueError("OpenSTA unannotated driver grammar absent")
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        names = [line.strip() for line in body[match.end():end].splitlines()
                 if line.strip() and not line.startswith("=")]
        if len(names) != int(match.group(1)):
            raise ValueError("OpenSTA unannotated names differ from count")
        found.extend(names)
    if len(set(found)) != len(found):
        raise ValueError("OpenSTA unannotated driver repeated")
    return sorted(found)


def _unescape(name: str) -> str:
    """Compare SPEF and OpenSTA names without their escape characters."""
    return re.sub(r"\\(.)", r"\1", name)


def _spef_connections(path: Path) -> dict[str, set[str]]:
    """Map every SPEF *D_NET to the pin endpoints its *CONN section names.

    A net name alone is not parasitic evidence for a pin (R-0928-DRV-IC): only
    a *P port or *I instance pin inside that net's *CONN section is.
    """
    divider, delimiter = "/", ":"
    names: dict[str, str] = {}
    nets: dict[str, set[str]] = {}
    section = None
    current = None
    reduced = False
    for line in path.read_text(errors="replace").splitlines():
        words = line.split()
        if not words:
            continue
        head = words[0]
        if reduced and head != "*END":
            continue  # a *R_NET reduced model names no distributed pin RC
        if head in ("*P", "*I"):
            if section != "*CONN" or current is None:
                raise ValueError(f"SPEF {head} outside a *D_NET *CONN section")
            if len(words) < 3:
                raise ValueError(f"SPEF {head} connection grammar invalid")
            if head == "*P":
                endpoint = _unescape(names.get(words[1], words[1]))
            else:
                instance, found, pin = words[1].rpartition(delimiter)
                if not found or not instance or not pin:
                    raise ValueError("SPEF *I instance pin grammar invalid")
                instance = names.get(instance, instance)
                if divider != "/":
                    instance = instance.replace(divider, "/")
                endpoint = _unescape(instance) + "/" + _unescape(pin)
            nets[current].add(endpoint)
        elif head == "*N":
            continue  # an internal RC node is not a pin endpoint
        elif head in ("*DIVIDER", "*DELIMITER") and len(words) == 2:
            if head == "*DIVIDER":
                divider = words[1]
            else:
                delimiter = words[1]
        elif head == "*D_NET":
            if len(words) < 3:
                raise ValueError("SPEF *D_NET grammar invalid")
            current = _unescape(names.get(words[1], words[1]))
            if current in nets:
                raise ValueError(f"SPEF net repeated: {current}")
            nets[current] = set()
            section = head
        elif head == "*R_NET":
            current, section, reduced = None, head, True
        elif head == "*END":
            current, section, reduced = None, None, False
        elif head.startswith("*") and head[1:].isdigit():
            if section == "*NAME_MAP" and len(words) >= 2:
                names[head] = words[1]
        elif head.startswith("*") and head[1:].replace("_", "").isalpha():
            section = head
    return nets


#: Routed geometry in a DEF net record.  Regular wiring opens with one of
#: the four wiring statuses (a SUBNET's wiring has no leading '+'); special
#: wiring adds SHIELD and the DEF 5.8 RECT / POLYGON / VIA shapes.
_REGULAR_WIRING = re.compile(r"\b(?:ROUTED|FIXED|COVER|NOSHIELD)\b")
_SPECIAL_WIRING = re.compile(r"\b(?:ROUTED|FIXED|COVER|SHIELD|NOSHIELD)\b"
                             r"|\+\s*(?:RECT|POLYGON|VIA)\b")
_CONNECTION = re.compile(r"\(\s*(\S+)\s+(\S+)(?:\s+\+\s*SYNTHESIZED)?\s*\)")


def _net_record(record: str) -> tuple[list[tuple[str, str]], str]:
    """Split one net record into its connection list and the rest."""
    connections = []
    rest = record
    while True:
        match = _CONNECTION.match(rest.lstrip())
        if not match:
            break
        connections.append(match.groups())
        rest = rest.lstrip()[match.end():]
    return connections, rest


def _def_segments(path: Path) -> dict[str, dict]:
    """Every NETS and SPECIALNETS net: its routed-geometry count and the pin
    endpoints its connection list names (R-0928-DRV-IC: a zero-segment proof
    needs both).  A net present in both sections is one net."""
    body = path.read_text(errors="replace")
    sections = {"NETS": re.search(r"(?ms)^NETS\s+\d+\s*;\s*(.*?)^END NETS\b", body),
                "SPECIALNETS": re.search(
                    r"(?ms)^SPECIALNETS\s+\d+\s*;\s*(.*?)^END SPECIALNETS\b", body)}
    if not sections["NETS"]:
        raise ValueError("routed DEF NETS section absent")
    result: dict[str, dict] = {}
    for section, match in sections.items():
        if not match:
            continue
        seen: set[str] = set()
        wiring = _REGULAR_WIRING if section == "NETS" else _SPECIAL_WIRING
        for item in re.finditer(r"(?ms)^\s*-\s+(\S+)\s+(.*?);", match.group(1)):
            name, record = item.groups()
            if name in seen:
                raise ValueError(f"routed DEF {section} net repeated")
            seen.add(name)
            connections, rest = _net_record(record)
            net = result.setdefault(_unescape(name), {"segments": 0, "endpoints": set(),
                                           "wildcard": False, "sections": []})
            net["sections"].append(section)
            net["segments"] += len(wiring.findall(rest))
            for component, pin in connections:
                if component == "*":
                    net["wildcard"] = True  # every instance's pin: not a pin list
                elif component == "PIN":
                    net["endpoints"].add(_unescape(pin))
                else:
                    net["endpoints"].add(_unescape(component) + "/" + _unescape(pin))
    return result


def _zero_segment_proof(net: dict | None, pins: set[str]) -> bool:
    """The net carries no routed segment and its endpoints are exactly the
    census pins on it."""
    return bool(net) and net["segments"] == 0 and not net["wildcard"] and (
        net["endpoints"] == pins)


def derive(scene_dir: Path, pins: dict, liberties: list[dict], lefs: list[dict],
           routed_def: Path, spef: Path) -> dict:
    """Only LEF PG pins without any linked timing arc leave the population."""
    uses = _lef_uses(lefs)
    lib_pins = {}
    for item in liberties:
        cells = _liberty_limits(Path(item["path"]).read_text())["cells"]
        for cell, cell_pins in cells.items():
            for pin, props in cell_pins.items():
                key = (cell, pin)
                if key in lib_pins and lib_pins[key] != props:
                    raise ValueError(f"linked Liberty pin conflicts for {cell}/{pin}")
                lib_pins[key] = props
    pg = []
    unconnected = []
    for name, pin in sorted(pins.items()):
        if not pin["net"]:
            unconnected.append(name)
        key = (pin["cell"], pin["cell_pin"])
        if uses.get(key) in ("POWER", "GROUND") and key in lib_pins and not lib_pins[key]["has_timing_arc"]:
            pg.append({"pin": name, "lef_use": uses[key],
                       "liberty_timing_arc": False, "net": pin["net"]})
    names = _unannotated((scene_dir / "annotation.rpt").read_text())
    pg_names = {item["pin"] for item in pg}
    by_net = {}
    for name, pin in pins.items():
        if pin["net"]:
            by_net.setdefault(pin["net"], []).append(name)
    spef_connections = _spef_connections(spef)
    segments = _def_segments(routed_def)
    resolved = []
    unresolved = []
    for name in names:
        pin = pins.get(name)
        if pin is None:
            unresolved.append({"pin": name, "reason": "not_in_pin_census"})
        elif name in pg_names:
            resolved.append({"pin": name, "reason": "lef_pg_no_liberty_arc"})
        elif not pin["net"]:
            resolved.append({"pin": name, "reason": "unconnected_no_net"})
        else:
            net = pin["net"]
            members = by_net.get(net, [])
            # R-0928-DRV-IC's port-to-PAD net: the top-level port and IO-cell
            # pins only.  A net that also reaches a core pin is not one; its
            # missing RC understates that pin's load (review wave 57).
            port_pad = (any(pins[m]["kind"] == "port" for m in members) and
                        any(pins[m]["cell_class"] == "IO" for m in members) and
                        all(pins[m]["kind"] == "port" or pins[m]["cell_class"] == "IO"
                            for m in members))
            # The SPEF must carry this net's connectivity at the pin level:
            # the reported driver, its PAD endpoint and every other census pin
            # on the net.  A *D_NET header without those *CONN rows is not RC
            # evidence for any of them.
            endpoints = spef_connections.get(_unescape(net))
            wanted = {_unescape(m) for m in members} | {_unescape(name)}
            if port_pad and endpoints is not None and wanted <= endpoints:
                resolved.append({"pin": name, "net": net,
                                 "reason": "port_pad_spef_conn",
                                 "spef_endpoints": sorted(wanted)})
            elif port_pad and _zero_segment_proof(segments.get(_unescape(net)), wanted):
                resolved.append({"pin": name, "net": net,
                                 "reason": "port_pad_zero_routed_segments",
                                 "def_sections": segments[_unescape(net)]["sections"],
                                 "def_endpoints": sorted(wanted)})
            else:
                unresolved.append({"pin": name, "net": net,
                                   "reason": "missing_parasitic_or_geometry_proof"})
    return {"unannotated_names": names, "pg_exclusions": pg,
            "unconnected_pins": unconnected, "resolved": resolved,
            "unresolved": unresolved}
