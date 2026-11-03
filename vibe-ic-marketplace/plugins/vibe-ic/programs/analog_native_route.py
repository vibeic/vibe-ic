#!/usr/bin/env python3
"""A11 placement of declared banks as macros, routed by native OpenROAD.

`steps.A11.floorplan.routing` selects this path. Each base-plane bank becomes
macros of the PDK's own device cells with every terminal a macro pin. Each column
of an upper-plane bank becomes a macro overlapping them. OpenROAD's global and
detailed routers connect the pins, and KLayout merges routed DEF with macro GDS
through the PDK's own layer map. Sign-off stays with the native A12 and A13 steps.
"""
from __future__ import annotations

import math
import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DBU_PER_UM = 1000
GRID = 5


class RouteRefused(RuntimeError):
    """A named reason this path cannot produce the declared layout."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def um(value: float) -> int:
    """Microns to database units, on the manufacturing grid."""
    return int(round(value * DBU_PER_UM / GRID)) * GRID


def layer_numbers(map_text: str) -> Dict[str, Tuple[int, int]]:
    """{LEF layer: (GDS layer, datatype)} from a KLayout LEF/DEF layer map."""
    numbers: Dict[str, Tuple[int, int]] = {}
    for line in map_text.splitlines():
        fields = line.split()
        if len(fields) == 4 and {"NET", "VIA"} & set(fields[1].split(",")) and fields[0] not in numbers:
            numbers[fields[0]] = (int(fields[2]), int(fields[3]))
    return numbers


def lef_stack(lef_text: str) -> Tuple[List[str], List[str], Dict[str, Tuple[float, float]]]:
    """(ROUTING layers, CUT layers, {routing layer: (x pitch, y pitch)}), bottom up."""
    routing: List[str] = []
    cuts: List[str] = []
    pitch: Dict[str, Tuple[float, float]] = {}
    for name, body in re.findall(r"^LAYER\s+(\S+)\s*$(.*?)^END\s+\1\s*$", lef_text, re.M | re.S):
        kind = re.search(r"\bTYPE\s+(\S+)", body)
        kind = kind.group(1) if kind else ""
        if kind == "ROUTING":
            routing.append(name)
            values = re.search(r"\bPITCH\s+([\d.]+)(?:\s+([\d.]+))?", body)
            if values:
                pitch[name] = (float(values.group(1)), float(values.group(2) or values.group(1)))
        elif kind == "CUT" and routing:
            cuts.append(name)
    return routing, cuts, pitch


def group_devices(banks: Sequence[dict], keepout: Sequence[str]) -> Tuple[List[List[str]], List[str]]:
    """(base-plane banks with keep-out devices first as their own, upper-plane devices)."""
    held = [n for bank in banks for n in bank["members"]
            if bank.get("plane") != "above"
            and any(fnmatchcase(n, pattern) for pattern in keepout)]
    groups = [held] if held else []
    above: List[str] = []
    for bank in banks:
        if bank.get("plane") == "above":
            above.extend(bank["members"])
            continue
        members = [n for n in bank["members"] if n not in held]
        if members:
            groups.append(members)
    return groups, above


def wrap_by_width(members: Sequence[str], width_of, limit: int, gap: int) -> List[List[str]]:
    """Consecutive runs whose packed width stays within `limit`, in the given order."""
    runs: List[List[str]] = []
    run: List[str] = []
    x = 0
    for name in members:
        width = width_of(name)
        if run and x + width > limit:
            runs.append(run)
            run, x = [], 0
        run.append(name)
        x += width + gap
    if run:
        runs.append(run)
    return runs


def shelf_pack(macros: Sequence[dict], left: int, bottom: int, width: int, gap: int) -> Tuple[int, int]:
    """Place macros left to right on shelves. Returns (right edge, top edge)."""
    x, y, shelf = left, bottom, 0
    right = top = bottom
    for macro in macros:
        if x + macro["w"] > left + width and x > left:
            x, y, shelf = left, y + shelf + gap, 0
        macro["x"], macro["y"] = x, y
        x += macro["w"] + gap
        shelf = max(shelf, macro["h"])
        right, top = max(right, macro["x"] + macro["w"]), max(top, y + macro["h"])
    return right, top


def columns_by_height(heights: Sequence[Tuple[str, int]], limit: int, start: int) -> List[List[Tuple[str, int]]]:
    """[(name, y)] columns, in order, with each column below `limit`."""
    columns: List[List[Tuple[str, int]]] = []
    column: List[Tuple[str, int]] = []
    y = start
    for name, height in heights:
        if column and y + height > limit:
            columns.append(column)
            column, y = [], start
        column.append((name, y))
        y += height
    if column:
        columns.append(column)
    return columns


def common_centroid_columns(sets: Sequence[Sequence[Tuple[str, int]]], limit: int, start: int,
                            grid: int) -> List[List[Tuple[str, int]]]:
    """One array of identical pitch for units that define a ratio, as [(name, y)] columns.

    `sets` holds one list of (name, height) per matched device. Opposite slots go to
    the same device, so each device's centroid stays on the array centre. A device
    with an odd unit count takes one slot alone, nearest the centre."""
    units = [(index, name, height) for index, group in enumerate(sets) for name, height in group]
    if not units:
        return []
    pitch = max(height for _, _, height in units)
    pitch += -pitch % grid
    rows = max((limit - start) // pitch, 1)
    cols = -(-len(units) // rows)
    rows = -(-len(units) // cols)
    centre = ((cols - 1) / 2, (rows - 1) / 2)
    slots = sorted(((c, r) for c in range(cols) for r in range(rows)),
                   key=lambda s: ((s[0] - centre[0]) ** 2 + (s[1] - centre[1]) ** 2, s))
    left = [list(group) for group in sets]
    placed: Dict[Tuple[int, int], Tuple[str, int]] = {}
    free = list(slots)
    last = None
    for group in sorted(left, key=len):
        if len(group) % 2:
            mirror = last and (cols - 1 - last[0], rows - 1 - last[1])
            last = mirror if mirror in free else free[0]
            free.remove(last)
            placed[last] = group.pop(0)
    pairs = []
    while free:
        slot = free.pop(0)
        mirror = (cols - 1 - slot[0], rows - 1 - slot[1])
        if mirror in free:
            free.remove(mirror)
            pairs.append((slot, mirror))
    spare = [group for group in left if group]
    totals = {id(group): len(group) for group in spare}
    for pair in pairs:
        spare = [group for group in spare if group]
        if not spare:
            break
        group = max(spare, key=lambda g: len(g) / totals[id(g)])
        for slot in pair:
            if group:
                placed[slot] = group.pop(0)
    columns: List[List[Tuple[str, int]]] = [[] for _ in range(cols)]
    for (c, r), (name, height) in sorted(placed.items()):
        offset = (pitch - height) // 2
        columns[c].append((name, start + r * pitch + offset - offset % grid))
    return [column for column in columns if column]


def centroid_distance_um(members: Sequence[Sequence[str]], place: Dict[str, Tuple[float, float]]) -> float:
    """Largest distance between the centroids of matched devices, from placed plate centres."""
    centres = []
    for group in members:
        points = [place[name] for name in group]
        centres.append((sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)))
    return round(max((math.dist(a, b) for a in centres for b in centres), default=0.0), 3)


def signal_pin_sites(signal: Sequence[str], far_edge: Sequence[str], start: float, pitch: float,
                     top: float) -> List[Tuple[str, float, float]]:
    """(port, x, y) of each signal pin, on the bottom edge unless declared for the far edge."""
    sites = []
    for edge_ports, y in (([p for p in signal if p not in far_edge], 0.4),
                          ([p for p in signal if p in far_edge], top - 0.4)):
        sites += [(p, start + i * pitch, y) for i, p in enumerate(edge_ports)]
    return sites


def supply_rule(current_ma: float, lef_layers: Sequence[dict], routing: Sequence[str], low: int, high: int,
                space_um) -> dict:
    """Wire width per routed layer from the declared current and the LEF's current density."""
    density = {layer["name"]: layer.get("dc_density") for layer in lef_layers}
    rule = {}
    for index, name in enumerate(routing[low - 1:high], low):
        width = math.ceil(current_ma / density[name] * 200) / 200
        rule[name] = {"width_um": width, "space_um": space_um(index, width)}
    return rule


