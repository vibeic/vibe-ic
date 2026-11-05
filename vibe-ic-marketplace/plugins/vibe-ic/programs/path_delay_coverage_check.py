#!/usr/bin/env python3
"""path_delay_coverage_check.py — REAL at-speed PATH-DELAY-FAULT (PDF) coverage
gate for the timing-graded ATPG step (DT2).

ANTI-FABRICATION checker. Like the transition gate `transition_coverage_check`,
this does NOT trust the boolean the producing step wrote. It INDEPENDENTLY
re-derives PDF coverage from the per-path SAT verdicts in
reports/phase2/dft/path_delay_coverage.json and recomputes:

    sensitised          = #paths with loc_testable AND nr_verdict == 'DET'
    robust              = #sensitised with robust_verdict == 'DET'
    graded              = #paths with loc_testable
    false_held          = #graded with nr_verdict == 'RED' (SAT-proven redundant)
    testable            = graded - false_held         (redundant excluded)
    pdf_sensitised_cov  = sensitised / testable        (recomputed here)
    PASS iff pdf_sensitised_cov >= floor

    TEST-coverage denominator, identical to DT1 (`transition_coverage_check`):
    SAT-proven-redundant (false/held) paths are excluded from the denominator
    exactly as DT1 excludes redundant stuck-at faults — a provably-unsensitisable
    at-speed path has no 2-pattern by definition. ABORTED (SAT-undecided) paths
    STAY in the denominator as non-covered (conservative, mirrors DT1's aborted).

FALSE-CLEAN-PROOF (the crux): a path is counted covered ONLY when its RECORDED
non-robust SAT verdict is exactly 'DET' (a real `model found: FAIL!` 2-pattern).
A FALSE / HELD path (nr_verdict 'RED' = `no model found: SUCCESS!`), an ABORT,
or an UNMAPPABLE path is NEVER in the numerator. A path is 'robust' ONLY when
its OWN robust-miter verdict is 'DET' — a non-robust path can never be
mislabelled robust. If the producer's top-level `sensitised_paths` exceeds the
per-path recount, `sensitised_count_mismatch` is surfaced and the RECOMPUTED
(lower) number governs. A run with zero verdicts (SAT never ran) FAILs.

NOT_APPLICABLE (honest, never a fake pass): the producer records
NOT_APPLICABLE when the real timing model (routed netlist + SPEF + SDC) is
absent, or the design is combinational (no scan flops), or no LOC-launchable
path exists. The gate passes that through (rc 0) — self-skipping. A design that
SHOULD have timing but produced no evidence FAILs.

CHOSEN FLOOR: default 80 % PDF sensitised coverage over the top-K longest paths
— DISCLOSED. K is disclosed by the producer. This grades that each timing-
critical path has a REAL sensitising launch-capture 2-pattern; false/held paths
are correctly excluded (not fabricated). The floor is never relaxed below the
producer's own (effective = max(written_floor, --floor default)).

Usage:
    python3 path_delay_coverage_check.py <project_dir> [--json OUT]
                                         [--coverage-json PATH] [--floor 80]

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
    import path_delay_fault_atpg_run as _pdf  # reuse the pure coverage math
    import fault_atpg_run as _far             # shared zero-flop adjudication
except Exception:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import path_delay_fault_atpg_run as _pdf  # type: ignore
    import fault_atpg_run as _far             # type: ignore


# Where the phase3 producer leaves a record when no coverage artefact could be
# produced (vibe-ic#235). An absent artefact WITH one of these is BLOCKED (the
# step said why); an absent artefact WITHOUT one is FAIL (nothing knows whether
# it ever ran). Mirrors transition_coverage_check's DT1 channel.
_NOT_RUN_RECORDS = (
    "phase2/stage2/dft/path_delay_atpg_not_run.json",
    "reports/phase2/dft/path_delay_atpg_not_run.json",
)

_PROGRAM = "path_delay_coverage_check"
_VERSION = "1.0.0"
PDF_FLOOR_DEFAULT = 80.0


def _load_json(path: Path) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _recount(records: list) -> dict:
    """Independently recount PDF outcomes from the per-path list — this is what
    makes the gate un-gameable: it does not trust the producer's top-level
    `sensitised_paths`. A path is counted covered ONLY if it is loc_testable and
    its non-robust verdict is exactly 'DET'; robust ONLY if the robust verdict
    is 'DET'. Pure."""
    graded = sensitised = robust = false_held = aborted = 0
    for r in records:
        if not isinstance(r, dict) or not r.get("loc_testable"):
            continue
        graded += 1
        nr = r.get("nr_verdict")
        rv = r.get("robust_verdict")
        if nr == "DET":
            sensitised += 1
            if rv == "DET":
                robust += 1
        elif nr == "RED":
            false_held += 1
        else:
            aborted += 1
    return {"graded": graded, "sensitised": sensitised, "robust": robust,
            "false_held": false_held, "aborted": aborted}


def evaluate(blob: Optional[dict], floor: float = PDF_FLOOR_DEFAULT,
             not_run_record: Optional[dict] = None) -> dict:
    """Pure evaluator. Recomputes PDF coverage from per-path SAT verdicts and
    re-derives the verdict against the floor. NEVER trusts a written boolean;
    NEVER counts a false/held/aborted/unmappable path as covered. chip-AGNOSTIC.

    `not_run_record` — the producer's own not-run sentinel, when one exists
    (vibe-ic#235). An ABSENT coverage artefact is never a pass, but WHY it is
    absent decides between FAIL and BLOCKED, and the two are different repairs:
    a step that ran and could not measure is blocked on an input or a
    capability; a step that left no trace at all did not run, and nothing knows
    why. Without this branch the two are one indistinguishable state on disk.
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
                        "no path_delay_coverage.json was produced; the step "
                        f"recorded why it did not run"
                        f"{f' ({stage})' if stage else ''}: " + why
                        + " — BLOCKED (the at-speed PDF coverage is unmeasured, "
                          "which is not a pass)"]}
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["path_delay_coverage.json absent or invalid JSON, "
                            "and NO not-run record was left either — there is "
                            "no evidence the at-speed PDF step ran at all. An "
                            "absent coverage artefact is never a pass; the step "
                            "must produce a measurement or state why it could "
                            "not"]}

    if blob.get("verdict") == "BLOCKED":
        return {"verdict": "BLOCKED", "status": "BLOCKED",
                "scan_flops": blob.get("scan_flops"),
                "sequential_evidence": blob.get("sequential_evidence"),
                "reasons": blob.get("reasons", ["producer recorded BLOCKED"])}

    if blob.get("verdict") == "NOT_APPLICABLE":
        # A PDF self-skip has two legitimate grounds: no post-layout timing
        # model yet (established from file presence, and checked there), or a
        # genuinely combinational design. Only the SECOND rests on a flop count,
        # so only a blob that actually carries sequential evidence is
        # adjudicated — otherwise the pre-layout self-skip would false-FAIL.
        if isinstance(blob.get("sequential_evidence"), dict):
            override = _far.adjudicate_zero_flop_claim(blob)
            if override is not None:
                return override
        return {"verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                "scan_flops": blob.get("scan_flops", 0),
                "sequential_evidence": blob.get("sequential_evidence"),
                "reasons": blob.get("reasons",
                                    ["producer recorded NOT_APPLICABLE"])}

    if blob.get("verdict") == "ERROR":
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["producer recorded ERROR (PDF ATPG could not run): "
                            + "; ".join(blob.get("reasons", [])[:2])]}

    written_floor = blob.get("floor_pct")
    eff_floor = floor
    if isinstance(written_floor, (int, float)):
        eff_floor = max(float(written_floor), floor)

    records = blob.get("path_records")
    if not isinstance(records, list) or not records:
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["no per-path PDF records present — the SAT "
                            "sensitisation did not run; cannot pass on zero "
                            "evidence"]}

    rc = _recount(records)
    graded = rc["graded"]
    if graded == 0:
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["no LOC-testable graded paths in the record list — "
                            "cannot pass on zero evidence"]}

    testable = graded - rc["false_held"]  # exclude SAT-proven-redundant (DT1 parity)
    sens_cov = (round(100.0 * rc["sensitised"] / testable, 4)
                if testable > 0 else None)
    robust_cov = (round(100.0 * rc["robust"] / testable, 4)
                  if testable > 0 else None)

    written_sens = blob.get("sensitised_paths")
    sensitised_count_mismatch = (
        isinstance(written_sens, int) and written_sens != rc["sensitised"])
    if sensitised_count_mismatch:
        reasons.append(
            f"producer wrote sensitised_paths={written_sens} but the per-path "
            f"recount is {rc['sensitised']} (false/held/aborted counted as "
            "sensitised) — recomputed number governs")

    ge_floor = (sens_cov is not None and sens_cov >= eff_floor)
    if not ge_floor:
        reasons.append(
            f"recomputed PDF sensitised coverage {sens_cov}% < floor "
            f"{eff_floor}% (sensitised {rc['sensitised']} / testable {testable}; "
            f"{graded} graded; robust {rc['robust']}; false/held "
            f"{rc['false_held']} excluded; aborted {rc['aborted']} counted "
            "as non-covered)")

    return {
        "floor_pct": eff_floor,
        "graded_paths": graded,
        "testable_paths": testable,
        "sensitised_paths": rc["sensitised"],
        "robust_paths": rc["robust"],
        "non_robust_paths": rc["sensitised"] - rc["robust"],
        "false_or_held_paths": rc["false_held"],
        "aborted_paths": rc["aborted"],
        "pdf_sensitised_coverage_pct": sens_cov,
        "pdf_robust_coverage_pct": robust_cov,
        "recomputed_ge_floor": ge_floor,
        "sensitised_count_mismatch": sensitised_count_mismatch,
        "k_selected": blob.get("k_selected"),
        "verdict": "PASS" if ge_floor else "FAIL",
        "status": "PASS" if ge_floor else "FAIL",
        "reasons": reasons,
    }


