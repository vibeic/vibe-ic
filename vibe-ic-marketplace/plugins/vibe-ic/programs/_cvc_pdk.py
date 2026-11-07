"""Lower PDK SPICE primitive calls to CVC's native CDL device syntax."""
from __future__ import annotations

import fnmatch
import gzip
import json
from pathlib import Path
import re

from _analog_a8_extraction_wrapper import logical_lines
from _pad_ring import (bond_fed_rails, parse_lef_pin_roles,
                       parse_liberty_supply_view, parse_spice_subckts)


ASSIGN = re.compile(r"\$?\b([A-Za-z_]\w*)\s*=\s*(\{[^}]*\}|'[^']*'|\"[^\"]*\"|[^\s]+)")
KINDS = {"MN": "M", "MP": "M", "LDDN": "M", "LDDP": "M",
         "M": "M", "R": "R", "D": "D", "C": "C", "Q": "Q"}


def assemble_cdl(text, config, pdk, models, source):
    """Resolve referenced cells from the same native views as WriteCDL and LVS."""
    cdls = config.get("CELL_CDLS") or [Path(pdk) / (
        f"libs.ref/{config['STD_CELL_LIBRARY']}/cdl/{config['STD_CELL_LIBRARY']}.cdl")]
    # Netgen.LVS lets SPICE_MODELS replace CELL_SPICE_MODELS, then adds extras/pads.
    spices = config.get("SPICE_MODELS") or config.get("CELL_SPICE_MODELS") or []
    paths = [*cdls, *(config.get("EXTRA_CDLS") or []), *(config.get("PAD_CDLS") or []),
             *spices, *(config.get("EXTRA_SPICE_MODELS") or []),
             *(config.get("PAD_SPICE_MODELS") or [])]
    # PDK CDL wrappers may call cells in their library's companion SPICE view.
    for cdl in [*cdls, *(config.get("EXTRA_CDLS") or []), *(config.get("PAD_CDLS") or [])]:
        paths.extend(sorted((Path(cdl).parent.parent / "spice").glob("*.spice")))
    headers = {}
    active = None
    # cdl.awk removes Magic's blackboxes. Keep their named terminal order for
    # binding to the PDK view, which can omit electrically aliased terminals.
    with Path(source).open() as stream:
        for line in stream:
            words = line.split()
            if not words or words[0].startswith("*"):
                continue
            if words[0] == "+" and active is not None:
                headers[active].extend(words[1:])
                continue
            active = words[1].casefold() if words[0].casefold() == ".subckt" else None
            if active is not None:
                headers[active] = words[2:]
    circuits, bindings = {}, {}
    block_pattern = r"(?ims)^[ \t]*\.subckt[ \t]+(\S+)[^\n]*\n.*?^[ \t]*\.ends\b[^\n]*"
    for path in dict.fromkeys(map(str, paths)):
        if path.endswith(".gz"):
            with gzip.open(path, "rt") as stream:
                library = stream.read()
        else:
            library = Path(path).read_text()
        for block in re.finditer(block_pattern, library):
            circuits.setdefault(block[1].casefold(), (block[0], path))

    def references(source):
        result = set()
        for line in logical_lines(source):
            if not line[:1].casefold() == "x":
                continue
            head = ASSIGN.search(line)
            result.add((line[:head.start()] if head else line).split()[-1].casefold())
        return result

    defined = {name.casefold() for name in re.findall(r"(?im)^\s*\.subckt\s+(\S+)", text)}
    defined.update(model_definitions(models))
    pending = references(text) - defined
    while pending:
        name = min(pending)
        pending.remove(name)
        if name in defined or name not in circuits:
            continue  # CVC reports a genuinely unresolved cell; never invent a model.
        block, path = circuits[name]
        text += f"\n* PDK subcircuit from {path}\n{block}\n"
        defined.add(name)
        target = logical_lines(block)[0].split()[2:]
        if name in headers:
            bindings[name] = (headers[name], target)
        pending.update(references(block) - defined)
    output = []
    for line in logical_lines(text):
        if line[:1].casefold() == "x":
            head = ASSIGN.search(line)
            words = (line[:head.start()] if head else line).split()
            master = words[-1].casefold()
            if master in bindings:
                original, target = bindings[master]
                nodes = [node for node in words[1:-1] if node != "/"]
                named = dict(zip(original, nodes))
                if (len(nodes) == len(original) == len(named)
                        and all(pin in named for pin in target)):
                    mapped = [named[pin] for pin in target]
                    # A missing physical terminal may be omitted only when its
                    # node already occurs on the native model's retained ports.
                    if set(nodes) <= set(mapped):
                        line = " ".join([words[0], *mapped, words[-1]])
                        if head:
                            line += " " + head.string[head.start():]
        output.append(line)
    return "\n".join(output) + "\n"


