"""Read OpenSTA's existing reports for the native flow selector."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import librelane_prelayout as native


_SDC_READ = re.compile(r"^Reading design constraints file at '([^']+)'", re.M)


def pad_direction_facts(directory: Path, config: dict, state: dict, declarations: dict):
    """Read constant pad controls with OpenSTA; Liberty names their roles.

    STAPrePNR's verbose lists do not report the pad control values. This
    Boolean-only query loads its input netlist and libraries without SDC or
    changing a constraint, then records the native constant observations.
    """
    from flow_activity import _paths, _word
    from flow_native_adapters import Commands
    from _pad_ring import parse_liberty_pad_cells, _product_literals
    import gzip

    corner = config.get("DEFAULT_CORNER", "")
    netlists = _paths(state.get("nl"), directory, corner)
    libraries = list(dict.fromkeys(path for key in ("LIB", "PAD_LIBS", "EXTRA_LIBS")
                                  for path in _paths(config.get(key), directory, corner)))
    if (not config.get("DESIGN_NAME") or len(netlists) != 1 or not netlists[0].is_file()
            or not libraries or any(not path.is_file() for path in libraries)):
        return {}, {}
    plans, ambiguous = {}, set()
    for path in libraries:
        try:
            text = gzip.open(path, "rt").read() if path.suffix == ".gz" else path.read_text()
        except (OSError, UnicodeError):
            continue
        for master, pins in parse_liberty_pad_cells(text).items():
            terminals = [p for p, value in pins.items() if str(value.get("is_pad") or "").lower() == "true"]
            if len(terminals) != 1:
                continue
            terminal = terminals[0]
            if pins[terminal].get("direction") != "inout":
                continue
            tri = _product_literals(pins[terminal].get("three_state"))
            receivers = [lits for value in pins.values() if value.get("direction") == "output"
                         and (lits := _product_literals(value.get("function")))
                         and any(pin == terminal for _, pin in lits)]
            controls = sorted({pin for _, pin in (tri or [])}
                              | {pin for lits in receivers for _, pin in lits if pin != terminal})
            plan = {"terminal": terminal, "tri": tri, "receivers": receivers,
                    "controls": controls, "liberty": str(path)}
            if master in plans and any(plans[master][key] != plan[key] for key in ("terminal", "tri", "receivers")):
                plans.pop(master)
                ambiguous.add(master)
            if master not in ambiguous:
                plans.setdefault(master, plan)
    plans = {master: plan for master, plan in plans.items() if plan["controls"]}
    if not plans:
        return {}, {}
    work = directory / "pad_direction"
    work.mkdir(exist_ok=True)
    script = work / "controls.tcl"
    lines = [*("read_liberty " + _word(path) for path in libraries),
             "read_verilog " + _word(netlists[0]), "link_design " + _word(config["DESIGN_NAME"]),
             "set models [dict create]"]
    for master, plan in plans.items():
        lines.append("dict set models " + _word(master) + " [list " + _word(plan["terminal"])
                     + " [list " + " ".join(map(_word, plan["controls"])) + "]]")
    lines.append(r'''
set ports_by_net [dict create]
foreach port [get_ports *] {
  set net [[[sta::get_port_pin $port] term] net]
  if {$net ne "NULL"} {dict lappend ports_by_net [get_full_name $net] [get_full_name $port]}
}
foreach cell [get_cells -hierarchical *] {
  set master [get_property $cell ref_name]
  if {![dict exists $models $master]} {continue}
  lassign [dict get $models $master] terminal controls
  set instance [get_full_name $cell]
  set bond [sta::find_pin "$instance/$terminal"]
  if {$bond eq "NULL"} {continue}
  foreach net [get_nets -of_objects $bond] {
    set name [get_full_name $net]
    if {![dict exists $ports_by_net $name]} {continue}
    foreach port [dict get $ports_by_net $name] {
      foreach control $controls {
        set pin [sta::find_pin "$instance/$control"]
        if {$pin ne "NULL"} {
          puts [join [list PAD_CONTROL $port $instance $master $control [sta::pin_sim_logic_value $pin]] "\t"]
        }
      }
    }
  }
}
exit
''')
    script.write_text("\n".join(lines) + "\n")
    commands = Commands(work)
    run = commands.run(["sta", "-no_init", "-no_splash", "-exit", str(script)])
    measurement = commands.result(reports=[script], detail="Native pad-direction control query.")
    groups = {}
    if run is not None and run.returncode == 0:
        for line in run.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 6 and fields[0] == "PAD_CONTROL":
                _, port, instance, master, control, value = fields
                groups.setdefault(port, {}).setdefault((instance, master), {})[control] = value
    facts = {}
    for port, pads in groups.items():
        base = re.fullmatch(r"([A-Za-z_]\w*)(?:\[-?\d+\])*", port)
        declared = declarations.get(base[1]) if base else None
        if declared is None:
            continue
        sources, disabled = [], []
        for (instance, master), values in pads.items():
            plan = plans[master]
            def literal(neg, pin):
                value = values.get(pin)
                return None if value not in {"0", "1"} else (value == "1") != neg
            if declared["direction"] == "input":
                inactive = bool(plan["tri"]) and all(literal(neg, pin) is True for neg, pin in plan["tri"])
            else:
                inactive = bool(plan["receivers"]) and all(
                    any(pin != plan["terminal"] and literal(neg, pin) is False for neg, pin in lits)
                    for lits in plan["receivers"])
            disabled.append(inactive)
            sources.append({"file": str(netlists[0]), "instance": instance, "master": master,
                            "controls": values, "liberty": plan["liberty"],
                            "three_state": plan["tri"], "receiver_functions": plan["receivers"],
                            "report": commands.records[0]["log"]})
        if disabled and all(disabled):
            facts[port] = {"direction": declared["direction"],
                           "sources": [*declared["sources"], *sources]}
    return facts, measurement


def _sdc_findings(log: str, configured: set[str]):
    sources = set(_SDC_READ.findall(log))
    if not sources or not sources <= configured:
        return None
    selected = {Path(source) for source in sources}
    names = {source.name for source in selected}
    lines = []
    for match in native._FILE_DIAG_RE.finditer(log):
        path = Path(match.group(3))
        if path in selected or (path.parent == Path(".") and path.name in names):
            lines.append(match.group(0))
    filtered = "\n".join(lines)
    return [item for name in sorted(names)
            for item in native.sdc_diagnostics(filtered, Path(name), calibrate=False)]


def read_sta_reports(directory: Path, config: dict, *, project: Path | None = None) -> dict:
    """Sum native corner diagnostics, omitting metrics whose reports are missing."""
    directory = Path(directory)
    reports, details = [], []
    ports, declarations, observations = {}, {}, []
    mode_facts, mode_measurement = None, {}
    if project is not None:
        path = Path(project) / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        if path.is_file():
            from _specrtl_common import _norm_dir
            reports.append(str(path))
            body = json.loads(path.read_text())
            hierarchy = body["fields"] if isinstance(body.get("fields"), dict) else {}
            locations = [("top_ports", body.get("top_ports")), ("fields.top_ports", hierarchy.get("top_ports")),
                         ("ports", body.get("ports")), ("fields.ports", hierarchy.get("ports"))]
            location, rows = next(((key, value) for key, value in locations if value), ("top_ports", []))
            ports = {p["name"]: p for p in rows
                     if p.get("timing_class") in {"asynchronous", "unused"}
                     and p.get("timing_class_sources")}
            for index, port in enumerate(rows):
                values = {key: value for key in ("direction", "mode", "dir")
                          if isinstance(port.get(key), str) and (value := _norm_dir(port[key]))}
                if len(set(values.values())) == 1 and next(iter(values.values())) in {"input", "output"}:
                    declarations[port["name"]] = {"direction": next(iter(values.values())), "sources": [
                        {"file": str(path), "field": f"{location}[{index}].{key}", "value": port[key]}
                        for key in values]}
            from _specrtl_common import Port
            from spec_conformance_check import _selected_interface_ports
            sources = {name: record["sources"] for name, record in declarations.items()}
            selected = _selected_interface_ports(Path(project),
                [Port(port["name"], declarations[port["name"]]["direction"], port.get("width"))
                 for port in rows if port["name"] in declarations],
                body.get("top_module") or hierarchy.get("top_module"), port_sources=sources)
            declarations = {port.name: {"direction": port.direction, "sources": sources[port.name]}
                            for port in selected}
    resolved = dict(config)
    state = {}
    output = {}
    metadata_complete = True
    for filename in ("config.json", "state_in.json", "state_out.json"):
        path = directory / filename
        if not path.is_file():
            continue
        reports.append(str(path))
        try:
            body = json.loads(path.read_text())
            if not isinstance(body, dict):
                raise ValueError("native metadata is not an object")
            if filename == "config.json":
                resolved.update(body)
            elif filename == "state_in.json":
                state = body
            else:
                output = body
        except (OSError, ValueError, TypeError) as exc:
            metadata_complete = False
            details.append(f"Native {filename} could not be read: {exc}")
    configured = {str(value) for value in (
        resolved.get("PNR_SDC_FILE"), resolved.get("SIGNOFF_SDC_FILE"),
        resolved.get("FALLBACK_SDC"), state.get("sdc")) if value}
    reported_corners = {key.split("__corner:", 1)[1] for key in output.get("metrics", {})
                        if key.startswith("timing__setup__ws__corner:")}
    population_known = metadata_complete and (bool(reported_corners) or not resolved.get("STA_CORNERS"))
    if not population_known:
        details.append("Native output has not reported its deduplicated timing-corner population.")
    corners = sorted({path.parent for pattern in ("*/checks.rpt", "*/sta.log")
                      for path in directory.glob(pattern)} | {directory / name for name in reported_corners})
    counts, diagnostics = [], []
    for corner in corners:
        texts = {}
        for filename in ("checks.rpt", "sta.log"):
            path = corner / filename
            if path.is_file():
                reports.append(str(path))
                texts[filename] = path.read_text(errors="replace")
        found = None
        for filename in ("checks.rpt", "sta.log"):
            if filename in texts:
                found = native.check_setup_counts(texts[filename], native.supply_names(resolved),
                                                  calibrate=False)
                if found is not None:
                    for kind, count, listed in native.check_setup_sections(texts[filename]):
                        if kind not in {"no_input_delay", "no_output_delay", "unconstrained_endpoints"}:
                            continue
                        removed = []
                        for name in listed:
                            base = re.fullmatch(r"([A-Za-z_]\w*)(?:\[-?\d+\])*", name)
                            port = ports.get(base[1]) if base else None
                            if port is not None and name not in native.supply_names(resolved):
                                removed.append(name)
                                observations.append({"kind": "documented_port_timing", "port": name,
                                    "timing_class": port["timing_class"], "sources": port["timing_class_sources"],
                                    "corner": corner.name, "finding": kind, "status": "NOT_APPLICABLE"})
                            elif base and base[1] in declarations:
                                direction = declarations[base[1]]["direction"]
                                reverse = ((kind == "no_input_delay" and direction == "output")
                                           or (kind in {"no_output_delay", "unconstrained_endpoints"}
                                               and direction == "input"))
                                if reverse:
                                    if mode_facts is None:
                                        mode_facts, mode_measurement = pad_direction_facts(
                                            directory, resolved, state, declarations)
                                    if name in mode_facts:
                                        removed.append(name)
                                        observations.append({"kind": "inactive_pad_direction", "port": name,
                                            **mode_facts[name], "corner": corner.name, "finding": kind,
                                            "status": "NOT_APPLICABLE"})
                        found[kind] -= min(count, len(removed))
                    break
        if found is None:
            details.append(f"{corner.name}: native check_setup section is missing.")
        else:
            counts.append(found)
        findings = (_sdc_findings(texts["sta.log"], configured)
                    if "sta.log" in texts and metadata_complete else None)
        if findings is None or found is None:
            details.append(f"{corner.name}: complete diagnostics for the native SDC source are missing.")
        else:
            diagnostics.append(findings)
    metrics = {}
    if population_known and corners and len(counts) == len(corners):
        metrics["unconstrained_endpoints"] = sum(c.get("unconstrained_endpoints", 0) for c in counts)
        metrics["unconstrained_required_paths"] = sum(sum(c.values()) for c in counts)
    if population_known and corners and len(diagnostics) == len(corners):
        metrics["invalid_timing_exceptions"] = sum(map(len, diagnostics))
    if not corners:
        details.append("No native STA corner reports exist.")
    details.insert(0, f"Read {len(corners)} native STA corners; check_setup {len(counts)}/{len(corners)}, "
                      f"SDC diagnostics {len(diagnostics)}/{len(corners)}.")
    return {"metrics": metrics, "reports": reports + mode_measurement.get("reports", []),
            "detail": " ".join(details), "observations": observations,
            "tool_seconds": mode_measurement.get("tool_seconds", 0),
            "native_steps": [{"name": "sta", "ran": mode_measurement.get("ran", False),
                              "exit_code": mode_measurement.get("exit_code"),
                              "status": ("PASS" if mode_measurement.get("exit_code") == 0 else
                                         "FAIL" if mode_measurement.get("ran") else "NOT_MEASURED")}]
                             if mode_measurement else []}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--project", type=Path)
    args = parser.parse_args()
    result = read_sta_reports(args.directory, json.loads(args.config.read_text()) if args.config else {},
                              project=args.project)
    print(json.dumps(result, indent=2))
