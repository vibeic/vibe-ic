#!/usr/bin/env python3
"""spare_cell_coverage_check.py — Design-for-ECO READINESS gate (Step 18).

Reads the spare-cell insertion plan emitted by phase3_one_shot_runner
(`phase3/stage3/pnr/spare_cells.json`) — and, when present, the runner's
coverage summary `reports/spare_cell_coverage.json` — and confirms the
project carries a usable spare-cell ECO budget:

  PASS iff ALL of:
    1. actual_density >= target_density (default target 0.02 = 2%).
    2. spares are DISTRIBUTED across the core (not all clustered in one
       spot) — measured as distinct grid-cell occupancy >= a minimum
       fraction of the spare count (and at least 2 distinct positions
       when there is more than 1 spare).
    3. all spares are tied off (tied_off == true).

Emits a JSON verdict and exits 0 (PASS) / 1 (FAIL) / 2 (IO/arg error).
chip-AGNOSTIC: reads only the generic spare_cells.json schema.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None


_DEFAULT_TARGET_DENSITY = 0.02
# A spare set is "distributed" when the number of distinct (llx, lly)
# positions is at least this fraction of the spare count. Spares
# inserted on a sqrt(N) grid occupy ~N distinct positions, so a healthy
# distribution easily clears this; a clustered set (all at one point)
# fails it.
_DISTRIBUTION_MIN_FRACTION = 0.5


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def compute_distribution(instances: List[Dict[str, Any]]
                         ) -> Tuple[int, int, bool]:
    """Return (distinct_positions, total, distributed_ok) for a spare
    instance list. Distribution is OK when count <= 1, or there is more
    than one distinct (llx, lly) AND distinct positions cover at least
    _DISTRIBUTION_MIN_FRACTION of the spares. Pure, chip-AGNOSTIC."""
    total = len(instances)
    if total == 0:
        return 0, 0, False
    distinct = {
        (inst.get("llx"), inst.get("lly"))
        for inst in instances
        if isinstance(inst, dict)
    }
    n_distinct = len(distinct)
    if total <= 1:
        return n_distinct, total, True
    if n_distinct <= 1:
        return n_distinct, total, False
    distributed_ok = n_distinct >= max(2, math.ceil(
        total * _DISTRIBUTION_MIN_FRACTION))
    return n_distinct, total, distributed_ok


def evaluate_coverage(spare_plan: dict,
                      coverage_summary: Optional[dict] = None,
                      target_density: float = _DEFAULT_TARGET_DENSITY
                      ) -> dict:
    """Pure evaluator. `spare_plan` is the spare_cells.json dict;
    `coverage_summary` is the optional runner-emitted coverage JSON.

    Returns a verdict dict {target_density, actual_density, count,
    distinct_positions, distribution_ok, tie_off_ok, density_ok,
    verdict, reasons[]}. chip-AGNOSTIC."""
    reasons: List[str] = []
    count = int(spare_plan.get("count", 0) or 0)
    instances = spare_plan.get("instances", [])
    if not isinstance(instances, list):
        instances = []

    # The gate floor is ALWAYS the caller-supplied `target_density`
    # (default 0.02). The plan may record its own `target_density` for
    # provenance, but that self-target can never relax the readiness
    # floor below what the gate asks for — a plan that inserted spares
    # at a laxer self-target must still clear the gate's minimum.
    tgt = target_density

    # Actual density: prefer an explicit field, else plan's recorded
    # density, else recompute from count / placed_cells_est.
    actual: Optional[float] = None
    for src in (coverage_summary or {}, spare_plan):
        if isinstance(src, dict) and src.get("actual_density") is not None:
            try:
                actual = float(src["actual_density"])
                break
            except (TypeError, ValueError):
                pass
    if actual is None:
        placed = spare_plan.get("placed_cells_est")
        try:
            placed = int(placed)
        except (TypeError, ValueError):
            placed = 0
        actual = round(count / placed, 6) if placed > 0 else 0.0
    if actual is None:
        actual = 0.0

    density_ok = actual >= tgt
    if not density_ok:
        reasons.append(
            f"actual_density {actual:g} < target_density {tgt:g}")

    n_distinct, total, distribution_ok = compute_distribution(instances)
    if not distribution_ok:
        reasons.append(
            f"spares clustered: only {n_distinct} distinct position(s) "
            f"for {total} spare(s)")

    tie_off_ok = bool(spare_plan.get("tied_off"))
    if not tie_off_ok:
        reasons.append("spares not tied off (tied_off != true)")

    verdict = "PASS" if (density_ok and distribution_ok and tie_off_ok
                         and count > 0) else "FAIL"
    if count <= 0:
        reasons.append("no spare cells inserted (count == 0)")
    return {
        "target_density": round(tgt, 6),
        "actual_density": round(actual, 6),
        "count": count,
        "distinct_positions": n_distinct,
        "distribution_ok": distribution_ok,
        "tie_off_ok": tie_off_ok,
        "density_ok": density_ok,
        "verdict": verdict,
        "reasons": reasons,
    }


def _resolve_paths(project: Path) -> Tuple[Path, Path]:
    """Resolve (spare_cells.json, coverage.json) from canonical layout,
    with a literal fallback so the checker also works without
    _path_layout importable."""
    if _pl is not None:
        spare_json = _pl.pnr_dir(project) / "spare_cells.json"
    else:  # pragma: no cover
        spare_json = project / "phase3/stage3/pnr/spare_cells.json"
    # Coverage summary is emitted by the runner at the literal
    # flow-declared path reports/spare_cell_coverage.json.
    cov_json = project / "reports" / "spare_cell_coverage.json"
    return spare_json, cov_json


def audit(project: Path,
          target_density: float = _DEFAULT_TARGET_DENSITY) -> dict:
    spare_json, cov_json = _resolve_paths(project)
    if not spare_json.is_file():
        return {
            "program": "spare_cell_coverage_check",
            "version": "1.0.0",
            "project_dir": str(project),
            "verdict": "FAIL",
            "reasons": [f"spare_cells.json not found at {spare_json}"],
            "count": 0,
        }
    plan = _load_json(spare_json)
    if plan is None:
        return {
            "program": "spare_cell_coverage_check",
            "version": "1.0.0",
            "project_dir": str(project),
            "verdict": "FAIL",
            "reasons": [f"spare_cells.json is not valid JSON: {spare_json}"],
            "count": 0,
        }
    summary = _load_json(cov_json) if cov_json.is_file() else None
    result = evaluate_coverage(plan, summary, target_density)
    result.update({
        "program": "spare_cell_coverage_check",
        "version": "1.0.0",
        "project_dir": str(project),
        "spare_cells_json": str(spare_json),
        "coverage_summary_json": (str(cov_json)
                                  if cov_json.is_file() else None),
    })
    # `status` mirrors `verdict` so consumers reading the documented
    # coverage schema (benchmark_verify_report Pillar 6 expects a
    # top-level "status": "PASS") see a PASS. Both kept for compat.
    result["status"] = result.get("verdict")
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Design-for-ECO spare-cell coverage readiness check")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--target-density", type=float,
                    default=_DEFAULT_TARGET_DENSITY,
                    help="Minimum acceptable spare density (default 0.02)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = audit(project, args.target_density)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    # Canonical output: reports/spare_cell_coverage.json (Pillar 6 reads
    # this literal path), in addition to any explicit --json path.
    canon = project / "reports" / "spare_cell_coverage.json"
    try:
        canon.parent.mkdir(parents=True, exist_ok=True)
        canon.write_text(out + "\n")
    except Exception:
        pass
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return 0 if report.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
