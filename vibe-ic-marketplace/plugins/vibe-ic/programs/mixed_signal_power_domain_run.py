#!/usr/bin/env python3
"""M2: placed protection-cell evidence from UPF + routed Verilog/DEF.

ENFORCEMENT: blocking

Default uses one Yosys read_liberty/read_verilog/hierarchy/write_json invocation.
The tool does NOT insert cells or simulate power-off behavior. This producer
derives signal paths and counts only Liberty-identified protection cells on
those paths, also present and placed in the routed DEF. It consumes the merged
GDS without claiming geometrical, electrical or dynamic power verification.

Supported intent is the literal, flat UPF subset documented in
flow/mixed_signal_m2.md. Unknown voltages, hierarchy, ambiguous domains, unsupported
Tcl, unresolved pins/drivers and incomplete protection metadata fail closed.
No waiver is read. rc 0 verified, 1 invalid/unsafe, 2 missing basis/tool.
--check-only independently re-derives the evidence from the bound native JSON;
it reads the actual native graph and compares the derived protection results.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
import sys
import vibeic_temp as tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as ce
import _progress_run as progress
import power_domain_signal_crossing_check as intent

PROGRAM = "mixed_signal_power_domain_run"
DIR = "reports/analog/mixed_signal"
OUTPUTS = ("power_domain.json", "level_shifter.json", "isolation.json",
           "pd_connectivity.json")
RECEIPT = "power_domain_run.json"
SCHEMA = "vibeic.mixed_signal.m2.v1"


class Refusal(ValueError):
    def __init__(self, rule, message, rc=1):
        self.rule, self.rc = rule, rc
        super().__init__(message)




def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("MISSING_OR_MALFORMED_OUTPUT", str(exc)) from exc
    if not isinstance(value, dict):
        raise Refusal("MALFORMED_OUTPUT", str(path))
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.atomic_file(mode="w", dir=path.parent, delete=False) as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")
    Path(f.name).replace(path)


def groups(text, kind):
    """Balanced Liberty groups; braces in strings/comments are not syntax."""
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    pattern = re.compile(r'\b' + kind + r'\s*\(\s*"?([^\s"()]+)"?\s*\)\s*\{')
    for m in pattern.finditer(text):
        depth, quoted, escaped = 1, False, False
        for end in range(m.end(), len(text)):
            ch = text[end]
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = not quoted
            elif not quoted:
                depth += (ch == "{") - (ch == "}")
                if depth == 0:
                    yield m.group(1), text[m.end():end]
                    break
        else:
            raise Refusal("MALFORMED_LIBERTY", "unterminated " + kind)


def attr(body, name):
    m = re.search(r'\b' + name + r'\s*:\s*"?([\w]+)"?\s*;', body)
    return m.group(1) if m else None


def library_cells(paths):
    cells = {}
    for path in paths:
        for name, body in groups(path.read_text(), "cell"):
            if name in cells:
                raise Refusal("AMBIGUOUS_LIBRARY", name)
            pins = {p: b for p, b in groups(body, "pin")}
            kinds = [k for k in ("level_shifter", "isolation_cell")
                     if attr(body, "is_" + k) == "true"]
            data, controls = None, []
            if kinds:
                # Combined cells must identify the same data pin for both roles.
                role_pins = [{p for p, b in pins.items()
                              if attr(b, k + "_data_pin") == "true"} for k in kinds]
                if any(len(p) != 1 for p in role_pins) or any(p != role_pins[0] for p in role_pins):
                    raise Refusal("UNSUPPORTED_PROTECTION_PINS", name)
                data = next(iter(role_pins[0]))
                if attr(pins[data], "direction") != "input":
                    raise Refusal("UNSUPPORTED_PROTECTION_PINS", name)
                if "isolation_cell" in kinds and not any(
                        attr(b, "isolation_cell_enable_pin") == "true"
                        and attr(b, "direction") == "input" for b in pins.values()):
                    raise Refusal("ISOLATION_CONTROL_UNSTATED", name)
                controls = [p for p, b in pins.items() if any(
                    attr(b, k + "_enable_pin") == "true" for k in kinds)]
                if any(p == data or attr(pins[p], "direction") != "input" for p in controls):
                    raise Refusal("UNSUPPORTED_PROTECTION_PINS", name)
            cells[name] = {"kinds": kinds, "data": data,
                           "controls": controls,
                           "conversion": attr(body, "level_shifter_type")}
    if not cells:
        raise Refusal("NO_LIBRARY_CELLS", "no Liberty cells", 2)
    return cells


def upf_command(line):
    """Validate only the supported literal flat command/option/arity subset.

    Supply commands bind declarations, without certifying supply connectivity.
    Strategy direction/rule variants whose semantics are not implemented are
    refused rather than accepted as a declaration with ignored options.
    """
    schema = {
        "upf_version": (set(), set()),
        "set_design_top": (set(), set()),
        "create_power_domain": ({"-elements"}, {"-elements"}),
        "create_supply_net": ({"-domain", "-voltage"}, {"-domain"}),
        "create_supply_port": ({"-domain", "-direction"}, set()),
        "connect_supply_net": ({"-ports"}, {"-ports"}),
        "set_domain_supply_net": ({"-primary_power_net", "-primary_ground_net"},
                                  {"-primary_power_net", "-primary_ground_net"}),
        "add_power_state": ({"-state"}, {"-state"}),
        "set_isolation": ({"-domain", "-applies_to", "-clamp_value"}, {"-domain"}),
        "set_level_shifter": ({"-domain", "-applies_to", "-rule"}, {"-domain"}),
    }
    tokens = re.findall(r'\{[^{}]*\}|[^\s{}]+', line)
    if (len(tokens) < 2 or tokens[0] not in schema
            or re.search(r'[;$\[\]\\"]', line)
            or " ".join(tokens).split() != line.split()
            or tokens[1].startswith(("-", "{"))):
        raise Refusal("UNSUPPORTED_UPF", line)
    command, name, *rest = tokens
    allowed, required = schema[command]
    options = {}
    if len(rest) % 2:
        raise Refusal("UNSUPPORTED_UPF", line)
    for flag, value in zip(rest[::2], rest[1::2]):
        if flag not in allowed or flag in options or value.startswith("-"):
            raise Refusal("UNSUPPORTED_UPF", line)
        options[flag] = value
    if not required <= options.keys():
        raise Refusal("UNSUPPORTED_UPF", line)
    for flag, value in options.items():
        if flag in ("-elements", "-ports", "-state"):
            if not value.startswith("{") or not value[1:-1].strip():
                raise Refusal("UNSUPPORTED_UPF", line)
        elif len(value.split()) != 1 or "{" in value:
            raise Refusal("UNSUPPORTED_UPF", line)
        if flag == "-applies_to" and value != "outputs":
            raise Refusal("UNSUPPORTED_UPF", line)
        if flag == "-rule" and value != "both":
            raise Refusal("UNSUPPORTED_UPF", line)
        if flag == "-clamp_value" and value not in ("0", "1"):
            raise Refusal("UNSUPPORTED_UPF", line)
        if flag == "-direction" and value not in ("in", "out"):
            raise Refusal("UNSUPPORTED_UPF", line)
        if flag == "-voltage" and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value):
            raise Refusal("UNSUPPORTED_UPF", line)
    if command == "upf_version" and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', name):
        raise Refusal("UNSUPPORTED_UPF", line)
    if command == "add_power_state" and not re.fullmatch(
            r'\{(?:ON -voltage [0-9]+(?:\.[0-9]+)?|OFF)\}', options["-state"]):
        raise Refusal("UNSUPPORTED_POWER_STATE", line)
    return command, name, options


def power_model(path, top):
    text = path.read_text()
    names, voltages = [], {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        command, name, options = upf_command(line)
        if command == "set_design_top" and name != top:
            raise Refusal("TOP_MISMATCH", line)
        if command == "create_power_domain":
            names.append(intent._norm(name))
        if command in ("create_supply_net", "add_power_state"):
            dom = intent._norm(options["-domain"] if command == "create_supply_net" else name)
            value = re.search(r'-voltage ([0-9.]+)', line)
            if value:
                voltages.setdefault(dom, set()).add(float(value.group(1)))
    domains, iso, ls = intent.parse_upf(text)
    if not names or len(names) != len(set(names)) or set(names) != set(domains):
        raise Refusal("AMBIGUOUS_DOMAINS", "missing/duplicate/undeclared power domain")
    for name, d in domains.items():
        if not d["elements"] or d["voltage"] is None or not math.isfinite(d["voltage"]) or d["voltage"] <= 0:
            raise Refusal("INCOMPLETE_POWER_INTENT", name)
        if len(voltages.get(name, set())) != 1:
            raise Refusal("UNSUPPORTED_MULTI_VOLTAGE", name)
    return domains, iso, ls


def inputs(project, top, liberties=()):
    if not re.fullmatch(r'[A-Za-z_][\w$]*', top):
        raise Refusal("UNSUPPORTED_TOP", top)
    upfs = sorted((project / "phase2/stage2/constraints").glob("*.upf"))
    upf = project / f"phase2/stage2/constraints/{top}.upf"
    if len(upfs) != 1 or upfs[0] != upf:
        raise Refusal("MISSING_OR_AMBIGUOUS_UPF", str(upf), 2)
    libs = [Path(p) if Path(p).is_absolute() else project / p for p in liberties]
    if not libs:
        libs = sorted((project / "input/pdk/liberty").glob("*.lib"))
    pnr = project / "phase3/stage3/pnr"
    paths = {"upf": upf, "netlist": pnr / f"{top}_pnr.v",
             "def": pnr / "routed.def",
             "gds": project / "phase3/mixed_signal/top_merged.gds"}
    if not paths["def"].is_file():
        paths["def"] = pnr / f"{top}.def"
    if not libs:
        raise Refusal("MISSING_LIBERTY", "stage libraries in input/pdk/liberty/", 2)
    for p in [*paths.values(), *libs]:
        if not p.is_file() or p.stat().st_size == 0:
            raise Refusal("MISSING_INPUT", str(p), 2)
    return paths, libs




def derive(paths, libs, top, native):
    domains, iso_strategy, ls_strategy = power_model(paths["upf"], top)
    masters = library_cells(libs)
    modules = native.get("modules", {})
    if top not in modules or not modules[top].get("cells") or modules[top].get("processes"):
        raise Refusal("INVALID_NATIVE_NETLIST", "missing/empty/nonstructural top")
    nl = modules[top]
    cells = nl["cells"]
    df = paths["def"].read_text()
    if not re.search(r'\bDESIGN\s+' + re.escape(top) + r'\s*;', df):
        raise Refusal("TOP_MISMATCH", "routed DEF")
    section = re.search(r'\bCOMPONENTS\s+(\d+)\s*;(.*?)END COMPONENTS', df, re.S)
    placed = {}
    if section:
        for row in section.group(2).split(";"):
            m = re.search(r'^\s*-\s+(\S+)\s+(\S+)\s+.*?\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)', row, re.S)
            if m:
                if m.group(1) in placed:
                    raise Refusal("AMBIGUOUS_DEF", m.group(1))
                placed[m.group(1)] = m.group(2)
        if len(placed) != int(section.group(1)):
            raise Refusal("INCOMPLETE_DEF", "unparsed/unplaced component")
    if set(placed) != set(cells) or any(placed[n] != c["type"] for n, c in cells.items()):
        raise Refusal("NETLIST_DEF_MISMATCH", "placed instances/types differ")

    def domain(name):
        matches = []
        for d, v in domains.items():
            for e in v["elements"]:
                e = e.removeprefix(top + "/")
                if name == e or name.startswith(e.rstrip("/") + "/"):
                    matches.append(d)
                    break
        if len(matches) != 1:
            raise Refusal("UNRESOLVED_INSTANCE_DOMAIN", name)
        return matches[0]

    drivers, sinks, cell_domains = {}, [], {}
    def drive(bit, node):
        if isinstance(bit, int):
            if bit in drivers:
                raise Refusal("MULTIPLE_DRIVERS", str(bit))
            drivers[bit] = node

    for n, c in cells.items():
        typ = c["type"]
        if typ not in masters or not modules.get(typ, {}).get("attributes", {}).get("blackbox"):
            raise Refusal("UNRESOLVED_OR_HIERARCHICAL_CELL", typ)
        cell_domains[n] = domain(n)
        if set(c.get("port_directions", {})) != set(c["connections"]):
            raise Refusal("UNRESOLVED_PIN_DIRECTION", n)
        for control in masters[typ]["controls"]:
            if (not c["connections"].get(control)
                    or c["port_directions"].get(control) != "input"):
                raise Refusal("UNCONNECTED_PROTECTION_CONTROL", n + "/" + control)
        for p, bits in c["connections"].items():
            direction = c["port_directions"][p]
            if direction not in ("input", "output"):
                raise Refusal("UNSUPPORTED_PIN_DIRECTION", n + "/" + p)
            for i, b in enumerate(bits):
                if direction == "output":
                    drive(b, (n, p, i))
                elif p != masters[typ]["data"]:
                    sinks.append((n, p, i, b))
    for p, port in nl.get("ports", {}).items():
        cell_domains["@" + p] = domain(p)
        for i, b in enumerate(port["bits"]):
            if port["direction"] == "input":
                drive(b, ("@" + p, p, i))
            elif port["direction"] == "output":
                sinks.append(("@" + p, p, i, b))
            else:
                raise Refusal("UNSUPPORTED_PIN_DIRECTION", p)

    def source(bit, seen=()):
        if isinstance(bit, str):
            if bit in ("0", "1"):
                return None, []
            raise Refusal("UNKNOWN_SIGNAL", bit)
        if bit not in drivers or bit in seen:
            raise Refusal("UNRESOLVED_SIGNAL_PATH", str(bit))
        node = drivers[bit]
        n, p, i = node
        if n.startswith("@"):
            return node, []
        meta = masters[cells[n]["type"]]
        if not meta["kinds"]:
            return node, []
        data = cells[n]["connections"].get(meta["data"], [])
        if len(data) != len(cells[n]["connections"][p]) or i >= len(data):
            raise Refusal("UNSUPPORTED_PROTECTION_WIDTH", n)
        origin, chain = source(data[i], (*seen, bit))
        return origin, chain + [n]

    crossings, shifters, isolators = [], [], []
    for recv, pin, index, bit in sinks:
        origin, chain = source(bit)
        if origin is None:
            continue
        drv = origin[0]
        # A transparent chain may leave and re-enter the endpoint domain.
        # Check each actual adjacent edge before considering endpoint equality.
        nodes = [drv, *chain, recv]
        for sender, receiver in zip(nodes, nodes[1:]):
            a, b = cell_domains[sender], cell_domains[receiver]
            av, bv = domains[a], domains[b]
            if a == b:
                continue
            if av["voltage"] != bv["voltage"]:
                conversion = "LH" if av["voltage"] < bv["voltage"] else "HL"
                adjacent = [n for n in (sender, receiver) if n in chain]
                if not any("level_shifter" in masters[cells[n]["type"]]["kinds"]
                           and masters[cells[n]["type"]]["conversion"] in (conversion, "HL_LH")
                           for n in adjacent) or not {a, b} & ls_strategy:
                    raise Refusal("MISSING_LEVEL_SHIFTER", sender + "->" + receiver)
            # OFF capability requires isolation even at equal voltage and
            # even if this chain later returns to the original domain.
            if (av["off_capable"] or bv["off_capable"]) and (
                    not any("isolation_cell" in masters[cells[n]["type"]]["kinds"]
                            and not domains[cell_domains[n]]["off_capable"] for n in chain)
                    or not {a, b} & iso_strategy):
                raise Refusal("MISSING_ISOLATION_CELL", sender + "->" + receiver)
        a, b = cell_domains[drv], cell_domains[recv]
        if a == b:
            continue
        key = f"{drv}/{origin[1]}[{origin[2]}]->{recv}/{pin}[{index}]"
        av, bv = domains[a], domains[b]
        c = {"net": key, "driver_domain": a, "receiver_domain": b,
             "vdd_from": av["voltage"], "vdd_to": bv["voltage"],
             "from_power_down": av["off_capable"], "to_power_down": bv["off_capable"],
             "path_cells": chain}
        crossings.append(c)
        ls_needed = av["voltage"] != bv["voltage"]
        iso_needed = av["off_capable"] or bv["off_capable"]
        conversion = "LH" if av["voltage"] < bv["voltage"] else "HL"
        for n in chain:
            typ = cells[n]["type"]
            meta = masters[typ]
            entry = {"net": key, "instance": n, "cell": typ, "placed": True}
            if "level_shifter" in meta["kinds"] and meta["conversion"] in (conversion, "HL_LH"):
                shifters.append(entry)
            if "isolation_cell" in meta["kinds"] and not domains[cell_domains[n]]["off_capable"]:
                isolators.append(entry)
        if ls_needed and (not any(e["net"] == key for e in shifters) or not {a, b} & ls_strategy):
            raise Refusal("MISSING_LEVEL_SHIFTER", key)
        if iso_needed and (not any(e["net"] == key for e in isolators) or not {a, b} & iso_strategy):
            raise Refusal("MISSING_ISOLATION_CELL", key)
    # A complete enumerated flat graph may have zero inter-domain edges. The
    # denominator is actual placed cells/pins, never absent connectivity.
    return {
        "power_domain.json": {"schema": SCHEMA, "all_crossings_protected": True,
                              "examined_cells": len(cells), "crossings": crossings},
        "level_shifter.json": {"schema": SCHEMA, "all_required_inserted": True, "level_shifters": shifters},
        "isolation.json": {"schema": SCHEMA, "all_required_inserted": True, "isolation_cells": isolators},
        "pd_connectivity.json": {"schema": SCHEMA, "crossings": crossings},
    }


def run_tool(script, work, container):
    command = "yosys -T -s " + shlex.quote(str(script))
    try:
        if container in (None, "", "host"):
            done = progress.run(["yosys", "-T", "-s", str(script)], capture_output=True, text=True)
        else:
            done = ce.run_in_container_supervised(container, command, ceiling_s=120)
    except progress.Stalled as exc:
        (work / "yosys.log").write_text(exc.stdout + exc.stderr + "\n" + str(exc))
        return progress.RC_STALLED
    (work / "yosys.log").write_text(done.stdout + done.stderr)
    return done.returncode


def verify(project):
    root = project / DIR
    report = read_json(root / RECEIPT)
    if report.get("verdict") != "PASS" or report.get("tool", {}).get("exit_code") != 0:
        raise Refusal("NATIVE_TOOL_NOT_MEASURED", "no successful native M2 result")
    paths, libs = inputs(project, report["top"], report["liberties"])
    native = read_json(root / "power_domain_tool/netlist.json")
    expected = derive(paths, libs, report["top"], native)
    for name, result in expected.items():
        if read_json(root / name) != result:
            raise Refusal("CONTRADICTS_NATIVE_OUTPUT", name)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--top")
    ap.add_argument("--liberty", action="append", default=[])
    ap.add_argument("--container", default="host")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    project = args.project.resolve()
    root = project / DIR
    report = {"program": PROGRAM, "schema": SCHEMA, "verdict": "FAIL", "findings": []}
    rc = 1
    try:
        if args.check_only:
            observed = verify(project)
            report.update(verdict="PASS", top=observed["top"])
        else:
            # Withdraw the prior admission before examining or invoking anything.
            for name in (*OUTPUTS, RECEIPT):
                (root / name).unlink(missing_ok=True)
            top = args.top
            if not top:
                upfs = sorted((project / "phase2/stage2/constraints").glob("*.upf"))
                if len(upfs) != 1:
                    raise Refusal("MISSING_OR_AMBIGUOUS_UPF", "need one top UPF", 2)
                top = upfs[0].stem
            paths, libs = inputs(project, top, args.liberty)
            power_model(paths["upf"], top)
            library_cells(libs)
            work = root / "power_domain_tool"
            work.mkdir(parents=True, exist_ok=True)
            native_path = work / "netlist.json"
            native_path.unlink(missing_ok=True)
            script = work / "read.ys"
            quote = lambda p: json.dumps(str(p))
            script.write_text("\n".join(
                [f"read_liberty -lib {quote(p)}" for p in libs] +
                [f"read_verilog {quote(paths['netlist'])}", f"hierarchy -check -top {top}",
                 f"write_json {quote(native_path)}"]) + "\n")
            code = run_tool(script, work, args.container)
            if code == progress.RC_STALLED:
                raise Refusal("NATIVE_TOOL_STALLED", f"Yosys supervision stalled; see {work / 'yosys.log'}", 2)
            if code:
                raise Refusal("NATIVE_TOOL_FAILED", f"Yosys rc={code}")
            native = read_json(native_path)
            evidence = derive(paths, libs, top, native)
            for name, obj in evidence.items():
                write_json(root / name, obj)
            report.update(verdict="PASS", top=top,
                          liberties=[str(p.resolve()) for p in libs],
                          tool={"name": "yosys", "exit_code": code,
                                "container": args.container},
                          scope="placed structural protection paths; no electrical/dynamic signoff")
            write_json(root / RECEIPT, report)
        rc = 0
    except Refusal as exc:
        rc = exc.rc
        report.update(verdict="NOT_READY" if rc == 2 else "FAIL",
                      findings=[{"rule": exc.rule, "message": str(exc)}])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        report.update(findings=[{"rule": "INVALID_EVIDENCE", "message": str(exc)}])
    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = project / out
        if out.resolve() == (root / RECEIPT).resolve():
            raise ValueError("--json audit path must differ from producer report")
        write_json(out, report)
    print(f"[{PROGRAM}] {report['verdict']}: {report['findings']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
