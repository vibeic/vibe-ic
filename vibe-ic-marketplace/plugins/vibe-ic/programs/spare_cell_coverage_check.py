#!/usr/bin/env python3
"""spare_cell_coverage_check.py — Design-for-ECO READINESS gate (Step 18).

Reads the spare-cell insertion plan emitted by phase3_one_shot_runner
(`phase3/stage3/pnr/spare_cells.json`) — step 18's other declared output
and this gate's ONLY input — and confirms the project carries a usable
spare-cell ECO budget:

  PASS iff ALL of:
    1. actual_density >= target_density (default target 0.02 = 2%).
    2. spares are DISTRIBUTED across the core (not all clustered in one
       spot) — measured as distinct grid-cell occupancy >= a minimum
       fraction of the spare count (and at least 2 distinct positions
       when there is more than 1 spare).
    3. all spares are tied off (tied_off == true).

Emits a JSON verdict and exits 0 (PASS) / 1 (FAIL) / 2 (IO/arg error).
chip-AGNOSTIC: reads only the generic spare_cells.json schema.

DECLARING PRODUCER of `reports/spare_cell_coverage.json`. This program
writes that path and NOTHING ELSE MAY. It also does not READ it: the
verdict is recomputed from spare_cells.json on every invocation, so a
file left at that path by a previous run — or by any other writer —
cannot reach the verdict.
docs/decisions/2026-08-22-spare-cell-coverage-declaring-producer.md
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
    ONLY input. This evaluator used to take a second argument, the
    coverage JSON found at this program's own output path, and prefer
    its `actual_density` over the plan's. On a re-run that file IS this
    program's previous verdict, so a stale density was carried forward
    over the current plan: a project re-checked with 10 spares in 10000
    cells reported `actual_density: 0.02` beside `count: 10` and exited
    0. The argument is gone; there is no path by which anything written
    at the output path can influence the verdict.

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

    # Actual density: the plan's recorded density, else recomputed from
    # count / placed_cells_est. Both come from spare_cells.json, which
    # this program does not write — so neither can be an echo of an
    # earlier verdict.
    actual: Optional[float] = None
    if spare_plan.get("actual_density") is not None:
        try:
            actual = float(spare_plan["actual_density"])
        except (TypeError, ValueError):
            actual = None
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


def _resolve_input(project: Path) -> Path:
    """Resolve spare_cells.json from the canonical layout, with a literal
    fallback so the checker also works without _path_layout importable.

    There is exactly ONE input. The output path is resolved separately in
    `main`, and is never opened for reading."""
    if _pl is not None:
        return _pl.pnr_dir(project) / "spare_cells.json"
    return project / "phase3/stage3/pnr/spare_cells.json"  # pragma: no cover


def _carried_measurements(plan: dict) -> Dict[str, Any]:
    """The MEASUREMENT the removed runner summary used to publish, carried
    from the plan into the one file at the declared path.

    Removing a second writer must not cost a reader anything it could read
    before. `phase3_one_shot_runner` published `placed_cells_est`, the
    measured `tie_off` evidence and the run's own density target at this
    path; all three are measurements of the insertion and none of them is a
    grade, so they travel here from `spare_cells.json` — the gate's only
    input — instead of from a rival writer.

    `plan_target_density` is deliberately NOT `target_density`. The run's
    own `--spare-density` and the gate's readiness floor are two different
    numbers, and publishing the first under the second's key is exactly the
    confusion the removed summary shipped: a run invoked with
    `--spare-density 0.005` graded itself against 0.005 and called it PASS.
    Provenance and floor are kept apart so neither can be read as the other.

    A key the plan does not carry is OMITTED, never emitted as null. A null
    here would be indistinguishable from "measured, and the answer is
    nothing", and this repository has paid for that confusion once already
    in the PPA scope records.
    """
    carried: Dict[str, Any] = {}
    if plan.get("placed_cells_est") is not None:
        carried["placed_cells_est"] = plan["placed_cells_est"]
    if plan.get("tie_off") is not None:
        carried["tie_off"] = plan["tie_off"]
    if plan.get("target_density") is not None:
        carried["plan_target_density"] = plan["target_density"]
    return carried


def audit(project: Path,
          target_density: float = _DEFAULT_TARGET_DENSITY) -> dict:
    spare_json = _resolve_input(project)
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
        "version": "1.2.0",
        "project_dir": str(project),
        "spare_cells_json": str(spare_json),
        # `inputs` is exhaustive: this gate reads spare_cells.json and
        # nothing else. The removed `coverage_summary_json` key named
        # this program's OWN output as an input, which is what let a
        # previous verdict feed the next one.
        "inputs": [str(spare_json)],
    })
    result.update(_carried_measurements(plan))
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
    # this literal path), in addition to any explicit --json path. This
    # program is the DECLARING PRODUCER of this path — step 18 names it,
    # nothing else may write it, and this program never reads it back.
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
