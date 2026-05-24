#!/usr/bin/env python3
"""
constants_validation.py — Deterministic compliance check for rtl-constants-gen.

Verifies that RTL constants JSON files contain well-formed constant definitions
with required fields (name, value, width/bits) and no duplicates.

What it catches:
  1. NO_CONSTANTS_FILE — no *constants*.json or *rtl_constants*.json found
  2. INVALID_JSON — file is not valid JSON or cannot be parsed
  3. MISSING_FIELD — a constant entry is missing a required field
  4. INVALID_FIELD — a field has an invalid value (empty name, null value, bad width)
  5. DUPLICATE_NAME — two or more constants share the same name
  6. EMPTY_CONSTANTS — file parses but contains zero constant entries
  7. SECTION_STRUCTURE — (WARNING) no recognized section keys in top-level dict
  8. MISSING_COMMENT — (WARNING) a constant entry has no 'comment' field

Usage:
    python3 constants_validation.py ./my_project
    python3 constants_validation.py ./my_project --json

Exit codes:
    0 = all checks pass
    1 = one or more checks fail

Generality: works for ANY IC project with RTL constants JSON.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import os
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
    severity: str       # ERROR, WARNING, INFO
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_constants_files(base: Path) -> List[Path]:
    """Find JSON files matching *constants*.json or *rtl_constants*.json."""
    found: List[Path] = []
    for fpath in sorted(base.rglob("*.json")):
        name_lower = fpath.name.lower()
        if "constants" in name_lower:
            found.append(fpath)
    return found


# ---------------------------------------------------------------------------
# Extract constants list from parsed JSON
# ---------------------------------------------------------------------------
def extract_constants(data) -> list:
    """Extract the list of constant entries from a parsed JSON structure.

    Handles both:
      - Top-level list: [{name, value, width}, ...]
      - Dict with a 'constants' key: {"constants": [...]}
      - Dict with other keys wrapping lists
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Prefer explicit 'constants' key
        for key in ("constants", "rtl_constants", "params", "parameters"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Fall back: find the first list value
        for v in data.values():
            if isinstance(v, list) and len(v) > 0:
                return v
    return []


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit(project_dir: str) -> AuditResult:
    findings: List[Finding] = []
    base = Path(project_dir)

    if not base.exists() or not base.is_dir():
        findings.append(Finding(
            rule="DIR_MISSING",
            severity="ERROR",
            message=f"Project directory does not exist: {project_dir}",
        ))
        return AuditResult(
            program="constants_validation",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "constants_total": 0},
        )

    json_files = discover_constants_files(base)

    if not json_files:
        findings.append(Finding(
            rule="NO_CONSTANTS_FILE",
            severity="ERROR",
            message="No *constants*.json files found in project directory",
        ))
        return AuditResult(
            program="constants_validation",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "constants_total": 0},
        )

    all_names: dict = {}  # name -> file (for duplicate detection across files)
    total_constants = 0

    for jf in json_files:
        rel = str(jf.relative_to(base)) if jf.is_relative_to(base) else str(jf)

        # Parse JSON
        try:
            raw = jf.read_text(errors="replace")
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            findings.append(Finding(
                rule="INVALID_JSON",
                severity="ERROR",
                message=f"Invalid JSON: {e}",
                file=rel,
            ))
            continue
        except OSError as e:
            findings.append(Finding(
                rule="READ_ERROR",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        # ----- Section structure check (WARNING, not ERROR) -----
        RECOGNIZED_SECTIONS = {
            "tx_phy_constants", "rx_phy_constants", "crc8_constants",
            "mac_key_signals", "port_naming_convention",
        }
        if isinstance(data, dict):
            has_section = any(k in data for k in RECOGNIZED_SECTIONS)
            has_constants_key = "constants" in data
            if not has_section and not has_constants_key:
                findings.append(Finding(
                    rule="SECTION_STRUCTURE",
                    severity="WARNING",
                    message="No recognized section structure "
                            "(tx_phy, rx_phy, crc8, mac, port_naming)",
                    file=rel,
                ))

        constants = extract_constants(data)

        if len(constants) == 0:
            findings.append(Finding(
                rule="EMPTY_CONSTANTS",
                severity="ERROR",
                message="File contains zero constant entries",
                file=rel,
            ))
            continue

        for idx, entry in enumerate(constants):
            prefix = f"constants[{idx}]"

            if not isinstance(entry, dict):
                findings.append(Finding(
                    rule="INVALID_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: entry is not a dict (got {type(entry).__name__})",
                    file=rel,
                ))
                continue

            # Check 'name'
            name = entry.get("name")
            if name is None or (isinstance(name, str) and name.strip() == ""):
                findings.append(Finding(
                    rule="MISSING_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: missing or empty 'name'",
                    file=rel,
                ))
            else:
                name_str = str(name).strip()
                # Duplicate check
                if name_str in all_names:
                    findings.append(Finding(
                        rule="DUPLICATE_NAME",
                        severity="ERROR",
                        message=f"{prefix}: duplicate constant name '{name_str}' "
                                f"(first seen in {all_names[name_str]})",
                        file=rel,
                    ))
                else:
                    all_names[name_str] = rel

            # Check 'value'
            if "value" not in entry or entry["value"] is None:
                findings.append(Finding(
                    rule="MISSING_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: missing or null 'value'",
                    file=rel,
                ))

            # Check 'comment' (WARNING only)
            if "comment" not in entry:
                findings.append(Finding(
                    rule="MISSING_COMMENT",
                    severity="WARNING",
                    message=f"{prefix}: missing 'comment' field",
                    file=rel,
                ))

            # Check 'width' or 'bits'
            width = entry.get("width", entry.get("bits"))
            if width is None:
                findings.append(Finding(
                    rule="MISSING_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: missing 'width' or 'bits' field",
                    file=rel,
                ))
            else:
                try:
                    w = int(width)
                    if w <= 0:
                        findings.append(Finding(
                            rule="INVALID_FIELD",
                            severity="ERROR",
                            message=f"{prefix}: 'width'/'bits' must be > 0 (got {w})",
                            file=rel,
                        ))
                except (ValueError, TypeError):
                    findings.append(Finding(
                        rule="INVALID_FIELD",
                        severity="ERROR",
                        message=f"{prefix}: 'width'/'bits' is not a valid integer (got {width!r})",
                        file=rel,
                    ))

            total_constants += 1

    # Final: at least 1 constant total
    if total_constants == 0 and not any(f.rule == "EMPTY_CONSTANTS" for f in findings):
        findings.append(Finding(
            rule="EMPTY_CONSTANTS",
            severity="ERROR",
            message="No valid constant entries found across all files",
        ))

    passed = not any(f.severity == "ERROR" for f in findings)
    return AuditResult(
        program="constants_validation",
        passed=passed,
        findings=findings,
        summary={
            "files_checked": len(json_files),
            "constants_total": total_constants,
            "duplicates": sum(1 for f in findings if f.rule == "DUPLICATE_NAME"),
            "errors": sum(1 for f in findings if f.severity == "ERROR"),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for rtl-constants-gen"
    )
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true",
                   help="Output JSON report to stdout")
    args = p.parse_args()

    result = audit(args.project_dir)

    if args.json:
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    else:
        for f in result.findings:
            tag = f"[{f.file}] " if f.file else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{status} — {result.summary}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
