#!/usr/bin/env python3
"""device_response_no_br_check.py — deterministic compliance check derived from
<chip-class> v042 fresh-agent debug.

Flags tx_phy modules that include BR (Break/Reset) states in the response
transmission path. In protocols where BR is host-only (e.g., Apple AID, many
single-wire protocols), the DEVICE tx_phy response MUST NOT emit a leading BR.

Heuristic pattern scanned (Verilog / SystemVerilog):
  - Look for module named *tx_phy* or files whose role is transmission
  - Inside, if a state enum has ST_BR_LOW/ST_BR_HIGH/BR_LOW/BR_HIGH declared,
    check if it's reachable from ST_IDLE → ST_START_WAIT → ST_BR_* transition.
  - If reachable during normal transmission (not behind a `tx_send_br` input),
    flag as error.

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


BR_STATE_DEF_RE = re.compile(r"ST_BR_(?:LOW|HIGH)\b", re.IGNORECASE)
BR_STATE_TRANS_RE = re.compile(r"(?:st|state)\s*<=\s*ST_BR_(?:LOW|HIGH)\b", re.IGNORECASE)
TX_SEND_BR_GUARD_RE = re.compile(r"\btx_send_br\b|\bsend_br\b|\btrail_br\b", re.IGNORECASE)
TX_PHY_FILE_HINT = re.compile(r"tx_phy|tx_pad|response_phy", re.IGNORECASE)


def analyze_file(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        findings.append(
            Finding(
                rule="read-error",
                severity="error",
                message=f"Could not read: {e}",
                file=str(path),
            )
        )
        return findings

    # Only analyze if this looks like a TX PHY file
    is_tx_phy = (
        TX_PHY_FILE_HINT.search(path.name)
        or re.search(r"\bmodule\s+tx_phy\b", text, re.IGNORECASE)
    )
    if not is_tx_phy:
        return findings

    # Scan for BR state transitions
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not BR_STATE_TRANS_RE.search(line):
            continue
        # Check the surrounding ~10 lines for a guard like `if (tx_send_br)`
        window_lo = max(0, lineno - 10)
        window_hi = min(len(text.splitlines()), lineno + 2)
        window = "\n".join(text.splitlines()[window_lo:window_hi])
        if TX_SEND_BR_GUARD_RE.search(window):
            # Gated behind an explicit tx_send_br input → acceptable (for hosts)
            continue
        findings.append(
            Finding(
                rule="device-response-has-leading-br",
                severity="error",
                message=(
                    f"tx_phy transitions to a ST_BR_* state at line {lineno} without "
                    "a `tx_send_br`/`send_br` guard. Device response MUST NOT emit "
                    "leading BR — BR is host-only per typical single-wire protocols "
                    "(Apple AID, etc.). Fresh-agent bug from <chip-class> v042: <half-duplex-tester> "
                    "rejects responses starting with BR as host traffic. "
                    "Fix: remove ST_BR_* states from response path, or gate them "
                    "behind an external tx_send_br input."
                ),
                file=str(path),
                line=lineno,
            )
        )

    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="RTL file(s) or directory")
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
    # no device response no br defect.
    #
    # Measured over 40 tracked corpus projects before landing: every one
    # scanned at least 1 file (counts 1..2, tracking the project), so no real
    # project moves. rc 2 is "could not check", which the CI dispatcher
    # already separates from a finding.
    if result.stats.get("files_scanned", 0) == 0:
        print(f"VACUOUS_PASS: device_response_no_br_check examined nothing "
              f"(reason: 0 files scanned) — this is not a clean result",
              file=sys.stderr)
        return 2

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
