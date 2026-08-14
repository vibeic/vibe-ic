#!/usr/bin/env python3
"""
coverage_metric_check.py -- Deterministic coverage report metric checker.

For skill: coverage-closure

Verifies that coverage reports exist and contain parseable percentage metrics.

Checks:
  1. At least 1 coverage file exists
  2. Contains percentage metric (\\d+\\.?\\d*\\s*%)
  3. Coverage value is parseable and >= 0

Usage:
    python3 coverage_metric_check.py <project_dir>
    python3 coverage_metric_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (coverage metrics found)
    1 = FAIL (no coverage report or no percentage found)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
PERCENT_RE = re.compile(r"(\d+\.?\d*)\s*%")

COVERAGE_PATTERNS = [
    "*coverage*.rpt", "*coverage*.log", "*coverage*.txt",
    "*Coverage*.rpt", "*Coverage*.log", "*Coverage*.txt",
    "*.ucdb",  # Questa UCDB summary
]


def audit_coverage(project_dir: Path) -> AuditResult:
    result = AuditResult(program="coverage_metric_check", passed=False)

    if not project_dir.is_dir():
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"files_found": 0, "metrics": []}
        return result

    # Discover coverage files
    found: List[Path] = []
    for pat in COVERAGE_PATTERNS:
        found.extend(project_dir.rglob(pat))

    # Deduplicate
    seen = set()
    unique: List[Path] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    if not unique:
        result.findings.append(Finding(
            rule="COVERAGE_FILE_EXISTS", severity="ERROR",
            message="No coverage report found (searched *coverage*.rpt/log/txt, *.ucdb)"))
        result.summary = {"files_found": 0, "metrics": []}
        return result

    result.findings.append(Finding(
        rule="COVERAGE_FILE_EXISTS", severity="INFO",
        message=f"Found {len(unique)} coverage file(s)",
        file=str(unique[0])))

    # Extract percentage metrics
    all_metrics: List[dict] = []
    for fp in unique:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            result.findings.append(Finding(
                rule="COVERAGE_FILE_READABLE", severity="WARNING",
                message=f"Cannot read file: {fp.name}",
                file=str(fp)))
            continue

        matches = PERCENT_RE.findall(text)
        for m in matches:
            try:
                val = float(m)
                if val >= 0:
                    all_metrics.append({"file": fp.name, "value": val})
            except ValueError:
                continue

    if not all_metrics:
        result.findings.append(Finding(
            rule="COVERAGE_PERCENT_FOUND", severity="ERROR",
            message="No percentage metrics (N%) found in any coverage report",
            file=str(unique[0])))
        result.summary = {"files_found": len(unique), "metrics": []}
        return result

    result.findings.append(Finding(
        rule="COVERAGE_PERCENT_FOUND", severity="INFO",
        message=f"Found {len(all_metrics)} coverage percentage value(s)"))

    result.passed = True
    result.summary = {
        "files_found": len(unique),
        "metric_count": len(all_metrics),
        "metrics": all_metrics[:20],  # Cap output size
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Coverage report metric checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    result = audit_coverage(Path(args.project_dir))

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    # vibe-ic#1080 — emit the per-step metric HERE, where the number was
    # computed, rather than leaving it to be re-parsed out of this report or
    # out of a log. A log regex is a proxy for the measurement, not the
    # measurement. Best-effort: a metrics-sink failure must not change this
    # gate's verdict, which is about coverage, not about bookkeeping.
    try:
        import step_metrics as _sm  # noqa: PLC0415
        _m = {"passed": bool(result.passed),
              "findings_count": len(result.findings)}
        for _k, _v in (result.summary or {}).items():
            if isinstance(_v, (int, float)) and not isinstance(_v, bool):
                _m[str(_k)] = _v
        _sm.emit(Path(args.project_dir), "11", _m, domain="coverage")
    except Exception:  # noqa: BLE001  — see above
        pass

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
