"""Native PPA comparison, porting _ppa/benchmark.py:score arithmetic.

Raw axes and failures remain visible. This score ranks only complete all-PASS
public trials; it does not replace native feasibility or document limits.
"""
from __future__ import annotations

import math
from pathlib import Path

from constraint_prose_tokens import scan_inputs
from flow_config import _input_docs, _load, _value
from _prose_polarity import is_denied


# ORFS PPAImprov coefficients, OpenROAD-flow-scripts 5928a0be5748c7505e69f342f8b0d140dfcc630f.
INHERITED_WEIGHTS = {"performance": 10000, "power": 100, "area": 100}
FINAL_COUNTERS = (
    "design__max_slew_violation__count", "design__max_cap_violation__count",
    "design__max_fanout_violation__count", "design__power_grid_violation__count",
    "timing__setup_vio__count", "timing__hold_vio__count",
    "route__antenna_violation__count", "route__drc_errors",
    "magic__drc_error__count", "klayout__drc_error__count", "em_violations",
)


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def final_violation_metrics(metrics: dict) -> dict:
    """Retain final native counters, never an earlier router iteration's residue."""
    counts = {key: metrics[key] for key in FINAL_COUNTERS if key in metrics}
    if "route__drc_errors_final" in metrics:
        counts["route__drc_errors"] = metrics["route__drc_errors_final"]
    return counts


def objective_weights(project: Path) -> dict:
    fields = _load(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").get("fields", {})
    declared = dict(fields.get("ppa_weights", {}))
    rows = [*fields.get("constraint_declarations", []),
            *scan_inputs(_input_docs(project).items())["settings"]]
    for axis in INHERITED_WEIGHTS:
        values = [_value(row["value"]) for row in rows
                  if row.get("token") == f"PPA_{axis.upper()}_WEIGHT"
                  and not is_denied(str(row.get("evidence", "")))]
        if axis in declared:
            values.append(declared[axis])
        if any(not numeric(value) or value < 0 for value in values):
            raise ValueError(f"Invalid PPA {axis} weight")
        if len(set(values)) > 1:
            raise ValueError(f"Conflicting PPA {axis} weights")
        if values:
            declared[axis] = values[0]
    values = {**INHERITED_WEIGHTS, **declared}
    if not sum(values[axis] for axis in INHERITED_WEIGHTS):
        raise ValueError("At least one PPA weight must be positive")
    return {"values": {axis: values[axis] for axis in INHERITED_WEIGHTS},
            "source": {axis: "document" if axis in declared else "inherited, not chosen"
                       for axis in INHERITED_WEIGHTS},
            "inherited_from": "ORFS PPAImprov performance:power:area =10000:100:100"}


def native_axes(row: dict) -> dict:
    metrics, config = row["metrics"], row.get("resolved_settings", {})
    period, slack = config.get("CLOCK_PERIOD"), metrics.get("timing__setup__ws")
    period = _value(period)
    return {"area": metrics.get("design__instance__area"),
            "power": metrics.get("power__total"),
            "performance": period - min(slack, 0) if numeric(period) and period > 0 and numeric(slack) else None}


def compare_native(reference: dict, candidate: dict, weights: dict) -> dict:
    """Minimize a declared percentage objective; native failures stay ineligible.

    Keep ORFS's clipped effective period and inherited coefficient ratio, but
    use measured instance area rather than utilization complement for our area
    term. This adaptation is explicit; it is not claimed to be stock ORFS score.
    """
    before, after = native_axes(reference), native_axes(candidate)
    result = {"reference": reference["name"], "reference_all_pass": reference["all_pass"],
              "reference_axes": before, "candidate_axes": after,
              "weights": weights, "score": None, "eligible": False,
              "area_basis": "native instance area, including physical fill when present",
              "performance_basis": "clock_period - min(setup_ws,0); positive slack is reported separately",
              "formula": "100*(100*sum(weights)-sum(weight*improvement_pct)) + raw_score/10*(native_violation_count+failed_rows)",
              "direction": "minimize"}
    for key in ("CLOCK_PERIOD", "PDK", "STD_CELL_LIBRARY", "STA_CORNERS"):
        a = reference.get("resolved_settings", {}).get(key)
        b = candidate.get("resolved_settings", {}).get(key)
        if a is None or b is None or a != b:
            result["detail"] = f"NOT_MEASURED: native comparison basis is missing or differs for {key}"
            return result
    if any(not numeric(before[axis]) or before[axis] <= 0 or not numeric(after[axis]) or after[axis] < 0
           for axis in INHERITED_WEIGHTS):
        result["detail"] = "NOT_MEASURED: a reference/candidate PPA axis is unavailable or has an undefined ratio"
        return result
    improvement = {axis: 100 * (before[axis] - after[axis]) / before[axis] for axis in INHERITED_WEIGHTS}
    raw = 100 * sum(weights["values"].values()) - sum(weights["values"][axis] * improvement[axis]
                                                               for axis in INHERITED_WEIGHTS)
    counts = candidate.get("violation_metrics", {})
    if any(not numeric(value) or value < 0 for value in counts.values()):
        result["detail"] = "NOT_MEASURED: a reported final native violation counter is unavailable or invalid"
        return result
    failures = sum(row["status"] == "FAIL" for row in candidate["rows"])
    result.update(improvement_pct=improvement, native_violation_metrics=counts, failed_rows=failures,
                  score=100 * raw + raw / 10 * (sum(counts.values()) + failures),
                  eligible=candidate["all_pass"] and not any(counts.values()))
    return result
