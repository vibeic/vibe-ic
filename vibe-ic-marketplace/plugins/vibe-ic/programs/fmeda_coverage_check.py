#!/usr/bin/env python3
"""fmeda_coverage_check.py — independent anti-fabrication gate over the FMEDA
diagnostic-coverage report emitted by `fmeda_fault_injection_coverage.py`.

WHY a separate gate: the producer already self-gates (its exit code reflects DC
vs the ASIL floor), but per the plugin's producer/gate doctrine a report's own
`verdict`/`ge_floor` boolean must NOT be trusted at sign-off. This gate RE-READS
`reports/phase2/safety/fmeda_coverage.json`, RECOMPUTES the verdict from the raw
`detected_faults` / `injected_faults` counts + the ASIL floor, and IGNORES the
written `verdict`/`ge_floor`. A report that claims PASS while its own counts say
DC < floor is caught (recomputed verdict wins), and a report that claims a DC
while `baseline_valid=false` is FAILed (a bogus measurement is not a pass).

  * NOT_APPLICABLE (applicable=false)  → VACUOUS PASS (exit 0). This step only
    fires for designs that DECLARE a safety mechanism; a non-safety design must
    skip, never fail.
  * applicable=true → recompute DC = detected/injected, compare to the resolved
    ASIL floor, require baseline_valid. Mismatch with the written verdict is
    reported and the RECOMPUTED verdict is authoritative.
  * missing report → this gate is a no-op VACUOUS PASS ONLY IF the design has no
    safety mechanism is UNKNOWN here, so a missing report is a soft skip (exit 0)
    unless --require is passed (then a missing report FAILs).

USAGE
  python3 fmeda_coverage_check.py <project> [--report <path>] [--asil D]
      [--min-dc <pct>] [--require] [--json <out>]

EXIT
  0 — recomputed PASS, or a DISCLOSED vacuous/soft skip. A vacuous exit prints
      a LINE-START `VACUOUS_PASS:` token — the rc-0 disclosure channel
      `flow_compliance_check._stdout_signals_vacuous` reads — so the step
      resolves to the VACUOUS_PASS tier instead of the plain PASS bucket.
  1 — recomputed FAIL (DC < floor, invalid baseline, or fabricated verdict)
  2 — IO / argument error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import _path_layout as _pl  # noqa: E402
import fmeda_fault_injection_coverage as fi  # noqa: E402


def check(report: dict, asil_override: Optional[str],
          min_dc: Optional[float]) -> dict:
    """Recompute the verdict from raw counts. Pure — the authoritative gate."""
    if not report.get("applicable", False):
        return {"gate": "fmeda_coverage_check", "verdict": "VACUOUS_PASS",
                "passed": True,
                "reason": report.get("reason", "no safety mechanism — N/A")}
    asil = asil_override or report.get("asil", "D")
    floor = fi.asil_floor(asil, min_dc)
    injected = int(report.get("injected_faults", 0))
    detected = int(report.get("detected_faults", 0))
    baseline_ok = bool(report.get("baseline_valid", False))
    dc = fi.compute_dc(detected, injected)
    if injected <= 0:
        return {"gate": "fmeda_coverage_check", "verdict": "FAIL",
                "passed": False, "recomputed_dc_pct": dc,
                "reason": "applicable but zero faults injected — no evidence"}
    if not baseline_ok:
        return {"gate": "fmeda_coverage_check", "verdict": "FAIL",
                "passed": False, "recomputed_dc_pct": round(dc, 4),
                "reason": "baseline_valid=false — DC measurement not trustworthy"}
    passed, reason = fi.dc_verdict(dc, floor)
    written = report.get("verdict")
    fabricated = (written == "PASS" and not passed)
    out = {
        "gate": "fmeda_coverage_check",
        "asil": asil,
        "dc_floor_pct": floor,
        "recomputed_dc_pct": round(dc, 4),
        "injected_faults": injected,
        "detected_faults": detected,
        "written_verdict": written,
        "verdict": "PASS" if passed else "FAIL",
        "passed": passed,
        "reason": reason,
        "fabricated_verdict_detected": fabricated,
    }
    if fabricated:
        out["reason"] = ("FABRICATED: report claims PASS but recomputed "
                         f"{reason}")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--report", default=None,
                   help="path to fmeda_coverage.json (default: "
                        "reports/phase2/safety/fmeda_coverage.json)")
    p.add_argument("--asil", default=None)
    p.add_argument("--min-dc", type=float, default=None)
    p.add_argument("--require", action="store_true",
                   help="FAIL if the report is missing (default: soft skip)")
    p.add_argument("--json", default=None)
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    rpt_path = (Path(args.report) if args.report
                else _pl.reports_phase2_dir(project) / "safety" /
                "fmeda_coverage.json")
    if not rpt_path.exists():
        res = {"gate": "fmeda_coverage_check",
               "verdict": "FAIL" if args.require else "VACUOUS_PASS",
               "passed": not args.require,
               "reason": f"report not found: {rpt_path}"
               + ("" if args.require else " — soft skip")}
        rc = 1 if args.require else 0
    else:
        try:
            report = json.loads(rpt_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"fmeda_coverage_check: bad report: {e}", file=sys.stderr)
            return 2
        res = check(report, args.asil, args.min_dc)
        rc = 0 if res["passed"] else 1

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(res, indent=2) + "\n")
    if res["verdict"] == "VACUOUS_PASS":
        # DISCLOSED SKIP. The report already self-declared
        # `verdict="VACUOUS_PASS"`, but no consumer opens the report file, and
        # the old line started `[PASS] fmeda_coverage_check: VACUOUS_PASS ...`
        # — `flow_compliance_check._stdout_signals_vacuous` matches the token
        # at LINE START only, so the disclosure could never reach the step's
        # tier and an unmeasured FMEDA was counted as a plain PASS. Put the
        # token where the consumer looks.
        #
        # Reason FIRST, bounded token line LAST: the consumer's window is
        # `stdout[-300:]`, so a token printed ahead of a long reason is sliced
        # mid-line and the step silently reverts to the plain PASS bucket.
        # Measured on the upstream `UNMEASURED_NO_RTL_READ` reason, which this
        # gate copies verbatim and which is longer than the window.
        print(f"fmeda_coverage_check: {res['verdict']} — {res['reason']}")
        print(f"VACUOUS_PASS: fmeda_coverage_check recomputed NOTHING "
              f"(verdict={res['verdict']}); see the --json report for why"
              [:fi.VACUOUS_TOKEN_MAX_LEN])
    else:
        tag = "PASS" if res["passed"] else "FAIL"
        print(f"[{tag}] fmeda_coverage_check: {res['verdict']} — "
              f"{res['reason']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
