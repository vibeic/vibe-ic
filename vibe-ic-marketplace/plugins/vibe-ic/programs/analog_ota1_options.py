"""Declared OTA1 cell and internal chopper options; no transistor sizing.

Existing geometry is retained. New folded-cell geometry and physical bias
resistors must be bound by the ordinary sizing input, and chopper switch
geometry must be declared explicitly. This module does not select a current,
overdrive, transistor area, capacitor value, or noise budget.
"""
from copy import deepcopy
import math
import re


LABELS = ("ota1_folded_cascode", "ota1_chopper", "ota1_chop_ratio",
          "ota1_chop_sc_phase", "ota1_chop_polarity", "ota1_chop_nmos_w_um",
          "ota1_chop_pmos_w_um", "ota1_chop_l_um", "ota1_cc_ff",
          "ota1_chop_stages", "ota1_folded_remove_cc")


def spec_label(name):
    token = re.sub(r"[^a-z0-9]", "", str(name).lower())
    return next((n for n in LABELS if n.replace("_", "") == token), None)


def _int(values, key, default=None):
    value = values.get(key, default)
    if isinstance(value, bool) or value is None or not math.isfinite(value) or value != int(value):
        raise ValueError(f"{key} requires an explicit integer")
    return int(value)


def _positive(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} requires an explicit positive value")
    return float(value)


