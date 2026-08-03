#!/usr/bin/env python3
"""analog_sigma_delta_gain_floor_check.py — R14 integrator-gain floor gate (A4).

For an oversampled delta-sigma / incremental converter, the loop-filter
integrator (OTA) DC gain must clear the noise-leakage floor

        gain_floor_dB = 20 * log10(OSR)

or the finite-gain integrator leaks in-band quantisation noise back into the
signal band and the modulator cannot reach the SQNR its OSR implies — so the
claimed ENOB is unachievable REGARDLESS of what a behavioural ENOB sim
reports. This gate is the one that flags an insufficient integrator gain
BEFORE ENOB is claimed. It would have caught a real hot-corner residual: an
OTA at 42.8 dB against a 48.16 dB (= 20*log10(256)) floor at the hot corner.

It reads the DESIGN INPUT (OSR from spec.json) and the sim-measured OTA DC
gain per corner (a legitimate TOOL OUTPUT of the AC sim, never a golden):

  * phase3/analog/<block>/spec.json          — OSR + converter_type (INPUT)
  * phase3/analog/<block>/corner_results.json — per-corner OTA DC gain (OUTPUT)

Applicability (chip-AGNOSTIC): the block is an oversampled sigma-delta /
incremental converter — its spec.json declares an `osr` spec AND its
`converter_type`/`type` names a delta-sigma family (`delta_sigma`,
`sigma_delta`, `incremental`, `dsm`, `modulator`). No OSR / not a sigma-delta
=> the 20*log10(OSR) floor does not apply => SKIP.

Per-corner gain is read in priority order from these fields:
    ota_dc_gain_db, integrator_gain_db, dc_gain_db, ota_gain_db, gain_db
If NO corner carries a gain field, the gate SKIPs (honest — no AC-sim gain
data here), never a vacuous PASS.

Verdict (the margin is a design GUARD BAND above the hard functional floor):
  FAIL — >=1 corner gain < gain_floor_dB. This is a hard functional failure:
         below the leakage floor the modulator physically cannot reach its
         target SQNR. The finding prints measured-gain vs floor per corner.
  PASS-with-WARN — every corner clears the floor but >=1 corner sits within
         `--margin-db` of it (default 3 dB): the design is MARGINAL at the
         leakage floor (exit 0, a MARGINAL warning is recorded).
  PASS — every corner clears floor + margin.
  SKIP — not an oversampled sigma-delta with OSR, or no per-corner gain data.

Exit codes: 0 = PASS / PASS-with-WARN / SKIP, 1 = FAIL, 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl

GATE = "analog_sigma_delta_gain_floor_check"

_SIGMA_DELTA_TOKENS = (
    "delta_sigma", "delta-sigma", "sigma_delta", "sigma-delta",
    "incremental", "dsm", "modulator",
)
_GAIN_FIELDS = (
    "ota_dc_gain_db", "integrator_gain_db", "dc_gain_db",
    "ota_gain_db", "gain_db",
)
_DEFAULT_MARGIN_DB = 3.0


def _load_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _spec_value(spec: dict, name: str) -> Optional[float]:
    for s in spec.get("specs", []) if isinstance(spec, dict) else []:
        if not isinstance(s, dict):
            continue
        if str(s.get("name", "")).strip().lower() == name:
            for key in ("target", "value", "min"):
                v = s.get(key)
                if isinstance(v, (int, float)) and math.isfinite(v):
                    return float(v)
    return None


def _is_sigma_delta(spec: dict) -> bool:
    if not isinstance(spec, dict):
        return False
    blob = " ".join(str(spec.get(k, "")) for k in ("type", "converter_type"))
    # converter_type can also be a spec entry (value form).
    for s in spec.get("specs", []) if isinstance(spec.get("specs"), list) else []:
        if isinstance(s, dict) and str(s.get("name", "")).lower() == "converter_type":
            blob += " " + str(s.get("value", "")) + " " + str(s.get("target", ""))
    blob = blob.lower()
    return any(tok in blob for tok in _SIGMA_DELTA_TOKENS)


def _corner_gain(corner: dict) -> Optional[float]:
    if not isinstance(corner, dict):
        return None
    for k in _GAIN_FIELDS:
        v = corner.get(k)
        # A non-finite value (NaN / inf) is a non-converged / invalid sim
        # measurement, NOT a clean pass — treat it as UNMEASURED so it can
        # never silently clear the floor (NaN < floor is always False).
        if isinstance(v, (int, float)) and math.isfinite(v):
            return float(v)
    return None


def _check_block(block_dir: Path, margin_db: float
                 ) -> Tuple[str, Optional[dict]]:
    """Return (status, detail). status in {PASS, WARN, FAIL, SKIP}."""
    spec = _load_json(block_dir / "spec.json") or {}
    osr = _spec_value(spec, "osr")
    if osr is None or osr <= 1 or not _is_sigma_delta(spec):
        return "SKIP", None  # floor formula does not apply

    floor_db = 20.0 * math.log10(osr)

    corners_doc = _load_json(block_dir / "corner_results.json")
    corners = (corners_doc or {}).get("corners")
    if not isinstance(corners, list) or not corners:
        return "UNMEASURED", {"block": block_dir.name, "reason": "no_corner_data",
                        "osr": osr, "gain_floor_db": round(floor_db, 3)}

    measured: List[dict] = []
    failing: List[dict] = []
    marginal: List[dict] = []
    for idx, c in enumerate(corners):
        gain = _corner_gain(c if isinstance(c, dict) else {})
        if gain is None:
            continue
        cname = (c.get("name") if isinstance(c, dict) else None) or f"#{idx}"
        rec = {"corner": cname, "gain_db": round(gain, 3),
               "gain_floor_db": round(floor_db, 3)}
        measured.append(rec)
        if gain < floor_db - 1e-9:
            rec["deficit_db"] = round(floor_db - gain, 3)
            failing.append(rec)
        elif gain < floor_db + margin_db - 1e-9:
            rec["margin_db"] = round(gain - floor_db, 3)
            marginal.append(rec)

    if not measured:
        return "UNMEASURED", {"block": block_dir.name, "reason": "no_gain_data",
                        "osr": osr, "gain_floor_db": round(floor_db, 3),
                        "corners_seen": len(corners)}

    detail = {
        "block": block_dir.name,
        "osr": osr,
        "gain_floor_db": round(floor_db, 3),
        "margin_db": margin_db,
        "corners_measured": len(measured),
        "worst_gain_db": min(m["gain_db"] for m in measured),
        "failing_corners": failing,
        "marginal_corners": marginal,
    }
    if failing:
        return "FAIL", detail
    if marginal:
        return "WARN", detail
    return "PASS", detail


def run_audit(project: Path, margin_db: float) -> dict:
    analog = _pl.analog_dir(project)
    if not analog.is_dir():
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no_analog_dir", "blocks": []}

    results = []
    verdict = "SKIP"
    for bdir in sorted(d for d in analog.iterdir() if d.is_dir()):
        status, detail = _check_block(bdir, margin_db)
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
        elif status == "WARN":
            if verdict not in ("FAIL",):
                verdict = "WARN"
        elif verdict not in ("FAIL", "WARN"):
            verdict = "PASS"

    graded = [r for r in results if r.get("status") in ("PASS", "WARN", "FAIL")]
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
    ap.add_argument("--margin-db", type=float, default=_DEFAULT_MARGIN_DB,
                    help=f"guard-band above the 20*log10(OSR) floor "
                         f"(default {_DEFAULT_MARGIN_DB} dB)")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    report = run_audit(args.project_dir.resolve(), args.margin_db)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                              ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    print(f"[{verdict}] {GATE}")
    for b in report["blocks"]:
        if b.get("status") == "FAIL":
            for fc in b.get("failing_corners", []):
                print(f"  FAIL {b['block']} @ {fc['corner']}: gain "
                      f"{fc['gain_db']} dB < floor {fc['gain_floor_db']} dB "
                      f"(deficit {fc.get('deficit_db')} dB, OSR={b['osr']})")
        elif b.get("status") == "WARN":
            for mc in b.get("marginal_corners", []):
                print(f"  WARN {b['block']} @ {mc['corner']}: gain "
                      f"{mc['gain_db']} dB only {mc['margin_db']} dB over "
                      f"floor {mc['gain_floor_db']} dB (MARGINAL, OSR={b['osr']})")
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
