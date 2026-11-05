"""Native placement and KLayout readback of analog macro views.

Coordinates and limits are in micrometres. The R0 placer checks the supplied
die/core limits, macro and LEF pin populations, technology-grid/access rules
and abstract overlap. Routing and DRC/LVS remain separate native steps.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _pad_ring import parse_lef_pin_ports



class Refusal(ValueError):
    pass


def read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise Refusal("D31_INPUT_INVALID: expected object")
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Refusal("D31_INPUT_INVALID: finite numeric constraint required")
    return float(value)


def box(value):
    if not isinstance(value, list) or len(value) != 4:
        raise Refusal("D31_INPUT_INVALID: rectangle required")
    x1, y1, x2, y2 = map(number, value)
    if x1 >= x2 or y1 >= y2:
        raise Refusal("D31_INPUT_INVALID: empty rectangle")
    return [x1, y1, x2, y2]


def bound_file(project, value):
    path = Path(value['path'] if isinstance(value, dict) else value)
    path = path if path.is_absolute() else Path(project) / path
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()



def lef_envelope(macro, master):
    """Read the adopted placement abstract; this R0 method supports zero origin.

    LEF SIZE describes placement occupancy even where no GDS polygon exists.
    It must not be replaced by a native geometry bbox or required to equal it.
    Nonzero LEF origins/foreign frames need a coordinate transform this bounded
    method does not implement, so they refuse rather than silently shifting.
    """
    header = re.split(r"(?m)^\s*(?:PIN|OBS)\b", macro, maxsplit=1)[0]
    statements = re.findall(r"\bSIZE\b([^;]*);", header)
    if len(statements) != 1:
        raise Refusal("D31_LEF_SIZE_INVALID: exactly one SIZE required")
    parts = statements[0].split()
    try:
        if len(parts) != 3 or parts[1] != "BY":
            raise ValueError("SIZE width BY height required")
        width, height = number(float(parts[0])), number(float(parts[2]))
        if width <= 0 or height <= 0:
            raise ValueError("positive dimensions required")
    except (ValueError, OverflowError) as exc:
        raise Refusal("D31_LEF_SIZE_INVALID: finite positive width/height required") from exc
    for keyword in ("ORIGIN", "FOREIGN"):
        values = re.findall(r"\b" + keyword + r"\b([^;]*);", header)
        if len(values) > 1 or (re.search(r"\b" + keyword + r"\b", header) and not values):
            raise Refusal("D31_LEF_FRAME_UNSUPPORTED: malformed " + keyword)
        if not values:
            continue  # LEF's omitted origin is (0, 0).
        fields = values[0].split()
        if keyword == "FOREIGN":
            if not fields or fields[0] != master:
                raise Refusal("D31_LEF_FRAME_UNSUPPORTED: foreign master")
            fields = fields[1:]
            if not fields:
                continue  # FOREIGN name without an explicit point.
        try:
            if len(fields) != 2 or any(number(float(x)) != 0 for x in fields):
                raise ValueError("zero frame required")
        except (ValueError, OverflowError) as exc:
            raise Refusal("D31_LEF_FRAME_UNSUPPORTED: " + keyword) from exc
    return [0.0, 0.0, width, height]


def load_inputs(project, options):
    """The inventory is independent of placements; omissions cannot shrink it."""
    project = Path(project).resolve(strict=True)
    plan = options
    def consume(value):
        return bound_file(project, value)
    expected = plan.get("instances")
    placements = plan.get("placements")
    if (not isinstance(expected, dict) or not expected or not isinstance(placements, dict)
            or set(expected) != set(placements)):
        raise Refusal("D31_MACRO_POPULATION_INCOMPLETE")
    if plan.get("units") != "um" or not isinstance(plan.get("limits"), dict):
        raise Refusal("D31_DECLARED_BOUNDS_UNAVAILABLE: explicit um limits required")
    limits = plan["limits"]
    die, core = box(limits.get("die")), box(limits.get("core"))
    if not (die[0] <= core[0] < core[2] <= die[2] and die[1] <= core[1] < core[3] <= die[3]):
        raise Refusal("D31_DECLARED_BOUNDS_INVALID: core outside die")
    min_access = number(limits.get("pin_access_min_width"))
    if min_access <= 0:
        raise Refusal("D31_DECLARED_BOUNDS_INVALID: pin access width")
    tech = consume(plan.get("technology_lef"))
    layer_map = consume(plan.get("layer_properties"))
    tech_text = tech.read_text()
    grid_match = re.search(r"\bMANUFACTURINGGRID\s+([\d.]+)\s*;", tech_text)
    if not grid_match or float(grid_match[1]) <= 0:
        raise Refusal("D31_TECHNOLOGY_GRID_UNAVAILABLE")
    grid = float(grid_match[1])
    layers = {}
    for item in ET.parse(layer_map).getroot().iter("properties"):
        name, source = item.findtext("name") or "", item.findtext("source") or ""
        match = re.fullmatch(r"(\d+)/(\d+)", source)
        if name.endswith(".drawing") and match:
            layers[name[:-8]] = tuple(map(int, match.groups()))
    rows = []
    for name, view in expected.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not isinstance(view, dict):
            raise Refusal("D31_MACRO_IDENTITY_INVALID")
        gds, lef = consume(view.get("gds")), consume(view.get("lef"))
        master = view.get("master")
        text = lef.read_text()
        macros = re.findall(r"(?ms)^MACRO\s+" + re.escape(str(master)) +
                            r"\s.*?^END\s+" + re.escape(str(master)) + r"\s*$", text)
        if len(macros) != 1:
            raise Refusal("D31_MACRO_VIEW_MISMATCH: " + name)
        macro = macros[0]
        envelope = lef_envelope(macro, master)
        ports = parse_lef_pin_ports(macro).get(master, {})
        census = re.findall(r"(?m)^\s*PIN\s+(\S+)\s*$", macro)
        if not census or len(census) != len(set(census)) or set(census) != set(ports):
            raise Refusal("D31_UNSUPPORTED_PIN_GEOMETRY: full RECT port census required")
        place = placements[name]
        if not isinstance(place, dict) or place.get("orientation") != "R0" or place.get("region") not in ("die", "core"):
            raise Refusal("D31_UNSUPPORTED_PLACEMENT: explicit R0 die/core placement required")
        xy = place.get("origin")
        if not isinstance(xy, list) or len(xy) != 2:
            raise Refusal("D31_PLACEMENT_ABSENT: " + name)
        xy = list(map(number, xy))
        if any(abs(v / grid - round(v / grid)) > 1e-7 for v in xy):
            raise Refusal("D31_PLACEMENT_OFF_TECHNOLOGY_GRID: " + name)
        pins = place.get("pins")
        if not isinstance(pins, dict) or set(pins) != set(census):
            raise Refusal("D31_PIN_POPULATION_INCOMPLETE: " + name)
        accesses = []
        for pin, access in pins.items():
            layer = access.get("layer") if isinstance(access, dict) else None
            layer_rule = re.search(r"(?ms)^LAYER\s+" + re.escape(str(layer)) + r"\s.*?^END\s+" + re.escape(str(layer)) + r"\s*$", tech_text)
            width = re.search(r"\bWIDTH\s+([\d.]+)\s*;", layer_rule[0]) if layer_rule else None
            if layer not in layers or not width or not re.search(r"\bTYPE\s+ROUTING\s*;", layer_rule[0]):
                raise Refusal("D31_PIN_LAYER_UNAVAILABLE: " + str(layer))
            rect = box(access.get("rect"))
            if (any(abs(v / grid - round(v / grid)) > 1e-7 for v in rect)
                    or min(rect[2]-rect[0], rect[3]-rect[1]) + 1e-9 < max(min_access, float(width[1]))):
                raise Refusal("D31_PIN_ACCESS_RULE_VIOLATION: " + name + "/" + pin)
            if not any(layer == port_layer and r[0] <= rect[0] and r[1] <= rect[1]
                       and rect[2] <= r[2] and rect[3] <= r[3] for port_layer, r in ports[pin]):
                raise Refusal("D31_PIN_ACCESS_OUTSIDE_LEF_PORT: " + name + "/" + pin)
            accesses.append(dict(name=pin, layer=list(layers[layer]), rect=rect))
        rows.append(dict(name=name, master=master, gds=str(gds), origin=xy,
                         region=place["region"], pins=accesses, lef_envelope=envelope))
    return dict(instances=rows, die=die, core=core)


def native(project, output, producing, options):
    """Actual native geometry readback, not a caller-supplied verdict."""
    import pya
    data = load_inputs(project, options)
    layout = pya.Layout()
    if producing:
        top = layout.create_cell("D31_FLOORPLAN")
        imported = {}
        for row in data["instances"]:
            key = (row["gds"], row["master"])
            if key not in imported:
                source = pya.Layout()
                source.read(row["gds"])
                cell = source.cell(row["master"])
                if cell is None or cell.is_empty():
                    raise Refusal("D31_NATIVE_MASTER_ABSENT: " + row["master"])
                if not imported:
                    layout.dbu = source.dbu
                if layout.dbu != source.dbu or layout.cell(row["master"]) is not None:
                    raise Refusal("D31_UNSUPPORTED_VIEW_COLLISION_OR_DBU")
                target = layout.create_cell(row["master"])
                target.copy_tree(cell)
                imported[key] = target
            x, y = row["origin"]
            if any(abs(v/layout.dbu-round(v/layout.dbu)) > 1e-7
                   for v in (x, y, *row["lef_envelope"])):
                raise Refusal("D31_UNREPRESENTABLE_GDS_COORDINATE")
            inst = top.insert(pya.CellInstArray(imported[key].cell_index(),
                pya.Trans(round(x/layout.dbu), round(y/layout.dbu))))
            inst.set_property(61, row["name"])
        layout.write(str(output / "floorplan.gds"))
        return {"gds": str(output / "floorplan.gds")}
    layout.read(str(output / "floorplan.gds"))
    top = layout.cell("D31_FLOORPLAN")
    if top is None or len(list(layout.top_cells())) != 1:
        raise Refusal("D31_NATIVE_TOP_MISMATCH")
    instances = list(top.each_inst())
    actual_names = [i.property(61) for i in instances]
    if len(actual_names) != len(set(actual_names)) or set(actual_names) != {r["name"] for r in data["instances"]}:
        raise Refusal("D31_NATIVE_MACRO_POPULATION_MISMATCH")
    if any(not top.shapes(li).is_empty() for li in layout.layer_indexes()):
        raise Refusal("D31_UNDECLARED_TOP_GEOMETRY")
    violations, footprints, observations = [], [], []
    def ibox(values):
        scaled = [v/layout.dbu for v in values]
        if any(abs(v-round(v)) > 1e-7 for v in scaled):
            raise Refusal("D31_UNREPRESENTABLE_GDS_COORDINATE")
        return pya.Box(*map(round, scaled))
    for row in data["instances"]:
        instance = instances[actual_names.index(row["name"])]
        expected_trans = pya.Trans(*[round(v/layout.dbu) for v in row["origin"]])
        if instance.is_regular_array() or instance.trans != expected_trans or instance.cell.name != row["master"]:
            raise Refusal("D31_NATIVE_PLACEMENT_MISMATCH: " + row["name"])
        source = pya.Layout()
        source.read(row["gds"])
        original = source.cell(row["master"])
        if original is None or original.is_empty() or source.dbu != layout.dbu:
            raise Refusal("D31_NATIVE_SOURCE_MISMATCH")
        # Reopen both original and emitted GDS and compare every geometry layer.
        layer_infos = set(source.layer_infos()) | set(layout.layer_infos())
        for info in layer_infos:
            si, oi = source.find_layer(info), layout.find_layer(info)
            sr = pya.Region(original.begin_shapes_rec(si)) if si is not None else pya.Region()
            emitted = pya.Region(instance.cell.begin_shapes_rec(oi)) if oi is not None else pya.Region()
            if not (sr ^ emitted).is_empty():
                raise Refusal("D31_NATIVE_VIEW_GEOMETRY_CHANGED: " + row["name"])
        # Both adopted abstract occupancy and actual native geometry matter.
        # Neither may silently shrink the other; real GDS overhang is legal
        # when the union still fits the declared placement region.
        abstract = ibox(row["lef_envelope"]).transformed(instance.trans)
        region = pya.Region(instance.bbox()) | pya.Region(abstract)
        if not (region - pya.Region(ibox(data[row["region"]]))).is_empty():
            violations.append("boundary:" + row["name"])
        footprints.append((row["name"], region))
        access_regions = []
        for pin in row["pins"]:
            local = ibox(pin["rect"])
            li = layout.find_layer(*pin["layer"])
            metal = pya.Region(instance.cell.begin_shapes_rec(li)) if li is not None else pya.Region()
            if not (pya.Region(local) - metal).is_empty():
                violations.append("native_pin_metal_absent:" + row["name"] + "/" + pin["name"])
            placed = pya.Region(local.transformed(instance.trans))
            if not (placed - pya.Region(ibox(data["die"]))).is_empty():
                violations.append("pin_boundary:" + row["name"] + "/" + pin["name"])
            for other, layer, area in access_regions:
                if layer == pin["layer"] and not (placed & area).is_empty():
                    violations.append("pin_access_overlap:" + row["name"] + "/" + other + "/" + pin["name"])
            access_regions.append((pin["name"], pin["layer"], placed))
        observations.append(dict(name=row["name"], master=row["master"],
            bbox_um=str(instance.dbbox()), lef_envelope_um=str(abstract.to_dtype(layout.dbu)),
            pins=len(row["pins"])))
    overlaps = []
    for index, (name, area) in enumerate(footprints):
        for other, other_area in footprints[:index]:
            if not (area & other_area).is_empty():
                overlaps.append([other, name])
    return dict(status="FAIL" if violations or overlaps else "PASS", violations=violations,
                illegal_macro_overlap=len(overlaps), overlap_pairs=overlaps,
                floorplan_boundary_pin_feasibility="FAIL" if violations else "PASS",
                instances=observations, gds=str(output / "floorplan.gds"))


def execute(project, context):
    project = Path(project).resolve(strict=True)
    output = project / "reports/phase3/analog_floorplan" / uuid.uuid4().hex
    output.mkdir(parents=True)
    record = {"component_status": "NOT_MEASURED", "native_started": False,
              "executions": [], "outputs": [],
              "scope": "Native macro placement and geometry; routing and DRC/LVS are separate"}
    try:
        options = context["floorplan"]
        load_inputs(project, options)
        executable = shutil.which("klayout")
        if not executable:
            raise FileNotFoundError("klayout")
        record["tool"] = executable
        for mode in ("produce", "consume"):
            request = output / (mode + "-request.json")
            request.write_text(json.dumps({"project": str(project), "output": str(output),
                                           "mode": mode, "options": options}, default=str))
            argv = [executable, "-b", "-r", str(Path(__file__).resolve()),
                    "-rd", "D31_REQUEST=" + str(request)]
            record["native_started"] = True
            result = subprocess.run(argv, text=True, capture_output=True)
            log = output / (mode + ".log")
            log.write_text(result.stdout + result.stderr)
            record["executions"].append({"argv": argv, "returncode": result.returncode,
                                         "log": str(log)})
            answer = read(output / (mode + ".json"))
            if result.returncode or answer.get("error"):
                raise Refusal(answer.get("error", "D31_NATIVE_ERROR"))
            if mode == "consume":
                record.update(component_status=answer["status"], measurements=answer)
        record["outputs"] = [str(output / "floorplan.gds"), str(output / "consume.json")]
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        record["reason"] = str(exc)
    (output / "result.json").write_text(json.dumps(record, indent=2))
    return record


if __name__ == "__main__" and "D31_REQUEST" in globals():
    request = read(globals()["D31_REQUEST"])
    output = Path(request["output"])
    try:
        answer = native(Path(request["project"]), output,
                        request["mode"] == "produce", request["options"])
    except Exception as exc:
        answer = {"error": type(exc).__name__ + ": " + str(exc)}
    (output / (request["mode"] + ".json")).write_text(json.dumps(answer, indent=2))
    if answer.get("error"):
        raise RuntimeError(answer["error"])