def spaced_rule(lef_layers: Sequence[dict], routing: Sequence[str], low: int, high: int,
                factor: float, space_um) -> dict:
    """A net class at the LEF's minimum width, with `factor` times the layer's spacing."""
    width = {layer["name"]: layer["width"] for layer in lef_layers}
    return {name: {"width_um": width[name], "space_um": round(space_um(index, width[name]) * factor, 3)}
            for index, name in enumerate(routing[low - 1:high], low)}


def strap_gaps(columns: int, pairs: int) -> List[int]:
    """Column indexes after which a supply strap pair sits, evenly through the plane."""
    if columns < 2 or not pairs:
        return []
    return sorted({max(1, round(columns * k / (pairs + 1))) - 1 for k in range(1, pairs + 1)})


def route_violations(report_text: str) -> int:
    """The number of violations in a detailed-route DRC report."""
    return len(re.findall(r"violation type", report_text))


def site_name(lef_text: str) -> Optional[str]:
    """The first SITE a LEF defines; the floorplanner needs one before it is removed."""
    found = re.search(r"^\s*SITE\s+(\S+)\s*$", lef_text, re.M)
    return found.group(1) if found else None


def route_tcl(top: str, tech_lef: str, cell_lef: str, site: str,
              pitch: Dict[str, Tuple[float, float]], routing: Sequence[str],
              die: Tuple[float, float], macros: Sequence[dict], signal_pins: Sequence[Tuple[str, float, float]],
              pin_layer: str, routing_cfg: dict, net_classes: Sequence[dict] = ()) -> str:
    """The OpenROAD script: native floorplan, macro placement, global and detailed route."""
    low, high = routing_cfg["routing_layers"]
    margin = 8
    lines = [
        f"read_lef {{{tech_lef}}}", f"read_lef {{{cell_lef}}}", "read_lef macros.lef", "read_verilog top.v",
        f"link_design {top}",
        f'initialize_floorplan -die_area "0 0 {die[0] + margin} {die[1] + margin}" '
        f'-core_area "0 0 {die[0] + margin} {die[1] + margin}" -site {site}']
    for layer in routing:
        if layer in pitch:
            x, y = pitch[layer]
            lines.append(f"make_tracks {layer} -x_offset {x / 2 if x > 1 else 0.0} -x_pitch {x} "
                         f"-y_offset {y / 2 if y > 1 else 0.0} -y_pitch {y}")
    for macro in macros:
        lines.append(f"place_macro -macro_name u_{macro['name']} -location "
                     f"[list {macro['x'] / DBU_PER_UM} {macro['y'] / DBU_PER_UM}] "
                     "-orientation R0 -exact -allow_overlap")
    lines += [
        "set block [ord::get_db_block]",
        f"$block setDieArea [odb::new_Rect 0 0 {int(die[0] * DBU_PER_UM)} {int(die[1] * DBU_PER_UM)}]",
        "foreach r [$block getRows] { odb::dbRow_destroy $r }"]
    for name, x, y in signal_pins:
        lines.append(f"place_pin -pin_name {name} -layer {pin_layer} -location [list {x} {y}] "
                     "-pin_size {0.3 0.8}")
    lines.append(f"set_routing_layers -signal {routing[low - 1]}-{routing[high - 1]}")
    for net_class in net_classes:
        rule = net_class["rule"]
        widths = " ".join(f"{name} {spec['width_um']}" for name, spec in rule.items())
        spaces = " ".join(f"{name} {spec['space_um']}" for name, spec in rule.items())
        lines.append(f"create_ndr -name {net_class['name']} -spacing {{{spaces}}} -width {{{widths}}}")
        lines += [f"assign_ndr -ndr {net_class['name']} -net {net}" for net in net_class["nets"]]
    for index, adjustment in zip(range(low, high + 1), (0.7, 0.3, 0.2, 0.2)):
        lines.append(f"set_global_routing_layer_adjustment {routing[index - 1]} {adjustment}")
    lines += [
        "global_route -allow_congestion -congestion_iterations 30",
        f"set_thread_count {routing_cfg['threads']}",
        f"detailed_route -output_drc drt_drc.rpt -droute_end_iter "
        f"{routing_cfg['detailed_route_iterations']} -verbose 1 -clean_patches",
        "write_def routed.def", 'puts "A11_ROUTE_DONE"', "exit"]
    return "\n".join(lines) + "\n"


