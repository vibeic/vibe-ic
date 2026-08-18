#!/usr/bin/env python3
"""
synth-doctor — Yosys Synthesis Error Auto-Classifier + Fix Suggester
====================================================================
Parses Yosys synthesis logs, classifies errors into known patterns,
and outputs actionable fix suggestions.

Usage:
    python3 synth_doctor.py <synth.log>
    python3 synth_doctor.py <synth.log> --json  # machine-readable output
    python3 synth_doctor.py <synth.log> --fix   # output fix commands

Known patterns (from 135-IC campaign):
    1. UNPACKED_ARRAY   — Yosys doesn't support unpacked array ports
    2. MULTI_DRIVER      — Multiple always_ff blocks driving same register
    3. RETURN_IN_FUNC    — 'return' keyword in function body
    4. PAST_IN_COMB      — $past() used in always_comb
    5. AUTOMATIC_IN_FF   — 'automatic' keyword in always_ff
    6. LATCH_INFERENCE    — Incomplete case/if in always_comb
    7. SYNTAX_ERROR       — General syntax error (parse failure)
    8. MODULE_NOT_FOUND   — Missing module instantiation
    9. WIDTH_MISMATCH     — Signal width mismatch warning
   10. UNKNOWN            — Unclassified error
"""

import re
import sys
import json
import argparse
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from pathlib import Path


@dataclass
class Diagnosis:
    pattern: str
    severity: str  # ERROR, WARNING, INFO
    line_num: Optional[int]
    file_name: Optional[str]
    message: str
    root_cause: str
    fix_suggestion: str
    fix_command: Optional[str]  # actual code/command to fix
    raw_line: str


@dataclass
class SynthReport:
    log_file: str
    status: str  # PASS, FAIL, WARN
    cell_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    diagnoses: List[Diagnosis] = field(default_factory=list)
    summary: str = ""


# ============================================================================
# Pattern Matchers
# ============================================================================

PATTERNS = [
    {
        'name': 'UNPACKED_ARRAY',
        'regex': r'(?:syntax error|unsupported).*(?:unpacked|array\s+port)',
        'alt_regex': r'ERROR:.*\[.*\[',
        'severity': 'ERROR',
        'root_cause': 'Yosys does not support unpacked array ports (e.g., logic [7:0] data [0:3])',
        'fix_suggestion': 'Flatten unpacked array to packed vector: logic [31:0] data_flat',
        'fix_command': '// Before: logic [7:0] data_in [0:3]\n// After:  logic [31:0] data_in_flat\n// Inside: wire [7:0] data_in_0 = data_in_flat[7:0]; ...',
    },
    {
        'name': 'MULTI_DRIVER',
        'regex': r'(?:Warning|ERROR).*(?:multi.?driven|multiple.*driver|driven.*multiple)',
        'alt_regex': r'Warning.*Resolvable.*net',
        'severity': 'WARNING',
        'root_cause': 'A register is driven by more than one always_ff block',
        'fix_suggestion': 'Merge all drivers into a single always_ff with priority mux',
        'fix_command': '// Before: two always_ff both assign cfg_reg\n// After: single always_ff with:\n//   if (subsys_a_update) cfg_reg <= subsys_a_value;\n//   else if (subsys_b_update) cfg_reg <= subsys_b_value;',
    },
    {
        'name': 'RETURN_IN_FUNC',
        'regex': r'(?:syntax error|unexpected).*return',
        'severity': 'ERROR',
        'root_cause': 'Yosys does not support "return" keyword in function bodies',
        'fix_suggestion': 'Replace "return value;" with function name assignment',
        'fix_command': '// Before: function logic [7:0] calc; ... return result; endfunction\n// After:  function logic [7:0] calc; ... calc = result; endfunction',
    },
    {
        'name': 'PAST_IN_COMB',
        'regex': r'\$past.*always_comb|always_comb.*\$past',
        'severity': 'ERROR',
        'root_cause': '$past() is not supported in combinational always blocks by Yosys',
        'fix_suggestion': 'Use a shadow register: reg prev_val; always_ff prev_val <= current_val;',
        'fix_command': '// Before: always_comb if ($past(sig)) ...\n// After:  logic sig_prev;\n//         always_ff @(posedge clk) sig_prev <= sig;\n//         always_comb if (sig_prev) ...',
    },
    {
        'name': 'AUTOMATIC_IN_FF',
        'regex': r'automatic.*always_ff|always_ff.*automatic',
        'severity': 'ERROR',
        'root_cause': '"automatic" variables inside always_ff are not supported by Yosys',
        'fix_suggestion': 'Move variable declarations to module level as regular wires/regs',
        'fix_command': '// Before: always_ff begin automatic logic tmp; ...\n// After:  logic tmp; // module level\n//         always_ff begin tmp <= ...',
    },
    {
        'name': 'LATCH_INFERENCE',
        'regex': r'(?:latch|Warning.*inferred.*latch|incomplete.*case|incomplete.*if)',
        'severity': 'WARNING',
        'root_cause': 'Incomplete case/if statements in always_comb cause latch inference',
        'fix_suggestion': 'Add default assignments at the top of always_comb for ALL signals',
        'fix_command': '// Before: always_comb case(sel) 2\'b00: out = a; 2\'b01: out = b; endcase\n// After:  always_comb begin out = 0; case(sel) ... endcase end',
    },
    {
        'name': 'SYNTAX_ERROR',
        'regex': r'ERROR:.*syntax error|unexpected.*token|expected.*got',
        'severity': 'ERROR',
        'root_cause': 'SystemVerilog syntax not recognized by Yosys parser',
        'fix_suggestion': 'Check for Yosys-unsupported SV constructs (interfaces, classes, etc.)',
        'fix_command': None,
    },
    {
        'name': 'MODULE_NOT_FOUND',
        'regex': r'ERROR:.*Module.*not found|ERROR:.*Unknown module|can.*find.*module',
        'severity': 'ERROR',
        'root_cause': 'A module instantiation references a module not in the source files',
        'fix_suggestion': 'Add missing source file to Yosys read_verilog command',
        'fix_command': '// Add: read_verilog -sv missing_module.sv',
    },
    {
        'name': 'WIDTH_MISMATCH',
        'regex': r'Warning.*width.*mismatch|Warning.*truncated|Warning.*extended',
        'severity': 'WARNING',
        'root_cause': 'Signal widths don\'t match in assignment or port connection',
        'fix_suggestion': 'Explicitly size constants and check port widths',
        'fix_command': '// Before: logic [5:0] x = 64;  // 64 needs 7 bits\n// After:  logic [6:0] x = 7\'d64;',
    },
]


