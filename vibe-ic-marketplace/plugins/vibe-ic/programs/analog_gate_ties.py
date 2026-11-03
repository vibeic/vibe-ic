"""Antenna ties for nets that reach gates and capacitor plates but no diffusion.

Such a net has nothing to discharge through while the metal above it is etched, so
the deck's limit without a protection diode applies to all of its plate and wire.
A spec row names the net and sizes an off device whose drain gives it diffusion.
The tie's own gate sits on the low rail, so the native antenna deck judges its size.
"""
import math

FIELD = "antenna_tie"
SPEC_INVALID = "ANTENNA_TIE_SPEC_INVALID"


class TieRefused(ValueError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


def _positive(row, key):
    value = row.get(key)
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value <= 0):
        raise TieRefused(SPEC_INVALID, f"{FIELD} {key} must be a positive number, got {value!r}")
    return float(value)


def declared(spec):
    """[(net, w_um, l_um)] from the spec's rows."""
    rows = spec.get("specs") if isinstance(spec, dict) else None
    rows = [r for r in rows if isinstance(r, dict) and r.get("name") == FIELD] if isinstance(rows, list) else []
    ties = []
    for row in rows:
        net = row.get("net")
        if not isinstance(net, str) or not net:
            raise TieRefused(SPEC_INVALID, f"{FIELD} needs a net name, got {net!r}")
        ties.append((net, _positive(row, "w_um"), _positive(row, "l_um")))
    if len({net for net, _, _ in ties}) != len(ties):
        raise TieRefused(SPEC_INVALID, f"{FIELD} names a net twice: {sorted(n for n, _, _ in ties)}")
    return ties


def apply(ir, ties):
    """The IR with one off device per declared net."""
    low = ir["rails"]["vss"]
    known = {net for device in ir["devices"] for net in device["nets"]}
    devices = list(ir["devices"])
    for net, width, length in ties:
        if net not in known:
            raise TieRefused(SPEC_INVALID, f"{FIELD} net {net!r} is not in this block")
        devices.append({"name": f"mn_tie_{net}", "role": "nmos", "w": width, "l": length,
                        "function": f"antenna tie: off device whose drain gives {net} diffusion",
                        "nets": [net, low, low, low]})
    return {**ir, "devices": devices} if ties else ir
