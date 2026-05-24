#!/usr/bin/env python3
"""
gds_size_check.py — Deterministic GDS file existence and size checker.

Verifies that a GDSII file exists and has a reasonable file size. This catches
the common failure where an agent claims GDS generation succeeded but the
output file is missing, empty, or trivially small (indicating a failed or
incomplete place-and-route).

What it catches:
  1. MISSING_GDS — the GDS file does not exist
  2. EMPTY_GDS — the GDS file has zero bytes
  3. INVALID_GDS_FORMAT — the file does not have a valid GDSII header
  4. TOO_SMALL — the GDS file is below the minimum size threshold

Usage:
    python3 gds_size_check.py --gds-file gds/design.gds [--min-size-kb 100]

Exit codes:
    0 = valid GDS file with sufficient size
    1 = missing, empty, or too small
    2 = parse error / invalid arguments

Generality: works for ANY GDSII file.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
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
    category: str       # MISSING_GDS, EMPTY_GDS, TOO_SMALL
    message: str
    details: str = ""


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_gds(
    gds_path: Path,
    min_size_kb: float = 100.0,
) -> Tuple[List[Finding], dict]:
    """Check GDS file existence and size.

    Returns (findings, stats).
    """
    findings: List[Finding] = []
    min_bytes = int(min_size_kb * 1024)
    stats = {
        "file_exists": False,
        "file_size_bytes": 0,
        "file_size_kb": 0.0,
        "min_size_kb": min_size_kb,
    }

    # Check file exists
    if not gds_path.exists():
        findings.append(Finding(
            severity="ERROR",
            category="MISSING_GDS",
            message=f"GDS file not found: {gds_path}",
        ))
        return findings, stats

    stats["file_exists"] = True
    file_size = gds_path.stat().st_size
    stats["file_size_bytes"] = file_size
    stats["file_size_kb"] = round(file_size / 1024, 2)

    # Check for zero size
    if file_size == 0:
        findings.append(Finding(
            severity="ERROR",
            category="EMPTY_GDS",
            message="GDS file exists but has zero bytes",
        ))
        return findings, stats

    # Check GDSII magic number: first record must be HEADER (record type 0x0002)
    try:
        with open(gds_path, 'rb') as f:
            header = f.read(4)
        if len(header) >= 4:
            record_type = (header[2] << 8) | header[3]
            if record_type != 0x0002:
                findings.append(Finding(
                    severity="WARNING",
                    category="INVALID_GDS_FORMAT",
                    message="File does not have a valid GDSII header (expected record type 0x0002 HEADER)",
                    details=f"Bytes 2-3: 0x{header[2]:02x}{header[3]:02x} (expected 0x0002)",
                ))
    except OSError:
        pass  # file read issue already covered by existence check

    # Check minimum size
    if file_size < min_bytes:
        findings.append(Finding(
            severity="ERROR",
            category="TOO_SMALL",
            message=(
                f"GDS file is {stats['file_size_kb']} KB, "
                f"minimum required is {min_size_kb} KB"
            ),
            details=f"File size: {file_size} bytes, threshold: {min_bytes} bytes",
        ))

    return findings, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], stats: dict,
                 gds_path: str) -> dict:
    return {
        "program": "gds_size_check",
        "version": "1.1.0",
        "gds_file": gds_path,
        "summary": {
            "file_exists": stats["file_exists"],
            "file_size_kb": stats["file_size_kb"],
            "min_size_kb": stats["min_size_kb"],
            "findings_count": len(findings),
            "warnings_count": len([f for f in findings if f.severity == "WARNING"]),
            "errors_count": len([f for f in findings if f.severity == "ERROR"]),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "stats": stats,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify GDS file exists and has reasonable size"
    )
    parser.add_argument('--gds-file', required=True,
                        help="Path to GDSII file")
    parser.add_argument('--min-size-kb', type=float, default=100.0,
                        help="Minimum file size in KB (default: 100)")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    gds_path = Path(args.gds_file)
    findings, stats = audit_gds(gds_path, args.min_size_kb)

    report = build_report(findings, stats, str(gds_path))
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
