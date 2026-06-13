#!/usr/bin/env python3
"""
output_artifact_check.py — Deterministic output artifact existence checker.

Verifies that files an agent claimed to produce actually exist on disk.
Supports both explicit file lists and glob patterns with minimum count.

What it catches:
  1. MISSING_ARTIFACT — a claimed output file does not exist
  2. EMPTY_FILE — a claimed output file exists but has 0 bytes
  3. GLOB_NO_MATCH — a glob pattern matched fewer files than required
  4. BASE_DIR_MISSING — the base directory itself does not exist

Usage:
    python3 output_artifact_check.py --artifacts file1.v,file2.json --base-dir /path/to/project
    python3 output_artifact_check.py --pattern "phase2/stage1/rtl/*.v" --base-dir /path --min-count 3

Exit codes:
    0 = all artifacts exist (or glob meets min-count)
    1 = any artifact missing (or glob below min-count)
    2 = parse error / invalid arguments

Generality: works for ANY file type in ANY project directory.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # MISSING_ARTIFACT, GLOB_NO_MATCH, BASE_DIR_MISSING
    message: str
    file: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_artifacts(
    base_dir: Path,
    artifacts: List[str],
    pattern: str = "",
    min_count: int = 1,
) -> Tuple[List[Finding], dict]:
    """Check that all listed artifacts exist, and/or glob pattern meets min count.

    Returns (findings, summary_info).
    """
    findings: List[Finding] = []
    info = {
        "base_dir": str(base_dir),
        "checked_artifacts": [],
        "glob_pattern": pattern,
        "glob_matches": [],
    }

    # Check base dir exists
    if not base_dir.exists():
        findings.append(Finding(
            severity="ERROR",
            category="BASE_DIR_MISSING",
            message=f"Base directory does not exist: {base_dir}",
        ))
        return findings, info

    # Check explicit artifact list
    for artifact in artifacts:
        artifact = artifact.strip()
        if not artifact:
            continue
        full_path = base_dir / artifact
        info["checked_artifacts"].append(str(artifact))
        if not full_path.exists():
            findings.append(Finding(
                severity="ERROR",
                category="MISSING_ARTIFACT",
                message=f"Artifact not found: {artifact}",
                file=str(full_path),
            ))
        elif full_path.stat().st_size == 0:
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_FILE",
                message=f"Artifact exists but is empty (0 bytes): {artifact}",
                file=str(full_path),
            ))

    # Check glob pattern
    if pattern:
        glob_path = str(base_dir / pattern)
        matches = sorted(globmod.glob(glob_path, recursive=True))
        info["glob_matches"] = [str(m) for m in matches]
        if len(matches) < min_count:
            findings.append(Finding(
                severity="ERROR",
                category="GLOB_NO_MATCH",
                message=(
                    f"Glob pattern '{pattern}' matched {len(matches)} file(s), "
                    f"minimum required is {min_count}"
                ),
                details=f"Matches: {matches}",
            ))

    return findings, info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], info: dict,
                 min_count: int) -> dict:
    return {
        "program": "output_artifact_check",
        "version": "1.1.0",
        "base_dir": info["base_dir"],
        "summary": {
            "artifacts_checked": len(info["checked_artifacts"]),
            "glob_pattern": info["glob_pattern"],
            "glob_match_count": len(info["glob_matches"]),
            "min_count": min_count,
            "findings_count": len(findings),
            "pass": len(findings) == 0,
        },
        "checked_artifacts": info["checked_artifacts"],
        "glob_matches": info["glob_matches"],
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify output artifacts exist on disk"
    )
    parser.add_argument('--artifacts', default="",
                        help="Comma-separated list of artifact paths (relative to base-dir)")
    parser.add_argument('--base-dir', required=True,
                        help="Base directory for artifact resolution")
    parser.add_argument('--pattern', default="",
                        help="Glob pattern to check (e.g. 'phase2/stage1/rtl/*.v')")
    parser.add_argument('--min-count', type=int, default=1,
                        help="Minimum number of glob matches required (default: 1)")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir)
    artifacts = [a for a in args.artifacts.split(',') if a.strip()] if args.artifacts else []

    findings, info = audit_artifacts(base_dir, artifacts, args.pattern, args.min_count)

    report = build_report(findings, info, args.min_count)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
