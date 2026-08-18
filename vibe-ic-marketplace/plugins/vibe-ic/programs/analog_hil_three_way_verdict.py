#!/usr/bin/env python3
"""analog_hil_three_way_verdict.py — deterministic three-way HIL verdict table.

The analog-hw-tuning-loop skill documents a four-row decision table that maps the
three numeric verdicts of a hardware-in-the-loop iteration onto one action. Given
(SPICE-vs-Spec, HW-vs-Spec, HW-vs-SPICE-discrepancy) the action is fully
determined — there is NO judgment, it is a pure table lookup:

    | SPICE vs Spec | HW vs Spec | HW vs SPICE | Action / verdict                 |
    |:-------------:|:----------:|:-----------:|----------------------------------|
    | PASS          | PASS       | < 20 %      | CONVERGED          (ideal)       |
    | PASS          | PASS       | >= 20 %     | CONVERGED_WARNING  (model accuracy)|
    | PASS          | FAIL       | (any)       | MODEL_INACCURACY   (add margin)  |
    | FAIL          | (any)      | (any)       | BACK_TO_PHASE1     (sizing problem)|

This program reads a per-block comparison file and computes the verdict for every
metric, then derives the block-level verdict (worst-case action wins). It earns its
PASS only when at least one metric is present and the worst-case verdict is a
CONVERGED variant; it FAILs honestly when the worst-case verdict is
MODEL_INACCURACY or BACK_TO_PHASE1, and SKIPs (exit 0 + INFO) when there is no
data to evaluate. Garbage / missing input is a non-zero / SKIP, never a vacuous
PASS.

Input file shape (per block, default analog/<block>/hw_tuning_report.json, or a
single file passed explicitly):

    {
      "block_name": "ldo_1v8",
      "final_comparison": {
        "<metric>": {
          "spec": <number>,           # spec target/limit
          "spice": <number>,          # SPICE-converged value
          "hw": <number>,             # measured hardware value
          "spec_min": <number?>,      # optional explicit limits …
          "spec_max": <number?>,      # … if absent, default tol applies
          "tol_pct": <number?>        # optional per-metric spec tol (% of spec)
        }
      }
    }

Pass / fail semantics per metric:
  * SPICE-vs-Spec PASS  iff spice within spec limits (explicit min/max, else
    |spice-spec|/|spec| <= tol_pct, default DEFAULT_SPEC_TOL_PCT).
  * HW-vs-Spec   PASS   iff hw within the same spec limits.
  * HW-vs-SPICE discrepancy = |hw-spice|/|spice|*100; < HW_SPICE_WARN_PCT is OK.

Usage:
    python3 analog_hil_three_way_verdict.py <project_dir> [--json <out>]
    python3 analog_hil_three_way_verdict.py --file <report.json> [--json <out>]

Exit codes:
    0  PASS  (worst-case verdict is CONVERGED / CONVERGED_WARNING) or SKIP
    1  FAIL  (worst-case verdict is MODEL_INACCURACY or BACK_TO_PHASE1)
    2  argument / I/O / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover - allow `python3 programs/...` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl


DEFAULT_SPEC_TOL_PCT = 5.0     # default spec tolerance when no explicit min/max
HW_SPICE_WARN_PCT = 20.0       # HW-vs-SPICE discrepancy >= this → model-accuracy WARNING

# Worst-case ordering: lower index = better. Block verdict = worst metric.
_VERDICT_ORDER = ("CONVERGED", "CONVERGED_WARNING", "MODEL_INACCURACY", "BACK_TO_PHASE1")
_FAIL_VERDICTS = ("MODEL_INACCURACY", "BACK_TO_PHASE1")


@dataclass
class MetricVerdict:
    metric: str
    spice_vs_spec: str          # PASS / FAIL
    hw_vs_spec: str             # PASS / FAIL
    hw_spice_discrepancy_pct: float
    verdict: str                # one of _VERDICT_ORDER
    detail: str = ""


@dataclass
class BlockVerdict:
    block: str
    source: str
    verdict: str
    metrics: List[MetricVerdict] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def _within_limits(val: float, spec: float, mn, mx, tol_pct: float) -> bool:
    if mn is not None and val < mn:
        return False
    if mx is not None and val > mx:
        return False
    if mn is None and mx is None:
        if spec == 0:
            return abs(val) <= (tol_pct / 100.0)
        return abs(val - spec) / abs(spec) * 100.0 <= tol_pct
    return True


def _table_lookup(spice_pass: bool, hw_pass: bool, hw_spice_pct: float) -> str:
    """The four-row decision table — pure lookup, no judgment."""
    if not spice_pass:
        return "BACK_TO_PHASE1"
    # spice_pass is True from here
    if not hw_pass:
        return "MODEL_INACCURACY"
    if hw_spice_pct >= HW_SPICE_WARN_PCT:
        return "CONVERGED_WARNING"
    return "CONVERGED"


def _eval_metric(name: str, m: dict) -> Optional[MetricVerdict]:
    spec = m.get("spec")
    spice = m.get("spice")
    hw = m.get("hw")
    if not all(isinstance(x, (int, float)) for x in (spec, spice, hw)):
        return None
    mn = m.get("spec_min")
    mx = m.get("spec_max")
    tol = m.get("tol_pct", DEFAULT_SPEC_TOL_PCT)
    if not isinstance(tol, (int, float)):
        tol = DEFAULT_SPEC_TOL_PCT

    spice_pass = _within_limits(float(spice), float(spec), mn, mx, float(tol))
    hw_pass = _within_limits(float(hw), float(spec), mn, mx, float(tol))
    if spice == 0:
        hw_spice_pct = 0.0 if hw == 0 else float("inf")
    else:
        hw_spice_pct = abs(float(hw) - float(spice)) / abs(float(spice)) * 100.0

    verdict = _table_lookup(spice_pass, hw_pass, hw_spice_pct)
    detail = (f"spec={spec} spice={spice}({'PASS' if spice_pass else 'FAIL'}) "
              f"hw={hw}({'PASS' if hw_pass else 'FAIL'}) "
              f"hw_vs_spice={hw_spice_pct:.2f}%")
    return MetricVerdict(
        metric=name,
        spice_vs_spec="PASS" if spice_pass else "FAIL",
        hw_vs_spec="PASS" if hw_pass else "FAIL",
        hw_spice_discrepancy_pct=round(hw_spice_pct, 4)
        if hw_spice_pct != float("inf") else hw_spice_pct,
        verdict=verdict,
        detail=detail,
    )


def _worst(verdicts: List[str]) -> str:
    if not verdicts:
        return "CONVERGED"
    return max(verdicts, key=lambda v: _VERDICT_ORDER.index(v)
               if v in _VERDICT_ORDER else len(_VERDICT_ORDER))


def evaluate_file(path: Path) -> Optional[BlockVerdict]:
    """Evaluate a single hw_tuning_report.json. Returns None if unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    block = data.get("block_name") or data.get("block") or path.parent.name
    comparison = data.get("final_comparison")
    if not isinstance(comparison, dict) or not comparison:
        return BlockVerdict(block=block, source=str(path), verdict="SKIP",
                            reasons=["final_comparison missing / empty"])
    metrics: List[MetricVerdict] = []
    for name, m in comparison.items():
        if not isinstance(m, dict):
            continue
        mv = _eval_metric(name, m)
        if mv is not None:
            metrics.append(mv)
    if not metrics:
        return BlockVerdict(block=block, source=str(path), verdict="SKIP",
                            reasons=["no metric had numeric spec/spice/hw"])
    worst = _worst([mv.verdict for mv in metrics])
    reasons = [f"{mv.metric}: {mv.verdict} ({mv.detail})"
               for mv in metrics if mv.verdict in _FAIL_VERDICTS]
    return BlockVerdict(block=block, source=str(path), verdict=worst,
                        metrics=metrics, reasons=reasons)


