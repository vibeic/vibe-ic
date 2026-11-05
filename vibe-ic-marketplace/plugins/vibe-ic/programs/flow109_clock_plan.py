"""Native OpenROAD clock-plan measurement and structural sink census."""
from __future__ import annotations

import json
from pathlib import Path

from _atomic_artefact import write_json

OUTPUT = "phase3/stage3/cts/clock_plan.json"
SINK_SOURCE = "reports/phase3/clock_sink_inventory.json"



def execute(project, context):
    import _physical_current as current
    import _path_layout as layout
    import clock_plan_check
    project = Path(project).resolve()
    result = {"component_status": "NOT_MEASURED", "native_started": False}
    try:
        sdcs = context.get("sdcs") or layout.clock_plan_input_sdcs(project)
        if not sdcs:
            raise ValueError("D34_SDC_ABSENT")
        floorplan = project / "phase3/stage3/pnr/floorplan.def"
        result["native_started"] = True
        current.clock_plan(project, project / OUTPUT, floorplan, sdcs, context["pdk"],
                           io_context=context.get("io_context"))
        report = project / "reports/phase2/gates/clock_plan.json"
        rc = clock_plan_check.main([str(project), "--json", str(report)])
        result.update(component_status="PASS" if rc == 0 else "FAIL",
                      native_exit_code=rc, plan=OUTPUT, report=str(report))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(reason=str(exc).split(":", 1)[0], detail=str(exc))
    return result



def liberty_clock_pins(text: str) -> dict[str, str]:
    """``cell -> clock pin`` for every Liberty ``ff``/``latch`` group.

    The library's own declaration decides what is sequential, never a cell
    name. A multi-bit bank or a clock expression that is not a single pin is
    refused rather than guessed at.
    """
    import re
    starts = [(m.start(), m.group(1)) for m in re.finditer(
        r'\bcell\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', text)]
    pins = {}
    for index, (start, name) in enumerate(starts):
        block = text[start:starts[index + 1][0] if index + 1 < len(starts) else len(text)]
        if re.search(r"\b(ff_bank|latch_bank)\s*\(", block):
            raise ValueError("D34_LIBERTY_BANK_UNSUPPORTED: " + name)
        group = re.search(r"\b(ff|latch)\s*\([^)]*\)\s*\{([^{}]*)\}", block, re.S)
        if not group:
            continue
        key = "clocked_on" if group.group(1) == "ff" else "enable"
        value = re.search(key + r'\s*:\s*"([^"]*)"', group.group(2))
        pin = re.sub(r"[!()'\s]", "", value.group(1)) if value else ""
        if not re.fullmatch(r"[A-Za-z_][\w$]*", pin):
            raise ValueError(f"D34_LIBERTY_CLOCK_EXPRESSION_UNSUPPORTED: {name}: {value and value.group(1)}")
        pins[name] = pin
    return pins


def _liberty_group(text: str, brace: int) -> tuple[str, int]:
    """The body of the group whose ``{`` is at ``brace``, with nested groups blanked."""
    depth, top = 0, []
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return "".join(top), index
        elif depth == 1:
            top.append(char)
    raise ValueError("D34_LIBERTY_GROUP_UNTERMINATED")


def liberty_pin_roles(text: str) -> dict[str, dict[str, dict]]:
    """``cell -> pin -> {direction, clock, is_pad}`` from each pin's own attributes.

    Only a pin group's top-level attributes count; timing and power subgroups
    are blanked so their keywords cannot be read as the pin's.
    """
    import re
    roles = {}
    for cell in re.finditer(r'\bcell\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', text):
        _, end = _liberty_group(text, cell.end() - 1)
        block, pins = text[cell.end() - 1:end + 1], {}
        for pin in re.finditer(r'\bpin\s*\(\s*"?([A-Za-z_][\w$]*)"?\s*\)\s*\{', block):
            body, pin_end = _liberty_group(block, pin.end() - 1)
            pin_block, arcs = block[pin.end():pin_end], []
            for timing in re.finditer(r'\btiming\s*\([^)]*\)\s*\{', pin_block):
                arc, _ = _liberty_group(pin_block, timing.end() - 1)
                fields = [re.search(r'\b' + key + r'\s*:\s*"?([\w$]+)', arc)
                          for key in ("related_pin", "timing_sense")]
                arcs.append(tuple(f.group(1) if f else None for f in fields))
            direction = re.search(r'\bdirection\s*:\s*"?(\w+)', body)
            pins[pin.group(1)] = {
                "direction": direction.group(1) if direction else None,
                "clock": bool(re.search(r'\bclock\s*:\s*"?true', body)),
                "is_pad": bool(re.search(r'\bis_pad\s*:\s*"?true', body)),
                "timing_arcs": arcs,
                **{key: bool(re.search(r"\b" + key + r'\s*:\s*"?true', body))
                   for key in ("clock_gate_clock_pin", "clock_gate_out_pin")}}
        roles[cell.group(1)] = pins
    return roles


