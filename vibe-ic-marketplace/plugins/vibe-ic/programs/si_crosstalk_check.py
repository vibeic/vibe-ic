#!/usr/bin/env python3
"""Verify signal integrity / crosstalk analysis was performed."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    rpt = _pl.report_path(project_dir, "si_crosstalk.rpt")
    jsn = _pl.report_path(project_dir, "si_crosstalk.json")
    waiver = project_dir / "waivers.json"
    stats = {"report_found": False, "format": "", "violations": 0}

    if jsn.exists():
        stats["report_found"] = True
        stats["format"] = "json"
        try:
            data = json.loads(jsn.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(Finding("ERROR", "BAD_JSON",
                                    f"Cannot parse si_crosstalk.json: {exc}"))
            return findings, stats

        for key in ("max_crosstalk_noise", "violations_count"):
            if key not in data:
                findings.append(Finding("ERROR", "MISSING_FIELD",
                                        f"si_crosstalk.json missing '{key}'"))

        violations = data.get("violations_count", 0)
        stats["violations"] = violations
        if isinstance(violations, (int, float)) and violations > 0:
            has_waiver = False
            if waiver.exists():
                try:
                    w = json.loads(waiver.read_text())
                    waivers = w if isinstance(w, list) else w.get("waivers", [])
                    has_waiver = any(
                        e.get("step") == "si_crosstalk" or
                        e.get("category") == "si_crosstalk"
                        for e in waivers if isinstance(e, dict)
                    )
                except (json.JSONDecodeError, OSError):
                    pass
            if not has_waiver:
                findings.append(Finding("ERROR", "SI_VIOLATIONS",
                                        f"{violations} crosstalk violations without waiver"))

    elif rpt.exists():
        stats["report_found"] = True
        stats["format"] = "rpt"
        if rpt.stat().st_size == 0:
            findings.append(Finding("ERROR", "EMPTY_RPT",
                                    "si_crosstalk.rpt is empty"))
    else:
        findings.append(Finding("ERROR", "NO_REPORT",
                                "Neither si_crosstalk.rpt nor si_crosstalk.json found"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "si_crosstalk_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "report_found": stats["report_found"],
            "format": stats["format"],
            "violations": stats["violations"],
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check signal integrity / crosstalk analysis")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
