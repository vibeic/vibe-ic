#!/usr/bin/env python3
"""Verify parasitic extraction (SPEF) was produced after routing."""
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


def _waiver_reason(project_dir: Path) -> str:
    """Return the spef_extraction_unavailable_reason waiver text, or ""."""
    waivers = project_dir / "waivers.json"
    if not waivers.is_file():
        return ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return ""
    val = d.get("spef_extraction_unavailable_reason", "")
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return "\n".join(str(x).strip() for x in val if str(x).strip())
    return ""


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    extracted = _pl.extracted_dir(project_dir)
    stats = {"spef_files": 0, "total_bytes": 0, "has_nets": False,
             "waived": False}

    # v0.119.21: tool-unavailable-for-PDK waiver. Custom PDKs without a
    # Magic .tech file (<foundry> m18e80pm180su, etc.) cannot run
    # parasitic extraction in the open-source flow. The honest path is
    # a documented waiver with a reason ≥20 chars (matches the waivers
    # schema's anti-rubber-stamp policy). No content fabrication.
    reason = _waiver_reason(project_dir)
    if reason and len(reason) >= 20:
        stats["waived"] = True
        findings.append(Finding(
            "INFO", "WAIVED_TOOL_UNAVAILABLE",
            "SPEF extraction waived: open-source toolchain has no extraction "
            "path for this PDK",
            details=reason,
        ))
        return findings, stats

    if not extracted.is_dir():
        findings.append(Finding("ERROR", "NO_EXTRACTED_DIR",
                                "extracted/ directory not found"))
        return findings, stats

    spef_files = sorted(extracted.glob("*.spef"))
    stats["spef_files"] = len(spef_files)

    if not spef_files:
        findings.append(Finding("ERROR", "NO_SPEF",
                                "No .spef files in extracted/"))
        return findings, stats

    for sf in spef_files:
        size = sf.stat().st_size
        stats["total_bytes"] += size

        if size == 0:
            findings.append(Finding("ERROR", "EMPTY_SPEF",
                                    f"Empty SPEF: {sf.name}"))
            continue

        if size < 1024:
            findings.append(Finding("ERROR", "TOO_SMALL",
                                    f"SPEF file {sf.name} is {size} bytes (<1 KB)"))
            continue

        text = sf.read_text(errors="replace")[:8192]
        has_header = "*SPEF" in text
        has_design = "*DESIGN" in text or "*DATE" in text
        has_nets = "*D_NET" in text or "*R_NET" in text

        if not has_header:
            findings.append(Finding("ERROR", "BAD_HEADER",
                                    f"{sf.name} missing *SPEF header"))
        if not has_design:
            findings.append(Finding("WARNING", "MISSING_METADATA",
                                    f"{sf.name} missing *DESIGN or *DATE"))
        if has_nets:
            stats["has_nets"] = True
        else:
            findings.append(Finding("WARNING", "NO_NETS",
                                    f"{sf.name} has no *D_NET/*R_NET entries"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "spef_extraction_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "spef_files": stats["spef_files"],
            "total_bytes": stats["total_bytes"],
            "has_nets": stats["has_nets"],
            "waived": stats.get("waived", False),
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check SPEF extraction artifacts")
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
