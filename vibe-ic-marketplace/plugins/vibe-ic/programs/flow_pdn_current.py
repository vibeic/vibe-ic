from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import fnmatch
import gzip
import json
import math
from pathlib import Path
import re

from em_current_density_check import parse_lef_jmax


def paths(value):
    if isinstance(value, dict):
        return [path for item in value.values() for path in paths(item)]
    if isinstance(value, (list, tuple)):
        return [path for item in value for path in paths(item)]
    return [Path(str(value))] if value else []


def matching(views, corner):
    return [path for pattern, value in views.items() if fnmatch.fnmatchcase(corner, pattern)
            for path in paths(value)]


def estimated_current(config, metrics):
    samples = []
    if len(config.get("VDD_NETS") or []) != 1 or len(config.get("GND_NETS") or []) != 1:
        return None, samples
    for key, power in metrics.items():
        if not key.startswith("power__total__corner:"):
            continue
        corner = key.split("__corner:", 1)[1]
        voltages = set()
        for library in matching(config["LIB"], corner):
            opener = gzip.open if library.suffix == ".gz" else open
            with opener(library, "rt") as stream:
                match = re.search(r"\bnom_voltage\s*:\s*([-+0-9.eE]+)", stream.read())
            if match:
                voltages.add(float(match[1]))
        if len(voltages) != 1:
            return None, samples
        voltage = voltages.pop()
        if voltage <= 0 or not math.isfinite(voltage) or not math.isfinite(float(power)) or power < 0:
            return None, samples
        samples.append({"corner": corner, "power_w": power, "voltage_v": voltage,
                        "current_a": power / voltage})
    return max((row["current_a"] for row in samples), default=None), samples


