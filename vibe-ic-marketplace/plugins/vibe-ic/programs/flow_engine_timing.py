"""Plain totals of the recorded row durations."""

def timing_summary(report):
    rows = report.get("steps", [])
    return {key: (None if key == "ai_seconds" and any(row.get(key) is None for row in rows)
                  else sum(row.get(key) or 0 for row in rows))
            for key in ("tool_seconds", "program_seconds", "ai_seconds", "wall_seconds")}
