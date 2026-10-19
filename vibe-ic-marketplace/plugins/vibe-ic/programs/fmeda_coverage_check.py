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

  * NOT_APPLICABLE (applicable=false)  → not a verdict. This step only fires
    for designs that DECLARE a safety mechanism; a non-safety design must skip,
    never fail. WHICH kind of skip is mirrored from the producer's own report,
    never re-derived here: when that report carries a valid R-0915-119
    `structural_absence` record — the RTL was read, its modules enumerated and
    none of them is a safety mechanism candidate — this gate states the same
    NOT_APPLICABLE_BY_STRUCTURE with the same enumeration and exits 2 (the
    non-verdict-candidate code). Every other inapplicable shape — an input
    nobody read or a missing report — keeps
    the disclosed VACUOUS PASS at exit 0. Mirroring rather than re-deriving is
    the point: two gates of one step must not hold two opinions about one
    design, and a second scanner is a second answer waiting to disagree with
    the first.
  * applicable=true, binding=UNBOUND → NOT_MEASURED and non-PASS. A port-shape
    candidate or embedded checker without a bound source path is not a DC result.
  * applicable=true with a measured, bound mechanism → recompute DC from raw
    counts, compare to the resolved ASIL floor, require baseline_valid.
    Mismatch with the written verdict is reported and the RECOMPUTED verdict
    is authoritative.
  * missing report → this gate is a no-op VACUOUS PASS ONLY IF the design has no
    safety mechanism is UNKNOWN here, so a missing report is a soft skip (exit 0)
    unless --require is passed (then a missing report FAILs).

USAGE
  python3 fmeda_coverage_check.py <project> [--report <path>] [--asil D]
      [--min-dc <pct>] [--require] [--json <out>]

EXIT
  2 — the R-0915-119 decided state, mirrored from the producer's report, or an
      IO / argument error. Both are NON-VERDICT CANDIDATES the consumer
      classifies from the report, never from the number alone.
  0 — recomputed PASS, or a DISCLOSED vacuous/soft skip. A vacuous exit prints
      a LINE-START `VACUOUS_PASS:` token — the rc-0 disclosure channel
      `flow_compliance_check._stdout_signals_vacuous` reads — so the step
      resolves to the VACUOUS_PASS tier instead of the plain PASS bucket.
  1 — recomputed FAIL (DC < floor, invalid baseline, or fabricated verdict)
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
import _structural_absence as _sa  # noqa: E402  R-0915-119
import fmeda_fault_injection_coverage as fi  # noqa: E402


def check(report: dict, asil_override: Optional[str],
          min_dc: Optional[float], project: Optional[Path] = None) -> dict:
    """Recompute the verdict from raw counts. Pure — the authoritative gate."""
    import _fmeda_mechanisms as declared
    manifest_present = project is not None and ((project / declared.MANIFEST).exists() or
                                               (project / declared.MANIFEST).is_symlink())
    if manifest_present or report.get("schema") == declared.REPORT_SCHEMA:
        try:
            if project is None:
                raise declared.Refusal("current project required for declared mechanism evidence")
            return declared.consume(project, report, asil_override, min_dc)
        except (declared.Refusal, OSError, ValueError, TypeError, KeyError) as exc:
            return {"gate": "fmeda_coverage_check", "verdict": "FAIL", "passed": False,
                    "reason": f"declared mechanism evidence refused: {exc}"}
    mechanism = report.get("mechanism")
    legacy_auto = (isinstance(mechanism, dict)
                   and mechanism.get("source") == "auto-detected")
    if report.get("mechanism_binding") == "UNBOUND" or legacy_auto:
        # Current producer marks candidates UNBOUND. Earlier reports carried
        # only mechanism.source=auto-detected and may even contain fault
        # counts. Those counts came from a shape-inferred pair, without a
        # source-bound encoder/checker relationship, and cannot become PASS by
        # replaying an old report. A contradictory applicable=false flag also
        # cannot turn the same candidate into N/A. Explicit measured reports
        # still reach the raw-count and ASIL-floor recomputation below.
        return {"gate": "fmeda_coverage_check", "verdict": "NOT_MEASURED",
                "passed": False, "recomputed_dc_pct": None,
                "reason": "mechanism candidate is unbound; no fault injection "
                          "or diagnostic-coverage measurement exists"}
    if not report.get("applicable", False):
        # THE PRODUCER'S OWN ENUMERATION, MIRRORED — not a second scan. If it
        # established that the design's modules were walked and none is a
        # safety mechanism, this gate says the same thing with the same
        # evidence; if it established nothing, so does this. `evidence_of`
        # re-validates the record (guards (i) and (ii)) before it is repeated,
        # so a report carrying only the class token, a malformed enumeration,
        # or a subject that was FOUND cannot borrow the decided state here.
        _absence = _sa.evidence_of(report)
        if _absence is not None:
            out = {"gate": "fmeda_coverage_check",
                   "verdict": "NOT_APPLICABLE", "passed": True,
                   "reason": _sa.sentence(
                       _absence, "FMEDA diagnostic coverage (recomputed)"),
                   "mirrored_from": "fmeda_fault_injection_coverage"}
            _sa.attach(out, _absence)
            return out
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
        import _fmeda_mechanisms as declared
        required = args.require or (project / declared.MANIFEST).exists() or (project / declared.MANIFEST).is_symlink()
        res = {"gate": "fmeda_coverage_check",
               "verdict": "FAIL" if required else "VACUOUS_PASS",
               "passed": not required,
               "reason": f"report not found: {rpt_path}"
               + ("" if required else " — soft skip")}
        rc = 1 if required else 0
    else:
        try:
            report = json.loads(rpt_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"fmeda_coverage_check: bad report: {e}", file=sys.stderr)
            return 2
        res = check(report, args.asil, args.min_dc, project)
        rc = 0 if res["passed"] else 1
        if _sa.evidence_of(res) is not None:
            # DECIDED, not vacuous: rc 2 is the only channel that carries a
            # reason class to `flow_compliance_check`.
            rc = fi.RC_NON_VERDICT

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        import _gate_authorship as _ga
        res['program'] = 'fmeda_coverage_check'
        _ga.stamp(res)
        Path(args.json).write_text(json.dumps(res, indent=2) + "\n")
    _absence = _sa.evidence_of(res)
    if _absence is not None:
        # Printed ALONE and LAST — R-0915-119's stdout channel, bounded so it
        # lands whole in the consumer's `stdout[-300:]` window — and never
        # beside the `VACUOUS_PASS:` token, which makes the opposite claim.
        print(_sa.sentence(_absence, "FMEDA diagnostic coverage (recomputed)"))
    elif res["verdict"] == "VACUOUS_PASS":
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
