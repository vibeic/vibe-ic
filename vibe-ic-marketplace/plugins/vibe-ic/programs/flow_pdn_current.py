from __future__ import annotations

import argparse
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


def tcl_word(value):
    return "".join({"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(char,
        "\\" + char if char in '\\ $;{}[]"' else char) for char in str(value))


def attach(project, config, destination, original_source):
    if Path(str(original_source)).resolve() != (project / "work/flow/pdn_cfg.tcl").resolve():
        return
    base = Path(config["PDN_CFG"])
    script = destination / "pdn_current.tcl"
    program = Path(__file__).resolve()
    script.write_text(
        "set pdn_env [file join $::env(STEP_DIR) pdn_current_env.tcl]\n"
        + "file copy -force $::env(_TCL_ENV_IN) $pdn_env\n"
        + "set pdn_env_file [open $pdn_env a]\n"
        + 'puts $pdn_env_file ""\n'
        + "foreach {key value} [exec python3 " + tcl_word(program)
        + " --project " + tcl_word(project)
        + " --config [file join $::env(STEP_DIR) config.json]] {\n"
        + "  puts $pdn_env_file [list set ::env($key) $value]\n"
        + "  set ::env($key) $value\n"
        + '  utl::metric_float "pdn__requested_width__um__variable:$key" $value\n'
        + "}\nclose $pdn_env_file\n"
        + "set ::env(_TCL_ENV_IN) $pdn_env\nsource " + tcl_word(base) + "\n")
    config["PDN_CFG"] = str(script)


def main():
    parser = argparse.ArgumentParser(description="Size native Chip power conductors from estimated current")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    path = args.project / "steps/pre_layout_timing/result.json"
    metrics = json.loads(path.read_text()).get("native_metrics", {}) if path.is_file() else {}
    current, samples = estimated_current(config, metrics)
    tech = matching(config["TECH_LEFS"], config["DEFAULT_CORNER"])
    widths = sized_widths(config, current, tech[0].read_text()) if len(tech) == 1 else {}
    report = {"estimated_current_a": current, "corners": samples, "requested_widths_um": widths,
              "model": "The full estimated supply current may flow in each strap and ring conductor. "
                       "Pre-layout modeled power omits routed loading and clock-tree changes; "
                       "native geometry checks and final EM determine adequacy."}
    output = args.project / "work/flow/chip/pdn_sizing.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(" ".join(f"{key} {value:.12g}" for key, value in widths.items()))


if __name__ == "__main__":
    main()
