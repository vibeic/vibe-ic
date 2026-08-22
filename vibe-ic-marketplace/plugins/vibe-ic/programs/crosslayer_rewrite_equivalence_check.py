#!/usr/bin/env python3
"""crosslayer_rewrite_equivalence_check.py — the JUDGE for the rewrite-fidelity
gate (`crosslayer_rewrite_equivalence.py` is the PRODUCER).

Same split the flow already uses at step 13: the producer drives the tool and
writes a truthful report; a separate program decides PASS/FAIL by INDEPENDENTLY
reading that report. The split is why the gate command needs no design-specific
argument, and it is also why a producer that never ran cannot look like a
producer that ran and found nothing wrong.

WHAT IT REFUSES, AND WHY EACH ONE HAS TO BE HERE
------------------------------------------------
    CLX_BASELINE_PRESENT_NO_REPORT  a cross-layer baseline snapshot exists (so
                                    the design's RTL may have been REWRITTEN)
                                    and no rewrite-fidelity report was written
                                    -- a search that skips its own filter has
                                    not been filtered. NOT the clause that does
                                    the blocking: MEASURED, deleting it leaves
                                    `CLX_REPORT_MISSING` refusing the same
                                    case. It is the clause that says WHY, and a
                                    refusal a reader cannot act on is worth
                                    less than one they can.
    CLX_REPORT_MISSING              the report the caller named is not there
    CLX_REPORT_UNPARSEABLE          present, not JSON
    CLX_NOT_EQUIVALENT              measured: a counterexample exists
    CLX_NOT_PROVEN                  ran, proved nothing, refuted nothing
    CLX_NOT_MEASURED                nothing was compared at all
    CLX_VACUOUS_CLAIM               status PASS with zero compared points --
                                    the same vacuous-proof hole step 13's own
                                    judge closes, closed again here because a
                                    second copy of a boolean is not evidence
    CLX_UNCITED_LATENCY_OFFSET      the comparison used a latency offset with
                                    no cited specification sentence. An offset
                                    realigns what is compared; one nobody
                                    authorised is a cheat, not a mode.
    CLX_SEARCH_SPACE_UNVERIFIABLE   a search ran and its emitted search space
                                    fails its own citation audit, so at least
                                    one lever was searched on a sentence that
                                    is not there.

WHAT THIS GATE CANNOT SEE, STATED PLAINLY
-----------------------------------------
It binds on DECLARED artefacts. A search driver that rewrote the RTL and
declared nothing -- no baseline snapshot, no search space, no report -- leaves
this program with a tree indistinguishable from a design that never ran a
search, and it correctly reports NOT_APPLICABLE. No artefact-reading gate can
close that; closing it needs a digest of step 1's RTL carried forward by the
flow, which does not exist at the revision this was written against. The
snapshot is written by `crosslayer_search_space` before any lever is searched,
so an undeclared search has also skipped its own authorisation -- but that is a
discipline, not a proof, and it is recorded here as a discipline.

THIS GATE IS UNCONDITIONAL, ON PURPOSE
--------------------------------------
It was first written as a flow step CONDITIONAL on the baseline snapshot
existing, and `flow_condition_reachability_check` refused that shape in one
line: *"a check disabled by exactly the situation it was written for"*. A
search that skipped the snapshot would have skipped the gate with it. So the
step always runs and this program always writes a verdict; a design that never
ran a cross-layer search gets an explicit `NOT_APPLICABLE` RECORD — not a
silent skip, and not an absence a reader has to interpret.

A PASS requires the report to say PASS **and** to carry >0 compared points
**and** 0 unproven points, re-derived here from the counts rather than trusted
from the verdict string.

CLI
    python3 crosslayer_rewrite_equivalence_check.py <project_dir>
        [--report reports/crosslayer/rewrite_equivalence.json]
        [--baseline-marker reports/crosslayer/baseline_rtl]
        [--json <out>]
    main(argv) -> int   0 PASS / 1 FAIL / 2 IO-or-arg error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROGRAM = "crosslayer_rewrite_equivalence_check"
DEFAULT_REPORT_REL = "reports/crosslayer/rewrite_equivalence.json"
DEFAULT_MARKER_REL = "reports/crosslayer/baseline_rtl"
DEFAULT_SPACE_REL = "reports/crosslayer/search_space.json"
DEFAULT_JSON_REL = "reports/crosslayer/rewrite_equivalence_check.json"


def judge(report: Optional[Dict], *, baseline_present: bool,
          report_readable: bool,
          space_problems: Optional[List[str]] = None) -> Tuple[bool, str, str]:
    """(ok, status, explanation). Pure — the tests drive this directly."""
    if report is None:
        if not report_readable and baseline_present:
            return (False, "CLX_BASELINE_PRESENT_NO_REPORT",
                    "a cross-layer baseline snapshot exists, so this design's "
                    "RTL may have been rewritten, and NO rewrite-fidelity "
                    "report was produced. A search that skips its own filter "
                    "has not been filtered.")
        if not report_readable:
            return (False, "CLX_REPORT_MISSING",
                    "no rewrite-fidelity report at the named path.")
        return (False, "CLX_REPORT_UNPARSEABLE",
                "the rewrite-fidelity report is present but is not valid JSON.")

    status = str(report.get("status") or "")
    compared = int(report.get("compared_points") or 0)
    unproven = int(report.get("unproven_points") or 0)
    offset = int(report.get("latency_offset_cycles") or 0)
    evidence = report.get("latency_freedom_evidence")

    if offset and not (isinstance(evidence, dict) and evidence.get("literal")):
        return (False, "CLX_UNCITED_LATENCY_OFFSET",
                f"the comparison used a {offset}-cycle latency offset with no "
                f"cited specification sentence. An offset realigns what is "
                f"compared; one nobody authorised is a cheat, not a mode.")
    if status == "NOT_EQUIVALENT":
        return (False, "CLX_NOT_EQUIVALENT",
                f"measured: the candidate is not the baseline "
                f"({report.get('explanation', '')})")
    if status == "NOT_PROVEN_EQUIVALENT":
        return (False, "CLX_NOT_PROVEN",
                f"the comparison ran and neither proved nor refuted "
                f"{unproven} of {compared} point(s). Unproven is not proven.")
    if status == "NOT_MEASURED":
        return (False, "CLX_NOT_MEASURED",
                f"nothing was compared ({report.get('explanation', '')}). "
                f"Absence of a measurement is never a pass.")
    if status != "PASS":
        return (False, "CLX_NOT_MEASURED",
                f"unrecognised status {status!r}; refusing to read it as a "
                f"proof.")
    if compared <= 0:
        return (False, "CLX_VACUOUS_CLAIM",
                "the report says PASS having compared ZERO points.")
    if unproven != 0:
        return (False, "CLX_NOT_PROVEN",
                f"the report says PASS while {unproven} point(s) are unproven.")
    if space_problems:
        return (False, "CLX_SEARCH_SPACE_UNVERIFIABLE",
                f"the candidate is equivalent to the baseline, but the search "
                f"space that authorised the rewrite does not survive its own "
                f"citation audit ({len(space_problems)} problem(s), first: "
                f"{space_problems[0]}). A lever searched on a sentence that is "
                f"not there was not authorised.")
    return (True, "PASS",
            f"the candidate RTL is proven equivalent to the baseline RTL at "
            f"all {compared} compared point(s)"
            + (f", under a cited {offset}-cycle latency offset" if offset
               else ""))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Judge the rewrite-fidelity report (candidate RTL == "
                    "baseline RTL).")
    ap.add_argument("project_dir")
    ap.add_argument("--report", default=DEFAULT_REPORT_REL)
    ap.add_argument("--baseline-marker", default=DEFAULT_MARKER_REL)
    ap.add_argument("--search-space", default=DEFAULT_SPACE_REL,
                    help="The emitted cross-layer search space. When a search "
                         "ran, its citations are re-resolved against the "
                         "files on disk from here.")
    ap.add_argument("--json", default=DEFAULT_JSON_REL)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    marker = project / args.baseline_marker
    baseline_present = marker.exists()
    rp = project / args.report

    report: Optional[Dict] = None
    readable = rp.is_file()
    if readable:
        try:
            report = json.loads(rp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            report = None

    # A design that never ran a cross-layer search has no baseline snapshot and
    # no report, and this gate is simply not about it. Say so explicitly rather
    # than passing it silently — a reader must be able to tell "not applicable"
    # from "checked and clean".
    if not baseline_present and not readable:
        payload = {"program": PROGRAM, "status": "NOT_APPLICABLE",
                   "explanation": (
                       "no cross-layer baseline snapshot and no "
                       "rewrite-fidelity report — this design's RTL was not "
                       "produced by a cross-layer search, so there is no "
                       "rewrite to check."),
                   "baseline_marker": str(marker), "report": str(rp)}
        out = project / args.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"[{PROGRAM}] NOT_APPLICABLE — no cross-layer search was run.")
        return 0

    # Re-resolve the search space's citations. Delegated to the program that
    # emitted them so there is ONE audit, not a second weaker copy of it.
    space_problems: List[str] = []
    sp = project / args.search_space
    if sp.is_file():
        try:
            import crosslayer_search_space as _css
            space_problems = _css.audit_space(
                json.loads(sp.read_text(encoding="utf-8")))
        except Exception as exc:                     # noqa: BLE001
            space_problems = [f"the search space could not be audited: {exc}"]

    ok, status, why = judge(report, baseline_present=baseline_present,
                            report_readable=readable,
                            space_problems=space_problems)
    payload = {"program": PROGRAM, "status": status, "pass": ok,
               "explanation": why, "report": str(rp),
               "baseline_marker": str(marker),
               "baseline_present": baseline_present,
               "compared_points": (report or {}).get("compared_points"),
               "unproven_points": (report or {}).get("unproven_points"),
               "latency_offset_cycles": (report or {}).get(
                   "latency_offset_cycles"),
               "latency_freedom_evidence": (report or {}).get(
                   "latency_freedom_evidence"),
               "search_space": str(sp),
               "search_space_problems": space_problems}
    out = project / args.json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[{PROGRAM}] {status}: {why}", file=sys.stderr if not ok
          else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
