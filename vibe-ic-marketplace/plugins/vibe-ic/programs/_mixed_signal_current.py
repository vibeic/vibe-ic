"""Current physical two-port interfaces resolved from retained tool views.

Explicit multi-interface populations use the existing sequential scenario loop.
Shared/cross-coupled interfaces require a coupled method and remain unmeasured.
This does not extend the declared component contract or qualify a whole design.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

import os as _os
import sys as _sys
if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

SCOPE = "current_post_layout_interface"


def native():
    import _mixed_signal_native as n
    return n


def refuse(message):
    raise native().api().Refusal("CURRENT_INTERFACE_NOT_SUPPORTED", message)


def for_scenario(data, row):
    """Select only a caller-declared interface; never infer a row's wiring."""
    interfaces = data.get("_current_interfaces")
    if interfaces is None:
        return data
    name = row.get("interface")
    if not isinstance(name, str) or name not in interfaces:
        refuse("each scenario must name one complete current interface")
    return interfaces[name]


def resolve(project, original):
    """Resolve the full explicit physical population before any execution."""
    canonical = original.get("canonical") or {}
    if "interfaces" not in canonical:
        return _resolve_interface(project, original)
    entries = canonical["interfaces"]
    if (set(canonical) != {"interfaces"} or not isinstance(entries, list) or not entries
            or any(not isinstance(item, dict) for item in entries)):
        refuse("nonempty explicit canonical interfaces are required")
    names = [item.get("id") for item in entries]
    instances = [item.get("instance") for item in entries]
    if (any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) for name in names)
            or len(set(names)) != len(names) or len(set(instances)) != len(instances)):
        refuse("interface IDs and physical instances must be unique")
    population = []
    for item in entries:
        roles = item.get("digital")
        if (not isinstance(roles, dict) or not {"drive", "sense", "response"} <= set(roles)
                or set(roles) - {"clock", "reset_n", "drive", "sense", "response"}):
            refuse("each physical interface needs explicit digital port roles")
        view = copy.deepcopy(original)
        view["canonical"] = {key: value for key, value in item.items() if key not in ("id", "digital", "analog")}
        view["digital"] = {**original["digital"], **roles}
        view["analog"] = {**original["analog"], **item.get("analog", {})}
        population.append(view)
    signals = [view["digital"][key] for view in population for key in ("drive", "sense")]
    if len(set(signals)) != len(signals):
        refuse("shared physical drive/sense nets require a coupled multi-driver method")
    rows = native().api().plan(project)
    if (not rows or any(row.get("interface") not in names for row in rows)
            or {row.get("interface") for row in rows} != set(names)):
        refuse("the complete declared interface population must have explicit scenarios")
    resolved = {}
    for name, view in zip(names, population):
        result = _resolve_interface(project, view, population)
        result["_current"].update(interface_id=name, instance=view["canonical"]["instance"])
        resolved[name] = result
    data = copy.deepcopy(original)
    data["si"] = resolved[names[0]]["si"]
    if any(view["si"] != data["si"] for view in resolved.values()):
        refuse("all interfaces must consume the same complete retained timing population")
    data["_current"] = {"inputs": sorted({path for view in resolved.values() for path in view["_current"]["inputs"]})}
    data["_current_interfaces"] = resolved
    return data


