#!/usr/bin/env python3
"""D31 analog-die placement of real macro views; BLOCKING geometry checks.

KLayout copies the supplied native cells and independently reopens the placed
GDS. This bounded R0 placer checks declared die/core limits, complete macro and
LEF pin populations, technology-grid/access rules and abstract overlap. It is
not routing, DRC/LVS, technology qualification or whole-die acceptance.
"""
from __future__ import annotations

import hashlib
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

PLAN = Path("input/flow109/D31.json")
BOUNDS = Path("requirements/base_20/floorplan_boundary_pin_feasibility.json")


class Refusal(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def bound_file(project, ref):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise Refusal("D31_INPUT_ABSENT: bound file reference required")
    rel = Path(ref["path"])
    if rel.is_absolute() or ".." in rel.parts:
        raise Refusal("D31_INPUT_FOREIGN: project-local input required")
    path = project / rel
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise Refusal("D31_INPUT_ABSENT: " + str(rel))
    if sha(path) != ref.get("sha256"):
        raise Refusal("D31_INPUT_STALE: " + str(rel))
    return path


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


def load_inputs(project):
    """The inventory is independent of placements; omissions cannot shrink it."""
    project = Path(project).resolve(strict=True)
    files = {}
    documents = []
    for rel in (PLAN, BOUNDS):
        path = project / rel
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise Refusal("D31_INPUT_FOREIGN: " + str(rel))
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise Refusal("D31_INPUT_INVALID: " + str(rel))
        documents.append(value)
        files[path] = hashlib.sha256(raw).hexdigest()
    plan, bounds = documents
    def consume(ref):
        path = bound_file(project, ref)
        files[path] = ref["sha256"]
        return path
    inventory = read(consume(plan.get("macro_inventory")))
    expected = inventory.get("instances")
    placements = plan.get("placements")
    if (not isinstance(expected, dict) or not expected or not isinstance(placements, dict)
            or set(expected) != set(placements)):
        raise Refusal("D31_MACRO_POPULATION_INCOMPLETE")
    if bounds.get("units") != "um" or not isinstance(bounds.get("limits"), dict):
        raise Refusal("D31_DECLARED_BOUNDS_UNAVAILABLE: explicit um limits required")
    limits = bounds["limits"]
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
    if any(sha(path) != digest for path, digest in files.items()):
        raise Refusal("D31_INPUT_CHANGED_DURING_READ")
    inputs = {str(p.relative_to(project)): digest for p, digest in files.items()}
    return dict(instances=rows, die=die, core=core, inputs=inputs)


def native(project, output, producing):
    """Actual native geometry readback, not a caller-supplied verdict."""
    import pya
    data = load_inputs(project)
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
        return {"gds_sha256": sha(output / "floorplan.gds"), "inputs": data["inputs"]}
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
                instances=observations, inputs=data["inputs"], gds_sha256=sha(output / "floorplan.gds"))


def operation_sources():
    return {"programs/" + p.name: sha(p) for p in (Path(__file__), HERE / "_pad_ring.py")}