def structural_clock_domains(def_text: str, clock_pins: dict[str, str],
                             pin_roles: dict[str, dict[str, dict]],
                             clock_sources: dict[str, str]) -> dict:
    """Assign every sequential clock pin to the clock whose source it traces back to.

    The trace follows the floorplan's own NETS backwards from each register
    clock pin through single-input cells, an input marked ``clock`` (clock
    gates) or ``is_pad`` (IO pads), until it reaches a declared clock source:
    a top-level port or a pin a clock is defined on. It shares no code with the
    timing graph. A register whose clock pin has no driver, or whose source is
    no declared clock, is ``unclocked`` and is a required sink the census must
    report. Any path the rules cannot decide raises: an unknown association is
    never guessed, so no reference exists and the row stays unmeasured.
    """
    import re

    def section(name):
        found = re.search(r"\n" + name + r"\s+\d+\s*;(.*?)\nEND " + name, def_text, re.S)
        if not found:
            raise ValueError("D34_DEF_" + name + "_ABSENT")
        return found.group(1)

    clean = lambda token: token.replace("\\", "")
    masters = {clean(i): m for i, m in re.findall(r"-\s+(\S+)\s+(\S+)", section("COMPONENTS"))}
    inputs = set()
    for entry in section("PINS").split(";"):
        name, direction = re.search(r"-\s+(\S+)", entry), re.search(r"\+\s+DIRECTION\s+(\w+)", entry)
        if name and direction and direction.group(1) == "INPUT":
            inputs.add(clean(name.group(1)))
    net_of, members = {}, {}
    for net, body in re.findall(r"-\s+(\S+)((?:\s*\(\s*\S+\s+\S+\s*\))+)", section("NETS")):
        for owner, pin in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", body):
            node = (clean(owner), clean(pin))
            net_of[node] = clean(net)
            members.setdefault(clean(net), []).append(node)

    def drivers(net):
        return [(owner, pin) for owner, pin in members.get(net, [])
                if (owner == "PIN" and pin in inputs) or (owner != "PIN" and
                    pin_roles.get(masters.get(owner), {}).get(pin, {}).get("direction") == "output")]

    domains, unclocked = {name: [] for name in set(clock_sources.values())}, []
    for instance, master in sorted(masters.items()):
        if master not in clock_pins:
            continue
        sink = instance + "/" + clock_pins[master]
        node, seen, clock = (instance, clock_pins[master]), set(), None
        while True:
            net = net_of.get(node)
            found = drivers(net) if net else []
            if not found:
                break
            if len(found) > 1:
                raise ValueError("D34_CLOCK_TRACE_UNRESOLVED: multiple drivers for " + sink)
            owner, pin = found[0]
            name = pin if owner == "PIN" else owner + "/" + pin
            if name in clock_sources:
                clock = clock_sources[name]
                break
            if owner == "PIN" or (owner, pin) in seen:
                break
            seen.add((owner, pin))
            ins = {p: r for p, r in pin_roles.get(masters.get(owner), {}).items()
                   if r.get("direction") == "input"}
            follow = ([p for p, r in ins.items() if r["clock"]] or
                      [p for p, r in ins.items() if r["is_pad"]] or
                      (list(ins) if len(ins) == 1 else []))
            if len(follow) != 1:
                raise ValueError(f"D34_CLOCK_TRACE_UNRESOLVED: {sink} through {owner} ({masters.get(owner)})")
            node = (owner, follow[0])
        (domains[clock] if clock else unclocked).append(sink)
    return {"clocks": {name: sorted(pins) for name, pins in domains.items()},
            "unclocked": sorted(unclocked)}


def propose_sink_reference(project: Path, liberties: list[Path]) -> dict:
    """Read the DEF and libraries to report their structural clock sinks."""
    project = Path(project).resolve()
    floorplan = project / "phase3/stage3/pnr/floorplan.def"
    plan = json.loads((project / OUTPUT).read_text())
    sources = {source: clock["name"] for clock in plan.get("clocks", [])
               for source in str(clock.get("source", "")).split()}
    if not sources:
        raise ValueError("D34_CLOCK_SOURCES_ABSENT: " + OUTPUT)
    pins, roles = {}, {}
    for path in liberties:
        text = Path(path).read_text(errors="ignore")
        pins.update(liberty_clock_pins(text))
        roles.update(liberty_pin_roles(text))
    if not pins:
        raise ValueError("D34_LIBERTY_SEQUENTIAL_CELLS_ABSENT")
    reference = structural_clock_domains(floorplan.read_text(), pins, roles, sources)
    write_json(project / SINK_SOURCE, reference)
    return {"path": SINK_SOURCE,
            "sinks": {name: len(found) for name, found in reference["clocks"].items()},
            "unclocked": len(reference["unclocked"])}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Structural clock sink census")
    parser.add_argument("command", choices=["propose-sink-reference"])
    parser.add_argument("project")
    parser.add_argument("--liberty", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(propose_sink_reference(Path(args.project), [Path(p) for p in args.liberty])))
