"""Typed physical routing declarations, private branch compilation and proof."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import copy
import math
from typing import Any


CURRENT_ROUTE_PASSES = 4
STACK_SHARE = 0.45
PIN_SHARE = 0.10


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
class CurrentBudget:
    net: str
    device: str
    ir_drop_mv: float


@dataclass(frozen=True)
class PathSize:
    rail_lam: int
    cuts: int
    pin_lam: int


@dataclass(frozen=True)
class CurrentPath:
    """One declared current's series path: pin wire, pin via stack, rail, parallel terminal legs."""
    current_ma: float
    budget_mv: float
    cut_ohms: tuple[float, ...]
    sheet_ohm: float
    pin_sheet_ohm: float
    pin_run: int
    source: int
    sinks: tuple[int, ...]
    leg_ohms: tuple[float, ...]

    @property
    def budget_ohm(self) -> float:
        return self.budget_mv / self.current_ma

    @property
    def legs_ohm(self) -> float:
        return 1 / sum(1 / ohm for ohm in self.leg_ohms)

    def stack_ohm(self, cuts: int) -> float:
        return sum(self.cut_ohms) / cuts

    def pin_ohm(self, width_lam: int) -> float:
        return self.pin_sheet_ohm * self.pin_run / width_lam

    def rail_ohm(self, width_lam: int) -> float:
        """Series-equivalent resistance of the rail for equal currents at its terminal legs."""
        squares = 0.0
        for side in ([x for x in self.sinks if x >= self.source], [x for x in self.sinks if x < self.source]):
            share, here = len(side) / len(self.sinks), self.source
            for x in sorted(side, key=lambda v: abs(v - self.source)):
                squares += share * share * abs(x - here) / width_lam
                here, share = x, share - 1 / len(self.sinks)
        return self.sheet_ohm * squares

    def _remaining(self, spent: float) -> float:
        remaining = self.budget_ohm - self.legs_ohm - spent
        if remaining <= 0:
            refuse("IR_BUDGET_UNACHIEVABLE", f"{self.budget_mv:g} mV at {self.current_ma:g} mA leaves "
                   f"{remaining:.3f} ohm after {self.legs_ohm:.3f} ohm of parallel terminal legs and "
                   f"{spent:.3f} ohm of stack and pin wire")
        return remaining

    def size(self) -> PathSize:
        """The smallest stack, rail and pin wire meeting the budget at fixed shares of what the legs leave."""
        remaining = self._remaining(0.0)
        cuts = max(1, math.ceil(self.stack_ohm(1) / (remaining * STACK_SHARE) - 1e-9))
        pin = max(1, math.ceil(self.pin_ohm(1) / (remaining * PIN_SHARE) - 1e-9))
        rail = math.ceil(self.rail_ohm(1) / (remaining * (1 - STACK_SHARE - PIN_SHARE)) - 1e-9)
        return PathSize(2 * math.ceil(rail / 2), cuts, 2 * math.ceil(pin / 2))

    def resize(self, drawn: PathSize) -> PathSize:
        """Keep the seated stack; re-derive the wires for the rail and pin run it was given."""
        pin = max(drawn.pin_lam, 2 * math.ceil(self.pin_ohm(1) / (self._remaining(self.stack_ohm(drawn.cuts)) * PIN_SHARE) / 2))
        remaining = self._remaining(self.stack_ohm(drawn.cuts) + self.pin_ohm(pin))
        return PathSize(2 * math.ceil(math.ceil(self.rail_ohm(1) / remaining - 1e-9) / 2), drawn.cuts, pin)

    def total_ohm(self, drawn: PathSize) -> float:
        return self.legs_ohm + self.rail_ohm(drawn.rail_lam) + self.stack_ohm(drawn.cuts) + self.pin_ohm(drawn.pin_lam)


