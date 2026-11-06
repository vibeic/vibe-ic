"""Per-field arithmetic ported from _ppa/benchmark.py:score.

The caller supplies measurements with a common scope. These comparisons report
tradeoffs; native public-row results remain the adoption decision.
"""
from flow_ppa_objective import numeric


FIELDS = {
    "area": ("lower", "ratio"),
    "power": ("lower", "ratio"),
    "setup_slack": ("higher", "interval"),
    "hold_slack": ("higher", "interval"),
    "wirelength": ("lower", "ratio"),
    "wall_seconds": ("lower", "ratio"),
    "cpu_hours": ("lower", "ratio"),
}


def compare_fields(subject, baseline):
    """Keep losses, ties and unavailable measurements beside wins."""
    result = {}
    for field, (direction, scale) in FIELDS.items():
        value, reference = subject.get(field), baseline.get(field)
        row = {"subject": value, "baseline": reference, "better_is": direction,
               "scale": scale, "delta": None, "delta_pct": None,
               "verdict": "NOT_MEASURED"}
        if not numeric(value) or not numeric(reference):
            row["detail"] = "A native measurement is unavailable"
        else:
            row["delta"] = value - reference
            row["verdict"] = ("TIE" if value == reference else
                              "SUBJECT_BETTER" if (value < reference) == (direction == "lower")
                              else "BASELINE_BETTER")
            if scale == "interval":
                row["delta_pct_reason"] = "Signed slack uses an absolute delta, not a percentage"
            elif reference <= 0:
                row["delta_pct_reason"] = "The baseline has no positive denominator"
            else:
                row["delta_pct"] = (value - reference) / reference * 100
        result[field] = row
    return result


def trial_fields(row):
    """Adapt existing public trial values without filling missing values."""
    metrics = row.get("metrics", {})
    return {
        "area": metrics.get("design__instance__area"),
        "power": metrics.get("power__total"),
        "setup_slack": metrics.get("timing__setup__ws"),
        "hold_slack": metrics.get("timing__hold__ws"),
        "wirelength": metrics.get("route__wirelength"),
        "wall_seconds": row.get("wall_seconds"),
        "cpu_hours": row.get("cpu_hours"),
    }