def _resolve_interface(project, original, population=None):
    """Resolve roles to existing A7/A8/M1/M2/STA material, never caller models."""
    import analog_a7_post_layout_emit as a7
    import analog_a7_post_layout_resim_check as a7_gate
    import mixed_signal_top_lvs_run as m1
    import mixed_signal_power_domain_run as m2
    import librelane_contract as lc
    import librelane_postroute as postroute
    from _container_exec import localise_mounted_paths
    import path_spice_tool as spice
    from _analog_a_check_common import load_block_list, block_list_path
    from l_doc_consumer_contract import load_l_doc, l_doc_fields
    from l9_rtl_pin_consistency_check import extract_l9_ports_with_audit
    from si_signoff_timing_aware import parse_spef

    n = native()
    data = copy.deepcopy(original)
    c = data["canonical"]
    block, instance = c["block"], c["instance"]
    population = population or [data]
    declared = load_block_list(project)
    expected_blocks = {view["canonical"]["block"] for view in population}
    if not declared or len(set(declared)) != len(declared) or set(declared) != expected_blocks:
        refuse("the complete master block population must be mapped")
    block_list = block_list_path(project)
    declarations = json.loads(block_list.read_text())
    declarations = declarations.get("blocks", []) if isinstance(declarations, dict) else declarations
    for declaration in declarations:
        if not isinstance(declaration, dict):
            continue
        counts = [declaration[key] for key in ("count", "multiplicity") if key in declaration]
        name = declaration.get("name") or declaration.get("block")
        if counts and (any(type(count) is not int or count <= 0 for count in counts)
                       or len(set(counts)) != 1
                       or sum(view["canonical"]["block"] == name for view in population) != counts[0]):
            refuse("declared block multiplicity must match every explicit physical interface")
    bdir = project / "phase3/analog" / block
    record_path = bdir / "a7_post_layout.json"
    record = n.api().read(record_path)
    comparison = n.api().read(bdir / "pre_vs_post.json")
    if a7_gate._layout_provenance_findings(project, block, comparison):
        refuse("current A7 layout provenance is not accepted")
    if record.get("layout_netlist_identity", {}).get("state") != "MATCH":
        refuse("A7 does not consume the current layout/netlist pair")
    corners = record.get("corners", [])
    selected = [r for r in corners if r.get("extraction_style") == c["extraction_style"]]
    if len(corners) != 1 or len(selected) != 1:
        refuse("the entire retained extraction-style population must be supported")
    row = selected[0]
    if not row.get("audit_passed") or row.get("device_inventory", {}).get("result") != "MATCH":
        refuse("A7 extracted material is not accepted")
    step = n.local(project, row["step_dir"])
    extraction_receipt = lc.validate_step_receipt(step, "Magic.RCX")
    extracted = n.local(project, row["extracted_netlist"])
    post = n.local(project, row["post_layout_netlist"])
    if extraction_receipt["sha256"].get(str(extracted.relative_to(step))) != n.api().digest(extracted):
        refuse("A7 selected extracted model is not a retained native output")
    topology = n.api().read(bdir / "topology.json")
    ports = topology.get("ports", [])
    rails = topology.get("rails", {})
    signal_ports = [p for p in ports if p not in rails.values()]
    if signal_ports != [c["macro_drive"], c["macro_sense"]]:
        refuse("all macro signal ports must belong to the supported interface")
    rebuilt, _ = a7.post_layout_netlist(block, ports, extracted.read_text(),
        a7.model_binding_lines((bdir / (block + ".sp")).read_text(), bdir, post.parent))
    if post.read_text() != rebuilt:
        refuse("A7 post-layout view differs from the current extracted circuit")
    top_lvs = n.api().read(project / "reports/analog/mixed_signal/top_lvs.json")
    if top_lvs.get("verdict") != "PASS" or m1.validate_current_receipt(project, top_lvs) is not None:
        refuse("current M1 merge/LVS is not accepted")
    _, macros, views, netlist, detail, _ = m1.current_merge_inputs(project, data["top"])
    expected_instances = {(view["canonical"]["block"], view["canonical"]["instance"]) for view in population}
    actual_instances = [(cell, item["inst"]) for cell, items in detail["placements"].items() for item in items]
    if ({p.stem for p in macros} != expected_blocks or len(actual_instances) != len(expected_instances)
            or set(actual_instances) != expected_instances):
        refuse("all physical macro instances must match the complete explicit mapping")
    macro_gds = next(path for path in macros if path.stem == block)
    macro_view = next(path for path in views if re.search(r"\bmodule\s+" + re.escape(block) + r"\b", m1._uncomment(path.read_text())))
    manifest_path = macro_gds.parent / "a8_views_provenance.json"
    manifest = n.api().read(manifest_path)
    if m1._a8_manifest_failure(project, macro_gds, macro_view):
        refuse("current A8 views are not accepted")
    if (manifest["source_gds"] != record["layout_path"] or
            manifest["source_gds_sha256"] != record["layout_sha256"]):
        refuse("M1/A8 does not consume the A7 layout")
    m2.verify(project)
    folder, _ = postroute.stapostpnr_state(project)
    analysed = [d.name for d in folder.iterdir() if (d / "sta.log").is_file()]
    if analysed != [c["sta_corner"]]:
        refuse("the full retained STA corner population must be supported")
    timing = lc.post_pnr_timing_inputs(project, folder / "state_out.json", c["sta_corner"])
    config = n.api().read(folder / "config.json")
    if config.get("PDK") != record.get("pdk"):
        refuse("A7 and current routed timing use different PDKs")
    if n.api().digest(netlist) != n.api().digest(n.local(project, timing["sta_netlist"])):
        refuse("M1 and current timing consume different netlists")
    if data["digital"]["netlist"] != str(netlist.relative_to(project)):
        refuse("the digital wrapper is not M1's current netlist")
    retained_inputs = set()

    def model_paths(values, fingerprint_key="config_files"):
        paths = []
        for value in values:
            path = Path(value) if Path(value).is_absolute() else n.local(project, value)
            if not path.resolve().is_relative_to(project.resolve()):
                # The step's guest namespace names the retained host material;
                # a conventional /pdk name alone does not identify that root.
                try:
                    receipt = lc.validate_step_receipt(folder, "OpenROAD.STAPostPNR")
                except lc.Refusal as exc:
                    refuse(str(exc))
                if receipt["sha256"].get("config.json") != n.api().digest(folder / "config.json"):
                    refuse("current PDK config is not bound by the retained STA receipt")
                roots = n.api().read(folder / "pdk_root.json")
                mapping = [(guest, host) for host, guest in roots["mounts_under_it"]]
                mapped = localise_mounted_paths(value, mapping)
                path = Path(mapped)
                expected = receipt["input"].get(fingerprint_key, {}).get(value)
                if mapped == value or not path.is_file() or expected != n.api().digest(path):
                    refuse("current PDK model differs from the retained STA mount/input")
                retained_inputs.update(folder / name for name in (
                    "vibeic_receipt.json", "input_fingerprint.json", "pdk_root.json", "invocation.log"))
            paths.append(path)
        return paths

    logical_sources = model_paths(config.get("CELL_VERILOG_MODELS", []))
    pdk_dir = Path(record["pdk_root"]) / record["pdk"]
    if not logical_sources or any(not p.is_file() or not p.resolve().is_relative_to(pdk_dir.resolve()) or
                                  not p.resolve().is_relative_to(project.resolve()) for p in logical_sources):
        refuse("current same-PDK digital driver models are unavailable")
    expected_sources = [*logical_sources, *views]
    supplied_sources = [n.local(project, p).resolve() for p in data["digital"].get("extra_sources", [])]
    if set(supplied_sources) != {p.resolve() for p in expected_sources}:
        refuse("wrapper simulation must consume exactly the current PDK/A8 logical models")
    data["digital"]["extra_sources"] = [str(p.relative_to(project)) for p in expected_sources]
    libs = model_paths(timing["liberties"], "liberty_files")
    for p in libs:
        if not p.resolve().is_relative_to(project.resolve()):
            refuse("the first supported canonical shape requires staged current PDK views")
    graph = n.api().read(project / "reports/analog/mixed_signal/power_domain_tool/netlist.json")
    # M2's native graph uses the producer's established power_domain_tool path.
    module = graph["modules"][data["top"]]
    macro = module["cells"].get(instance)
    driver = module["cells"].get(c["driver_instance"])
    if not macro or macro["type"] != block or not driver:
        refuse("current native graph does not contain the declared physical roles")
    d = data["digital"]
    if (macro["connections"][c["macro_drive"]] != module["ports"][d["drive"]]["bits"] or
            macro["connections"][c["macro_sense"]] != module["ports"][d["sense"]]["bits"] or
            driver["connections"][c["driver_output"]] != module["ports"][d["drive"]]["bits"]):
        refuse("native graph interface pins do not consume the declared wrapper nets")
    definitions = [body for lib in libs for name, body in m2.groups(lib.read_text(), "cell")
                   if name == driver["type"]]
    if len(definitions) != 1:
        refuse("actual driver has no current PDK Liberty view")
    # The sampled transport currently supports a non-inverting single-input
    # driver. Other functions need their own observed input trajectory.
    output_pin = dict(m2.groups(definitions[0], "pin")).get(c["driver_output"], "")
    if not re.search(r'\bfunction\s*:\s*"' + re.escape(c["driver_input"]) + r'"\s*;', output_pin):
        refuse("the first supported sampled driver must be a unity buffer")
    for layer in ("L5", "L9"):
        _, doc = load_l_doc(project, layer)
        fields = l_doc_fields(doc) if doc else {}
        if layer == "L5" and isinstance(fields.get("analog_digital_interfaces"), list):
            declared = {r.get("signal", r.get("name")) for r in fields["analog_digital_interfaces"]}
            if declared != {view["digital"][key] for view in population for key in ("drive", "sense")}:
                refuse("the complete declared ADI signal population is unsupported")
        if layer == "L9":
            declared, discarded = extract_l9_ports_with_audit(fields)
            if (any(str(r.get("reason", "")).startswith("unparseable") for r in discarded) or
                    declared and {r["name"] for r in declared} != set(module["ports"])):
                refuse("current L9 and native top-port populations disagree")
    parsed = parse_spef(n.local(project, timing["spef"]).read_text(), topology=True)
    expected_nets = {d["drive"], d["sense"]}
    names = parsed["name_map"]
    net_name = lambda raw: names.get(raw, raw)
    expected_drivers = {d["drive"]: {c["driver_instance"] + "/" + c["driver_output"]},
                        d["sense"]: {instance + "/" + c["macro_sense"]}}
    allowed_loads = {d["drive"]: {instance + "/" + c["macro_drive"], d["drive"]},
                     d["sense"]: {d["sense"]}}
    for raw, drivers in parsed["net_driver_pins"].items():
        net = net_name(raw)
        if net in expected_nets and set(drivers) != expected_drivers[net]:
            refuse("selected interface has an unsupported electrical driver population")
    for raw, loads in parsed["net_load_pins"].items():
        net = net_name(raw)
        if net in expected_nets and not set(loads) <= allowed_loads[net]:
            refuse("selected interface has an unsupported electrical load population")
    if module["ports"][d["sense"]].get("direction") != "output":
        refuse("the current physical sense port must observe the macro output")
    mapped_pairs = {frozenset((view["digital"]["drive"], view["digital"]["sense"])) for view in population}
    if any(frozenset(net_name(net) for net in pair) not in mapped_pairs for pair in parsed["pair_cc"]):
        refuse("cross-interface or unmapped coupling requires a coupled multi-driver method")
    if not parsed["topology"]["coupling_caps"]:
        refuse("no native mutual-capacitance population was extracted")
    selected_nodes = {node for node, owner in parsed["node_net"].items() if net_name(owner) in expected_nets}
    rc = parsed["topology"]
    rc = {"resistors": [r for r in rc["resistors"] if r[0] in selected_nodes and r[1] in selected_nodes],
          "ground_caps": [r for r in rc["ground_caps"] if r[0] in selected_nodes],
          "coupling_caps": [cap for cap in rc["coupling_caps"] if cap[0] in selected_nodes and cap[1] in selected_nodes]}
    def pin(name):
        found = [raw for raw in selected_nodes if raw.replace(parsed["delimiter"], "/") == name or
                 spice_pin(raw, parsed) == name]
        if len(found) != 1:
            refuse("one current extracted node is required for " + name)
        return found[0]
    pin_roles = {"driver": pin(c["driver_instance"] + "/" + c["driver_output"]),
                 "drive": pin(instance + "/" + c["macro_drive"]),
                 "sense": pin(instance + "/" + c["macro_sense"])}
    sources = model_paths(config.get("CELL_SPICE_MODELS", []))
    if not sources or any(not p.is_file() or not p.resolve().is_relative_to(pdk_dir.resolve()) or
                          not p.resolve().is_relative_to(project.resolve()) for p in sources):
        refuse("current same-PDK driver SPICE material is unavailable")
    header = spice._scc.parse_liberty_header(libs[0].read_text())
    volts = spice.supply_voltages([p.read_text() for p in libs])
    if not config.get("VDD_PIN") in volts or not config.get("GND_PIN") in volts:
        refuse("current Liberty supply voltages are unavailable")
    for lib in libs[1:]:
        other = spice._scc.parse_liberty_header(lib.read_text())
        if any(other.get(key) != header.get(key) for key in ("nom_temperature", "nom_voltage", "nom_process")):
            refuse("all current PDK libraries must use the supported common operating condition")
    sections = spice.model_sections(pdk_dir / "libs.tech/ngspice", "ngspice")
    bindings = []
    for line in a7.model_binding_lines((bdir / (block + ".sp")).read_text(), bdir, post.parent):
        binding = spice._LIB_REF_RE.match(line)
        if binding:
            target = Path(binding.group(1))
            target = target if target.is_absolute() else post.parent / target
            bindings.append((str(target.resolve()), binding.group(2)))
    process = {"tt", "typ", "typical", "nom", "nominal", "ff", "ss", "fs", "sf", "fast", "slow"}
    central = {"tt", "typ", "typical", "nom", "nominal"}
    tokens = set(re.split(r"[^a-z]+", libs[0].stem.lower())) & process
    if not tokens or not bindings:
        refuse("actual A7 model section/current Liberty process is not resolved")
    covered = set()
    for binding in bindings:
        candidates = [key for key in sections if Path(key[0]).resolve() == Path(binding[0])]
        expected = spice._scc.select_model_section(candidates, libs[0].name)
        selected_tokens = set(re.findall(r"[a-z]+", binding[1].lower()))
        if expected != binding or not (tokens & selected_tokens or tokens & central and selected_tokens & central):
            refuse("A7 model section differs from the current PDK Liberty process")
        covered |= sections[binding]
    devices = spice.device_names(post.read_text() + "\n" + "\n".join(p.read_text() for p in sources))
    if devices - covered:
        refuse("current same-PDK model sections do not cover the actual devices")
    if (data["analog"]["drive_low_v"] != volts[config["GND_PIN"]] or
            data["analog"]["drive_high_v"] != volts[config["VDD_PIN"]]):
        refuse("sampled drive rails differ from the current PDK corner")
    signal_pins = {view["canonical"]["instance"] + "/" + view["canonical"][key]
                   for view in population for key in ("macro_drive", "macro_sense")}
    if {item.get("pin") for item in data["si"]["interfaces"]} != signal_pins:
        refuse("timing criteria must consume every current macro signal pin")
    driver_views = [ports for source in sources for name, (ports, _) in
                    spice.subckt_devices(source.read_text()).items() if name == driver["type"]]
    if len(driver_views) != 1 or any(port not in {c["driver_input"], c["driver_output"], *volts}
                                   for port in driver_views[0]):
        refuse("the actual PDK driver port population is unsupported")
    model_inputs = set(sources)
    pending = [post, *sources]
    while pending:
        source = pending.pop()
        for line in a7._joined_lines(source.read_text()):
            if spice._LIB_OPEN_RE.match(line):
                continue
            match = a7._LIB_RE.match(line)
            if not match:
                continue
            target = Path(match.group(2).strip("'\""))
            target = target if target.is_absolute() else source.parent / target
            target = target.resolve()
            if not target.is_file() or not target.is_relative_to(pdk_dir.resolve()) or not target.is_relative_to(project.resolve()):
                refuse("current SPICE bindings must consume staged same-PDK material")
            if target not in model_inputs:
                model_inputs.add(target)
                pending.append(target)
    inputs = {str(p.relative_to(project)) for p in [block_list, record_path, bdir / "pre_vs_post.json", bdir / "topology.json",
        bdir / (block + ".sp"), extracted, post, step / "vibeic_receipt.json", step / "input_fingerprint.json",
        step / "state_out.json", step / "pdk_root.json", step / "invocation.log", manifest_path,
        project / "phase3/mixed_signal/m1_merge_receipt.json", project / "reports/analog/mixed_signal/top_lvs.json",
        project / "reports/analog/mixed_signal/power_domain_run.json", project / "reports/analog/mixed_signal/power_domain_tool/netlist.json",
        project / postroute.STEP23_RECORD, folder / "config.json", folder / c["sta_corner"] / "sta.log", *libs, *model_inputs, *logical_sources, *retained_inputs]}
    inputs.update(timing[k] for k in ("sta_netlist", "sdc", "spef", "state"))
    data["si"] = {**data["si"], "netlist": timing["sta_netlist"], "sdc": timing["sdc"],
                  "spef": timing["spef"], "liberties": [str(p.relative_to(project)) for p in libs]}
    data["_current"] = {"inputs": sorted(inputs), "block": block, "post": str(post.relative_to(project)),
        "ports": ports, "rails": rails, "rc": rc, "pin_roles": pin_roles, "nodes": sorted(selected_nodes),
        "driver_cell": driver["type"], "driver_sources": [str(p.relative_to(project)) for p in sources],
        "driver_ports": driver_views[0],
        "driver_input": c["driver_input"], "driver_output": c["driver_output"], "voltages": volts,
        "power": config["VDD_PIN"], "ground": config["GND_PIN"], "temperature_c": header.get("nom_temperature")}
    return data