@dataclass(frozen=True)
class RoutingIntent:
    topology: tuple[Topology, ...] = ()
    widths: tuple[Width, ...] = ()
    separations: tuple[Separation, ...] = ()
    currents: tuple[CurrentBudget, ...] = ()


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
    topology, widths, separations, currents = [], [], [], []
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
        elif kind == "current_budget":
            _object(item, {"kind", "net", "device", "ir_drop_mv"})
            currents.append(CurrentBudget(_name(item["net"]), _name(item["device"]), _positive(item["ir_drop_mv"])))
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
    if {item.net for item in currents} & {item.net for item in widths}:
        refuse("CONFLICT", "a net declares both an explicit width and a current budget")
    for values in (topology, widths, currents):
        names = [item.net for item in values]
        if len(names) != len(set(names)):
            refuse("CONFLICT", "a net has repeated topology or width declarations")
    pairs = [tuple(sorted(item.nets)) for item in separations]
    if len(pairs) != len(set(pairs)):
        refuse("CONFLICT", "a net pair has repeated separation declarations")
    return RoutingIntent(tuple(topology), tuple(widths), tuple(separations), tuple(currents))


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
    for item in intent.separations:
        if item.shield_net is None:
            continue
        order = []
        for net in (item.nets[0], item.shield_net, item.nets[1]):
            private = next((private for private in compiled_ports if canonical[private] == net), None)
            if private is None:
                refuse("SHIELD_UNROUTABLE", "the bounded shield channel requires declared pair and shield ports")
            order.append(private)
        positions = [compiled_ports.index(private) for private in order]
        for position, private in zip(sorted(positions), order):
            compiled_ports[position] = private
    if compiled_spec:
        for private, spec in compiled_spec["ports"].items():
            policy = next((width for width in intent.widths if width.net == canonical[private]), None)
            if policy:
                spec["cuts"] = max(spec["cuts"], policy.via_cuts)
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
    rows = [dict(row, _route=(row["layer"], tuple(row["box"])) not in plan.patch_of)
            for row in plan.shapes] + [dict(row, _route=False) for row in plan.device_shapes]
    full = components(rows, linked)
    evidence = []
    for topology in compiled.intent.topology:
        ids = set(compiled.branches[topology.net])
        roots = {full[i] for i, row in enumerate(rows) if row["net"] in ids and row["_route"]}
        if len(roots) != 1:
            witness = {root: sorted({row["net"] for i, row in enumerate(rows)
                                    if row["net"] in ids and row["_route"] and full[i] == root}) for root in roots}
            refuse("DISCONNECTED_BRANCH", f"{topology.net} has {len(roots)} routed components {witness}")
        junction = regions[topology.net]
        load_rows = [i for i, row in enumerate(rows)
                     if row["layer"] == junction["load_layer"]
                     and (row.get("comp") == junction.get("native_component") if junction.get("native_component") is not None
                          else row["net"] == compiled.joins[topology.net])
                     and _overlap(row["box"], junction["box"])]
        if not load_rows or not any(full[index] in roots for index in load_rows):
            refuse("DISCONNECTED_BRANCH", f"{topology.net} does not reach the declared load conductor")
        local = [dict(row, box=_intersection(row["box"], junction["box"])) for row in rows
                 if row["layer"] in junction["layers"] and _overlap(row["box"], junction["box"])]
        local_roots = components(local, linked)
        load_roots = {root for row, root in zip(local, local_roots)
                      if row["layer"] == junction["load_layer"]
                      and (row.get("comp") == junction.get("native_component") if junction.get("native_component") is not None
                           else row["net"] == compiled.joins[topology.net])}
        for private in ids:
            if not any(row["net"] == private and row["_route"] and root in load_roots
                       for row, root in zip(local, local_roots)):
                refuse("DISCONNECTED_BRANCH", f"{private} does not contact the load inside its declared junction")
        clipped = [dict(row, box=box) for row in rows
                   for box in (_clip(row["box"], junction["box"])
                               if row["layer"] in junction["layers"] else [row["box"]])]
        roots = components(clipped, linked)
        members = {}
        for row, root in zip(clipped, roots):
            if row["net"] in ids and row["_route"]:
                members.setdefault(root, set()).add(row["net"])
        if any(len(group) > 1 for group in members.values()):
            refuse("PREMATURE_JOIN", f"{topology.net} branches connect outside its declared load contact")
        for ref, private in compiled.endpoints.items():
            if private not in ids or ref == topology.join:
                continue
            anchors = plan.intent_anchors.get(ref, [])
            if not anchors:
                refuse("ENDPOINT", f"no physical label for {ref}")
            for anchor in anchors:
                endpoint_roots = {roots[index] for index, row in enumerate(clipped)
                                  if row.get("comp") == anchor["comp"] and _overlap(row["box"], anchor["box"])}
                reached = bool(endpoint_roots & {roots[index] for index, row in enumerate(clipped)
                                                if row["net"] == private and row["_route"]})
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
        semantic, _, _ = a5.terminal_map(raw, device["cell"])
        section_owners = {}
        for private, labels in semantic.items():
            for label in labels:
                section_owners.setdefault(label.get("layer"), set()).add(compiled.canonical[private])
        ox, oy = device["origin"]
        for section, boxes in device["cell"]["sections"].items():
            owners = section_owners.get(section, set())
            if len(owners) != 1:
                continue
            planes = a5.carried_planes(section, device["cell"].get("layers"))
            for native in device["rows"]:
                if native["layer"] not in planes:
                    continue
                if any(_overlap(native["box"], (ox + box[0], oy + box[1], ox + box[2], oy + box[3])) for box in boxes):
                    component_nets.setdefault(native["comp"], set()).update(owners)
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
    for patch in plan.shapes:
        owner = plan.patch_of.get((patch["layer"], tuple(patch["box"])))
        if owner is None:
            continue
        for native in plan.device_shapes:
            if native.get("comp", (None,))[0] == owner and native["layer"] == patch["layer"] and _overlap(native["box"], patch["box"]):
                component_nets.setdefault(native["comp"], set()).add(compiled.canonical.get(patch["net"], patch["net"]))
    plan.intent_component_nets = component_nets


