#!/usr/bin/env python3
"""metal_layer_density_check.py — PER-LAYER metal-density sign-off gate for tapeout.

The tapeout-signoff survey found the existing `metal_fill_density_check.py` gates on
the WRONG axis: it reads `density.json` = ROW / core utilization, not per-layer METAL
density. A foundry CMP rule (and the equivalent min-clear-area pattern-density rule
run at precheck) is a PER-LAYER window: each metal layer's filled-area fraction must
sit within [min, max]. A sparse design passes row-util but FAILs the per-layer
metal-density rule at precheck. This gate closes that axis.

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
  Windows: from `--pdk NAME` (that PDK's OWN stated per-layer windows, served by
  `pdk_metal_density_windows`), else a supplied `--windows JSON`
  ({"met1":[0.3,0.7], ...}), else a supplied per-report `windows`/`limits` block,
  else the generic default window (`_DEFAULT_MIN`.._DEFAULT_MAX`) applied to every
  discovered metal layer — with the default DISCLOSED in the verdict (an honest
  generic bound, not a foundry number).

  A supplied window may state only ONE bound (`[0.30, null]`): some processes
  state a minimum coverage and no ceiling. Each bound is then resolved and
  DISCLOSED INDEPENDENTLY — the stated bound is used as stated, and the unstated
  one falls back to the generic default carrying its own `generic-default` label.
  This matters because the two claims are not the same: "the foundry requires
  >=30%" is a foundry rule, "<=70%" next to it is our generic guess, and a single
  window_source string covering both would misattribute half of the verdict.

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
    python3 metal_layer_density_check.py <report> [--pdk NAME] [--windows WIN.json]
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

# A per-layer window. Either bound may be None, meaning "not stated" — see
# `_resolve_window`. This is NOT the same as an absent window (no rule at all).
Window = Tuple[Optional[float], Optional[float]]

# THE layer-name shape this gate judges, stated ONCE. Every place that needs to
# recognise a layer name is built from this token below, because the previous
# arrangement restated it three times (this filter, the .rpt scraper, the flat-
# key matcher) and a fourth time in the producer — and they had already drifted
# apart once, which is what shipped a measurement nobody judged.
#
# `li\d+` is the local-interconnect layer. It is here because it is a REGULATED
# layer, not because it is metal: at least one open PDK's own sign-off script
# checks it against the same window as its first routing layers, and its DRC
# deck gives it its own density rule id alongside them. It was being measured
# and then dropped here, so the number reached the report and no verdict.
#
# The trailing digit is load-bearing: it is what separates a routing/interconnect
# layer from the CONTACT layer whose name it prefixes (…con1), which is a cut,
# not a plane, and carries no area-density rule.
_METAL_LAYER_TOKEN = r"met(?:al)?\d+|m\d+|topmetal\d+|cap?metal\d+|li\d+"

# Full-name match: the filter that decides which measured layers get judged.
_METAL_RE = re.compile(r"^(%s)$" % _METAL_LAYER_TOKEN, re.IGNORECASE)
# .rpt scrape: "<layer> ... <num>[%]" with an explicit density context on the line.
_RPT_LINE_RE = re.compile(
    r"\b(%s)\b[^0-9]*([0-9]*\.?[0-9]+)\s*(%%?)" % _METAL_LAYER_TOKEN,
    re.IGNORECASE)
# Flat "<layer>_density" JSON keys.
_FLAT_KEY_RE = re.compile(r"(%s)_density$" % _METAL_LAYER_TOKEN, re.IGNORECASE)


def pdk_windows_for(pdk: str) -> Tuple[Dict[str, Window], Dict[str, object]]:
    """That PDK's OWN stated per-layer windows + where they were measured from.

    Kept behind a function (not a module-level import) so this gate still runs
    standalone from a stripped install: an unavailable registry degrades to "no
    windows", which is the pre-existing generic-default behaviour, rather than
    an ImportError at the top of a sign-off gate."""
    try:
        import pdk_metal_density_windows as _pw
    except ImportError:  # pragma: no cover - stripped install
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import pdk_metal_density_windows as _pw
        except ImportError:
            return {}, {"status": "unknown-pdk", "pdk": pdk,
                        "detail": "PDK window table unavailable in this install"}
    return _pw.windows_for_pdk(pdk)


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
    # flat "<layer>_density" keys
    for k, v in d.items():
        m = _FLAT_KEY_RE.match(k)
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


def _opt_density(v: object) -> Optional[float]:
    """A stated bound -> fraction; an explicit null -> None (bound NOT stated).

    None is not a parse failure here — it is the whole point. A window may state
    one side only, and the distinction between "no bound stated" and "bound is
    0.0" has to survive the load or the fallback below cannot be honest."""
    if v is None:
        return None
    try:
        return _norm_density(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _load_windows(path: Optional[Path]) -> Dict[str, Window]:
    if path is None or not path.is_file():
        return {}
    try:
        d = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    win: Dict[str, Window] = {}
    for k, v in (d.items() if isinstance(d, dict) else []):
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            continue
        lo, hi = _opt_density(v[0]), _opt_density(v[1])
        if lo is None and hi is None:
            continue  # states neither bound => states nothing
        win[k.lower()] = (lo, hi)
    return win


def _resolve_window(win: Optional[Window],
                    default_min: Optional[float],
                    default_max: Optional[float],
                    supplied_label: str
                    ) -> Tuple[Optional[float], Optional[float], str]:
    """Resolve one layer's window BOUND BY BOUND and label where each came from.

    Returns (lo, hi, window_source). A None in either returned bound means the
    layer cannot be judged on that side and the caller must treat it as
    UNCHECKED — never as a pass.

    The per-bound split exists because a partially-stated window is real: a
    process may require a minimum coverage and state no ceiling. Resolving the
    pair as a unit would force a choice between discarding the stated minimum
    and inventing a maximum, and labelling the pair with one source string would
    then report a generic guess under a foundry's name."""
    sup_lo, sup_hi = win if win is not None else (None, None)
    lo = sup_lo if sup_lo is not None else default_min
    hi = sup_hi if sup_hi is not None else default_max
    lo_src = supplied_label if sup_lo is not None else "generic-default"
    hi_src = supplied_label if sup_hi is not None else "generic-default"
    if lo_src == hi_src:
        return lo, hi, lo_src
    return lo, hi, f"min={lo_src},max={hi_src}"


def check(report: Path, windows: Dict[str, Window],
          default_min: Optional[float],
          default_max: Optional[float],
          windows_provenance: Optional[Dict[str, object]] = None
          ) -> Dict[str, object]:
    if report.is_dir():
        # `.log` LAST, and it is load-bearing. MEASURED: a KLayout density deck
        # writes its per-layer ratios ONLY into its run transcript —
        #     `... : Metal1 ratio: 43.811811093445066 %`
        # — while the `.json` beside it is a per-RULE violation tally
        # (`{"DCF.1b": 0, ...}`) carrying no per-layer density at all. Handed the
        # project directory, this scan found neither and returned
        #     {"verdict": "IO_ERROR", "error": "no density report at <dir>"}
        # i.e. rc 2, which the caller reads as "could not measure" — on a project
        # whose densities were sitting in that same directory. Ordered last so
        # every existing preference still wins; a transcript that carries no
        # per-layer density still FAILs on the "no per-layer metal density found"
        # branch rather than passing, so widening the scan cannot fabricate a
        # verdict.
        for pat in ("*density*layer*.json", "*metal*density*.json",
                    "*density*.rpt", "*density*.txt", "*density*.log"):
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

    per_layer: Dict[str, dict] = {}
    failures: List[str] = []
    unchecked: List[str] = []
    for layer, val in sorted(dens.items()):
        win = windows.get(layer)
        label = "supplied"
        if win is None:
            win = report_windows.get(layer)
            label = "report"
        lo, hi, src = _resolve_window(win, default_min, default_max, label)
        if lo is None or hi is None:
            # No rule on at least one side and no default to fall back on.
            unchecked.append(layer)
            per_layer[layer] = {"density": round(val, 4),
                                "window": None if (lo is None and hi is None)
                                          else [lo, hi],
                                "status": "UNCHECKED"}
            continue
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
    # Disclose the generic default whenever ANY bound of ANY layer fell back to
    # it — including the half-and-half case, where a foundry-stated minimum sits
    # next to a generic ceiling. Matching the whole string would have silently
    # dropped exactly that case, which is the one most likely to be misread as a
    # fully foundry-judged verdict.
    generic_bound_layers = sorted(
        layer for layer, v in per_layer.items()
        if "generic-default" in str(v.get("window_source", "")))
    if generic_bound_layers:
        res["window_note"] = (
            f"generic default window [{default_min},{default_max}] supplied at "
            f"least one bound for: {', '.join(generic_bound_layers)} — a generic "
            f"bound, NOT a foundry number")
    if windows_provenance:
        res["windows_provenance"] = windows_provenance
    return res


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Per-layer metal-density sign-off gate.")
    ap.add_argument("report", help="per-layer density report (JSON/.rpt) or dir")
    ap.add_argument("--pdk", default=None,
                    help="PDK name — judge against THAT PDK's own stated "
                         "per-layer windows (from the PDK registry)")
    ap.add_argument("--windows", default=None,
                    help="JSON {layer:[min,max]} foundry per-layer windows; a "
                         "bound may be null to mean 'not stated'")
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
    windows = _load_windows(Path(ns.windows) if ns.windows else None)
    provenance: Optional[Dict[str, object]] = None
    if ns.pdk:
        pdk_windows, provenance = pdk_windows_for(ns.pdk)
        # An explicit --windows file is the operator speaking directly and wins
        # over the registry, per layer.
        merged = dict(pdk_windows)
        merged.update(windows)
        windows = merged
    res = check(Path(ns.report), windows, dmin, dmax, provenance)
    out = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(out)
    print(out)
    if res["verdict"] == "IO_ERROR":
        return 2
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