def spice_pin(raw, parsed):
    from si_signoff_timing_aware import _map_pin
    return _map_pin(raw, parsed["name_map"], parsed["delimiter"])


def deck(project, data, row, drive, wave):
    """Actual extracted R/C and current A7/PDK views, one native circuit."""
    n = native()
    m = data["_current"]
    period, step, _, cycles = n.settings(row)
    a = data["analog"]
    for key in ("drive_low_v", "drive_high_v", "drive_transition_ns", "adc_low_v", "adc_high_v"):
        n.number(a[key], key, positive=key == "drive_transition_ns")
    if not a["drive_low_v"] <= a["adc_low_v"] < a["adc_high_v"] <= a["drive_high_v"] or a["drive_transition_ns"] >= period / 2:
        refuse("bounded DAC/ADC declaration inside the current rails required")
    low, high, rise = a["drive_low_v"], a["drive_high_v"], a["drive_transition_ns"]
    points = [(0, high if int(drive[0]["drive"]) else low)]
    for previous, current in zip(drive, drive[1:]):
        if current["drive"] != previous["drive"]:
            points.extend([(current["time_ns"], high if int(previous["drive"]) else low),
                           (current["time_ns"] + rise, high if int(current["drive"]) else low)])
    points.append((period * cycles, high if int(drive[-1]["drive"]) else low))
    pwl = " ".join(f"{t * 1e-9:.17g} {v:.17g}" for t, v in points)
    noise = data["canonical"]["noise"]
    bound_criteria(noise["criteria"], "integrated_output_noise_v_rms", "V_RMS")
    bound_criteria(data["canonical"]["crosstalk"]["criteria"], "peak_crosstalk_v", "V_PEAK")
    start = n.number(noise["frequency_start_hz"], "frequency_start_hz", True)
    stop = n.number(noise["frequency_stop_hz"], "frequency_stop_hz", True)
    count = noise["points_per_decade"]
    if type(count) is not int or not 20 <= count <= 200 or not 0 < start < stop <= 1e12:
        refuse("bounded native noise sweep required")
    intervals = count * math.log10(stop / start)
    if not 2 <= intervals <= 20000 or not math.isclose(intervals, round(intervals), abs_tol=1e-7):
        refuse("a complete bounded noise grid is required")
    bias = n.number(noise["dc_drive_v"], "dc_drive_v")
    if not low <= bias <= high:
        refuse("noise bias must lie inside the current rails")
    if m["temperature_c"] is None:
        refuse("current Liberty temperature is unavailable")
    model_sha = n.api().digest(n.local(project, m["post"]))
    lines = ["* Current A7 + same-PDK driver + actual SPEF R/C; no analytical augmentation",
             *(f'.include "{n.local(project, p)}"' for p in m["driver_sources"]),
             f'.include "{n.local(project, m["post"])}"', f'.temp {m["temperature_c"]:.17g}',
             f'Vdrive stimulus 0 DC {noise["dc_drive_v"]:.17g} AC 1 PWL({pwl})']
    for prefix in ("live", "reference"):
        nodes = {raw: f"{prefix}_{i}" for i, raw in enumerate(m["nodes"])}
        p = m["pin_roles"]
        # A unity driver's logical input follows the observed actual wrapper
        # trajectory. Its current PDK SPICE still determines electrical drive.
        driver_ports = {m["driver_input"]: "stimulus", m["driver_output"]: nodes[p["driver"]]}
        for rail in m["driver_ports"]:
            if rail in m["voltages"]:
                driver_ports[rail] = prefix + "_driver_" + rail
                lines.append(f'V{prefix}driver{rail} {driver_ports[rail]} 0 {m["voltages"][rail]:.17g}')
        lines.append(f'X{prefix}driver ' + " ".join(driver_ports[port] for port in m["driver_ports"]) + " " + m["driver_cell"])
        ports = {data["canonical"]["macro_drive"]: nodes[p["drive"]],
                 data["canonical"]["macro_sense"]: nodes[p["sense"]]}
        for rail in m["rails"].values():
            if rail not in m["voltages"]:
                refuse("macro rail has no same-PDK Liberty voltage")
            ports[rail] = prefix + "_" + rail
            lines.append(f'V{prefix}{rail} {ports[rail]} 0 {m["voltages"][rail]:.17g}')
        lines.append(f'X{prefix}receiver ' + " ".join(ports[port] for port in m["ports"]) + " " + m["block"])
        for i, (left, right, value) in enumerate(m["rc"]["resistors"]):
            lines.append(f'R{prefix}{i} {nodes[left]} {nodes[right]} {value:.17g}')
        for i, (node, value) in enumerate(m["rc"]["ground_caps"]):
            if value:
                lines.append(f'C{prefix}g{i} {nodes[node]} 0 {value:.17g}')
        if prefix == "live":
            for i, (left, right, value) in enumerate(m["rc"]["coupling_caps"]):
                lines.append(f'C{prefix}c{i} {nodes[left]} {nodes[right]} {value:.17g}')
    sense_index = m["nodes"].index(m["pin_roles"]["sense"])
    token = wave.parent.parent.name
    lines += [".control", "set sparse", "set numdgt=15", "set wr_singlescale", "set wr_vecnames",
        f"echo M3RUN {token}", f'tran {step * 1e-9:.17g} {cycles * period * 1e-9:.17g}',
        f'wrdata wave.txt v(live_{sense_index})', f'wrdata coupling.txt v(live_{sense_index}) v(reference_{sense_index})',
        f"echo M3DONE {token}", "unset sqrnoise",
        f'echo M3NOISE_RUN {token} {row["id"]} {model_sha}',
        f'noise v(live_{sense_index}) Vdrive dec {count} {start:.17g} {stop:.17g}',
        "setplot noise1", "wrdata spectrum.txt onoise_spectrum", "setplot noise2",
        "wrdata integrated.txt onoise_total", "print onoise_total", f'echo M3NOISE_DONE {token} {row["id"]}',
        ".endc", ".end", ""]
    return "\n".join(lines)


