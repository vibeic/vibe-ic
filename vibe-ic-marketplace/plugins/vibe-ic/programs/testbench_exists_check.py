#!/usr/bin/env python3
"""
testbench_exists_check.py — Deterministic testbench existence and coverage checker.

Verifies that a Verilog/SystemVerilog testbench file exists in the RTL directory
and contains a minimum number of test cases. This catches the common failure
where an agent claims to have generated a testbench but either didn't create one,
or created an empty stub.

What it catches:
  1. NO_TESTBENCH — no *_tb.v, tb_*.v, *_tb.sv, or tb_*.sv files found
  2. INSUFFICIENT_TESTS — testbench has fewer test cases than required minimum
  3. EMPTY_TESTBENCH — testbench file exists but has no meaningful content
  4. STRUCTURAL_ISSUE — testbench lacks initial/always blocks or timing delays
  5. CLOCK_RESET_MISSING — no clock generation or reset handling patterns (WARNING)
  6. STIMULUS_METHOD_MISSING — no recognizable stimulus method (WARNING)
  7. CHECKING_MISSING — no self-checking mechanism (WARNING)

Usage:
    python3 testbench_exists_check.py --rtl-dir ./rtl/ [--min-tests 10]

Exit codes:
    0 = testbench with sufficient tests found
    1 = missing testbench or insufficient test coverage
    2 = parse error / invalid arguments

Generality: works for ANY Verilog/SystemVerilog testbench.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # NO_TESTBENCH, INSUFFICIENT_TESTS, EMPTY_TESTBENCH
    message: str
    file: str = ""
    details: str = ""


@dataclass
class TestbenchInfo:
    file: str
    test_count: int
    test_patterns: List[str]


# ---------------------------------------------------------------------------
# Test case detection patterns
# ---------------------------------------------------------------------------
# Each pattern represents a common testbench test case indicator.
# We count unique lines matching any of these patterns.
TEST_PATTERNS = [
    # $display with PASS/FAIL/TEST/ERROR markers
    re.compile(r'\$display\s*\(\s*".*(?:PASS|FAIL|TEST|ERROR|CASE|CHECK)', re.IGNORECASE),
    # $display with test numbering like "Test 1:", "Test #2"
    re.compile(r'\$display\s*\(\s*".*(?:Test\s*#?\d|test\s*#?\d)', re.IGNORECASE),
    # assert statements (SystemVerilog)
    re.compile(r'\bassert\s*\(', re.IGNORECASE),
    # if-check patterns with $error or $fatal
    re.compile(r'\$(?:error|fatal)\s*\('),
    # Explicit test labels in comments or strings: // TEST 1, // Test Case 2
    re.compile(r'//\s*(?:TEST|Test)\s*(?:Case\s*)?\d'),
    # $write with PASS/FAIL
    re.compile(r'\$write\s*\(\s*".*(?:PASS|FAIL)', re.IGNORECASE),
    # Stimulus blocks marked with task calls like run_test, test_
    re.compile(r'\b(?:run_test|test_\w+)\s*(?:\(|;)'),
]


def count_test_cases(text: str) -> Tuple[int, List[str]]:
    """Count unique test case indicators in testbench text.

    Returns (count, list_of_matched_lines).
    """
    matched_lines: List[str] = []
    seen_line_nums: Set[int] = set()
    lines = text.split('\n')

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('//') and not any(
            p.search(stripped) for p in TEST_PATTERNS
        ):
            continue
        for pattern in TEST_PATTERNS:
            if pattern.search(stripped):
                if i not in seen_line_nums:
                    seen_line_nums.add(i)
                    matched_lines.append(f"L{i}: {stripped[:120]}")
                break  # count each line only once

    return len(matched_lines), matched_lines


# ---------------------------------------------------------------------------
# Testbench file discovery
# ---------------------------------------------------------------------------
TB_PATTERNS = ['*_tb.v', 'tb_*.v', '*_tb.sv', 'tb_*.sv',
               '*_tb.sv', '*_testbench.v', '*_testbench.sv']


def find_testbenches(rtl_dir: Path) -> List[Path]:
    """Find all testbench files in the RTL directory (recursive)."""
    tb_files = []
    for pattern in TB_PATTERNS:
        tb_files.extend(rtl_dir.rglob(pattern))
    # Deduplicate
    return sorted(set(tb_files))


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_testbenches(
    rtl_dir: Path,
    min_tests: int = 10,
) -> Tuple[List[Finding], List[TestbenchInfo]]:
    """Check testbench existence and coverage.

    Returns (findings, testbench_info_list).
    """
    findings: List[Finding] = []

    if not rtl_dir.exists():
        findings.append(Finding(
            severity="ERROR",
            category="NO_TESTBENCH",
            message=f"RTL directory does not exist: {rtl_dir}",
        ))
        return findings, []

    tb_files = find_testbenches(rtl_dir)

    if not tb_files:
        findings.append(Finding(
            severity="ERROR",
            category="NO_TESTBENCH",
            message=f"No testbench files (*_tb.v, tb_*.v, *_tb.sv, tb_*.sv) found in {rtl_dir}",
        ))
        return findings, []

    tb_infos: List[TestbenchInfo] = []
    total_tests = 0

    for tb_path in tb_files:
        text = tb_path.read_text(errors='replace')

        # Check for empty testbench
        non_empty_lines = [l for l in text.split('\n')
                           if l.strip() and not l.strip().startswith('//')]
        if len(non_empty_lines) < 3:
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_TESTBENCH",
                message=f"Testbench file is empty or trivial",
                file=str(tb_path),
            ))
            tb_infos.append(TestbenchInfo(
                file=str(tb_path), test_count=0, test_patterns=[]))
            continue

        # Structural check: must have initial/always blocks and timing delays
        has_block = bool(re.search(r'\b(initial\s+begin|always\s)', text))
        has_delay = bool(re.search(r'#\s*\d', text))
        if not has_block and not has_delay:
            findings.append(Finding(
                severity="WARNING",
                category="STRUCTURAL_ISSUE",
                message="Testbench has no initial/always blocks and no timing delays (#)",
                file=str(tb_path),
                details="A valid testbench needs at least one procedural block and timing control",
            ))
        elif not has_block:
            findings.append(Finding(
                severity="WARNING",
                category="STRUCTURAL_ISSUE",
                message="Testbench has no 'initial begin' or 'always' block",
                file=str(tb_path),
            ))
        elif not has_delay:
            findings.append(Finding(
                severity="WARNING",
                category="STRUCTURAL_ISSUE",
                message="Testbench has no timing delays (#) — simulation may not advance time",
                file=str(tb_path),
            ))

        # --- Additional structural quality checks (WARNINGS only) ---

        # a) CLOCK_RESET_MISSING: clock generation and reset handling
        has_clock = bool(re.search(
            r'always\s+#|Clock\s*\(|cocotb\.clock|clk|initial\s+begin\s*.*#',
            text, re.IGNORECASE))
        has_reset = bool(re.search(r'rst|reset|RST', text))
        if not has_clock and not has_reset:
            findings.append(Finding(
                severity="WARNING",
                category="CLOCK_RESET_MISSING",
                message="Testbench has no clock generation or reset handling patterns",
                file=str(tb_path),
                details="Expected at least one of: always #, Clock(, cocotb.clock, clk, "
                        "initial begin...#, rst, reset",
            ))

        # b) STIMULUS_METHOD_MISSING: stimulus generation
        has_stimulus = bool(re.search(
            r'\$random|randomize|constrained|directed|test_case|scenario|'
            r'@\s*\(\s*posedge|fork|task',
            text, re.IGNORECASE))
        if not has_stimulus:
            findings.append(Finding(
                severity="WARNING",
                category="STIMULUS_METHOD_MISSING",
                message="Testbench has no recognizable stimulus method",
                file=str(tb_path),
                details="Expected at least one of: $random, randomize, constrained, "
                        "directed, test_case, scenario, @(posedge, fork, task",
            ))

        # c) CHECKING_MISSING: self-checking / assertion
        has_checking = bool(re.search(
            r'assert|expect|PASS|FAIL|\$error|scoreboard|checker|monitor|golden',
            text, re.IGNORECASE))
        if not has_checking:
            findings.append(Finding(
                severity="WARNING",
                category="CHECKING_MISSING",
                message="Testbench has no self-checking mechanism",
                file=str(tb_path),
                details="Expected at least one of: assert, expect, PASS, FAIL, "
                        "$error, scoreboard, checker, monitor, golden",
            ))

        count, matched = count_test_cases(text)
        total_tests += count
        tb_infos.append(TestbenchInfo(
            file=str(tb_path), test_count=count, test_patterns=matched))

    if total_tests < min_tests:
        findings.append(Finding(
            severity="ERROR",
            category="INSUFFICIENT_TESTS",
            message=(
                f"Found {total_tests} test case(s) across {len(tb_files)} "
                f"testbench file(s), minimum required is {min_tests}"
            ),
            details=f"Testbenches: {[str(f) for f in tb_files]}",
        ))

    return findings, tb_infos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], tb_infos: List[TestbenchInfo],
                 rtl_dir: str, min_tests: int) -> dict:
    total_tests = sum(tb.test_count for tb in tb_infos)
    return {
        "program": "testbench_exists_check",
        "version": "1.2.0",
        "rtl_dir": rtl_dir,
        "min_tests": min_tests,
        "summary": {
            "testbench_count": len(tb_infos),
            "total_test_cases": total_tests,
            "findings_count": len(findings),
            "warnings_count": len([f for f in findings if f.severity == "WARNING"]),
            "errors_count": len([f for f in findings if f.severity == "ERROR"]),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "testbenches": [asdict(tb) for tb in tb_infos],
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify testbench existence and minimum test coverage"
    )
    parser.add_argument('--rtl-dir', required=True,
                        help="Path to RTL directory")
    parser.add_argument('--min-tests', type=int, default=10,
                        help="Minimum number of test cases required (default: 10)")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    findings, tb_infos = audit_testbenches(rtl_dir, args.min_tests)

    report = build_report(findings, tb_infos, str(rtl_dir), args.min_tests)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
