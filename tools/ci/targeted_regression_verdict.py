#!/usr/bin/env python3
"""Decide a landing's targeted arm by REGRESSION, not by absolute greenness.

THE QUESTION A LANDING ASKS
===========================
"Did this change break something that used to work." Not "is the tree entirely
green". Those are different questions and only the first is a landing's.

WHY THIS FILE EXISTS (measured, 2026-08-18)
===========================================
tools/git-hooks/pre-push refuses any push to main whose commit lacks a passing
gatekeeper-land stamp, and gatekeeper-land judged the targeted arm ABSOLUTELY: any
red, no stamp. Clean origin/main ITSELF carried red tests. So no commit could reach
main -- INCLUDING a commit that fixes those reds. Five observed rounds, ~2.5 hours
of gate wall clock, zero landings.

Meanwhile changes DID reach main, through the PR path, which GitHub merges
server-side where no local hook runs. So the only path that honoured the gate was
unusable and the usable path never ran it. That is how the reds accumulated.

The sibling script already had the right rule and said so:
    gatekeeper-verify-merge.sh:116  "candidate is judged on WHAT IT BREAKS"
    gatekeeper-land.sh:538          "the differential still has to decide whether
                                     they were pre-existing"
-- but that differential lived only in verify-merge, so the direct-push path never
performed it. This file performs it.

THE RULE
========
    NEW      = candidate failures - base failures     -> a REGRESSION, refuse
    INHERITED= candidate failures & base failures     -> report by name, do not refuse
    FIXED    = base failures - candidate failures     -> report; this is the point

A landing passes when NEW is empty. INHERITED is printed in full, every time: a
permanent red that stops being mentioned is how it becomes invisible, and this
change must not buy silence with leniency.

WHAT IS NOT DECIDED HERE
========================
Only the targeted TEST arm. Whole-tree gates -- NDA tokens, version monotonicity,
collateral revert, corpus writes -- stay ABSOLUTE, because inheriting a violation
is not a licence to add one and for several of them any occurrence at all is
disqualifying. verify-merge draws that same line (:851) and this file does not
move it.

FAILURE MODES THAT MUST NOT BUY LENIENCY
========================================
Every one of these returns REFUSE, not pass:
  * the base arm produced no readable record       -> we cannot know what is new
  * the base junit is missing, empty, unparseable  -> same
  * the base run was TRUNCATED (--maxfail)         -> a truncated base has no
    failure SET, only a prefix of one, and a new failure hiding past the cut would
    read as pre-existing. verify-merge:737 forbids --maxfail on the base arm for
    exactly this reason.
Unknown must never be cheaper than red.

Usage:
    targeted_regression_verdict.py --candidate CAND.xml --base BASE.xml
                                   [--base-truncated] [--json OUT]
Exit:
    0  no new failure -- the change breaks nothing that used to work
    1  a NEW failure: this change is a regression
    2  NOT DETERMINED -- could not compare. Never a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional, Set, Tuple


def _case_id(tc) -> str:
    """The identity two arms are compared on.

    classname::name, with the aggregate wrapper's own process record excluded by the
    caller. NOT the file path: the same test can be reported under a different file
    attribute by the per-file driver and by the aggregate session, and comparing on
    that would make every case look new.
    """
    return f"{tc.get('classname') or ''}::{tc.get('name') or ''}"


#: The driver records its own OS exit as a testcase so a session that died is not
#: mistaken for a clean one. It is not a test, and including it would make every
#: red round look like it had one extra failure in both arms.
_PROCESS_RECORDS = ("process_exit",)


def read_failures(path: Path) -> Tuple[Optional[Set[str]], Optional[str]]:
    """(failures, None) or (None, reason). NONE IS 'COULD NOT READ', NOT 'NO FAILURES'."""
    if not path.is_file():
        return None, f"{path} does not exist"
    if path.stat().st_size == 0:
        return None, f"{path} is empty"
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:                                    # noqa: BLE001
        return None, f"{path} is not parseable: {type(exc).__name__}: {exc}"
    total = 0
    bad: Set[str] = set()
    for tc in root.iter("testcase"):
        if (tc.get("name") or "") in _PROCESS_RECORDS:
            continue
        total += 1
        if any(c.tag in ("failure", "error") for c in tc):
            bad.add(_case_id(tc))
    if total == 0:
        # A junit with no testcases is not a green run; it is a run that recorded
        # nothing, which is exactly the NORECORD shape the driver exists to catch.
        return None, f"{path} contains zero testcases — nothing was recorded"
    return bad, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--base-truncated", action="store_true",
                    help="the base arm stopped early (--maxfail); its failure set is "
                         "a prefix, so no comparison is sound")
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    if a.base_truncated:
        print("[NOT DETERMINED] the base arm was TRUNCATED, so its failure set is a "
              "prefix and a new failure past the cut would read as pre-existing. "
              "Re-run the base arm without --maxfail.", file=sys.stderr)
        return 2

    cand, cerr = read_failures(Path(a.candidate))
    base, berr = read_failures(Path(a.base))
    if cerr:
        print(f"[NOT DETERMINED] candidate arm unreadable: {cerr}", file=sys.stderr)
        return 2
    if berr:
        print(f"[NOT DETERMINED] base arm unreadable: {berr}\n"
              "  Without the base there is no way to tell a regression from an "
              "inherited red, and unknown must never be cheaper than red.",
              file=sys.stderr)
        return 2

    new = sorted(cand - base)
    inherited = sorted(cand & base)
    fixed = sorted(base - cand)

    rec: Dict[str, object] = {
        "new": new, "inherited": inherited, "fixed": fixed,
        "candidate_failures": len(cand), "base_failures": len(base),
    }
    if a.json:
        Path(a.json).write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")

    # INHERITED IS ALWAYS PRINTED IN FULL. A permanent red that stops being
    # mentioned is how it becomes invisible, and this rule must not buy silence.
    if inherited:
        print(f"  INHERITED — already red at the base, NOT this change's "
              f"({len(inherited)}):")
        for c in inherited:
            print(f"      {c}")
    if fixed:
        print(f"  FIXED by this change ({len(fixed)}):")
        for c in fixed:
            print(f"      {c}")

    if new:
        print(f"[FAIL] {len(new)} NEW failure(s) — this change breaks what used to "
              f"work:")
        for c in new:
            print(f"      {c}")
        return 1

    print(f"[PASS] no new failure: {len(cand)} red at the candidate, all {len(inherited)} "
          f"of them already red at the base"
          + (f"; {len(fixed)} fixed" if fixed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