def _canonical(row, compiled, plan):
    if "comp" in row:
        return plan.intent_component_nets.get(row["comp"], set())
    return {compiled.canonical.get(row["net"], row["net"])}


def _safe(paint, net, plan, compiled, geo, a5, allowed=None, allowed_layers=(), friendly=None):
    for index, (layer, box) in enumerate(paint):
        for other_layer, other in paint[:index]:
            if layer != other_layer or tuple(box) == tuple(other):
                continue
            dx = max(box[0] - other[2], other[0] - box[2], 0)
            dy = max(box[1] - other[3], other[1] - box[3], 0)
            if not (dx or dy) and not layer.startswith("via"):
                continue
            spacing = geo.metal_space(layer, box, other)
            if dx < spacing and dy < spacing:
                return False
    for layer, box in paint:
        for row in list(plan.shapes) + list(plan.device_shapes):
            if not a5._linked(layer, row["layer"]):
                continue
            other = row["box"]
            touching = _overlap(box, other)
            if row["net"] == net:
                if layer == row["layer"] and layer.startswith("via"):
                    if tuple(box) == tuple(other):
                        continue
                elif touching:
                    continue
            if touching and allowed is not None and layer in allowed_layers and row["layer"] in allowed_layers:
                same = compiled.canonical.get(row["net"]) == compiled.canonical.get(net)
                native = friendly is not None and row.get("comp") == friendly
                if (same or native) and _inside(_intersection(box, other), allowed):
                    continue
            if layer != row["layer"] and not touching:
                continue
            spacing = geo.metal_space(layer, box, other)
            for pair in compiled.intent.separations:
                if pair.spacing_um is not None and compiled.canonical.get(net, net) in pair.nets and any(n in pair.nets and n != compiled.canonical.get(net, net)
                                                                                        for n in _canonical(row, compiled, plan)):
                    spacing = max(spacing, math.ceil(pair.spacing_um * geo.lam - 1e-9))
            dx = max(box[0] - other[2], other[0] - box[2], 0)
            dy = max(box[1] - other[3], other[1] - box[3], 0)
            if dx < spacing and dy < spacing:
                plan.intent_collision = {"net": net, "candidate": [layer, list(box)],
                                         "obstacle": {key: row[key] for key in ("net", "layer", "box")}}
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
        refuse("NO_LEGAL_ROUTE", f"{compiled.canonical[owner]} has no clear declared pin junction; {getattr(plan, 'intent_collision', {})}")
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
    level = max(3, int(anchor["layer"][5:]))
    top = max(4, level + 1)
    if top not in geo.rules["metal_width_um"]:
        refuse("NO_LEGAL_ROUTE", "the load terminal has no available upper routing plane")
    count = len(compiled.branches[topology.net]) - 1
    _, bars = a5._pin_stack_boxes(0, 0, level, top, geo, geo.intent_cuts.get(compiled.joins[topology.net], 1))
    half = max(abs(box[index]) for box in bars.values() for index in (1, 3))
    pitch = 2 * half + max(geo.metal_space(f"metal{level}"), geo.metal_space(f"metal{top}"))
    height = (count - 1) * pitch + 2 * half
    if height > region[3] - region[1]:
        refuse("VIA_SITE", "the declared terminal cannot contain independent branch landings")
    first_y = y - ((count - 1) * pitch) // 2
    targets = [(x, first_y + index * pitch) for index in range(count)]
    owner = compiled.joins[topology.net]
    column = _wire(level, x, targets[0][1], x, targets[-1][1], geo)
    if not _inside(column[1], region) or not _safe([column], owner, plan, compiled, geo, a5, region,
                                               (f"metal{level}",), anchor["comp"]):
        refuse("NO_LEGAL_ROUTE", "no clear local load-terminal junction exists")
    plan.paint(owner, column[0], *column[1])
    return region, level, top, targets, anchor["comp"]


