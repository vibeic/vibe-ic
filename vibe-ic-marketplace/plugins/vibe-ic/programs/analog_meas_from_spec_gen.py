#!/usr/bin/env python3
"""analog_meas_from_spec_gen.py — deterministic `.meas` statement generator
from an analog block spec.json.

Rule (from skill `analog-netlist-gen`):
    Each spec key maps to a templated ngspice `.meas` line:
      * a DC operating-point spec (vout_dc, vref, ...)  -> `.meas DC ...`
      * a small-signal AC spec (gain_db, ugbw, pm, ...)  -> `.meas AC  ...`
      * a transient timing spec (tpd, tr, tf, slew, ...) -> `.meas TRAN ...`
    Given spec.json this is DETERMINISTIC template emission, not authoring.

This program reads `<block>/spec.json` and emits the corresponding `.meas`
deck to stdout (or --out). It is a GENERATOR, so its "PASS" (exit 0) means
"emitted >= 1 .meas line from real spec keys"; it FAILs honestly when the
spec is missing/garbage/has no recognizable measurable keys.

Spec key classification (case-insensitive substring / suffix):
    DC   : '_dc', 'vout', 'vref', 'vbias', 'iq', 'idd', 'idd_', 'pwr_dc'
    AC   : 'gain', 'ugbw', 'gbw', 'bw', 'pm', 'phase_margin', 'gm', 'psrr',
           'cmrr', 'db'
    TRAN : 'tpd', 'tr', 'tf', 'slew', 'settling', 'rise', 'fall', 'jitter',
           'period', 'tphl', 'tplh'

Each spec value may be a bare number or {"value":.., "unit":..}; the value is
informational (emitted as a trailing comment) — the .meas line itself does
not need the target value to be a valid measurement extraction.

Honest-FAIL guarantees:
  * missing spec.json                       -> exit 1, no output
  * spec.json that is not valid JSON        -> exit 2
  * spec.json with no measurable keys       -> exit 1 (NO_MEASURABLE_KEYS)
  * a valid spec with >=1 measurable key    -> exit 0 + emitted deck

Usage:
    python3 analog_meas_from_spec_gen.py <spec.json>
    python3 analog_meas_from_spec_gen.py <spec.json> --out meas.inc
    python3 analog_meas_from_spec_gen.py <spec.json> --json report.json

Exit codes:
    0 = PASS (>=1 .meas line emitted)
    1 = FAIL (missing spec / no measurable keys)
    2 = IO / parse error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

GATE = "analog_meas_from_spec_gen"

DC_TOKENS = ("_dc", "vout", "vref", "vbias", "iq", "idd", "pwr_dc", "vop")
AC_TOKENS = ("gain", "ugbw", "gbw", "_bw", "bandwidth", "pm", "phase_margin",
             "gm", "psrr", "cmrr", "_db", "gain_db")
TRAN_TOKENS = ("tpd", "_tr", "_tf", "slew", "settling", "rise", "fall",
               "jitter", "period", "tphl", "tplh", "delay")


def _classify(key: str) -> Optional[str]:
    k = key.lower()
    # TRAN first (timing keys are most specific), then AC, then DC.
    if any(t in k for t in TRAN_TOKENS):
        return "TRAN"
    if any(t in k for t in AC_TOKENS):
        return "AC"
    if any(t in k for t in DC_TOKENS):
        return "DC"
    return None


def _value_comment(val) -> str:
    if isinstance(val, dict):
        v = val.get("value")
        u = val.get("unit", "")
        if v is not None:
            return f"  $ target={v}{u}"
        return ""
    if isinstance(val, (int, float, str)):
        return f"  $ target={val}"
    return ""


def _emit_line(key: str, kind: str, val) -> str:
    comment = _value_comment(val)
    if kind == "DC":
        return f".meas DC {key} FIND V(vout) AT=last{comment}"
    if kind == "AC":
        if "pm" in key.lower() or "phase" in key.lower():
            return f".meas AC {key} FIND VP(vout) WHEN VDB(vout)=0{comment}"
        return f".meas AC {key} FIND VDB(vout) AT=1k{comment}"
    # TRAN
    return (f".meas TRAN {key} TRIG V(in) VAL=vmid RISE=1 "
            f"TARG V(out) VAL=vmid FALL=1{comment}")


def generate(spec: dict) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return (deck_lines, [(key, kind)...]) for the measurable keys."""
    lines: List[str] = ["* auto-generated .meas deck from spec.json"]
    emitted: List[Tuple[str, str]] = []
    # spec may nest measurable values under a 'specs'/'targets' object.
    candidates = {}
    for container in (spec, spec.get("specs"), spec.get("targets")):
        if isinstance(container, dict):
            candidates.update(container)
    for key in sorted(candidates):
        if key in ("specs", "targets"):
            continue
        kind = _classify(key)
        if kind is None:
            continue
        lines.append(_emit_line(key, kind, candidates[key]))
        emitted.append((key, kind))
    return lines, emitted


def run(spec_path: Path) -> Tuple[int, dict, str]:
    if not spec_path.is_file():
        return 1, {"pass": False, "reason": "spec_missing",
                   "spec": str(spec_path)}, ""
    try:
        raw = spec_path.read_text(encoding="utf-8", errors="replace")
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        return 2, {"pass": False, "reason": f"json_error: {exc}",
                   "spec": str(spec_path)}, ""
    except OSError as exc:
        return 2, {"pass": False, "reason": f"io_error: {exc}",
                   "spec": str(spec_path)}, ""
    if not isinstance(spec, dict):
        return 2, {"pass": False, "reason": "spec_not_object",
                   "spec": str(spec_path)}, ""

    deck_lines, emitted = generate(spec)
    if not emitted:
        return 1, {"pass": False, "reason": "no_measurable_keys",
                   "spec": str(spec_path), "meas_lines": 0}, ""

    deck = "\n".join(deck_lines) + "\n"
    summary = {
        "pass": True,
        "spec": str(spec_path),
        "meas_lines": len(emitted),
        "emitted": [{"key": k, "kind": kind} for k, kind in emitted],
    }
    return 0, summary, deck


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, help="path to <block>/spec.json")
    ap.add_argument("--out", default=None, help="write .meas deck to this file")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    code, summary, deck = run(args.spec)

    report = {"program": GATE, "version": "1.0.0", "summary": summary}
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False))

    if code == 0:
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(deck)
        elif not args.json:
            sys.stdout.write(deck)
    else:
        if not args.json:
            print(f"[FAIL] {GATE}: {summary.get('reason')}", file=sys.stderr)

    return code


if __name__ == "__main__":
    sys.exit(main())
