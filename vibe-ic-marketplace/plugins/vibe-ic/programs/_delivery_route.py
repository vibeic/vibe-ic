"""Physical and RTL delivery labels from the unchanged Router decision."""
from __future__ import annotations

from pathlib import Path


def report_label(project: Path) -> dict:
    from flow_engine import select_route
    route = select_route(Path(project))
    target = route["delivery_target"]
    if target == "rtl":
        return {"delivery_route": "RTL", "deliverable": "RTL", "delivery_scope": route}
    if target in {"gds", "shippable_gds", "foundry_handoff"}:
        return {"delivery_route": "IC", "deliverable": "DIE"}
    return {"delivery_route": "IP", "deliverable": "HARDMACRO"}