def _connect_branch(plan, branch, owner, region, level, top, target, compiled, geo, a5, friendly=None, junction_layers=None):
    tx, ty = target
    cuts = geo.intent_cuts.get(branch, 1)
    allowed_layers = junction_layers or tuple([f"metal{k}" for k in range(level, top + 1)]
                                              + [f"via{k}" for k in range(level, top)])
    join_paint, bars = a5._pin_stack_boxes(tx, ty, level, top, geo, cuts)
    if not _inside(bars[level], region):
        refuse("VIA_SITE", "the declared load contact cannot enclose the requested cut array")
    sources = [row for row in plan.shapes if row["net"] == branch and row["layer"] == "metal3"]
    sources.sort(key=lambda row: (row["box"][1], -(row["box"][3] - row["box"][1])))
    for source in sources:
        box = source["box"]
        sx, sy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        for carry in range(3, top + 1):
            access = a5._pin_stack_boxes(sx, sy, 3, carry, geo, cuts)[0] if carry > 3 else []
            elbow, _ = a5._pin_stack_boxes(sx, ty, carry, top, geo, cuts)
            paint = access + [_wire(carry, sx, sy, sx, ty, geo)] + elbow
            paint += [_wire(top, sx, ty, tx, ty, geo)] + join_paint
            if _safe(paint, branch, plan, compiled, geo, a5, region, allowed_layers, friendly):
                for layer, rectangle in paint:
                    plan.paint(branch, layer, *rectangle)
                return
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
            access, _ = a5._pin_stack_boxes(sx, sy, min(plan.rail_level, 3), max(plan.rail_level, 3), geo, cuts)
            elbow, _ = a5._pin_stack_boxes(sx, ty, 3, top, geo, cuts)
            paint = access + [_wire(3, sx, sy, sx, ty, geo)] + elbow
            paint += [_wire(top, sx, ty, tx, ty, geo)] + join_paint
            if not _safe(paint, branch, plan, compiled, geo, a5, region, allowed_layers, friendly):
                continue
            for layer, rectangle in paint:
                plan.paint(branch, layer, *rectangle)
            return
    refuse("NO_LEGAL_ROUTE", f"branch {branch} has no clear route to the declared load contact; {getattr(plan, 'intent_collision', {})}")