def bound_criteria(criteria, metric, units):
    n = native()
    if not isinstance(criteria, list) or not criteria:
        refuse("nonempty bounded native interface criteria required")
    for c in criteria:
        if c.get("metric") != metric or c.get("units") != units or "max" not in c:
            refuse("unsupported or unbounded native interface metric")
        for key in ("min", "max"):
            if key in c and n.number(c[key], key) < 0:
                refuse("nonnegative native interface bounds required")
        if c.get("min", 0) > c["max"]:
            refuse("inverted native interface bounds")


def measure(project, data, row, work, token):
    import path_spice_tool as spice
    import _mixed_signal_receiver_noise as noise
    n = native()
    m = data["_current"]
    index = m["nodes"].index(m["pin_roles"]["sense"])
    wave = spice.read_waveform(work / "coupling.txt", "ngspice")
    live, reference = wave[f"live_{index}"], wave[f"reference_{index}"]
    _, _, _, cycles = n.settings(row)
    period = row["native"]["clock_period_ns"]
    start = n.number(data["canonical"]["crosstalk"]["measure_from_ns"], "crosstalk measure_from_ns")
    if not 0 <= start < cycles * period:
        refuse("native crosstalk measurement window is empty")
    if (len(live) < 3 or len(live) != len(reference) or
            any(not math.isfinite(t + v) for t, v in live + reference) or
            any(b[0] <= a[0] for a, b in zip(live, live[1:])) or
            live[0][0] > start * 1e-9 or
            live[-1][0] < cycles * period * 1e-9 and not math.isclose(live[-1][0], cycles * period * 1e-9, rel_tol=1e-12)):
        raise n.api().Refusal("FAILED_MEASUREMENT", "native coupling window is incomplete")
    values = [abs(left[1] - right[1]) for left, right in zip(live, reference) if left[0] >= start * 1e-9]
    peak = max(values)
    criteria = [{**c, "measured": peak, "verdict": "PASS" if c.get("min", 0) <= peak <= c["max"] else "FAIL"}
                for c in data["canonical"]["crosstalk"]["criteria"]]
    spec = {**data["canonical"]["noise"], "id": row["id"], "top": data["top"], "scope": SCOPE,
            "analysis": "ngspice_noise", "model": m["post"], "model_sha256": n.api().digest(n.local(project, m["post"])),
            "subckt": m["block"], "temperature_c": m["temperature_c"]}
    # derive() checks the independent scalar/spectrum, actual band and tokens.
    noise_spec = noise.derive(project, spec, work, token, log_name="ngspice.log")
    attribution = ({"interface": m["interface_id"], "block": m["block"], "instance": m["instance"]}
                   if "interface_id" in m else {})
    return {"id": row["id"], "scope": SCOPE, **attribution, "noise": noise_spec,
            "crosstalk": {"criteria": criteria, "sample_count": len(values), "verdict": "PASS" if all(c["verdict"] == "PASS" for c in criteria) else "FAIL"},
            "verdict": "FAIL" if noise_spec["verdict"] == "FAIL" or any(c["verdict"] == "FAIL" for c in criteria) else "PASS"}


def blend(project, data, root, result):
    result = {**result, "coverage": dict(result["coverage"]), "blockers": list(result["blockers"])}
    measured = [measure(project, for_scenario(data, row), row, root.parent / row["id"], root.parent.name)
                for row in native().api().plan(project)]
    result["current_interfaces"] = measured
    result["coverage"].update(noise="MEASURED", crosstalk="MEASURED")
    result["blockers"] = [] if result["coverage"]["timing"] == "MEASURED" else result["blockers"]
    failed = result["verdict"] == "FAIL" or any(r["verdict"] == "FAIL" for r in measured)
    result["verdict"] = "FAIL" if failed else "PASS" if measured and all(v == "MEASURED" for v in result["coverage"].values()) else "NOT_MEASURED"
    result["all_interfaces_clean"] = result["verdict"] == "PASS"
    return result
