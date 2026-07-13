#!/usr/bin/env python3
"""transition_coverage_check.py — REAL transition-delay-fault (TDF) coverage
gate for the LOC at-speed ATPG step.

ANTI-FABRICATION checker for the transition (at-speed) DFT step. Like the
stuck-at gate `dft_atpg_coverage_check.py`, this does NOT trust the boolean
the producing step wrote. It INDEPENDENTLY re-derives the coverage from the
RAW verdict counts (detected / redundant / aborted) in
reports/phase2/dft/transition_coverage.json and recomputes:

    tdf_test_coverage = detected / (sampled - redundant)      (recomputed here)
    PASS iff tdf_test_coverage >= floor

FALSE-CLEAN-PROOF (the crux): a REDUNDANT or ABORTED fault is NEVER counted
as detected. The gate recomputes `detected` only from faults whose recorded
verdict is exactly `DET`, and cross-checks it against the top-level `detected`
count; a mismatch (i.e. the producer inflated detected by counting redundant/
aborted faults) is surfaced as `detected_count_mismatch` and the RECOMPUTED
(lower) number governs. So a run that counts redundant faults as detected —
or that never actually ran the SAT solver (0 verdicts) — FAILs.

NOT_APPLICABLE (honest, never a fake pass): when the producer recorded
`verdict=NOT_APPLICABLE` (a purely combinational design with no scan flops has
no launch-off-capture transition faults), the gate resolves to NOT_APPLICABLE
(rc 0) — self-skipping on non-applicable designs. A design that SHOULD have
scan but produced no evidence FAILs (missing evidence, not a skip).

CHOSEN FLOOR: default 90 % TDF LOGIC coverage — DISCLOSED as a chosen floor.
This grades that each transition was LAUNCHED and OBSERVED; it is NOT at-speed
timing-graded (true path-delay grading needs OpenSTA K-longest-path
sensitisation — deferred). The floor is configurable via --floor and never
relaxed below what the producer wrote (effective = max(written_floor, --floor
default)).

Usage:
    python3 transition_coverage_check.py <project_dir> [--json <out>]
                                         [--coverage-json PATH] [--floor 90]

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.
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
    import transition_fault_atpg_run as _tdf  # reuse the pure coverage math
except Exception:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import transition_fault_atpg_run as _tdf  # type: ignore


_PROGRAM = "transition_coverage_check"
_VERSION = "1.0.0"
TDF_LOGIC_FLOOR_DEFAULT = 90.0


def _load_json(path: Path) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _recount_from_fault_list(blob: dict):
    """Independently recount DET/RED/ABORT from the per-fault verdict list —
    this is what makes the gate un-gameable: it does not trust the producer's
    top-level `detected` field. Returns (det, red, abort) or None if there is
    no usable fault list."""
    fl = blob.get("fault_list")
    if not isinstance(fl, list) or not fl:
        return None
    det = red = abort = 0
    for f in fl:
        v = (f or {}).get("verdict")
        if v == "DET":
            det += 1
        elif v == "RED":
            red += 1
        else:
            abort += 1
    return det, red, abort


def evaluate(blob: Optional[dict], floor: float = TDF_LOGIC_FLOOR_DEFAULT) -> dict:
    """Pure evaluator. Recomputes TDF coverage from raw counts and recomputes
    the verdict against the floor. NEVER trusts a written boolean; NEVER counts
    redundant/aborted as detected. chip-AGNOSTIC."""
    reasons: list[str] = []

    if blob is None:
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["transition_coverage.json absent or not valid JSON "
                            "— the at-speed TDF step cannot pass without a real "
                            "coverage measurement"]}

    # Honest NOT_APPLICABLE passthrough (no scan flops → no TDF faults).
    if blob.get("verdict") == "NOT_APPLICABLE":
        return {"verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                "scan_flops": blob.get("scan_flops", 0),
                "reasons": blob.get("reasons",
                                    ["producer recorded NOT_APPLICABLE"])}

    if blob.get("verdict") == "ERROR":
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["producer recorded ERROR (ATPG could not run): "
                            + "; ".join(blob.get("reasons", [])[:2])]}

    # Effective floor: never below the producer's chosen floor.
    written_floor = blob.get("floor_pct")
    eff_floor = floor
    if isinstance(written_floor, (int, float)):
        eff_floor = max(float(written_floor), floor)

    # Prefer the un-gameable per-fault recount; fall back to raw count fields.
    recount = _recount_from_fault_list(blob)
    if recount is not None:
        det, red, abort = recount
        source = "fault_list recount"
    else:
        det = int(blob.get("detected") or 0)
        red = int(blob.get("redundant") or 0)
        abort = int(blob.get("aborted") or 0)
        source = "raw count fields"

    sampled = det + red + abort
    if sampled == 0:
        return {"verdict": "FAIL", "status": "FAIL",
                "count_source": source,
                "reasons": ["no TDF fault verdicts present (detected=redundant="
                            "aborted=0) — the SAT ATPG did not actually run; "
                            "cannot pass on zero evidence"]}

    cov = _tdf.coverage_math(det, red, abort)
    test_cov = cov["tdf_test_coverage_pct"]

    # Cross-check: did the producer inflate `detected` beyond the recount?
    written_detected = blob.get("detected")
    detected_count_mismatch = (
        isinstance(written_detected, int) and recount is not None
        and written_detected != det)
    if detected_count_mismatch:
        reasons.append(
            f"producer wrote detected={written_detected} but the per-fault "
            f"list recounts detected={det} (redundant/aborted were counted as "
            "detected) — recomputed number governs")

    ge_floor = (test_cov is not None and test_cov >= eff_floor)
    if not ge_floor:
        reasons.append(
            f"recomputed TDF logic test-coverage {test_cov}% < floor "
            f"{eff_floor}% (detected {det} / testable {cov['testable_faults']}; "
            f"redundant {red} excluded, aborted {abort} counted as undetected)")

    out = {
        "count_source": source,
        "floor_pct": eff_floor,
        "recomputed_ge_floor": ge_floor,
        "detected_count_mismatch": detected_count_mismatch,
        "verdict": "PASS" if ge_floor else "FAIL",
        "status": "PASS" if ge_floor else "FAIL",
        "reasons": reasons,
    }
    out.update(cov)
    return out


def _resolve_coverage_json(project: Path, override: Optional[str]) -> Optional[Path]:
    cands = []
    if override:
        cands.append(Path(override))
    else:
        if _pl is not None:
            cands.append(_pl.report_path(project, "dft/transition_coverage.json"))
        cands.append(project / "reports/phase2/dft/transition_coverage.json")
        cands.append(project / "reports/dft/transition_coverage.json")
    return next((p for p in cands if p.is_file()), None)


def audit(project: Path, coverage_json: Optional[str] = None,
          floor: float = TDF_LOGIC_FLOOR_DEFAULT) -> dict:
    path = _resolve_coverage_json(project, coverage_json)
    base = {"program": _PROGRAM, "version": _VERSION,
            "project_dir": str(project),
            "coverage_json": str(path) if path else None}
    blob = _load_json(path) if path else None
    result = evaluate(blob, floor=floor)
    result.update(base)
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Transition (at-speed) TDF coverage gate — recomputes "
                    "detected/(sampled-redundant) >= floor; never counts "
                    "redundant/aborted as detected")
    ap.add_argument("project_dir")
    ap.add_argument("--coverage-json", default=None,
                    help="Explicit transition_coverage.json path")
    ap.add_argument("--floor", type=float, default=TDF_LOGIC_FLOOR_DEFAULT,
                    help=f"TDF logic-coverage floor %% (default "
                         f"{TDF_LOGIC_FLOOR_DEFAULT:.0f}; chosen, DISCLOSED; "
                         "at-speed timing grading deferred)")
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
          f"test_cov={report.get('tdf_test_coverage_pct')}% "
          f"detected={report.get('detected')} redundant={report.get('redundant')} "
          f"aborted={report.get('aborted')} floor={report.get('floor_pct')}",
          file=sys.stderr)
    if v == "NOT_APPLICABLE":
        return 0
    return 0 if v == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
