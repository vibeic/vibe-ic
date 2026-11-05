"""Plan one physical PDN replay from native conductor measurements."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from em_current_density_check import parse_lef_jmax
from flow_pdn_current import coherent_geometry, matching


@dataclass(frozen=True)
class Wire:
    layer: str
    role: str
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class RecoveryPlan:
    settings: dict[str, float]
    evidence: tuple[dict, ...]


def printed_bound(value: str, upper: bool) -> Decimal:
    number = Decimal(value)
    half_unit = Decimal(5).scaleb(number.as_tuple().exponent - 1)
    return number + half_unit if upper else number - half_unit


def measured_settings(config, hotspots, tech, limits, wires, rules, parallel_length_um=None):
    """Return actuator inputs; native remeasurement decides whether they work."""
    grid = Decimal(tech.getManufacturingGrid()) / Decimal(tech.getDbUnitsPerMicron())
    if grid <= 0:
        return None
    quantum = grid * 2
    widths = {key: float(config[key]) for key in
              ("PDN_VWIDTH", "PDN_HWIDTH", "PDN_CORE_RING_VWIDTH", "PDN_CORE_RING_HWIDTH")}
    pitch_factor = 1
    evidence = []
    for row in hotspots:
        if row["Basis"] != "AREAL" or row.get("Cuts", "0") != "0":
            return None
        layer = row["Layer"].lower()
        limit = limits.get(layer)
        thickness = rules.get(layer, {}).get("thickness_um")
        if limit is None or thickness is None or limit <= 0 or thickness <= 0:
            return None
        current = printed_bound(row["Current(A)"], True)
        area = printed_bound(row["Area(um^2)"], False)
        if not current.is_finite() or not area.is_finite() or area <= 0 or current <= 0:
            return None
        points = [float(row[key]) for key in ("Node0 X", "Node0 Y", "Node1 X", "Node1 Y")]
        endpoint_roles = [{wire.role for wire in wires if wire.layer.lower() == layer
            and wire.bounds[0] <= points[index] <= wire.bounds[2]
            and wire.bounds[1] <= points[index + 1] <= wire.bounds[3]} for index in (0, 2)]
        owners = endpoint_roles[0] & endpoint_roles[1]
        if len(owners) != 1:
            return None
        role = owners.pop()
        if role == "rail":
            pitch_factor = max(pitch_factor, int((current / (area * limit)).to_integral_value(
                rounding=ROUND_CEILING)))
        elif role in widths:
            required = current / (limit * Decimal(str(thickness)))
            widths[role] = max(widths[role], float((required / quantum).to_integral_value(
                rounding=ROUND_CEILING) * quantum))
        else:
            return None
        evidence.append({**row, "role": role, "current_upper_a": str(current),
                         "area_lower_um2": str(area), "exact_limit_a_per_um2": str(limit)})
    if not evidence:
        return None
    for axis in ("V", "H"):
        widths[f"PDN_CORE_RING_{axis}WIDTH"] = max(widths[f"PDN_CORE_RING_{axis}WIDTH"],
                                                  widths[f"PDN_{axis}WIDTH"])
    proposed = dict(config)
    if pitch_factor > 1:
        for axis in ("V", "H"):
            key = f"PDN_{axis}PITCH"
            proposed[key] = float((Decimal(str(config[key])) / pitch_factor / quantum
                ).to_integral_value(rounding=ROUND_FLOOR) * quantum)
    settings = coherent_geometry(proposed, widths, tech, parallel_length_um)
    settings = {key: value for key, value in settings.items() if value != float(config[key])}
    return RecoveryPlan(settings, tuple(evidence)) if settings else None


def _wires(block, config):
    units = block.getDbUnitsPerMicron()
    result = []
    for net in block.getNets():
        if net.getSigType() not in {"POWER", "GROUND"}:
            continue
        for swire in net.getSWires():
            for shape in swire.getWires():
                if shape.isVia():
                    continue
                layer = shape.getTechLayer().getName()
                direction = "VERTICAL" if shape.getDY() > shape.getDX() else "HORIZONTAL"
                axis = "V" if direction == "VERTICAL" else "H"
                kind = shape.getWireShapeType()
                role = None
                if kind == "FOLLOWPIN" and layer == config["PDN_RAIL_LAYER"]:
                    role = "rail"
                elif kind == "STRIPE" and layer == config[f"PDN_{direction}_LAYER"]:
                    role = f"PDN_{axis}WIDTH"
                elif kind == "RING" and layer == (config.get(f"PDN_CORE_{direction}_LAYER")
                                                  or config[f"PDN_{direction}_LAYER"]):
                    role = f"PDN_CORE_RING_{axis}WIDTH"
                if role:
                    result.append(Wire(layer, role, tuple(value / units for value in
                        (shape.xMin(), shape.yMin(), shape.xMax(), shape.yMax()))))
    for instance in block.getInsts():
        if not instance.getMaster().getType().startswith("CORE"):
            continue
        for terminal in instance.getITerms():
            net = terminal.getNet()
            if net is None or net.getSigType() not in {"POWER", "GROUND"}:
                continue
            boxes = [box for layer, box in terminal.getGeometries()
                     if layer.getName() == config["PDN_RAIL_LAYER"]]
            if boxes:
                result.append(Wire(config["PDN_RAIL_LAYER"], "rail", (
                    min(box.xMin() for box in boxes) / units,
                    min(box.yMin() for box in boxes) / units,
                    max(box.xMax() for box in boxes) / units,
                    max(box.yMax() for box in boxes) / units)))
    return result


def plan_recovery(project: Path, route: dict, summary: dict) -> RecoveryPlan | None:
    try:
        return _plan_recovery(project, route, summary)
    except (OSError, KeyError, ValueError, InvalidOperation) as exc:
        print(f"PDN recovery unavailable: {exc}", file=sys.stderr)
        return None


def _derived_aggregate_failure(row):
    return (row.get("tool_kind") == "aggregate" and row.get("status") == "FAIL"
            and row.get("tool_ran") and row.get("tool_exit_code") == 0
            and not row.get("native_steps") and bool(row.get("metrics"))
            and all(item.get("metric") == "non_passing_steps" and item.get("operator") == "=="
                    and item.get("limit") == 0 and item.get("status") == "FAIL"
                    for item in row["metrics"]))


def _plan_recovery(project: Path, route: dict, summary: dict) -> RecoveryPlan | None:
    if any((project / "work/flow/pdn_attempts").glob("*/pdn_recovery.json")):
        return None
    if route.get("delivery_target") not in {"gds", "shippable_gds", "foundry_handoff", "ip_hardmacro"}:
        return None
    blockers = [row for row in summary.get("steps", []) if row["status"] != "PASS"
                and not _derived_aggregate_failure(row)]
    if (len(blockers) != 1 or blockers[0]["name"] != "candidate_electromigration"
            or blockers[0]["status"] != "FAIL" or not blockers[0].get("tool_ran")
            or summary.get("pending_steps")
            or "die_floorplan_and_macros" not in summary.get("selected_names", [])):
        return None
    metrics = blockers[0].get("native_metrics", {})
    if metrics.get("em_violations", 0) <= 0 and metrics.get("em_worst_utilization_pct", 0) <= 100:
        return None
    configs = list((project / "steps").glob("*/openroad_generatepdn/config.json"))
    if len(configs) != 1:
        return None
    config = json.loads(configs[0].read_text())
    for supply in ("VDD", "GND"):
        if config.get(f"{supply}_NETS") is None:
            config[f"{supply}_NETS"] = [config[f"{supply}_PIN"]]
    script = config.get("PDN_CFG")
    if script is not None and Path(script).resolve() != (project / "work/flow/pdn_cfg.tcl").resolve():
        return None
    lefs = matching(config["TECH_LEFS"], config["DEFAULT_CORNER"])
    if len(lefs) != 1:
        return None
    em_root = project / "steps/candidate_electromigration/vibeic_emcorners"
    reports = list(em_root.glob("max_*/em-*.csv"))
    hotspots, limits = [], {}
    for report in reports:
        for line in (report.parent / "em_limits_pdk.txt").read_text().splitlines():
            fields = line.split()
            if len(fields) == 2:
                value = Decimal(fields[1])
                key = fields[0].lower()
                limits[key] = min(limits.get(key, value), value)
        with report.open(newline="") as stream:
            hotspots.extend(row for row in csv.DictReader(stream) if row["Status"] == "VIOLATED")
    if not hotspots:
        return None
    import odb
    state = json.loads((em_root / "state_in.json").read_text())
    database = odb.dbDatabase.create()
    try:
        odb.read_db(database, state["odb"])
        block = database.getChip().getBlock()
        die = block.getDieArea()
        length = max(die.dx(), die.dy()) / block.getDbUnitsPerMicron()
        return measured_settings(config, hotspots, database.getTech(), limits,
            _wires(block, config), parse_lef_jmax(lefs[0].read_text()), length)
    finally:
        odb.dbDatabase.destroy(database)


def apply_plan(project: Path, route: dict, summary: dict, plan: RecoveryPlan) -> Path:
    argv = [sys.executable, str(Path(__file__).with_name("flow_config.py")), "--project", str(project),
            "--route", "ic" if route["delivery_target"] != "ip_hardmacro" else "ip"]
    for key, value in plan.settings.items():
        argv.extend(["--set", f"{key}={json.dumps(value)}"])
    subprocess.run(argv, check=True)
    directory = project / "work/flow/pdn_attempts" / str(time.time_ns())
    directory.mkdir(parents=True)
    (directory / "flow_engine.json").write_text(json.dumps(summary, indent=2) + "\n")
    (directory / "pdn_recovery.json").write_text(json.dumps({"settings": plan.settings,
        "evidence": plan.evidence}, indent=2) + "\n")
    names = summary["selected_names"]
    start = names.index("die_floorplan_and_macros")
    for name in names[start:]:
        source = project / "steps" / name
        if source.exists():
            shutil.move(str(source), str(directory / name))
    return directory


def finish_replay(project: Path, first: dict, final: dict, archive: Path,
                  extra_program_seconds=0.0) -> dict:
    """Retain spent execution time while final-candidate measurements replace old ones."""
    import flow_engine
    started = time.perf_counter()
    old_rows = {row["name"]: row for row in first["steps"]}
    for row in final["steps"]:
        old = old_rows.get(row["name"], {})
        for key in ("tool_seconds", "program_seconds", "wall_seconds"):
            row[key] = row.get(key, 0) + old.get(key, 0)
        row["ai_seconds"] = (row.get("ai_seconds", 0) + old.get("ai_seconds", 0)
            if row.get("ai_seconds") is not None and old.get("ai_seconds") is not None else None)
        flow_engine.write_json(project / "steps" / row["name"] / "result.json", row)
    for key in ("selected", "selected_names", "not_selected"):
        if key in first:
            final[key] = first[key]
    overhead = extra_program_seconds + time.perf_counter() - started
    floorplan = project / "steps/die_floorplan_and_macros/result.json"
    row = json.loads(floorplan.read_text())
    row["program_seconds"] = row.get("program_seconds", 0) + overhead
    flow_engine.write_json(floorplan, row)
    final["pdn_recovery"] = {"first_attempt": str(archive), "physical_replays": 1,
                             "program_seconds": overhead}
    flow_engine.write_json(project / "reports/flow_engine.json", final)
    return flow_engine.refresh_report(project)