def analyze_log(log_path: str) -> SynthReport:
    """Parse synthesis log and generate diagnosis report."""
    report = SynthReport(log_file=log_path, status='UNKNOWN')

    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        report.status = 'FAIL'
        report.summary = f'Log file not found: {log_path}'
        return report

    error_lines = []
    warning_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Count errors and warnings
        if 'ERROR' in stripped or 'Error' in stripped:
            error_lines.append((i + 1, stripped))
        if 'Warning' in stripped or 'WARNING' in stripped:
            warning_lines.append((i + 1, stripped))

        # Extract cell count
        m = re.search(r'Number of cells:\s*(\d+)', stripped)
        if m:
            report.cell_count = int(m.group(1))

        # Also check alternate format
        m = re.search(r'^\s+(\d+)\s+cells\s*$', stripped)
        if m:
            report.cell_count = int(m.group(1))

    report.error_count = len(error_lines)
    report.warning_count = len(warning_lines)

    # Classify each error/warning
    all_issues = error_lines + warning_lines
    classified = set()

    for line_num, line_text in all_issues:
        matched = False
        for pat in PATTERNS:
            if re.search(pat['regex'], line_text, re.IGNORECASE):
                if pat['name'] not in classified or pat['severity'] == 'ERROR':
                    # Extract file:line if present
                    file_match = re.search(r'(\S+\.sv?):(\d+)', line_text)
                    fname = file_match.group(1) if file_match else None
                    fline = int(file_match.group(2)) if file_match else line_num

                    report.diagnoses.append(Diagnosis(
                        pattern=pat['name'],
                        severity=pat['severity'],
                        line_num=fline,
                        file_name=fname,
                        message=line_text,
                        root_cause=pat['root_cause'],
                        fix_suggestion=pat['fix_suggestion'],
                        fix_command=pat.get('fix_command'),
                        raw_line=line_text,
                    ))
                    classified.add(pat['name'])
                matched = True
                break

        if not matched and 'ERROR' in line_text:
            report.diagnoses.append(Diagnosis(
                pattern='UNKNOWN',
                severity='ERROR',
                line_num=line_num,
                file_name=None,
                message=line_text,
                root_cause='Unclassified error — manual review needed',
                fix_suggestion='Read the full error message and check Yosys documentation',
                fix_command=None,
                raw_line=line_text,
            ))

    # Determine status
    if report.error_count > 0:
        report.status = 'FAIL'
    elif report.warning_count > 0:
        report.status = 'WARN'
    else:
        report.status = 'PASS'

    # Summary
    diag_summary = ", ".join(set(d.pattern for d in report.diagnoses))
    report.summary = (
        f"{'PASS' if report.status == 'PASS' else report.status}: "
        f"{report.cell_count} cells, {report.error_count} errors, "
        f"{report.warning_count} warnings"
        + (f" [{diag_summary}]" if diag_summary else "")
    )

    return report


def print_report(report: SynthReport, show_fix=False):
    """Pretty-print diagnosis report."""
    status_icon = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}.get(report.status, '?')

    print(f"\n{'='*60}")
    print(f"  synth-doctor — Synthesis Diagnosis Report")
    print(f"{'='*60}")
    print(f"  Log:      {report.log_file}")
    print(f"  Status:   {status_icon} {report.status}")
    print(f"  Cells:    {report.cell_count}")
    print(f"  Errors:   {report.error_count}")
    print(f"  Warnings: {report.warning_count}")

    if report.diagnoses:
        print(f"\n  {'─'*56}")
        print(f"  Diagnoses ({len(report.diagnoses)}):\n")

        for i, d in enumerate(report.diagnoses):
            icon = '❌' if d.severity == 'ERROR' else '⚠️'
            print(f"  {icon} [{d.pattern}] {d.severity}")
            if d.file_name:
                print(f"     File: {d.file_name}:{d.line_num}")
            print(f"     Cause: {d.root_cause}")
            print(f"     Fix:   {d.fix_suggestion}")
            if show_fix and d.fix_command:
                print(f"     Code:")
                for cl in d.fix_command.split('\n'):
                    print(f"       {cl}")
            print()

    if report.status == 'PASS':
        print(f"\n  ✅ No issues found. Synthesis successful.")
    print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='synth-doctor: Yosys error classifier')
    parser.add_argument('log_file', help='Path to synth.log')
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--fix', action='store_true', help='Show fix code snippets')
    args = parser.parse_args()

    report = analyze_log(args.log_file)

    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print_report(report, show_fix=args.fix)

    sys.exit(0 if report.status == 'PASS' else 1)


if __name__ == '__main__':
    main()