def _resolve_coverage_json(project: Path, override: Optional[str]) -> Optional[Path]:
    cands = []
    if override:
        cands.append(Path(override))
    else:
        if _pl is not None:
            cands.append(_pl.report_path(project, "dft/path_delay_coverage.json"))
        cands.append(project / "reports/phase2/dft/path_delay_coverage.json")
        cands.append(project / "reports/dft/path_delay_coverage.json")
    return next((p for p in cands if p.is_file()), None)


def _resolve_not_run_record(project: Path) -> tuple[Optional[dict], Optional[Path]]:
    """Find the step's own record of why it produced no coverage artefact."""
    for rel in _NOT_RUN_RECORDS:
        p = project / rel
        if p.is_file():
            d = _load_json(p)
            if d is not None:
                return d, p
    return None, None


def audit(project: Path, coverage_json: Optional[str] = None,
          floor: float = PDF_FLOOR_DEFAULT) -> dict:
    path = _resolve_coverage_json(project, coverage_json)
    blob = _load_json(path) if path else None
    rec, rec_path = (_resolve_not_run_record(project) if blob is None
                     else (None, None))
    base = {"program": _PROGRAM, "version": _VERSION,
            "project_dir": str(project),
            "coverage_json": str(path) if path else None,
            "not_run_record": str(rec_path) if rec_path else None}
    result = evaluate(blob, floor=floor, not_run_record=rec)
    result.update(base)
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="At-speed path-delay-fault coverage gate — recomputes "
                    "sensitised/graded >= floor from per-path SAT verdicts; "
                    "never counts a false/held/aborted path as covered")
    ap.add_argument("project_dir")
    ap.add_argument("--coverage-json", default=None,
                    help="Explicit path_delay_coverage.json path")
    ap.add_argument("--floor", type=float, default=PDF_FLOOR_DEFAULT,
                    help=f"PDF sensitised-coverage floor %% (default "
                         f"{PDF_FLOOR_DEFAULT:.0f}; chosen, DISCLOSED)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = audit(project, args.coverage_json, floor=args.floor)
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
          f"sens_cov={report.get('pdf_sensitised_coverage_pct')}% "
          f"sensitised={report.get('sensitised_paths')}/"
          f"{report.get('graded_paths')} robust={report.get('robust_paths')} "
          f"floor={report.get('floor_pct')}", file=sys.stderr)
    if v in ("FAIL", "BLOCKED"):
        for r in report.get("reasons", [])[:3]:
            print(f"  {v}: {r}", file=sys.stderr)
    if v == "NOT_APPLICABLE":
        return 0
    # BLOCKED is NOT a pass. An unmeasured at-speed step must not exit 0.
    return 0 if v == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
