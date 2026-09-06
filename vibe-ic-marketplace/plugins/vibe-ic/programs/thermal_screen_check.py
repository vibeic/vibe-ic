#!/usr/bin/env python3
"""thermal_screen_check.py — power-density / junction-temperature screen.

The tapeout-signoff survey found thermal was MISSING from the flow — only
a recommendation string ("consider thermal"), never a deterministic
verdict. A design can pass DRC/LVS/STA/IR and still cook itself: if the
total power dissipated per unit die area (power density, W/mm²) is too
high for the package/cooling, the junction temperature Tj rises, which in
turn accelerates aging and can push Tj past its rated maximum.

This gate is a FIRST-ORDER power-density screen (honestly labeled — NOT a
full self-heating thermal solve):

    PASS iff  power_density (W/mm²)  <  limit
              AND (Tj < Tj_max        when a Tj estimate is available)

power_density = total_power_W / die_area_mm²

It reads:
  * total power from a power report — JSON keys
      total_power_w / total_power / power_w  (also *_mw → /1000);
      if only dynamic+leakage are present it SUMS them; OR a plain
      OpenROAD `report_power` .rpt ("Total ... <watts>" summary row,
      "Total Power = <n> W", etc.).
  * die area from — a supplied --die-area-mm2 / --die-area-um2, OR a DEF
      (DIEAREA ( x1 y1 ) ( x2 y2 ) ; scaled by UNITS DISTANCE MICRONS),
      OR a floorplan JSON key die_area_mm2 / die_area_um2.

Junction temperature (optional, gated only when available):
  * a Tj value from the power/thermal report (JSON tj_c / junction_temp_c,
    or "Tj = <n> C" text), OR
  * a first-order estimate Tj = T_ambient + P_total × θ_ja, computed when
    both --theta-ja (°C/W) and --ambient (°C) are supplied.
  When a Tj is available it is gated against Tj_max (default 125 °C).

Honest-verdict rules (NO vacuous pass on absence):
  * power report absent / unreadable                      → SKIP (rc 3)
  * power report present but no total power extractable    → SKIP (rc 3)
      (e.g. a power_report_gen fallback with "not_computed" — the open
       PDK could not compute power; SKIP, never fabricate a density)
  * die area absent (no --die-area, no DEF, no floorplan)  → SKIP (rc 3)
  * die area degenerate / non-positive                     → SKIP (rc 3)
  * power_density  >=  limit                               → FAIL (rc 1)
      (names the hotspot metric: power density)
  * Tj  >=  Tj_max  (when a Tj is available)               → FAIL (rc 1)
  * power_density < limit AND (Tj < Tj_max or no Tj)       → PASS (rc 0)
  * report/inputs path not found at all                    → rc 2 (IO/arg)

SKIP (rc 3) is a distinct "cannot judge / not supplied" verdict — it is
NEVER conflated with PASS.

Honest scope (disclosed, not fabricated):
  * A full thermal sign-off needs a THERMAL SOLVER (a self-heating map:
    per-cell power → chip/package thermal RC network → Tj hotspot map).
    This gate is a FIRST-ORDER lumped power-density screen: it flags a
    design whose average W/mm² exceeds a package limit, and gates Tj only
    against a lumped θ_ja estimate (or a Tj a real solver already emitted).
    It does NOT localize hotspots and does NOT replace a thermal solver.

Usage:
    python3 thermal_screen_check.py <power_report_or_dir>
            [--die-source DEF_OR_JSON | --die-area-mm2 A | --die-area-um2 A]
            [--limit-w-per-mm2 L] [--tj-max C]
            [--theta-ja C_per_W --ambient C] [--json OUT]

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error / 3 SKIP.

chip-AGNOSTIC: reads only generic power/DEF schemas; no design/PDK literal
appears in any rule.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import _declared_die as _dd                                     # noqa: E402

_VERSION = "1.0.0"

# Default first-order air-cooled-package screen limit. Power density is
# strongly package/cooling dependent; 1.0 W/mm² is a permissive default that
# never FAILs a design a stricter house rule would also pass (mirrors the
# ir_drop_budget_check permissive-default doctrine). Override per package.
_DEFAULT_LIMIT_W_PER_MM2 = 1.0
# Default commercial-grade junction-temperature ceiling.
_DEFAULT_TJ_MAX_C = 125.0

# --- power (Watts) JSON keys ---
_TOTAL_W_KEYS = ("total_power_w", "total_power", "power_w", "p_total_w",
                 "total_watts")
_TOTAL_MW_KEYS = ("total_power_mw", "power_mw", "total_mw")
_DYN_W_KEYS = ("dynamic_power_w", "switching_power_w", "dynamic_power",
               "internal_plus_switching_w")
_DYN_MW_KEYS = ("dynamic_power_mw", "switching_power_mw")
_LEAK_W_KEYS = ("leakage_power_w", "static_power_w", "leakage_power")
_LEAK_MW_KEYS = ("leakage_power_mw", "static_power_mw")

# --- junction temp JSON keys ---
_TJ_KEYS = ("tj_c", "junction_temp_c", "junction_temperature_c", "tj",
            "max_junction_temp_c")

# --- die-area JSON keys ---
_AREA_MM2_KEYS = ("die_area_mm2", "die_area_mm^2", "die_area_mm")
_AREA_UM2_KEYS = ("die_area_um2", "die_area_um^2", "die_area_um", "die_area")

# --- text scrapers ---
# OpenROAD report_power summary row is
#   Total   <internal> <switching> <leakage> <TOTAL> <pct>%
# The TOTAL-power column is the LAST watt-scale number AFTER the trailing
# percentage token is stripped (a naive "largest / last number" grabs the
# "100.0%" and is wrong).
_TOTAL_LINE_RE = re.compile(r"^[ \t]*Total\b(.*)$", re.IGNORECASE | re.MULTILINE)
_PCT_TOKEN_RE = re.compile(r"[-+]?\d+(?:\.\d+)?\s*%")
_FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_TOTAL_EQ_RE = re.compile(
    r"Total\s*Power\s*[=:]\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(m?)W",
    re.IGNORECASE)
_NOT_COMPUTED_RE = re.compile(r"not_computed", re.IGNORECASE)
_TJ_TEXT_RE = re.compile(
    r"\bTj\b\s*[=:]\s*([-+]?\d+(?:\.\d+)?)\s*(?:°?\s*C)?", re.IGNORECASE)

# DEF parsing.
_DIEAREA_RE = re.compile(
    r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)")
_UNITS_RE = re.compile(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", re.IGNORECASE)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _first_key(scope: Dict[str, Any], keys, scale: float = 1.0
               ) -> Optional[float]:
    for k in keys:
        if k in scope:
            v = _num(scope[k])
            if v is not None:
                return v * scale
    return None


def _power_from_json(data: Any) -> Tuple[Optional[float], str]:
    """Return (total_power_W, provenance) — sums dyn+leak when total absent."""
    if not isinstance(data, dict):
        return None, "not_a_dict"
    scopes = [data]
    for k in ("summary", "power", "total"):
        sub = data.get(k)
        if isinstance(sub, dict):
            scopes.append(sub)
    for scope in scopes:
        tw = _first_key(scope, _TOTAL_W_KEYS)
        if tw is None:
            tw = _first_key(scope, _TOTAL_MW_KEYS, 1e-3)
        if tw is not None:
            return tw, "total_power_key"
    # Fall back to dynamic + leakage sum.
    for scope in scopes:
        dyn = _first_key(scope, _DYN_W_KEYS)
        if dyn is None:
            dyn = _first_key(scope, _DYN_MW_KEYS, 1e-3)
        leak = _first_key(scope, _LEAK_W_KEYS)
        if leak is None:
            leak = _first_key(scope, _LEAK_MW_KEYS, 1e-3)
        if dyn is not None or leak is not None:
            return (dyn or 0.0) + (leak or 0.0), "dynamic_plus_leakage_sum"
    return None, "no_power_key"


def _power_from_text(text: str) -> Tuple[Optional[float], str]:
    """Return (total_power_W, provenance) scraped from a report_power .rpt."""
    m = _TOTAL_EQ_RE.search(text)
    if m:
        val = _num(m.group(1))
        if val is not None:
            return (val * 1e-3 if m.group(2).lower() == "m" else val), "total_eq"
    # OpenROAD "Total" summary row — strip the trailing percentage, then the
    # TOTAL-power column is the LAST watt-scale number. Use the LAST such
    # "Total" line so a bottom summary wins over any per-group "Total".
    result: Optional[float] = None
    for lm in _TOTAL_LINE_RE.finditer(text):
        rest = _PCT_TOKEN_RE.sub(" ", lm.group(1))
        nums = [n for n in (_num(x) for x in _FLOAT_RE.findall(rest))
                if n is not None]
        if nums:
            result = nums[-1]
    if result is not None:
        return result, "total_row"
    return None, "no_total"


def _tj_from(data: Any, text: str) -> Optional[float]:
    if isinstance(data, dict):
        scopes = [data]
        for k in ("summary", "thermal", "power"):
            sub = data.get(k)
            if isinstance(sub, dict):
                scopes.append(sub)
        for scope in scopes:
            v = _first_key(scope, _TJ_KEYS)
            if v is not None:
                return v
    m = _TJ_TEXT_RE.search(text)
    if m:
        return _num(m.group(1))
    return None


def _die_area_mm2_from_text(text: str) -> Tuple[Optional[float], str]:
    """Return (die_area_mm2, provenance) from a DEF's DIEAREA + UNITS."""
    m = _DIEAREA_RE.search(text)
    if not m:
        return None, "no_diearea"
    x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
    dbu_m = _UNITS_RE.search(text)
    dbu = int(dbu_m.group(1)) if dbu_m else 1000  # sky130/gf180 default 1000
    w_um = (x2 - x1) / dbu
    h_um = (y2 - y1) / dbu
    area_um2 = w_um * h_um
    return area_um2 / 1e6, f"def_diearea(dbu={dbu})"


