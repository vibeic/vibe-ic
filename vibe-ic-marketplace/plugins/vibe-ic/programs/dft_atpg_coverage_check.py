#!/usr/bin/env python3
"""dft_atpg_coverage_check.py — REAL stuck-at coverage gate (Step 11 DFT/ATPG).

ANTI-FABRICATION checker for flow Step 11. The old gate trusted the
self-produced boolean `stuck_at_ge_target` that the *producing* step
(fault_atpg_run / a runner) wrote into reports/phase2/dft/coverage.json —
i.e. the step asserted its own PASS. A run that emitted

    {"stuck_at_ge_target": true, "stuck_at_coverage_percent": 0.0,
     "stuck_at_target": 50.0}

would have sailed through even though the netlist had NO scan chain and
0% real stuck-at coverage — a silicon DFT-deficit that ships untestable
parts.

This checker does NOT re-echo that boolean. It independently parses the
ATPG artefact(s), reads the REAL measured stuck-at coverage number and
the REAL target, and recomputes the verdict:

    PASS iff measured_coverage_pct >= target_pct   (recomputed here)

It accepts the two coverage.json schemas seen in the wild — the
fault_atpg_run schema (`coverage_pct` / `target_pct`) and the
runner/skill schema (`stuck_at_coverage_percent` / `stuck_at_target`) —
plus a fallback that parses the human-readable atpg_coverage.rpt. The
written `stuck_at_ge_target` field is ONLY used as a cross-check: a
mismatch between the recomputed verdict and the written boolean is
surfaced as `self_assertion_mismatch` in the report (the recomputed
number always wins).

Honest-failure rules (NO vacuous pass on absence):
  * coverage.json (and atpg_coverage.rpt) both absent          → FAIL (rc=1)
  * present but no measured coverage number can be extracted   → FAIL (rc=1)
  * present but no target can be extracted                     → FAIL (rc=1)
  * measured < target                                          → FAIL (rc=1)
  * measured >= target                                         → PASS (rc=0)

There is no SKIP path: Step 11 applies to every digital design that
reaches synthesis. A design with no sequential logic still has a
combinational stuck-at coverage number; absence of the report is a
missing-evidence FAIL, not a not-applicable SKIP.

FOUNDRY-GRADE FLOOR (2026-07 DFT-depth raise): the checker no longer
trusts a lenient written target. It enforces a FOUNDRY floor (default
95 %, configurable via --foundry-floor / down for legacy) so a producing
step that writes `target_pct: 50` (or the old 80 %) can no longer pass a
sub-foundry number. The effective target is:

    effective_target = max(written_target, foundry_floor)

    PASS iff measured_coverage_pct >= effective_target

This closes the loophole where a below-foundry coverage sailed through
only because the artefact carried a lax self-chosen target. §4.05: the
floor RAISES the bar (never relaxes it) — a design below the foundry bar
FAILs honestly instead of shipping untestable silicon.

Usage:
    python3 dft_atpg_coverage_check.py <project_dir> [--json <out>]
    python3 dft_atpg_coverage_check.py <project_dir> [--coverage-json PATH]
    python3 dft_atpg_coverage_check.py <project_dir> [--foundry-floor 98]

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.

chip-AGNOSTIC: reads only the generic coverage.json / atpg_coverage.rpt
schemas; no design-specific knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None

try:
    import dft_signoff_common
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dft_signoff_common  # type: ignore


_PROGRAM = "dft_atpg_coverage_check"
_VERSION = "1.1.0"

# Foundry / ATE sign-off floor. A written target below this is clamped UP so
# a lenient self-chosen target cannot pass a sub-foundry coverage number.
FOUNDRY_FLOOR_DEFAULT = 95.0

# Field names that may hold the REAL measured stuck-at coverage (%) — in
# priority order. fault_atpg_run writes `coverage_pct`; the runner/skill
# JSON writes `stuck_at_coverage_percent`. We never read
# `stuck_at_ge_target` for the number.
_MEASURED_FIELDS = (
    "coverage_pct",
    "stuck_at_coverage_percent",
    "stuck_at_coverage_pct",
    "coverage_percent",
    "stuck_at_pct",
)

# Field names that may hold the REAL target/min coverage (%) — priority order.
_TARGET_FIELDS = (
    "target_pct",
    "stuck_at_target",
    "target_percent",
    "min_coverage",
    "target",
)


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _as_pct(val: Any) -> Optional[float]:
    """Coerce a number to a percentage. A fractional value in [0,1] is
    treated as a ratio and scaled to %; anything > 1 is taken as already-%.
    Returns None if not coercible."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return None
    # Heuristic: ratios are <= 1.0; percentages can exceed 1.0. A genuine
    # 1.0 is ambiguous (1% vs 100%) but in stuck-at practice "1.0" stored
    # as a ratio means 100% and a 1% coverage would be stored as "1.0"%
    # only in degenerate runs — fault_atpg_run already normalises ratio→%
    # before writing, so the JSON path almost always carries a %. We only
    # scale strictly-less-than-1 values, leaving 1.0 as 1.0% (conservative:
    # the lower interpretation never produces a false PASS).
    if f < 1.0:
        return f * 100.0
    return f


