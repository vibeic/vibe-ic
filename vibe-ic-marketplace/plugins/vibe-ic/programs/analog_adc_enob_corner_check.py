#!/usr/bin/env python3
"""analog_adc_enob_corner_check.py — R12 system-ENOB per-corner gate (A4).

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
For any ADC/DAC block that declares an ENOB (or SNDR) target, assert the
converter's measured effective resolution meets the spec on EVERY corner of
the corner sweep — not just the typical (TT/27C) corner. The classic escape
this closes: ENOB is measured and reported for the nominal corner only, so a
converter that meets ENOB typ but droops below it at a slow/hot corner ships
with an un-flagged spec violation. (A real hot-corner residual: an
oversampled modulator whose in-band SQNR — hence ENOB — collapses at SS/125C
because the integrator gain sags there.)

ENOB is derived from the sim-measured SNDR the standard way:

        ENOB = (SNDR_dB - 1.76) / 6.02

SNDR (and therefore ENOB) is a legitimate TOOL OUTPUT of the FFT/behavioural
converter sim — never a golden/oracle value. This gate READS that measured
output + the ENOB target from the design INPUT spec (spec.json) and compares;
it does not itself simulate.

Per block, reads:
  * phase3/analog/<block>/spec.json          — the ENOB target (design INPUT)
  * phase3/analog/<block>/corner_results.json — per-corner SNDR/ENOB (OUTPUT)

Applicability (chip-AGNOSTIC, no chip/SKU literal):
  * the block's spec.json declares a spec named `enob` OR `sndr`/`sndr_db`.
    (No ENOB/SNDR target => this is not a resolution-graded converter => SKIP.)

Per-corner resolution is read in priority order:
  1. a direct `enob` field on the corner, else
  2. computed from an SNDR field (`sndr_db` / `sndr` / `snr_db` alias) via the
     6.02/1.76 relation.
Corners with neither field are counted as UNMEASURED. If NO corner carries a
readable SNDR/ENOB, the gate SKIPs (honest — the resolution was verified
elsewhere / no FFT sim data here), never a vacuous PASS and never a false FAIL.

Verdict:
  PASS  — every measured corner's ENOB >= target.
  FAIL  — >=1 measured corner ENOB < target; the finding lists each failing
          corner with its ENOB and the shortfall.
  SKIP  — no ADC/DAC block with an ENOB/SNDR target, or no per-corner
          SNDR/ENOB data present.

Exit codes: 0 = PASS / SKIP, 1 = FAIL, 2 = IO / argument error.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl

GATE = "analog_adc_enob_corner_check"

# ENOB <-> SNDR ideal-quantiser relation (both are chip-AGNOSTIC constants).
_SNDR_SLOPE = 6.02   # dB per bit
_SNDR_INTERCEPT = 1.76  # dB


def _load_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _enob_target(spec: dict) -> Optional[float]:
    """The ENOB floor from spec.json, or None when the block declares no
    ENOB / SNDR resolution target (=> not applicable)."""
    if not isinstance(spec, dict):
        return None
    specs = spec.get("specs")
    if not isinstance(specs, list):
        return None
    enob_target: Optional[float] = None
    sndr_target: Optional[float] = None
    for s in specs:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip().lower()
        # prefer an explicit target, else a min floor.
        val = s.get("target")
        if not (isinstance(val, (int, float)) and math.isfinite(val)):
            val = s.get("min")
        if not (isinstance(val, (int, float)) and math.isfinite(val)):
            continue
        if name == "enob":
            enob_target = float(val)
        elif name in ("sndr", "sndr_db", "snr", "snr_db"):
            sndr_target = float(val)
    if enob_target is not None:
        return enob_target
    if sndr_target is not None:
        return (sndr_target - _SNDR_INTERCEPT) / _SNDR_SLOPE
    return None


def _corner_enob(corner: dict) -> Optional[float]:
    """Read/derive one corner's ENOB, or None when unmeasured here."""
    if not isinstance(corner, dict):
        return None
    # A non-finite value (NaN / inf) is a non-converged / invalid sim
    # measurement, NOT a clean pass — treat it as UNMEASURED so it can never
    # silently clear the ENOB target (NaN < target is always False).
    direct = corner.get("enob")
    if isinstance(direct, (int, float)) and math.isfinite(direct):
        return float(direct)
    for k in ("sndr_db", "sndr", "snr_db", "snr"):
        v = corner.get(k)
        if isinstance(v, (int, float)) and math.isfinite(v):
            return (float(v) - _SNDR_INTERCEPT) / _SNDR_SLOPE
    return None