def sized_widths(config, current_a, tech_lef):
    grid = re.search(r"\bMANUFACTURINGGRID\s+([0-9.eE+-]+)\s*;", tech_lef, re.I)
    if grid is None or Decimal(grid[1]) <= 0:
        return {}
    quantum = Decimal(grid[1]) * 2
    rules = parse_lef_jmax(tech_lef)

    def width(layer, baseline):
        rule = rules.get(str(layer).lower(), {})
        capacity = rule.get("jmax_per_width_A_per_um")
        if capacity is None and rule.get("jmax_areal_A_per_um2") and rule.get("thickness_um"):
            capacity = rule["jmax_areal_A_per_um2"] * rule["thickness_um"]
        wanted = Decimal(str(baseline))
        if rule.get("width_um") is not None:
            wanted = max(wanted, Decimal(str(rule["width_um"])))
        if current_a is not None and capacity is not None and capacity > 0:
            wanted = max(wanted, Decimal(str(current_a)) / Decimal(str(capacity)))
        return float((wanted / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum)

    result = {}
    for axis, direction in (("V", "VERTICAL"), ("H", "HORIZONTAL")):
        layer = config[f"PDN_{direction}_LAYER"]
        strap_key, ring_key = f"PDN_{axis}WIDTH", f"PDN_CORE_RING_{axis}WIDTH"
        strap = width(layer, config[strap_key])
        ring_layer = config.get(f"PDN_CORE_{direction}_LAYER") or layer
        ring = width(ring_layer, max(float(config[ring_key]), strap))
        result.update({strap_key: strap, ring_key: ring})
    return result


def coherent_geometry(config, widths, tech, parallel_length_um=0, explicit=()):
    units = tech.getDbUnitsPerMicron()
    grid = Decimal(tech.getManufacturingGrid()) / Decimal(units)
    if grid <= 0:
        raise ValueError("PDK technology has no manufacturing grid")
    snap = lambda value: float((Decimal(str(value)) / grid).to_integral_value(rounding=ROUND_CEILING) * grid)
    count = len(config["VDD_NETS"]) + len(config["GND_NETS"])
    result = dict(widths)

    def spacing(layer_name, width):
        layer = tech.findLayer(str(layer_name))
        if layer is None:
            raise ValueError(f"PDN routing layer is absent from technology: {layer_name}")
        size = round(width * units)
        length = math.ceil(parallel_length_um * units)
        return max(layer.getSpacing(size, length), layer.findTwSpacing(size, size, length)) / units

    def at_least(key, value):
        if key in explicit and Decimal(str(config[key])) < Decimal(str(value)):
            raise ValueError(f"Declared {key}={config[key]} cannot fit native PDN geometry minimum {value}")
        if key in explicit:
            return declared_value(key)
        return snap(max(Decimal(str(config[key])), Decimal(str(value))))

    def declared_value(key):
        value = Decimal(str(config[key]))
        if value % grid:
            raise ValueError(f"Declared {key}={value} is not on the PDK manufacturing grid {grid}")
        return float(value)

    for axis, direction in (("V", "VERTICAL"), ("H", "HORIZONTAL")):
        width = widths[f"PDN_{axis}WIDTH"]
        gap = at_least(f"PDN_{axis}SPACING", spacing(config[f"PDN_{direction}_LAYER"], width))
        result[f"PDN_{axis}SPACING"] = gap
        result[f"PDN_{axis}PITCH"] = at_least(f"PDN_{axis}PITCH",
            count * (Decimal(str(width)) + Decimal(str(gap))))
        result[f"PDN_{axis}OFFSET"] = (declared_value(f"PDN_{axis}OFFSET") if f"PDN_{axis}OFFSET" in explicit
            else snap(Decimal(str(config[f"PDN_{axis}OFFSET"]))
                + (Decimal(str(width)) - Decimal(str(config[f"PDN_{axis}WIDTH"]))) / 2))
        if config.get("PDN_CORE_RING"):
            layer = config.get(f"PDN_CORE_{direction}_LAYER") or config[f"PDN_{direction}_LAYER"]
            result[f"PDN_CORE_RING_{axis}SPACING"] = at_least(f"PDN_CORE_RING_{axis}SPACING",
                spacing(layer, widths[f"PDN_CORE_RING_{axis}WIDTH"]))
    return result


def current_settings(project, config, parallel_length_um=0):
    base = project / "work/flow/pdn_cfg.tcl"
    script = config.get("PDN_CFG")
    if script is not None and Path(str(script)).resolve() != base.resolve():
        return {}
    power = project / "steps/pre_layout_timing/result.json"
    if not power.is_file():
        return {}
    current, samples = estimated_current(config, json.loads(power.read_text()).get("native_metrics", {}))
    lefs = matching(config["TECH_LEFS"], config["DEFAULT_CORNER"])
    if len(lefs) != 1:
        raise ValueError("PDN sizing needs one native technology LEF for the default corner")
    widths = sized_widths(config, current, lefs[0].read_text())
    if not widths:
        return {}
    import odb
    from flow_config import _load, _settings
    docs = _load(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")
    explicit = set(_settings(docs.get("fields", {}), config["PDK"]))
    explicit.update(_load(project / "plugin_output/declaration.json"))
    database = odb.dbDatabase.create()
    try:
        odb.read_lef(database, str(lefs[0]))
        settings = coherent_geometry(config, widths, database.getTech(), parallel_length_um, explicit)
    finally:
        odb.dbDatabase.destroy(database)
    output = project / "work/flow/chip/pdn_sizing.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"estimated_current_a": current, "corners": samples,
        "requested_widths_um": widths, "settings": settings, "parallel_length_um": parallel_length_um,
        "model": "Full estimated supply current is a conservative conductor bound. "
                 "Widths and native spacing/pitch/offset geometry are resolved before floorplan; "
                 "native connectivity, DRC and final EM determine adequacy."}, indent=2) + "\n")
    return settings


def needs_estimate(route, from_name, table):
    if route["delivery_target"] not in {"gds", "shippable_gds", "foundry_handoff", "ip_hardmacro"}:
        return False
    from flow_engine import aliases
    positions = {name: index for index, row in enumerate(table["steps"])
                 for name in [row["name"], *aliases(row)]}
    first = positions[str(from_name or route["entry_step"])]
    last = positions[str(route["verify_through"])]
    return first <= positions["pre_layout_timing"] < positions["die_floorplan_and_macros"] <= last
