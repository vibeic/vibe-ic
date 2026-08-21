#!/usr/bin/env python3
"""
hold_area_budget_check.py — enforce the hold-buffer area-budget guardrail.

From `skills/hold-fix/SKILL.md` "Constraints and Guardrails" #2:
  "Area budget: hold buffers should not exceed 5% of total cell area. If
   exceeded, investigate why — possible CTS imbalance."

This is a numeric threshold check on the area added by hold fixing relative to
the total cell area:

    overhead_pct = 100 * hold_buffer_area / total_cell_area
    overhead_pct <= 5.0   => PASS  (within budget)
    overhead_pct  > 5.0   => FAIL  (budget exceeded — investigate CTS imbalance)

The hold-buffer area can be supplied directly, OR derived from a before/after
total-area pair (after_total - before_total). The percentage is taken against
the TOTAL post-fix cell area (the SKILL says "5% of total cell area").

HARD honesty rules (no vacuous PASS):
  - Missing / non-finite / non-positive total area  => FAIL (rc=1). A 0 or
    absent denominator cannot be certified within budget.
  - Negative hold-buffer area (a fix that REMOVED area) => FAIL (rc=1): hold
    fixing only ADDS cells; a negative delta means the wrong baseline.
  - hold_buffer_area == 0 (nothing inserted) is reported as PASS only when a
    total area is present AND the caller explicitly allows a no-op
    (`allow_zero=True`); by default a 0-overhead claim with no inserted area is
    a FAIL because a hold-fix step that inserted nothing did no work (mirrors
    hold_closure_check). Use --allow-zero for the "design had no hold
    violations" path.

Input forms (JSON or CLI flags):
  {"hold_buffer_area": 1234.5, "total_cell_area": 100000.0}
  {"before_total_area": 98765.5, "after_total_area": 100000.0}   # delta derived

PROJECT-DIRECTORY MODE, and the NO-PRODUCER disclosure it exists to make
------------------------------------------------------------------------
THE GUARDRAIL IS ENFORCED AT NEITHER END TODAY. Measured over the published
corpus and over `phase3_one_shot_runner` itself:

  * 0 files anywhere under `benchmark-data/` carry `hold_buffer_area`,
    `total_cell_area` or a `before/after_total_area` pair, and 0 carry an
    `area*.rpt`. Nothing in the plugin writes this gate's input.
  * The flow's only area emission is a single `report_design_area` at the END
    of `pnr.tcl` — one post-P&R total, with no before/after bracket around the
    hold-repair step, so the numerator cannot even be derived.
  * The EX-ANTE half is missing too: `openroad_hold_repair_tcl_gen` emits
    `-max_buffer_percent <= 5`, and the count of `max_buffer_percent` in
    `phase3_one_shot_runner.py` and in every published `pnr*.tcl` is 0. The
    template emits a bare `repair_timing -hold`.

So the SKILL's 5% hold-buffer area guardrail is documentation at both ends.
Wiring this gate on a raw path would have FAILed 100% of runs for
`TOTAL_AREA_MISSING_OR_ZERO` — a total outage for the wrong reason.

A positional argument that is a DIRECTORY is therefore treated as a PROJECT
ROOT: the known producer paths are probed, and when none exists the gate
returns rc=2 NOT CHECKED with reason `NO_AREA_PRODUCER`, printing what is
missing. That is a DISCLOSURE, not permission — and it is a disclosure that is
regenerated on every run instead of typed once into a list that can rot. The
moment a producer lands, the same wiring judges it with no further change.

WHAT WOULD MAKE THIS GATE BLOCKING: `phase3_one_shot_runner` bracketing the
hold-repair block with `report_design_area` and emitting
`reports/phase3/pnr/hold_area.json` with `before_total_area` / `after_total_area`
(and, when the tool reports it, `hold_buffer_area` directly).

chip-AGNOSTIC: the only constant is the SKILL's universal 5% guardrail; no
PDK / cell / design literal is hard-coded.

Usage
-----
    python3 hold_area_budget_check.py <input.json> [--json <out>] [--allow-zero]
    python3 hold_area_budget_check.py <project_dir> [--json <out>]
    python3 hold_area_budget_check.py --hold-buffer-area 1200 \\
        --total-cell-area 100000 [--json <out>]

Exit codes
----------
    0 — PASS (within budget)
    1 — FAIL (budget exceeded, or an input that exists but cannot be certified)
    2 — NOT CHECKED: project-directory mode found no producer for the input.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional, Tuple


_TOOL = "hold_area_budget_check"
AREA_BUDGET_PCT = 5.0   # SKILL guardrail: hold buffers <= 5% of total cell area


def _finite_positive(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def evaluate(hold_buffer_area: Optional[float],
             total_cell_area: Optional[float],
             before_total_area: Optional[float] = None,
             after_total_area: Optional[float] = None,
             allow_zero: bool = False) -> Tuple[str, int, dict]:
    report = {"tool": _TOOL, "budget_pct": AREA_BUDGET_PCT}

    # Derive hold_buffer_area / total from a before/after pair if given.
    if hold_buffer_area is None and \
            before_total_area is not None and after_total_area is not None:
        if not (_finite_positive(before_total_area) and
                _finite_positive(after_total_area)):
            report.update(verdict="FAIL", reason="BEFORE_AFTER_NOT_POSITIVE",
                          message="before/after total area must be finite "
                                  "positive numbers")
            return "FAIL", 1, report
        hold_buffer_area = after_total_area - before_total_area
        if total_cell_area is None:
            total_cell_area = after_total_area

    report["hold_buffer_area"] = hold_buffer_area
    report["total_cell_area"] = total_cell_area

    # Denominator must be finite positive.
    if not _finite_positive(total_cell_area):
        report.update(verdict="FAIL", reason="TOTAL_AREA_MISSING_OR_ZERO",
                      message="total cell area absent / non-positive — cannot "
                              "certify hold-buffer area within budget "
                              "(missing input is an honest FAIL)")
        return "FAIL", 1, report

    if hold_buffer_area is None or not isinstance(hold_buffer_area, (int, float)) \
            or not math.isfinite(hold_buffer_area):
        report.update(verdict="FAIL", reason="HOLD_AREA_MISSING",
                      message="hold-buffer area absent / non-finite — supply it "
                              "directly or as before/after totals")
        return "FAIL", 1, report

    if hold_buffer_area < 0:
        report.update(verdict="FAIL", reason="NEGATIVE_HOLD_AREA",
                      message=f"hold-buffer area {hold_buffer_area:g} is "
                              "negative — hold fixing only ADDS cells; check "
                              "the before/after baseline")
        return "FAIL", 1, report

    if hold_buffer_area == 0:
        if allow_zero:
            report.update(verdict="PASS", reason="NO_HOLD_BUFFERS_NEEDED",
                          overhead_pct=0.0,
                          message="no hold buffers inserted (design had no hold "
                                  "violations) — within budget by --allow-zero")
            return "PASS", 0, report
        report.update(verdict="FAIL", reason="ZERO_HOLD_AREA_NO_WORK",
                      overhead_pct=0.0,
                      message="hold-buffer area is 0 — the hold-fix step "
                              "inserted nothing (use --allow-zero only if the "
                              "design genuinely had no hold violations)")
        return "FAIL", 1, report

    overhead_pct = 100.0 * hold_buffer_area / total_cell_area
    report["overhead_pct"] = overhead_pct

    if overhead_pct > AREA_BUDGET_PCT:
        report.update(verdict="FAIL", reason="AREA_BUDGET_EXCEEDED",
                      message=f"hold-buffer overhead {overhead_pct:.3f}% exceeds "
                              f"the {AREA_BUDGET_PCT:g}% guardrail — investigate "
                              f"(possible CTS imbalance / over-skewed clock tree)")
        return "FAIL", 1, report

    report.update(verdict="PASS", reason="WITHIN_BUDGET",
                  message=f"hold-buffer overhead {overhead_pct:.3f}% within the "
                          f"{AREA_BUDGET_PCT:g}% guardrail")
    return "PASS", 0, report


def _load_input(args) -> Tuple[Optional[float], Optional[float],
                               Optional[float], Optional[float]]:
    hba = args.hold_buffer_area
    tca = args.total_cell_area
    bta = args.before_total_area
    ata = args.after_total_area
    if args.input_json:
        p = Path(args.input_json)
        if not p.is_file():
            return None, None, None, None  # honest FAIL downstream
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            return None, None, None, None
        if isinstance(data, dict):
            hba = data.get("hold_buffer_area", hba)
            tca = data.get("total_cell_area", tca)
            bta = data.get("before_total_area", bta)
            ata = data.get("after_total_area", ata)
    return hba, tca, bta, ata


#: Where a producer WOULD write this gate's input, most canonical first. Probed
#: in project-directory mode; none of them exists in the corpus today, which is
#: the finding this mode reports.
_PRODUCER_CANDIDATES = (
    "reports/phase3/pnr/hold_area.json",
    "reports/phase3/hold_area.json",
    "reports/phase3/pnr/hold_buffer_area.json",
)
#: Any one of these keys makes a JSON judgeable by this gate.
_AREA_KEYS = ("hold_buffer_area", "total_cell_area",
              "before_total_area", "after_total_area")


def find_producer(project: Path) -> Optional[Path]:
    """First existing producer artefact under a project root, else None."""
    for rel in _PRODUCER_CANDIDATES:
        p = project / rel
        if p.is_file():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Enforce the 5% hold-buffer area-budget guardrail")
    ap.add_argument("input_json", nargs="?",
                    help="JSON with hold_buffer_area+total_cell_area OR "
                         "before_total_area+after_total_area, or a project "
                         "directory to probe for a producer")
    ap.add_argument("--hold-buffer-area", type=float)
    ap.add_argument("--total-cell-area", type=float)
    ap.add_argument("--before-total-area", type=float)
    ap.add_argument("--after-total-area", type=float)
    ap.add_argument("--allow-zero", action="store_true",
                    help="treat 0 inserted area as PASS (no hold violations)")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    if not (args.input_json or args.hold_buffer_area is not None or
            args.before_total_area is not None):
        print(f"[{_TOOL}] supply <input.json> or area flags", file=sys.stderr)
        return 1

    if args.input_json and Path(args.input_json).is_dir():
        project = Path(args.input_json)
        found = find_producer(project)
        if found is None:
            report = {
                "tool": _TOOL, "budget_pct": AREA_BUDGET_PCT,
                "mode": "project", "project": str(project),
                "verdict": "NOT CHECKED", "reason": "NO_AREA_PRODUCER",
                "probed": list(_PRODUCER_CANDIDATES),
                "message": (
                    "the 5% hold-buffer area guardrail was NOT CHECKED: no "
                    "producer wrote this gate's input. Probed "
                    + ", ".join(_PRODUCER_CANDIDATES) + ". Nothing in the "
                    "plugin emits hold_buffer_area / total_cell_area or a "
                    "before/after total-area pair around the hold-repair "
                    "step; the flow's only area emission is a single "
                    "post-P&R report_design_area with no bracket. The "
                    "ex-ante half (-max_buffer_percent in the emitted "
                    "repair_timing -hold) is absent too, so the guardrail is "
                    "enforced at NEITHER end."),
            }
            if args.json:
                outp = Path(args.json)
                outp.parent.mkdir(parents=True, exist_ok=True)
                outp.write_text(json.dumps(report, indent=2) + "\n")
            print(f"=== {_TOOL} === verdict: NOT CHECKED")
            print(f"VACUOUS_PASS: {_TOOL} — NOT CHECKED "
                  f"[NO_AREA_PRODUCER]: {report['message']}")
            return 2
        args.input_json = str(found)

    hba, tca, bta, ata = _load_input(args)
    verdict, rc, report = evaluate(hba, tca, bta, ata, allow_zero=args.allow_zero)

    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"=== {_TOOL} === verdict: {verdict}")
    if "overhead_pct" in report:
        print(f"  overhead: {report['overhead_pct']:.3f}% "
              f"(budget {AREA_BUDGET_PCT:g}%)")
    if verdict == "FAIL":
        print(f"  FAIL [{report.get('reason')}]: {report.get('message')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