def verify_separation(plan, compiled, geo, a5):
    rows = list(plan.shapes) + list(plan.device_shapes)
    evidence = []
    for item in compiled.intent.separations:
        if item.spacing_um is None:
            continue
        first = [row for row in rows if item.nets[0] in _canonical(row, compiled, plan)]
        second = [row for row in rows if item.nets[1] in _canonical(row, compiled, plan)]
        measured = []
        for native in plan.device_shapes:
            if _canonical(native, compiled, plan) or not native["layer"].startswith("metal"):
                continue
            if any(row["layer"] == native["layer"] and _gap(row["box"], native["box"]) / geo.lam + 1e-9 < item.spacing_um
                   for row in first + second):
                refuse("NATIVE_OWNERSHIP_AMBIGUOUS", f"cannot establish {item.nets} spacing beside {native.get('comp')}")
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


def build_shields(plan, compiled, geo, facts, a5):
    evidence = []
    for item in compiled.intent.separations:
        if item.shield_net is None:
            continue
        level = None
        if facts.layers is not None and facts.layers.knows(item.layer):
            canonical = facts.layers.canon[item.layer]
            planes = facts.layers.conductor_planes(item.layer)
            if canonical in facts.layers.connects or len(planes) != 1:
                refuse("SHIELD_LAYER", f"{item.layer} is a contact, not a pure routing conductor")
            level = facts.layers.level(item.layer)
        elif facts.layers is None and item.layer.startswith("metal") and item.layer[5:].isdigit():
            level = int(item.layer[5:])
        if level not in geo.rules["metal_width_um"]:
            refuse("SHIELD_LAYER", f"{item.layer} is not a declared PDK routing plane")
        layer = f"metal{level}"
        if any(row["layer"] == layer and not _canonical(row, compiled, plan) for row in plan.device_shapes):
            refuse("NATIVE_OWNERSHIP_AMBIGUOUS", f"cannot establish complete shield coverage on {layer}")
        rows = list(plan.shapes) + list(plan.device_shapes)
        first = [row for row in rows if row["layer"] == layer and item.nets[0] in _canonical(row, compiled, plan)]
        second = [row for row in rows if row["layer"] == layer and item.nets[1] in _canonical(row, compiled, plan)]
        guards = [row for row in plan.shapes if row["layer"] == layer and item.shield_net in _canonical(row, compiled, plan)]
        if not first or not second or not guards:
            refuse("SHIELD_UNROUTABLE", f"the declared pair and shield have no connected {layer} channel")
        def extent(records):
            return (min(row["box"][0] for row in records), min(row["box"][1] for row in records),
                    max(row["box"][2] for row in records), max(row["box"][3] for row in records))
        a, b = extent(first), extent(second)
        shield_id = compiled.joins.get(item.shield_net, guards[0]["net"])
        profile = geo.for_net(shield_id)
        half = math.ceil(profile.wire[level] / 2)
        candidates = []
        for axis in (0, 1):
            low, high = sorted((a, b), key=lambda box: box[axis])
            other_axis = 1 - axis
            if max(a[other_axis], b[other_axis]) >= min(a[other_axis + 2], b[other_axis + 2]):
                continue
            for guard in guards:
                center = (guard["box"][axis] + guard["box"][axis + 2]) // 2
                if center - half <= low[axis + 2] or center + half >= high[axis]:
                    continue
                lo = min(a[other_axis], b[other_axis], guard["box"][other_axis])
                hi = max(a[other_axis + 2], b[other_axis + 2], guard["box"][other_axis + 2])
                box = (center - half, lo, center + half, hi) if axis == 0 else (lo, center - half, hi, center + half)
                if _safe([(layer, box)], shield_id, plan, compiled, profile, a5):
                    candidates.append((box, axis))
        if not candidates:
            refuse("SHIELD_UNROUTABLE", f"no PDK-clear connected {layer} shield lies between {item.nets}")
        box, axis = candidates[0]
        plan.paint(shield_id, layer, *box)
        full_rows = list(plan.shapes) + list(plan.device_shapes)
        roots = components(full_rows, a5._linked)
        guard_roots = {roots[index] for index, row in enumerate(full_rows)
                       if index < len(plan.shapes) and item.shield_net in _canonical(row, compiled, plan)
                       and (row["layer"], tuple(row["box"])) not in plan.patch_of}
        if len(guard_roots) != 1:
            refuse("SHIELD_UNCONNECTED", f"{item.shield_net} shield is not one connected routed net")
        evidence.append({"kind": "separation", "nets": list(item.nets), "shield_net": item.shield_net,
                         "layer": layer, "shield_box_lambda": list(box), "axis": axis,
                         "continuous_projection": True, "connected": True})
    return evidence


