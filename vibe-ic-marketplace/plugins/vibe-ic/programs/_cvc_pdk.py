"""Lower PDK SPICE primitive calls to CVC's native CDL device syntax."""
from __future__ import annotations

import fnmatch
import gzip
from pathlib import Path
import re

from _analog_a8_extraction_wrapper import logical_lines
from _pad_ring import parse_liberty_supply_view, parse_spice_subckts


ASSIGN = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*(\{[^}]*\}|'[^']*'|\"[^\"]*\"|[^\s]+)")
KINDS = {"MN": "M", "MP": "M", "LDDN": "M", "LDDP": "M",
         "M": "M", "R": "R", "D": "D", "C": "C", "Q": "Q"}


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
    for line in lines:
        words = line.split()
        if not words or words[0][0].upper() not in {"X", "M", "R", "C", "D", "Q"}:
            continue
        head = ASSIGN.search(line)
        before = line[:head.start()] if head else line
        name = before.split()[-1].casefold()
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


def power_setup(text, config):
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
    rails = set(supplies + grounds)
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
