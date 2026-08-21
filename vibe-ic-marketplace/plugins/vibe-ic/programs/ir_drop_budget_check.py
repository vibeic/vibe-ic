#!/usr/bin/env python3
"""ir_drop_budget_check.py — numeric IR-drop budget gate for tapeout sign-off.

The tapeout-checklist skill's power-integrity row requires:

    Static IR-drop < budget (typical 5-10% of Vdd)

The existing `eda_report_audit --mode ir_drop` (= ir_drop_report_check.py)
only confirms that *some* voltage-drop value APPEARS in the report
(presence + tool-authenticity). It never computes the actual budget
`budget_mV = pct * Vdd * 1000` and never compares the measured worst-case
drop against it. `ir_drop_triage_classify.py` classifies hotspot CAUSES
but likewise does no Vdd-budget pass/fail.

This program closes that gap with a deterministic numeric threshold:

    PASS iff  max_drop_mV  <  pct * Vdd * 1000      (strictly under budget)

It reads the worst-case static IR drop from an IR-drop report. Two
schemas are accepted:

  1. JSON  — any of these keys (mV unless a *_pct / *_percent key is used):
       max_ir_drop_mv / worst_ir_drop_mv / max_drop_mv / ir_drop_mv
       max_ir_drop_pct / worst_ir_drop_percent (% of Vdd)
     plus a supply-voltage key:  vdd / vdd_v / supply_voltage_v / nominal_vdd_v
  2. Plain .rpt — scrapes the largest "<num> mV" OR "<num> % Vdd" token.

Honest-failure rules (NO vacuous pass on absence / garbage):
  * report file absent / unreadable                      → FAIL (rc=1)
  * present but no drop value can be extracted           → FAIL (rc=1)
  * drop given in mV but no Vdd available to size budget  → FAIL (rc=1)
  * measured drop >= budget                              → FAIL (rc=1)
  * measured drop  <  budget                             → PASS (rc=0)
  * project/report path not found at all                 → rc=2 (IO/arg)

There is no SKIP path: any design that reaches IR sign-off has a power
grid and therefore a measurable worst-case drop; a missing report is a
missing-evidence FAIL, not a not-applicable SKIP.

Usage:
    python3 ir_drop_budget_check.py <report> [--vdd V] [--budget-pct P]
                                    [--json OUT]
    <report> may be a JSON file, a .rpt file, or a directory (the program
    then searches for *ir*.json / *ir*.rpt / *voltage_drop* under it).

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.

chip-AGNOSTIC: reads only generic IR-report schemas; no design knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default budget: 10% of Vdd is the loosest commonly-cited static budget;
# the skill says "typical 5-10% Vdd". 10% is the permissive default so the
# gate never FAILs a design that a stricter house rule would also pass.
_DEFAULT_BUDGET_PCT = 10.0

_DROP_MV_KEYS = (
    "max_ir_drop_mv", "worst_ir_drop_mv", "max_drop_mv", "ir_drop_mv",
    "max_voltage_drop_mv", "worst_voltage_drop_mv",
)
_DROP_PCT_KEYS = (
    "max_ir_drop_pct", "worst_ir_drop_pct", "max_ir_drop_percent",
    "worst_ir_drop_percent", "ir_drop_pct_vdd",
)
_VDD_KEYS = (
    "vdd", "vdd_v", "supply_voltage_v", "nominal_vdd_v", "vdd_volts",
)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _extract_from_json(data: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (drop_mv, drop_pct, vdd_v) — any may be None if absent."""
    drop_mv: Optional[float] = None
    drop_pct: Optional[float] = None
    vdd_v: Optional[float] = None
    if not isinstance(data, dict):
        return None, None, None
    # Allow a nested summary dict (common in our report payloads).
    scopes = [data]
    for k in ("summary", "ir_drop", "static_ir_drop", "power_integrity"):
        sub = data.get(k)
        if isinstance(sub, dict):
            scopes.append(sub)
    for scope in scopes:
        for k in _DROP_MV_KEYS:
            if drop_mv is None and k in scope:
                drop_mv = _num(scope[k])
        for k in _DROP_PCT_KEYS:
            if drop_pct is None and k in scope:
                drop_pct = _num(scope[k])
        for k in _VDD_KEYS:
            if vdd_v is None and k in scope:
                vdd_v = _num(scope[k])
    return drop_mv, drop_pct, vdd_v


_MV_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*mV", re.I)
_PCT_VDD_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%\s*(?:of\s*)?Vdd", re.I)
_VDD_RE = re.compile(r"\bVdd\b\s*[=:]\s*([-+]?\d+(?:\.\d+)?)\s*V?", re.I)


