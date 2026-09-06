#!/usr/bin/env python3
"""
eda_log_check.py — Deterministic EDA tool log/report checker.

Verifies EDA tool execution by checking for log/report files with expected
content patterns and absence of error patterns.

What it catches:
  1. LOG_MISSING — log/report file does not exist
  2. EMPTY_LOG — log file exists but is empty
  3. STALE_LOG — log file is older than max-age-hours (WARNING)
  4. EXPECTED_NOT_FOUND — none of the expected patterns were found
  5. REJECTED_FOUND — a reject pattern was found (Error, FATAL, etc.)

Usage:
    python3 eda_log_check.py --log-file reports/synth.log \
        --expect-pattern "Number of cells|Chip area" \
        --reject-pattern "Error|FATAL"

Exit codes:
    0 = log exists + expected content found + no rejected content
    1 = missing log, empty log, expected not found, or rejected found
    2 = parse error / invalid arguments

Generality: works for ANY EDA tool log (Yosys, OpenROAD, Cadence, Synopsys, etc.).
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_receipt import emit_receipt  # noqa: E402


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # LOG_MISSING, EMPTY_LOG, STALE_LOG, EXPECTED_NOT_FOUND, REJECTED_FOUND
    message: str
    file: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_log(
    log_file: Path,
    expect_patterns: List[str],
    reject_patterns: List[str],
    max_age_hours: Optional[float] = None,
) -> Tuple[List[Finding], dict]:
    """Check an EDA log file for expected and rejected patterns.

    Returns (findings, info_dict).
    """
    findings: List[Finding] = []
    info = {
        "log_file": str(log_file),
        "expect_matched": [],
        "reject_matched": [],
        "line_count": 0,
    }

    # Check file exists
    if not log_file.exists():
        findings.append(Finding(
            severity="ERROR",
            category="LOG_MISSING",
            message=f"Log file does not exist: {log_file}",
            file=str(log_file),
        ))
        return findings, info

    # Freshness check
    if max_age_hours is not None:
        mtime = log_file.stat().st_mtime
        age_hours = (time.time() - mtime) / 3600
        if age_hours > max_age_hours:
            findings.append(Finding(
                severity="WARNING",
                category="STALE_LOG",
                message=(
                    f"Log file is {age_hours:.1f} hours old "
                    f"(threshold: {max_age_hours} hours)"
                ),
                file=str(log_file),
                details=f"Last modified: {time.ctime(mtime)}",
            ))

    # Read content
    text = log_file.read_text(errors='replace')
    lines = text.split('\n')
    info["line_count"] = len(lines)

    # Check empty
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        findings.append(Finding(
            severity="ERROR",
            category="EMPTY_LOG",
            message="Log file is empty",
            file=str(log_file),
        ))
        return findings, info

    # Check expect patterns (at least one must match)
    if expect_patterns:
        for pat in expect_patterns:
            pat = pat.strip()
            if not pat:
                continue
            try:
                regex = re.compile(pat, re.IGNORECASE)
            except re.error:
                # Treat as literal string match
                if pat.lower() in text.lower():
                    info["expect_matched"].append(pat)
                continue
            if regex.search(text):
                info["expect_matched"].append(pat)

        if not info["expect_matched"]:
            findings.append(Finding(
                severity="ERROR",
                category="EXPECTED_NOT_FOUND",
                message="None of the expected patterns were found in log",
                file=str(log_file),
                details=f"Expected patterns: {expect_patterns}",
            ))

    # Check reject patterns (none should match)
    if reject_patterns:
        for pat in reject_patterns:
            pat = pat.strip()
            if not pat:
                continue
            try:
                regex = re.compile(pat, re.IGNORECASE)
            except re.error:
                if pat.lower() in text.lower():
                    info["reject_matched"].append(pat)
                    # Find the offending line
                    for i, line in enumerate(lines, 1):
                        if pat.lower() in line.lower():
                            findings.append(Finding(
                                severity="ERROR",
                                category="REJECTED_FOUND",
                                message=f"Rejected pattern found: '{pat}'",
                                file=str(log_file),
                                details=f"L{i}: {line.strip()[:200]}",
                            ))
                            break
                continue

            match = regex.search(text)
            if match:
                info["reject_matched"].append(pat)
                # Find the offending line for reporting
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        findings.append(Finding(
                            severity="ERROR",
                            category="REJECTED_FOUND",
                            message=f"Rejected pattern found: '{pat}'",
                            file=str(log_file),
                            details=f"L{i}: {line.strip()[:200]}",
                        ))
                        break

    return findings, info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], info: dict) -> dict:
    return {
        "program": "eda_log_check",
        "version": "1.1.0",
        "log_file": info["log_file"],
        "summary": {
            "line_count": info["line_count"],
            "expect_matched": info["expect_matched"],
            "reject_matched": info["reject_matched"],
            "findings_count": len(findings),
            "warnings_count": len([f for f in findings if f.severity == "WARNING"]),
            "errors_count": len([f for f in findings if f.severity == "ERROR"]),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify EDA tool log/report exists with expected content"
    )
    parser.add_argument('--log-file', required=True,
                        help="Path to the EDA log/report file")
    parser.add_argument('--expect-pattern', default="",
                        help="Pipe-separated expected patterns (at least one must match)")
    parser.add_argument('--reject-pattern', default="",
                        help="Pipe-separated reject patterns (none should match)")
    parser.add_argument('--max-age-hours', type=float, default=None,
                        help="Maximum log age in hours (default: no check; e.g. 168 = 1 week)")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    log_file = Path(args.log_file)
    expect_patterns = [p for p in args.expect_pattern.split('|') if p.strip()] if args.expect_pattern else []
    reject_patterns = [p for p in args.reject_pattern.split('|') if p.strip()] if args.reject_pattern else []

    findings, info = audit_log(log_file, expect_patterns, reject_patterns, args.max_age_hours)

    report = build_report(findings, info)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)
        # #2050 — producer-written receipt (see programs/_audit_receipt.py).
        # `examined` is the log's line count: a zero-line log that matched no
        # reject pattern is a pass over nothing, and must not read as a tool
        # log that was checked.
        emit_receipt(
            'eda_log_check', args.json,
            'PASS' if report["summary"]["pass"] else 'FAIL',
            int(info["line_count"] or 0), [log_file],
            extra={'expect_matched': info["expect_matched"],
                   'reject_matched': info["reject_matched"]})

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
