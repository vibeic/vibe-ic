#!/usr/bin/env python3
"""
drv_promotion_corroboration_check.py — a route promoted on its OWN
re-measurement must be corroborated by the SIGN-OFF report it claims to
improve (#293).

The lesson this encodes
-----------------------
`signoff_spef_repair` promotes a repaired route as the shipped sign-off route
when its own in-session numbers look better. Those numbers come from the SAME
OpenROAD session that did the repair: a fast SPEF re-extract plus
`report_check_types -violators`, parsed out of `signoff_spef_repair.log`.

That is not the measurement anyone downstream trusts. In the landed regression
that motivated this gate, the promotion gate read 330 -> 178 violations and
promoted; the real multi-corner OCV sign-off (`sta_mcorner_ocv.rpt`, the report
`sta_corner_record_completeness_check` actually reads) went 4 -> 219, and the
reroute additionally merged a spare-tie net into an unrelated signal net,
breaking LVS. The step was disabled in v1.5.65.

FIXING YOUR OWN INTERNAL RE-MEASUREMENT IS NOT THE SAME AS FIXING THE
DOWNSTREAM GATE'S MEASUREMENT. "Passes its own test" is not "actually better" —
and that regression came from a change whose whole purpose was to stop false
certificates.

Promotion happens BEFORE sign-off STA exists, so the promotion decision itself
cannot read the sign-off report. This gate therefore runs AFTER sign-off and
corroborates the claim retrospectively: if a promotion happened, the sign-off
report must agree that it did not make DRV worse.

Verdicts
--------
VACUOUS_PASS (0) no promotion happened this run (no `routed_base_prerepair.def`)
PASS         (0) promotion happened AND the sign-off report corroborates it
FAIL         (1) sign-off DRV is WORSE than the promotion claimed, or a
                 promotion happened with NO sign-off report to corroborate it
                 (an uncorroborated promotion is exactly the failure mode)
IO_ERROR     (2) argument / read error

ENFORCEMENT: blocking — shipping a route whose claimed improvement the
sign-off contradicts is the exact false certificate this exists to stop.
NOTE: currently wired AUDIT_ONLY; the contradiction is surfaced, not hidden.

chip-AGNOSTIC: no design, PDK, or cell literals — pure artefact grammar.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# The promotion leaves this behind when (and only when) it swapped the route.
_PROMOTION_MARKER = "routed_base_prerepair.def"
_REPAIR_LOG = "signoff_spef_repair.log"

# The report the acceptance gate reads. Same candidate paths as
# sta_corner_record_completeness_check, so the two can never diverge.
_SIGNOFF_RPT_CANDIDATES = (
    "phase3/stage3/sta/sta_mcorner_ocv.rpt",
    "reports/phase3/sta_mcorner_ocv.rpt",
)

_PNR_DIRS = ("phase3/stage3/pnr", "pnr")

# A DRV table row: "<pin>  <limit>  <value>  <slack>". A NEGATIVE trailing
# slack is a violation. Matches slew and capacitance tables identically.
#
# vibe-ic#579 — the `\s*$` used to sit immediately after the slack field, and
# OpenSTA does not end the line there. Every violating row it prints carries a
# trailing tag:
#
#     _07896_/B0                              3.00    6.12   -3.12 (VIOLATED)
#
# so the pattern matched NOTHING, `signoff_drv_violations()` returned 0 for every
# report, and this BLOCKING gate could not fail. Measured on a real shipped
# `sta_mcorner_ocv.rpt`: 0 matches against 4 rows carrying `(VIOLATED)`.
#
# The trailing group is OPTIONAL rather than required. A row ending in a bare
# negative slack is still a violation — requiring the tag would trade one
# unfireable gate for a narrower one, and would tie this gate to one tool's
# choice of decoration. Measured on the same corpus: 0 rows end in a bare
# negative slack today, so the optional arm changes no current verdict and
# exists so a build that stops printing the tag does not silently re-empty this
# gate.
_DRV_ROW_RE = re.compile(
    r"^\s*\S+\s+-?[\d.]+\s+-?[\d.]+\s+(-[\d.]+)\s*(?:\([A-Z]+\))?\s*$", re.M)


def find_signoff_report(project: Path) -> Optional[Path]:
    for rel in _SIGNOFF_RPT_CANDIDATES:
        p = project / rel
        if p.is_file():
            return p
    return None


def promotion_happened(project: Path) -> Optional[Path]:
    for d in _PNR_DIRS:
        p = project / d / _PROMOTION_MARKER
        if p.is_file():
            return p
    return None


def repair_log(project: Path) -> Optional[Path]:
    for d in _PNR_DIRS:
        p = project / d / _REPAIR_LOG
        if p.is_file():
            return p
    return None


def claimed_drv_after(log_text: str) -> Optional[int]:
    """What the promotion gate's OWN transcript claimed it ended at: the LAST
    `Found N slew violations.` plus the last capacitance count. None when the
    log carries no such claim."""
    slew = re.findall(r"Found (\d+) slew violations\.", log_text or "")
    cap = re.findall(r"Found (\d+) capacitance violations\.", log_text or "")
    if not slew and not cap:
        return None
    return (int(slew[-1]) if slew else 0) + (int(cap[-1]) if cap else 0)


def signoff_drv_violations(rpt_text: str) -> int:
    """DRV violations the SIGN-OFF report actually shows: rows in the max-slew
    / max-capacitance tables whose trailing slack is negative, across every
    corner section in the file."""
    return len(_DRV_ROW_RE.findall(rpt_text or ""))


def check(project: Path) -> dict:
    promo = promotion_happened(project)
    if promo is None:
        return {"verdict": "VACUOUS_PASS", "rc": 0,
                "reason": "no route promotion this run — gate inapplicable",
                "promoted": False}

    rpt = find_signoff_report(project)
    if rpt is None:
        return {"verdict": "FAIL", "rc": 1, "promoted": True,
                "reason": ("a repaired route was PROMOTED as the sign-off route "
                           "but no sign-off report exists to corroborate it. An "
                           "uncorroborated promotion is the exact failure mode "
                           "this gate exists for: the promotion gate's own "
                           "in-session numbers are not evidence."),
                "signoff_report": None}

    rtext = rpt.read_text(errors="replace")
    actual = signoff_drv_violations(rtext)
    log = repair_log(project)
    claimed = claimed_drv_after(log.read_text(errors="replace")) if log else None

    out = {"promoted": True, "signoff_report": str(rpt),
           "signoff_drv_violations": actual, "claimed_drv_after": claimed}
    if claimed is not None and actual > claimed:
        out.update({
            "verdict": "FAIL", "rc": 1,
            "reason": (f"the promotion claimed it ended at {claimed} DRV "
                       f"violation(s) from its own session, but the sign-off "
                       f"report the acceptance gate reads shows {actual}. "
                       f"Passing your own re-measurement is not passing the "
                       f"downstream gate — do not ship this route.")})
        return out
    out.update({"verdict": "PASS", "rc": 0,
                "reason": (f"promotion corroborated by the sign-off report "
                           f"({actual} DRV violation(s)"
                           + (f", claimed {claimed}" if claimed is not None else "")
                           + ")")})
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Corroborate a promoted route against the sign-off report.")
    ap.add_argument("project_dir", help="project root")
    ap.add_argument("--json", help="write the report JSON here")
    a = ap.parse_args(argv)
    project = Path(a.project_dir)
    if not project.is_dir():
        print(f"IO_ERROR: no such project dir: {project}", file=sys.stderr)
        return 2
    rep = check(project)
    print(f"=== DRV promotion corroboration ===\n"
          f"verdict: {rep['verdict']}\n{rep['reason']}")
    if rep["verdict"] == "VACUOUS_PASS":
        # vibe-ic#1115. The word was already right and the SHAPE was not:
        # `flow_compliance_check._stdout_signals_vacuous` matches the prefix at
        # line start, so "verdict: VACUOUS_PASS" reached nobody and the step was
        # recorded as an ordinary PASS. Measured against the consumer directly.
        print(f"VACUOUS_PASS: {rep['reason']}")
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    return rep["rc"]


if __name__ == "__main__":
    sys.exit(main())
