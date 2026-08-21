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

NOT_APPLICABLE IS EARNED, NEVER ASSERTED. `verdict=NOT_APPLICABLE` is a CLAIM
that the design is purely combinational, and the gate asks what it rests on
before honouring it. The producer records `sequential_evidence` derived from the
`ff` groups of the Liberty the flow already reads — a cell's `ff` group is
authoritative, its name is not — and the gate adjudicates:

  * evidence says the design HAS sequential elements -> FAIL. A scan insertion
    that inserted nothing into a sequential design is a failed gate, not an
    inapplicable one. (Measured: 0 of 65 flops detected because the detector
    required a naming convention only some libraries follow; no chain was cut;
    `scan_flops: 0` scored PASS.)
  * evidence authoritatively says it has NONE -> NOT_APPLICABLE (rc 0). A
    genuinely flop-free design must not false-FAIL.
  * no evidence -> BLOCKED (rc 1). The claim was never checked. "We could not
    verify" is now sayable, and it is not a pass.

ABSENT ARTEFACT IS NEVER A PASS. No transition_coverage.json + a not-run record
-> BLOCKED, quoting the recorded reason. No artefact and no record at all ->
FAIL: nothing establishes that the step ever ran.

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
    import fault_atpg_run as _far             # shared zero-flop adjudication
except Exception:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import transition_fault_atpg_run as _tdf  # type: ignore
    import fault_atpg_run as _far             # type: ignore

# Where the producer/runner leaves a record when no coverage artefact could be
# produced. An absent artefact WITH one of these is BLOCKED (the step said why);
# an absent artefact WITHOUT one is FAIL (nothing knows whether it ever ran).
_NOT_RUN_RECORDS = (
    "phase2/stage2/dft/transition_atpg_not_run.json",
    "reports/phase2/dft/transition_atpg_not_run.json",
)


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


