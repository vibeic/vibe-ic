#!/usr/bin/env python3
"""spare_cell_coverage_check.py — Design-for-ECO READINESS gate (Step 18).

Reads the spare-cell insertion plan emitted by phase3_one_shot_runner
(`phase3/stage3/pnr/spare_cells.json`) and confirms the project carries a
usable spare-cell ECO budget:

  PASS iff ALL of:
    1. actual_density >= target_density (default target 0.02 = 2%).
    2. spares are DISTRIBUTED across the core (not all clustered in one
       spot) — measured as distinct grid-cell occupancy >= a minimum
       fraction of the spare count (and at least 2 distinct positions
       when there is more than 1 spare).
    3. all spares are tied off (tied_off == true).

Emits a JSON verdict and exits 0 (PASS) / 1 (FAIL) / 2 (IO/arg error).
chip-AGNOSTIC: reads only the generic spare_cells.json schema.

THIS PROGRAM IS THE DECLARING PRODUCER of `reports/spare_cell_coverage.json`
— step 18 of `flow/phase1_phase2_phase3.yaml` declares that path and names
this program in the step's `programs:` list. It is therefore the ONLY writer,
and it does NOT read that path. See
`docs/decisions/2026-08-22-spare-cell-coverage-declaring-producer.md`.

Until 2026-08-22 this file read the path it writes: `audit()` loaded
`reports/spare_cell_coverage.json` as a "runner-emitted coverage summary" and
PREFERRED its `actual_density` over the current `spare_cells.json`. Because
this program also wrote that path, the summary it read on any second
invocation was its OWN previous verdict. Measured on one project directory:
a run whose insertion collapsed from 203 spares to 5 (actual_density 0.000493,
40x under the 0.02 floor) exited 0 and published `"verdict": "PASS"` carrying
`"actual_density": 0.020022` — the PREVIOUS run's number — beside its own
`"count": 5`. Deleting the report first and re-running the identical input
gave rc=1, FAIL, 0.000493. The stale value beat the plan's own fresh one
because the summary was consulted FIRST.
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
                      target_density: float = _DEFAULT_TARGET_DENSITY
                      ) -> dict:
    """Pure evaluator. `spare_plan` is the spare_cells.json dict — the
    ONLY input. There is deliberately no second source: the removed
    `coverage_summary` parameter was fed `reports/spare_cell_coverage.json`,
    which is this program's own output path, so it let a previous run's
    number outrank the plan this run produced.

    Returns a verdict dict {target_density, plan_target_density,
    actual_density, count, placed_cells_est, distinct_positions,
    distribution_ok, tie_off_ok, tie_off, density_ok, verdict,
    reasons[]}. chip-AGNOSTIC."""
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

    # Actual density comes from the plan and only from the plan: its
    # recorded `actual_density`, else recomputed from
    # count / placed_cells_est. Both are the runner's measurement of THIS
    # run, carried in the runner's own declared artefact.
    placed = spare_plan.get("placed_cells_est")
    try:
        placed = int(placed)
    except (TypeError, ValueError):
        placed = 0
    actual: Optional[float] = None
    if spare_plan.get("actual_density") is not None:
        try:
            actual = float(spare_plan["actual_density"])
        except (TypeError, ValueError):
            actual = None
    if actual is None:
        actual = round(count / placed, 6) if placed > 0 else 0.0

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
    # The plan's OWN target is provenance, kept under a distinct key so it
    # can never be mistaken for the gate floor above.
    plan_tgt = spare_plan.get("target_density")
    try:
        plan_tgt = round(float(plan_tgt), 6)
    except (TypeError, ValueError):
        plan_tgt = None
    return {
        "target_density": round(tgt, 6),
        "plan_target_density": plan_tgt,
        "actual_density": round(actual, 6),
        "count": count,
        "placed_cells_est": placed or None,
        # The runner's MEASURED tie-off evidence ({raised, sinks, ...}),
        # carried through so the one file at the declared path says WHICH
        # of "raised", "never ran" or "partial" produced `tie_off_ok`.
        "tie_off": spare_plan.get("tie_off"),
        "distinct_positions": n_distinct,
        "distribution_ok": distribution_ok,
        "tie_off_ok": tie_off_ok,
        "density_ok": density_ok,
        "verdict": verdict,
        "reasons": reasons,
    }


def _resolve_spare_json(project: Path) -> Path:
    """Resolve spare_cells.json from the canonical layout, with a literal
    fallback so the checker also works without _path_layout importable.

    This returns ONE path. It used to return a second — the coverage
    report this program writes — and reading that was the defect the
    module docstring records.
    """
    if _pl is not None:
        return _pl.pnr_dir(project) / "spare_cells.json"
    return project / "phase3/stage3/pnr/spare_cells.json"  # pragma: no cover


def audit(project: Path,
          target_density: float = _DEFAULT_TARGET_DENSITY) -> dict:
    spare_json = _resolve_spare_json(project)
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
    result = evaluate_coverage(plan, target_density)
    result.update({
        "program": "spare_cell_coverage_check",
        "version": "1.1.0",
        "project_dir": str(project),
        "spare_cells_json": str(spare_json),
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
    # Canonical output: reports/spare_cell_coverage.json — step 18's
    # declared required_output, which this program declares and therefore
    # is the sole writer of. `benchmark_verify_report` Pillar 6 grades this
    # literal path by its `status` alone, so a second writer there is a
    # second sign-off verdict the release tier cannot tell apart. Written
    # in addition to any explicit --json path.
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
