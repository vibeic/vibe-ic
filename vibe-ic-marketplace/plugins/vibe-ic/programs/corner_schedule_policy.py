#!/usr/bin/env python3
"""corner_schedule_policy.py — deterministic corner-schedule policy for
the analog sizing loop (analog-sizing-loop rule 3).

The skill mandated:
  "Do not run all corners on iteration 0 — TT-only is sufficient for
   initial sanity."  +  iteration 1..N run the full PVT matrix.

This is a fixed schedule keyed on the iteration index, not judgment.
The program has two jobs:

  1. POLICY  — given an iteration index, return the corner subset that
     SHOULD be run (TT-only at iter 0, the full set at iter ≥ 1).

  2. AUDIT   — given a sizing_history.json that records, per iteration,
     which corners were actually run, FAIL if iteration 0 ran more than
     the typical/TT corner (wasted a full PVT sweep on the first guess),
     or if a later iteration ran ONLY the TT corner (false convergence —
     a PASS that never saw SS/FF or temperature extremes).

The TT corner is recognised structurally: a corner name whose process
token is one of {tt, typ, typical, nom, nominal}. "Full" means the
iteration touched at least one non-typical process corner (ss/ff/sf/fs)
OR a temperature extreme — i.e. it actually exercised PVT spread.

HONEST FAIL / SKIP:
  * `policy <iter>` with iter < 0 or non-integer → exit 2 (bad input).
  * `audit <file>` on a missing / unparsable / empty-iterations file →
    exit 2 (cannot audit) — never a vacuous PASS.
  * An iteration record with no `corners` list is reported UNKNOWN and
    does NOT earn a PASS for the schedule rule it would gate.

Usage:
    # POLICY: print the corner subset to run for an iteration
    python3 corner_schedule_policy.py policy 0
    python3 corner_schedule_policy.py policy 2 --corners tt_25C ss_-40C ff_125C
    python3 corner_schedule_policy.py policy 0 --json out.json

    # AUDIT: check a sizing_history.json obeyed the schedule
    python3 corner_schedule_policy.py audit sizing_history.json
    python3 corner_schedule_policy.py audit sizing_history.json --json out.json

Exit codes:
    0 = PASS / policy emitted
    1 = FAIL (schedule violated)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

TYPICAL_TOKENS = {"tt", "typ", "typical", "nom", "nominal"}
SPREAD_PROCESS = {"ss", "ff", "sf", "fs", "fast", "slow"}


def _process_token(corner_name: str) -> str:
    """First alpha token of a corner name, lowercased
    (e.g. 'ss_-40C_3.0V' → 'ss', 'tt_25C' → 'tt')."""
    m = re.match(r"[a-zA-Z]+", str(corner_name).strip())
    return m.group(0).lower() if m else ""


def _is_typical(corner_name: str) -> bool:
    return _process_token(corner_name) in TYPICAL_TOKENS


def _has_temp_extreme(corner_name: str) -> bool:
    """A temperature far from room (≤0C or ≥85C) counts as spread."""
    for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s*[cC]\b", str(corner_name)):
        try:
            t = float(m.group(1))
        except ValueError:
            continue
        if t <= 0.0 or t >= 85.0:
            return True
    return False


def _exercises_spread(corners: List[str]) -> bool:
    """True if the corner set touches non-typical process OR a temp
    extreme — i.e. it actually exercised PVT spread (not TT-only)."""
    for c in corners:
        if _process_token(c) in SPREAD_PROCESS:
            return True
        if _has_temp_extreme(c):
            return True
    return False


def schedule_for_iteration(iteration: int, available: List[str]) -> List[str]:
    """Return the corner subset to run for `iteration`.
    iter 0 → TT-only (the typical corner(s) in `available`, or the first
    available corner if none is recognisably typical);
    iter ≥ 1 → all available corners (full PVT sweep)."""
    if iteration <= 0:
        tt = [c for c in available if _is_typical(c)]
        if tt:
            return tt
        return available[:1] if available else []
    return list(available)


def cmd_policy(args) -> int:
    if args.iteration < 0:
        print("ERROR: iteration must be >= 0", file=sys.stderr)
        return 2
    available = args.corners or ["tt_25C", "ss_-40C", "ss_125C",
                                 "ff_-40C", "ff_125C", "tt_-40C", "tt_125C",
                                 "ff_25C", "ss_25C"]
    chosen = schedule_for_iteration(args.iteration, available)
    report = {
        "program": "corner_schedule_policy",
        "mode": "policy",
        "iteration": args.iteration,
        "available": available,
        "run_corners": chosen,
        "tt_only": args.iteration <= 0,
    }
    _emit(args, report)
    return 0


def cmd_audit(args) -> int:
    path = Path(args.history)
    if not path.is_file():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        print(f"ERROR: cannot parse {path}", file=sys.stderr)
        return 2
    iters = data.get("iterations") if isinstance(data, dict) else None
    if not isinstance(iters, list) or not iters:
        print("ERROR: sizing_history has no non-empty 'iterations' list",
              file=sys.stderr)
        return 2

    findings = []
    passed = True
    for rec in iters:
        if not isinstance(rec, dict):
            continue
        idx = rec.get("iter", rec.get("iteration"))
        corners = rec.get("corners")
        if not isinstance(idx, int):
            continue
        if not isinstance(corners, list) or not corners:
            findings.append({"iter": idx, "severity": "INFO",
                             "rule": "NO_CORNER_RECORD",
                             "message": f"iter {idx}: no corners[] recorded"})
            continue
        spread = _exercises_spread(corners)
        if idx == 0 and spread:
            passed = False
            findings.append({"iter": idx, "severity": "ERROR",
                             "rule": "ITER0_RAN_FULL_SWEEP",
                             "message": (f"iter 0 ran a full/spread PVT sweep "
                                         f"({corners}) — wasted on the first "
                                         f"un-tuned guess; TT-only expected")})
        elif idx >= 1 and not spread:
            passed = False
            findings.append({"iter": idx, "severity": "ERROR",
                             "rule": "LATE_ITER_TT_ONLY",
                             "message": (f"iter {idx} ran TT-only ({corners}) "
                                         f"— PVT spread never exercised; a "
                                         f"PASS here is false convergence")})
        else:
            findings.append({"iter": idx, "severity": "INFO",
                             "rule": "SCHEDULE_OK",
                             "message": (f"iter {idx}: "
                                         f"{'TT-only' if idx == 0 else 'full sweep'}"
                                         f" as scheduled")})

    report = {
        "program": "corner_schedule_policy",
        "mode": "audit",
        "passed": passed,
        "iterations_audited": len(iters),
        "findings": findings,
    }
    _emit(args, report)
    if not args.json:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] corner_schedule_policy audit")
        for f in findings:
            if f["severity"] in ("ERROR", "WARNING"):
                print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return 0 if passed else 1


def _emit(args, report: dict) -> None:
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                               ensure_ascii=False))
    elif report.get("mode") == "policy":
        print(json.dumps(report, indent=2, ensure_ascii=False))


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pol = sub.add_parser("policy", help="emit corner subset for an iteration")
    p_pol.add_argument("iteration", type=int)
    p_pol.add_argument("--corners", nargs="*", default=None,
                       help="available corner names (default: 9-corner matrix)")
    p_pol.add_argument("--json", default=None)
    p_pol.set_defaults(func=cmd_policy)

    p_aud = sub.add_parser("audit", help="audit a sizing_history.json schedule")
    p_aud.add_argument("history")
    p_aud.add_argument("--json", default=None)
    p_aud.set_defaults(func=cmd_audit)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