def evaluate(blob: Optional[dict], floor: float = TDF_LOGIC_FLOOR_DEFAULT,
             not_run_record: Optional[dict] = None) -> dict:
    """Pure evaluator. Recomputes TDF coverage from raw counts and recomputes
    the verdict against the floor. NEVER trusts a written boolean; NEVER counts
    redundant/aborted as detected. chip-AGNOSTIC.

    `not_run_record` — the producer's own not-run sentinel, when one exists. An
    ABSENT coverage artefact is never a pass, but WHY it is absent decides
    between FAIL and BLOCKED, and the two are different repairs: a step that ran
    and could not measure is blocked on a capability; a step that left no trace
    at all did not run, and nothing knows why."""
    reasons: list[str] = []

    if blob is None:
        if isinstance(not_run_record, dict):
            why = str(not_run_record.get("reason")
                      or "producer recorded a not-run sentinel with no reason")
            stage = not_run_record.get("not_run_stage")
            return {"verdict": "BLOCKED", "status": "BLOCKED",
                    "not_run_stage": stage,
                    "reasons": [
                        "no transition_coverage.json was produced; the step "
                        f"recorded why it did not run{f' ({stage})' if stage else ''}: "
                        + why
                        + " — BLOCKED (the at-speed TDF coverage is unmeasured, "
                          "which is not a pass)"]}
        return {"verdict": "FAIL", "status": "FAIL",
                "reasons": ["transition_coverage.json absent or not valid JSON, "
                            "and NO not-run record was left either — there is no "
                            "evidence the at-speed TDF step ran at all. An "
                            "absent coverage artefact is never a pass; the step "
                            "must produce a measurement or state why it could "
                            "not"]}

    if blob.get("verdict") == "BLOCKED":
        return {"verdict": "BLOCKED", "status": "BLOCKED",
                "scan_flops": blob.get("scan_flops"),
                "sequential_evidence": blob.get("sequential_evidence"),
                "reasons": blob.get("reasons",
                                    ["producer recorded BLOCKED"])}

    # ENGINE_LIMITED — a DOCUMENTED OSS capability gap, SKIPPED-CONDITION (rc 0),
    # NOT a pass and NOT a coverage claim. The at-speed `fault` engine cannot
    # detect flops in a GENERIC (unmapped) yosys netlist (`$_DFF_*` primitives) —
    # the SAME disclosed gap the sibling stuck-at ATPG records (Step 11:
    # cap:atpg_signoff_coverage), and the flow's Step-10 DFT gate already accepts
    # "transition >= target (or DOCUMENTED engine-limited)". Guarded so a design
    # cannot fabricate it: honoured ONLY when the producer attests engine_limited
    # on a `generic_unmapped` netlist that DOES have sequential cells (SEQ_PRESENT)
    # — a flop-free design is NOT_APPLICABLE, and a MAPPED netlist with 0 pairs
    # stays a hard ERROR (the producer never emits ENGINE_LIMITED for it).
    if blob.get("verdict") == "ENGINE_LIMITED":
        _ev = blob.get("sequential_evidence") or {}
        _seq_present = str(_ev.get("verdict", "")).upper() in (
            "HAS_SEQUENTIAL", "SEQ_PRESENT")
        if (blob.get("engine_limited") is True
                and blob.get("pdk_detected") == "generic_unmapped"
                and str(blob.get("capability_flag", "")).startswith("cap:")
                and _seq_present):
            return {"verdict": "SKIPPED-CONDITION", "status": "SKIPPED-CONDITION",
                    "scan_flops": blob.get("scan_flops", 0),
                    "engine_limited": True,
                    "capability_flag": blob.get("capability_flag"),
                    "sequential_evidence": blob.get("sequential_evidence"),
                    "reasons": blob.get("reasons",
                                        ["at-speed TDF ATPG engine-limited on a "
                                         "generic/unmapped netlist — DOCUMENTED "
                                         "OSS capability gap (coverage unmeasured, "
                                         "never claimed)"])}
        # An ENGINE_LIMITED claim missing its attestation is not trustworthy.
        return {"verdict": "BLOCKED", "status": "BLOCKED",
                "scan_flops": blob.get("scan_flops"),
                "sequential_evidence": blob.get("sequential_evidence"),
                "reasons": ["producer claimed ENGINE_LIMITED without the required "
                            "attestation (engine_limited=true + "
                            "pdk_detected=generic_unmapped + cap: flag + "
                            "SEQ_PRESENT evidence) — refusing an unverified skip"]}

    # NOT_APPLICABLE is EARNED, not asserted. "No scan flops, therefore no TDF
    # faults" is only sound on a design that genuinely has no sequential
    # elements — which is checkable, from the `ff` groups of the Liberty the
    # flow already reads. A producer that claims it without that evidence gets
    # BLOCKED; one whose own evidence says the design HAS flops gets FAIL.
    zero_flop = _far.adjudicate_zero_flop_claim(blob)
    if blob.get("verdict") == "NOT_APPLICABLE":
        if zero_flop is not None:
            return zero_flop
        return {"verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                "scan_flops": blob.get("scan_flops", 0),
                "sequential_evidence": blob.get("sequential_evidence"),
                "reasons": blob.get("reasons",
                                    ["producer recorded NOT_APPLICABLE"])}

    if blob.get("verdict") == "ERROR":
        return {"verdict": "FAIL", "status": "FAIL",
                "scan_flops": blob.get("scan_flops"),
                "sequential_evidence": blob.get("sequential_evidence"),
                "reasons": ["producer recorded ERROR (ATPG could not run): "
                            + "; ".join(blob.get("reasons", [])[:2])]}

    # A numeric result is no shelter either: a coverage number computed over a
    # core into which zero flops were cut measures nothing about the scan logic.
    if zero_flop is not None and zero_flop.get("verdict") == "FAIL":
        return zero_flop

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
        "scan_flops": blob.get("scan_flops"),
        "sequential_evidence": blob.get("sequential_evidence"),
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
          floor: float = TDF_LOGIC_FLOOR_DEFAULT) -> dict:
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
          f"scan_flops={report.get('scan_flops')} "
          f"test_cov={report.get('tdf_test_coverage_pct')}% "
          f"detected={report.get('detected')} redundant={report.get('redundant')} "
          f"aborted={report.get('aborted')} floor={report.get('floor_pct')}",
          file=sys.stderr)
    if v in ("FAIL", "BLOCKED"):
        for r in report.get("reasons", [])[:3]:
            print(f"  {v}: {r}", file=sys.stderr)
    if v == "NOT_APPLICABLE":
        return 0
    # SKIPPED-CONDITION is the DOCUMENTED engine-limited outcome (generic/unmapped
    # netlist — the OSS at-speed engine cannot detect its flops; the Step-10 DFT
    # gate accepts "DOCUMENTED engine-limited"). It is emitted ONLY behind the
    # evaluate() attestation guard, never a coverage claim.
    if v == "SKIPPED-CONDITION":
        for r in report.get("reasons", [])[:2]:
            print(f"  SKIPPED-CONDITION: {r}", file=sys.stderr)
        return 0
    # BLOCKED is NOT a pass. An unmeasured at-speed step must not exit 0.
    return 0 if v == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
