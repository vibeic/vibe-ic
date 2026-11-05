"""Read the delivery route already selected by the native flow runner."""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Optional

PATH_CHIP = "CHIP"
PATH_IP = "IP"
PATH_BOTH = "BOTH"
PATH_NOT_DETERMINED = "NOT_DETERMINED"
PATH_UNREADABLE = "UNREADABLE"
PATH_NOT_SUPPLIED = "NOT_SUPPLIED"
TAPEOUT_BOUND = (PATH_CHIP,)


def resolve(project: Optional[Any]) -> Dict[str, Any]:
    """Return the Router's delivery target from the native run report."""
    if project is None or str(project).strip() == "":
        return {"path": PATH_NOT_SUPPLIED, "reason": "No project was supplied.",
                "evidence": {}}
    root = pathlib.Path(str(project))
    evidence = {"project": str(root)}
    if not root.is_dir():
        return {"path": PATH_UNREADABLE, "reason": f"{root} is not a directory.",
                "evidence": evidence}
    report = root / "reports/flow_engine.json"
    evidence["report"] = str(report)
    if not report.is_file():
        return {"path": PATH_NOT_DETERMINED, "reason": "No native flow route was reported.",
                "evidence": evidence}
    try:
        target = json.loads(report.read_text())["route"]["delivery_target"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"path": PATH_UNREADABLE, "reason": f"The native flow route could not be read: {exc}",
                "evidence": evidence}
    evidence["delivery_target"] = target
    if not isinstance(target, str):
        return {"path": PATH_UNREADABLE, "reason": "The reported delivery target is not text.",
                "evidence": evidence}
    if target in {"gds", "shippable_gds", "foundry_handoff"}:
        return {"path": PATH_CHIP, "reason": "The Router selected physical chip delivery.",
                "evidence": evidence}
    if target == "ip_hardmacro":
        return {"path": PATH_IP, "reason": "The Router selected hardmacro delivery.",
                "evidence": evidence}
    return {"path": PATH_NOT_DETERMINED,
            "reason": "The reported route does not select physical chip or hardmacro delivery.",
            "evidence": evidence}


def is_tapeout_bound(path: Any) -> bool:
    return path in TAPEOUT_BOUND
