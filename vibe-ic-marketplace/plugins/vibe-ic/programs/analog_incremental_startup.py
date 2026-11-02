"""Physical conversion boundaries shared by incremental CIFF and CIFB loops."""
from collections import defaultdict


class _Cells:
    def __init__(self, devices):
        self.devices = devices
        self.names = {d["name"] for d in devices}

    def mos(self, name, role, drain, gate, source, width=None, length=.5):
        if name in self.names:
            raise ValueError(f"INCREMENTAL_STARTUP_DEVICE: duplicate device {name}")
        self.names.add(name)
        body = "vss" if role == "nmos" else "vdd"
        self.devices.append({"name": name, "role": role,
            "function": "incremental conversion control",
            "nets": [drain, gate, source, body],
            "w": width if width is not None else (2. if role == "nmos" else 4.),
            "l": length})

    def inv(self, tag, output, source, weak=False):
        for role, rail, width in (("nmos", "vss", .5 if weak else 2.),
                                  ("pmos", "vdd", 1. if weak else 4.)):
            self.mos(("mn_" if role == "nmos" else "mp_")+tag,
                     role, output, source, rail, width)

    def nand(self, tag, output, a, b):
        mid = "n_"+tag+"_series"
        self.mos("mp_"+tag+"_a", "pmos", output, a, "vdd")
        self.mos("mp_"+tag+"_b", "pmos", output, b, "vdd")
        self.mos("mn_"+tag+"_a", "nmos", output, a, mid)
        self.mos("mn_"+tag+"_b", "nmos", mid, b, "vss")

    def nor(self, tag, output, a, b):
        mid = "n_"+tag+"_series"
        self.mos("mp_"+tag+"_a", "pmos", mid, a, "vdd")
        self.mos("mp_"+tag+"_b", "pmos", output, b, mid)
        self.mos("mn_"+tag+"_a", "nmos", output, a, "vss")
        self.mos("mn_"+tag+"_b", "nmos", output, b, "vss")

    def and_(self, tag, output, a, b):
        complement = "n_"+tag+"_bar"
        self.nand(tag, complement, a, b)
        self.inv(tag+"_out", output, complement)

    def or_(self, tag, output, a, b):
        complement = "n_"+tag+"_bar"
        self.nor(tag, complement, a, b)
        self.inv(tag+"_out", output, complement)

    def tg(self, tag, left, right, enable, complement):
        self.mos("mn_"+tag, "nmos", left, enable, right, 2., .15)
        self.mos("mp_"+tag, "pmos", left, complement, right, 4., .15)

    def latch(self, tag, output, data):
        self.tg(tag+"_sample", output, data, "nph1", "nph1b")
        self.inv(tag+"_bar", output+"b", output)
        self.inv(tag+"_keeper", output, output+"b", weak=True)
        self.mos("mn_"+tag+"_reset", "nmos", output, "nall", "vss", 4.)


def _charge_paths(devices, stages):
    """Find capacitors whose plates reach a resettable integrator through a TG."""
    pairs = defaultdict(dict)
    caps = [d for d in devices if d["role"] == "cap"]
    for d in devices:
        if d["role"] in ("nmos", "pmos"):
            ends = frozenset((d["nets"][0], d["nets"][2]))
            pairs[ends].setdefault(d["role"], []).append(d)
    tgs = {}
    for ends, roles in pairs.items():
        if len(roles.get("nmos", [])) == len(roles.get("pmos", [])) == 1:
            tgs[ends] = (roles["nmos"][0], roles["pmos"][0])
    summing = set()
    outputs = set(stages.get("chain", [])[1:])
    for group in stages.get("groups", []):
        if group.get("role") == "cascade":
            outputs.update(group.get("chain", [])[1:])
    if not outputs:
        raise ValueError("INCREMENTAL_STARTUP_PATH: no declared integrator state outputs")
    for cap in caps:
        pair = tgs.get(frozenset(cap["nets"]))
        if pair and pair[0]["nets"][1] == "nall":
            if len(set(cap["nets"]) & outputs) == 1:
                summing.update(set(cap["nets"]) - outputs)
    paths = []
    for cap in caps:
        if set(cap["nets"]) & summing:
            continue
        transfers = []
        for plate in cap["nets"]:
            for destination in summing:
                pair = tgs.get(frozenset((plate, destination)))
                if pair and pair[0]["nets"][1] != "nall":
                    transfers.append((plate, destination, pair))
        if not transfers:
            continue
        if len(transfers) != 1:
            raise ValueError(f"INCREMENTAL_STARTUP_PATH: {cap['name']} has ambiguous integrator transfers")
        top, destination, transfer = transfers[0]
        bottom = next(n for n in cap["nets"] if n != top)
        references = [pair for ends, pair in tgs.items()
                      if bottom in ends and ends & {"ndac", "ndacb"}]
        if len(references) > 1:
            raise ValueError(f"INCREMENTAL_STARTUP_PATH: {cap['name']} has ambiguous DAC selection")
        reference = references[0] if references else None
        kind = ("dac" if reference and reference[0]["nets"][1] == "nckdac"
                else "dac_shared" if reference else "input_or_state")
        paths.append((cap, destination, transfer, reference, kind))
    if not paths:
        raise ValueError("INCREMENTAL_STARTUP_PATH: no integrator sampling paths found")
    return paths


