#!/usr/bin/env python3
"""field_agent_terminology_scan.py — terminology guard for external text
(extracted from vibe-ic:core-agent-loop §Hard prohibitions #7).

Project terminology decided 2026-05-10: the half of the quality loop that
runs the plugin against benchmark ICs and files issues is the **field
agent**, NOT the "debug agent". External text the core-agent publishes
(GitHub issue comments, READMEs, skill prose, commit messages) must use
the canonical term.

The skill stated this as prose "use 'field agent' (not 'debug agent')".
This program makes it a real deterministic scan: feed it a file (or
--text), and it FAILs (rc=1) if the forbidden phrase "debug agent" (any
case, with one or more whitespace chars between the two words) appears.

It also reports — advisory, never failing — whether the canonical
"field agent" term appears, so a caller can spot text that talks about
the loop role using neither phrase.

Usage
-----
    python3 field_agent_terminology_scan.py <file.md> [--json <out>]
    python3 field_agent_terminology_scan.py --text "ask the debug agent to verify"

Exit codes
----------
    0   PASS — no "debug agent" occurrence.
    1   FAIL — ≥1 "debug agent" occurrence (line numbers in the report).
    2   argument / I/O error.

Missing file -> rc 2 (honest). Empty input -> rc 0 but `vacuous=true` in
the JSON so an empty file cannot masquerade as verified-clean prose.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# "debug agent" with one-or-more intervening whitespace, case-insensitive,
# word-bounded so "debugging-agentless" etc. do not match.
_FORBIDDEN = re.compile(r"\bdebug\s+agent\b", re.IGNORECASE)
# Canonical term, for the advisory presence report.
_CANONICAL = re.compile(r"\bfield\s+agent\b", re.IGNORECASE)


@dataclass
class Hit:
    line_no: int
    text: str


@dataclass
class Report:
    passed: bool
    scanned_lines: int
    vacuous: bool
    forbidden_hits: List[Hit] = field(default_factory=list)
    canonical_present: bool = False


def scan_text(text: str) -> Report:
    lines = text.splitlines()
    hits: List[Hit] = []
    canonical = False
    nonblank = 0
    for idx, ln in enumerate(lines, start=1):
        if ln.strip():
            nonblank += 1
        if _FORBIDDEN.search(ln):
            hits.append(Hit(line_no=idx, text=ln.strip()))
        if _CANONICAL.search(ln):
            canonical = True
    return Report(
        passed=(len(hits) == 0),
        scanned_lines=nonblank,
        vacuous=(nonblank == 0),
        forbidden_hits=hits,
        canonical_present=canonical,
    )


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Reject 'debug agent'; enforce canonical 'field agent' "
                    "in external text (chip-AGNOSTIC).")
    p.add_argument("file", nargs="?", default=None,
                   help="Text file to scan (markdown / comment body / etc.).")
    p.add_argument("--text", default=None,
                   help="A literal string to scan (instead of a file).")
    p.add_argument("--json", default=None, help="Write JSON report to this path.")
    args = p.parse_args(argv)

    if args.text is not None:
        text = args.text
    elif args.file is not None:
        fp = Path(args.file)
        if not fp.is_file():
            print(f"ERROR: file not found: {fp}", file=sys.stderr)
            return 2
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError as e:
            print(f"ERROR: cannot read {fp}: {e}", file=sys.stderr)
            return 2
    else:
        print("ERROR: provide a file or --text", file=sys.stderr)
        return 2

    report = scan_text(text)
    report_json = json.dumps(asdict(report), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json + "\n", encoding="utf-8")

    if report.forbidden_hits:
        print("[FAIL] field_agent_terminology_scan: "
              f"{len(report.forbidden_hits)} occurrence(s) of 'debug agent' "
              f"(use 'field agent'):")
        for h in report.forbidden_hits:
            print(f"  line {h.line_no}: {h.text}")
        return 1

    if report.vacuous:
        print("[PASS] field_agent_terminology_scan: empty input (vacuous).")
        return 0

    print(f"[PASS] field_agent_terminology_scan: {report.scanned_lines} "
          f"line(s) clean — no 'debug agent' "
          f"(canonical 'field agent' present={report.canonical_present}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
