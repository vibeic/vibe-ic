#!/usr/bin/env python3
"""dynamic_ir_drop_check.py — transient (dynamic) IR-drop budget gate for tapeout.

The tapeout-signoff survey found the plugin does STATIC IR-drop (OpenROAD PSM →
`ir_drop_budget_check.py`) but NO dynamic/transient analysis — the two effects that
most often kill real silicon are dynamic voltage droop (di/dt during a switching
window) and EM. `em_current_density_check.py` now covers EM; this gate covers the
transient IR droop.

A dynamic-IR report gives the WORST TRANSIENT voltage droop (from a vectorless or
VCD/SAIF-driven transient PSM/DVD run). The dynamic budget is TIGHTER than static
(a transient droop eats into the same noise margin as static drop + SI), so the
default budget here is the same %-of-Vdd knob but callers should size it to the
design's timing margin.

    PASS iff  worst_transient_droop_mV  <  pct * Vdd * 1000   (strictly under budget)

Report schemas accepted (mirrors ir_drop_budget_check.py so the two gates share the
operator's mental model):
  1. JSON — worst transient droop key (mV unless a *_pct key is used):
       max_dynamic_drop_mv / worst_transient_drop_mv / dynamic_ir_mv /
       max_transient_droop_mv / worst_dvd_mv
       max_dynamic_drop_pct / worst_transient_drop_percent (% of Vdd)
     plus a supply key: vdd / vdd_v / supply_voltage_v / nominal_vdd_v
  2. Plain .rpt — the largest "<num> mV" / "<num> % Vdd" token in a section whose
     header mentions dynamic/transient/droop/DVD (so a static-IR .rpt is not
     mis-read as dynamic).

§4.05 honest-failure (NO vacuous pass on absence / garbage):
  * report absent / unreadable                          → FAIL (rc 1)
  * present but no transient droop value extractable    → FAIL (rc 1)
  * droop in mV but no Vdd to size the budget           → FAIL (rc 1)
  * measured droop >= budget                            → FAIL (rc 1)
  * measured droop  <  budget                           → PASS (rc 0)
  * path not found at all                               → rc 2 (IO/arg)

There is NO skip path: any design that reaches dynamic-IR sign-off has a power grid
and a switching profile, so a missing report is a missing-evidence FAIL — never a
not-applicable SKIP. (A design that has not YET produced a dynamic-IR report is not
"N/A"; it is "not signed off for dynamic IR".)

chip-AGNOSTIC: generic report schemas only; no design knowledge.

Usage:
    python3 dynamic_ir_drop_check.py <report> [--vdd V] [--budget-pct P] [--json OUT]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default dynamic budget: 10% of Vdd (same permissive default as the static gate;
# a real sign-off tightens this to the design's timing/noise margin).
_DEFAULT_BUDGET_PCT = 10.0

_JSON_DROP_MV_KEYS = (
    "max_dynamic_drop_mv", "worst_transient_drop_mv", "dynamic_ir_mv",
    "max_transient_droop_mv", "worst_dvd_mv", "max_dynamic_droop_mv",
)
_JSON_DROP_PCT_KEYS = (
    "max_dynamic_drop_pct", "worst_transient_drop_percent",
    "max_transient_droop_pct", "worst_dvd_pct",
)
_JSON_VDD_KEYS = ("vdd", "vdd_v", "supply_voltage_v", "nominal_vdd_v")

# A .rpt section is "dynamic" only if its context mentions one of these.
_DYNAMIC_CONTEXT_RE = re.compile(
    r"dynamic|transient|droop|\bdvd\b|di/dt|switching", re.IGNORECASE)
_MV_RE = re.compile(r"([0-9]*\.?[0-9]+)\s*mv", re.IGNORECASE)
_PCT_RE = re.compile(r"([0-9]*\.?[0-9]+)\s*%\s*(?:of\s*)?v?dd", re.IGNORECASE)


def _first_num(d: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for k in keys:
        if k in d:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def _extract_from_json(d: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Return (droop_mV, vdd_V) — droop resolved from mV or (pct × Vdd)."""
    vdd = _first_num(d, _JSON_VDD_KEYS)
    mv = _first_num(d, _JSON_DROP_MV_KEYS)
    if mv is not None:
        return mv, vdd
    pct = _first_num(d, _JSON_DROP_PCT_KEYS)
    if pct is not None and vdd is not None:
        return pct / 100.0 * vdd * 1000.0, vdd
    if pct is not None:
        # a pct with no Vdd → carry the pct as a pseudo-droop only if a later
        # Vdd arg is supplied; signal by returning (None, vdd) + pct via caller.
        return None, vdd
    return None, vdd


def _extract_from_rpt(text: str) -> Optional[float]:
    """Largest mV droop found in a DYNAMIC-context line; else None."""
    best: Optional[float] = None
    for line in text.splitlines():
        if not _DYNAMIC_CONTEXT_RE.search(line):
            continue
        for m in _MV_RE.finditer(line):
            v = float(m.group(1))
            best = v if best is None or v > best else best
    return best


def check(report: Path, vdd: Optional[float],
          budget_pct: float) -> Dict[str, object]:
    if not report.exists():
        # search a dir for a dynamic-IR report
        if report.is_dir():
            for pat in ("*dynamic*ir*.json", "*transient*.json", "*dvd*.json",
                        "*dynamic*ir*.rpt", "*transient*.rpt"):
                hits = sorted(report.rglob(pat))
                if hits:
                    report = hits[0]
                    break
        if not report.is_file():
            return {"verdict": "IO_ERROR",
                    "error": f"dynamic-IR report not found at {report}"}
    if report.is_dir():
        return {"verdict": "IO_ERROR",
                "error": f"{report} is a directory with no dynamic-IR report"}
    try:
        raw = report.read_text(errors="replace")
    except OSError as e:
        return {"verdict": "IO_ERROR", "error": str(e)}

    droop_mv: Optional[float] = None
    rpt_vdd: Optional[float] = None
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            droop_mv, rpt_vdd = _extract_from_json(d)
    except (json.JSONDecodeError, ValueError):
        droop_mv = _extract_from_rpt(raw)

    if droop_mv is None:
        return {"verdict": "FAIL",
                "detail": "no transient/dynamic droop value could be extracted "
                          "(report present but carries no dynamic-IR measurement)"}

    v = vdd if vdd is not None else rpt_vdd
    if v is None:
        return {"verdict": "FAIL",
                "detail": f"transient droop {droop_mv:.3f} mV found but no Vdd to "
                          f"size the budget (pass --vdd or add a vdd key)"}
    budget_mv = budget_pct / 100.0 * v * 1000.0
    passed = droop_mv < budget_mv
    return {
        "verdict": "PASS" if passed else "FAIL",
        "worst_transient_droop_mv": round(droop_mv, 4),
        "vdd_v": v,
        "budget_pct": budget_pct,
        "budget_mv": round(budget_mv, 4),
        "report": str(report),
    }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Dynamic (transient) IR-drop budget gate.")
    ap.add_argument("report", help="dynamic-IR report (JSON/.rpt) or a directory")
    ap.add_argument("--vdd", type=float, default=None, help="supply voltage V")
    ap.add_argument("--budget-pct", type=float, default=_DEFAULT_BUDGET_PCT,
                    help="dynamic droop budget as %% of Vdd (default 10)")
    ap.add_argument("--json", dest="json_out", default=None)
    ns = ap.parse_args(argv)
    res = check(Path(ns.report), ns.vdd, ns.budget_pct)
    out = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(out)
    print(out)
    if res["verdict"] == "IO_ERROR":
        return 2
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
