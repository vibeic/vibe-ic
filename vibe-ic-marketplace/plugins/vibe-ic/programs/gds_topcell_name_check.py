#!/usr/bin/env python3
"""
gds_topcell_name_check.py — Deterministic GDSII top-cell-name verifier.

Closes the one GDS-sanity sub-rule that no existing program owned. The
`phase3-backend-verify` skill (checklist item 6) asked Claude to confirm
"top cell name matches the --top-name argument". `gds_size_check.py`
already owns existence / empty / valid-header / min-size; the top-cell
NAME-equality sub-rule is a pure structural string match and is extracted
here so it runs identically every time instead of by hand.

What it does (pure Python, no gdspy/klayout dependency)
-------------------------------------------------------
Parses the GDSII binary records directly:
  * STRNAME (record type 0x06, datatype 0x06)  -> a structure DEFINITION
  * SNAME   (record type 0x12, datatype 0x06)  -> a structure REFERENCE
The TOP cell is the structure that is DEFINED but never REFERENCED by any
other structure (the classic GDSII top-of-hierarchy definition). The check
then verifies:

  1. The GDS contains >= 1 structure definition (else not a real layout).
  2. A structure named exactly <top-name> is DEFINED in the GDS.
  3. (informational) Whether that <top-name> is the/an actual top cell
     (defined-and-never-referenced). If the named cell exists but is
     referenced by something else, that is reported as a WARNING (the
     argument names a sub-cell, not the hierarchy root) — never a vacuous
     pass and never a hard fail, because a single GDS can legitimately
     carry multiple un-referenced tops (e.g. scribe-line + chip).

No fabrication
--------------
The ONLY assertion that can FAIL is a real, checkable structural fact:
the named top cell is/ is-not present as a STRNAME in the file. No size,
PDK, IC, or tool-specific threshold is invented. Missing file / empty
file / no structures / name-absent all FAIL honestly (never vacuous PASS).

Usage
-----
    python3 gds_topcell_name_check.py --gds-file final.gds --top-name chip_top
    python3 gds_topcell_name_check.py --gds-file final.gds --top-name chip_top --json out.json

Exit codes
----------
    0 = the named top cell is present (PASS; possibly WARN if it is a
        referenced sub-cell rather than a hierarchy root)
    1 = file missing/empty/unparseable, no structures, or the named cell
        is absent (FAIL)
    2 = bad arguments

Generality: works for ANY GDSII file + any top-cell name. chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# GDSII record identifiers (big-endian record-length header is bytes 0..1,
# record-type is byte 2, data-type is byte 3).
_REC_STRNAME = (0x06, 0x06)   # structure definition name
_REC_SNAME = (0x12, 0x06)     # structure reference name (SREF/AREF target)
_REC_HEADER = 0x0002          # first record of a valid GDSII stream


@dataclass
class Finding:
    severity: str   # ERROR, WARNING, INFO
    category: str
    message: str
    details: str = ""


def _decode_name(body: bytes) -> str:
    # GDSII strings are NUL-padded to an even length; take up to the first NUL.
    return body.split(b"\x00", 1)[0].decode("ascii", "replace")


def parse_structures(data: bytes) -> Tuple[List[str], set, bool]:
    """Return (defined_names, referenced_names, valid_header).

    Pure-Python GDSII record walk. Robust to truncation: stops cleanly when
    a record length is impossible. Never raises on garbage input.
    """
    defined: List[str] = []
    referenced: set = set()
    valid_header = False
    n = len(data)
    if n >= 4:
        first_type = (data[2] << 8) | data[3]
        valid_header = (first_type == _REC_HEADER)
    i = 0
    while i + 4 <= n:
        rlen = (data[i] << 8) | data[i + 1]
        rtype = data[i + 2]
        dtype = data[i + 3]
        if rlen < 4 or i + rlen > n:
            break  # truncated / malformed — stop the walk honestly
        body = data[i + 4:i + rlen]
        if (rtype, dtype) == _REC_STRNAME:
            defined.append(_decode_name(body))
        elif (rtype, dtype) == _REC_SNAME:
            referenced.add(_decode_name(body))
        i += rlen
    return defined, referenced, valid_header


def check_topcell(gds_path: Path, top_name: str) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    stats: Dict[str, object] = {
        "file_exists": False,
        "valid_header": False,
        "structure_count": 0,
        "top_name_arg": top_name,
        "named_cell_defined": False,
        "named_cell_referenced": False,
        "top_cell_candidates": [],
    }

    if not top_name or not top_name.strip():
        findings.append(Finding(
            "ERROR", "NO_TOP_NAME",
            "no --top-name provided to match against the GDS"))
        return findings, stats

    if not gds_path.exists():
        findings.append(Finding(
            "ERROR", "MISSING_GDS",
            f"GDS file not found: {gds_path}"))
        return findings, stats
    stats["file_exists"] = True

    if gds_path.stat().st_size == 0:
        findings.append(Finding(
            "ERROR", "EMPTY_GDS",
            "GDS file exists but has zero bytes"))
        return findings, stats

    try:
        data = gds_path.read_bytes()
    except OSError as e:
        findings.append(Finding(
            "ERROR", "UNREADABLE_GDS", f"cannot read GDS: {e}"))
        return findings, stats

    defined, referenced, valid_header = parse_structures(data)
    stats["valid_header"] = valid_header
    stats["structure_count"] = len(defined)
    candidates = [d for d in defined if d not in referenced]
    stats["top_cell_candidates"] = candidates

    if not valid_header:
        findings.append(Finding(
            "WARNING", "INVALID_GDS_HEADER",
            "file does not begin with a GDSII HEADER record (0x0002) — "
            "structure parse may be unreliable"))

    if not defined:
        findings.append(Finding(
            "ERROR", "NO_STRUCTURES",
            "GDS contains no structure (STRNAME) definitions — not a real "
            "layout; cannot match a top cell"))
        return findings, stats

    named_defined = top_name in defined
    named_referenced = top_name in referenced
    stats["named_cell_defined"] = named_defined
    stats["named_cell_referenced"] = named_referenced

    if not named_defined:
        findings.append(Finding(
            "ERROR", "TOPCELL_NAME_MISMATCH",
            f"--top-name '{top_name}' is NOT defined as a structure in the "
            f"GDS",
            details=f"defined structures: {sorted(defined)[:20]}"
                    + (" ..." if len(defined) > 20 else "")))
        return findings, stats

    # Named cell is present. Is it actually a top (defined-and-unreferenced)?
    if named_referenced:
        findings.append(Finding(
            "WARNING", "TOPNAME_IS_SUBCELL",
            f"--top-name '{top_name}' IS defined but is also REFERENCED by "
            f"another structure — it is a sub-cell, not the hierarchy root. "
            f"Actual top-cell candidate(s): {candidates}"))
    else:
        findings.append(Finding(
            "INFO", "TOPCELL_MATCH",
            f"--top-name '{top_name}' is defined and is a top cell "
            f"(never referenced by another structure)"))
    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 gds_path: str) -> dict:
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]
    return {
        "program": "gds_topcell_name_check",
        "version": "1.0.0",
        "gds_file": gds_path,
        "summary": {
            "top_name_arg": stats["top_name_arg"],
            "file_exists": stats["file_exists"],
            "structure_count": stats["structure_count"],
            "named_cell_defined": stats["named_cell_defined"],
            "named_cell_referenced": stats["named_cell_referenced"],
            "top_cell_candidates": stats["top_cell_candidates"],
            "errors_count": len(errors),
            "warnings_count": len(warnings),
            "pass": len(errors) == 0,
        },
        "stats": stats,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a GDSII file defines the expected top-cell name")
    parser.add_argument("--gds-file", required=True, help="Path to GDSII file")
    parser.add_argument("--top-name", required=True,
                        help="Expected top-cell name to match")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    gds_path = Path(args.gds_file)
    findings, stats = check_topcell(gds_path, args.top_name)
    report = build_report(findings, stats, str(gds_path))
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)
    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
