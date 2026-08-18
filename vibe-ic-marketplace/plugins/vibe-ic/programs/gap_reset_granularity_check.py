#!/usr/bin/env python3
"""gap_reset_granularity_check.py — deterministic compliance check derived from
<chip-class> v041 fresh-agent debug (bug #6, the final blocker).

Detects MAC FSMs that reset an end-of-command gap counter ONLY on byte-level
completion (`rx_byte_valid`) but NOT on bit-level activity (`bit_valid`).

Root cause from <chip-class> v041: between two bytes of a command, the elapsed time
from the last `rx_byte_valid` to the next one is tIBT + (7 bits × tBit) ≈ 82 µs
at 10 MHz. If `CMD_SETTLE_GAP` is set to anything below that, the FSM
prematurely exits `ST_RX` with only 1 byte captured → command dispatch fails.

The fix is NOT to just raise the threshold — the threshold must ALSO fit below
tSRS_min (device response-start time) to avoid host timeout. The correct fix
is to reset the gap counter on EVERY `bit_valid` pulse so gap only ticks during
true idle (no bit activity at all).

Heuristic pattern scanned:
  - Find an always block that declares a register named *gap_cnt* or similar,
    increments it on `if (gap_cnt < SOME_LIMIT)`, and triggers an FSM
    transition when the limit is reached.
  - Inside that block, check that gap_cnt is reset on an input signal named
    *bit_valid* (or similar bit-level activity indicator).
  - If gap_cnt is only reset on *_byte_valid or *_data_valid (byte-level),
    flag it.

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


GAP_REG_RE = re.compile(r"\breg\s*(?:\[[^\]]+\])?\s*(\w*gap_?cnt\w*)\s*;", re.IGNORECASE)
GAP_LIMIT_RE = re.compile(
    r"(\w*gap_?cnt\w*)\s*<\s*([A-Z_][A-Z0-9_]*|[0-9]+)",
    re.IGNORECASE,
)
GAP_RESET_RE = re.compile(
    r"(\w*gap_?cnt\w*)\s*<=\s*(?:16'd0|0|\{16\{1'b0\}\}|\d+'d0)",
    re.IGNORECASE,
)
BIT_VALID_HINT_RE = re.compile(r"\b(bit_valid|rx_bit_valid|bit_ready)\b")
BYTE_VALID_HINT_RE = re.compile(r"\b(rx_byte_valid|byte_valid|data_valid)\b")


def analyze_file(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        findings.append(
            Finding(
                rule="read-error",
                severity="error",
                message=f"Could not read file: {e}",
                file=str(path),
            )
        )
        return findings

    gap_regs = GAP_REG_RE.findall(text)
    if not gap_regs:
        return findings

    has_bit_reset = False
    has_byte_reset = False
    bit_reset_line = 0
    byte_reset_line = 0
    gap_reset_count = 0

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not GAP_RESET_RE.search(line):
            continue
        gap_reset_count += 1
        # Widen context window: gap_cnt reset is typically inside an `if`
        # block whose condition can be 10-15 lines earlier.
        window = "\n".join(
            text.splitlines()[max(0, lineno - 15) : min(len(text.splitlines()), lineno + 3)]
        )
        if BIT_VALID_HINT_RE.search(window):
            has_bit_reset = True
            bit_reset_line = lineno
        if BYTE_VALID_HINT_RE.search(window):
            has_byte_reset = True
            byte_reset_line = lineno

    if gap_reset_count >= 1 and has_byte_reset and not has_bit_reset:
        findings.append(
            Finding(
                rule="gap-reset-byte-only",
                severity="error",
                message=(
                    f"gap_cnt-like counter {gap_regs[0]!r} is reset on byte-level "
                    f"activity (line {byte_reset_line}) but NOT on bit-level activity. "
                    "Fresh agent anti-pattern from <chip-class> v041 debug: premature end-of-command "
                    "trigger during byte-2 reception. Fix: add `else if (bit_valid) gap_cnt <= 0;`"
                ),
                file=str(path),
                line=byte_reset_line,
            )
        )
    elif gap_reset_count >= 1 and not has_bit_reset and not has_byte_reset:
        findings.append(
            Finding(
                rule="gap-reset-unknown-source",
                severity="warning",
                message=(
                    f"gap_cnt-like counter {gap_regs[0]!r} reset logic does not reference "
                    "any *bit_valid or *byte_valid signal nearby. Verify gap_cnt resets on "
                    "bit-level activity to avoid premature end-of-command."
                ),
                file=str(path),
                line=0,
            )
        )

    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="RTL file(s) or directory to scan")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    files: List[Path] = []
    for p in args.paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(sorted(pp.rglob("*.v")))
            files.extend(sorted(pp.rglob("*.sv")))
        elif pp.is_file():
            files.append(pp)

    all_findings: List[Finding] = []
    for f in files:
        all_findings.extend(analyze_file(f))

    errors = [f for f in all_findings if f.severity == "error"]
    result = AuditResult(
        passed=(len(errors) == 0),
        findings=all_findings,
        stats={
            "files_scanned": len(files),
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
    # no gap reset granularity defect.
    #
    # Measured over 40 tracked corpus projects before landing: every one
    # scanned at least 1 file (counts 1..2, tracking the project), so no real
    # project moves. rc 2 is "could not check", which the CI dispatcher
    # already separates from a finding.
    if result.stats.get("files_scanned", 0) == 0:
        print(f"VACUOUS_PASS: gap_reset_granularity_check examined nothing "
              f"(reason: 0 files scanned) — this is not a clean result",
              file=sys.stderr)
        return 2

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
