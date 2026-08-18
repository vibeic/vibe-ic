#!/usr/bin/env python3
"""sizing_adjust_policy.py — the fixed failure-mode → parameter-delta
lookup table from analog-sizing-loop (rule 5).

The skill's "Convergence strategy" table is a FIXED mapping from a
*named, already-identified* failure mode to a canonical sizing delta:

  | Failure mode        | Adjustment                         |
  |---------------------|------------------------------------|
  | gain_low            | +50% W on input pair               |
  | bandwidth_low       | -W (less parasitic C) / +Ibias     |
  | phase_margin_low    | +50% Cc                            |
  | noise_high          | +2x area (W*L) on input pair       |
  | power_high          | -30% Ibias                         |
  | output_swing_low    | +W at same Id (lower Vdsat)        |

The CAUSAL half — "which device is dominant", "is gain shortfall in
M1's gm or the load impedance", "is this a topology ceiling" — stays
in the skill as LLM judgment. THIS program only performs the
deterministic table lookup once the failure mode is named: given a
failure_mode string (and the current sizing point), it returns the
canonical multiplicative deltas to apply to the named parameters.

This makes the heuristic table machine-checkable and reproducible
instead of free-text prose the agent re-invents each session.

HONEST FAIL (NO vacuous PASS):
  * An UNKNOWN failure mode → exit 1 + UNKNOWN_FAILURE_MODE (the policy
    has no canonical fix; that's the LLM's cue to do real analysis or
    escalate to a topology change). It does NOT silently return "no
    change".
  * A delta that names a parameter ABSENT from the supplied --sizing
    point → exit 1 + PARAM_NOT_IN_SIZING (you asked to scale a knob the
    design doesn't expose).
  * Missing failure_mode argument → exit 2.

Usage:
    # list the canonical table
    python3 sizing_adjust_policy.py list
    python3 sizing_adjust_policy.py list --json out.json

    # propose a delta for a named failure mode
    python3 sizing_adjust_policy.py propose gain_low
    python3 sizing_adjust_policy.py propose power_high \
        --sizing '{"W_in":20.0,"Ibias":30.0,"Cc":2.0}' --json out.json

Exit codes:
    0 = a canonical delta was produced (and applied, if --sizing given)
    1 = FAIL (unknown failure mode, or delta param not in sizing)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional

# Canonical failure-mode → multiplicative parameter deltas.
# Each entry: param -> factor (factor>1 grows, <1 shrinks).
# Parameter names are the canonical loop knobs used by the skill's
# iterative_search SearchSpace (W_in, L_in, Ibias, Cc, area_in).
ADJUST_TABLE: Dict[str, Dict[str, float]] = {
    # Gain too low → +50% W on the input pair (more gm/Id).
    "gain_low": {"W_in": 1.5},
    # Bandwidth too low → shrink input W (less parasitic C) AND raise
    # the bias current (more gm → higher fT). Trades gain for BW.
    "bandwidth_low": {"W_in": 0.7, "Ibias": 1.3},
    # Phase margin too low → +50% compensation cap.
    "phase_margin_low": {"Cc": 1.5},
    # Noise too high → +2x area on the input devices (W*L product).
    "noise_high": {"area_in": 2.0},
    # Power too high → drop bias current 30%.
    "power_high": {"Ibias": 0.7},
    # Output swing too small → +W at the same Id to lower Vdsat.
    "output_swing_low": {"W_in": 1.4},
}

# Accept a few common aliases so callers needn't memorise exact keys.
ALIASES = {
    "gain": "gain_low", "low_gain": "gain_low",
    "bw_low": "bandwidth_low", "bw": "bandwidth_low", "bandwidth": "bandwidth_low",
    "pm_low": "phase_margin_low", "pm": "phase_margin_low",
    "phase_margin": "phase_margin_low",
    "noise": "noise_high",
    "power": "power_high", "high_power": "power_high",
    "swing_low": "output_swing_low", "swing": "output_swing_low",
    "output_swing": "output_swing_low",
}


def canonical_mode(mode: str) -> Optional[str]:
    key = str(mode).strip().lower()
    if key in ADJUST_TABLE:
        return key
    return ALIASES.get(key)


def cmd_list(args) -> int:
    report = {
        "program": "sizing_adjust_policy",
        "mode": "list",
        "table": ADJUST_TABLE,
        "aliases": ALIASES,
    }
    _emit(args, report)
    if not args.json:
        print("[INFO] sizing_adjust_policy canonical table:")
        for k, v in ADJUST_TABLE.items():
            print(f"  {k}: {v}")
    return 0


def cmd_propose(args) -> int:
    mode = canonical_mode(args.failure_mode)
    if mode is None:
        report = {
            "program": "sizing_adjust_policy", "mode": "propose",
            "passed": False, "failure_mode": args.failure_mode,
            "reason": "unknown_failure_mode",
            "known_modes": sorted(ADJUST_TABLE.keys()),
        }
        _emit(args, report)
        if not args.json:
            print(f"[FAIL] UNKNOWN_FAILURE_MODE: '{args.failure_mode}' has no "
                  f"canonical delta — needs LLM analysis / topology escalation",
                  file=sys.stderr)
        return 1

    delta = ADJUST_TABLE[mode]

    sizing = None
    if args.sizing:
        try:
            sizing = json.loads(args.sizing)
        except json.JSONDecodeError:
            print("ERROR: --sizing is not valid JSON", file=sys.stderr)
            return 2
        if not isinstance(sizing, dict):
            print("ERROR: --sizing must be a JSON object", file=sys.stderr)
            return 2

    new_sizing = None
    if sizing is not None:
        missing = [p for p in delta if p not in sizing]
        if missing:
            report = {
                "program": "sizing_adjust_policy", "mode": "propose",
                "passed": False, "failure_mode": mode, "delta": delta,
                "reason": "param_not_in_sizing", "missing_params": missing,
                "sizing_keys": sorted(sizing.keys()),
            }
            _emit(args, report)
            if not args.json:
                print(f"[FAIL] PARAM_NOT_IN_SIZING: delta touches {missing} "
                      f"not present in --sizing {sorted(sizing.keys())}",
                      file=sys.stderr)
            return 1
        new_sizing = dict(sizing)
        for p, factor in delta.items():
            if isinstance(new_sizing[p], (int, float)):
                new_sizing[p] = round(float(new_sizing[p]) * factor, 6)

    report = {
        "program": "sizing_adjust_policy", "mode": "propose",
        "passed": True, "failure_mode": mode, "delta": delta,
        "applied": sizing is not None, "new_sizing": new_sizing,
    }
    _emit(args, report)
    if not args.json:
        print(f"[PASS] {mode} → delta {delta}"
              + (f"  new_sizing={new_sizing}" if new_sizing else ""))
    return 0


def _emit(args, report: dict) -> None:
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                               ensure_ascii=False))


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="print the canonical adjust table")
    p_list.add_argument("--json", default=None)
    p_list.set_defaults(func=cmd_list)

    p_prop = sub.add_parser("propose", help="propose a delta for a failure mode")
    p_prop.add_argument("failure_mode")
    p_prop.add_argument("--sizing", default=None,
                        help="current sizing as JSON object to apply delta to")
    p_prop.add_argument("--json", default=None)
    p_prop.set_defaults(func=cmd_propose)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
