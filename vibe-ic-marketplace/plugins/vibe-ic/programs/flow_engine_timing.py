"""Reduce recorded native, independent-check and review times."""
from __future__ import annotations

import math


def _number(value):
    try:
        return float(value) if value is not None and math.isfinite(value) else None
    except TypeError:
        return None


def _total(rows, key):
    return sum(_number(row.get(key)) or 0 for row in rows)


def _intervals(rows):
    intervals = []
    for row in rows:
        start, end = _number(row.get("started_at")), _number(row.get("completed_at"))
        if start is not None and end is not None and end >= start:
            intervals.append((start, end))
    return sorted(intervals)


def _union(intervals):
    elapsed, previous = 0.0, None
    for start, end in intervals:
        if previous is None or start > previous:
            elapsed += end - start
        elif end > previous:
            elapsed += end - previous
        previous = max(end, previous) if previous is not None else end
    return elapsed


def _pending_reviews(rows):
    return [row["name"] for row in rows if row.get("tool_ran") and row.get("ai_seconds") is None]


def timing_summary(report):
    rows = report.get("steps", [])
    groups = {}
    for group in ("librelane", "other", "unclassified"):
        selected = [row for row in rows if row.get("timing_group", "unclassified") == group]
        intervals = _intervals(selected)
        groups[group] = {
            "tool_seconds": _total(selected, "tool_seconds"),
            "program_seconds": _total(selected, "program_seconds"),
            "ai_seconds": _total(selected, "ai_seconds"),
            "ai_pending_steps": _pending_reviews(selected),
            "execution_wall_seconds": _union(intervals),
            "wall_span_seconds": max(end for _, end in intervals) - intervals[0][0] if intervals else None,
            "queue_seconds": _total(selected, "queue_seconds"),
            "unclassified_seconds": _total(selected, "unclassified_seconds"),
            "retained_tool_seconds": _total([row for row in selected if row.get("retained")], "tool_seconds"),
        }
    common = [row for row in rows if row.get("timing_group") == "librelane"]
    start = _number(report.get("native_common_started_at"))
    native_end = _number(report.get("native_common_completed_at"))
    recorded_starts = [_number(row.get("native_common_started_at")) for row in common if not row.get("retained")]
    recorded_ends = [_number(row.get("native_common_completed_at")) for row in common if not row.get("retained")]
    recorded_starts = [value for value in [start, *recorded_starts] if value is not None]
    recorded_ends = [value for value in [native_end, *recorded_ends] if value is not None]
    start = min(recorded_starts) if recorded_starts else None
    native_end = max(recorded_ends) if recorded_ends else None
    reviews = [_number(row.get("reviewed_at")) for row in common if row.get("tool_ran")]
    reviews = [value for value in reviews if value is not None]
    end = max([native_end, *reviews]) if native_end is not None else None
    elapsed = max(0, end - start) if start is not None and end is not None else None
    missing_timing = []
    for row in common:
        if row.get("tool_kind") == "native_report":
            continue
        native_steps = row.get("native_steps", [])
        disabled = bool(native_steps) and all(item.get("native_config_disabled") for item in native_steps)
        if (row.get("retained") or not row.get("timing_complete", True)
                or not row.get("tool_ran") and not disabled
                or any((not item.get("ran") or item.get("status") == "NOT_MEASURED")
                       and not item.get("native_config_disabled") for item in native_steps)):
            missing_timing.append(row["name"])
    pending = _pending_reviews(common)
    tools_complete = (set(report["common_step_names"]) <= {row["name"] for row in rows}
                      if "common_step_names" in report else report.get("common_tools_complete"))
    complete = bool(tools_complete and report.get("timing_scope", "full_router_window") == "full_router_window" and elapsed is not None
                    and not pending and not missing_timing)
    budget = _number(report.get("budget_seconds"))
    status = "NOT_MEASURED"
    if budget is not None and elapsed is not None:
        if elapsed > budget:
            status = "OVER_BUDGET"
        elif complete:
            status = "IN_BUDGET"
    invocation_start = _number(report.get("started_at"))
    invocation_end = _number(report.get("completed_at"))
    all_reviews = [_number(row.get("reviewed_at")) for row in rows]
    all_reviews = [value for value in all_reviews if value is not None]
    if invocation_end is not None:
        invocation_end = max([invocation_end, *all_reviews])
    else:
        invocation_end = _number(report.get("updated_at"))
    wall = (max(0, invocation_end - invocation_start)
            if invocation_start is not None and invocation_end is not None else report.get("wall_seconds"))
    ai_pending = _pending_reviews(rows)
    return {
        "tool_seconds": _total(rows, "tool_seconds"),
        "program_seconds": _total(rows, "program_seconds"),
        "ai_seconds": None if ai_pending else _total(rows, "ai_seconds"),
        "ai_measured_seconds": _total(rows, "ai_seconds"),
        "ai_unmeasured_steps": ai_pending,
        "wall_seconds": wall,
        "common_wall_seconds": elapsed,
        "common_native_wall_seconds": max(0, native_end - start) if start is not None and native_end is not None else None,
        "common_budget_completed_at": end,
        "common_reviews_pending": pending,
        "common_tools_complete": bool(tools_complete),
        "common_timing_unmeasured_steps": missing_timing,
        "common_timing_complete": complete,
        "runtime_status": status,
        "timing_groups": groups,
        "other_execution_wall_seconds": groups["other"]["execution_wall_seconds"],
        "other_wall_span_seconds": groups["other"]["wall_span_seconds"],
        "timing_reference": "Recorded common native bounds and applicable common review completion; independent checks reported separately",
    }
