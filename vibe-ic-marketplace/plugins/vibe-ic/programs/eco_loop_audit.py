#!/usr/bin/env python3
"""Audit ECO (Engineering Change Order) log for completeness."""
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
    eco_dir = _pl.eco_dir(project_dir)
    eco_log = eco_dir / "eco_log.json"
    no_eco = eco_dir / "no_eco_needed.flag"
    stats = {"eco_needed": None, "changes_count": 0, "re_verified": False}

    if no_eco.exists():
        stats["eco_needed"] = False
        return findings, stats

    if not eco_log.exists():
        findings.append(Finding("ERROR", "NO_ECO_ARTIFACT",
                                "Neither eco/eco_log.json nor eco/no_eco_needed.flag found"))
        return findings, stats

    stats["eco_needed"] = True
    try:
        data = json.loads(eco_log.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        findings.append(Finding("ERROR", "BAD_JSON",
                                f"Cannot parse eco_log.json: {exc}"))
        return findings, stats

    changes = data.get("changes", [])
    if not isinstance(changes, list) or len(changes) == 0:
        findings.append(Finding("ERROR", "EMPTY_CHANGES",
                                "eco_log.json 'changes' array is missing or empty"))
    stats["changes_count"] = len(changes) if isinstance(changes, list) else 0

    re_verified = data.get("re_verified", False)
    stats["re_verified"] = bool(re_verified)
    if not re_verified:
        findings.append(Finding("ERROR", "NOT_REVERIFIED",
                                "ECO applied but re_verified is false — must re-run sign-off"))

    if "affected_steps" not in data:
        findings.append(Finding("WARNING", "NO_AFFECTED_STEPS",
                                "eco_log.json missing 'affected_steps' array"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "eco_loop_audit",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "eco_needed": stats["eco_needed"],
            "changes_count": stats["changes_count"],
            "re_verified": stats["re_verified"],
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Audit ECO log completeness")
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
