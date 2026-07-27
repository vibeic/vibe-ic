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

Project mode (`--project`), added when this check was wired into the flow
------------------------------------------------------------------------
A flow gate CANNOT be conditioned on the hold artefact's existence: a project
that produced no hold analysis at all is the very defect this check exists to
name, and a `condition_files_exist` on that path would disable the check in
exactly that case (`flow_condition_reachability_check` — the self-disabling
condition guard — refuses that shape, and refused this one).

So `--project <dir>` DISCOVERS every hold-analysis script/log in the project
and judges ALL of them, which also closes a real gap: a flow can emit two hold
views (the multi-corner OCV one and the SI-MCF re-run), and only one of them
being FF-fed is not good enough. `_resolve_flow_liberty` in si_mcf_sta.py
recovers its Liberty from the SETUP script, so the second view is precisely
where an SS-fed hold analysis appears.

Finding nothing is a DISCLOSED skip (rc 2) that prints every pattern searched
— never a silent pass, and never a cry-wolf FAIL on a flow that names its hold
artefacts differently.

Usage
-----
    python3 hold_corner_coverage_check.py <hold_tcl_or_log> [--json <out>]
    python3 hold_corner_coverage_check.py --project . [--json <out>]
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


# ── --project discovery ─────────────────────────────────────────────────────
# The SCRIPTS/LOGS that DRIVE a hold analysis. Report files (*.rpt) are
# deliberately excluded: they carry the analysis RESULT, not the Liberty it was
# fed, and mining them would invent verdicts from output text.
_HOLD_GLOBS = (
    "phase3/stage3/sta/*hold*.tcl",
    "phase3/stage3/sta/*hold*.sdc",
    "phase3/stage3/sta/*hold*.log",
    "phase3/stage3/extracted/*hold*.tcl",
    "phase3/stage3/extracted/*/*hold*.tcl",
    "phase3/stage3/extracted/*/*hold*.log",
    "phase3/stage3/sta/*/*hold*.tcl",
)


def discover_hold_artefacts(project: Path) -> List[Path]:
    seen, out = set(), []
    for pat in _HOLD_GLOBS:
        for p in sorted(project.glob(pat)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _judge(p: Path) -> Tuple[str, int, dict]:
    try:
        text: Optional[str] = p.read_text(errors="replace")
    except OSError:
        text = None
    verdict, rc, report = evaluate(text)
    report["artefact"] = str(p)
    return verdict, rc, report


def _emit(report: dict, json_path: Optional[str]) -> None:
    if not json_path:
        return
    outp = Path(json_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(report, indent=2) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Confirm hold analysis uses the FF (fast) corner")
    ap.add_argument("hold_artefact", nargs="?", default=None,
                    help="hold-analysis Tcl / SDC / log that drives the "
                         "min-path (hold) check")
    ap.add_argument("--project", default=None,
                    help=("Project directory: discover and judge EVERY "
                          "hold-analysis script/log in it. A flow gate cannot "
                          "be conditioned on one artefact's existence without "
                          "disabling itself in the case it exists to catch, so "
                          "this is the mode the flow uses. Finding none is a "
                          "DISCLOSED skip (rc 2) listing what was searched."))
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    if args.project is not None:
        project = Path(args.project)
        if not project.is_dir():
            print(f"ERROR: --project is not a directory: {project}",
                  file=sys.stderr)
            return 2
        found = discover_hold_artefacts(project)
        if not found:
            report = {
                "tool": _TOOL, "verdict": "SKIP", "reason": "NO_HOLD_ARTEFACT",
                "message": ("no hold-analysis script/log found — nothing to "
                            "judge. NOT a pass: this run has no evidence that "
                            "hold was analysed at the fast corner."),
                "searched": list(_HOLD_GLOBS), "artefacts": [],
            }
            _emit(report, args.json)
            print(f"=== {_TOOL} === verdict: SKIP")
            print(f"  {report['message']}")
            print(f"  searched: {', '.join(_HOLD_GLOBS)}")
            return 2
        results = [_judge(p) for p in found]
        failing = [r for r in results if r[0] == "FAIL"]
        report = {
            "tool": _TOOL,
            "verdict": "FAIL" if failing else "PASS",
            "artefacts_judged": len(results),
            "artefacts": [r[2] for r in results],
            "failing": [r[2]["artefact"] for r in failing],
        }
        _emit(report, args.json)
        print(f"=== {_TOOL} === verdict: {report['verdict']}")
        print(f"  hold artefacts judged: {len(results)}")
        for v, _rc, rep in results:
            corners = rep.get("hold_feed_corners") or []
            print(f"  [{v}] {rep['artefact']} corners={corners}")
            if v == "FAIL":
                print(f"        FAIL [{rep.get('reason')}]: "
                      f"{rep.get('message')}")
        return 1 if failing else 0

    if not args.hold_artefact:
        ap.error("a hold artefact path is required unless --project is given")

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

    _emit(report, args.json)
    print(f"=== {_TOOL} === verdict: {verdict}")
    if report.get("hold_feed_corners"):
        print(f"  hold feed corners: {report['hold_feed_corners']}")
    if verdict == "FAIL":
        print(f"  FAIL [{report.get('reason')}]: {report.get('message')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