def _extract_number(blob: dict, fields: Tuple[str, ...]) -> Tuple[Optional[float], Optional[str]]:
    """Return (pct, source_field) for the first present, coercible field."""
    for fld in fields:
        if fld in blob and blob[fld] is not None:
            pct = _as_pct(blob[fld])
            if pct is not None:
                return pct, fld
    return None, None


# ── Human-readable .rpt fallback parsers ───────────────────────────────
# Two rpt dialects exist:
#   fault_atpg_run.py:   "Stuck-at %    : 81.72"  +  "Target (min)  : 55.00"
#   runner/skill .rpt:   "Stuck-at coverage reached  : 0.0% (target was ≥50%)"
_RPT_MEASURED_PATTERNS = (
    re.compile(r"Stuck-at\s*%\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
    re.compile(r"Stuck-at\s+coverage\s+reached\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
    re.compile(r"stuck_at_coverage\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
)
_RPT_TARGET_PATTERNS = (
    re.compile(r"Target\s*\(min\)\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
    re.compile(r"target\s+was\s*[>≥]=?\s*([0-9]+(?:\.[0-9]+)?)\s*%?", re.IGNORECASE),
    re.compile(r"target\s*[>≥]=?\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
)


def _parse_rpt(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Return (measured_pct, target_pct) parsed from an atpg_coverage.rpt."""
    measured: Optional[float] = None
    for pat in _RPT_MEASURED_PATTERNS:
        m = pat.search(text)
        if m:
            measured = float(m.group(1))
            break
    target: Optional[float] = None
    for pat in _RPT_TARGET_PATTERNS:
        m = pat.search(text)
        if m:
            target = float(m.group(1))
            break
    return measured, target


def evaluate(coverage_json: Optional[dict],
             rpt_text: Optional[str],
             foundry_floor: float = FOUNDRY_FLOOR_DEFAULT) -> dict:
    """Pure evaluator. Independently derives measured + target stuck-at
    coverage from the artefact(s) and recomputes the verdict against a
    FOUNDRY floor. NEVER trusts a written boolean, and NEVER trusts a
    written target below the foundry floor. Returns a verdict dict.

    effective_target = max(written_target, foundry_floor)
    PASS iff measured >= effective_target.

    chip-AGNOSTIC."""
    reasons: List[str] = []

    measured: Optional[float] = None
    measured_src: Optional[str] = None
    target: Optional[float] = None
    target_src: Optional[str] = None

    if coverage_json is not None:
        measured, measured_src = _extract_number(coverage_json, _MEASURED_FIELDS)
        target, target_src = _extract_number(coverage_json, _TARGET_FIELDS)

    # Fall back to the human-readable report for whatever is still missing.
    if rpt_text and (measured is None or target is None):
        rpt_measured, rpt_target = _parse_rpt(rpt_text)
        if measured is None and rpt_measured is not None:
            measured = rpt_measured
            measured_src = "atpg_coverage.rpt"
        if target is None and rpt_target is not None:
            target = rpt_target
            target_src = "atpg_coverage.rpt"

    # The boolean the producing step asserted — used ONLY for cross-check.
    self_asserted = None
    if coverage_json is not None and "stuck_at_ge_target" in coverage_json:
        self_asserted = bool(coverage_json.get("stuck_at_ge_target"))

    # Honest-failure on insufficient substance.
    if measured is None:
        reasons.append(
            "no measured stuck-at coverage number found in coverage.json "
            f"(looked for {list(_MEASURED_FIELDS)}) or atpg_coverage.rpt")
    if target is None:
        reasons.append(
            "no stuck-at coverage target found in coverage.json "
            f"(looked for {list(_TARGET_FIELDS)}) or atpg_coverage.rpt")

    # FOUNDRY floor: clamp the written target UP so a lenient self-chosen
    # target cannot pass a sub-foundry number. A missing written target still
    # FAILs above (insufficient substance) — the floor only ever RAISES the
    # bar, it never invents a target to make an under-specified run pass.
    effective_target: Optional[float] = None
    floor_governs = False
    if target is not None:
        effective_target = max(target, foundry_floor)
        floor_governs = foundry_floor > target
        if floor_governs:
            reasons.append(
                f"written target {target:.2f}% is below the foundry floor "
                f"{foundry_floor:.2f}% — foundry floor governs "
                f"(effective target {effective_target:.2f}%)")

    recomputed_ge_target: Optional[bool] = None
    if measured is not None and effective_target is not None:
        recomputed_ge_target = measured >= effective_target
        if not recomputed_ge_target:
            reasons.append(
                f"measured stuck-at coverage {measured:.2f}% < "
                f"effective target {effective_target:.2f}% "
                f"(written {target:.2f}%, foundry floor {foundry_floor:.2f}%) "
                f"— DFT/ATPG coverage below required foundry floor "
                f"(untestable silicon)")

    # Cross-check the self-asserted boolean against our recomputation.
    self_assertion_mismatch = (
        recomputed_ge_target is not None
        and self_asserted is not None
        and recomputed_ge_target != self_asserted
    )
    if self_assertion_mismatch:
        reasons.append(
            f"self-asserted stuck_at_ge_target={self_asserted} contradicts "
            f"recomputed {recomputed_ge_target} from measured "
            f"{measured:.2f}% vs effective target {effective_target:.2f}% — "
            f"boolean ignored, recomputed verdict governs")

    verdict = "PASS" if recomputed_ge_target is True else "FAIL"

    return {
        "measured_coverage_pct": (round(measured, 4)
                                  if measured is not None else None),
        "measured_source": measured_src,
        "target_pct": round(target, 4) if target is not None else None,
        "target_source": target_src,
        "foundry_floor_pct": round(foundry_floor, 4),
        "effective_target_pct": (round(effective_target, 4)
                                 if effective_target is not None else None),
        "foundry_floor_governs": floor_governs,
        "recomputed_ge_target": recomputed_ge_target,
        "self_asserted_ge_target": self_asserted,
        "self_assertion_mismatch": self_assertion_mismatch,
        "verdict": verdict,
        "status": verdict,
        "reasons": reasons,
    }


def _resolve_paths(project: Path,
                   coverage_json_override: Optional[str]) -> Tuple[List[Path], List[Path]]:
    """Return (coverage_json_candidates, rpt_candidates) in priority order.

    Canonical coverage.json: reports/phase2/dft/coverage.json (matches the
    flow YAML + fault_atpg_run's report_path(dft/coverage.json) routing).
    Older flat layout reports/dft/coverage.json is accepted as a fallback.
    """
    cov_candidates: List[Path] = []
    if coverage_json_override:
        cov_candidates.append(Path(coverage_json_override))
    else:
        if _pl is not None:
            cov_candidates.append(_pl.report_path(project, "dft/coverage.json"))
            cov_candidates.append(_pl.reports_phase2_dir(project) / "dft" / "coverage.json")
        cov_candidates.append(project / "reports" / "phase2" / "dft" / "coverage.json")
        cov_candidates.append(project / "reports" / "dft" / "coverage.json")

    rpt_candidates: List[Path] = []
    if _pl is not None:
        rpt_candidates.append(_pl.dft_dir(project) / "atpg_coverage.rpt")
    rpt_candidates.append(project / "phase2" / "stage2" / "dft" / "atpg_coverage.rpt")
    rpt_candidates.append(project / "dft" / "atpg_coverage.rpt")

    # De-dup preserving order.
    def _dedup(paths: List[Path]) -> List[Path]:
        seen = set()
        out = []
        for p in paths:
            key = str(p)
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    return _dedup(cov_candidates), _dedup(rpt_candidates)


def _has_measurable_coverage(project: Path,
                             coverage_json_override: Optional[str]) -> bool:
    """True iff a REAL measurable coverage artefact is present: a
    coverage.json or atpg_coverage.rpt exists AND — for a coverage.json — it
    does not self-report faults_total==0 (which means the engine never
    enumerated a single fault, i.e. it did not run). Used ONLY to GUARD the
    disclosed-skip path so a real run (measurable coverage present) can NEVER
    take the skip. A present-but-low coverage counts as measurable and is
    judged normally (still FAILs)."""
    cov_candidates, rpt_candidates = _resolve_paths(project, coverage_json_override)
    if any(p.is_file() for p in rpt_candidates):
        return True
    cov_path = next((p for p in cov_candidates if p.is_file()), None)
    if cov_path is not None:
        data = _load_json(cov_path)
        if isinstance(data, dict) and data.get("faults_total") == 0:
            return False  # engine-did-not-run (0 faults enumerated)
        return True
    return False


def audit(project: Path,
          coverage_json_override: Optional[str] = None,
          foundry_floor: float = FOUNDRY_FLOOR_DEFAULT) -> dict:
    cov_candidates, rpt_candidates = _resolve_paths(project, coverage_json_override)

    cov_path = next((p for p in cov_candidates if p.is_file()), None)
    rpt_path = next((p for p in rpt_candidates if p.is_file()), None)

    base = {
        "program": _PROGRAM,
        "version": _VERSION,
        "project_dir": str(project),
        "coverage_json": str(cov_path) if cov_path else None,
        "atpg_rpt": str(rpt_path) if rpt_path else None,
    }

    if cov_path is None and rpt_path is None:
        # No evidence at all → honest FAIL (NOT a vacuous pass on absence).
        base.update({
            "measured_coverage_pct": None,
            "target_pct": None,
            "recomputed_ge_target": None,
            "foundry_floor_pct": round(foundry_floor, 4),
            "verdict": "FAIL",
            "status": "FAIL",
            "reasons": [
                "no DFT/ATPG coverage evidence found: neither "
                f"coverage.json ({cov_candidates[0]}) nor "
                f"atpg_coverage.rpt ({rpt_candidates[0]}) exists — "
                "Step 11 cannot pass without a real stuck-at coverage "
                "measurement"
            ],
        })
        return base

    coverage_json = _load_json(cov_path) if cov_path else None
    if cov_path is not None and coverage_json is None:
        base["reasons_prefix"] = [
            f"coverage.json present but not valid JSON: {cov_path}"]
    rpt_text = None
    if rpt_path is not None:
        try:
            rpt_text = rpt_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            rpt_text = None

    result = evaluate(coverage_json, rpt_text, foundry_floor=foundry_floor)
    # Surface a JSON-parse note as a leading reason if applicable.
    if base.get("reasons_prefix"):
        result["reasons"] = base.pop("reasons_prefix") + result.get("reasons", [])
    result.update(base)
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 11 DFT/ATPG real stuck-at coverage gate "
                    "(recomputes coverage >= target; ignores self-asserted bool)")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--coverage-json", default=None,
                    help="Explicit path to coverage.json (overrides auto-resolve)")
    ap.add_argument("--foundry-floor", type=float, default=FOUNDRY_FLOOR_DEFAULT,
                    help="Foundry/ATE stuck-at coverage floor %% — the effective "
                         "target is max(written_target, floor). Default "
                         f"{FOUNDRY_FLOOR_DEFAULT:.0f}%%. Raising it (e.g. 98) "
                         "tightens the bar; a lenient written target can never "
                         "drop below it.")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # HONEST disclosed-skip (flow step-11): when the OSS Fault ATPG engine
    # genuinely could not MEASURE sign-off coverage on this netlist form AND
    # the runner honestly self-reported the skip via a sibling
    # dft_atpg_not_run.json (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION), AND no
    # measurable coverage artefact exists, resolve to SKIPPED-CONDITION
    # (rc=2 → VACUOUS_PASS) instead of a hard missing-evidence FAIL. Guarded
    # on BOTH conditions — a real run (measurable coverage present) NEVER
    # takes this path, so a real low coverage still FAILs.
    _skip = dft_signoff_common.disclosed_atpg_skip(project)
    if _skip is not None and not _has_measurable_coverage(project, args.coverage_json):
        print(f"{_PROGRAM}: SKIPPED-CONDITION — DFT ATPG disclosed-skipped: "
              f"{_skip}")
        if args.json:
            try:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps({
                    "program": _PROGRAM,
                    "version": _VERSION,
                    "project_dir": str(project),
                    "verdict": "SKIPPED-CONDITION",
                    "status": "SKIPPED-CONDITION",
                    "reason": _skip,
                    "reasons": [f"DFT ATPG disclosed-skipped: {_skip} — no "
                                "measurable stuck-at coverage artefact and a "
                                "sibling sentinel honestly self-reports the "
                                "skip"],
                }, indent=2, ensure_ascii=False) + "\n")
            except Exception as exc:  # pragma: no cover - IO edge
                print(f"WARN: could not write --json {args.json}: {exc}",
                      file=sys.stderr)
        return 2

    report = audit(project, args.coverage_json, foundry_floor=args.foundry_floor)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        try:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out + "\n")
        except Exception as exc:  # pragma: no cover - IO edge
            print(f"WARN: could not write --json {args.json}: {exc}",
                  file=sys.stderr)
    print(out)

    verdict = report.get("verdict")
    meas = report.get("measured_coverage_pct")
    tgt = report.get("target_pct")
    eff = report.get("effective_target_pct")
    print(f"{_PROGRAM}: measured={meas} written_target={tgt} "
          f"effective_target={eff} verdict={verdict}", file=sys.stderr)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
