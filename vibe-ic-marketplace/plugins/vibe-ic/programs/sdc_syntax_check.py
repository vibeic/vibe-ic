#!/usr/bin/env python3
"""
sdc_syntax_check.py — Deterministic compliance check for constraint-gen.

Verifies that SDC (Synopsys Design Constraints) files exist and contain valid
clock definitions, timing constraints, and no obvious syntax errors.

What it catches:
  1. NO_SDC_FILE — no .sdc files found in project directory
  2. NO_CREATE_CLOCK — SDC file has no create_clock command
  3. NO_TIMING_CONSTRAINT — no set_input_delay, set_output_delay, set_max_delay,
     set_false_path, or set_multicycle_path found
  4. BAD_CLOCK_PERIOD — clock period is outside reasonable range (0.1ns to 10000ns)
  5. SYNTAX_ERROR — unmatched brackets or missing -period value
  6. EMPTY_FILE — SDC file is empty or has no meaningful content

Usage:
    python3 sdc_syntax_check.py ./my_project
    python3 sdc_syntax_check.py ./my_project --json

Exit codes:
    0 = valid SDC file(s) found
    1 = no valid SDC found

Generality: works for ANY IC project with SDC constraint files.
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
from typing import List, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


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
CREATE_CLOCK_RE = re.compile(
    r'\bcreate_clock\b', re.MULTILINE
)
CLOCK_PERIOD_RE = re.compile(
    r'\bcreate_clock\b[^;\n]*-period\s+(\S+)', re.MULTILINE
)
TIMING_COMMANDS = [
    "set_input_delay",
    "set_output_delay",
    "set_max_delay",
    "set_false_path",
    "set_multicycle_path",
]
TIMING_RE = re.compile(
    r'\b(' + '|'.join(TIMING_COMMANDS) + r')\b', re.MULTILINE
)

# Reasonable clock period bounds (nanoseconds)
MIN_PERIOD_NS = 0.1
MAX_PERIOD_NS = 10000.0


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_sdc_files(base: Path) -> List[Path]:
    """Find .sdc files in project directory recursively."""
    return sorted(base.rglob("*.sdc"))


# ---------------------------------------------------------------------------
# Bracket checking
# ---------------------------------------------------------------------------
def check_brackets(text: str) -> List[Tuple[int, str]]:
    """Check for unmatched brackets in SDC text.

    Returns list of (line_number, description) for issues found.
    """
    issues: List[Tuple[int, str]] = []
    stack: List[Tuple[str, int]] = []  # (bracket_char, line_number)
    pairs = {')': '(', ']': '[', '}': '{'}

    for lineno, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue
        for ch in stripped:
            if ch in ('(', '[', '{'):
                stack.append((ch, lineno))
            elif ch in (')', ']', '}'):
                if not stack:
                    issues.append((lineno, f"Unmatched closing '{ch}'"))
                elif stack[-1][0] != pairs[ch]:
                    issues.append((lineno, f"Mismatched bracket: expected closing for '{stack[-1][0]}' but got '{ch}'"))
                    stack.pop()
                else:
                    stack.pop()

    for bracket, lineno in stack:
        issues.append((lineno, f"Unmatched opening '{bracket}'"))

    return issues


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
            program="sdc_syntax_check",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "valid_files": 0},
        )

    sdc_files = discover_sdc_files(base)

    if not sdc_files:
        findings.append(Finding(
            rule="NO_SDC_FILE",
            severity="ERROR",
            message="No .sdc files found in project directory",
        ))
        return AuditResult(
            program="sdc_syntax_check",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "valid_files": 0},
        )

    valid_files = 0

    for sf in sdc_files:
        rel = str(sf.relative_to(base)) if sf.is_relative_to(base) else str(sf)
        file_errors = 0

        try:
            text = sf.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                rule="READ_ERROR",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        # Check: not empty
        content_lines = [
            l for l in text.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        if len(content_lines) == 0:
            findings.append(Finding(
                rule="EMPTY_FILE",
                severity="ERROR",
                message="SDC file is empty or contains only comments",
                file=rel,
            ))
            file_errors += 1
            continue

        # Check: create_clock command exists
        if not CREATE_CLOCK_RE.search(text):
            findings.append(Finding(
                rule="NO_CREATE_CLOCK",
                severity="ERROR",
                message="No 'create_clock' command found",
                file=rel,
            ))
            file_errors += 1
        else:
            # Validate clock period values
            for m in CLOCK_PERIOD_RE.finditer(text):
                period_str = m.group(1)
                try:
                    period = float(period_str)
                    if period < MIN_PERIOD_NS or period > MAX_PERIOD_NS:
                        findings.append(Finding(
                            rule="BAD_CLOCK_PERIOD",
                            severity="ERROR",
                            message=f"Clock period {period}ns is outside reasonable range "
                                    f"({MIN_PERIOD_NS}ns - {MAX_PERIOD_NS}ns)",
                            file=rel,
                        ))
                        file_errors += 1
                    else:
                        freq_mhz = 1000.0 / period
                        findings.append(Finding(
                            rule="CLOCK_PERIOD_OK",
                            severity="INFO",
                            message=f"Clock period {period}ns ({freq_mhz:.1f} MHz)",
                            file=rel,
                        ))
                except ValueError:
                    # Period might be a variable/expression — not necessarily an error
                    findings.append(Finding(
                        rule="CLOCK_PERIOD_EXPR",
                        severity="WARNING",
                        message=f"Clock period is an expression '{period_str}', cannot validate statically",
                        file=rel,
                    ))

            # Check for create_clock without -period
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "create_clock" in stripped and "-period" not in stripped:
                    # create_clock without -period is invalid
                    findings.append(Finding(
                        rule="SYNTAX_ERROR",
                        severity="ERROR",
                        message="'create_clock' without '-period' flag",
                        file=rel,
                    ))
                    file_errors += 1

        # Check: at least 1 timing constraint
        timing_matches = TIMING_RE.findall(text)
        if not timing_matches:
            findings.append(Finding(
                rule="NO_TIMING_CONSTRAINT",
                severity="ERROR",
                message="No timing constraints found (set_input_delay, set_output_delay, "
                        "set_max_delay, set_false_path, set_multicycle_path)",
                file=rel,
            ))
            file_errors += 1
        else:
            unique_commands = set(timing_matches)
            findings.append(Finding(
                rule="TIMING_FOUND",
                severity="INFO",
                message=f"Found {len(timing_matches)} timing constraint(s): {sorted(unique_commands)}",
                file=rel,
            ))

        # Check: bracket matching
        bracket_issues = check_brackets(text)
        for lineno, desc in bracket_issues:
            findings.append(Finding(
                rule="SYNTAX_ERROR",
                severity="ERROR",
                message=f"Line {lineno}: {desc}",
                file=rel,
            ))
            file_errors += 1

        if file_errors == 0:
            valid_files += 1

    passed = valid_files > 0
    return AuditResult(
        program="sdc_syntax_check",
        passed=passed,
        findings=findings,
        summary={
            "files_checked": len(sdc_files),
            "valid_files": valid_files,
            "errors": sum(1 for f in findings if f.severity == "ERROR"),
            "clocks_found": sum(1 for f in findings if f.rule == "CLOCK_PERIOD_OK"),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for constraint-gen"
    )
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", nargs="?", const="-", default=None,
                   help="Emit JSON. With no value → stdout. With a path → write file.")
    args = p.parse_args()

    result = audit(args.project_dir)

    if args.json is not None:
        payload = json.dumps(asdict(result), indent=2, ensure_ascii=False)
        if args.json == "-":
            print(payload)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(_P(args.json), payload)
    else:
        for f in result.findings:
            tag = f"[{f.file}] " if f.file else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{status} — {result.summary}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
