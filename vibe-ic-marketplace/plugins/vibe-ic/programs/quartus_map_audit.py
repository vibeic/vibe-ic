#!/usr/bin/env python3
"""
quartus_map_audit.py — Scan Quartus .map.rpt for silent-failure indicators.

Learned from <chip-class> FPGA BIST debug (2026-04-21):

  Quartus can compile a design "successfully" (0 errors) while still having
  rejected critical RTL init blocks or lost fanout on key registers. The
  map report flags these cases, but they are buried in hundreds of pages.

This program checks for patterns that almost always indicate broken hardware
even though the build tool returned success:

  1. "Stuck at GND" / "Stuck at VCC" — a register or net is optimized to a
     constant because its data_in cannot change. Usually caused by a failed
     ROM/LUT init, a missing driver, or an unreachable FSM state.

  2. "has no driver or initial value" (Warning 10030) — a signal has been
     declared but synthesis found no logic to drive it.

  3. "initial value for variable <name> should be constant" (Warning 10855) —
     an `initial` block assignment was dropped because Quartus couldn't fold
     it to a constant at elaboration time.

  4. "Lost fanout" — a register's output is never consumed after optimization;
     typically a symptom of upstream logic being optimized away to a constant.

Usage:
    python3 quartus_map_audit.py <path-to-*.map.rpt>
    python3 quartus_map_audit.py --json out.json <path-to-*.map.rpt>

Exit codes:
    0 = clean (no hits)
    1 = at least one audit finding (always blocking)
    2 = usage / io error
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
    line: int
    text: str
    severity: str  # "error"


_PATTERNS = [
    ("stuck-at-gnd", re.compile(r"Stuck at GND", re.IGNORECASE)),
    ("stuck-at-vcc", re.compile(r"Stuck at VCC", re.IGNORECASE)),
    ("no-driver",    re.compile(r"Warning \(10030\)")),
    ("init-not-const", re.compile(r"Warning \(10855\)")),
    # Lost fanout lines appear inside tables; match them but exclude the
    # header line so we don't spam findings for every column.
    ("lost-fanout",  re.compile(r"Lost fanout", re.IGNORECASE)),
]


def scan(path: Path) -> List[Finding]:
    if not path.exists():
        print(f"quartus_map_audit: missing report file: {path}", file=sys.stderr)
        raise SystemExit(2)
    findings: List[Finding] = []
    with path.open(errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip()
            # skip table header/footer junk
            if line.startswith(";") and "Registers optimized away" in line:
                continue
            for rule, pat in _PATTERNS:
                if pat.search(line):
                    findings.append(
                        Finding(
                            rule=rule,
                            line=lineno,
                            text=line.strip()[:300],
                            severity="error",
                        )
                    )
                    break
    return findings


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("report", help="Path to Quartus *.map.rpt file")
    p.add_argument("--json", help="Write findings as JSON")
    args = p.parse_args(argv)

    findings = scan(Path(args.report))

    if args.json:
        Path(args.json).write_text(
            json.dumps([asdict(f) for f in findings], indent=2)
        )

    if not findings:
        print("quartus_map_audit: OK — no silent-failure indicators found")
        return 0

    # group by rule for readable output
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    for rule, lst in by_rule.items():
        print(f"\n[{rule}] {len(lst)} hit(s):", file=sys.stderr)
        for f in lst[:10]:
            print(f"  {f.line}: {f.text}", file=sys.stderr)
        if len(lst) > 10:
            print(f"  ... ({len(lst) - 10} more)", file=sys.stderr)

    print(
        f"\nquartus_map_audit: {len(findings)} finding(s) — "
        f"build reports 0 errors but synthesis may have silently dropped logic. "
        f"See LL memory: feedback_fpga_debug_order.md + "
        f"feedback_quartus_init_for_loop.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
