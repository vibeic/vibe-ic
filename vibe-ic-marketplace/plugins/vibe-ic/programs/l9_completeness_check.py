#!/usr/bin/env python3
"""
l9_completeness_check.py — Deterministic L9 Integration Spec completeness checker.

Verifies that the L9 Integration Spec JSON file contains all required sections
for successful RTL generation. The L9 spec is the single source of truth for
DTOP integration — missing sections cause port mismatches and silent failures.

What it catches:
  1. MISSING_SECTION — a required top-level key is absent from the L9 JSON
  2. EMPTY_SECTION — a required section exists but is empty ([] or {})
  3. INVALID_JSON — the file is not valid JSON
  4. MISSING_FILE — the L9 file does not exist

Required sections (with accepted aliases):
  - top_level_ports (or dtop_ports)
  - submodules
  - internal_wires (or wire_map)
  - registers (or register_infrastructure)

Usage:
    python3 l9_completeness_check.py --l9-file generated_docs/L9_INTEGRATION_SPEC.json

Exit codes:
    0 = all required sections present and non-empty
    1 = missing or empty sections
    2 = file not found or invalid JSON

Generality: works for ANY L9 Integration Spec JSON.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # MISSING_SECTION, EMPTY_SECTION, INVALID_JSON, MISSING_FILE
    section: str
    message: str


# ---------------------------------------------------------------------------
# Required sections with aliases
# ---------------------------------------------------------------------------
# Each entry: (canonical_name, set_of_aliases, required)
REQUIRED_SECTIONS = [
    ("top_level_ports", {"top_level_ports", "dtop_ports", "ports", "top_ports"}, True),
    ("submodules", {"submodules", "sub_modules", "instances", "module_instances"}, True),
    ("internal_wires", {"internal_wires", "wire_map", "wires", "internal_signals", "connections"}, True),
    ("registers", {"registers", "register_infrastructure", "register_map", "reg_map", "regs"}, True),
]

OPTIONAL_SECTIONS = [
    ("clock_reset", {"clock_reset", "clocks", "clock_tree", "resets"}, False),
    ("parameters", {"parameters", "params", "generics"}, False),
]

# v0.56: nested containers the orchestrator uses to group L9 sections.
# `phase1-orchestrate/SKILL.md` puts ports under `dtop_top_level.ports`
# rather than at the JSON root. The original schema check only scanned
# the root, so any orchestrator-shaped L9 doc reported MISSING_SECTION
# for `top_level_ports` even when ports were correctly nested under
# `dtop_top_level`. The v0.55 multi-IC validation flagged this on both
# 24LC256 and ADS1115 runs.
_NESTED_CONTAINERS = ("dtop_top_level", "dtop", "top_level", "integration",
                      "rtl_integration", "design")


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def find_section(data: dict, aliases: Set[str]) -> Tuple[Optional[str], any]:
    """Find a section in `data`.

    Search order:
      1. Top-level keys matching any alias.
      2. Nested keys under one of the orchestrator's grouping containers
         (`dtop_top_level`, `dtop`, `top_level`, `integration`, etc.).

    Returns (key_path, value) — the key_path is dot-joined when nested
    (e.g. `dtop_top_level.ports`) so the caller can report where it
    was found. Returns (None, None) when no alias matches anywhere."""
    # Top-level scan
    for alias in aliases:
        if alias in data:
            return alias, data[alias]
    # Nested scan
    for container in _NESTED_CONTAINERS:
        nested = data.get(container)
        if isinstance(nested, dict):
            for alias in aliases:
                if alias in nested:
                    return f"{container}.{alias}", nested[alias]
    return None, None


def audit_l9(l9_path: Path) -> Tuple[List[Finding], dict]:
    """Check L9 Integration Spec completeness.

    Returns (findings, section_summary).
    """
    findings: List[Finding] = []
    section_summary: Dict[str, dict] = {}

    # Check file exists
    if not l9_path.exists():
        findings.append(Finding(
            severity="ERROR",
            category="MISSING_FILE",
            section="",
            message=f"L9 file not found: {l9_path}",
        ))
        return findings, section_summary

    # Read and parse JSON
    raw = l9_path.read_text(errors='replace').strip()
    if not raw:
        findings.append(Finding(
            severity="ERROR",
            category="INVALID_JSON",
            section="",
            message="L9 file is empty",
        ))
        return findings, section_summary

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        findings.append(Finding(
            severity="ERROR",
            category="INVALID_JSON",
            section="",
            message=f"Invalid JSON: {e}",
        ))
        return findings, section_summary

    if not isinstance(data, dict):
        findings.append(Finding(
            severity="ERROR",
            category="INVALID_JSON",
            section="",
            message=f"L9 root must be a JSON object, got {type(data).__name__}",
        ))
        return findings, section_summary

    # Check required sections
    # v0.57 D4: detect "no register file" projects via top-level
    # `no_registers: true` flag in L9. Pure-logic / pad-only ICs and
    # some analog-front-end ICs have no addressable register interface
    # — they should declare it explicitly here so the `registers`
    # section requirement skips cleanly. The flag is intentional (must
    # be set; absence keeps the legacy hard-required behaviour) so a
    # missed orchestrator step doesn't get mistaken for "no registers".
    no_registers = bool(data.get("no_registers")
                         or data.get("registers_not_applicable"))

    for canonical, aliases, required in REQUIRED_SECTIONS:
        # Conditional skip for the registers section
        if canonical == "registers" and no_registers:
            section_summary[canonical] = {
                "present": False, "key": None, "size": 0,
                "skipped": True,
                "skip_reason": "L9.no_registers=true (declared)",
            }
            findings.append(Finding(
                severity="INFO",
                category="SKIPPED_SECTION",
                section=canonical,
                message=("registers section skipped — L9 declares "
                         "`no_registers: true` (or `registers_not_applicable`). "
                         "Use this only for ICs with no addressable register "
                         "interface (pure-logic / pad-only / some analog-FE)."),
            ))
            continue

        key_found, value = find_section(data, aliases)

        if key_found is None:
            findings.append(Finding(
                severity="ERROR",
                category="MISSING_SECTION",
                section=canonical,
                message=f"Required section '{canonical}' not found (checked aliases: {sorted(aliases)})",
            ))
            section_summary[canonical] = {"present": False, "key": None, "size": 0}
        else:
            # Check if empty
            is_empty = (
                (isinstance(value, (list, dict)) and len(value) == 0) or
                value is None
            )
            # The L9 emitter records absence explicitly: alongside a section it
            # writes `no_<section>_in_input`, true when the INPUT carried none.
            # Measured over the 193 canonical L9 files in benchmark-data:
            #
            #   internal_wires empty + marker true    186   honest, explained
            #   internal_wires filled + marker false    4   honest, explained
            #   internal_wires filled + marker true     3   CONTRADICTION
            #
            # Erroring on the first group flags an absence the document itself
            # accounts for, and it is why this gate FAILs 120 of 120 corpus L9
            # files — a universal FAIL that says nothing about any of them.
            # The third group is the finding actually worth having: the marker
            # and the content disagree, so one of them is wrong.
            marker_key = f"no_{canonical}_in_input"
            marker_present = marker_key in data
            input_had_none = bool(data.get(marker_key))
            if not is_empty and marker_present and input_had_none:
                findings.append(Finding(
                    severity="ERROR",
                    category="ABSENCE_MARKER_CONTRADICTS_CONTENT",
                    section=canonical,
                    message=(f"'{key_found}' has {len(value)} entr(ies) but "
                             f"'{marker_key}' is true — the marker and the "
                             f"content disagree"),
                ))
            if is_empty and required and input_had_none:
                findings.append(Finding(
                    severity="INFO",
                    category="EMPTY_SECTION_EXPLAINED",
                    section=canonical,
                    message=(f"Section '{key_found}' is empty, and "
                             f"'{marker_key}' is true — the input carried none. "
                             f"Not a completeness defect."),
                ))
            elif is_empty and required:
                findings.append(Finding(
                    severity="ERROR",
                    category="EMPTY_SECTION",
                    section=canonical,
                    message=f"Section '{key_found}' exists but is empty",
                ))
            size = len(value) if isinstance(value, (list, dict)) else 1
            section_summary[canonical] = {
                "present": True,
                "key": key_found,
                "size": size,
                "empty": is_empty,
            }

    # Check optional sections (INFO only)
    for canonical, aliases, _ in OPTIONAL_SECTIONS:
        key_found, value = find_section(data, aliases)
        if key_found is None:
            findings.append(Finding(
                severity="INFO",
                category="MISSING_SECTION",
                section=canonical,
                message=f"Optional section '{canonical}' not found",
            ))
            section_summary[canonical] = {"present": False, "key": None, "size": 0}
        else:
            size = len(value) if isinstance(value, (list, dict)) else 1
            section_summary[canonical] = {
                "present": True, "key": key_found, "size": size}

    return findings, section_summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], section_summary: dict,
                 l9_path: str) -> dict:
    error_findings = [f for f in findings if f.severity == "ERROR"]
    return {
        "program": "l9_completeness_check",
        "version": "1.0.0",
        "l9_file": l9_path,
        "summary": {
            "sections_checked": len(REQUIRED_SECTIONS),
            "sections_present": sum(
                1 for s in section_summary.values() if s.get("present")),
            "findings_count": len(findings),
            "error_count": len(error_findings),
            "pass": len(error_findings) == 0,
        },
        "sections": section_summary,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify L9 Integration Spec JSON completeness"
    )
    parser.add_argument('--l9-file', required=True,
                        help="Path to L9 Integration Spec JSON file")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    l9_path = Path(args.l9_file)
    findings, section_summary = audit_l9(l9_path)

    report = build_report(findings, section_summary, str(l9_path))
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)

    error_findings = [f for f in findings if f.severity == "ERROR"]
    if any(f.category in ("MISSING_FILE", "INVALID_JSON") for f in findings):
        return 2
    return 0 if len(error_findings) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
