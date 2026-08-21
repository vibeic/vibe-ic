#!/usr/bin/env python3
"""perc_signoff_check.py — Step 28 PERC / reliability sign-off gate
(v2.3 flow-completeness review).

The runner's deterministic PERC-equivalent aggregate
(`reports/phase3/perc_equivalent.json`) already computes the
Calibre-PERC-class categories — ESD pad-ring presence, ESD discharge
topology, latch-up well-tap coverage, cross-voltage-domain protection,
plus the AUTOMATED antenna/IR/EM/floating-net verdicts — but its
conclusive FAILs previously lived only in a memo. This gate makes them
ENFORCED:

  * any AUTOMATED category with result=FAIL  → exit 1 (conclusive
    reliability defect — ESD ring/topology gap, well-tap gap,
    unprotected cross-domain crossing, antenna/IR over budget …)
  * AUTOMATED INCOMPLETE and MANUAL_REVIEW categories are NAMED open
    items (exit 0, verdict PASS_WITH_OPEN_ITEMS) — capability-tier
    measurements (e.g. EM MEASURED) and foundry device-physics sizing
    are review work, not fabricate-a-FAIL material;
  * everything conclusive PASS → exit 0 PASS.

Exit codes: 0 PASS / PASS_WITH_OPEN_ITEMS, 1 FAIL, 2 no
perc_equivalent.json yet (vacuous — run phase3 sign-off first).
chip-AGNOSTIC: consumes only the aggregate's structural fields.

THE HUMAN-READABLE HALF (what this gate used to ignore)
-------------------------------------------------------
Step 28 declares THREE artefacts::

    reports/phase3/perc_equivalent.json
    reports/phase3/perc_equivalent.rpt
    reports/phase3/PERC_SIGNOFF_MEMO.md

`phase3_one_shot_runner._emit_perc_equivalent` writes all three from ONE
summary, and the memo is the artefact a reviewer actually signs at tapeout
(the flow's step table lists step 28's outputs as "perc_equivalent.json ·
PERC memo · gate verdict"). This gate opened the JSON only, so the two
human-readable projections could say anything at all and the step still
signed off. Measured: a memo whose `**Overall verdict:** \\`PASS\\`` line was
edited to contradict a JSON carrying a conclusive ESD `FAIL` produced rc=1 on
the JSON alone — but a memo that simply DROPPED the failing category's row,
or a stale memo left over from the previous run stating `PASS`, was invisible.

The three are now cross-checked, CONTRADICTION-first:

  * a projection that states an overall verdict different from the JSON's is
    an ERROR — the machine record and the signed record disagree;
  * a category the JSON reports as AUTOMATED/FAIL that is NOT named in a
    projection is an ERROR — the conclusive defect is missing from the
    document a human signs;
  * a projection that is ABSENT is DISCLOSED (a named finding in the report,
    not a blocking one): step 28's `required_outputs` is ALL-of-N and already
    reports a missing declared artefact, so this gate states the gap rather
    than double-failing it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

#: The human-readable projections step 28 declares, exactly as the flow yaml
#: spells them, paired with the regex that extracts the verdict each states.
#: `_emit_perc_equivalent` writes `OVERALL VERDICT: <v>` into the .rpt and
#: `**Overall verdict:** \`<v>\`` into the memo.
PROJECTIONS: Tuple[Tuple[str, str], ...] = (
    ("reports/phase3/perc_equivalent.rpt",
     r"^OVERALL\s+VERDICT:\s*(\S+)\s*$"),
    ("reports/phase3/PERC_SIGNOFF_MEMO.md",
     r"^\*\*Overall verdict:\*\*\s*`([^`]+)`"),
)


def _stated_verdict(text: str, pattern: str) -> Optional[str]:
    hit = re.search(pattern, text, re.MULTILINE)
    return hit.group(1).strip() if hit else None


def cross_check_projections(project: Path,
                            summary: Dict[str, Any]) -> Tuple[
                                List[str], List[str]]:
    """``(errors, disclosures)`` comparing the two declared projections.

    ``summary`` is the parsed ``perc_equivalent.json``. Only an explicit
    disagreement is an error; a projection that states no verdict at all is
    disclosed, never guessed at.
    """
    errors: List[str] = []
    disclosures: List[str] = []
    json_verdict = summary.get("verdict")
    conclusive_failed = [
        str(c.get("category"))
        for c in (summary.get("categories") or [])
        if isinstance(c, dict)
        and c.get("status") == "AUTOMATED" and c.get("result") == "FAIL"
    ]

    for rel, pattern in PROJECTIONS:
        path = project / rel
        if not path.is_file():
            disclosures.append(
                f"{rel} (declared by step 28) is absent — the machine verdict "
                f"in perc_equivalent.json is uncorroborated by the "
                f"human-readable sign-off record")
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            errors.append(f"{rel} unreadable: {exc}")
            continue
        stated = _stated_verdict(text, pattern)
        if stated is None:
            disclosures.append(
                f"{rel} states no overall verdict line — cannot be compared "
                f"with perc_equivalent.json's {json_verdict!r}")
        elif json_verdict is not None and stated != str(json_verdict):
            errors.append(
                f"{rel} states overall verdict {stated!r} but "
                f"perc_equivalent.json states {str(json_verdict)!r} — the "
                f"signed record contradicts the machine record")
        for cat in conclusive_failed:
            if cat and cat not in text:
                errors.append(
                    f"{rel} does not name the conclusive AUTOMATED FAIL "
                    f"{cat!r} that perc_equivalent.json reports — a "
                    f"reliability defect missing from the document a human "
                    f"signs")
    return errors, disclosures


def audit(project: Path) -> dict:
    src = project / "reports" / "phase3" / "perc_equivalent.json"
    if not src.is_file():
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("reports/phase3/perc_equivalent.json absent — "
                           "run the phase3 sign-off chain first")}
    try:
        data = json.loads(src.read_text(errors="replace"))
    except (OSError, ValueError):
        return {"verdict": "FAIL", "rc": 1,
                "reason": "perc_equivalent.json unparseable"}

    cats = data.get("categories") or []
    automated = [c for c in cats if isinstance(c, dict)
                 and c.get("status") == "AUTOMATED"]
    failed = [c for c in automated if c.get("result") == "FAIL"]
    incomplete = [c for c in automated if c.get("result") == "INCOMPLETE"]
    manual = [c for c in cats if isinstance(c, dict)
              and c.get("status") == "MANUAL_REVIEW"]
    open_items = ([f"INCOMPLETE: {c.get('category')}" for c in incomplete]
                  + [f"MANUAL_REVIEW: {c.get('category')}" for c in manual])

    proj_errors, proj_disclosures = cross_check_projections(project, data)

    rep = {
        "source": "reports/phase3/perc_equivalent.json",
        "source_verdict": data.get("verdict"),
        "automated_total": len(automated),
        "automated_failed": [c.get("category") for c in failed],
        "open_items": open_items,
        "projections_checked": [rel for rel, _ in PROJECTIONS],
        "projection_contradictions": proj_errors,
        "projection_disclosures": proj_disclosures,
    }
    # A conclusive reliability defect is reported FIRST when both are present:
    # a contradicted memo is a bookkeeping failure, a failed ESD / latch-up
    # category is a silicon one. Both appear in the report either way, and
    # both produce rc=1.
    if failed:
        reason = ("conclusive PERC reliability defect(s): "
                  + "; ".join(
                      f"{c.get('category')}: "
                      f"{str(c.get('note') or c.get('source_verdict') or '')[:120]}"
                      for c in failed))
        if proj_errors:
            reason += ("; ALSO, the declared human-readable sign-off "
                       "artefact(s) contradict perc_equivalent.json: "
                       + "; ".join(proj_errors))
        rep.update(verdict="FAIL", rc=1, reason=reason)
    elif proj_errors:
        rep.update(verdict="FAIL", rc=1, reason=(
            "no conclusive reliability defect in perc_equivalent.json, but the "
            "declared human-readable PERC sign-off artefact(s) contradict it, "
            "so the machine record and the signed record cannot both be "
            "trusted: " + "; ".join(proj_errors)))
    elif not automated:
        # "ALL AUTOMATED CATEGORIES CONCLUSIVE PASS" OVER ZERO OF THEM (#1115).
        #
        # `perc_equivalent.json` is PRESENT and carries no AUTOMATED category,
        # so the producer ran and emitted nothing to judge. Every branch above
        # is empty by construction -- no FAIL, no INCOMPLETE, no contradiction
        # -- and the tail landed on the sentence "all AUTOMATED PERC categories
        # conclusive PASS" with `automated_total: 0` sitting in the same report.
        # That is LibreLane's `klayout.py:486-490` shape: the producer emits
        # nothing and the checker reads the absence as consent.
        #
        # rc 2, NOT rc 0, and NOT a new convention: this gate ALREADY answers
        # rc 2 / SKIP when `perc_equivalent.json` is absent. A file that is
        # present and carries zero categories is the same epistemic state --
        # nothing to judge -- so it gets the same answer. A project with no
        # PERC run was already rc 2 by the branch above, so this reddens
        # nothing that was green.
        #
        # The projection disclosures ride along, because they were computed and
        # then dropped: they lived in the report dict and never reached the
        # verdict line a reader sees.
        why = ("perc_equivalent.json is present but declares 0 AUTOMATED PERC "
               "categor(ies) — there is nothing to judge, so this is NOT "
               "'all categories conclusive PASS'")
        if proj_disclosures:
            why += "; " + "; ".join(proj_disclosures)
        rep.update(verdict="VACUOUS_PASS", rc=2, reason=why)
    elif open_items:
        rep.update(verdict="PASS_WITH_OPEN_ITEMS", rc=0, reason=(
            f"no conclusive reliability defect; {len(open_items)} named "
            f"open item(s) pending review before tapeout"))
    else:
        # The disclosures are named HERE too. They were computed, stored in the
        # report and never surfaced in the sentence that decides how a reader
        # feels about this gate -- "cannot be compared with
        # perc_equivalent.json's None" is not a detail, it is the reason the
        # corroboration this gate exists for did not happen.
        reason = (f"all {len(automated)} AUTOMATED PERC categor(ies) "
                  f"conclusive PASS")
        if proj_disclosures:
            reason += ("; UNCORROBORATED: " + "; ".join(proj_disclosures))
        rep.update(verdict="PASS", rc=0, reason=reason)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    rep = {"program": "perc_signoff_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)
    print(out)
    if rep.get("verdict") == "VACUOUS_PASS":
        # `flow_compliance_check._stdout_signals_vacuous` matches this prefix at
        # line start. The JSON above carries the same fact and no consumer
        # reads it.
        print(f"VACUOUS_PASS: {rep.get('reason')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
