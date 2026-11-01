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
          "ota1_chop_pmos_w_um", "ota1_chop_l_um", "ota1_cc_ff")


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
    if folded not in (0, 1) or chop not in (0, 1):
        raise ValueError("OTA1 template selectors must be 0 or 1")
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
    if "ota1_cc_ff" in values:
        _positive(values["ota1_cc_ff"], "ota1_cc_ff")
        for e in exprs:
            if e["device"] == "cc1":
                e.update(expr=cap_length("ota1_cc_ff"), ff_expr="ota1_cc_ff")
        record["compensation_value_source"] = "ota1_cc_ff"
    devices.extend(new)
    new_names = [d["name"] for d in new]
    if chop:
        ratio = _int(values, "ota1_chop_ratio")
        phase = _int(values, "ota1_chop_sc_phase")
        polarity = _int(values, "ota1_chop_polarity", 0)
        if ratio < 2 or ratio > 2**16 or ratio & (ratio-1) or phase not in (1, 2) or polarity not in (0, 1):
            raise ValueError("chop ratio must be a power of two in [2,65536], SC phase 1/2, polarity 0/1")
        wn, wp, length = [_positive(values.get(k), k) for k in
                          ("ota1_chop_nmos_w_um", "ota1_chop_pmos_w_um", "ota1_chop_l_um")]
        # Reuse the conversion counter's static TG divider cells, clocked
        # from the DECLARED SC phase rather than a second free-running clock.
        count = ratio.bit_length()-1
        counter = template["stage"][1]
        for i in range(1, count+1):
            sub = {"i": i, "i1": i+1,
                   "in": f"nph{phase}" if i == 1 else f"ota1_ch_q{i-1}",
                   "out": f"ota1_ch_q{i}"}
            for original in counter["devices"]:
                # The AND-accumulator belongs to the conversion window, not
                # to a frequency divider. No unused accumulator is emitted.
                if any("{in2}" in n or "{out2}" in n for n in original["nets"]) or "nand" in original["name"] or "andinv" in original["name"]:
                    continue
                d = deepcopy(original)
                d["name"] = "ota1_ch_"+original["name"].format(**sub)
                d["nets"] = [n.format(**sub) if "{" in n else
                             ("ota1_ch_"+n if n not in ("vdd", "vss") else n)
                             for n in original["nets"]]
                # Internal node templates must receive the same namespace.
                d["nets"] = ["ota1_ch_"+n if n not in ("vdd", "vss") and
                             not n.startswith(("ota1_ch_", "nph")) else n for n in d["nets"]]
                devices.append(d)
        declaration = deepcopy(template["clock_phase_generator"])
        declaration.update(source=f"ota1_ch_q{count}", complement=f"ota1_ch_nqb{count}",
            phases={"ota1_ch_p": {"complement_net": "ota1_ch_pb"},
                    "ota1_ch_n": {"complement_net": "ota1_ch_nb"}})
        generated = phase_devices(declaration)
        # Generator instance names are normally shared by one block. Give
        # this second generator a distinct namespace as well as distinct nets.
        for d in generated:
            d["name"] = "ota1_"+d["name"]
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
        record["chopper"] = {"enabled": True, "ratio": ratio, "source_phase": f"nph{phase}",
            "polarity": polarity, "clock_net": f"ota1_ch_q{count}",
            "positive_phase": positive[0], "negative_phase": negative[0],
            "switch_geometry_um": {"nmos_w": wn, "pmos_w": wp, "l": length},
            "input_nodes": original_gates, "demodulation_nodes": outputs,
            "location": "folding_cascode_sources" if folded else "common_gate_sources_before_mirror",
            "output_interface": "single_ended", "second_stage_retained": not bool(folded)}
    record["explicit_geometry_devices"] = new_names
    nets[:] = sorted({n for d in devices for n in d["nets"]} - set(template["ports"]))
    return record