def execute(project, context):
    project = Path(project).resolve(strict=True)
    output = project / "reports/flow109/D31" / uuid.uuid4().hex
    output.mkdir(parents=True)
    record = dict(step_id="D31", native_step_id="flow109.D31", context_sha256=context.get("context_sha256"),
                  component_status="NOT_MEASURED", default_row_status="NOT_MEASURED", completed=False,
                  flow109_acceptance="NOT_MEASURED", whole_flow_acceptance="NOT_MEASURED",
                  delivery_accepted=False, qualification="NOT_CLAIMED", native_started=False,
                  operation_sources=operation_sources(), executions=[], outputs=[],
                  scope="D31 native macro placement and geometry only; G1-G9 and full die acceptance unmeasured")
    try:
        if (context.get("requested_step") != "D31" or context.get("native_step_id") != "flow109.D31"
                or context.get("resolved_row", {}).get("profile", {}).get("id") != "analog_die"):
            raise Refusal("D31_CONTEXT_INVALID")
        from flow109_admission import require_launch_admission
        record["launch_admission"] = require_launch_admission(project, "flow109.D31", {"flow109_context": context})
        import librelane_contract as launch
        try:
            record["native_launch"] = launch.local_image_attestation()
        except launch.Refusal as exc:
            record["native_launch"] = {"status": "NOT_MEASURED", "reason": exc.code}
        inputs = load_inputs(project)["inputs"]
        executable = shutil.which("klayout")
        if not executable:
            raise Refusal("D31_NATIVE_TOOL_UNAVAILABLE: klayout")
        record["tool"] = dict(path=str(Path(executable).resolve()), sha256=sha(Path(executable).resolve()))
        for mode in ("produce", "consume"):
            request = output / (mode + "-request.json")
            request.write_text(json.dumps(dict(project=str(project), output=str(output), mode=mode)))
            argv = [executable, "-b", "-r", str(Path(__file__).resolve()), "-rd", "D31_REQUEST=" + str(request)]
            record["native_started"] = True
            result = subprocess.run(argv, text=True, capture_output=True)
            log = output / (mode + ".log")
            log.write_text(result.stdout + result.stderr)
            record["executions"].append(dict(argv=argv, returncode=result.returncode, log=str(log.relative_to(project)), log_sha256=sha(log)))
            raw_answer = (output / (mode + ".json")).read_bytes()
            answer = json.loads(raw_answer)
            answer_digest = hashlib.sha256(raw_answer).hexdigest()
            if result.returncode or answer.get("error"):
                raise Refusal(answer.get("error", "D31_NATIVE_ERROR"))
            if answer.get("inputs") != inputs or load_inputs(project)["inputs"] != inputs:
                raise Refusal("D31_INPUT_CHANGED_DURING_EXECUTION")
            if mode == "produce":
                produced = answer
            else:
                if answer.get("gds_sha256") != produced.get("gds_sha256"):
                    raise Refusal("D31_OUTPUT_CHANGED_DURING_READBACK")
                record.update(component_status=answer["status"], measurements=answer)
        record["inputs"] = inputs
        record["outputs"] = [{"path": str(p.relative_to(project)), "sha256": sha(p)}
                             for p in (output / "floorplan.gds", output / "consume.json")]
        if ([r["sha256"] for r in record["outputs"]] != [answer["gds_sha256"], answer_digest]
                or load_inputs(project)["inputs"] != inputs
                or operation_sources() != record["operation_sources"]):
            raise Refusal("D31_EVIDENCE_CHANGED_BEFORE_PUBLICATION")
        if record["native_launch"].get("cid") and launch.local_image_attestation() != record["native_launch"]:
            raise Refusal("D31_NATIVE_LAUNCH_CHANGED")
        record["reason"] = "Native placed-view readback " + record["component_status"] + "; row qualification remains unmeasured"
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        # A late unreadable/stale output must never retain an earlier PASS.
        # A genuine already-bound geometry FAIL remains blocking.
        if record["component_status"] != "FAIL":
            record["component_status"] = "NOT_MEASURED"
        record["reason"] = str(exc)
    (output / "component.json").write_text(json.dumps(record, indent=2))
    return record