class MacroBuilder:
    """Macro cells and their LEF, from the device cells' own mask geometry."""

    def __init__(self, kdb, devices_gds: Sequence[str], numbers: Dict[str, Tuple[int, int]],
                 routing: Sequence[str], cuts: Sequence[str], rules: dict) -> None:
        self.kdb = kdb
        self.source = kdb.Layout()
        for path in devices_gds:
            self.source.read(path)
        self.layout = kdb.Layout()
        self.layout.dbu = 1.0 / DBU_PER_UM
        self.routing, self.cuts = list(routing), list(cuts)
        self.numbers = numbers
        self.rules = rules
        self.masters: Dict[str, object] = {}
        self.lef: List[str] = []
        self.instances: List[Tuple[str, Dict[str, str]]] = []

    def out(self, name: str) -> int:
        return self.layout.layer(*self.numbers[name])

    def src(self, name: str) -> int:
        return self.source.layer(*self.numbers[name])

    def master(self, name: str):
        if name not in self.masters:
            cell = self.layout.create_cell(name)
            cell.copy_tree(self.source.cell(name))
            self.masters[name] = cell
        return self.masters[name]

    def bbox(self, cell_name: str):
        return self.source.cell(cell_name).bbox()

    def _rects(self, region) -> List:
        return [t.bbox() for t in region.merged().decompose_trapezoids_to_region().each()]

    def write_lef(self, name: str, w: int, h: int, pins: Dict[str, Tuple[str, Dict[str, List]]],
                  obs: Dict[str, List]) -> None:
        def rect(b):
            return (f"{b.left / DBU_PER_UM:.3f} {b.bottom / DBU_PER_UM:.3f} "
                    f"{b.right / DBU_PER_UM:.3f} {b.top / DBU_PER_UM:.3f}")
        text = [f"MACRO {name}", "  CLASS BLOCK ;", "  ORIGIN 0 0 ;", f"  FOREIGN {name} 0 0 ;",
                f"  SIZE {w / DBU_PER_UM:.3f} BY {h / DBU_PER_UM:.3f} ;", "  SYMMETRY X Y ;"]
        for pin, (_net, geometry) in pins.items():
            text += [f"  PIN {pin}", "    DIRECTION INOUT ;", "    USE SIGNAL ;", "    PORT"]
            for layer, boxes in geometry.items():
                text.append(f"      LAYER {layer} ;")
                text += [f"        RECT {rect(b)} ;" for b in boxes]
            text += ["    END", f"  END {pin}"]
        text.append("  OBS")
        for layer, boxes in obs.items():
            if boxes:
                text.append(f"    LAYER {layer} ;")
                text += [f"      RECT {rect(b)} ;" for b in boxes]
        text += ["  END", f"END {name}", ""]
        self.lef.extend(text)
        self.instances.append((name, {pin: spec[0] for pin, spec in pins.items()}))

    def device_terminals(self, cell_name: str, device_labels: Dict[str, List[dict]],
                         sections: Dict[str, List]) -> List[Tuple[str, str, object]]:
        """[(net, routing layer, polygon)] for one device, each polygon holding one net.

        A polygon holds a label when the label's point lies on it on the label's
        own level. An unlabelled polygon sits over a contact type: it belongs to
        the one net labelled on that type, which is how a gate contact at the far
        end of a finger is found. Anything else is refused by name."""
        cell = self.source.cell(cell_name)
        placed: List[Tuple[str, str, object]] = []
        levels = sorted({label["level"] for labels in device_labels.values() for label in labels})
        for level in levels:
            layer = self.routing[level - 1]
            polygons = list(self.kdb.Region(cell.begin_shapes_rec(self.src(layer))).merged().each())
            here = [(net, label) for net, labels in device_labels.items()
                    for label in labels if label["level"] == level]
            for polygon in polygons:
                held = {net for net, label in here if polygon.inside(self.kdb.Point(
                    int(label["x"] * 10), int(label["y"] * 10)))}
                if not held:
                    box = polygon.bbox()
                    over = {name for name, rects in sections.items() if any(
                        r[0] * 10 < box.right and box.left < r[2] * 10
                        and r[1] * 10 < box.top and box.bottom < r[3] * 10 for r in rects)}
                    held = {net for net, label in here if label.get("layer") in over}
                    if not held and level == 1:
                        continue
                if len(held) != 1:
                    raise RouteRefused("TERMINAL_AMBIGUOUS",
                                       f"{cell_name}: {layer} polygon {polygon.bbox()} holds {sorted(held)}")
                placed.append((held.pop(), layer, polygon))
        return placed

    def grow_to_min_area(self, polygons: Sequence, footprint) -> List:
        """Extra rectangles bringing each small polygon to the deck's minimum area,
        placed where the deck can see them instead of leaving it to router patches."""
        kdb = self.kdb
        need = self.rules["min_area_dbu2"]
        space = self.rules["space_dbu"]
        region = kdb.Region()
        for polygon in polygons:
            region.insert(polygon)
        region.merge()
        extra: List = []
        cy, cx = footprint.center().y, footprint.center().x
        for polygon in list(region.each()):
            b = polygon.bbox()
            if polygon.area() >= need:
                continue

            def rounded(value):
                value = int((need - polygon.area()) / value) + 10
                return value + (GRID - value % GRID) % GRID
            up = kdb.Box(b.left, b.top, b.right, b.top + rounded(b.width()))
            down = kdb.Box(b.left, b.bottom - rounded(b.width()), b.right, b.bottom)
            left = kdb.Box(b.left - rounded(b.height()), b.bottom, b.left, b.top)
            right = kdb.Box(b.right, b.bottom, b.right + rounded(b.height()), b.top)
            order = (up, down) if b.center().y >= cy else (down, up)
            order += (left, right) if b.center().x < cx else (right, left)
            others = region - kdb.Region(polygon)
            for candidate in order:
                if (others & kdb.Region(candidate.enlarged(space, space))).is_empty():
                    extra.append(candidate)
                    region.insert(candidate)
                    break
            else:
                raise RouteRefused("MIN_AREA_NO_ROOM", f"polygon {b} cannot reach the deck's minimum area")
        return extra

    def device_macro(self, name: str, members: Sequence[dict], gap: int) -> dict:
        """One macro of devices packed left to right, every terminal a pin."""
        kdb = self.kdb
        cell = self.layout.create_cell(name)
        pins: Dict[str, Tuple[str, Dict[str, List]]] = {}
        obs: Dict[str, object] = {}
        x = 0
        placed = []
        for member in members:
            box = self.bbox(member["cell"])
            placed.append((member, box, x - box.left))
            x += box.width() + gap
        width = x - gap
        height = max(box.height() for _, box, _ in placed)
        low, cut = self.routing[0], self.cuts[0]
        second = self.routing[1]
        for member, box, ox in placed:
            shift = kdb.Trans(0, False, ox, -box.bottom)
            cell.insert(kdb.CellInstArray(self.master(member["cell"]).cell_index(), shift))
            source = self.source.cell(member["cell"])
            terminals = self.device_terminals(member["cell"], member["labels"], member["sections"])
            on_second = [polygon for _, layer, polygon in terminals if layer == second]
            growth = self.grow_to_min_area(on_second, box)
            for rect in growth:
                cell.shapes(self.out(second)).insert(rect.transformed(shift))
            grown = kdb.Region()
            for polygon in on_second:
                grown.insert(polygon)
            for rect in growth:
                grown.insert(rect)
            grown.merge()
            pinned_low = kdb.Region()
            for index, (net, layer, polygon) in enumerate(terminals):
                if layer == second:
                    touching = [q for q in grown.each() if q.bbox().touches(polygon.bbox())]
                    region = kdb.Region()
                    for q in touching:
                        region.insert(q)
                else:
                    pinned_low.insert(polygon)
                    region = kdb.Region(polygon)
                pins[f"{member['name']}__t{index}"] = (
                    net, {layer: self._rects(region.transformed(shift))})
            low_all = kdb.Region(source.begin_shapes_rec(self.src(low))).merged()
            cut_all = kdb.Region(source.begin_shapes_rec(self.src(cut))).merged()
            obs.setdefault(low, kdb.Region())
            obs.setdefault(cut, kdb.Region())
            obs[low] += (low_all - pinned_low).transformed(shift)
            obs[cut] += cut_all.sized(150).sized(-150).transformed(shift)
        self.write_lef(name, width, height, pins,
                       {low: self._rects(obs[low]),
                        cut: [p.bbox() for p in obs[cut].merged().each()], second: []})
        return {"name": name, "w": width, "h": height, "devices": [m["name"] for m in members],
                "plane": "base"}

    def _stack(self, cell, x: float, y: float, cut_um: float, pad_um: float, cut_layer: str, pad_layer: str):
        half = um(cut_um / 2)
        cell.shapes(self.out(cut_layer)).insert(self.kdb.Box(
            um(x) - half, um(y) - half, um(x) + half, um(y) + half))
        pad = um(pad_um / 2)
        box = self.kdb.Box(um(x) - pad, um(y) - pad, um(x) + pad, um(y) + pad)
        cell.shapes(self.out(pad_layer)).insert(box)
        return box

    def cap_column(self, name: str, column: Sequence[Tuple[dict, int]], width: int, stem: dict,
                   plane_levels: Tuple[int, int, int]) -> dict:
        """One column of MIM cells. Each plate leaves through a pin on the top routed plane."""
        kdb = self.kdb
        pad_level, bottom_level, top_level = plane_levels
        pad_layer = self.routing[pad_level - 1]
        lower_cut = self.cuts[pad_level - 1]
        bottom_layer = self.routing[bottom_level - 1]
        top_cut = self.cuts[bottom_level - 1]
        top_layer = self.routing[top_level - 1]
        cell = self.layout.create_cell(name)
        pins: Dict[str, Tuple[str, Dict[str, List]]] = {}
        height = 0
        centre = width / 2 / DBU_PER_UM
        for member, y in column:
            box = self.bbox(member["cell"])
            base = y / DBU_PER_UM
            plate_h = box.height() / DBU_PER_UM
            shift = kdb.Trans(0, False, um(centre) - (box.left + box.right) // 2, y - box.bottom)
            cell.insert(kdb.CellInstArray(self.master(member["cell"]).cell_index(), shift))
            bx = centre + stem["bottom_x_um"]
            half = stem["bottom_tab_half_um"]
            cell.shapes(self.out(bottom_layer)).insert(kdb.Box(
                um(bx - half), um(base - stem["bottom_tab_um"]), um(bx + half), um(base)))
            bottom_pin = self._stack(cell, bx, base - stem["bottom_drop_um"], stem["lower_via_um"],
                                     stem["bottom_pad_um"], lower_cut, pad_layer)
            top = base + plate_h
            island_low = top + stem["island_gap_um"]
            island_y = island_low + stem["island_um"] / 2
            cell.shapes(self.out(bottom_layer)).insert(kdb.Box(
                um(centre - stem["island_um"] / 2), um(island_low),
                um(centre + stem["island_um"] / 2), um(island_low + stem["island_um"])))
            via = stem["top_via_um"] / 2
            cell.shapes(self.out(top_cut)).insert(kdb.Box(
                um(centre - via), um(island_y - via), um(centre + via), um(island_y + via)))
            upper = island_low + stem["island_um"] + stem["top_via_enclosure_um"]
            cell.shapes(self.out(top_layer)).insert(kdb.Box(
                um(centre - stem["tab_width_um"] / 2), um(top - stem["tab_overlap_um"]),
                um(centre + stem["tab_width_um"] / 2), um(upper)))
            top_pin = self._stack(cell, centre, island_y, stem["lower_via_um"], stem["top_pad_um"],
                                  lower_cut, pad_layer)
            nets = member["plate_nets"]
            pins[f"{member['name']}__top"] = (nets[0], {pad_layer: [top_pin]})
            pins[f"{member['name']}__bottom"] = (nets[1], {pad_layer: [bottom_pin]})
            height = max(height, um(upper))
        self.write_lef(name, width, height, pins, {})
        return {"name": name, "w": width, "h": height, "plane": "above",
                "devices": [m["name"] for m, _ in column]}

    def rail(self, net: str, x: int, height: int, cfg: dict, stem: dict,
             plane_levels: Tuple[int, int, int], suffix: str = "", y: int = 0) -> dict:
        """A top-metal strip stacked down to pins on the routed plane."""
        kdb = self.kdb
        pad_level, middle_level, top_level = plane_levels
        pad_layer = self.routing[pad_level - 1]
        lower_cut = self.cuts[pad_level - 1]
        middle = self.routing[middle_level - 1]
        top_cut = self.cuts[middle_level - 1]
        top_layer = self.routing[top_level - 1]
        name = f"rail_{net}{suffix}"
        cell = self.layout.create_cell(name)
        width = um(cfg["width_um"])
        cell.shapes(self.out(top_layer)).insert(kdb.Box(0, 0, width, height))
        count = max(2, int(height / DBU_PER_UM // cfg["via_pitch_um"]))
        pins = {}
        cx = cfg["width_um"] / 2
        for k in range(count):
            stack_y = 2.0 + k * (height / DBU_PER_UM - 4.0) / (count - 1)
            half = stem["top_via_um"] / 2
            cell.shapes(self.out(top_cut)).insert(kdb.Box(
                um(cx - half), um(stack_y - half), um(cx + half), um(stack_y + half)))
            island = stem["island_um"] / 2
            cell.shapes(self.out(middle)).insert(kdb.Box(
                um(cx - island), um(stack_y - island), um(cx + island), um(stack_y + island)))
            pin = self._stack(cell, cx, stack_y, stem["lower_via_um"], stem["top_pad_um"], lower_cut, pad_layer)
            pins[f"{net}_s{k}"] = (net, {pad_layer: [pin]})
        self.write_lef(name, width, height, pins, {})
        return {"name": name, "w": width, "h": height, "x": x, "y": y, "plane": "rail", "devices": [],
                "net": net, "stacks": count}

    def verilog(self, top: str, ports: Sequence[str]) -> str:
        nets = sorted({net for _, conn in self.instances for net in conn.values()} - set(ports))
        lines = [f"module {top} ({', '.join(ports)});"] + [f"  inout {p};" for p in ports]
        lines += [f"  wire {net};" for net in nets]
        for name, conn in self.instances:
            lines.append(f"  {name} u_{name} (" + ", ".join(
                f".{pin}({net})" for pin, net in conn.items()) + ");")
        return "\n".join(lines + ["endmodule", ""])

    def write(self, directory: Path) -> None:
        (directory / "macros.lef").write_text(
            'VERSION 5.7 ;\nBUSBITCHARS "[]" ;\nDIVIDERCHAR "/" ;\n\n' + "\n".join(self.lef) + "\nEND LIBRARY\n")
        self.layout.write(str(directory / "macros.gds"))


def merge_routed(kdb, directory: Path, tech_lef: str, map_file: str, top_name: str, output: Path,
                 rails: Sequence[dict], pin_layer_for: str, die_top: int, numbers) -> dict:
    """Routed DEF plus macro GDS into one GDS, on the PDK's own layer map."""
    config = kdb.LEFDEFReaderConfiguration()
    config.map_file = map_file
    config.lef_files = [tech_lef, str(directory / "macros.lef")]
    config.macro_layout_files = [str(directory / "macros.gds")]
    config.macro_resolution_mode = 2
    config.read_lef_with_def = False
    config.produce_cell_outlines = False
    config.produce_placement_blockages = False
    config.produce_regions = False
    config.produce_blockages = False
    options = kdb.LoadLayoutOptions()
    options.lefdef_config = config
    layout = kdb.Layout()
    layout.read(str(directory / "routed.def"), options)
    top = layout.top_cell()
    if top.name != top_name:
        raise RouteRefused("MERGE_TOP_MISMATCH", f"routed DEF top {top.name}, expected {top_name}")
    number, _ = numbers[pin_layer_for]
    text = layout.layer(number, 25)
    pin = layout.layer(number, 2)
    for rail in rails:
        if rail["y"]:
            continue
        cx = rail["x"] + rail["w"] // 2
        top.shapes(text).insert(kdb.Text(rail["net"], kdb.Trans(cx, die_top // 2)))
        top.shapes(pin).insert(kdb.Box(rail["x"], 0, rail["x"] + rail["w"], die_top))
    layout.write(str(output))
    box = top.bbox().to_dtype(layout.dbu)
    return {"width_um": box.width(), "height_um": box.height(), "area_um2": box.width() * box.height(),
            "bbox_um": [box.left, box.bottom, box.right, box.top]}