def run(project: Optional[Path], single_file: Optional[Path]) -> dict:
    blocks: List[BlockVerdict] = []
    if single_file is not None:
        bv = evaluate_file(single_file)
        if bv is None:
            return {"gate": "analog_hil_three_way_verdict", "verdict": "ERROR",
                    "reason": f"cannot parse {single_file}", "blocks": []}
        blocks.append(bv)
    else:
        analog_dir = _pl.analog_dir(project)
        if not analog_dir.is_dir():
            return {"gate": "analog_hil_three_way_verdict", "verdict": "SKIP",
                    "reason": "no phase3/analog directory", "blocks": []}
        report_files = sorted(analog_dir.glob("*/hw_tuning_report.json"))
        if not report_files:
            return {"gate": "analog_hil_three_way_verdict", "verdict": "SKIP",
                    "reason": "no hw_tuning_report.json under analog/", "blocks": []}
        for rp in report_files:
            bv = evaluate_file(rp)
            if bv is None:
                blocks.append(BlockVerdict(block=rp.parent.name, source=str(rp),
                                           verdict="ERROR",
                                           reasons=["unreadable / malformed JSON"]))
            else:
                blocks.append(bv)

    # Block verdicts that are SKIP/ERROR do not pass; a real CONVERGED is required.
    evaluable = [b for b in blocks if b.verdict in _VERDICT_ORDER]
    has_fail = any(b.verdict in _FAIL_VERDICTS for b in blocks)
    has_error = any(b.verdict == "ERROR" for b in blocks)
    if not evaluable and not has_fail and not has_error:
        # all SKIP
        overall = "SKIP"
    elif has_fail or has_error or not evaluable:
        overall = "FAIL"
    else:
        overall = "PASS"
    return {
        "gate": "analog_hil_three_way_verdict",
        "verdict": overall,
        "hw_spice_warn_pct": HW_SPICE_WARN_PCT,
        "default_spec_tol_pct": DEFAULT_SPEC_TOL_PCT,
        "blocks": [asdict(b) for b in blocks],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", nargs="?", default=None)
    ap.add_argument("--file", default=None,
                    help="evaluate a single hw_tuning_report.json directly")
    ap.add_argument("--json", default=None, help="write JSON report to this path")
    args = ap.parse_args(argv)

    single = Path(args.file) if args.file else None
    project = Path(args.project_dir).resolve() if args.project_dir else None

    if single is None and project is None:
        print("error: provide <project_dir> or --file <report.json>", file=sys.stderr)
        return 2
    if single is not None and not single.is_file():
        print(f"error: file not found: {single}", file=sys.stderr)
        return 2
    if single is None and not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    report = run(project, single)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    print(f"[{verdict}] analog_hil_three_way_verdict")
    for b in report["blocks"]:
        print(f"  [{b['verdict']}] block={b['block']}")
        for r in b.get("reasons", []):
            print(f"      {r}")

    if verdict == "ERROR":
        return 2
    return 0 if verdict in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main())
