#!/usr/bin/env python3
"""
assertion_property_check.py — Deterministic compliance check for assertion-gen.

Verifies that SystemVerilog assertion files (.sv/.sva) exist and contain valid
property declarations and assert property statements.

What it catches:
  1. NO_ASSERTION_FILE — no .sv or .sva files containing 'assert' or 'property' found
  2. NO_PROPERTY_DECL — file has no 'property <name>' declaration
  3. NO_ASSERT_PROPERTY — file has no 'assert property' statement
  4. STUB_FILE — file has fewer than 11 non-empty lines (empty/stub)
  5. EMPTY_FILE — file is empty or unreadable

Usage:
    python3 assertion_property_check.py ./my_project
    python3 assertion_property_check.py ./my_project --json

Exit codes:
    0 = at least 1 valid assertion file found
    1 = no valid assertion files found

Generality: works for ANY IC project with SVA assertions.
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
# Regex patterns
# ---------------------------------------------------------------------------
PROPERTY_DECL_RE = re.compile(r'\bproperty\s+\w+', re.MULTILINE)
ASSERT_PROPERTY_RE = re.compile(r'\bassert\s+property\b', re.MULTILINE)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_assertion_files(base: Path) -> List[Path]:
    """Find .sv and .sva files that contain 'assert' or 'property'."""
    candidates: List[Path] = []
    for ext in ("*.sv", "*.sva"):
        for fpath in sorted(base.rglob(ext)):
            try:
                text = fpath.read_text(errors="replace")
            except OSError:
                continue
            # Only include files that actually mention assertions or properties
            if re.search(r'\b(assert|property)\b', text, re.IGNORECASE):
                candidates.append(fpath)
    return candidates


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
            program="assertion_property_check",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "valid_files": 0},
        )

    assertion_files = discover_assertion_files(base)

    if not assertion_files:
        findings.append(Finding(
            rule="NO_ASSERTION_FILE",
            severity="ERROR",
            message="No .sv or .sva files containing 'assert' or 'property' found",
        ))
        return AuditResult(
            program="assertion_property_check",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "valid_files": 0},
        )

    valid_files = 0

    for af in assertion_files:
        rel = str(af.relative_to(base)) if af.is_relative_to(base) else str(af)
        file_errors = 0

        try:
            text = af.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                rule="EMPTY_FILE",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        # Check: not a stub (>10 non-empty lines)
        non_empty_lines = [
            l for l in text.split("\n")
            if l.strip() and not l.strip().startswith("//")
        ]
        if len(non_empty_lines) <= 10:
            findings.append(Finding(
                rule="STUB_FILE",
                severity="ERROR",
                message=f"File has only {len(non_empty_lines)} non-empty lines (stub/incomplete)",
                file=rel,
            ))
            file_errors += 1

        # Check: at least 1 property declaration
        property_matches = PROPERTY_DECL_RE.findall(text)
        if not property_matches:
            findings.append(Finding(
                rule="NO_PROPERTY_DECL",
                severity="ERROR",
                message="No 'property <name>' declaration found",
                file=rel,
            ))
            file_errors += 1
        else:
            findings.append(Finding(
                rule="PROPERTY_COUNT",
                severity="INFO",
                message=f"Found {len(property_matches)} property declaration(s)",
                file=rel,
            ))

        # Check: at least 1 assert property statement
        assert_matches = ASSERT_PROPERTY_RE.findall(text)
        if not assert_matches:
            findings.append(Finding(
                rule="NO_ASSERT_PROPERTY",
                severity="ERROR",
                message="No 'assert property' statement found",
                file=rel,
            ))
            file_errors += 1
        else:
            findings.append(Finding(
                rule="ASSERT_COUNT",
                severity="INFO",
                message=f"Found {len(assert_matches)} 'assert property' statement(s)",
                file=rel,
            ))

        if file_errors == 0:
            valid_files += 1

    # Overall: at least 1 valid assertion file required
    if valid_files == 0:
        findings.append(Finding(
            rule="NO_VALID_FILE",
            severity="ERROR",
            message=f"No valid assertion files found ({len(assertion_files)} checked, none passed all rules)",
        ))

    passed = valid_files > 0
    return AuditResult(
        program="assertion_property_check",
        passed=passed,
        findings=findings,
        summary={
            "files_checked": len(assertion_files),
            "valid_files": valid_files,
            "errors": sum(1 for f in findings if f.severity == "ERROR"),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for assertion-gen"
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