def _die_area_mm2_from_json(data: Any) -> Tuple[Optional[float], str]:
    if not isinstance(data, dict):
        return None, "not_a_dict"
    scopes = [data]
    for k in ("summary", "floorplan", "die"):
        sub = data.get(k)
        if isinstance(sub, dict):
            scopes.append(sub)
    for scope in scopes:
        mm2 = _first_key(scope, _AREA_MM2_KEYS)
        if mm2 is not None:
            return mm2, "json_mm2"
        um2 = _first_key(scope, _AREA_UM2_KEYS)
        if um2 is not None:
            return um2 / 1e6, "json_um2"
    return None, "no_area_key"


def _resolve_die_area_mm2(die_source: Optional[Path],
                          area_mm2: Optional[float],
                          area_um2: Optional[float],
                          project: Optional[Path] = None,
                          ) -> Tuple[Optional[float], str]:
    """Resolve die area to mm² — the RUN'S DECLARED DIE before any DEF.

    vibe-ic#2058 FP-15. A power DENSITY is a power divided by a die area, and
    on a SLOT run `DIEAREA` is the placeable CORE, not the die: measured
    1052 x 1647 um stated as the die of a 1936 x 2531 um slot, which is 2.4x
    too small and makes every density on such a run 2.4x too large. The run's
    own floorplan record answers first; the DEF is consulted only after it, and
    the provenance token says which of the two the number came from, so a
    reader is never left to infer it.
    """
    if area_mm2 is not None:
        return area_mm2, "cli_mm2"
    if area_um2 is not None:
        return area_um2 / 1e6, "cli_um2"
    if project is not None:
        rect, why, _rec = _dd.declared(project)
        if rect is not None:
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            return (w * h) / 1e6, f"declared_die_record({why})"
    if die_source is None:
        return None, "no_die_source"
    try:
        raw = die_source.read_text(errors="replace")
    except OSError as exc:
        return None, f"die_source_unreadable:{exc}"
    if die_source.suffix.lower() == ".json":
        try:
            return _die_area_mm2_from_json(json.loads(raw))
        except json.JSONDecodeError as exc:
            return None, f"die_source_bad_json:{exc}"
    return _die_area_mm2_from_text(raw)


