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

Usage:
    python3 dft_atpg_coverage_check.py <project_dir> [--json <out>]
    python3 dft_atpg_coverage_check.py <project_dir> [--coverage-json PATH]

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


_PROGRAM = "dft_atpg_coverage_check"
_VERSION = "1.0.0"

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
             rpt_text: Optional[str]) -> dict:
    """Pure evaluator. Independently derives measured + target stuck-at
    coverage from the artefact(s) and recomputes the verdict. NEVER
    trusts a written boolean. Returns a verdict dict.

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

    recomputed_ge_target: Optional[bool] = None
    if measured is not None and target is not None:
        recomputed_ge_target = measured >= target
        if not recomputed_ge_target:
            reasons.append(
                f"measured stuck-at coverage {measured:.2f}% < "
                f"target {target:.2f}% — DFT/ATPG coverage below required "
                f"floor (untestable silicon)")

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
            f"{measured:.2f}% vs target {target:.2f}% — boolean ignored, "
            f"recomputed verdict governs")

    verdict = "PASS" if recomputed_ge_target is True else "FAIL"

    return {
        "measured_coverage_pct": (round(measured, 4)
                                  if measured is not None else None),
        "measured_source": measured_src,
        "target_pct": round(target, 4) if target is not None else None,
        "target_source": target_src,
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
        cov_candidates.append(project / "reports" / "phase2b" / "dft" / "coverage.json")

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


def audit(project: Path,
          coverage_json_override: Optional[str] = None) -> dict:
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

    result = evaluate(coverage_json, rpt_text)
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
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = audit(project, args.coverage_json)
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
    print(f"{_PROGRAM}: measured={meas} target={tgt} verdict={verdict}",
          file=sys.stderr)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