def _current_path(plan, budget, compiled, geo):
    """Read the path a current budget governs from an already routed plan."""
    private = {net for ref, net in compiled.endpoints.items()
               if ref.device == budget.device and compiled.canonical.get(net) == budget.net}
    if len(private) != 1:
        refuse("ENDPOINT", f"device {budget.device} has no single terminal group on {budget.net}")
    net = private.pop()
    pin = next((row for row in plan.pins if row["net"] == budget.net), None)
    if pin is None or compiled.joins.get(budget.net, budget.net) != net:
        refuse("CURRENT_PATH_UNSUPPORTED", f"{budget.net}: {budget.device} is not on the branch that owns the pin")
    rows = [rails for rails in plan.row_rails if net in rails]
    if len(rows) != 1:
        refuse("CURRENT_PATH_UNSUPPORTED", f"{budget.net} spans {len(rows)} rows; only one rail is sized")
    tables = (compiled.pin_spec or {}).get("resistance_ohm", {})
    current = compiled.pin_spec["ports"][net].get("em", {}).get("current_mA")
    if not current:
        refuse("CURRENT_UNDECLARED", f"{budget.net} has no declared current in the block specification")
    level, rail = int(pin["layer"][5:]), plan.rail_level
    cuts = [tables.get("cut", {}).get(k) for k in range(rail, level)]
    sheets = tables.get("metal_per_square", {})
    sheet, leg_sheet, pin_sheet = (sheets.get(k) for k in (rail, rail + 1, level))
    if not sheet or not leg_sheet or not pin_sheet or not all(cuts):
        refuse("RESISTANCE_UNDECLARED", f"the tech LEF states no resistance for the {budget.net} path")
    ry = rows[0][net]
    groups = [group for device in plan.intent_placed if device["dev"]["name"] == budget.device
              for group in device["groups"] if group["net"] == net and not group.get("body_tap")]
    legs = tuple(leg_sheet * abs(group["abs_escape_y"] - ry) / geo.wire[rail + 1] + cuts[0] for group in groups)
    source = (pin["strip_box"][0] + pin["strip_box"][2]) // 2
    label = pin["label_box"]
    pin_run = abs((label[0] + label[2]) // 2 - source) + abs((label[1] + label[3]) // 2 - ry)
    return net, CurrentPath(current, budget.ir_drop_mv, tuple(cuts), sheet, pin_sheet, pin_run, source,
                            tuple(group["lane_x"] for group in groups), legs)


def _drawn_size(plan, net, cuts):
    box = plan.intent_rail_boxes[net]
    return PathSize(box[3] - box[1], cuts, plan.intent_pin_widths[net])


def _build_current_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec, intent, raw, options):
    """Measure each governed path on a first route, then route once more at its derived size."""
    if options.get("shared_capacitor_escapes"):
        refuse("CURRENT_PATH_UNSUPPORTED", "current budgets size the single-rail placer's rails")
    probe = build_intent_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec,
                              dataclasses.replace(intent, currents=()), options)
    compiled = compile_branches(intent, devs, ports, pin_spec)
    paths = {budget: _current_path(probe, budget, compiled, base_geo) for budget in intent.currents}
    sizes = {net: path.size() for net, path in paths.values()}
    # A larger cut array can only seat further along its rail, and a wider rail
    # pushes the pin run; re-derive both wires until the drawn path meets its budget.
    for _ in range(CURRENT_ROUTE_PASSES):
        plan = build_intent_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec,
                                 dataclasses.replace(intent, currents=()), options, path_sizes=sizes)
        paths = {budget: _current_path(plan, budget, compiled, base_geo) for budget in intent.currents}
        drawn = {net: _drawn_size(plan, net, sizes[net].cuts) for net, _ in paths.values()}
        over = {net: path for net, path in paths.values() if path.total_ohm(drawn[net]) > path.budget_ohm + 1e-9}
        if not over:
            break
        sizes.update({net: path.resize(drawn[net]) for net, path in over.items()})
    else:
        net, path = next(iter(over.items()))
        size = drawn[net]
        refuse("IR_BUDGET_UNACHIEVED", f"{compiled.canonical[net]}: {path.total_ohm(size):.3f} ohm drawn > "
               f"{path.budget_ohm:.3f} ohm budget (stack {path.stack_ohm(size.cuts):.3f} at {size.cuts} cuts, "
               f"rail {path.rail_ohm(size.rail_lam):.3f} at {size.rail_lam / base_geo.lam:g} um, "
               f"pin wire {path.pin_ohm(size.pin_lam):.3f}, legs {path.legs_ohm:.3f})")
    evidence = []
    for budget, (net, path) in paths.items():
        size = drawn[net]
        evidence.append({"kind": "current_budget", "net": budget.net, "device": budget.device,
                         "current_mA": path.current_ma, "ir_drop_budget_mV": budget.ir_drop_mv,
                         "rail_width_um": size.rail_lam / base_geo.lam, "pin_width_um": size.pin_lam / base_geo.lam,
                         "cuts_per_via": size.cuts,
                         "modelled_ohm": {"stack": path.stack_ohm(size.cuts), "rail": path.rail_ohm(size.rail_lam),
                                          "pin_wire": path.pin_ohm(size.pin_lam), "terminal_legs": path.legs_ohm,
                                          "total": path.total_ohm(size)}})
    plan.routing_intent_evidence["declaration"] = raw if isinstance(raw, dict) else None
    plan.routing_intent_evidence["constraints"].extend(evidence)
    return plan


