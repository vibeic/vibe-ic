#!/usr/bin/env python3
"""metal_layer_density_check.py — PER-LAYER metal-density sign-off gate for tapeout.

The tapeout-signoff survey found the existing `metal_fill_density_check.py` gates on
the WRONG axis: it reads `density.json` = ROW / core utilization, not per-layer METAL
density. A foundry CMP rule (and Efabless mpw_precheck's `met_min_ca_density`) is a
PER-LAYER window: each metal layer's filled-area fraction must sit within [min, max]
(e.g. sky130 met1..met5 ~ 30%..70%). A sparse design passes row-util but FAILs the
per-layer metal-density rule at precheck. This gate closes that axis.

    For each metal layer L:  min_L  <=  density(L)  <=  max_L
    PASS iff EVERY layer is within its window.

Report schemas accepted:
  1. JSON — a per-layer density map, any of:
       {"layers": {"met1": 0.42, "met2": 0.55, ...}}
       {"per_layer_density": {"met1": {"density": 0.42}, ...}}
       {"met1_density": 0.42, "met2_density": 0.55, ...}      (flat keys)
     Density given as a fraction (0..1) or a percentage (>1 treated as %).
  2. KLayout/Magic density report (.rpt/.txt) — lines like
       "met1 density = 42.3%"  /  "Layer met1: 0.423"  /  "met1  0.42  PASS"
     scraped per layer.
  Windows: from a supplied `--windows JSON` ({"met1":[0.3,0.7], ...}), else a
  supplied per-report `windows`/`limits` block, else the generic default window
  (`_DEFAULT_MIN`.._DEFAULT_MAX`) applied to every discovered metal layer — with
  the default DISCLOSED in the verdict (an honest generic bound, not a foundry number).

§4.05 honest-failure (NO vacuous pass):
  * report absent / unreadable                        → rc 2 (IO error)
  * present but NO per-layer metal density found      → FAIL (rc 1)  (never PASS on
                                                         an empty/mis-shaped report)
  * any layer OUTSIDE its window                      → FAIL (rc 1) naming the layer
  * every layer within window                         → PASS (rc 0)
A layer with a density value but NO window (and no default requested) is reported as
UNCHECKED and makes the gate FAIL (a metal layer with no density rule is not a pass).

chip-AGNOSTIC: pure per-layer numeric compare; metal-layer names are discovered from
the report, no chip literal.

Usage:
    python3 metal_layer_density_check.py <report> [--windows WIN.json]
        [--default-min M] [--default-max X] [--json OUT]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Generic default window when no foundry windows are supplied. DISCLOSED as generic.
_DEFAULT_MIN = 0.30
_DEFAULT_MAX = 0.70

# A metal-layer token: met1..metN / metalN / mN / topmetalN (case-insensitive).
_METAL_RE = re.compile(r"^(met(?:al)?\d+|m\d+|topmetal\d+|cap?metal\d+)$",
                       re.IGNORECASE)
# .rpt scrape: "<layer> ... <num>[%]" with an explicit density context on the line.
_RPT_LINE_RE = re.compile(
    r"\b(met(?:al)?\d+|m\d+|topmetal\d+)\b[^0-9]*([0-9]*\.?[0-9]+)\s*(%?)",
    re.IGNORECASE)


def _norm_density(v: float) -> float:
    """A value >1 is a percentage → fraction."""
    return v / 100.0 if v > 1.0 else v


def _densities_from_json(d: dict) -> Dict[str, float]:
    out: Dict[str, float] = {}
    # {"layers": {...}} / {"per_layer_density": {...}}
    for container_key in ("layers", "per_layer_density", "metal_density",
                          "density_per_layer"):
        sub = d.get(container_key)
        if isinstance(sub, dict):
            for k, v in sub.items():
                if isinstance(v, dict):
                    v = v.get("density", v.get("value"))
                try:
                    out[k.lower()] = _norm_density(float(v))
                except (TypeError, ValueError):
                    continue
    # flat "<met>_density" keys
    for k, v in d.items():
        m = re.match(r"(met(?:al)?\d+|m\d+|topmetal\d+)_density$", k, re.IGNORECASE)
        if m:
            try:
                out[m.group(1).lower()] = _norm_density(float(v))
            except (TypeError, ValueError):
                continue
    return out


def _densities_from_rpt(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for line in text.splitlines():
        if "densit" not in line.lower() and "%" not in line:
            continue
        m = _RPT_LINE_RE.search(line)
        if not m:
            continue
        layer = m.group(1).lower()
        val = float(m.group(2))
        if m.group(3) == "%":
            val = val / 100.0
        else:
            val = _norm_density(val)
        out[layer] = val
    return out


def _load_windows(path: Optional[Path]) -> Dict[str, Tuple[float, float]]:
    if path is None or not path.is_file():
        return {}
    try:
        d = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    win: Dict[str, Tuple[float, float]] = {}
    for k, v in (d.items() if isinstance(d, dict) else []):
        try:
            lo, hi = float(v[0]), float(v[1])
            win[k.lower()] = (_norm_density(lo), _norm_density(hi))
        except (TypeError, ValueError, IndexError):
            continue
    return win


def check(report: Path, windows: Dict[str, Tuple[float, float]],
          default_min: Optional[float],
          default_max: Optional[float]) -> Dict[str, object]:
    if report.is_dir():
        for pat in ("*density*layer*.json", "*metal*density*.json",
                    "*density*.rpt", "*density*.txt"):
            hits = sorted(report.rglob(pat))
            if hits:
                report = hits[0]
                break
    if not report.is_file():
        return {"verdict": "IO_ERROR", "error": f"no density report at {report}"}
    try:
        raw = report.read_text(errors="replace")
    except OSError as e:
        return {"verdict": "IO_ERROR", "error": str(e)}

    dens: Dict[str, float] = {}
    report_windows: Dict[str, Tuple[float, float]] = {}
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            dens = _densities_from_json(d)
            rw = d.get("windows") or d.get("limits")
            if isinstance(rw, dict):
                for k, v in rw.items():
                    try:
                        report_windows[k.lower()] = (_norm_density(float(v[0])),
                                                     _norm_density(float(v[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
    except (json.JSONDecodeError, ValueError):
        dens = _densities_from_rpt(raw)

    dens = {k: v for k, v in dens.items() if _METAL_RE.match(k)}
    if not dens:
        return {"verdict": "FAIL",
                "detail": "no per-layer metal density found in the report "
                          "(present but carries no per-layer metal-density data)"}

    use_default = default_min is not None and default_max is not None
    per_layer: Dict[str, dict] = {}
    failures: List[str] = []
    unchecked: List[str] = []
    for layer, val in sorted(dens.items()):
        win = windows.get(layer) or report_windows.get(layer)
        src = "supplied"
        if win is None and use_default:
            win = (default_min, default_max)
            src = "generic-default"
        if win is None:
            unchecked.append(layer)
            per_layer[layer] = {"density": val, "window": None,
                                "status": "UNCHECKED"}
            continue
        lo, hi = win
        ok = lo <= val <= hi
        per_layer[layer] = {"density": round(val, 4), "window": [lo, hi],
                            "window_source": src,
                            "status": "PASS" if ok else "FAIL"}
        if not ok:
            failures.append(f"{layer}: density={val:.3f} outside [{lo:.2f},{hi:.2f}]")

    # §4.05: an UNCHECKED metal layer (density but no rule) is NOT a pass.
    passed = not failures and not unchecked
    res: Dict[str, object] = {
        "verdict": "PASS" if passed else "FAIL",
        "per_layer": per_layer,
        "report": str(report),
    }
    if failures:
        res["failures"] = failures
    if unchecked:
        res["unchecked_layers"] = unchecked
        res["unchecked_note"] = ("metal layers with a density but no window are "
                                 "NOT a pass — supply --windows or --default-min/max")
    if use_default and any(v.get("window_source") == "generic-default"
                           for v in per_layer.values()):
        res["window_note"] = (f"generic default window "
                              f"[{default_min},{default_max}] applied — supply the "
                              f"foundry per-layer windows for a real sign-off")
    return res


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Per-layer metal-density sign-off gate.")
    ap.add_argument("report", help="per-layer density report (JSON/.rpt) or dir")
    ap.add_argument("--windows", default=None,
                    help="JSON {layer:[min,max]} foundry per-layer windows")
    ap.add_argument("--default-min", type=float, default=None,
                    help="generic default min density for layers without a window")
    ap.add_argument("--default-max", type=float, default=None,
                    help="generic default max density for layers without a window")
    ap.add_argument("--use-generic", action="store_true",
                    help=f"apply the generic default window "
                         f"[{_DEFAULT_MIN},{_DEFAULT_MAX}] to unruled layers")
    ap.add_argument("--json", dest="json_out", default=None)
    ns = ap.parse_args(argv)
    dmin, dmax = ns.default_min, ns.default_max
    if ns.use_generic and dmin is None and dmax is None:
        dmin, dmax = _DEFAULT_MIN, _DEFAULT_MAX
    res = check(Path(ns.report), _load_windows(Path(ns.windows) if ns.windows else None),
                dmin, dmax)
    out = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(out)
    print(out)
    if res["verdict"] == "IO_ERROR":
        return 2
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
