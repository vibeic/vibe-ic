#!/usr/bin/env python3
"""htol_attestation_check.py — Step 43 reliability qualification (HTOL)
attestation gate (v2.3).

HTOL (High-Temperature Operating Life) is the long-duration stress
qual — distinct from the Step-42 burn-in infant-mortality screen. The
stress itself runs in external chambers; this gate verifies the
attestation artifact is SUBSTANTIVE and arithmetically self-consistent,
never fabricating reliability numbers:

  * required numeric fields: units_tested > 0, stress_hours > 0,
    failures >= 0 (integer);
  * device_hours: provided value must equal units_tested×stress_hours
    (±1%) — else derived and disclosed;
  * failures > 0 → FAIL (qualification stress demands zero fails;
    AEC-Q100-style 77/3-lot zero-failure criterion) — a documented
    re-qual is a NEW artifact, not a waived old one;
  * FIT: point estimate failures(+0.5 χ²-floor)/device_hours×1e9; an
    `acceleration_factor` (>1) is applied when provided, else the FIT
    is labelled unaccelerated — disclosed, never silently assumed.

Exit codes: 0 PASS, 1 FAIL, 2 htol_results.json absent → BLOCKED
(vibe-ic#220 — an unperformed reliability qual on shipped silicon is an
unanswered question, not a benign SKIP; the flow step is scoped by the
silicon-intake declaration, so it REACHES this gate and reports BLOCKED
rather than self-disabling on its own missing output).
chip-AGNOSTIC: numeric/structural rules only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def audit(project: Path) -> dict:
    src = project / "phase3" / "stage5_manufacturing" / "htol_results.json"
    if not src.is_file():
        # #220 — name the missing input and call it BLOCKED, never SKIP.
        # Silicon reached this step, so reliability qualification was owed.
        # "SKIP" reads as "nothing to do here"; an unperformed HTOL is not
        # nothing to do, it is an unanswered question. rc stays non-zero.
        return {"verdict": "BLOCKED", "rc": 2,
                "missing_input": str(src),
                "reason": ("phase3/stage5_manufacturing/htol_results.json "
                           "absent — HTOL was never run or never recorded, so "
                           "no FIT/reliability claim can be substantiated. "
                           "Produce the HTOL result, or record an explicit "
                           "waiver stating why this silicon ships without "
                           "reliability qualification.")}
    try:
        d = json.loads(src.read_text(errors="replace"))
    except (OSError, ValueError):
        return {"verdict": "FAIL", "rc": 1,
                "reason": "htol_results.json unparseable"}

    findings = []
    units = d.get("units_tested")
    hours = d.get("stress_hours", d.get("duration_hours"))
    fails = d.get("failures")
    if not (isinstance(units, int) and units > 0):
        findings.append("UNITS_MISSING: units_tested must be a positive int")
    if not (isinstance(hours, (int, float)) and hours > 0):
        findings.append("HOURS_MISSING: stress_hours must be > 0")
    if not (isinstance(fails, int) and fails >= 0):
        findings.append("FAILURES_MISSING: failures must be an int >= 0")
    if findings:
        return {"verdict": "FAIL", "rc": 1,
                "reason": "attestation not substantive: "
                          + "; ".join(findings)}

    derived_dh = units * float(hours)
    dh = d.get("device_hours")
    dh_note = None
    if isinstance(dh, (int, float)) and dh > 0:
        if abs(dh - derived_dh) > 0.01 * derived_dh:
            return {"verdict": "FAIL", "rc": 1,
                    "reason": (f"DEVICE_HOURS_INCONSISTENT: stated "
                               f"{dh} vs units×hours={derived_dh:.0f} "
                               f"(>1% off) — numbers must reconcile")}
    else:
        dh = derived_dh
        dh_note = "derived from units_tested × stress_hours"

    af = d.get("acceleration_factor")
    accelerated = isinstance(af, (int, float)) and af > 1
    eff_hours = dh * (af if accelerated else 1.0)
    # χ²-style 0.5-failure floor so 0 fails still yields a finite
    # upper-bound point estimate.
    fit = (max(fails, 0.5) / eff_hours) * 1e9 if eff_hours > 0 else None

    rep = {
        "units_tested": units, "stress_hours": hours, "failures": fails,
        "device_hours": dh, "device_hours_note": dh_note,
        "acceleration_factor": af if accelerated else None,
        "fit_point_estimate": round(fit, 3) if fit is not None else None,
        "fit_basis": ("accelerated (AF applied)" if accelerated else
                      "UNACCELERATED raw stress-hours — apply the "
                      "Arrhenius AF for use-condition FIT"),
    }
    if fails > 0:
        rep.update(verdict="FAIL", rc=1, reason=(
            f"{fails} failure(s) during HTOL — qualification requires "
            f"zero failures; root-cause and re-qual with a new lot"))
    else:
        rep.update(verdict="PASS", rc=0, reason=(
            f"0 failures over {dh:.0f} device-hours"
            + (f" (AF={af})" if accelerated else "")))
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
    rep = {"program": "htol_attestation_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
