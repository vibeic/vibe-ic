#!/usr/bin/env python3
"""crc_residual_check.py — deterministic compliance check derived from
<chip-class> v041 fresh-agent debug (bug #5).

Detects RTL that checks `crc_out == 0` (or equivalent) to validate a received
frame, WITHOUT verifying that the CRC accumulator is initialized to 0x00.

Root cause: "residual = 0 after feeding data || CRC(data)" holds ONLY when the
CRC register is initialized to 0x00. For CRC-8 init=0xFF (common: Apple AID,
Maxim 1-Wire), the residual is NON-ZERO and protocol-specific. Hard-coding
`== 0` silently drops every command.

Heuristic pattern scanned:
  - Any equality comparison like `*crc*_out == 8'h00`, `*crc_reg == 0`, etc.
  - Check nearby for an `init=0xFF` / `crc_reg <= 8'hFF` / `crc_clear → 8'hFF`.
  - If an 0xFF initializer is found AND a `== 0` residual check is present, flag.

Exit: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Directory arguments
# route through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the per-line regex scan again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    passed: bool
    findings: List[Finding]
    stats: dict

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "findings": [asdict(f) for f in self.findings],
                "stats": self.stats,
            },
            indent=2,
        )


CRC_INIT_FF_RE = re.compile(
    r"(?:crc\w*|reg)\s*<=\s*8'h[fF][fF]\b|crc_reg\s*=\s*8'h[fF][fF]|seed\s*=\s*0x[fF][fF]",
    re.IGNORECASE,
)
CRC_ZERO_CHECK_RE = re.compile(
    r"\w*crc\w*_out\s*==\s*(?:8'h0+|8'd0|0)\b|\w*crc_reg\s*==\s*(?:8'h0+|8'd0|0)\b",
    re.IGNORECASE,
)
CRC_RELATED_RE = re.compile(r"\bcrc\w*\b", re.IGNORECASE)


def analyze_tree(paths: List[Path]) -> List[Finding]:
    findings: List[Finding] = []

    # Gather all Verilog files across input paths (directories go through the
    # shared authored-RTL collector; explicit files are honoured verbatim).
    files: List[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(rtl_source_files(p))
        elif p.is_file():
            files.append(p)

    has_init_ff = False
    ff_evidence_file = ""
    ff_evidence_line = 0
    zero_checks: List[tuple] = []  # (path, line)

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            findings.append(
                Finding(
                    rule="read-error",
                    severity="error",
                    message=f"Could not read file: {e}",
                    file=str(f),
                )
            )
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if CRC_INIT_FF_RE.search(line):
                has_init_ff = True
                if not ff_evidence_file:
                    ff_evidence_file = str(f)
                    ff_evidence_line = lineno
            if CRC_ZERO_CHECK_RE.search(line):
                zero_checks.append((str(f), lineno, line.strip()))

    if has_init_ff and zero_checks:
        for path, lineno, snippet in zero_checks:
            findings.append(
                Finding(
                    rule="crc-residual-zero-on-init-ff",
                    severity="error",
                    message=(
                        f"CRC residual check `== 0` present ({snippet!r}) while a CRC init=0xFF "
                        f"was detected at {ff_evidence_file}:{ff_evidence_line}. "
                        "Residual != 0 for init=0xFF. Anti-pattern from <chip-class> v041. "
                        "Fix: trust `cmd_cnt >= expected_bytes` OR compute real residual offline "
                        "and compare against that, OR init CRC to 0x00 if protocol allows."
                    ),
                    file=path,
                    line=lineno,
                )
            )

    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="RTL file(s) or directory")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    all_findings = analyze_tree([Path(p) for p in args.paths])
    errors = [f for f in all_findings if f.severity == "error"]

    # count files scanned (same collector as analyze_tree so the stat matches
    # what was actually scanned)
    fscanned = 0
    for p in args.paths:
        pp = Path(p)
        if pp.is_dir():
            fscanned += len(rtl_source_files(pp))
        elif pp.is_file():
            fscanned += 1

    result = AuditResult(
        passed=(len(errors) == 0),
        findings=all_findings,
        stats={
            "files_scanned": fscanned,
            "errors": len(errors),
            "warnings": len(all_findings) - len(errors),
        },
    )

    if args.json:
        print(result.to_json())
    else:
        for f in all_findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity.upper()}] {f.rule}: {f.message} ({loc})")
        print(
            f"\nFiles: {result.stats['files_scanned']}  "
            f"Errors: {result.stats['errors']}  "
            f"Warnings: {result.stats['warnings']}  "
            f"Result: {'PASS' if result.passed else 'FAIL'}"
        )

    # Zero files scanned is not a clean project (#564). `passed` is true
    # because nothing contradicted the rule, and rc 0 is what the P0 umbrella
    # aggregates — so a path with no RTL under it would be certified as having
    # no crc residual defect.
    #
    # Measured over 40 tracked corpus projects before landing: every one
    # scanned at least 1 file (counts 1..2, tracking the project), so no real
    # project moves. rc 2 is "could not check", which the CI dispatcher
    # already separates from a finding.
    if result.stats.get("files_scanned", 0) == 0:
        print(f"VACUOUS_PASS: crc_residual_check examined nothing "
              f"(reason: 0 files scanned) — this is not a clean result",
              file=sys.stderr)
        return 2

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