def observe_component(project, context, component):
    """Reopen a normal attempt and read its GDS; never rerun placement.

    Original requests/source/outputs remain immutable. The original worker
    source must reopen at its recorded path, hash exactly, and have identical
    consumed definitions to this reader. A release number is not a reuse test.
    Fresh readback is required because coherent edits to printed measurements
    and their JSON hashes cannot establish native geometry or population.
    """
    import ast
    import flow109
    project = Path(project).resolve(strict=True)
    current = flow109.validate_execution_context(context)
    if (current.get("requested_step") != "D31"
            or current["resolved_row"]["profile"]["id"] != "analog_die"):
        raise Refusal("D31_METRIC_CONTEXT_INVALID")
    if not isinstance(component, dict) or component.get("step_id") != "D31":
        raise Refusal("D31_COMPONENT_ABSENT")
    outputs = component.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 2:
        raise Refusal("D31_OUTPUT_POPULATION_INCOMPLETE")
    paths = [bound_file(project, ref) for ref in outputs]
    directory = paths[0].parent
    if (paths != [directory / "floorplan.gds", directory / "consume.json"]
            or directory.parent != project / "reports/flow109/D31"
            or not re.fullmatch(r"[0-9a-f]{32}", directory.name)):
        raise Refusal("D31_OUTPUT_ATTEMPT_FOREIGN")
    raw_path = directory / "component.json"
    raw_bytes = raw_path.read_bytes()
    bound_file(project, {"path": str(raw_path.relative_to(project)), "sha256": hashlib.sha256(raw_bytes).hexdigest()})
    raw = json.loads(raw_bytes)
    if raw != component or raw.get("native_started") is not True:
        raise Refusal("D31_COMPONENT_RECORD_MISMATCH")
    original_hash = raw.get("context_sha256")
    if not isinstance(original_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", original_hash):
        raise Refusal("D31_ORIGINAL_CONTEXT_ABSENT")
    original_path = project / "reports/flow109/requests" / (original_hash + ".json")
    original_bytes = original_path.read_bytes()
    bound_file(project, {"path": str(original_path.relative_to(project)), "sha256": hashlib.sha256(original_bytes).hexdigest()})
    original = json.loads(original_bytes)
    payload = {k: v for k, v in original.items() if k != "context_sha256"}
    if (flow109.digest(payload) != original_hash or original.get("context_sha256") != original_hash
            or original.get("requested_step") != "D31"
            or original.get("native_step_id") != "flow109.D31"
            or original.get("features") != current["features"]):
        raise Refusal("D31_ORIGINAL_CONTEXT_STALE")
    def semantic_row(row):
        row = json.loads(json.dumps(row))
        row.pop("metric_acceptance_status", None)
        for obligation in row.get("obligations", []):
            obligation.pop("status", None)
        return row
    if semantic_row(original.get("resolved_row", {})) != semantic_row(current["resolved_row"]):
        raise Refusal("D31_ORIGINAL_SELECTION_CHANGED")
    data = load_inputs(project)
    if raw.get("inputs") != data["inputs"]:
        raise Refusal("D31_CURRENT_INPUTS_STALE")
    executions = raw.get("executions")
    if not isinstance(executions, list) or len(executions) != 2:
        raise Refusal("D31_EXECUTION_POPULATION_INCOMPLETE")
    executable = shutil.which("klayout")
    if not executable or raw.get("tool") != {"path": str(Path(executable).resolve()), "sha256": sha(Path(executable).resolve())}:
        raise Refusal("D31_EXECUTION_TOOL_CHANGED")
    retained_source = None
    readset = {str(raw_path.relative_to(project)): hashlib.sha256(raw_bytes).hexdigest(),
               str(original_path.relative_to(project)): hashlib.sha256(original_bytes).hexdigest(), **data["inputs"]}
    for mode, execution in zip(("produce", "consume"), executions):
        argv = execution.get("argv")
        if (execution.get("returncode") != 0 or not isinstance(argv, list) or len(argv) != 6
                or Path(argv[0]).resolve() != Path(executable).resolve()
                or argv[1:3] != ["-b", "-r"] or argv[4] != "-rd"
                or argv[5] != "D31_REQUEST=" + str(directory / (mode + "-request.json"))):
            raise Refusal("D31_EXECUTION_INVOCATION_INVALID")
        source = Path(argv[3])
        if source.name != Path(__file__).name or source.is_symlink() or not source.is_file():
            raise Refusal("D31_ORIGINAL_SOURCE_ABSENT")
        if retained_source is not None and source != retained_source:
            raise Refusal("D31_ORIGINAL_SOURCE_MISMATCH")
        retained_source = source
        request_path = directory / (mode + "-request.json")
        if read(request_path) != {"project": str(project), "output": str(directory), "mode": mode}:
            raise Refusal("D31_EXECUTION_PROJECT_MISMATCH")
        log = bound_file(project, {"path": execution.get("log"), "sha256": execution.get("log_sha256")})
        for path in (request_path, log, directory / (mode + ".json")):
            readset[str(path.relative_to(project))] = sha(path)
    sources = {"programs/" + p.name: sha(p) for p in (retained_source, retained_source.parent / "_pad_ring.py")}
    if sources != raw.get("operation_sources"):
        raise Refusal("D31_ORIGINAL_SOURCE_STALE")
    original_tree, current_tree = ast.parse(retained_source.read_text()), ast.parse(Path(__file__).read_text())
    def definitions(tree):
        return {n.name: ast.dump(n, include_attributes=False) for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    before, after = definitions(original_tree), definitions(current_tree)
    original_constants = {n.targets[0].id: ast.dump(n.value, include_attributes=False)
        for n in original_tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("PLAN", "BOUNDS")}
    current_constants = {n.targets[0].id: ast.dump(n.value, include_attributes=False)
        for n in current_tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("PLAN", "BOUNDS")}
    native_names = ("Refusal", "sha", "read", "number", "box", "bound_file", "lef_envelope", "load_inputs", "native")
    if (any(after.get(name) != before.get(name) or name not in before for name in native_names)
            or original_constants != current_constants
            or sha(retained_source.parent / "_pad_ring.py") != sha(HERE / "_pad_ring.py")):
        raise Refusal("D31_NATIVE_METHOD_CHANGED")
    source_registry = retained_source.parent.parent / "flow/flow109.json"
    if (sha(source_registry) != original.get("registry_sha256")
            or sha(retained_source.parent / "flow109.py") != original.get("planner_sha256")):
        raise Refusal("D31_ORIGINAL_PLANNER_UNBOUND")
    produced, consumed = read(directory / "produce.json"), read(paths[1])
    if (produced.get("inputs") != data["inputs"] or consumed.get("inputs") != data["inputs"]
            or produced.get("gds_sha256") != sha(paths[0])
            or consumed.get("gds_sha256") != sha(paths[0])
            or consumed != raw.get("measurements")
            or raw.get("component_status") != consumed.get("status")):
        raise Refusal("D31_NATIVE_RECORD_MISMATCH")
    current_sources = operation_sources()
    check_dir = project / "reports/flow109/D31_metric_readback" / uuid.uuid4().hex
    check_dir.mkdir(parents=True)
    shutil.copyfile(paths[0], check_dir / "floorplan.gds")
    request = check_dir / "consume-request.json"
    request.write_text(json.dumps({"project": str(project), "output": str(check_dir), "mode": "consume"}))
    argv = [executable, "-b", "-r", str(Path(__file__).resolve()), "-rd", "D31_REQUEST=" + str(request)]
    run = subprocess.run(argv, text=True, capture_output=True)
    log = check_dir / "consume.log"
    log.write_text(run.stdout + run.stderr)
    observed = read(check_dir / "consume.json")
    if run.returncode or observed != consumed:
        raise Refusal("D31_NATIVE_READBACK_DISAGREEMENT")
    readset.update({r["path"]: r["sha256"] for r in outputs})
    if (any(sha(project / name) != digest for name, digest in readset.items())
            or load_inputs(project)["inputs"] != data["inputs"]
            or operation_sources() != current_sources
            or any(sha(retained_source.parent.parent / name) != digest for name, digest in sources.items())
            or sha(Path(executable).resolve()) != raw['tool']['sha256']):
        raise Refusal("D31_EVIDENCE_CHANGED_DURING_METRIC_READ")
    return {"measurement": observed, "original_context": original, "component": raw,
        "readset": readset, "component_ref": {"path": str(raw_path.relative_to(project)), "sha256": hashlib.sha256(raw_bytes).hexdigest()},
        "source_projection": {"original": sources, "current": current_sources, "consumed_definitions_unchanged": True},
        "readback": {"argv": argv, "returncode": run.returncode, "log": {"path": str(log.relative_to(project)), "sha256": sha(log)},
                     "report": {"path": str((check_dir / "consume.json").relative_to(project)), "sha256": sha(check_dir / "consume.json")}}}


def consume_default_row_completion(project, context, component):
    """Normal D31 metric hook; scoped geometry alone cannot finish the row."""
    import flow109_metric_acceptance as metrics
    accepted = metrics.accept_d31(Path(project), context, component)
    return {"step_id": "D31", "context_sha256": context["context_sha256"],
            "default_row_status": accepted["status"], "completed": accepted["status"] == "PASS",
            "flow109_acceptance": accepted["status"], "whole_flow_acceptance": "NOT_MEASURED",
            "delivery_accepted": False, "metric_acceptance": accepted, "reason": accepted.get("reason")}


if __name__ == "__main__" and "D31_REQUEST" in globals():
    request = read(globals()["D31_REQUEST"])
    output = Path(request["output"])
    try:
        answer = native(Path(request["project"]), output, request["mode"] == "produce")
    except Exception as exc:
        answer = {"error": type(exc).__name__ + ": " + str(exc)}
    (output / (request["mode"] + ".json")).write_text(json.dumps(answer, indent=2))
    if answer.get("error"):
        raise RuntimeError(answer["error"])
