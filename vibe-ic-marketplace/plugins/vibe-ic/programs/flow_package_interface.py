"""Read the package/pad assignment from documents before RTL authoring."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time


def execute(project, directory):
    from flow109_technology_qualification import documented_pdk
    import pad_assignment_gen

    project, directory = Path(project), Path(directory)
    pdk = documented_pdk(project)
    root = os.environ.get("VIBEIC_LIBRELANE_PDK_ROOT") or os.environ.get("PDK_ROOT")
    if not pdk or not root:
        return {"ran": False, "exit_code": None,
                "detail": "Package interface needs the documented PDK and installed PDK_ROOT."}
    output = directory / "pad_assignment.json"
    started = time.perf_counter()
    code = pad_assignment_gen.main([str(project), "--pdk-root", root, "--pdk", pdk,
        "--json", str(output), "--out", str(project / "phase3/stage3/pnr/pad_assignment.json")])
    report = json.loads(output.read_text())
    status = "PASS" if code == 0 else "FAIL" if code == 1 else "NOT_MEASURED"
    return {"ran": True, "exit_code": code,
            "metrics": {"package_interface__question__count": report["questions_answered"],
                        "package_interface__unanswered__count": len(report["questions_unanswered"])},
            "reports": [str(output)], "tool_seconds": time.perf_counter() - started,
            "detail": report.get("reason", report["verdict"]),
            "native_steps": [{"name": "pad_assignment_gen", "ran": True, "exit_code": code,
                              "status": status, "detail": report.get("reason", report["verdict"])}]}