def build_intent_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec, raw, options,
                      path_sizes=None):
    import analog_a5_layout_emit as a5
    intent = raw if isinstance(raw, RoutingIntent) else parse_intent(raw)
    if intent.currents:
        return _build_current_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec, intent, raw, options)
    if not (intent.topology or intent.widths or intent.separations):
        return a5._build_plan(devs, ports, cells, facts, base_geo, tap_clear, pin_spec, **options)
    compiled = compile_branches(intent, devs, ports, pin_spec)
    for net, size in (path_sizes or {}).items():
        spec = compiled.pin_spec["ports"][net]
        spec["cuts"] = max(spec["cuts"], size.cuts)
        spec["width_lam"] = max(spec["width_lam"], size.pin_lam)
    geo = copy.deepcopy(base_geo)
    geo.intent_strict = True
    geo.intent_cuts = {private: next((width.via_cuts for width in intent.widths if width.net == net), 1)
                       for private, net in compiled.canonical.items()}
    minimum = max([geo.rules["metal_width_um"].get(k, 0) for k in (1, 2, 3)])
    for width in intent.widths:
        if width.wire_width_um + 1e-12 < minimum:
            refuse("WIDTH_BELOW_PDK_MINIMUM", f"{width.net} width {width.wire_width_um:g}um < {minimum:g}um")
    reserve_width = max([math.ceil(width.wire_width_um * geo.lam - 1e-9) for width in intent.widths] + [0])
    geo.wire = {level: 2 * math.ceil(max(value, reserve_width) / 2) for level, value in geo.wire.items()}
    reserve_space = max([math.ceil(item.spacing_um * geo.lam - 1e-9) for item in intent.separations if item.spacing_um is not None] + [0])
    geo.space = {level: max(value, reserve_space) for level, value in geo.space.items()}
    geo.default_space = max(geo.default_space, reserve_space)
    profiles = {}
    for private, net in compiled.canonical.items():
        profile = copy.deepcopy(base_geo)
        profile.intent_strict = True
        profile.intent_cuts = geo.intent_cuts
        policy = next((width for width in intent.widths if width.net == net), None)
        requested = math.ceil(policy.wire_width_um * geo.lam - 1e-9) if policy else 0
        profile.wire = {level: 2 * math.ceil(max(value, requested) / 2) for level, value in profile.wire.items()}
        if policy:
            half = math.ceil(requested / 2)
            for level in profile.short_half:
                profile.short_half[level] = max(profile.short_half[level], half)
                profile.long_half[level] = max(profile.long_half[level], profile.short_half[level])
                profile.enc_half[level] = max(profile.enc_half[level], half)
                profile.patch[level] = max(profile.patch[level], profile.long_half[level])
        profile.space = dict(geo.space)
        profile.default_space = geo.default_space
        profile.rail_wire = path_sizes[private].rail_lam if private in (path_sizes or {}) else 0
        profiles[private] = profile
    for private, profile in profiles.items():
        cuts = profile.intent_cuts.get(private, 1)
        for level in profile.patch:
            if level not in profile.rules["via_width_um"]:
                continue
            _, bars = a5._pin_stack_boxes(0, 0, level, level + 1, profile, cuts)
            envelope = max(abs(value) for box in bars.values() for value in box)
            profile.patch[level] = max(profile.patch[level], envelope)
            geo.patch[level] = max(geo.patch[level], envelope)
    geo.intent_profiles = profiles
    if compiled.pin_spec:
        for topology in intent.topology:
            if not isinstance(topology.join, Port):
                continue
            owner = compiled.joins[topology.net]
            spec = compiled.pin_spec["ports"][owner]
            profile = profiles[owner]
            level = spec["level"]
            _, bars = a5._pin_stack_boxes(0, 0, level, level + 1, profile, profile.intent_cuts.get(owner, 1))
            spec["width_lam"] = max(spec["width_lam"], 2 * max(abs(bars[level][0]), abs(bars[level][2])))
    try:
        plan = a5._build_plan(compiled.devices, compiled.ports, cells, facts, geo, tap_clear,
                              compiled.pin_spec, **options)
    except a5.Refusal as exc:
        refuse("NO_LEGAL_ROUTE", str(exc))
    plan.intent_rail_boxes = dict(plan.rail_box)
    plan.intent_pin_widths = {compiled.joins.get(compiled.canonical.get(pin["net"], pin["net"]), pin["net"]): pin["width_lam"]
                              for pin in plan.pins}
    _anchors(plan, compiled, a5)
    regions = {}
    band = 1
    junction_layers = {}
    for topology in intent.topology:
        owner = compiled.joins[topology.net]
        net_geo = geo.for_net(owner)
        others = [branch for branch in compiled.branches[topology.net] if branch != owner]
        friendly = None
        if isinstance(topology.join, Port):
            region, level, top, targets = _join_port(plan, owner, len(others), band, compiled, net_geo, a5)
            band += len(others) + 3
        else:
            region, level, top, targets, friendly = _join_terminal(plan, topology, compiled, net_geo, a5)
        load_layer = f"metal{level}" if friendly is None else plan.intent_anchors[topology.join][0]["layer"]
        lowest = min(level, int(load_layer[5:]))
        junction_layers[topology.net] = tuple([f"metal{k}" for k in range(lowest, top + 1)]
                                                + [f"via{k}" for k in range(lowest, top)])
        regions[topology.net] = {"box": region, "layers": junction_layers[topology.net],
                                 "load_layer": load_layer, "native_component": friendly}
        for branch, target in zip(others, targets):
            _connect_branch(plan, branch, owner, region, level, top, target, compiled, geo.for_net(branch), a5, friendly, junction_layers[topology.net])
    shield_evidence = build_shields(plan, compiled, geo, facts, a5)
    evidence = verify_topology(plan, compiled, regions, a5._linked)
    evidence.extend(shield_evidence)
    evidence.extend(verify_separation(plan, compiled, geo, a5))
    for width in intent.widths:
        selected = [row for row in plan.shapes if compiled.canonical.get(row["net"], row["net"]) == width.net
                    and row["layer"].startswith("metal")
                    and (row["layer"], tuple(row["box"])) not in plan.patch_of]
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
    plan.routing_intent_evidence = {"version": 1, "declaration": raw if isinstance(raw, dict) else None, "constraints": evidence,
                                    "width_semantics": "per-net minimum; placement reserves the widest declared corridor"}
    return plan
