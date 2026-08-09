#!/usr/bin/env python3
"""
gds_size_check.py — Deterministic GDS file existence and size checker.

Verifies that a GDSII file exists and has a reasonable file size. This catches
the common failure where an agent claims GDS generation succeeded but the
output file is missing, empty, or trivially small (indicating a failed or
incomplete place-and-route).

What it catches (all five are hard ERRORs — every one can redden the gate):
  1. MISSING_GDS — the GDS file does not exist
  2. UNREADABLE_GDS — the file exists but cannot be opened for reading
  3. EMPTY_GDS — the GDS file has zero bytes
  4. INVALID_GDS_FORMAT — the file does not have a valid GDSII header
  5. TOO_SMALL — the GDS file is below the minimum size threshold

Usage:
    python3 gds_size_check.py --gds-file gds/design.gds [--min-size-kb 100]

Exit codes:
    0 = valid GDS file with sufficient size
    1 = missing, unreadable, empty, not a GDSII stream, or too small
    2 = invalid command-line arguments (raised by argparse)

    There is deliberately no "parse error" exit 2: this program has no parse
    stage, and rc 2 is spoken for elsewhere in this flow as VACUOUS_PASS. The
    docstring used to advertise one; it was never reachable from main().

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
    category: str       # MISSING_GDS, UNREADABLE_GDS, EMPTY_GDS,
                        # INVALID_GDS_FORMAT, TOO_SMALL
    message: str
    details: str = ""


#: First four bytes of every GDSII stream: record length 0x0006, record type
#: 0x00 (HEADER), data type 0x02 (2-byte integer). The magic tested here is
#: bytes 2-3 only — deliberately the SAME predicate this program has always
#: computed. This change is about which verdict that predicate can reach, not
#: about widening what it detects.
GDSII_HEADER_RECORD = 0x0002


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
        # None = not determined (file absent/unreadable); True/False = the
        # first record either is or is not a GDSII HEADER. Emitted so the
        # JSON report carries the distinction the verdict now makes.
        "gdsii_header_ok": None,
        "header_bytes_hex": None,
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
    #
    # THE FIX (was: unreachable verdict). This block used to emit
    # severity="WARNING" and to swallow OSError with `pass`. Since the verdict
    # is `pass = all(f.severity != "ERROR")` and the only caller — flow step 37,
    # `program_exit_zero: "gds_size_check --gds-file ... --json ..."` — reads
    # nothing but the exit code, NO input could make this block change the
    # answer. The module docstring advertised INVALID_GDS_FORMAT as one of the
    # things the check catches, yet the FAIL verdict for it was structurally
    # unreachable: anything above the size floor that is not a GDSII at all (a
    # renamed .def, a padded log, a random blob) signed off `pass: true, exit 0`.
    #
    # Mechanism chosen: correct the DEFAULT, do not add an opt-in flag. The one
    # real caller passes no arguments beyond --gds-file/--json, so a flag would
    # have to default to off to be compatible — which is exactly the shape that
    # made this verdict unreachable in the first place.
    #
    # Measured blast radius before landing: 12/12 real streamed .gds artefacts
    # in this repo begin 00 06 00 02, and 20/20 previously emitted
    # reports/phase3/gds_size.json recorded warnings_count 0. No run that a real
    # stream-out produced flips.
    header = None
    try:
        with open(gds_path, 'rb') as f:
            header = f.read(4)
    except OSError as exc:
        # NOT "already covered by the existence check": exists() says nothing
        # about readability. Swallowing this signed off files nobody could read.
        findings.append(Finding(
            severity="ERROR",
            category="UNREADABLE_GDS",
            message=f"GDS file exists but could not be read: {gds_path}",
            details=f"{type(exc).__name__}: {exc}",
        ))

    if header is not None:
        stats["header_bytes_hex"] = header.hex()
        if len(header) < 4:
            stats["gdsii_header_ok"] = False
            findings.append(Finding(
                severity="ERROR",
                category="INVALID_GDS_FORMAT",
                message=(
                    "File is too short to contain a GDSII HEADER record "
                    f"({len(header)} byte(s) readable, 4 required)"
                ),
                details=f"Leading bytes: 0x{header.hex() or '(none)'}",
            ))
        else:
            record_type = (header[2] << 8) | header[3]
            stats["gdsii_header_ok"] = record_type == GDSII_HEADER_RECORD
            if record_type != GDSII_HEADER_RECORD:
                findings.append(Finding(
                    severity="ERROR",
                    category="INVALID_GDS_FORMAT",
                    message="File does not have a valid GDSII header (expected record type 0x0002 HEADER)",
                    details=f"Bytes 2-3: 0x{header[2]:02x}{header[3]:02x} (expected 0x0002)",
                ))

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
        "version": "1.2.0",
        "gds_file": gds_path,
        "summary": {
            "file_exists": stats["file_exists"],
            "gdsii_header_ok": stats["gdsii_header_ok"],
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
