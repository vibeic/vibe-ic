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
    python3 assertion_property_check.py ./my_project --json            # stdout
    python3 assertion_property_check.py . --json reports/…/assert.json # file

Exit codes:
    0 = at least 1 valid assertion file found
    1 = assertion candidates EXIST but none is valid (the real defect)
    2 = INPUT NOT APPLICABLE — the project contains no .sv/.sva file that
        mentions `assert`/`property` at all, so there is nothing for this
        gate to audit. This is the flow-wide "input-missing skip"
        convention (`_check_program_exit_zero` in flow_compliance_check.py
        maps rc==2 → VACUOUS_PASS), and it is what keeps the #608 honest
        SKIPPED-CONDITION for a project with no formal/assertion harness
        from turning into a FAIL now that this gate is WIRED into step 5.

        NOTE the split: rc=2 is reserved for "no candidate exists". The
        moment a candidate file exists, a missing `property` declaration or
        a missing `assert property` statement is a DEFECT (rc=1), never an
        inapplicable input.

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
    # True  → the gate had real input to audit (assertion candidates exist).
    # False → NOTHING to audit; `passed` stays False (the audit did not
    #         succeed) but main() reports the flow-wide rc=2 "input not
    #         applicable" convention instead of rc=1 "defect found".
    # Kept as a SEPARATE field rather than folding it into `passed` so the
    # library-level contract (`audit().passed`) is unchanged for existing
    # callers/tests: no assertion file is still not a pass.
    applicable: bool = True


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
            # A missing project directory is a REAL error, not an
            # inapplicable input — keep it on the rc=1 path.
            applicable=True,
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
            # Nothing to audit anywhere in the tree → rc=2 (input not
            # applicable), the convention flow_compliance_check maps to
            # VACUOUS_PASS. Without this split, wiring the gate into step 5
            # would convert every project that legitimately has no formal /
            # assertion harness (the #608 SKIPPED-CONDITION case) into a
            # hard FAIL.
            applicable=False,
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

        # Check: not a stub.
        #
        # This used to be `len(non_empty_lines) <= 10` and nothing else. For a
        # GENERATED assertions file the line count is a function of the design:
        # professional_tb_gen emitted 2 lines per output port, so
        # non_empty_lines = 2 + n_outputs, and any design with fewer than 9
        # outputs was failed as a "stub/incomplete" file. It was reporting a
        # property of the DESIGN (how many outputs it has) as a property of the
        # FILE (whether anyone bothered to write it). A 5-output design got
        # STUB_FILE for being a 5-output design.
        #
        # So ask the actual question. An assertions file is a stub when it does
        # not ASSERT anything; that is what "stub" means here, and this program
        # already counts assertions two checks below. Line count survives only
        # as the fallback for the case it can still speak to — a file with no
        # assertions at all, where there is nothing better to measure.
        #
        # This is NOT a relaxation: a file with zero assertions still fails, and
        # it now fails at any length instead of only under 11 lines.
        non_empty_lines = [
            l for l in text.split("\n")
            if l.strip() and not l.strip().startswith("//")
        ]
        n_assertions = len(ASSERT_PROPERTY_RE.findall(text))
        if n_assertions == 0:
            findings.append(Finding(
                rule="STUB_FILE",
                severity="ERROR",
                message=(f"File asserts nothing: 0 'assert property' statements "
                         f"in {len(non_empty_lines)} non-empty lines "
                         f"(stub/incomplete)"),
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
    # `--json` alone keeps the historical stdout behaviour; `--json <path>`
    # writes the report to that path, which is what every WIRED gate in
    # flow/phase1_phase2_phase3.yaml does (the gate needs a dereferenceable
    # evidence artefact, not a stdout blob).
    p.add_argument("--json", nargs="?", const="-", default=None,
                   metavar="PATH",
                   help="Write the JSON report to PATH "
                        "(bare --json = stdout, as before)")
    args = p.parse_args()

    result = audit(args.project_dir)
    payload = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json == "-":
        print(payload)
    elif args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = Path(args.project_dir) / out
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, payload, encoding="utf-8")

    if args.json != "-":
        for f in result.findings:
            tag = f"[{f.file}] " if f.file else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        if not result.applicable:
            status = "SKIP"
        else:
            status = "PASS" if result.passed else "FAIL"
        print(f"\n{status} — {result.summary}")

    if result.passed:
        sys.exit(0)
    # rc=2 == "input not applicable" (nothing to audit); rc=1 == real defect.
    sys.exit(1 if result.applicable else 2)


if __name__ == "__main__":
    main()