def _discover_power_report(path: Path) -> Optional[Path]:
    if path.is_file():
        return path
    if path.is_dir():
        for pat in ("*power*.json", "*power*.rpt", "*power*.log",
                    "*Power*.rpt", "*Power*.log"):
            hits = sorted(path.rglob(pat))
            if hits:
                return hits[0]
    return None


def _discover_die_source(path: Path) -> Optional[Path]:
    """Find a DEF (DIEAREA) or floorplan JSON under a project dir."""
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    for pat in ("*floorplan*.def", "*.def", "*floorplan*.json",
                "*die_area*.json"):
        hits = sorted(path.rglob(pat))
        if hits:
            return hits[0]
    return None


def evaluate(power_path: Path, die_source: Optional[Path],
             area_mm2: Optional[float], area_um2: Optional[float],
             limit_w_per_mm2: float, tj_max_c: float,
             theta_ja: Optional[float], ambient_c: Optional[float],
             project: Optional[Path] = None,
             ) -> Tuple[str, Dict[str, Any]]:
    """Return (verdict, report). verdict in {PASS, FAIL, SKIP}."""
    rep: Dict[str, Any] = {
        "program": "thermal_screen_check",
        "version": _VERSION,
        "power_report": str(power_path),
        "limit_w_per_mm2": limit_w_per_mm2,
        "tj_max_c": tj_max_c,
        "findings": [],
    }

    # (1) power report.
    try:
        raw = power_path.read_text(errors="replace")
    except OSError as exc:
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "power_report_unreadable"
        rep["findings"].append({"severity": "SKIP", "rule": "POWER_REPORT_UNREADABLE",
                                "message": f"cannot read power report: {exc}"})
        return "SKIP", rep

    data = None
    if power_path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            rep["verdict"] = "SKIP"
            rep["skip_reason"] = "power_report_bad_json"
            rep["findings"].append({"severity": "SKIP", "rule": "POWER_REPORT_BAD_JSON",
                                    "message": f"unparseable JSON: {exc}"})
            return "SKIP", rep

    total_w, p_prov = (_power_from_json(data) if data is not None
                       else _power_from_text(raw))
    if total_w is None or total_w <= 0:
        # A power_report_gen fallback carrying "not_computed" lands here.
        reason = ("power_not_computed"
                  if (data is None and _NOT_COMPUTED_RE.search(raw))
                  else "no_total_power_value")
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = reason
        rep["findings"].append({
            "severity": "SKIP", "rule": "NO_TOTAL_POWER",
            "message": ("no positive total-power value in the power report "
                        f"({p_prov}); the open PDK could not compute power — "
                        "SKIP, never fabricate a density")})
        return "SKIP", rep

    # (2) die area.
    die_mm2, a_prov = _resolve_die_area_mm2(die_source, area_mm2, area_um2,
                                            project=project)
    if die_mm2 is None:
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "no_die_area"
        rep["findings"].append({
            "severity": "SKIP", "rule": "NO_DIE_AREA",
            "message": (f"no die area available ({a_prov}); supply "
                        "--die-area-mm2 / --die-area-um2 or a DEF/floorplan")})
        return "SKIP", rep
    if die_mm2 <= 0:
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "degenerate_die_area"
        rep["findings"].append({
            "severity": "SKIP", "rule": "DEGENERATE_DIE_AREA",
            "message": f"die area {die_mm2} mm² is non-positive ({a_prov})"})
        return "SKIP", rep

    power_density = total_w / die_mm2

    # (3) junction temperature — reported, or estimated from θ_ja + ambient.
    tj_c = _tj_from(data, raw)
    tj_prov = "report" if tj_c is not None else None
    if tj_c is None and theta_ja is not None and ambient_c is not None:
        tj_c = ambient_c + total_w * theta_ja
        tj_prov = f"estimate(Ta={ambient_c}+P*theta_ja={theta_ja})"

    rep["measured"] = {
        "total_power_w": total_w,
        "power_provenance": p_prov,
        "die_area_mm2": round(die_mm2, 6),
        "die_area_provenance": a_prov,
        "power_density_w_per_mm2": round(power_density, 6),
        "tj_c": tj_c,
        "tj_provenance": tj_prov,
    }

    # (4) verdict — power density is the primary gate; Tj gates when available.
    fails: List[str] = []
    if power_density >= limit_w_per_mm2:
        fails.append(
            f"HOTSPOT power density {power_density:.4f} W/mm² >= limit "
            f"{limit_w_per_mm2:.4f} W/mm² (total {total_w:.4g} W over "
            f"{die_mm2:.4g} mm²)")
    if tj_c is not None and tj_c >= tj_max_c:
        fails.append(f"junction temperature Tj {tj_c:.2f} °C >= Tj_max "
                     f"{tj_max_c:.2f} °C ({tj_prov})")

    if fails:
        rep["verdict"] = "FAIL"
        for msg in fails:
            rep["findings"].append({"severity": "ERROR",
                                    "rule": "THERMAL_OVER_LIMIT", "message": msg})
        return "FAIL", rep

    rep["verdict"] = "PASS"
    tj_note = (f", Tj {tj_c:.2f} °C < {tj_max_c:.2f} °C" if tj_c is not None
               else " (no Tj estimate — power-density screen only)")
    rep["findings"].append({
        "severity": "INFO", "rule": "THERMAL_WITHIN_LIMIT",
        "message": (f"power density {power_density:.4f} W/mm² < limit "
                    f"{limit_w_per_mm2:.4f} W/mm²{tj_note}")})
    return "PASS", rep


