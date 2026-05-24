#!/usr/bin/env python3
"""
provenance_hash_audit.py — v0.114 (BACKLOG-v10 P2.3).

Verify that PASS-verdict gate reports carry non-trivial provenance:
referenced output files exist on disk and their hashes match. Catches
the "stub-flag PASS" anti-pattern where a step verdict is PASS but the
required_output is empty / missing / a one-line placeholder.

False-positive guarded:
  - WARN-only on missing output_files (existing gates may not yet emit
    sha256). Won't all-fail legacy projects.
  - ERROR only on definitively-stale provenance: hash recorded but the
    file is gone, OR the file exists but its current sha256 differs from
    the recorded hash AND the file's mtime is older than the gate run
    (meaning the gate ran on a different file than what's there now).
  - File-not-exist + no hash recorded → INFO (nothing to verify).
  - Skip gracefully if no gate_reports/ directory.

Usage:
  python3 provenance_hash_audit.py <project_dir> [--json [PATH]] [--strict]

In --strict mode, missing output_files becomes ERROR. Default lenient.
Exit 0 PASS, 1 FAIL, 2 IO error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan_gate_reports(project: Path) -> List[Path]:
    out = []
    for d in (project / "gate_reports", project / "reports"):
        if not d.is_dir():
            continue
        for p in d.rglob("*.json"):
            out.append(p)
    return out


def _interpret(report: Any) -> Optional[bool]:
    """Best-effort: is this gate PASS? Handles dict / list / unknown."""
    if not isinstance(report, dict):
        return None
    summary = report.get("summary") or {}
    if isinstance(summary, dict):
        if summary.get("pass") is True:
            return True
        if summary.get("pass") is False:
            return False
    s = report.get("status") or report.get("verdict")
    if isinstance(s, str):
        if s.upper() in ("PASS", "OK"):
            return True
        if s.upper() in ("FAIL", "ERROR"):
            return False
    return None


def main():
    ap = argparse.ArgumentParser(description=(
        "Audit gate reports' provenance hashes — catch stub PASS verdicts."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--strict", action="store_true",
                    help="Treat missing output_files / hashes as ERROR (default WARN)")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    findings: List[Finding] = []
    reports = _scan_gate_reports(project)

    if not reports:
        result = {
            "program": "provenance_hash_audit",
            "version": "1.0.0",
            "project": str(project),
            "summary": {
                "skip": True,
                "reason": "no gate_reports/ or reports/ directory",
                "pass": True,
            },
            "findings": [],
        }
        if args.json is None:
            print("[PASS] provenance_hash_audit (skip — no reports dir)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
        return 0

    pass_count = 0
    fail_count = 0
    no_pass_marker = 0
    audited = 0

    for rpath in reports:
        try:
            d = json.loads(rpath.read_text())
        except Exception:
            findings.append(Finding(
                severity="WARN",
                category="REPORT_UNPARSEABLE",
                message=f"{rpath.relative_to(project)} is not valid JSON",
            ))
            continue
        verdict = _interpret(d)
        if verdict is None:
            no_pass_marker += 1
            continue
        if not verdict:
            fail_count += 1
            continue  # FAIL gates aren't required to have provenance
        pass_count += 1
        # PASS — verify provenance if any
        # Look for output_files: [{path, sha256}] OR outputs / artefacts arrays
        outputs = (
            d.get("output_files")
            or d.get("outputs")
            or d.get("artefacts")
            or d.get("evidence_files")
            or []
        )
        if not isinstance(outputs, list) or not outputs:
            sev = "ERROR" if args.strict else "WARN"
            findings.append(Finding(
                severity=sev,
                category="NO_PROVENANCE",
                message=(
                    f"{rpath.relative_to(project)} has PASS verdict but no "
                    f"output_files / outputs / artefacts list. Cannot "
                    f"verify the PASS is backed by real artefacts."
                ),
            ))
            continue
        audited += 1
        for entry in outputs:
            if isinstance(entry, str):
                fpath = (project / entry).resolve() if not Path(entry).is_absolute() else Path(entry)
                recorded_hash = None
            elif isinstance(entry, dict):
                fpath_str = entry.get("path") or entry.get("file") or entry.get("name") or ""
                if not fpath_str:
                    continue
                fpath = (project / fpath_str).resolve() if not Path(fpath_str).is_absolute() else Path(fpath_str)
                recorded_hash = entry.get("sha256") or entry.get("hash")
            else:
                continue
            try:
                fpath.relative_to(project)
            except ValueError:
                continue  # outside project — skip silently
            if not fpath.exists():
                findings.append(Finding(
                    severity="ERROR",
                    category="STALE_OUTPUT",
                    message=(
                        f"gate {rpath.name}: PASS verdict references "
                        f"output {fpath} which does not exist"
                    ),
                ))
                continue
            if recorded_hash:
                actual = _sha256(fpath)
                if actual.lower() != str(recorded_hash).lower().replace("sha256:", ""):
                    findings.append(Finding(
                        severity="ERROR",
                        category="HASH_MISMATCH",
                        message=(
                            f"gate {rpath.name}: output {fpath} hash "
                            f"mismatch (recorded {recorded_hash[:16]}.., "
                            f"current {actual[:16]}..)"
                        ),
                    ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)
    result = {
        "program": "provenance_hash_audit",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "reports_scanned": len(reports),
            "pass_verdicts": pass_count,
            "fail_verdicts": fail_count,
            "indeterminate": no_pass_marker,
            "audited_with_provenance": audited,
            "strict_mode": args.strict,
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] provenance_hash_audit{' (strict)' if args.strict else ''}")
        print(f"  reports scanned: {len(reports)}")
        print(f"  PASS verdicts: {pass_count} ({audited} with output_files)")
        for f in findings[:10]:
            print(f"  [{f.severity}] {f.category}: {f.message}")
        if len(findings) > 10:
            print(f"  ... +{len(findings)-10} more findings")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
