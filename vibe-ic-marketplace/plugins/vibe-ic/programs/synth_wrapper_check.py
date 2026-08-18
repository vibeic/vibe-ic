#!/usr/bin/env python3
"""
synth_wrapper_check.py — Deterministic compliance check for synth-wrapper-gen.

Verifies that synthesis wrapper files exist and contain valid module declarations,
DUT instantiations, and proper bidirectional port handling.

What it catches:
  1. NO_WRAPPER — no .v or .sv files matching *wrapper* found
  2. NO_MODULE_DECL — wrapper file has no 'module' declaration
  3. NO_DUT_INST — wrapper file has no module instantiation (no DUT being wrapped)
  4. STUB_FILE — wrapper has fewer than 5 lines of actual code
  5. NO_INOUT_DESIGN — no wrapper files found, but also no inout ports in design (INFO)

Usage:
    python3 synth_wrapper_check.py ./my_project
    python3 synth_wrapper_check.py ./my_project --json

Exit codes:
    0 = valid wrapper found, or no wrapper needed (no inout ports)
    1 = wrapper expected but missing or invalid

Generality: works for ANY IC project with synthesis wrappers.
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
MODULE_DECL_RE = re.compile(r'\bmodule\s+\w+', re.MULTILINE)
# Module instantiation: ModuleName [#(params)] instance_name (
INST_RE = re.compile(
    r'^\s*(\w+)\s+(?:#\s*\([^)]*\)\s*)?(\w+)\s*\(',
    re.MULTILINE,
)
INOUT_RE = re.compile(r'\binout\b', re.MULTILINE)

# Verilog keywords — cannot be module instantiation targets
VERILOG_KEYWORDS = {
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
    'logic', 'assign', 'always', 'always_ff', 'always_comb', 'always_latch',
    'initial', 'begin', 'end', 'if', 'else', 'case', 'endcase', 'for',
    'while', 'parameter', 'localparam', 'generate', 'endgenerate', 'genvar',
    'function', 'endfunction', 'task', 'endtask', 'integer', 'real',
    'typedef', 'struct', 'enum', 'packed', 'signed', 'unsigned',
    'supply0', 'supply1', 'tri', 'wand', 'wor',
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_wrapper_files(base: Path) -> List[Path]:
    """Find .v or .sv files with 'wrapper' in the name."""
    found: List[Path] = []
    for ext in ("*.v", "*.sv"):
        for fpath in sorted(base.rglob(ext)):
            if "wrapper" in fpath.name.lower():
                found.append(fpath)
    return found


def design_has_inout(base: Path) -> bool:
    """Check if any .v or .sv file in the project uses 'inout' ports."""
    for ext in ("*.v", "*.sv"):
        for fpath in base.rglob(ext):
            if "wrapper" in fpath.name.lower():
                continue  # skip wrapper files themselves
            try:
                text = fpath.read_text(errors="replace")
                if INOUT_RE.search(text):
                    return True
            except OSError:
                continue
    return False


def count_instantiations(text: str) -> int:
    """Count module instantiations in Verilog text, excluding keywords."""
    count = 0
    for m in INST_RE.finditer(text):
        mod_name = m.group(1)
        inst_name = m.group(2)
        if mod_name.lower() not in VERILOG_KEYWORDS and inst_name.lower() not in VERILOG_KEYWORDS:
            count += 1
    return count


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
            program="synth_wrapper_check",
            passed=False,
            findings=findings,
            summary={"wrappers_checked": 0, "valid_wrappers": 0},
        )

    wrapper_files = discover_wrapper_files(base)

    if not wrapper_files:
        # Check if design even needs a wrapper (has inout ports)
        has_inout = design_has_inout(base)
        if not has_inout:
            findings.append(Finding(
                rule="NO_INOUT_DESIGN",
                severity="INFO",
                message="No wrapper files found, but design has no inout ports — wrapper may not be needed",
            ))
            return AuditResult(
                program="synth_wrapper_check",
                passed=True,
                findings=findings,
                summary={"wrappers_checked": 0, "valid_wrappers": 0,
                          "wrapper_needed": False},
            )
        else:
            findings.append(Finding(
                rule="NO_WRAPPER",
                severity="ERROR",
                message="No *wrapper*.v or *wrapper*.sv files found, but design has inout ports",
            ))
            return AuditResult(
                program="synth_wrapper_check",
                passed=False,
                findings=findings,
                summary={"wrappers_checked": 0, "valid_wrappers": 0,
                          "wrapper_needed": True},
            )

    valid_wrappers = 0

    for wf in wrapper_files:
        rel = str(wf.relative_to(base)) if wf.is_relative_to(base) else str(wf)
        file_errors = 0

        try:
            text = wf.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                rule="READ_ERROR",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        # Check: not a stub (<5 non-comment, non-empty lines)
        code_lines = [
            l for l in text.split("\n")
            if l.strip() and not l.strip().startswith("//")
        ]
        if len(code_lines) < 5:
            findings.append(Finding(
                rule="STUB_FILE",
                severity="ERROR",
                message=f"Wrapper has only {len(code_lines)} lines of code (stub)",
                file=rel,
            ))
            file_errors += 1

        # Check: contains module declaration
        modules = MODULE_DECL_RE.findall(text)
        if not modules:
            findings.append(Finding(
                rule="NO_MODULE_DECL",
                severity="ERROR",
                message="No 'module' declaration found in wrapper",
                file=rel,
            ))
            file_errors += 1
        else:
            findings.append(Finding(
                rule="MODULE_FOUND",
                severity="INFO",
                message=f"Found {len(modules)} module declaration(s)",
                file=rel,
            ))

        # Check: contains at least 1 module instantiation (DUT)
        inst_count = count_instantiations(text)
        if inst_count == 0:
            findings.append(Finding(
                rule="NO_DUT_INST",
                severity="ERROR",
                message="No module instantiation found (no DUT being wrapped)",
                file=rel,
            ))
            file_errors += 1
        else:
            findings.append(Finding(
                rule="DUT_INST_FOUND",
                severity="INFO",
                message=f"Found {inst_count} module instantiation(s)",
                file=rel,
            ))

        # Check: inout / bidirectional handling
        has_inout_handling = bool(INOUT_RE.search(text))
        if has_inout_handling:
            findings.append(Finding(
                rule="INOUT_HANDLED",
                severity="INFO",
                message="Wrapper handles inout/bidirectional ports",
                file=rel,
            ))
        else:
            findings.append(Finding(
                rule="NO_INOUT_HANDLING",
                severity="WARNING",
                message="Wrapper does not contain any inout port declarations",
                file=rel,
            ))

        if file_errors == 0:
            valid_wrappers += 1

    passed = valid_wrappers > 0
    return AuditResult(
        program="synth_wrapper_check",
        passed=passed,
        findings=findings,
        summary={
            "wrappers_checked": len(wrapper_files),
            "valid_wrappers": valid_wrappers,
            "errors": sum(1 for f in findings if f.severity == "ERROR"),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for synth-wrapper-gen"
    )
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true",
                   help="Output JSON report to stdout")
    args = p.parse_args(argv)

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