def _emit(rep: Dict[str, Any], json_out: Optional[str]) -> None:
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(out + "\n")
    print(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("power_report", help="power report (JSON/.rpt) or project dir")
    ap.add_argument("--die-source", default=None,
                    help="DEF (DIEAREA) or floorplan JSON for die area")
    ap.add_argument("--die-area-mm2", type=float, default=None,
                    help="die area in mm² (overrides --die-source)")
    ap.add_argument("--die-area-um2", type=float, default=None,
                    help="die area in µm² (overrides --die-source)")
    ap.add_argument("--limit-w-per-mm2", type=float,
                    default=_DEFAULT_LIMIT_W_PER_MM2,
                    help=f"power-density limit W/mm² (default "
                         f"{_DEFAULT_LIMIT_W_PER_MM2}; package-dependent)")
    ap.add_argument("--tj-max", type=float, default=_DEFAULT_TJ_MAX_C,
                    help=f"junction-temp ceiling °C (default {_DEFAULT_TJ_MAX_C})")
    ap.add_argument("--theta-ja", type=float, default=None,
                    help="package θ_ja (°C/W) for a first-order Tj estimate")
    ap.add_argument("--ambient", type=float, default=None,
                    help="ambient T_a (°C) for a first-order Tj estimate")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if args.limit_w_per_mm2 <= 0:
        print("ERROR: --limit-w-per-mm2 must be positive", file=sys.stderr)
        return 2

    in_path = Path(args.power_report)
    if not in_path.exists():
        print(f"ERROR: power report path not found: {in_path}", file=sys.stderr)
        return 2

    power_path = _discover_power_report(in_path)
    if power_path is None:
        # a directory that exists but holds NO power report — §4.05: the
        # thermal screen has no power to screen → SKIP, never a vacuous pass.
        rep = {
            "program": "thermal_screen_check", "version": _VERSION,
            "power_report": str(in_path), "verdict": "SKIP",
            "skip_reason": "power_report_absent",
            "findings": [{
                "severity": "SKIP", "rule": "POWER_REPORT_ABSENT",
                "message": (f"no power report found under {in_path} — §4.05: "
                            "SKIP, never a vacuous pass")}],
        }
        _emit(rep, args.json)
        return 3

    # Resolve a die source: explicit --die-source, or discover under the dir
    # the power report came from (only when no area override was supplied).
    die_source: Optional[Path] = None
    if args.die_area_mm2 is None and args.die_area_um2 is None:
        if args.die_source is not None:
            ds = Path(args.die_source)
            if not ds.exists():
                print(f"ERROR: --die-source not found at {ds}", file=sys.stderr)
                return 2
            die_source = _discover_die_source(ds)
        elif in_path.is_dir():
            die_source = _discover_die_source(in_path)

    verdict, rep = evaluate(
        power_path, die_source, args.die_area_mm2, args.die_area_um2,
        args.limit_w_per_mm2, args.tj_max, args.theta_ja, args.ambient,
        project=(in_path if in_path.is_dir() else None))
    _emit(rep, args.json)
    return {"PASS": 0, "FAIL": 1, "SKIP": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
