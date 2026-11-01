"""Typed physical routing declarations, private branch compilation and proof."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import math
from typing import Any


class IntentRefusal(ValueError):
    """A declared physical contract could not be established."""


def refuse(code: str, detail: str):
    raise IntentRefusal(f"ROUTING_INTENT_{code}: {detail}")


@dataclass(frozen=True)
class Terminal:
    device: str
    terminal: int


@dataclass(frozen=True)
class Port:
    port: str


@dataclass(frozen=True)
class Topology:
    kind: str
    net: str
    groups: tuple[tuple[Terminal, ...], ...]
    join: Terminal | Port


@dataclass(frozen=True)
class Width:
    net: str
    wire_width_um: float
    via_cuts: int


@dataclass(frozen=True)
class Separation:
    nets: tuple[str, str]
    spacing_um: float | None
    shield_net: str | None = None
    layer: str | None = None


@dataclass(frozen=True)
class RoutingIntent:
    topology: tuple[Topology, ...] = ()
    widths: tuple[Width, ...] = ()
    separations: tuple[Separation, ...] = ()


@dataclass
class Compiled:
    intent: RoutingIntent
    devices: list[dict]
    ports: list[str]
    canonical: dict[str, str]
    endpoints: dict[Terminal, str]
    branches: dict[str, tuple[str, ...]]
    joins: dict[str, str]
    pin_spec: dict | None


def _object(raw: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(raw, dict) or set(raw) - required - optional or required - set(raw):
        refuse("SCHEMA", f"expected fields {sorted(required)} with optional {sorted(optional)}")
    return raw


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        refuse("SCHEMA", "net and device names must be nonempty names")
    return value


def _positive(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        refuse("SCHEMA", "dimensions must be finite positive numbers")
    return float(value)


def _terminal(raw: Any) -> Terminal:
    raw = _object(raw, {"device", "terminal"})
    index = raw["terminal"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        refuse("SCHEMA", "terminal is a zero-based integer")
    return Terminal(_name(raw["device"]), index)


def _members(raw: Any) -> tuple[Terminal, ...]:
    if not isinstance(raw, list) or not raw:
        refuse("SCHEMA", "a branch requires a nonempty terminal list")
    return tuple(_terminal(item) for item in raw)


def parse_intent(raw: Any) -> RoutingIntent:
    raw = _object(raw, {"version", "constraints"})
    if type(raw["version"]) is not int or raw["version"] != 1 or not isinstance(raw["constraints"], list):
        refuse("SCHEMA", "expected version 1 and a constraints array")
    topology, widths, separations = [], [], []
    for item in raw["constraints"]:
        if not isinstance(item, dict):
            refuse("SCHEMA", "each constraint must be an object")
        kind = item.get("kind")
        if kind in ("kelvin", "star"):
            fields = {"kind", "net", "join"} | ({"force", "sense"} if kind == "kelvin" else {"groups"})
            _object(item, fields)
            join = item["join"]
            join = Port(_name(join["port"])) if isinstance(join, dict) and set(join) == {"port"} else _terminal(join)
            if kind == "kelvin":
                groups = (_members(item["force"]), (_terminal(item["sense"]),))
            else:
                if not isinstance(item["groups"], list) or len(item["groups"]) < 2:
                    refuse("SCHEMA", "a star requires at least two terminal groups")
                groups = tuple(_members(group) for group in item["groups"])
            topology.append(Topology(kind, _name(item["net"]), groups, join))
        elif kind == "width":
            _object(item, {"kind", "net", "wire_width_um", "via_cuts"})
            cuts = item["via_cuts"]
            if type(cuts) is not int or cuts < 1:
                refuse("SCHEMA", "via_cuts must be a positive integer")
            widths.append(Width(_name(item["net"]), _positive(item["wire_width_um"]), cuts))
        elif kind == "separation":
            _object(item, {"kind", "nets"}, {"spacing_um", "shield_net", "layer"})
            ns = item["nets"]
            if not isinstance(ns, list) or len(ns) != 2 or ns[0] == ns[1]:
                refuse("SCHEMA", "separation requires two distinct nets")
            ns = tuple(_name(net) for net in ns)
            if "spacing_um" in item and not ({"shield_net", "layer"} & set(item)):
                separations.append(Separation(ns, _positive(item["spacing_um"])))
            elif set(item) == {"kind", "nets", "shield_net", "layer"}:
                separations.append(Separation(ns, None, _name(item["shield_net"]), _name(item["layer"])))
            else:
                refuse("SCHEMA", "choose spacing_um or shield_net and layer")
        else:
            refuse("SCHEMA", f"unknown constraint kind {kind!r}")
    for values in (topology, widths):
        names = [item.net for item in values]
        if len(names) != len(set(names)):
            refuse("CONFLICT", "a net has repeated topology or width declarations")
    pairs = [tuple(sorted(item.nets)) for item in separations]
    if len(pairs) != len(set(pairs)):
        refuse("CONFLICT", "a net pair has repeated separation declarations")
    return RoutingIntent(tuple(topology), tuple(widths), tuple(separations))


def compile_branches(intent: RoutingIntent, devices, ports, pin_spec=None) -> Compiled:
    copies = copy.deepcopy(devices)
    by_name = {device["name"]: device for device in copies}
    if len(by_name) != len(copies):
        refuse("ENDPOINT", "device names are not unique")
    nets = set(ports) | {net for device in copies for net in device["nets"]}
    canonical = {net: net for net in nets}
    endpoints = {Terminal(device["name"], index): net for device in copies for index, net in enumerate(device["nets"])}
    compiled_ports, compiled_spec = list(ports), copy.deepcopy(pin_spec)
    branches, joins = {}, {}

    def endpoint(ref, net):
        if isinstance(ref, Port):
            if ref.port != net or ref.port not in ports:
                refuse("ENDPOINT", f"join port {ref.port} is not a declared port of {net}")
        elif endpoints.get(ref) != net:
            refuse("ENDPOINT", f"terminal {ref} does not belong to {net}")

    for item in intent.widths:
        if item.net not in nets:
            refuse("ENDPOINT", f"width net {item.net} is absent")
    for item in intent.separations:
        if any(net not in nets for net in item.nets) or item.shield_net is not None and item.shield_net not in nets:
            refuse("ENDPOINT", "separation references an absent net")
        if item.shield_net in item.nets:
            refuse("CONFLICT", "the shield must be a third net")
        if item.shield_net is not None:
            refuse("SHIELD_UNROUTABLE", "a connected shield on the declared layer cannot be established by this channel planner")
    for ti, item in enumerate(intent.topology):
        endpoint(item.join, item.net)
        refs = [ref for group in item.groups for ref in group]
        for ref in refs:
            endpoint(ref, item.net)
        if len(set(refs)) != len(refs) or item.join in refs:
            refuse("CONFLICT", f"{item.net} has duplicate branch or join membership")
        expected = {ref for ref, net in endpoints.items() if net == item.net}
        if isinstance(item.join, Terminal):
            expected.remove(item.join)
        if set(refs) != expected:
            refuse("CONFLICT", f"{item.net} groups must cover every terminal except the declared join")
        ids = []
        groups = item.groups + (((item.join,),) if isinstance(item.join, Terminal) else ())
        for gi, group in enumerate(groups):
            private = f"__routing_intent_{ti}_{gi}"
            if private in nets:
                refuse("CONFLICT", "reserved routing identity collides with a schematic net")
            canonical[private] = item.net
            ids.append(private)
            for ref in group:
                by_name[ref.device]["nets"][ref.terminal] = private
                endpoints[ref] = private
        branches[item.net] = tuple(ids)
        owner = ids[-1] if isinstance(item.join, Terminal) else ids[0]
        joins[item.net] = owner
        if item.net in compiled_ports:
            compiled_ports[compiled_ports.index(item.net)] = owner
            if compiled_spec:
                compiled_spec["ports"][owner] = compiled_spec["ports"].pop(item.net)
    return Compiled(intent, copies, compiled_ports, canonical, endpoints, branches, joins, compiled_spec)


def _overlap(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _clip(box, region):
    if not _overlap(box, region):
        return [box]
    x1, y1, x2, y2 = box
    a, b, c, d = region
    out = [(x1, y1, min(x2, a), y2), (max(x1, c), y1, x2, y2),
           (max(x1, a), y1, min(x2, c), min(y2, b)),
           (max(x1, a), max(y1, d), min(x2, c), y2)]
    return [rect for rect in out if rect[2] > rect[0] and rect[3] > rect[1]]


def components(rows, linked):
    parent = list(range(len(rows)))
    def find(index):
        while index != parent[index]:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index
    for i, row in enumerate(rows):
        for j in range(i):
            other = rows[j]
            if linked(row["layer"], other["layer"]) and _overlap(row["box"], other["box"]):
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    return [find(i) for i in range(len(rows))]


def verify_topology(plan, compiled: Compiled, regions, linked):
    rows = list(plan.shapes) + list(plan.device_shapes)
    full = components(rows, linked)
    evidence = []
    for topology in compiled.intent.topology:
        ids = set(compiled.branches[topology.net])
        roots = {full[i] for i, row in enumerate(rows) if row["net"] in ids}
        if len(roots) != 1:
            refuse("DISCONNECTED_BRANCH", f"{topology.net} has {len(roots)} routed components")
        junction = regions[topology.net]
        load_rows = [i for i, row in enumerate(rows)
                     if row["layer"] == junction["load_layer"]
                     and (row.get("comp") == junction.get("native_component") if junction.get("native_component") is not None
                          else row["net"] == compiled.joins[topology.net])
                     and _overlap(row["box"], junction["box"])]
        if not load_rows or not any(full[index] in roots for index in load_rows):
            refuse("DISCONNECTED_BRANCH", f"{topology.net} does not reach the declared load conductor")
        clipped = [dict(row, box=box) for row in rows
                   for box in (_clip(row["box"], junction["box"])
                               if row["layer"] in junction["layers"] else [row["box"]])]
        roots = components(clipped, linked)
        members = {}
        for row, root in zip(clipped, roots):
            if row["net"] in ids:
                members.setdefault(root, set()).add(row["net"])
        if any(len(group) > 1 for group in members.values()):
            refuse("PREMATURE_JOIN", f"{topology.net} branches connect outside its declared load contact")
        for ref, private in compiled.endpoints.items():
            if private not in ids:
                continue
            anchors = plan.intent_anchors.get(ref, [])
            if not anchors:
                refuse("ENDPOINT", f"no physical label for {ref}")
            for anchor in anchors:
                endpoint_roots = {full[index] for index, row in enumerate(rows)
                                  if row.get("comp") == anchor["comp"]}
                reached = bool(endpoint_roots & {full[index] for index, row in enumerate(rows)
                                                if row["net"] == private})
                if not reached:
                    refuse("DISCONNECTED_BRANCH", f"{ref} is not reached by its branch")
        evidence.append({"kind": topology.kind, "net": topology.net, "branches": len(ids),
                         "join_box_lambda": list(junction["box"]), "outside_join_connected": False})
    return evidence


def _gap(a, b):
    return math.hypot(max(a[0] - b[2], b[0] - a[2], 0),
                      max(a[1] - b[3], b[1] - a[3], 0))


def _inside(box, region):
    return region[0] <= box[0] and region[1] <= box[1] and box[2] <= region[2] and box[3] <= region[3]


def _intersection(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _anchors(plan, compiled, a5):
    plan.intent_anchors = {}
    component_nets = {}
    for device in plan.intent_placed:
        raw = device["dev"]
        marked = dict(raw, nets=[f"__terminal_{index}" for index in range(len(raw["nets"]))])
        mapping, _, _ = a5.terminal_map(marked, device["cell"])
        ox, oy = device["origin"]
        for index, private in enumerate(raw["nets"]):
            ref = Terminal(raw["name"], index)
            anchors = []
            for label in mapping.get(f"__terminal_{index}", []):
                x, y, level = ox + label["x"], oy + label["y"], label["level"]
                layer = f"metal{level}"
                friendly = a5.friendly_conductor(device["rows"], layer, x, y, reach=0)
                if friendly is None:
                    refuse("ENDPOINT", f"{ref} has no native metal conductor")
                anchors.append({"layer": layer, "box": (x, y, x, y), "comp": friendly})
                component_nets.setdefault(friendly, set()).add(compiled.canonical[private])
            plan.intent_anchors[ref] = anchors
    plan.intent_component_nets = component_nets


def _canonical(row, compiled, plan):
    if "comp" in row:
        return plan.intent_component_nets.get(row["comp"], set())
    return {compiled.canonical.get(row["net"], row["net"])}


def _safe(paint, net, plan, compiled, geo, a5, allowed=None, allowed_layers=(), friendly=None):
    for layer, box in paint:
        for row in list(plan.shapes) + list(plan.device_shapes):
            if not a5._linked(layer, row["layer"]):
                continue
            other = row["box"]
            touching = _overlap(box, other)
            if row["net"] == net:
                continue
            if touching and allowed is not None and layer in allowed_layers and row["layer"] in allowed_layers:
                same = compiled.canonical.get(row["net"]) == compiled.canonical.get(net)
                native = friendly is not None and row.get("comp") == friendly
                if (same or native) and _inside(_intersection(box, other), allowed):
                    continue
            spacing = geo.metal_space(layer, box, other)
            for pair in compiled.intent.separations:
                if compiled.canonical.get(net, net) in pair.nets and any(n in pair.nets and n != compiled.canonical.get(net, net)
                                                                                        for n in _canonical(row, compiled, plan)):
                    spacing = max(spacing, math.ceil(pair.spacing_um * geo.lam - 1e-9))
            dx = max(box[0] - other[2], other[0] - box[2], 0)
            dy = max(box[1] - other[3], other[1] - box[3], 0)
            if dx < spacing and dy < spacing:
                return False
    return True


def _wire(layer, x1, y1, x2, y2, geo):
    half = max(1, math.ceil(geo.wire[layer] / 2))
    return (f"metal{layer}", (min(x1, x2) - half, min(y1, y2) - half,
                              max(x1, x2) + half, max(y1, y2) + half))


def _join_port(plan, owner, count, band, compiled, geo, a5):
    pin = next((pin for pin in plan.pins if pin["net"] == owner), None)
    if pin is None:
        refuse("ENDPOINT", f"declared load port {compiled.canonical[owner]} has no physical pin")
    level = int(pin["layer"][5:])
    if level >= max(geo.rules["metal_width_um"], default=4):
        refuse("NO_LEGAL_ROUTE", "load pin has no available overlying routing metal")
    top = level + 1
    cuts = geo.intent_cuts.get(owner, 1)
    _, bars = a5._pin_stack_boxes(0, 0, level, top, geo, cuts)
    bx = max(abs(bars[level][0]), abs(bars[level][2]))
    by = max(abs(bars[level][1]), abs(bars[level][3]), abs(bars[top][1]), abs(bars[top][3]))
    pitch = 2 * by + max(geo.metal_space(f"metal{top}"), geo.metal_space(f"metal{level}"))
    x = (pin["strip_box"][0] + pin["strip_box"][2]) // 2
    high = -band * pitch
    low = high - (count + 1) * pitch
    region = (x - bx, low, x + bx, high)
    extension = (pin["layer"], (x - bx, low, x + bx, pin["strip_box"][1] + 1))
    if not _safe([extension], owner, plan, compiled, geo, a5):
        refuse("NO_LEGAL_ROUTE", f"{compiled.canonical[owner]} has no clear declared pin junction")
    plan.paint(owner, extension[0], *extension[1])
    pin["label_box"] = region
    pin["strip_box"] = (min(region[0], pin["strip_box"][0]), low,
                        max(region[2], pin["strip_box"][2]), pin["strip_box"][3])
    pin["width_lam"] = max(pin["width_lam"], 2 * bx)
    targets = [(x, high - (index + 1) * pitch) for index in range(count)]
    return region, level, top, targets


def _join_terminal(plan, topology, compiled, geo, a5):
    anchors = plan.intent_anchors.get(topology.join, [])
    if len(anchors) != 1:
        refuse("ENDPOINT", "a terminal join requires one unambiguous native load contact")
    anchor = anchors[0]
    x, y = anchor["box"][:2]
    boxes = [row["box"] for row in plan.device_shapes if row.get("comp") == anchor["comp"]
             and row["layer"] == anchor["layer"] and _overlap(row["box"], anchor["box"])]
    if not boxes:
        refuse("ENDPOINT", "the load label has no native contact footprint")
    region = min(boxes, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))
    level = int(anchor["layer"][5:])
    top = max(4, level + 1)
    if top not in geo.rules["metal_width_um"]:
        refuse("NO_LEGAL_ROUTE", "the load terminal has no available upper routing plane")
    count = len(compiled.branches[topology.net]) - 1
    return region, level, top, [(x, y)] * count, anchor["comp"]


def _connect_branch(plan, branch, owner, region, level, top, target, compiled, geo, a5, friendly=None):
    tx, ty = target
    cuts = geo.intent_cuts.get(branch, 1)
    allowed_layers = tuple([f"metal{k}" for k in range(level, top + 1)]
                           + [f"via{k}" for k in range(level, top)])
    join_paint, bars = a5._pin_stack_boxes(tx, ty, level, top, geo, cuts)
    if not _inside(bars[level], region):
        refuse("VIA_SITE", "the declared load contact cannot enclose the requested cut array")
    rows = [row for row in plan.shapes if row["net"] == branch and row["layer"] == f"metal{plan.rail_level}"
            and row["box"][2] - row["box"][0] > row["box"][3] - row["box"][1]]
    rows.sort(key=lambda row: (row["box"][1], -(row["box"][2] - row["box"][0])))
    for rail in rows:
        box = rail["box"]
        sy = (box[1] + box[3]) // 2
        step = max(1, geo.pitch() // 2)
        xs = list(range(box[0] + step, box[2] - step + 1, step))
        xs.sort(key=lambda x: abs(x - tx))
        for sx in xs:
            access, _ = a5._pin_stack_boxes(sx, sy, plan.rail_level, 3, geo, cuts)
            elbow, _ = a5._pin_stack_boxes(sx, ty, 3, top, geo, cuts)
            paint = access + [_wire(3, sx, sy, sx, ty, geo)] + elbow
            paint += [_wire(top, sx, ty, tx, ty, geo)] + join_paint
            if not _safe(paint, branch, plan, compiled, geo, a5, region, allowed_layers, friendly):
                continue
            for layer, rectangle in paint:
                plan.paint(branch, layer, *rectangle)
            return
    refuse("NO_LEGAL_ROUTE", f"branch {branch} has no clear route to the declared load contact")


def verify_separation(plan, compiled, geo, a5):
    rows = list(plan.shapes) + list(plan.device_shapes)
    evidence = []
    for item in compiled.intent.separations:
        first = [row for row in rows if item.nets[0] in _canonical(row, compiled, plan)]
        second = [row for row in rows if item.nets[1] in _canonical(row, compiled, plan)]
        measured = []
        for a in first:
            for b in second:
                if a["layer"] != b["layer"] or not a["layer"].startswith("metal"):
                    continue
                gap = _gap(a["box"], b["box"]) / geo.lam
                measured.append(gap)
                if gap + 1e-9 < item.spacing_um:
                    refuse("SEPARATION", f"{item.nets} have {gap:g}um on {a['layer']}, need {item.spacing_um:g}um")
        if not measured:
            refuse("SEPARATION", f"{item.nets} have no measurable common metal plane")
        evidence.append({"kind": "separation", "nets": list(item.nets), "required_um": item.spacing_um,
                         "minimum_um": min(measured)})
    return evidence


def build_intent_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec, raw, options):
    import analog_a5_layout_emit as a5
    intent = raw if isinstance(raw, RoutingIntent) else parse_intent(raw)
    if not (intent.topology or intent.widths or intent.separations):
        return a5._build_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec, **options)
    compiled = compile_branches(intent, devs, ports, pin_spec)
    geo = copy.deepcopy(base_geo)
    geo.intent_strict = True
    geo.intent_cuts = {private: next((width.via_cuts for width in intent.widths if width.net == net), 1)
                       for private, net in compiled.canonical.items()}
    minimum = max([geo.rules["metal_width_um"].get(k, 0) for k in (1, 2, 3)])
    for width in intent.widths:
        if width.wire_width_um + 1e-12 < minimum:
            refuse("WIDTH_BELOW_PDK_MINIMUM", f"{width.net} width {width.wire_width_um:g}um < {minimum:g}um")
    reserve_width = max([math.ceil(width.wire_width_um * geo.lam - 1e-9) for width in intent.widths] + [0])
    geo.wire = {level: max(value, reserve_width) for level, value in geo.wire.items()}
    reserve_space = max([math.ceil(item.spacing_um * geo.lam - 1e-9) for item in intent.separations] + [0])
    geo.space = {level: max(value, reserve_space) for level, value in geo.space.items()}
    geo.default_space = max(geo.default_space, reserve_space)
    try:
        plan = a5._build_plan(compiled.devices, compiled.ports, cells, facts, geo, tap_clear,
                              compiled.pin_spec, **options)
    except a5.Refusal as exc:
        refuse("NO_LEGAL_ROUTE", str(exc))
    _anchors(plan, compiled, a5)
    regions = {}
    band = 1
    junction_layers = {}
    for topology in intent.topology:
        owner = compiled.joins[topology.net]
        others = [branch for branch in compiled.branches[topology.net] if branch != owner]
        friendly = None
        if isinstance(topology.join, Port):
            region, level, top, targets = _join_port(plan, owner, len(others), band, compiled, geo, a5)
            band += len(others) + 3
        else:
            region, level, top, targets, friendly = _join_terminal(plan, topology, compiled, geo, a5)
        junction_layers[topology.net] = tuple([f"metal{k}" for k in range(level, top + 1)]
                                                + [f"via{k}" for k in range(level, top)])
        regions[topology.net] = {"box": region, "layers": junction_layers[topology.net],
                                 "load_layer": f"metal{level}", "native_component": friendly}
        for branch, target in zip(others, targets):
            _connect_branch(plan, branch, owner, region, level, top, target, compiled, geo, a5, friendly)
    evidence = verify_topology(plan, compiled, regions, a5._linked)
    evidence.extend(verify_separation(plan, compiled, geo, a5))
    for width in intent.widths:
        selected = [row for row in plan.shapes if compiled.canonical.get(row["net"], row["net"]) == width.net
                    and row["layer"].startswith("metal")]
        actual = min([min(row["box"][2] - row["box"][0], row["box"][3] - row["box"][1]) / geo.lam
                      for row in selected] or [0])
        if actual + 1e-9 < width.wire_width_um:
            refuse("WIDTH_UNACHIEVED", f"{width.net} contains {actual:g}um metal below {width.wire_width_um:g}um")
        evidence.append({"kind": "width", "net": width.net, "required_um": width.wire_width_um,
                         "minimum_drawn_um": actual, "cuts_per_transition": width.via_cuts})
    for row in plan.shapes:
        row["net"] = compiled.canonical.get(row["net"], row["net"])
    for pin in plan.pins:
        pin["net"] = compiled.canonical.get(pin["net"], pin["net"])
    plan.ports = [(compiled.canonical.get(net, net), x, y) for net, x, y in plan.ports]
    plan.port_nets = list(ports)
    for row in plan.placement_rows:
        row["nets"] = list(dict.fromkeys(compiled.canonical.get(net, net) for net in row["nets"]))
    if a5.net_shorts(plan):
        refuse("CROSS_NET_METAL", "the completed intent layout shorts different schematic nets")
    plan.routing_intent_evidence = {"version": 1, "constraints": evidence,
                                    "width_semantics": "minimum; corridors reserve the widest declared style"}
    return plan