def assignments(text):
    return {name.casefold(): value for name, value in ASSIGN.findall(text)}


def model_definitions(text):
    result = {}
    for line in text.splitlines():
        words = line.split()
        if len(words) >= 2 and words[0] in KINDS:
            result[words[1].casefold()] = (KINDS[words[0]], line)
    return result


def primitive_definitions(pdk, needed):
    result = {}
    aliases = {}
    folders = [*(Path(pdk) / "libs.ref").glob("*/spice"), Path(pdk) / "libs.tech/ngspice"]
    for folder in folders:
        for path in sorted(folder.glob("*.spice")):
            text = path.read_text()
            if not any(name in text.casefold() for name in needed):
                continue
            for name, (ports, body) in parse_spice_subckts(text, preserve_parameters=True).items():
                key = name.casefold()
                if key not in needed:
                    continue
                defaults = assignments(" ".join(ports))
                for row in body:
                    if row[0].casefold() == ".param":
                        defaults.update(assignments(" ".join(row[1:])))
                elements = [row for row in body if not row[0].startswith(".")]
                if defaults and key not in result:
                    result[key] = {"defaults": defaults, "source": str(path)}
                if len(elements) == 1 and elements[0][0][0].casefold() == "x":
                    element = " ".join(elements[0])
                    head = ASSIGN.search(element)
                    words = (element[:head.start()] if head else element).split()
                    values = assignments(element)
                    terminals = [port for port in ports if "=" not in port]
                    if (words[1:-1] == terminals and all(values.get(name, "").strip("{}'\"") == name
                                                       for name in ("l", "w"))):
                        aliases.setdefault(key, {}).setdefault(words[-1].casefold(), str(path))
    for name, targets in aliases.items():
        if len(targets) == 1:
            target, source = next(iter(targets.items()))
            result.setdefault(name, {"defaults": {}}).update(alias=target, alias_source=source)
    return result


def normalize_cdl(text, pdk, models):
    definitions = model_definitions(models)
    circuit_names = {name.casefold() for name in
                     re.findall(r"(?im)^[ \t]*\.subckt[ \t]+(\S+)", text)}
    lines = logical_lines(text)
    needed = set()
    for index, line in enumerate(lines):
        words = line.split()
        if not words or words[0][0].upper() not in {"X", "M", "R", "C", "D", "Q"}:
            continue
        # CVC consumes CDL element designators; PDK SPICE can use lowercase.
        line = line[0].upper() + line[1:]
        # A Calibre bias terminal is metadata, and can precede the model tag.
        # Keep its connection while placing it after the model/geometry fields.
        bias = [word for word in line.split() if word.startswith("$SUB=")]
        if bias:
            line = " ".join([word for word in line.split() if not word.startswith("$SUB=")] + bias)
        head = ASSIGN.search(line)
        before = line[:head.start()] if head else line
        token = before.split()[-1]
        name = token.casefold()
        # Calibre wraps primitive model identifiers in $[...]. Bind to the
        # identically named native CVC profile without changing its properties.
        if name.startswith("$[") and name.endswith("]") and name[2:-1] in definitions:
            start = len(before.rstrip()) - len(token)
            native_name = definitions[name[2:-1]][1].split()[1]
            line = line[:start] + native_name + line[start + len(token):]
            name = name[2:-1]
        lines[index] = line
        definition = definitions.get(name)
        geometry = definition is not None and (definition[0] == "M" or
                    re.search(r"\b[wl]\b", definition[1].split("R=", 1)[-1], re.I))
        if ((geometry and not {"l", "w"} <= assignments(line).keys()) or
                (words[0][0].upper() == "X" and name not in circuit_names and definition is None)):
            needed.add(name)
    primitives = primitive_definitions(pdk, needed)
    pending = set(needed - definitions.keys())
    while pending:
        resolved = set()
        for name in sorted(pending):
            primitive = primitives.get(name, {})
            alias = definitions.get(primitive.get("alias"))
            if alias is not None:
                words = alias[1].split(maxsplit=2)
                line = words[0] + " " + name + (" " + words[2] if len(words) > 2 else "")
                models += f"\n# PDK alias from {primitive['alias_source']}\n{line}\n"
                definitions[name] = (alias[0], line)
                resolved.add(name)
        if not resolved:
            break
        pending -= resolved
    output = []
    for line in lines:
        words = line.split()
        if not words or words[0][0].upper() not in {"X", "M", "R", "C", "D", "Q"}:
            output.append(line)
            continue
        head = ASSIGN.search(line)
        before = line[:head.start()] if head else line
        name = before.split()[-1].casefold()
        definition = definitions.get(name)
        if definition is None or (words[0][0].upper() == "X" and name in circuit_names):
            output.append(line)
            continue
        if words[0][0].upper() == "X":
            line = definition[0] + line
        values = assignments(line)
        defaults = primitives.get(name, {}).get("defaults", {})
        for key in ("l", "w"):
            if key not in values and key in defaults:
                line += f" {key}={defaults[key]}"
        output.append(line)
    return "\n".join(output) + "\n", models


