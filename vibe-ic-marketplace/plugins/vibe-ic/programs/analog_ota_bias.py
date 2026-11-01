"""Declared SC loads and independently ratioed OTA bias branches.

A noise budget may size a sampling capacitor, but it is not an OTA load.
The realized Cs/Cf/Ci network owns feedback and settling. A declared
reference geometry can preserve a characterized OTA operating point while
independent mirror translators supply the other consumers. Current totals
remain estimates until native operating-point evidence is supplied.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re


_OLD_REQUIREMENTS = {"slew_margin", "bias_resistor_l_um", "settling_time_constants",
                     "settling_time_constants_at_fclk_max"}


def prepare_library(library):
    lib = deepcopy(library)
    requirements = lib.get("requires_derived", [])
    bound = next((r for r in requirements if r.get("name") == "bias_resistor_l_um"), {})
    lib["ota_bias_reference_bounds"] = lib.get("ota_bias_reference_bounds", {k: bound[k] for k in ("min", "max") if k in bound})
    lib["requires_derived"] = [r for r in requirements if r.get("name") not in _OLD_REQUIREMENTS]
    for row in lib.get("device_param_exprs", []):
        if row.get("device") == "r_ib" and row.get("param") == "l":
            row["expr"] = "bias_reference_length_um"
            row["rationale"] = "single reference declaration; per-OTA SC load targets set independent mirror branches"
    return lib


def _number(value, name, *, zero=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or (not zero and value == 0)):
        raise ValueError("OTA_BIAS_INPUT_INVALID: " + name + " must be finite and "
                         + ("nonnegative" if zero else "positive"))
    return float(value)


def read_inputs(project, block):
    path = project / "phase3/analog" / block / "bias_network_inputs.json"
    if not path.exists():
        return {}, None
    try:
        payload = path.read_bytes()
        data = json.loads(payload)
    except (OSError, ValueError) as exc:
        raise ValueError("OTA_BIAS_INPUT_INVALID: " + str(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("OTA_BIAS_INPUT_INVALID: bias_network_inputs must be an object")
    allowed = {"schema", "reference", "stages", "common_mode", "channel_current_budget_a",
               "fixed_current_a", "citation"}
    if set(data) - allowed:
        raise ValueError("OTA_BIAS_INPUT_INVALID: unknown fields " + str(sorted(set(data)-allowed)))
    if isinstance(data.get("schema", 1), bool) or data.get("schema", 1) != 1:
        raise ValueError("OTA_BIAS_INPUT_INVALID: unsupported schema")
    for key in ("reference", "stages", "common_mode"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError("OTA_BIAS_INPUT_INVALID: " + key + " must be an object")
    nested = {"reference": {"resistor_length_um", "current_a"},
              "common_mode": {"load_ff", "supply_current_a"}}
    for key, keys in nested.items():
        if set(data.get(key, {})) - keys:
            raise ValueError("OTA_BIAS_INPUT_INVALID: unknown " + key + " fields")
    for stage, row in data.get("stages", {}).items():
        if not re.fullmatch(r"[1-9]\d*", str(stage)) or not isinstance(row, dict):
            raise ValueError("OTA_BIAS_INPUT_INVALID: invalid stage declaration")
        if set(row) - {"input_parasitic_ff", "output_load_ff", "supply_current_a"}:
            raise ValueError("OTA_BIAS_INPUT_INVALID: unknown stage " + str(stage) + " fields")
    return data, {"path": str(path.relative_to(project)),
                  "sha256": hashlib.sha256(payload).hexdigest(),
                  "citation": data.get("citation")}


def _wl(device):
    return (_number(device["w"], device["name"] + ".w")
            / _number(device["l"], device["name"] + ".l")
            * _number(device.get("m", 1), device["name"] + ".m"))


def apply(library, values, devices, exprs, nets, constants, env, evaluate, project, block,
          minima=None, maxima=None, spec_path=None):
    declaration, source = read_inputs(project, block)
    specification = None
    if spec_path is not None:
        path = Path(spec_path)
        if not path.is_absolute():
            path = project / path
        if path.is_file():
            try:
                relative = path.resolve().relative_to(project.resolve())
                specification = {"path": str(relative),
                                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            except (OSError, ValueError) as exc:
                raise ValueError("OTA_BIAS_SPEC_INPUT_INVALID: " + str(exc)) from exc
    by_name = {d["name"]: d for d in devices}
    stages = sorted(int(n[2:]) for n in by_name if re.fullmatch(r"ci\d+", n))
    if not stages or "mn_bias" not in by_name or "r_ib" not in by_name:
        return None
    unknown_stages = set(declaration.get("stages", {})) - {str(i) for i in stages}
    if unknown_stages:
        raise ValueError("OTA_BIAS_INPUT_INVALID: undeclared stages " + str(sorted(unknown_stages)))
    by_expr = {(r["device"], r["param"]): r for r in exprs}
    def capacitance(name):
        if name not in by_name:
            return 0.
        d = by_name[name]
        row = by_expr.get((name, "l"))
        if "cap_area_ff_per_um2" in env:
            length = evaluate(row["expr"], env) if row else d["l"]
            return _number((env["cap_area_ff_per_um2"]*d["w"]*length
                           + 2*env.get("cap_perim_ff_per_um", 0)*(d["w"]+length))
                           * d.get("m", 1), name + " capacitance")
        if row and row.get("ff_expr"):
            ff = row["ff_expr"]
            if "coefficient" in row:
                ff = ff.format(coeff=row["coefficient"])
            return _number(evaluate(ff, env), name + " capacitance")
        raise ValueError("OTA_BIAS_LOAD_NOT_DERIVABLE: " + name)
    time = _number(env["settle_periods_available"], "settle_periods_available") / (
        _number(values["fclk"], "fclk") * env["hz_per_mhz"])
    margin = _number(env["slew_design_margin"], "slew_design_margin")
    vref = _number(values["vref"], "vref")
    vov = _number(env["integrator_input_overdrive_v"], "integrator_input_overdrive_v")
    required = (values["enob"] + env["settling_lsb_fraction_bits"]) * env["ln2"]
    reference = by_name["mn_bias"]
    reference_wl = _wl(reference)
    rows = []
    for stage in stages:
        setting = declaration.get("stages", {}).get(str(stage), {})
        if not isinstance(setting, dict):
            raise ValueError("OTA_BIAS_INPUT_INVALID: stage must be an object")
        cs, cf, ci = [capacitance(stem+str(stage)) for stem in ("cs", "cf", "ci")]
        cp = _number(setting.get("input_parasitic_ff", 0), "input_parasitic_ff", zero=True)
        default_load = (capacitance("cs"+str(stage+1)) + capacitance("cff"+str(stage))
                        + capacitance("cc"+str(stage)))
        if stage == stages[-1] and "cff"+str(stage) not in by_name:
            default_load += capacitance("caz")
        cl = _number(setting.get("output_load_ff", default_load), "output_load_ff", zero=True)
        beta = ci/(ci+cs+cf+cp)
        load = cl + ci*(cs+cf+cp)/(ci+cs+cf+cp)
        tail = "mn_tail"+str(stage)
        output = "mn_o"+str(stage)
        sinks = [tail] + ([output] if output in by_name else [])
        row = {"stage": stage, "Cs_ff": cs, "Cf_ff": cf, "Ci_ff": ci,
               "input_parasitic_ff": cp, "output_load_ff": cl, "beta": beta,
               "load_ff": load, "devices": sinks, "gate": "nbias" if stage == stages[0] else "nbias_ota"+str(stage),
               "I_slew_a": load*1e-15*vref*margin/time,
               "I_settle_a": load*1e-15*vov*required/(beta*time),
               "settling_time_constants_required": required,
               "tail_ratio": _wl(by_name[tail])/reference_wl,
               "output_ratio": _wl(by_name[output])/reference_wl if output in by_name else None,
               "supply_current_a": setting.get("supply_current_a"),
               "load_model": {"input_parasitic": "declared" if "input_parasitic_ff" in setting else "not_declared_zero_model",
                              "output_load": "declared" if "output_load_ff" in setting else "emitted_next_stage_summer_and_compensation",
                              "native_verified": False}}
        row["I_target_a"] = max(row["I_slew_a"], row["I_settle_a"])
        row["reference_current_a"] = max(row["I_settle_a"]/row["tail_ratio"],
            row["I_slew_a"]/(row["output_ratio"] or row["tail_ratio"]))
        rows.append(row)
    if "mn_cmtail" in by_name and "mn_cmo" in by_name:
        setting = declaration.get("common_mode", {})
        load = _number(setting.get("load_ff", capacitance("c_vcm") + capacitance("c_cmc")), "common_mode.load_ff")
        row = {"stage": "common_mode", "Cs_ff": 0., "Cf_ff": 0., "Ci_ff": 0.,
               "input_parasitic_ff": 0., "output_load_ff": load, "beta": 1.,
               "load_ff": load, "devices": ["mn_cmtail", "mn_cmo"], "gate": "nbias_common_mode",
               "I_slew_a": load*1e-15*vref*margin/time,
               "I_settle_a": load*1e-15*vov*required/time,
               "settling_time_constants_required": required,
               "tail_ratio": _wl(by_name["mn_cmtail"])/reference_wl,
               "output_ratio": _wl(by_name["mn_cmo"])/reference_wl,
               "supply_current_a": setting.get("supply_current_a"),
               "load_model": {"load": "declared" if "load_ff" in setting else "emitted_common_mode_capacitors",
                              "effective_switched_load_declared": "load_ff" in setting,
                              "native_verified": False}}
        row["I_target_a"] = max(row["I_slew_a"], row["I_settle_a"])
        row["reference_current_a"] = max(row["I_settle_a"]/row["tail_ratio"], row["I_slew_a"]/row["output_ratio"])
        rows.append(row)
    ref_inputs = declaration.get("reference", {})
    bounds = library.get("ota_bias_reference_bounds", {})
    headroom = _number(env["vdd"]-env["vth_n_extracted_v"]-env["bias_overdrive_v"], "reference headroom")
    sheet = _number(env["rsheet_ohm_per_sq"], "rsheet_ohm_per_sq")
    width = _number(by_name["r_ib"]["w"], "r_ib.w")
    if "resistor_length_um" in ref_inputs:
        length = _number(ref_inputs["resistor_length_um"], "reference.resistor_length_um")
        reference_current = _number(ref_inputs.get("current_a", headroom/(sheet*length/width)), "reference.current_a")
        reference_source = "declared_reference_geometry"
    else:
        reference_current = _number(ref_inputs.get("current_a", rows[0]["reference_current_a"]), "reference.current_a")
        reference_source = "declared_current" if "current_a" in ref_inputs else "first_stage_declared_load"
        if not ref_inputs and bounds.get("max") is not None:
            floor_current = headroom*width/(sheet*bounds["max"])
            if floor_current > reference_current:
                reference_current = floor_current
                reference_source = "first_stage_load_and_reference_geometry_bound"
        length = headroom/reference_current*width/sheet
    if (bounds.get("min") is not None and length < bounds["min"] or
            bounds.get("max") is not None and length > bounds["max"]):
        raise ValueError("OTA_BIAS_REFERENCE_NOT_REALISABLE: resistor length outside declared bounds")
    constants["bias_reference_length_um"] = env["bias_reference_length_um"] = length
    by_expr[("r_ib", "l")]["expr"] = "bias_reference_length_um"
    pmaster = next(d for d in devices if d.get("role") == "pmos")
    branches = []
    for row in rows:
        need = row["reference_current_a"]
        actual_reference = reference_current if row is rows[0] else need
        row["I_tail_estimate_a"] = actual_reference*row["tail_ratio"]
        row["I_output_estimate_a"] = actual_reference*(row["output_ratio"] or row["tail_ratio"])
        row["settling_time_constants"] = row["I_tail_estimate_a"]*row["beta"]*time/(vov*row["load_ff"]*1e-15)
        row["slew_margin"] = row["I_output_estimate_a"]*time/(row["load_ff"]*1e-15*vref)
        row["status"] = "SIZED" if row["settling_time_constants"] >= required*(1-1e-12) and row["slew_margin"] >= margin*(1-1e-12) else "UNDER_BIASED"
        row["mirror_reference_current_a"] = actual_reference
        row["mirror_ratio"] = actual_reference/reference_current
        row["sink_geometry"] = {name: {k: by_name[name][k] for k in ("w", "l", "m", "ng") if k in by_name[name]} for name in row["devices"]}
        row["translator_cards"] = []
        if row is rows[0]:
            row["translator_devices"] = []
        else:
            token = str(row["stage"])
            prefix = "ota_bias_"+token
            pref = prefix+"_p"
            gate = row["gate"]
            branch_names = []
            for suffix, master, terminals, ratio in (
                    ("sink", reference, [pref, "nbias", "vss", "vss"], need/reference_current),
                    ("pdiode", pmaster, [pref, pref, "vdd", "vdd"], 1.),
                    ("psource", pmaster, [gate, pref, "vdd", "vdd"], 1.),
                    ("ndiode", reference, [gate, gate, "vss", "vss"], 1.)):
                device = deepcopy(master)
                device.update(name=prefix+"_"+suffix, nets=terminals,
                              function="independent OTA bias mirror translator")
                device["w"] *= ratio
                for parameter, dimension in (("w", "width"), ("l", "length")):
                    value = device[parameter] / device.get("ng", 1) if parameter == "w" else device[parameter]
                    low = ((minima or {}).get(device["role"]) or {}).get("min_"+dimension+"_um")
                    high = ((maxima or {}).get(device["role"]) or {}).get("max_"+dimension+"_um")
                    if low is not None and value < low or high is not None and value > high:
                        raise ValueError("OTA_BIAS_MIRROR_NOT_REALISABLE: " + device["name"] + "." + parameter)
                devices.append(device)
                row["translator_cards"].append(deepcopy(device))
                branch_names.append(device["name"])
            row["translator_devices"] = branch_names
            nets.extend([pref, gate])
            for name in row["devices"]:
                by_name[name]["nets"][1] = gate
        row["folded_cards"] = []
        row["folded_net_map"] = {}
        row["folded_stage_devices"] = []
        shared_folded = library.get("folded_first_stage", {})
        folded_names = [d["name"] for d in shared_folded.get("devices", [])]
        if (row is not rows[0] and isinstance(row["stage"], int)
                and folded_names and all(name in by_name for name in folded_names)):
            prefix = "ota_bias_"+str(row["stage"])+"_"
            mapping = {net: prefix+net for net in shared_folded["internal_nets"]}
            row["folded_net_map"] = mapping
            for device in list(by_name.values()):
                suffix = re.search(r"(\d+)$", device["name"])
                if suffix and int(suffix[1]) == row["stage"] and any(net in mapping for net in device.get("nets", [])):
                    device["nets"] = [mapping.get(net, net) for net in device["nets"]]
                    row["folded_stage_devices"].append(device["name"])
            for name in folded_names:
                device = deepcopy(by_name[name])
                device["name"] = prefix+name
                device["nets"] = [row["gate"] if net == "nbias" else mapping.get(net, net) for net in device["nets"]]
                devices.append(device)
                row["folded_cards"].append(deepcopy(device))
            nets.extend(mapping.values())
            row["folded_bias_current_estimate_a"] = 2*need*_wl(by_name["mn_fc_bias_sink"])/reference_wl
        else:
            row["folded_bias_current_estimate_a"] = 0.
        branches.append({"stage": row["stage"], "gate": row["gate"],
                         "devices": row["devices"], "translator_devices": row["translator_devices"],
                         "target_reference_current_a": actual_reference})
    known = reference_current
    locked = reference_current
    unknown = False
    for row in rows:
        supply = row["supply_current_a"]
        folded_ref = (row.get("folded_net_map") or {}).get("fc_p_ref", "fc_p_ref")
        folded_sink = "ota_bias_"+str(row["stage"])+"_mn_fc_bias_sink" if row.get("folded_cards") else "mn_fc_bias_sink"
        folded_diode = "ota_bias_"+str(row["stage"])+"_mp_fc_bias" if row.get("folded_cards") else "mp_fc_bias"
        physical = {d["name"]: d for d in devices}
        if isinstance(row["stage"], int) and folded_sink in physical and folded_diode in physical:
            replica = row["mirror_reference_current_a"]*_wl(physical[folded_sink])/reference_wl
            diode_wl = _wl(physical[folded_diode])
            source_ratio = sum(_wl(d)/diode_wl for d in devices if d.get("role") == "pmos"
                               and d.get("nets", [None]*4)[1:] == [folded_ref, "vdd", "vdd"])
            row["folded_rail_supply_estimate_a"] = replica*source_ratio
        else:
            row["folded_rail_supply_estimate_a"] = None
        if supply is not None:
            supply = _number(supply, "supply_current_a")
        elif row["output_ratio"] is not None:
            supply = ((row["folded_rail_supply_estimate_a"] if row["folded_rail_supply_estimate_a"] is not None
                       else row["I_tail_estimate_a"]) + row["I_output_estimate_a"])
        else:
            supply = row["I_tail_estimate_a"]
            unknown = True
        row["supply_current_estimate_a"] = supply
        known += supply + (2*row["mirror_reference_current_a"] if row["translator_devices"] else 0.)
        if not row["translator_devices"]:
            locked += supply
    if "fixed_current_a" in declaration:
        fixed = _number(declaration["fixed_current_a"], "fixed_current_a", zero=True)
        known += fixed
        locked += fixed
    else:
        unknown = True
    limit = declaration.get("channel_current_budget_a")
    if limit is not None:
        limit = _number(limit, "channel_current_budget_a")
    status = "EXCEEDED" if limit is not None and known > limit else "UNDECIDED" if unknown or limit is None else "PASS_ESTIMATE"
    budget = {"status": status, "estimated_current_a": known, "limit_a": limit,
              "fixed_current_a": declaration.get("fixed_current_a"),
              "complete_estimate": not unknown, "native_verified": False,
              "locked_current_a": locked, "scalable_current_a": known-locked,
              "tradeoff_model": "fixed reference, OTA1 and fixed loads; fixed-overdrive scaling of independent consumers",
              "tradeoff_curve": [{"current_scale": scale, "estimated_current_a": locked+(known-locked)*scale,
                                  "settling_time_scale": 1/scale,
                                  "native_verified": False} for scale in (0.5, 0.75, 1., 1.25, 1.5)]}
    return {"schema": 1, "method": "declared_sc_load_independent_mirror_branches",
            "input": source, "specification": specification, "reference": {"node": "nbias", "device": "mn_bias", "resistor": "r_ib",
            "resistor_length_um": length, "resistor_width_um": width,
            "device_geometry": {k: reference[k] for k in ("w", "l", "m", "ng") if k in reference},
            "current_a": reference_current, "source": reference_source},
            "stage_table": rows, "branches": branches, "budget": budget,
            "warnings": (["OTA_BIAS_STAGE_UNDER_BIASED: "+str(r["stage"]) for r in rows if r["status"] == "UNDER_BIASED"]
                         + (["OTA_BIAS_COMMON_MODE_LOAD_UNDECLARED: emitted capacitor load is a model; switched loading and step remain unverified"]
                            if "common_mode" not in declaration and any(r["stage"] == "common_mode" for r in rows) else []))}


def _problems(ir, project=None):
    record = ir.get("ota_bias_network")
    if record is None:
        return []
    if not isinstance(record, dict) or not isinstance(record.get("stage_table"), list) or not record["stage_table"]:
        return ["OTA_BIAS_RECORD_INVALID: missing consumer table"]
    actual = {d.get("name"): d for d in ir.get("devices", [])}
    findings = []
    first_stage = min((r["stage"] for r in record.get("stage_table", []) if isinstance(r.get("stage"), int)), default=1)
    reference_record = record.get("reference", {})
    reference_device = actual.get(reference_record.get("device"), {})
    ref_node = reference_record.get("node")
    if (reference_device.get("role") != "nmos" or reference_device.get("nets", [])[:2] != [ref_node, ref_node]
            or ir.get("constants", {}).get("bias_reference_length_um") != reference_record.get("resistor_length_um")):
        findings.append("OTA_BIAS_REFERENCE_INVALID: actual reference differs from the network record")
    rdevice = actual.get(reference_record.get("resistor"), {})
    rrows = [r for r in ir.get("device_param_exprs", [])
             if r.get("device") == reference_record.get("resistor") and r.get("param") == "l"]
    if (rdevice.get("role") != "res" or rdevice.get("w") != reference_record.get("resistor_width_um")
            or len(rrows) != 1 or rrows[0].get("expr") != "bias_reference_length_um"
            or any(reference_device.get(k) != value for k, value in reference_record.get("device_geometry", {}).items())):
        findings.append("OTA_BIAS_REFERENCE_INVALID: reference geometry or rendered resistor expression differs")
    if project is not None:
        specification = record.get("specification")
        if specification is not None:
            relative = Path(specification["path"])
            if relative.is_absolute() or ".." in relative.parts:
                findings.append("OTA_BIAS_SPEC_CHANGED: specification path is not case-relative")
            else:
                path = project / relative
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != specification.get("sha256"):
                    findings.append("OTA_BIAS_SPEC_CHANGED: regenerate A2 for the current specification")
        path = project / "phase3/analog" / ir.get("block", "") / "bias_network_inputs.json"
        source = record.get("input")
        if path.exists() != bool(source):
            findings.append("OTA_BIAS_INPUT_CHANGED: regenerate A2 for current bias declaration")
        elif source and hashlib.sha256(path.read_bytes()).hexdigest() != source.get("sha256"):
            findings.append("OTA_BIAS_INPUT_CHANGED: bias declaration no longer matches emitted network")
    gates = {}
    for row in record.get("stage_table", []):
        expected = "nbias" if row.get("stage") == first_stage else "nbias_ota"+str(row["stage"]) if isinstance(row.get("stage"), int) else "nbias_common_mode"
        if row.get("gate") != expected:
            findings.append("OTA_BIAS_BRANCH_INVALID: consumer gate identity differs from its independent branch")
        for name in row.get("devices", []):
            device = actual.get(name)
            if not device or len(device.get("nets", [])) != 4 or device["nets"][1] != expected:
                findings.append("OTA_BIAS_BRANCH_INVALID: "+str(name))
            else:
                gates.setdefault(device["nets"][1], []).append(row)
                expected_geometry = row.get("sink_geometry", {}).get(name, {})
                if any(device.get(k) != value for k, value in expected_geometry.items()):
                    findings.append("OTA_BIAS_BRANCH_INVALID: " + str(name) + " geometry")
        if row.get("stage") != first_stage:
            prefix = "ota_bias_"+str(row["stage"])
            pref = prefix+"_p"
            expected_branches = {
                prefix+"_sink": ("nmos", [pref, ref_node, "vss", "vss"]),
                prefix+"_pdiode": ("pmos", [pref, pref, "vdd", "vdd"]),
                prefix+"_psource": ("pmos", [expected, pref, "vdd", "vdd"]),
                prefix+"_ndiode": ("nmos", [expected, expected, "vss", "vss"])}
            rename = ir.get("port_binding", {}).get("renamed", {})
            for name, (role, terminals) in expected_branches.items():
                device = actual.get(name, {})
                terminals = [rename.get(net, net) for net in terminals]
                if device.get("role") != role or device.get("nets") != terminals:
                    findings.append("OTA_BIAS_BRANCH_INVALID: " + name + " must originate at the one reference")
        for expected_card in row.get("translator_cards", []) + row.get("folded_cards", []):
            device = actual.get(expected_card["name"])
            if device is None or any(device.get(k) != expected_card.get(k) for k in ("role", "nets", "w", "l", "m", "ng")):
                findings.append("OTA_BIAS_BRANCH_INVALID: " + expected_card["name"] + " mirror graph")
        for name in row.get("translator_devices", []):
            if name not in actual:
                findings.append("OTA_BIAS_BRANCH_INVALID: "+str(name))
    for gate, rows in gates.items():
        needs = {r.get("reference_current_a") for r in rows}
        if len(needs) > 1:
            findings.append("OTA_BIAS_SHARED_NEEDS: "+str(gate))
    rows = record["stage_table"]
    def same(a, b):
        return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-18)
    for row in rows:
        if not same(row["I_target_a"], max(row["I_slew_a"], row["I_settle_a"])):
            findings.append("OTA_BIAS_MODEL_INVALID: target no longer matches slew and settling requirements")
        expected_ref = max(row["I_settle_a"]/row["tail_ratio"], row["I_slew_a"]/(row["output_ratio"] or row["tail_ratio"]))
        if not same(row["reference_current_a"], expected_ref):
            findings.append("OTA_BIAS_MODEL_INVALID: reference ratio no longer matches consumer requirements")
    budget = record["budget"]
    fixed = budget.get("fixed_current_a")
    known = reference_record["current_a"] + sum(r["supply_current_estimate_a"] +
        (2*r["mirror_reference_current_a"] if r.get("translator_devices") else 0.) for r in rows)
    if fixed is not None:
        known += fixed
    locked = reference_record["current_a"] + sum(r["supply_current_estimate_a"] for r in rows if not r.get("translator_devices")) + (fixed or 0.)
    unknown = fixed is None or any(r.get("supply_current_a") is None and r.get("output_ratio") is None for r in rows)
    limit = budget.get("limit_a")
    expected_status = "EXCEEDED" if limit is not None and known > limit else "UNDECIDED" if unknown or limit is None else "PASS_ESTIMATE"
    if (not same(budget["estimated_current_a"], known) or budget.get("status") != expected_status
            or budget.get("complete_estimate") != (not unknown) or budget.get("native_verified") is not False
            or not same(budget["locked_current_a"], locked) or not same(budget["scalable_current_a"], known-locked)):
        findings.append("OTA_BIAS_BUDGET_INVALID: budget verdict or total no longer matches physical branch model")
    for point in budget.get("tradeoff_curve", []):
        scale = _number(point["current_scale"], "current_scale")
        if (not same(point["estimated_current_a"], locked+(known-locked)*scale)
                or not same(point["settling_time_scale"], 1/scale) or point.get("native_verified") is not False):
            findings.append("OTA_BIAS_BUDGET_INVALID: tradeoff changes locked reference or OTA1/fixed currents")
    return findings


def legacy_shared_warning(ir):
    if ir.get("ota_bias_network") or ir.get("block_type") != "delta_sigma":
        return None
    devices = {d.get("name"): d for d in ir.get("devices", [])}
    exprs = {(r.get("device"), r.get("param")): r.get("expr") for r in ir.get("device_param_exprs", [])}
    groups = {}
    for name, device in devices.items():
        match = re.fullmatch(r"mn_tail(\d+)", str(name))
        if not match or len(device.get("nets", [])) != 4:
            continue
        stage = match[1]
        load = []
        for stem in ("cs", "cf", "ci"):
            cap = devices.get(stem+stage, {})
            load.append((cap.get("w"), exprs.get((stem+stage, "l"), cap.get("l"))))
        groups.setdefault(device["nets"][1], []).append(tuple(load))
    if any(len(set(loads)) > 1 for loads in groups.values()):
        return "OTA_BIAS_SHARED_NEEDS: legacy shared gate supplies different declared SC loads without per-OTA sizing; regenerate A2"
    return None


def route_existing_consumers(devices, network):
    by_name = {d["name"]: d for d in devices}
    for row in (network or {}).get("stage_table", []):
        for name in row.get("devices", []):
            if name in by_name:
                by_name[name]["nets"][1] = row["gate"]
        for name in row.get("folded_stage_devices", []):
            if name in by_name:
                by_name[name]["nets"] = [row.get("folded_net_map", {}).get(net, net) for net in by_name[name]["nets"]]


def problems(ir, project=None):
    try:
        return _problems(ir, project)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return ["OTA_BIAS_RECORD_INVALID: " + str(exc)]