def realize(lib, values, stages, devices, nets, startup=None):
    """Emit one controller after all loop and OTA specialization, before sizing.

    The existing raw-POR helper owns only power detection and counter startup.
    This owner controls the reset edge, decisions and every SC update path.
    A retained delay-chain level cannot start evaluation in non-overlap dead
    time. D1 summer clearing follows the qualified evaluation edge so the
    held sum remains available until the comparator has actually started.
    """
    groups = (stages or {}).get("groups", [])
    counter = next((g for g in groups if g.get("role") == "conversion_window_counter"), None)
    if counter is None:
        return None
    if startup:
        # The raw POR helper retains its published implementation. This owner
        # replaces its final OR so bootstrap and the phi1 slave own release.
        legacy_or = {"mp_por_or1", "mp_por_or2", "mn_por_or1", "mn_por_or2",
                     "mp_por_or", "mn_por_or"}
        devices[:] = [d for d in devices if d["name"] not in legacy_or]
    for d in devices:
        d["nets"] = list(d["nets"])
    before = {d["name"]: tuple(d["nets"]) for d in devices}
    by_name = {d["name"]: d for d in devices}
    paths = _charge_paths(devices, stages)
    mode = int(lib.get("sc_loop", {}).get("D", 1))
    cells = _Cells(devices)
    window = "nwindow_reset" if startup else "nall"
    slave = "nreset_slave"
    cells.tg("conversion_reset_slave", "nrmb", slave,
             "npor_clk" if startup else "clk", "npor_ckb" if startup else "nclkb")
    for name in ("mn_rout", "mp_rout"):
        by_name[name]["nets"][:2] = [window, slave]
    cells.inv("conversion_reset_keeper", slave, window, weak=True)
    bootstrap = None
    if startup:
        cells.mos("mp_conversion_reset_por", "pmos", slave, "npor_run", "vdd", 8.)
        bootstrap = "nconversion_boot"
        cells.and_("conversion_boot_clear", "nconversion_boot_clear", window, "npor_run")
        cells.nor("conversion_boot", bootstrap, "nconversion_boot_clear", bootstrap+"b")
        cells.nor("conversion_bootb", bootstrap+"b", "npor_runb", bootstrap)
        cells.or_("conversion_window_boot", "nconversion_reset_pending", window, bootstrap)
        cells.or_("conversion_reset", "nall", "nconversion_reset_pending", "npor_runb")
        startup.update(reset_net="nall", window_reset_net=window,
                       clears=["window_counter", "all_integrators"])

    for phase in (1, 2):
        p = by_name[f"mp_no{phase}b"]
        output = p["nets"][0]
        middle = f"nconversion_phase{phase}_series"
        p["nets"][0] = middle
        cells.mos(f"mp_no{phase}_reset", "pmos", output, "nall", middle, p["w"], p["l"])
        n = by_name[f"mn_no{phase}a"]
        cells.mos(f"mn_no{phase}_reset", "nmos", output, "nall", "vss", n["w"], n["l"])

    cells.and_("conversion_qeval", "nqeval_run", "nqstb", "nrstb")
    cells.and_("conversion_qeval_phase", "nqeval", "nqeval_run",
               "nph1" if mode == 0 else "nph2")
    if mode and lib.get("sc_loop"):
        for name in ("mn_sumrb", "mp_sumrb"):
            by_name[name]["nets"][1] = "nqeval"
    for name in ("mn_qtail", "mp_qrst1", "mp_qrst2", "mp_qrsti1", "mp_qrsti2"):
        by_name[name]["nets"][1] = "nqeval"
    cells.or_("conversion_setb", "nq_setb", "nq_n", "nall")
    cells.and_("conversion_resetb", "nq_resetb", "nq_p", "nrstb")
    for prefix in ("mn_", "mp_"):
        by_name[prefix+"n1a"]["nets"][1] = "nq_setb"
        by_name[prefix+"n2a"]["nets"][1] = "nq_resetb"

    cells.nand("conversion_xor1", "nq_xor1", "nq_p", "nq_n")
    cells.nand("conversion_xor2", "nq_xor2", "nq_p", "nq_xor1")
    cells.nand("conversion_xor3", "nq_xor3", "nq_n", "nq_xor1")
    cells.nand("conversion_xor4", "nq_resolved", "nq_xor2", "nq_xor3")
    cells.and_("conversion_resolution", "nq_resolution", "nq_resolved", "nqeval")
    cells.and_("conversion_valid_phase", "nq_valid_phase", "nq_resolution", "nph1" if mode == 0 else "nph2")
    valid = "ndecision_valid"
    cells.nor("conversion_valid", valid, "nall", valid+"b")
    cells.nor("conversion_validb", valid+"b", "nq_valid_phase", valid)
    ready = "ntransfer_ready"
    cells.latch("conversion_ready", ready, valid if mode == 0 else "nrstb")
    feedback_ready = ready
    if mode:
        feedback_ready = "nfeedback_ready"
        cells.latch("conversion_feedback_ready", feedback_ready, valid)
    cells.and_("conversion_transfer_run", "ntransfer_run", ready, "nrstb")
    cells.and_("conversion_transfer", "ntransfer", "nph2", "ntransfer_run")
    cells.inv("conversion_transferb", "ntransferb", "ntransfer")
    feedback_transfer, feedback_transfer_b = "ntransfer", "ntransferb"
    if mode:
        cells.and_("conversion_feedback_run", "nfeedback_run", feedback_ready, "nrstb")
        cells.and_("conversion_feedback_transfer", "nfeedback_transfer", "nph2", "nfeedback_run")
        cells.inv("conversion_feedback_transferb", "nfeedback_transferb", "nfeedback_transfer")
        feedback_transfer, feedback_transfer_b = "nfeedback_transfer", "nfeedback_transferb"

    cells.and_("conversion_dac_sample", "ndac_sample_valid", valid, "nrstb")
    for name in ("mn_ndac2", "mp_ndac2"):
        by_name[name]["nets"][1] = "ndac_sample_valid"

    records = []
    cleared = set()
    for cap, destination, transfer, reference, kind in paths:
        gates = ((feedback_transfer, feedback_transfer_b) if kind == "dac"
                 else ("ntransfer", "ntransferb"))
        for d, gate in zip(transfer, gates):
            if d["nets"][1] not in ("nph2", "nph2b"):
                raise ValueError(f"INCREMENTAL_STARTUP_PATH: unsupported transfer phase on {d['name']}")
            d["nets"][1] = gate
        if kind == "dac_shared":
            for d, gate in zip(reference, gates):
                if d["nets"][1] not in ("nph2", "nph2b"):
                    raise ValueError(f"INCREMENTAL_STARTUP_PATH: unsupported shared transfer on {d['name']}")
                d["nets"][1] = gate
        clear_names = []
        for plate in cap["nets"]:
            if plate in cleared:
                continue
            tag = "conversion_clear_"+plate
            cells.tg(tag, plate, "vcm", "nall", "nrstb")
            clear_names.extend(("mn_"+tag, "mp_"+tag))
            cleared.add(plate)
        records.append({"capacitor": cap["name"], "plates": list(cap["nets"]),
                        "summing_node": destination, "kind": kind,
                        "transfer_devices": [d["name"] for d in transfer],
                        "transfer_net": gates[0], "transfer_bar_net": gates[1],
                        "reset_devices": clear_names})

    if lib.get("sc_loop") and mode == 0:
        cells.or_("conversion_summer_prepare", "nsummer_prepare", "nall", "nph2")
        cells.inv("conversion_summer_prepareb", "nsummer_prepareb", "nsummer_prepare")
        for d in devices:
            if d["name"].startswith(("mn_ff", "mp_ff", "mn_sum_reset", "mp_sum_reset")):
                if d["nets"][1] == "nph2":
                    d["nets"][1] = "nsummer_prepare"
                elif d["nets"][1] == "nph2b":
                    d["nets"][1] = "nsummer_prepareb"
    elif lib.get("sc_loop"):
        cells.tg("conversion_sum_clear", "nsum", "vcm", "nall", "nrstb")
        if "cffk0" in by_name:
            bottom = next(n for n in by_name["cffk0"]["nets"] if n != "nsum")
            for prefix in ("mn_", "mp_"):
                name = prefix+"ffk0"
                if name not in by_name:
                    continue
                gate = by_name[name]["nets"][1]
                if prefix == "mn_":
                    cells.and_("conversion_k0_sample", "nk0_sample", gate, valid)
                    cells.inv("conversion_k0_sampleb", "nk0_sampleb", "nk0_sample")
                by_name[name]["nets"][1] = "nk0_sample" if prefix == "mn_" else "nk0_sampleb"
            cells.tg("conversion_k0_neutral", bottom, "vcm", valid+"b", valid)

    nets[:] = sorted({n for d in devices for n in d["nets"]} - set(lib["ports"]))
    return {"reset_net": "nall", "reset_bar_net": "nrstb", "window_reset_net": window,
            "bootstrap_net": bootstrap, "decision_valid_net": valid,
            "transfer_ready_net": ready, "feedback_ready_net": feedback_ready,
            "transfer_net": "ntransfer", "transfer_bar_net": "ntransferb", "mode": mode,
            "active_transfers": counter["window_clocks"]-1, "first_weight_index": 0,
            "initial_feedback": "zero_pipeline" if mode else "fresh_current_decision",
            "paths": records,
            "control_devices": [d["name"] for d in devices
                                if before.get(d["name"]) != tuple(d["nets"])],
            "verification": "physical control emitted; native timing verification required"}
