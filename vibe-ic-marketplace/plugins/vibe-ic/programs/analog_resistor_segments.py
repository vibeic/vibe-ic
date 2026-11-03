"""Series segmentation of long resistors from a declared maximum segment length.

A straight resistor as long as a row is what stretches a block's layout, and the
gencell's own serpentine does not extract. A declared
`max_resistor_segment_um` replaces each longer resistor with equal series
segments whose total resistance, contacts included, stays the original value.
The IR stays flat: A3 renders the segments like any other devices. The record
keeps each original device so that a check written against the unsegmented
graph reads `without_segments`, not a second description of that graph.
"""
import math

FIELD = "max_resistor_segment_um"
RECORD_KEY = "resistor_segments"
SPEC_INVALID = "RESISTOR_SEGMENT_SPEC_INVALID"
CONSTANTS_MISSING = "RESISTOR_SEGMENT_CONSTANTS_MISSING"
NOT_REALISABLE = "RESISTOR_SEGMENT_NOT_REALISABLE"
_MICROMETRE = {"um", "µm", "μm"}
_VALUE_KEYS = ("target", "typ", "value", "min", "max")


class SegmentRefused(ValueError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def declared_max_um(spec):
    """The declared maximum in um, or None when the spec has no such row."""
    rows = spec.get("specs") if isinstance(spec, dict) else None
    rows = [r for r in rows if isinstance(r, dict) and r.get("name") == FIELD] if isinstance(rows, list) else []
    if not rows:
        return None
    if len(rows) > 1:
        raise SegmentRefused(SPEC_INVALID, f"duplicate {FIELD} rows")
    row = rows[0]
    value = next((row[key] for key in _VALUE_KEYS if key in row), None)
    if not _is_number(value) or value <= 0:
        raise SegmentRefused(SPEC_INVALID, f"{FIELD} must be a positive finite number, got {value!r}")
    if str(row.get("unit") or "").strip().lower() not in _MICROMETRE:
        raise SegmentRefused(SPEC_INVALID, f"{FIELD} must be declared in um, got {row.get('unit')!r}")
    return float(value)


def _segment_count(length, maximum, added_length):
    count = math.ceil(length / maximum)
    while (length - (count - 1) * added_length) / count > maximum:
        count += 1
    return count


def _resolved_length(device, rows, env, safe_eval):
    """The length A3 renders: the last `l` expression that resolves, else the record's."""
    length = device.get("l")
    for row in rows:
        if row.get("param") != "l":
            continue
        try:
            length = safe_eval(row["expr"], dict(env))
        except Exception:
            continue
    return float(length) if _is_number(length) else None


def _chain_devices(parent):
    device = parent["device"]
    ends = [device["nets"][0], *parent["nets"], device["nets"][1]]
    return [dict(device, name=member, l=parent["segment_l_um"],
                 nets=[ends[i], ends[i + 1], *device["nets"][2:]])
            for i, member in enumerate(parent["segments"])]


def _segment_rows(row, parent):
    count = parent["count"]
    expr = row["expr"]
    if row.get("param") == "l":
        expr = f"(({expr}) - {count - 1} * 2 * r_end_ohm / r_per_um_ohm) / {count}"
    return [dict(row, device=member, expr=expr) for member in parent["segments"]]


def apply(ir, maximum, env, safe_eval, min_length_um=None):
    """Return `ir` with every longer resistor replaced by its series chain."""
    measured = ir.get("pdk_measured_params") or {}
    r_end, r_per_um = measured.get("r_end_ohm"), measured.get("r_per_um_ohm")
    if not _is_number(r_end) or not _is_number(r_per_um) or r_per_um <= 0:
        raise SegmentRefused(CONSTANTS_MISSING,
                             f"{FIELD} is declared but this PDK's measured r_end_ohm/r_per_um_ohm "
                             f"are {r_end!r}/{r_per_um!r}, so contact resistance cannot be preserved")
    added_length = 2 * r_end / r_per_um
    taken = {d["name"] for d in ir["devices"]} | set(ir.get("internal_nets") or []) | set(ir.get("ports") or [])
    devices, nets, parents, replaced_rows = [], list(ir.get("internal_nets") or []), [], {}
    all_rows = ir.get("device_param_exprs") or []
    for device in ir["devices"]:
        name = device["name"]
        rows = [r for r in all_rows if r.get("device") == name]
        length = _resolved_length(device, rows, env, safe_eval) if device.get("role") == "res" else None
        if length is None or length <= maximum:
            devices.append(device)
            continue
        count = _segment_count(length, maximum, added_length)
        each = (length - (count - 1) * added_length) / count
        if each <= 0 or (min_length_um is not None and each < min_length_um):
            raise SegmentRefused(NOT_REALISABLE,
                                 f"{name}: {count} segments of {each:.6g} um from l={length:.6g} um "
                                 f"are below this PDK's minimum length {min_length_um!r}")
        members = [f"{name}_s{i}" for i in range(count)]
        inner = [f"{name}_n{i}" for i in range(count - 1)]
        clashes = sorted(taken.intersection(members + inner))
        if clashes:
            raise SegmentRefused(NOT_REALISABLE, f"{name}: segment names already in use: {clashes}")
        parent = {"device": device, "param_exprs": rows, "resolved_l_um": length,
                  "count": count, "segment_l_um": each, "segments": members, "nets": inner}
        devices.extend(_chain_devices(parent))
        nets.extend(inner)
        parents.append(parent)
        replaced_rows[name] = [_segment_rows(row, parent) for row in rows]
    if not parents:
        return ir
    lengths = {parent["device"]["name"]: parent["segment_l_um"] for parent in parents}
    for group in ir.get("ratio_matching_groups") or []:
        members = [name for member in group.get("members", [])
                   for name in member.get("instances", []) if name in lengths]
        if len({lengths[name] for name in members}) > 1:
            raise SegmentRefused(NOT_REALISABLE,
                                 f"matched resistors {members} would get different segment "
                                 f"lengths, which breaks their ratio")
    exprs = []
    for row in all_rows:
        pending = replaced_rows.get(row.get("device"))
        if pending is None:
            exprs.append(row)
        else:
            exprs.extend(pending.pop(0))
    return dict(ir, devices=devices, internal_nets=nets, device_param_exprs=exprs,
                **{RECORD_KEY: {"max_segment_um": maximum, "parents": parents}})


def without_segments(ir):
    """The same IR with each series chain back as the one device it replaced."""
    record = ir.get(RECORD_KEY)
    if not record:
        return ir
    owner = {member: parent for parent in record["parents"] for member in parent["segments"]}
    inner = {net for parent in record["parents"] for net in parent["nets"]}
    devices, exprs, restored = [], [], {}
    for device in ir["devices"]:
        parent = owner.get(device["name"])
        if parent is None:
            devices.append(device)
        elif device["name"] == parent["segments"][0]:
            devices.append(parent["device"])
    for row in ir.get("device_param_exprs") or []:
        parent = owner.get(row.get("device"))
        if parent is None:
            exprs.append(row)
        elif row["device"] == parent["segments"][0]:
            position = restored.get(row["device"], 0)
            exprs.append(parent["param_exprs"][position])
            restored[row["device"]] = position + 1
    view = dict(ir, devices=devices, device_param_exprs=exprs,
                internal_nets=[n for n in ir.get("internal_nets") or [] if n not in inner])
    del view[RECORD_KEY]
    return view


def problems(ir):
    """Every chain must still be exactly what its record says it replaced."""
    record = ir.get(RECORD_KEY)
    if not record:
        return []
    actual = {d.get("name"): d for d in ir.get("devices") or []}
    rows = ir.get("device_param_exprs") or []
    findings = []
    for parent in record["parents"]:
        name = parent["device"]["name"]
        members = set(parent["segments"])
        if ([actual.get(d["name"]) for d in _chain_devices(parent)] != _chain_devices(parent)
                or not set(parent["nets"]) <= set(ir.get("internal_nets") or [])
                or name in actual):
            findings.append(f"RESISTOR_SEGMENT_CHAIN_INVALID: {name} chain differs from its record")
        wanted = [r for row in parent["param_exprs"] for r in _segment_rows(row, parent)]
        if sorted(map(repr, wanted)) != sorted(repr(r) for r in rows if r.get("device") in members):
            findings.append(f"RESISTOR_SEGMENT_CHAIN_INVALID: {name} length expressions differ from its record")
    return findings
