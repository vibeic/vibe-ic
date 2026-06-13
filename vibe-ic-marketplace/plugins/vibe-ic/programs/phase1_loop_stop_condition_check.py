#!/usr/bin/env python3
"""
phase1_loop_stop_condition_check.py — deterministic STOP gate for the
phase1-coverage-loop field-agent.

Extracted from skills/phase1-coverage-loop/SKILL.md "STOP CONDITION".
The loop must terminate (CronDelete) iff ALL THREE of the following
deterministic facts hold:

  (1) rotation_passes_completed >= 2
      Every IC has been audited at least twice — first pass to find
      gaps, second pass to confirm fixes landed.

  (2) zero OPEN `ORGANIC-phase1-*` issues
      `gh issue list --search "ORGANIC-phase1 in:title" --state open`
      returns empty. The loop CANNOT compute this itself (network);
      the caller runs the gh query and passes the count via
      --open-organic-issues N. N==0 satisfies the clause.

  (3) last full rotation's per-IC verdict is PASS or SKIP for EVERY IC
      Any FAIL or WARN in the last rotation's verdict map blocks STOP.
      Verdicts that count as "clean": PASS, SKIP, SKIP_REFERENCE,
      SKIP_LOW_TOKENS (the SKIP family from the completeness gate).

The program reads the loop state JSON (the
`_field_agent_phase1_state.json` schema) for facts (1) and (3), and
takes fact (2) as an argument so it stays a pure, network-free, unit-
testable boolean.

Usage
-----
    python3 phase1_loop_stop_condition_check.py \
        --state <state.json> --open-organic-issues N [--json <out>]

Exit codes
----------
    0  STOP  — all three clauses satisfied (loop should CronDelete)
    1  CONTINUE — at least one clause unsatisfied (loop keeps running)
    2  usage / input error (missing or unparseable state file, or a
       negative issue count)

This is intentionally NOT a PASS/FAIL gate — STOP and CONTINUE are both
"healthy" outcomes. exit 1 means "keep looping", exit 0 means "done".
A missing/garbage state file is an honest exit-2 error (we cannot
decide to STOP a loop whose state we cannot read).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List


_MIN_PASSES = 2
# Verdicts that do NOT block STOP.
_CLEAN_VERDICTS = {
    "PASS",
    "SKIP",
    "SKIP_REFERENCE",
    "SKIP_LOW_TOKENS",
}


def evaluate(state: dict, open_organic_issues: int) -> dict:
    """Pure boolean evaluation of the three STOP clauses.

    Returns a report dict with `stop` (bool) and the three clause
    results + the blocking reasons."""
    passes = state.get("rotation_passes_completed", 0)
    try:
        passes = int(passes)
    except (TypeError, ValueError):
        passes = -1

    per_ic = state.get("per_ic_last_verdict", {})
    if not isinstance(per_ic, dict):
        per_ic = {}

    clause1 = passes >= _MIN_PASSES
    clause2 = open_organic_issues == 0
    # clause3: empty verdict map is NOT clean — we have never recorded a
    # full clean rotation, so we must not STOP.
    dirty = {ic: v for ic, v in per_ic.items()
             if str(v).upper() not in _CLEAN_VERDICTS}
    clause3 = bool(per_ic) and not dirty

    reasons: List[str] = []
    if not clause1:
        reasons.append(
            f"rotation_passes_completed={passes} < {_MIN_PASSES}")
    if not clause2:
        reasons.append(
            f"{open_organic_issues} OPEN ORGANIC-phase1 issue(s) remain")
    if not clause3:
        if not per_ic:
            reasons.append("no per-IC verdicts recorded yet")
        else:
            reasons.append(
                "last rotation has non-clean verdict(s): "
                + ", ".join(f"{ic}={v}" for ic, v in sorted(dirty.items())))

    stop = clause1 and clause2 and clause3
    return {
        "gate": "phase1_loop_stop_condition_check",
        "stop": stop,
        "decision": "STOP" if stop else "CONTINUE",
        "clause1_passes_ge_2": clause1,
        "clause2_no_open_issues": clause2,
        "clause3_all_clean": clause3,
        "rotation_passes_completed": passes,
        "open_organic_issues": open_organic_issues,
        "dirty_verdicts": dirty,
        "blocking_reasons": reasons,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic STOP-condition boolean for the "
                    "phase1-coverage-loop.")
    parser.add_argument("--state", required=True,
                        help="Path to _field_agent_phase1_state.json.")
    parser.add_argument("--open-organic-issues", type=int, required=True,
                        dest="open_organic_issues",
                        help="Count from `gh issue list --search "
                             "\"ORGANIC-phase1 in:title\" --state open`.")
    parser.add_argument("--json", default=None,
                        help="Write the JSON report here.")
    args = parser.parse_args(argv)

    if args.open_organic_issues < 0:
        print(f"ERROR — open-organic-issues must be >=0 "
              f"(got {args.open_organic_issues}).")
        return 2

    state_path = Path(args.state)
    if not state_path.is_file():
        print(f"ERROR — state file not found: {state_path}")
        return 2
    try:
        state = json.loads(state_path.read_text(errors="replace"))
    except Exception as e:  # noqa: BLE001
        print(f"ERROR — could not parse state file: {e}")
        return 2
    if not isinstance(state, dict):
        print("ERROR — state file is not a JSON object.")
        return 2

    report = evaluate(state, args.open_organic_issues)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))

    if report["stop"]:
        print("STOP — all three clauses satisfied "
              f"(passes={report['rotation_passes_completed']}, "
              f"open_issues={report['open_organic_issues']}, "
              "last rotation all clean).")
        return 0
    print("CONTINUE — " + "; ".join(report["blocking_reasons"]))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
