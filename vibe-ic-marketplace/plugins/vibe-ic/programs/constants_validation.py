#!/usr/bin/env python3
"""
constants_validation.py — Deterministic compliance check for rtl-constants-gen.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
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
#: The two entry SHAPES this file can hold, and the key each is spelled with.
#: They are not the same object and must not be judged by the same schema: a
#: CONSTANT is a fixed value the RTL bakes in, so it has a `value` and a width;
#: a PARAMETER is an override point, so its value lives in `default` and it is
#: routinely unsized -- a Verilog `parameter` needs no width and most carry
#: none. Collapsing the two is what made this gate demand `value`/`width` of
#: every parameter the L8 emitter writes, which is a shape no emitter produces.
KIND_CONSTANTS = "constants"
KIND_PARAMETERS = "parameters"

_CONSTANT_KEYS = ("constants", "rtl_constants")
_PARAMETER_KEYS = ("params", "parameters")


def extract_constants(data) -> list:
    """The entry list alone, for callers that do not care which shape it is.

    Kept so the module's published surface does not change. New code should
    call `extract_entries`, which also says WHICH of the two shapes it read.
    """
    return extract_entries(data)[0]


def extract_entries(data) -> "tuple":
    """(entries, kind) for a parsed constants JSON.

    `kind` is what the entries were spelled as, so the caller can require the
    fields that shape actually carries instead of one schema for both. An
    unkeyed list -- a bare top-level list, or the first-list fallback -- is
    reported as KIND_CONSTANTS, which is the behaviour this program already
    had for it and the stricter of the two; widening it would lose findings.
    """
    if isinstance(data, list):
        return data, KIND_CONSTANTS
    if isinstance(data, dict):
        # Prefer an explicit constants key, then an explicit parameters key.
        for key in _CONSTANT_KEYS:
            if key in data and isinstance(data[key], list):
                return data[key], KIND_CONSTANTS
        for key in _PARAMETER_KEYS:
            if key in data and isinstance(data[key], list):
                return data[key], KIND_PARAMETERS
        # Fall back: find the first list value
        for v in data.values():
            if isinstance(v, list) and len(v) > 0:
                return v, KIND_CONSTANTS
    return [], KIND_CONSTANTS


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

        constants, kind = extract_entries(data)

        if len(constants) == 0:
            findings.append(Finding(
                rule="EMPTY_CONSTANTS",
                severity="ERROR",
                message="File contains zero constant entries",
                file=rel,
            ))
            continue

        for idx, entry in enumerate(constants):
            # Name the shape that was actually read. A message that says
            # `constants[0]` about a parameter misnames the object it refuses.
            prefix = f"{kind}[{idx}]"

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

            # Check the entry's VALUE field, under the name its shape uses.
            # A parameter's value is its `default`; `value` is still accepted
            # for an emitter that spells it that way, so this only ever widens
            # what satisfies the check -- an entry carrying neither is still
            # a finding, and that is the defect this rule exists to catch.
            if kind == KIND_PARAMETERS:
                value_keys = ("default", "value")
            else:
                value_keys = ("value",)
            if not any(k in entry and entry[k] is not None for k in value_keys):
                spelled = "' or '".join(value_keys)
                findings.append(Finding(
                    rule="MISSING_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: missing or null '{spelled}'",
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

            # Check 'width' or 'bits'. REQUIRED of a constant, which is a
            # literal the RTL bakes in at a definite width; NOT required of a
            # parameter, which is an override point and is routinely unsized
            # (`parameter memsize = 1024;` is legal and carries no width). A
            # width that IS stated is validated either way -- declaring one
            # and declaring it wrong is a finding whatever the shape.
            width = entry.get("width", entry.get("bits"))
            if width is None:
                if kind != KIND_PARAMETERS:
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