def apply(template, values, loop, stages, sizing, devices, nets, exprs,
          phase_devices, cap_length):
    folded = _int(values, "ota1_folded_cascode", 0)
    chop = _int(values, "ota1_chopper", 0)
    remove_cc = _int(values, "ota1_folded_remove_cc", 0)
    if folded not in (0, 1) or chop not in (0, 1):
        raise ValueError("OTA1 template selectors must be 0 or 1")
    if remove_cc not in (0, 1) or (remove_cc and not folded):
        raise ValueError("ota1_folded_remove_cc=1 requires the single-stage folded cell")
    if not folded and not chop and "ota1_cc_ff" not in values:
        return None
    if not loop or loop["family"] != "CIFF":
        raise ValueError("OTA1 options are declared for the CIFF template")
    if any(sizing.get("knobs", {}).get(k, False) for k in
           ("ota_folded_cascode_first_stage", "ota_input_drain_cascodes")):
        raise ValueError("OTA1 options cannot overlap legacy whole-cascade OTA topology selectors")
    by_name = {d["name"]: d for d in devices}
    output = stages["chain"][1]
    record = {"cell": "single_stage_folded_cascode" if folded else "two_stage_miller",
              "chopper": None, "geometry_status": "DECLARED_INPUT_ONLY_NOT_SIZED",
              "verification": "topology only; no native noise/headroom/settling qualification"}
    new = []
    def geometry(d):
        params = sizing.get("device_parameters", {}).get(d["name"], {})
        if not {"w", "l"} <= set(params):
            raise ValueError(d["name"]+": bind w/l in sizing_inputs.json.device_parameters; no geometry is synthesized")
        d["w"], d["l"] = (_positive(params[k], d["name"]+"."+k) for k in ("w", "l"))
        for k in ("m", "ng"):
            if k in params:
                d[k] = _positive(params[k], d["name"]+"."+k)
        new.append(d)
    if folded:
        # Reuse the existing folded-current cell graph, remove the second
        # stage, and expose its high-gain single-ended node as the OTA output.
        source = template["stage"][0]["folded_first_stage"]
        shared = template["folded_first_stage"]
        def rename(value):
            if isinstance(value, str):
                value = value.format(i=1)
                if value.startswith("fc_") or value.startswith(("mp_fc_", "mn_fc_", "r_fc_")):
                    return "ota1_"+value
                return output if value == "nd2_1" else value
            if isinstance(value, list):
                return [rename(x) for x in value]
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            return value
        for name, endpoints in source["rewire"].items():
            by_name[name.format(i=1)]["nets"] = rename(endpoints)
        # The removed second stage inverted the first-stage output. Swap the
        # folded input pair to retain negative gain at the SC summing node.
        by_name["mn_in1"]["nets"][1], by_name["mn_ref1"]["nets"][1] = (
            by_name["mn_ref1"]["nets"][1], by_name["mn_in1"]["nets"][1])
        removed = {n.format(i=1) for n in source["remove"]} | {"mp_o1", "mn_o1"}
        devices[:] = [d for d in devices if d["name"] not in removed]
        exprs[:] = [e for e in exprs if e["device"] not in removed]
        for d in list(source["devices"]) + list(shared["devices"]):
            geometry(rename(deepcopy(d)))
        # A single-stage OTA has no Miller second stage. Retain the existing
        # parameterized Cc as output-to-common-mode compensation, with its
        # value untouched. The owner may bind ota1_cc_ff later.
        by_name["cc1"]["nets"] = [output, "vcm"]
        by_name["cc1"]["function"] = "single-stage OTA1 output compensation; declared Cc value retained"
        record["removed_devices"] = sorted(removed)
        record["input_polarity"] = "swapped_to_preserve_inverting_summing_node"
        record["compensation"] = {"capacitor": "cc1", "connection": [output, "vcm"]}
        if remove_cc:
            devices[:] = [d for d in devices if d["name"] not in ("cc1", "rz_cc1")]
            exprs[:] = [e for e in exprs if e["device"] not in ("cc1", "rz_cc1")]
            record["compensation"] = {"capacitor": None, "miller_removed": True}
    if "ota1_cc_ff" in values:
        if remove_cc:
            raise ValueError("ota1_cc_ff conflicts with removal of OTA1 Cc")
        _positive(values["ota1_cc_ff"], "ota1_cc_ff")
        for e in exprs:
            if e["device"] == "cc1":
                e.update(expr=cap_length("ota1_cc_ff"), ff_expr="ota1_cc_ff")
        record["compensation_value_source"] = "ota1_cc_ff"
    devices.extend(new)
    new_names = [d["name"] for d in new]
    if chop:
        locations = _int(values, "ota1_chop_stages", 3 if folded else 2)
        ratio = _int(values, "ota1_chop_ratio", 2 if locations == 3 else None)
        phase = _int(values, "ota1_chop_sc_phase", 1 if locations == 3 else None)
        polarity = _int(values, "ota1_chop_polarity", 0)
        if ratio < 2 or ratio > 2**16 or ratio & (ratio-1) or phase not in (1, 2) or polarity not in (0, 1):
            raise ValueError("chop ratio must be a power of two in [2,65536], SC phase 1/2, polarity 0/1")
        if locations not in (2, 3) or (locations == 3 and (not folded or ratio != 2 or phase != 1)):
            raise ValueError("three-location chopping requires the folded cell, fs/2 ratio=2 and start-of-phi1 phase=1")
        wn, wp, length = [_positive(values.get(k), k) for k in
                          ("ota1_chop_nmos_w_um", "ota1_chop_pmos_w_um", "ota1_chop_l_um")]
        # Reuse the conversion counter's static TG divider cells, clocked
        # from the DECLARED SC phase rather than a second free-running clock.
        count = ratio.bit_length()-1
        counter = template["stage"][1]
        divider_source = f"nph{phase}"
        if locations == 3:
            divider_source = "ota1_ch_clk"
            # Conversion-resettable glitch-free clock gate. Release is held
            # while phi1 is high, so an asynchronous reset release cannot
            # create a partial chopping edge in phi2.
            def mos(name, role, drain, gate, source, width):
                devices.append({"name": name, "role": role, "function": "conversion-synchronous chopper reset",
                    "nets": [drain, gate, source, "vss" if role == "nmos" else "vdd"], "w": width, "l": length})
            def inv(name, out, inp):
                mos("mn_"+name, "nmos", out, inp, "vss", wn)
                mos("mp_"+name, "pmos", out, inp, "vdd", wp)
            mos("mn_ota1_ch_run_tg", "nmos", "ota1_ch_run", "nph1b", "nrstb", wn)
            mos("mp_ota1_ch_run_tg", "pmos", "ota1_ch_run", "nph1", "nrstb", wp)
            inv("ota1_ch_runb", "ota1_ch_runb", "ota1_ch_run")
            # Retain a standard divider keeper's reference geometry; no
            # keeper strength or transistor size is synthesized here.
            for original in counter["devices"]:
                if original["name"] not in ("mp_mkp{i}", "mn_mkp{i}"):
                    continue
                d = deepcopy(original)
                d["name"] = "ota1_ch_run_"+original["name"].format(i=1)
                d["nets"] = ["ota1_ch_run", "ota1_ch_runb", "vdd" if d["role"] == "pmos" else "vss", "vdd" if d["role"] == "pmos" else "vss"]
                devices.append(d)
            mos("mn_ota1_ch_run_reset", "nmos", "ota1_ch_run", "nall", "vss", wn)
            mos("mp_ota1_ch_gate1", "pmos", "ota1_ch_clkb", "nph1", "vdd", wp)
            mos("mp_ota1_ch_gate2", "pmos", "ota1_ch_clkb", "ota1_ch_run", "vdd", wp)
            mos("mn_ota1_ch_gate1", "nmos", "ota1_ch_clkb", "nph1", "ota1_ch_gates", wn)
            mos("mn_ota1_ch_gate2", "nmos", "ota1_ch_gates", "ota1_ch_run", "vss", wn)
            inv("ota1_ch_clk", "ota1_ch_clk", "ota1_ch_clkb")
        for i in range(1, count+1):
            sub = {"i": i, "i1": i+1,
                   "in": divider_source if i == 1 else f"ota1_ch_q{i-1}",
                   "out": f"ota1_ch_q{i}"}
            for original in counter["devices"]:
                # The AND-accumulator belongs to the conversion window, not
                # to a frequency divider. No unused accumulator is emitted.
                if any("{in2}" in n or "{out2}" in n for n in original["nets"]) or "nand" in original["name"] or "andinv" in original["name"]:
                    continue
                if locations == 3 and original["name"] in ("mp_cki{i}", "mn_cki{i}"):
                    continue
                d = deepcopy(original)
                d["name"] = "ota1_ch_"+original["name"].format(**sub)
                d["nets"] = [n.format(**sub) if "{" in n else
                             ("ota1_ch_"+n if n not in ("vdd", "vss") else n)
                             for n in original["nets"]]
                # Internal node templates must receive the same namespace.
                d["nets"] = ["ota1_ch_"+n if n not in ("vdd", "vss") and
                             not n.startswith(("ota1_ch_", "nph")) else n for n in d["nets"]]
                if locations == 3:
                    # A plain clock/complement TG divider can race through
                    # both latches on an edge. The adopted fs/2 cell uses
                    # the existing NON-OVERLAPPING SC phases: master in
                    # phi2, slave at the next gated phi1, held through phi2.
                    gates = {"mn_mtg{i}": "nph2", "mp_mtg{i}": "nph2b",
                             "mn_stg{i}": divider_source, "mp_stg{i}": "ota1_ch_clkb"}
                    if original["name"] in gates:
                        d["nets"][1] = gates[original["name"]]
                devices.append(d)
            if locations == 3:
                for storage in ("nm", "ns"):
                    mos(f"mp_ota1_ch_clear_{storage}{i}", "pmos", f"ota1_ch_{storage}{i}", "nrstb", "vdd", wp)
        declaration = deepcopy(template["clock_phase_generator"])
        declaration.update(source=f"ota1_ch_q{count}", complement=f"ota1_ch_nqb{count}",
            phases={"ota1_ch_p": {"complement_net": "ota1_ch_pb"},
                    "ota1_ch_n": {"complement_net": "ota1_ch_nb"}})
        generated = phase_devices(declaration)
        # Generator instance names are normally shared by one block. Give
        # this second generator a distinct namespace as well as distinct nets.
        for d in generated:
            d["name"] = "ota1_"+d["name"]
            external = {declaration["source"], declaration["complement"], "vdd", "vss",
                        "ota1_ch_p", "ota1_ch_pb", "ota1_ch_n", "ota1_ch_nb"}
            d["nets"] = [n if n in external else "ota1_ch_"+n for n in d["nets"]]
        devices.extend(generated)
        positive = ("ota1_ch_p", "ota1_ch_pb")
        negative = ("ota1_ch_n", "ota1_ch_nb")
        if polarity:
            positive, negative = negative, positive
        def tg(name, left, right, gates):
            for role, gate, body, width, prefix in (
                ("nmos", gates[0], "vss", wn, "mn_"), ("pmos", gates[1], "vdd", wp, "mp_")):
                devices.append({"name": prefix+"ota1_ch_"+name, "role": role,
                    "function": "OTA1 internal chopper transmission gate; explicitly bound switch dimensions",
                    "nets": [left, gate, right, body], "w": width, "l": length})
        by_name = {d["name"]: d for d in devices}
        input_pair = [by_name["mn_in1"], by_name["mn_ref1"]]
        original_gates = [d["nets"][1] for d in input_pair]
        for i, d in enumerate(input_pair, 1):
            d["nets"][1] = f"ota1_ch_g{i}"
        for i in range(2):
            tg(f"in{i+1}p", f"ota1_ch_g{i+1}", original_gates[i], positive)
            tg(f"in{i+1}n", f"ota1_ch_g{i+1}", original_gates[1-i], negative)
        if folded:
            outputs = [d["nets"][0] for d in input_pair]
            for i, suffix in enumerate(("in1", "ref1"), 1):
                # Bias currents stay on the input-pair side of the switch;
                # demodulated currents enter the folding cascode SOURCES.
                by_name["ota1_mp_fc_top_"+suffix]["nets"][0] = f"ota1_ch_raw{i}"
        else:
            outputs = [f"ota1_ch_cas_s{i}" for i in (1, 2)]
            for i, d in enumerate(input_pair, 1):
                # Common-gate current conveyors put the demodulator at LOW
                # impedance, ahead of the existing PMOS mirror. Geometry is
                # inherited from the input device, never sized here.
                cascode = {k: d[k] for k in ("w", "l", "m", "ng") if k in d}
                cascode.update(name=f"mn_ota1_ch_cas{i}", role="nmos",
                    function="low-impedance current demodulation cascode; inherited reference geometry",
                    nets=[d["nets"][0], "ota1_ch_cas_bias", outputs[i-1], "vss"])
                devices.append(cascode)
            for name, endpoints in (("r_ota1_ch_top", ["vdd", "ota1_ch_cas_bias", "vss"]),
                                    ("r_ota1_ch_bottom", ["ota1_ch_cas_bias", "vcm", "vss"])):
                d = {"name": name, "role": "res", "function": "physical chopper cascode bias divider",
                     "nets": endpoints}
                geometry(d)
                devices.append(new[-1])
                new_names.append(name)
        for i, d in enumerate(input_pair, 1):
            d["nets"][0] = f"ota1_ch_raw{i}"
        for i in range(2):
            tg(f"out{i+1}p", f"ota1_ch_raw{i+1}", outputs[i], positive)
            tg(f"out{i+1}n", f"ota1_ch_raw{i+1}", outputs[1-i], negative)
        switch_locations = {"CH1": {"kind": "input_pair", "nodes": original_gates},
                            "CH2": {"kind": "folding_cascode_sources" if folded else "common_gate_sources_before_mirror", "nodes": outputs}}
        if locations == 3:
            mirror_nodes = []
            for i, suffix in enumerate(("in1", "ref1"), 1):
                load = by_name["ota1_mn_fc_load_"+suffix]
                mirror_nodes.append(load["nets"][0])
                load["nets"][0] = f"ota1_ch_mraw{i}"
            for i in range(2):
                tg(f"mirror{i+1}p", f"ota1_ch_mraw{i+1}", mirror_nodes[i], positive)
                tg(f"mirror{i+1}n", f"ota1_ch_mraw{i+1}", mirror_nodes[1-i], negative)
            switch_locations["CH3"] = {"kind": "nmos_current_mirror", "nodes": mirror_nodes}
        record["chopper"] = {"enabled": True, "ratio": ratio, "source_phase": f"nph{phase}",
            "polarity": polarity, "clock_net": f"ota1_ch_q{count}",
            "positive_phase": positive[0], "negative_phase": negative[0],
            "switch_geometry_um": {"nmos_w": wn, "pmos_w": wp, "l": length},
            "input_nodes": original_gates, "demodulation_nodes": outputs,
            "location": "folding_cascode_sources" if folded else "common_gate_sources_before_mirror",
            "output_interface": "single_ended", "second_stage_retained": not bool(folded),
            "switch_locations": switch_locations, "stages": locations}
        if locations == 3:
            record["chopper"].update(update_event="start_of_phi1", static_phase="nph2",
                reset_net="nall", divider_clock_net=divider_source,
                conversion_start_phase="positive" if polarity == 0 else "negative")
    record["explicit_geometry_devices"] = new_names
    nets[:] = sorted({n for d in devices for n in d["nets"]} - set(template["ports"]))
    return record