def pad_power_setup(netlist, config, views):
    """Declare native primary pad supplies and documented logical inputs.

    The PDK's power.awk only sees Verilog inputs, which omit physical supply
    bonds in a chip netlist. Bind the extracted top's terminals to its native
    pad subcircuits, then reuse the chip producer's PDK bond-to-rail discovery.
    CVC requires power settings for internal as well as external power nets:
    https://github.com/d-m-bailey/cvc/wiki/Power
    Only Liberty primary supplies are fixed; non-primary supplies and
    ordinary signals are not inferred from a voltage or a net name.
    """
    if not netlist or not config.get("PAD_LEFS"):
        return {}, {}
    top = re.search(r"(?ims)^[ \t]*\.subckt[ \t]+" + re.escape(config["DESIGN_NAME"])
                    + r"[ \t]+([^\n]*)\n(.*?)^[ \t]*\.ends\b[^\n]*", netlist)
    if top is None:
        return {}, {}  # Native CVC diagnoses an absent top.
    ports = set(top[1].split())
    subckts = parse_spice_subckts(netlist[:top.start()] + netlist[top.end():])
    roles = {}
    for path in config["PAD_LEFS"]:
        roles.update(parse_lef_pin_roles(Path(path).read_text()))
    cells = {master: [(view, view["cells"][master]) for view in views
                     if master in view["cells"]]
             for master in roles}
    prepared = (Path(config["DESIGN_DIR"]) / "work/flow/chip/preparation.json"
                if config.get("DESIGN_DIR") else None)
    pads = json.loads(prepared.read_text()).get("pads", {}) if prepared and prepared.is_file() else {}
    configured = set((config.get("VDD_NETS") or [config.get("VDD_PIN")])
                     + (config.get("GND_NETS") or [config.get("GND_PIN")]))
    result, inputs = {}, {}

    def declare(name, voltage):
        if name in result and result[name] != voltage:
            raise ValueError(f"Conflicting active PDK Liberty voltages for {name}")
        result[name] = voltage

    for match in re.finditer(r"(?m)^[ \t]*[Xx]\S+[^\n]*", top[2]):
        words = match[0].split()
        master = words[-1]
        if master not in cells or master not in subckts:
            continue
        terminals = subckts[master][0]
        if len(terminals) != len(words) - 2:
            continue  # Keep a native terminal-count error visible.
        nets = dict(zip(terminals, words[1:-1]))
        declared = pads.get(words[0][1:], {})
        for view, cell in cells[master]:
            if view["nom_voltage"] is None:
                continue
            for pin, attrs in cell["pg_pins"].items():
                if (pin in nets and attrs.get("pg_type") in {"primary_power", "primary_ground"}
                        and attrs.get("voltage_name") in view["voltage_map"]):
                    # CVC distinguishes a top port from a local top-cell net
                    # by its leading hierarchy delimiter.
                    name = nets[pin] if nets[pin] in ports else "/" + nets[pin]
                    declare(name, view["voltage_map"][attrs["voltage_name"]])
            for kind in ("pins", "pg_pins"):
                for pin, attrs in cell[kind].items():
                    use = roles[master].get(pin, (None, None))[1]
                    name = nets.get(pin)
                    if (kind == "pins" and attrs.get("is_pad") == "true" and name in ports
                            and declared.get("direction") == "input"
                            and declared.get("master") == master and declared.get("port") == name
                            and declared.get("terminal") == pin):
                        # Chip preparation owns the selected logical direction;
                        # an inout bond is not automatically an external input.
                        bounds = [cell["pg_pins"].get(attrs.get(key), {}).get("voltage_name")
                                  for key in ("related_ground_pin", "related_power_pin")]
                        if all(rail in view["voltage_map"] for rail in bounds):
                            levels = tuple(view["voltage_map"][rail] for rail in bounds)
                            if name in inputs and inputs[name] != levels:
                                raise ValueError(f"Conflicting active PDK Liberty input levels for {name}")
                            inputs[name] = levels
                    if (attrs.get("is_pad") != "true" or nets.get(pin) not in ports
                            or use not in {"POWER", "GROUND"}):
                        continue
                    if nets[pin] in configured:
                        continue  # This bond already has the configured native supply definition.
                    fed = [pin] if kind == "pg_pins" else bond_fed_rails(subckts, master, pin)[0]
                    polarity = "primary_power" if use == "POWER" else "primary_ground"
                    values = {view["voltage_map"][pg["voltage_name"]]
                              for rail in fed
                              if (pg := cell["pg_pins"].get(rail, {})).get("pg_type") == polarity
                              and pg.get("voltage_name") in view["voltage_map"]}
                    if len(values) != 1:
                        raise ValueError(f"No unique PDK Liberty voltage for supply bond {master}/{pin}")
                    declare(nets[pin], values.pop())
    return result, inputs


