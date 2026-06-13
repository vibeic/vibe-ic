#!/usr/bin/env python3
"""
hold_corner_coverage_check.py — confirm hold is analysed at the FAST (FF)
corner, the worst-case corner for hold.

From `skills/hold-fix/SKILL.md` Step 1 + Step 6:
  "Run STA at the FF corner (fast process, high voltage, low temperature)."
  "Hold must be verified across all fast corners: FF, high voltage, low
   temperature (worst hold). ... If using MCMM, the hold analysis view must use
   the FF corner."

This is the narrow, hold-SPECIFIC corner rule — distinct from the broad PVT
presence audit in `corner_coverage_audit.py` (which only checks that SS/TT/FF
Liberty files exist somewhere in the tree). Here we verify that the LIBERTY /
operating-condition actually consumed by the HOLD analysis is a FAST corner.
A flow can have FF `.lib` files present (corner_coverage_audit PASS) yet still
read the SS/TT Liberty for its hold check — that is the real defect this gate
catches: hold analysed at the WRONG (non-FF) corner under-reports hold
violations and ships a hold-broken chip.

What it scans
-------------
A hold-analysis Tcl/SDC/log artefact (the file that drives the hold check).
It looks for the Liberty / operating-condition that the hold path consumes:
  * `read_liberty ...ff...lib`            (OpenSTA)
  * `report_checks -path_delay min ...`   (the hold-report invocation)
  * `set_operating_conditions ... ff...`  (MCMM hold view)
  * any explicit "hold corner = ff" / "min view = ff" assignment.

A process corner is FAST when its designator is `ff` / `fast_fast` / `fast`.
SS / TT (slow / typical) used for the hold (min) analysis is the FAIL.

Verdicts
--------
* PASS (rc=0) — a hold/min analysis is present AND every Liberty/operating
                condition feeding it is a FAST (FF) corner.
* FAIL (rc=1) — the hold/min analysis reads a NON-fast (SS/TT) Liberty or
                operating condition, OR no hold/min analysis is present at all
                (nothing was verified — honest FAIL, not a vacuous pass), OR
                the input file is missing/empty/garbage.

chip-AGNOSTIC: corner designators are matched by the same general convention
patterns used by corner_coverage_audit.py; no PDK / vendor cell is hard-coded.

Usage
-----
    python3 hold_corner_coverage_check.py <hold_tcl_or_log> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_TOOL = "hold_corner_coverage_check"

# Process-corner designators (subset of corner_coverage_audit.PROCESS_CORNER_MAP).
_FAST = {"ff", "fast_fast", "fastfast", "fast"}
_SLOW = {"ss", "slow_slow", "slowslow", "slow"}
_TYP = {"tt", "typical", "typ", "nom"}

_PROC_RE = re.compile(
    r"(?:^|[_/\-.\s:,])"
    r"(ss|tt|ff|sf|fs|slow_slow|fast_fast|typical|slowslow|fastfast|"
    r"slow_fast|fast_slow|slowfast|fastslow|slow|fast|typ|nom)"
    r"(?:[_/\-.\s:,]|$)",
    re.IGNORECASE,
)

# Lines that introduce a Liberty / operating-condition used by the MIN (hold)
# analysis. We mine the Liberty read AND any min-path / hold view assignment.
_LIB_READ_RE = re.compile(r"\bread_liberty\b(.*)$", re.I)
_MIN_VIEW_RE = re.compile(
    r"(?:hold|min)[^\n]*?(?:corner|view|operating_condition|lib)\b(.*)$", re.I)
_SET_OC_RE = re.compile(r"\bset_operating_conditions\b(.*)$", re.I)
# The invocation that runs the hold report (proves a hold analysis exists).
_HOLD_RUN_RE = re.compile(
    r"report_checks[^\n]*-path_delay\s+min|"
    r"report_worst_slack[^\n]*-min|report_tns[^\n]*-min|"
    r"\b-path_delay\s+min\b|\bcheck_hold\b", re.I)


def _classify_corner(token: str) -> str:
    t = token.lower()
    if t in _FAST:
        return "FF"
    if t in _SLOW:
        return "SS"
    if t in _TYP:
        return "TT"
    return "OTHER"


def _corners_in(text: str) -> List[str]:
    out = []
    for m in _PROC_RE.finditer(text):
        c = _classify_corner(m.group(1))
        if c in ("FF", "SS", "TT"):
            out.append(c)
    return out


def evaluate(text: Optional[str]) -> Tuple[str, int, dict]:
    report = {"tool": _TOOL}
    if text is None:
        report.update(verdict="FAIL", reason="INPUT_MISSING",
                      message="hold-analysis artefact missing/unreadable — "
                              "cannot verify the hold corner (honest FAIL)")
        return "FAIL", 1, report
    if not text.strip():
        report.update(verdict="FAIL", reason="INPUT_EMPTY",
                      message="hold-analysis artefact is empty")
        return "FAIL", 1, report

    has_hold_run = bool(_HOLD_RUN_RE.search(text))
    report["hold_analysis_present"] = has_hold_run
    if not has_hold_run:
        report.update(verdict="FAIL", reason="NO_HOLD_ANALYSIS",
                      message="no hold (min-path) analysis found "
                              "(report_checks -path_delay min / "
                              "report_worst_slack -min) — nothing was verified")
        return "FAIL", 1, report

    # Collect the corners that feed the hold/min analysis: every read_liberty,
    # set_operating_conditions, and explicit min/hold view line.
    feed_lines: List[str] = []
    for line in text.splitlines():
        if _LIB_READ_RE.search(line) or _SET_OC_RE.search(line) \
                or _MIN_VIEW_RE.search(line):
            feed_lines.append(line)

    feed_corners: List[str] = []
    for line in feed_lines:
        feed_corners.extend(_corners_in(line))
    report["hold_feed_corners"] = sorted(set(feed_corners))
    report["hold_feed_lines"] = feed_lines

    if not feed_corners:
        # A hold analysis runs but we cannot find ANY Liberty / OC corner
        # designator feeding it — we cannot certify it is FF. Honest FAIL.
        report.update(verdict="FAIL", reason="NO_FEED_CORNER",
                      message="hold analysis present but no Liberty / operating "
                              "condition corner could be identified feeding it "
                              "— cannot confirm the FF corner is used")
        return "FAIL", 1, report

    non_fast = [c for c in set(feed_corners) if c != "FF"]
    if non_fast:
        report.update(verdict="FAIL", reason="HOLD_NOT_AT_FF",
                      message=f"hold (min) analysis reads a NON-fast corner "
                              f"{sorted(non_fast)} — hold is worst at FF "
                              f"(fast/high-V/low-T); reading {sorted(non_fast)} "
                              f"under-reports hold violations")
        return "FAIL", 1, report

    report.update(verdict="PASS", reason="HOLD_AT_FF",
                  message="hold (min) analysis is driven by the FF corner — "
                          "the worst-case corner for hold")
    return "PASS", 0, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Confirm hold analysis uses the FF (fast) corner")
    ap.add_argument("hold_artefact",
                    help="hold-analysis Tcl / SDC / log that drives the "
                         "min-path (hold) check")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    p = Path(args.hold_artefact)
    text: Optional[str]
    if not p.is_file():
        text = None
    else:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            text = None

    verdict, rc, report = evaluate(text)
    report["artefact"] = str(p)

    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"=== {_TOOL} === verdict: {verdict}")
    if report.get("hold_feed_corners"):
        print(f"  hold feed corners: {report['hold_feed_corners']}")
    if verdict == "FAIL":
        print(f"  FAIL [{report.get('reason')}]: {report.get('message')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
