"""Tie devices for gates that would otherwise sit on a supply rail.

A gate wired straight to a rail collects the rail's whole metal for its antenna
ratio. When the block's spec declares `gate_tie_w_um` and `gate_tie_l_um`, those
gates take the output of a tie pair instead, the same two-device form a standard
cell tie uses: the diode-connected device's own gate stays off the rail. The
native antenna deck judges the declared size.
"""
import math

FIELDS = ("gate_tie_w_um", "gate_tie_l_um")
SPEC_INVALID = "GATE_TIE_SPEC_INVALID"
_VALUE_KEYS = ("target", "typ", "value", "min", "max")


class TieRefused(ValueError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


def declared_size(spec):
    """(w, l) in um, or None when the spec declares no tie."""
    rows = spec.get("specs") if isinstance(spec, dict) else None
    rows = [r for r in rows if isinstance(r, dict) and r.get("name") in FIELDS] if isinstance(rows, list) else []
    if not rows:
        return None
    values = {}
    for row in rows:
        value = next((row[key] for key in _VALUE_KEYS if key in row), None)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or value <= 0 or row["name"] in values):
            raise TieRefused(SPEC_INVALID, f"{row['name']} must be one positive number, got {value!r}")
        values[row["name"]] = float(value)
    if set(values) != set(FIELDS):
        raise TieRefused(SPEC_INVALID, f"a gate tie declares both of {FIELDS}, got {sorted(values)}")
    return values[FIELDS[0]], values[FIELDS[1]]


def apply(ir, width, length):
    """The IR with rail gates on tie nets, and the tie pairs that drive them."""
    high, low = ir["rails"]["vdd"], ir["rails"]["vss"]
    devices = []
    used = set()
    for device in ir["devices"]:
        if device.get("role") in ("nmos", "pmos") and device["nets"][1] in (high, low):
            net = "ntie_hi" if device["nets"][1] == high else "ntie_lo"
            used.add(net)
            device = {**device, "nets": [device["nets"][0], net, *device["nets"][2:]]}
        devices.append(device)
    if not used:
        return ir
    def pair(role_diode, name_diode, rail_diode, role_out, name_out, rail_out, inner, out):
        return [
            {"name": name_diode, "role": role_diode, "w": width, "l": length,
             "function": "gate tie: diode-connected device that biases the tie's output device",
             "nets": [inner, inner, rail_diode, rail_diode]},
            {"name": name_out, "role": role_out, "w": width, "l": length,
             "function": "gate tie: output device, so tied gates stay off the supply rail metal",
             "nets": [out, inner, rail_out, rail_out]}]
    nets = list(ir.get("internal_nets") or [])
    if "ntie_hi" in used:
        devices += pair("nmos", "mn_tie_hi_bias", low, "pmos", "mp_tie_hi", high, "ntie_hi_bias", "ntie_hi")
        nets += ["ntie_hi", "ntie_hi_bias"]
    if "ntie_lo" in used:
        devices += pair("pmos", "mp_tie_lo_bias", high, "nmos", "mn_tie_lo", low, "ntie_lo_bias", "ntie_lo")
        nets += ["ntie_lo", "ntie_lo_bias"]
    return {**ir, "devices": devices, "internal_nets": nets}