def power_setup(text, config, netlist=None):
    views = []
    for key in ("LIB", "PAD_LIBS", "EXTRA_LIBS"):
        libraries = config.get(key) or []
        if isinstance(libraries, dict):
            libraries = [path for pattern, paths in libraries.items()
                         if fnmatch.fnmatchcase(config.get("DEFAULT_CORNER", ""), pattern)
                         for path in paths]
        for path in libraries:
            if str(path).endswith(".gz"):
                with gzip.open(path, "rt") as stream:
                    library_text = stream.read()
            else:
                library_text = Path(path).read_text()
            views.append(parse_liberty_supply_view(library_text))
    voltages = {}
    for view in views:
        # Topology-only libraries can label supplies without characterizing
        # an operating voltage. Their voltage_map is not a corner stimulus.
        if view["nom_voltage"] is None:
            continue
        for name, value in view["voltage_map"].items():
            if name in voltages and voltages[name] != value:
                raise ValueError(f"Conflicting active PDK Liberty voltages for {name}")
            voltages[name] = value
    nominal = views[0]["nom_voltage"] if views else None
    supplies = config.get("VDD_NETS") or [config["VDD_PIN"]]
    grounds = config.get("GND_NETS") or [config["GND_PIN"]]
    lines = text.splitlines()
    original = {words[0]: words[2] for line in lines
                if len(words := line.split()) == 3 and words[1] == "power"}
    domains, inputs = pad_power_setup(netlist, config, views)
    rails = set(supplies + grounds) | domains.keys()
    result = [line for line in lines if not re.match(r"^\S+\s+power\s", line)
              and not (len(words := line.split()) > 1 and words[0] in rails and words[1] == "input")]
    for name in supplies:
        value = voltages.get(name, nominal if name == supplies[0] else None)
        if value is None:
            value = original.get(name)
        if value is None:
            raise ValueError(f"No PDK Liberty voltage or CVC power declaration for {name}")
        result.insert(0, f"{name} power {value}")
    for name in grounds:
        value = voltages.get(name, original.get(name, original.get(grounds[0])))
        if value is None:
            raise ValueError(f"No PDK Liberty voltage or CVC power declaration for {name}")
        result.insert(0, f"{name} power {value}")
    for name, value in domains.items():
        existing = next((line.split()[2] for line in result
                         if line.split()[:2] == [name, "power"]), None)
        if existing is not None and float(existing) != value:
            raise ValueError(f"Conflicting active PDK Liberty voltages for {name}")
        if existing is None:
            result.insert(0, f"{name} power {value}")
    for name, (low, high) in inputs.items():
        # Replace only the native core-domain default, preserving explicit levels.
        result = [line for line in result if line.split() != [name, "input", "std_input"]]
        if not any(line.split()[:1] == [name] for line in result):
            result.append(f"{name} input min@{low} max@{high}")
    return "\n".join(result) + "\n"


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk", type=Path, required=True)
    parser.add_argument("--cdl", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    text, models = normalize_cdl(args.cdl.read_text(), args.pdk, args.models.read_text())
    args.cdl.write_text(text)
    (args.cdl.parent / "models").write_text(models)


if __name__ == "__main__":
    main()
