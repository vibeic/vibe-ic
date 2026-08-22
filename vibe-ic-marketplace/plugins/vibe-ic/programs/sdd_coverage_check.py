#!/usr/bin/env python3
"""sdd_coverage_check.py — REAL small-delay-defect (SDD) coverage GATE for the
slack-weighted at-speed ATPG grade (sdd_atpg_run.py).

ANTI-FABRICATION checker. Like the sibling DT1/DT2 gates, it does NOT trust the
buckets or the coverage numbers the producer wrote. It INDEPENDENTLY re-derives
the strong/weak/undetected classification from the per-fault SLACK list in
reports/phase2/dft/sdd_coverage.json and re-checks:

    margin_ns'  = clock_period × margin_fraction        (re-derived here — a
                  DOCTORED top-level margin_ns is caught)
    sensitizable' = (nr_verdict == 'DET')               (re-derived — a
                    fabricated sensitisation flag is caught)
    bucket'     = slack_bucket(slack, sensitizable', margin_ns')
    strong'     = #records with bucket' == 'strong'
    weighted'   = mean(sdd_weight(slack, sensitizable', margin_ns')) × 100

FALSE-CLEAN-PROOF (the crux):
  * A record reported 'strong' whose RECORDED detecting-path slack exceeds the
    RE-DERIVED margin (or that is not genuinely sensitizable) is a strong-with-
    high-slack fabrication → FAIL. This is the exact false-clean the task asks
    the gate to catch: "a fault whose detecting path is high-slack but marked
    'strong' must FAIL the gate."
  * A record is 'sensitizable' ONLY when its recorded nr_verdict is exactly
    'DET' (a real DT2 LOC 2-pattern). undetected/aborted/false paths are never
    in the numerator.
  * The reported sdd_binary_strong_coverage / sdd_slack_weighted_coverage may
    NOT EXCEED the gate's independent recount (a tolerance guards float rounding
    only). A doctored (inflated) coverage FAILs.
  * The disclosed margin_fraction may not exceed the disclosed cap.

NOT_APPLICABLE (honest, never a fake pass): the producer records
NOT_APPLICABLE when DT2 is N/A (no timing model / no scan / no LOC path). The
gate passes that through (rc 0). A run with no per-fault records FAILs.

DESCRIPTIVE, NOT A FLOOR: SDD grades detection QUALITY by slack; a slack-rich
design HONESTLY reports low SDD coverage and that is a PASS. This gate enforces
SELF-CONSISTENCY (the reported grade matches the slack list) — it does not
impose a minimum coverage. An optional `--min-slack-weighted` may be supplied
by a caller that wants a hard at-speed bar, but it defaults OFF.

Usage:
    python3 sdd_coverage_check.py <project_dir> [--json OUT]
                                  [--coverage-json PATH]
                                  [--min-slack-weighted 0] [--tol 0.01]

main(argv) -> int : 0 PASS/NOT_APPLICABLE, 1 FAIL, 2 IO-or-arg error.
chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover
    _pl = None

try:
    import sdd_atpg_run as _sdd  # reuse the pure bucketing / weighting / math
except Exception:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sdd_atpg_run as _sdd  # type: ignore


# Where the phase3 producer leaves a record when no coverage artefact could be
# produced (vibe-ic#235). An absent artefact WITH one of these is BLOCKED (the
# step said why); an absent artefact WITHOUT one is FAIL (nothing knows whether
# it ever ran). Mirrors transition_coverage_check's DT1 channel.
_NOT_RUN_RECORDS = (
    "phase2/stage2/dft/sdd_atpg_not_run.json",
    "reports/phase2/dft/sdd_atpg_not_run.json",
)

_PROGRAM = "sdd_coverage_check"
_VERSION = "1.0.0"
# Small tolerance to absorb float rounding only — NEVER a coverage slack.
COVERAGE_TOL_DEFAULT = 0.01


def _load_json(path: Path) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _recount(records: list, margin_ns) -> dict:
    """Independently recount SDD outcomes from the per-fault list — the crux of
    the gate. sensitizable is RE-DERIVED from nr_verdict; bucket + weight are
    RE-DERIVED from the recorded slack against the RE-DERIVED margin. It never
    trusts the producer's `sdd_bucket` / `sensitizable` / coverage. Also flags
    every record whose REPORTED bucket over-claims 'strong'. Pure."""
    graded = strong = weak = undet = 0
    wsum = 0.0
    strong_high_slack: list = []      # reported strong, re-derived NOT strong
    sensitize_fabricated: list = []   # reported sensitizable, nr_verdict != DET
    for r in records:
        if not isinstance(r, dict) or not r.get("loc_testable"):
            continue
        graded += 1
        slack = r.get("detecting_path_slack_ns")
        sens = (r.get("nr_verdict") == "DET")
        bucket = _sdd.slack_bucket(slack, sens, margin_ns)
        wsum += _sdd.sdd_weight(slack, sens, margin_ns)
        if bucket == "strong":
            strong += 1
        elif bucket == "weak":
            weak += 1
        else:
            undet += 1
        # false-clean: a reported 'strong' that is NOT re-derived strong.
        if r.get("sdd_bucket") == "strong" and bucket != "strong":
            strong_high_slack.append({
                "idx": r.get("idx"), "startpoint": r.get("startpoint"),
                "endpoint": r.get("endpoint"),
                "detecting_path_slack_ns": slack, "margin_ns": margin_ns,
                "recomputed_bucket": bucket})
        # fabricated sensitisation flag.
        if r.get("sensitizable") and not sens:
            sensitize_fabricated.append({
                "idx": r.get("idx"), "endpoint": r.get("endpoint"),
                "nr_verdict": r.get("nr_verdict")})
    return {
        "graded": graded, "strong": strong, "weak": weak,
        "undetected_at_speed": undet, "weight_sum": wsum,
        "strong_high_slack": strong_high_slack,
        "sensitize_fabricated": sensitize_fabricated,
    }


def evaluate(blob: Optional[dict], min_slack_weighted: float = 0.0,
             tol: float = COVERAGE_TOL_DEFAULT,
             not_run_record: Optional[dict] = None) -> dict:
    """Pure evaluator. Recomputes SDD strong/weak/undetected + coverage from the
    per-fault slack list and re-derives the verdict. NEVER trusts a written
    bucket or coverage; NEVER counts a high-slack path as strong. chip-AGNOSTIC.

    `not_run_record` — the producer's own not-run sentinel, when one exists
    (vibe-ic#235). DT3 is the cascade case: whenever DT1 or DT2 self-disables,
    DT3 has nothing to fuse and vanishes too. An absent grade is never a pass,
    but a step that recorded WHY it could not grade is BLOCKED, not a bare FAIL
    that cannot distinguish "never ran" from "ran and could not measure".
    """
    reasons: list[str] = []

    if blob is None:
        if isinstance(not_run_record, dict):
            why = str(not_run_record.get("reason")
                      or "producer recorded a not-run sentinel with no reason")
            stage = not_run_record.get("not_run_stage")
            return {"verdict": "BLOCKED", "status": "BLOCKED",
                    "not_run_stage": stage,
                    "reasons": [
                        "no sdd_coverage.json was produced; the step recorded "
                        f"why it did not run{f' ({stage})' if stage else ''}: "
                        + why
                        + " — BLOCKED (the small-delay-defect grade is "
                          "unmeasured, which is not a pass)"]}
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["sdd_coverage.json absent or invalid JSON, and NO "
                            "not-run record was left either — there is no "
                            "evidence the SDD step ran at all. An absent grade "
                            "is never a pass; the step must produce a "
                            "measurement or state why it could not"]}

    if blob.get("verdict") == "NOT_APPLICABLE":
        return {"verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                "scan_flops": blob.get("scan_flops", 0),
                "reasons": blob.get("reasons",
                                    ["producer recorded NOT_APPLICABLE"])}

    if blob.get("verdict") == "ERROR":
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["producer recorded ERROR (SDD grade could not run): "
                            + "; ".join(blob.get("reasons", [])[:2])]}

    records = blob.get("sdd_records")
    if not isinstance(records, list) or not records:
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["no per-fault SDD records present — cannot pass on "
                            "zero evidence"]}

    # RE-DERIVE the margin from the disclosed inputs (catch a doctored margin_ns).
    period_ns = blob.get("clock_period_ns")
    margin_fraction = blob.get("margin_fraction")
    cap = blob.get("margin_fraction_cap", _sdd.SDD_MARGIN_FRACTION_CAP)
    written_margin_ns = blob.get("margin_ns")
    explicit_margin = (blob.get("margin_ns_derivation") == "explicit --margin-ns")

    if isinstance(margin_fraction, (int, float)) and margin_fraction > cap:
        reasons.append(
            f"disclosed margin_fraction {margin_fraction} exceeds the cap {cap} "
            "— a 'small-delay' window may not exceed the period")

    if explicit_margin:
        # An explicit ns margin is honoured as-is (disclosed), used for recount.
        recomputed_margin = written_margin_ns
    else:
        recomputed_margin = _sdd.sdd_margin_ns(period_ns, margin_fraction)
        # A written margin_ns that disagrees with period×fraction is doctored.
        if (isinstance(written_margin_ns, (int, float))
                and recomputed_margin is not None
                and abs(float(written_margin_ns) - recomputed_margin) > 1e-6):
            reasons.append(
                f"written margin_ns={written_margin_ns} != period×fraction "
                f"({recomputed_margin}) — margin appears doctored; recomputed "
                "margin governs")

    rc = _recount(records, recomputed_margin)
    graded = rc["graded"]
    if graded == 0:
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["no LOC-testable graded records — cannot pass on "
                            "zero evidence"]}

    strong_cov = round(100.0 * rc["strong"] / graded, 4)
    weighted_cov = round(100.0 * rc["weight_sum"] / graded, 4)

    # FALSE-CLEAN: any reported 'strong' that is not re-derived strong FAILs.
    if rc["strong_high_slack"]:
        ex = rc["strong_high_slack"][0]
        reasons.append(
            f"{len(rc['strong_high_slack'])} record(s) reported 'strong' but "
            f"their detecting-path slack exceeds the margin (or are not "
            f"sensitizable) — e.g. endpoint {ex['endpoint']} slack "
            f"{ex['detecting_path_slack_ns']} ns > margin {ex['margin_ns']} ns "
            f"→ re-derived '{ex['recomputed_bucket']}'; strong-with-high-slack "
            "is a false-clean fabrication")
    if rc["sensitize_fabricated"]:
        ex = rc["sensitize_fabricated"][0]
        reasons.append(
            f"{len(rc['sensitize_fabricated'])} record(s) flagged sensitizable "
            f"without a DT2 'DET' verdict (e.g. endpoint {ex['endpoint']} "
            f"nr_verdict={ex['nr_verdict']}) — fabricated sensitisation")

    # Over-claim: the written coverage may not exceed the independent recount.
    written_strong_cov = blob.get("sdd_binary_strong_coverage_pct")
    written_weighted_cov = blob.get("sdd_slack_weighted_coverage_pct")
    if (isinstance(written_strong_cov, (int, float))
            and float(written_strong_cov) > strong_cov + tol):
        reasons.append(
            f"reported strong coverage {written_strong_cov}% exceeds the "
            f"recount {strong_cov}% — inflated")
    if (isinstance(written_weighted_cov, (int, float))
            and float(written_weighted_cov) > weighted_cov + tol):
        reasons.append(
            f"reported slack-weighted coverage {written_weighted_cov}% exceeds "
            f"the recount {weighted_cov}% — inflated")

    # OPTIONAL hard bar (defaults OFF — SDD is descriptive, not a floor).
    below_min = False
    if min_slack_weighted and weighted_cov < float(min_slack_weighted):
        below_min = True
        reasons.append(
            f"slack-weighted SDD coverage {weighted_cov}% < requested minimum "
            f"{min_slack_weighted}% (caller-imposed at-speed bar)")

    fabricated = bool(rc["strong_high_slack"] or rc["sensitize_fabricated"])
    over_claim = any("exceeds the recount" in r for r in reasons)
    ok = (not fabricated) and (not over_claim) and (not below_min)

    return {
        "margin_ns": recomputed_margin,
        "margin_fraction": margin_fraction,
        "clock_period_ns": period_ns,
        "graded_faults": graded,
        "strong": rc["strong"],
        "weak": rc["weak"],
        "undetected_at_speed": rc["undetected_at_speed"],
        "sdd_binary_strong_coverage_pct": strong_cov,
        "sdd_slack_weighted_coverage_pct": weighted_cov,
        "strong_high_slack_violations": len(rc["strong_high_slack"]),
        "sensitize_fabrications": len(rc["sensitize_fabricated"]),
        "recomputed_consistent": ok,
        "verdict": "PASS" if ok else "FAIL",
        "status": "PASS" if ok else "FAIL",
        "reasons": reasons,
    }


def _resolve_coverage_json(project: Path, override: Optional[str]) -> Optional[Path]:
    cands = []
    if override:
        cands.append(Path(override))
    else:
        if _pl is not None:
            cands.append(_pl.report_path(project, "dft/sdd_coverage.json"))
        cands.append(project / "reports/phase2/dft/sdd_coverage.json")
        cands.append(project / "reports/dft/sdd_coverage.json")
    return next((p for p in cands if p.is_file()), None)


def _resolve_not_run_record(project: Path) -> tuple[Optional[dict], Optional[Path]]:
    """Find the step's own record of why it produced no coverage grade."""
    for rel in _NOT_RUN_RECORDS:
        p = project / rel
        if p.is_file():
            d = _load_json(p)
            if d is not None:
                return d, p
    return None, None


def audit(project: Path, coverage_json: Optional[str] = None,
          min_slack_weighted: float = 0.0,
          tol: float = COVERAGE_TOL_DEFAULT) -> dict:
    path = _resolve_coverage_json(project, coverage_json)
    blob = _load_json(path) if path else None
    rec, rec_path = (_resolve_not_run_record(project) if blob is None
                     else (None, None))
    base = {"program": _PROGRAM, "version": _VERSION,
            "project_dir": str(project),
            "coverage_json": str(path) if path else None,
            "not_run_record": str(rec_path) if rec_path else None}
    result = evaluate(blob, min_slack_weighted=min_slack_weighted, tol=tol,
                      not_run_record=rec)
    result.update(base)
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Small-delay-defect (SDD) coverage gate — recomputes "
                    "strong/weak/undetected from the per-fault slack list; a "
                    "high-slack path marked strong FAILs (false-clean-proof)")
    ap.add_argument("project_dir")
    ap.add_argument("--coverage-json", default=None,
                    help="Explicit sdd_coverage.json path")
    ap.add_argument("--min-slack-weighted", type=float, default=0.0,
                    help="Optional hard at-speed bar on slack-weighted SDD "
                         "coverage %% (default 0 = OFF; SDD is descriptive)")
    ap.add_argument("--tol", type=float, default=COVERAGE_TOL_DEFAULT,
                    help=f"Float-rounding tolerance on the over-claim check "
                         f"(default {COVERAGE_TOL_DEFAULT})")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = audit(project, args.coverage_json,
                   min_slack_weighted=args.min_slack_weighted, tol=args.tol)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        try:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out + "\n")
        except Exception as exc:  # pragma: no cover
            print(f"WARN: could not write --json {args.json}: {exc}",
                  file=sys.stderr)
    print(out)

    v = report.get("verdict")
    print(f"{_PROGRAM}: verdict={v} "
          f"strong={report.get('strong')} weak={report.get('weak')} "
          f"undetected_at_speed={report.get('undetected_at_speed')} "
          f"graded={report.get('graded_faults')} "
          f"slack_weighted_cov={report.get('sdd_slack_weighted_coverage_pct')}% "
          f"margin_ns={report.get('margin_ns')}", file=sys.stderr)
    if v in ("FAIL", "BLOCKED"):
        for r in report.get("reasons", [])[:3]:
            print(f"  {v}: {r}", file=sys.stderr)
    if v == "NOT_APPLICABLE":
        return 0
    # BLOCKED is NOT a pass. An unmeasured at-speed step must not exit 0.
    return 0 if v == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