def _check_block(project: Path, block_dir: Path
                 ) -> Tuple[str, Optional[dict]]:
    """Return (status, detail). status in {PASS, FAIL, SKIP}."""
    spec = _load_json(block_dir / "spec.json")
    target = _enob_target(spec or {})
    if target is None:
        return "SKIP", None  # not an ENOB/SNDR-graded converter

    corners_doc = _load_json(block_dir / "corner_results.json")
    corners = (corners_doc or {}).get("corners")
    if not isinstance(corners, list) or not corners:
        return "UNMEASURED", {"block": block_dir.name, "reason": "no_corner_data",
                        "enob_target": target}

    measured: List[dict] = []
    failing: List[dict] = []
    unmeasured = 0
    for idx, c in enumerate(corners):
        enob = _corner_enob(c if isinstance(c, dict) else {})
        if enob is None:
            unmeasured += 1
            continue
        cname = (c.get("name") if isinstance(c, dict) else None) or f"#{idx}"
        rec = {"corner": cname, "enob": round(enob, 3)}
        measured.append(rec)
        if enob < target - 1e-9:
            rec["shortfall_bits"] = round(target - enob, 3)
            failing.append(rec)

    if not measured:
        return "UNMEASURED", {"block": block_dir.name, "reason": "no_sndr_or_enob",
                        "enob_target": target,
                        "corners_seen": len(corners)}

    detail = {
        "block": block_dir.name,
        "enob_target": target,
        "corners_measured": len(measured),
        "corners_unmeasured": unmeasured,
        "worst_enob": min(m["enob"] for m in measured),
        "failing_corners": failing,
    }
    return ("FAIL" if failing else "PASS"), detail


def run_audit(project: Path) -> dict:
    analog = _pl.analog_dir(project)
    if not analog.is_dir():
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no_analog_dir", "blocks": []}

    results = []
    verdict = "SKIP"
    for bdir in sorted(d for d in analog.iterdir() if d.is_dir()):
        status, detail = _check_block(project, bdir)
        if status == "UNMEASURED":
            verdict = "UNMEASURED" if verdict != "FAIL" else verdict
            if detail:
                results.append({"status": "UNMEASURED", **detail})
            continue
        if status == "SKIP":
            if detail is not None:
                results.append({"status": "SKIP", **detail})
            continue
        results.append({"status": status, **(detail or {})})
        if status == "FAIL":
            verdict = "FAIL"
        elif verdict != "FAIL":
            verdict = "PASS"

    graded = [r for r in results if r.get("status") in ("PASS", "FAIL")]
    return {
        "gate": GATE,
        "verdict": verdict,
        "blocks_graded": len(graded),
        "blocks": results,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    report = run_audit(args.project_dir.resolve())

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                              ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    print(f"[{verdict}] {GATE}")
    for b in report["blocks"]:
        if b.get("status") == "FAIL":
            for fc in b.get("failing_corners", []):
                print(f"  FAIL {b['block']} @ {fc['corner']}: ENOB "
                      f"{fc['enob']} < target {b['enob_target']} "
                      f"(short {fc.get('shortfall_bits')} bits)")
    # UNMEASURED IS NOT NOT-APPLICABLE (vibe-ic#693 family). Two different
    # situations shared the SKIP status and therefore shared rc 0:
    #
    #   no target/OSR in the spec  -> the formula genuinely does not apply to
    #                                 this block. Not a finding.
    #   target/OSR DECLARED but no corner data -> the block IS graded on this
    #                                 axis and nobody measured it. That is an
    #                                 absence, and it was reported as a pass.
    #
    # Found by RUNNING the gate on the published corpus, which nothing had done:
    # it prints `[SKIP]` and exits 0, so a wired flow counts it among the gates
    # that passed. The second case is now UNMEASURED and exits 2.
    if verdict == "FAIL":
        return 1
    if verdict == "UNMEASURED":
        print(f"[UNMEASURED] {GATE}: a block declares this axis and no data "
              f"measures it — not a pass.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