def _extract_from_text(text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    mv_vals = [float(m) for m in _MV_RE.findall(text)]
    pct_vals = [float(m) for m in _PCT_VDD_RE.findall(text)]
    vdd_m = _VDD_RE.search(text)
    drop_mv = max(mv_vals) if mv_vals else None
    drop_pct = max(pct_vals) if pct_vals else None
    vdd_v = float(vdd_m.group(1)) if vdd_m else None
    return drop_mv, drop_pct, vdd_v


def _discover_report(path: Path) -> Optional[Path]:
    if path.is_file():
        return path
    if path.is_dir():
        patterns = ["*ir*drop*.json", "*ir*.json", "*ir*drop*.rpt",
                    "*ir*.rpt", "*voltage_drop*", "*power_grid*.rpt"]
        for pat in patterns:
            hits = sorted(path.rglob(pat))
            if hits:
                return hits[0]
    return None


def evaluate(report_path: Path, vdd_arg: Optional[float],
             budget_pct: float) -> Tuple[bool, Dict[str, Any]]:
    """Return (passed, report_dict). passed=False on any honest-failure."""
    rep: Dict[str, Any] = {
        "program": "ir_drop_budget_check",
        "version": "1.0.0",
        "report_path": str(report_path),
        "budget_pct": budget_pct,
        "findings": [],
    }

    raw: Optional[str] = None
    try:
        raw = report_path.read_text(errors="replace")
    except OSError as exc:
        rep["findings"].append({"severity": "ERROR", "rule": "READ_FAIL",
                                "message": f"cannot read report: {exc}"})
        rep["pass"] = False
        return False, rep

    drop_mv = drop_pct = vdd_v = None
    if report_path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            rep["findings"].append({"severity": "ERROR", "rule": "BAD_JSON",
                                    "message": f"unparseable JSON: {exc}"})
            rep["pass"] = False
            return False, rep
        drop_mv, drop_pct, vdd_v = _extract_from_json(data)
    else:
        drop_mv, drop_pct, vdd_v = _extract_from_text(raw)

    # CLI Vdd overrides / supplies the supply voltage.
    if vdd_arg is not None:
        vdd_v = vdd_arg

    if drop_mv is None and drop_pct is None:
        rep["findings"].append({
            "severity": "ERROR", "rule": "NO_DROP_VALUE",
            "message": "no worst-case IR-drop value (mV or %Vdd) found in report"})
        rep["pass"] = False
        return False, rep

    # Reduce to a single measured %-of-Vdd for the budget comparison.
    measured_pct: Optional[float] = None
    measured_mv: Optional[float] = drop_mv
    if drop_pct is not None:
        measured_pct = drop_pct
        if measured_mv is None and vdd_v is not None:
            measured_mv = drop_pct / 100.0 * vdd_v * 1000.0
    elif drop_mv is not None:
        if vdd_v is None:
            rep["findings"].append({
                "severity": "ERROR", "rule": "NO_VDD",
                "message": ("drop given in mV but no Vdd available to size the "
                            "budget; pass --vdd or include a vdd key")})
            rep["pass"] = False
            return False, rep
        measured_pct = drop_mv / (vdd_v * 1000.0) * 100.0

    budget_mv = (budget_pct / 100.0 * vdd_v * 1000.0) if vdd_v is not None else None

    rep["measured"] = {
        "drop_mv": measured_mv,
        "drop_pct_vdd": round(measured_pct, 4) if measured_pct is not None else None,
        "vdd_v": vdd_v,
    }
    rep["budget"] = {"budget_pct": budget_pct, "budget_mv": budget_mv}

    passed = measured_pct < budget_pct
    if not passed:
        rep["findings"].append({
            "severity": "ERROR", "rule": "IR_DROP_OVER_BUDGET",
            "message": (f"measured worst-case IR drop {measured_pct:.3f}% Vdd "
                        f">= budget {budget_pct:.3f}% Vdd"
                        + (f" ({measured_mv:.2f} mV >= {budget_mv:.2f} mV)"
                           if measured_mv is not None and budget_mv is not None
                           else ""))})
    rep["pass"] = passed
    return passed, rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("report", help="IR-drop report file or project/report dir")
    ap.add_argument("--vdd", type=float, default=None,
                    help="supply voltage in Volts (overrides report vdd key)")
    ap.add_argument("--budget-pct", type=float, default=_DEFAULT_BUDGET_PCT,
                    help=f"static IR budget as %% of Vdd (default {_DEFAULT_BUDGET_PCT})")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    in_path = Path(args.report)
    report_path = _discover_report(in_path)
    if report_path is None:
        print(f"ERROR: no IR-drop report found at {in_path}", file=sys.stderr)
        return 2

    if args.budget_pct <= 0:
        print("ERROR: --budget-pct must be positive", file=sys.stderr)
        return 2

    passed, rep = evaluate(report_path, args.vdd, args.budget_pct)
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
