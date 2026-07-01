#!/usr/bin/env python3
"""em_current_density_check.py — REAL electromigration current-density sign-off.

The tapeout-checklist skill's EM row requires a genuine per-segment current
DENSITY vs the foundry's Jmax limit (per metal / via layer), not a proxy.

Today the plugin only *measures* EM current:

  * `phase3_one_shot_runner._emit_ir_em_reports` runs OpenROAD PSM
    `analyze_power_grid -net <VPWR> -enable_em -em_outfile em_segments.csv`
    and writes `reports/phase3/em.json` with `verdict: "MEASURED"` plus a
    per-segment CSV whose columns are:
        Node0 Layer, Node0 X, Node0 Y, Node1 Layer, Node1 X, Node1 Y, Current
    (Current in Amperes). It NEVER compares that current to any Jmax limit.
  * `signoff_ladder_run.check_tier_2_decap` calls its "EM" tier a
    DECAP-CELL-COUNT proxy (`decap_cells >= 100`) — a placement heuristic,
    not a current-density check.

This program closes that gap with the physical sign-off computation:

    current-density  J = current / (width x thickness)          [A/um^2]
    PASS   iff  for EVERY screened segment  J < Jmax * (1 - margin)
    FAIL   iff  any segment reaches/exceeds the margined Jmax (offenders listed)

The per-layer Jmax + geometry (thickness, width) are read from the PDK:

  * a foundry / open-PDK **tech LEF** (sky130 / gf180 both carry, per LAYER:
      THICKNESS <um> ; WIDTH <um> ;
      DCCURRENTDENSITY AVERAGE <v> ;   # mA/um for ROUTING, mA/cut for CUT
    ), OR
  * a supplied **jmax JSON** (see schema below).

Because the foundry Jmax is calibrated to a target lifetime, we also report a
Black's-equation RELATIVE lifetime headroom  (Jmax / J) ** n  (n≈2) per the
current-density term of  MTTF = A * J^-n * exp(Ea / kT).  Absolute MTTF needs
Ea / T / A constants that a LEF does not carry, so only the relative headroom
(honest, un-fabricated) is reported.

Honest §4.05 rules — a missing input is NEVER a fabricated PASS and NEVER the
old decap-count proxy:

  * EM report absent / unreadable / no parseable segments  → SKIPPED (rc 3)
  * Jmax reference (tech LEF or jmax JSON) absent           → SKIPPED (rc 3)
  * report + Jmax present but NO segment maps to a Jmax     → SKIPPED (rc 3)
  * every screened segment under margined Jmax              → PASS   (rc 0)
  * any screened segment at/over margined Jmax              → FAIL   (rc 1)
  * bad CLI argument                                        → error  (rc 2)

SKIPPED is a distinct "cannot judge" verdict — it is never conflated with
PASS, so an rc-based sign-off gate can never read absence as green.

jmax JSON schema (any of the jmax-unit keys per layer)::

    {
      "layers": {
        "met1":  {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                  "jmax_mA_per_um": 2.8},
        "met5":  {"kind": "routing", "thickness_um": 1.26, "width_um": 1.6,
                  "jmax_A_per_um2": 8.0e-3},
        "via1":  {"kind": "cut", "jmax_mA_per_cut": 0.29}
      }
    }

  jmax may be given as  jmax_mA_per_um (per-width, LEF DC form),
  jmax_A_per_um2 (areal) or jmax_A_per_cm2 (areal, / 1e8).

Usage::

    python3 em_current_density_check.py <em_report> \
        [--jmax JMAX.json | --tech-lef TECH.lef] [--margin 0.10] \
        [--blacks-n 2.0] [--net NAME] [--top-offenders 20] [--json OUT]

  <em_report> may be an em_segments.csv, a JSON with a "segments" list, or a
  directory (searched for em_segments.csv / *em*segment*.csv / a segment JSON).

main(argv) -> int : 0 PASS / 1 FAIL / 2 arg-error / 3 SKIPPED-CONDITION.

chip-AGNOSTIC: pure numeric current/geometry compare; no chip literal.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

VERSION = "1.0.0"

# require J < Jmax * (1 - margin); 10% guardband is a common EM sign-off margin.
_DEFAULT_MARGIN = 0.10
# current-density exponent in Black's equation (n≈2 for the J^-n term).
_DEFAULT_BLACKS_N = 2.0


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # reject NaN


# ---------------------------------------------------------------------------
# Jmax table (per-layer geometry + limit) — from tech LEF or supplied JSON.
# Normalised internal entry:
#   routing: {"kind":"routing","thickness_um":t|None,"width_um":w|None,
#             "jmax_areal_A_per_um2":a|None,"jmax_per_width_A_per_um":p|None}
#   cut:     {"kind":"cut","jmax_per_cut_A":c}
# ---------------------------------------------------------------------------
_LAYER_BLOCK_RE = re.compile(
    r"^\s*LAYER\s+(\S+)\s*;?\s*$(.*?)^\s*END\s+\1\b",
    re.MULTILINE | re.DOTALL | re.IGNORECASE)
_TYPE_RE = re.compile(r"^\s*TYPE\s+(\w+)\s*;", re.MULTILINE | re.IGNORECASE)
_THICK_RE = re.compile(r"^\s*THICKNESS\s+([0-9.eE+\-]+)\s*;", re.MULTILINE | re.IGNORECASE)
_WIDTH_RE = re.compile(r"^\s*WIDTH\s+([0-9.eE+\-]+)\s*;", re.MULTILINE | re.IGNORECASE)
_MINWIDTH_RE = re.compile(r"^\s*MINWIDTH\s+([0-9.eE+\-]+)\s*;", re.MULTILINE | re.IGNORECASE)
# DCCURRENTDENSITY AVERAGE <single number> ;  (skip the table/frequency form)
_DCDENS_RE = re.compile(
    r"^\s*DCCURRENTDENSITY\s+AVERAGE\s+([0-9.eE+\-]+)\s*;",
    re.MULTILINE | re.IGNORECASE)


def parse_lef_jmax(text: str) -> Dict[str, Dict[str, Any]]:
    """Build a normalised Jmax table from a tech-LEF string."""
    table: Dict[str, Dict[str, Any]] = {}
    for m in _LAYER_BLOCK_RE.finditer(text):
        name = m.group(1)
        body = m.group(2)
        tm = _TYPE_RE.search(body)
        ltype = (tm.group(1).upper() if tm else "")
        dm = _DCDENS_RE.search(body)
        if not dm:
            continue  # no DC current-density limit → not screenable
        dc = _num(dm.group(1))
        if dc is None:
            continue
        if ltype == "ROUTING":
            th = _THICK_RE.search(body)
            wd = _WIDTH_RE.search(body) or _MINWIDTH_RE.search(body)
            thickness = _num(th.group(1)) if th else None
            width = _num(wd.group(1)) if wd else None
            per_width = dc * 1e-3  # LEF routing DCCURRENTDENSITY is mA/um
            areal = (per_width / thickness) if thickness else None
            table[name.lower()] = {
                "orig_name": name, "kind": "routing",
                "thickness_um": thickness, "width_um": width,
                "jmax_per_width_A_per_um": per_width,
                "jmax_areal_A_per_um2": areal,
            }
        elif ltype == "CUT":
            table[name.lower()] = {
                "orig_name": name, "kind": "cut",
                "jmax_per_cut_A": dc * 1e-3,  # LEF cut DCCURRENTDENSITY is mA/cut
            }
    return table


def parse_json_jmax(data: Any) -> Dict[str, Dict[str, Any]]:
    """Normalise a supplied jmax JSON (see module docstring schema)."""
    table: Dict[str, Dict[str, Any]] = {}
    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, dict):
        return table
    for name, spec in layers.items():
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind", "routing")).lower()
        if kind == "cut":
            per_cut = _num(spec.get("jmax_mA_per_cut"))
            if per_cut is not None:
                per_cut *= 1e-3
            elif _num(spec.get("jmax_A_per_cut")) is not None:
                per_cut = _num(spec.get("jmax_A_per_cut"))
            if per_cut is None:
                continue
            table[str(name).lower()] = {
                "orig_name": name, "kind": "cut", "jmax_per_cut_A": per_cut}
            continue
        thickness = _num(spec.get("thickness_um"))
        width = _num(spec.get("width_um")) or _num(spec.get("min_width_um"))
        per_width = None
        areal = None
        if _num(spec.get("jmax_mA_per_um")) is not None:
            per_width = _num(spec["jmax_mA_per_um"]) * 1e-3
        if _num(spec.get("jmax_A_per_um2")) is not None:
            areal = _num(spec["jmax_A_per_um2"])
        elif _num(spec.get("jmax_A_per_cm2")) is not None:
            areal = _num(spec["jmax_A_per_cm2"]) / 1e8  # 1 cm^2 = 1e8 um^2
        if per_width is None and areal is not None and thickness:
            per_width = areal * thickness
        if areal is None and per_width is not None and thickness:
            areal = per_width / thickness
        if per_width is None and areal is None:
            continue
        table[str(name).lower()] = {
            "orig_name": name, "kind": "routing",
            "thickness_um": thickness, "width_um": width,
            "jmax_per_width_A_per_um": per_width,
            "jmax_areal_A_per_um2": areal,
        }
    return table


def load_jmax_table(jmax_path: Optional[Path], tech_lef: Optional[Path]
                    ) -> Tuple[Dict[str, Dict[str, Any]], Optional[str], Optional[str]]:
    """Return (table, source_str, error). Empty table => no usable reference."""
    src = tech_lef or jmax_path
    if src is None:
        return {}, None, "no --jmax or --tech-lef supplied"
    if not src.is_file():
        return {}, str(src), f"Jmax reference not found: {src}"
    try:
        text = src.read_text(errors="replace")
    except OSError as exc:
        return {}, str(src), f"cannot read Jmax reference: {exc}"
    # decide LEF vs JSON by extension then by content sniff
    is_lef = src.suffix.lower() in (".lef", ".tlef")
    if not is_lef and src.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return {}, str(src), f"unparseable jmax JSON: {exc}"
        return parse_json_jmax(data), str(src), None
    if not is_lef:
        # sniff: LEF-ish if it has LAYER ... CURRENTDENSITY
        if re.search(r"\bLAYER\b", text) and re.search(r"CURRENTDENSITY", text, re.I):
            is_lef = True
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return {}, str(src), "Jmax reference is neither LEF nor JSON"
            return parse_json_jmax(data), str(src), None
    table = parse_lef_jmax(text)
    if not table:
        return {}, str(src), "tech LEF has no DCCURRENTDENSITY reference"
    return table, str(src), None


# ---------------------------------------------------------------------------
# EM report segment iteration.
# ---------------------------------------------------------------------------
def _discover_em_report(path: Path) -> Optional[Path]:
    if path.is_file():
        return path
    if path.is_dir():
        for pat in ("em_segments.csv", "*em*segment*.csv", "*em*.csv",
                    "*em*segment*.json", "em.json"):
            hits = sorted(path.rglob(pat))
            if hits:
                return hits[0]
    return None


def _iter_csv_segments(em_path: Path, net_hint: Optional[str]
                       ) -> Iterator[Dict[str, Any]]:
    with em_path.open(newline="", errors="replace") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return
        cols = [c.strip().lower() for c in header]

        def find(*needles: str) -> Optional[int]:
            for i, c in enumerate(cols):
                if all(n in c for n in needles):
                    return i
            return None

        i_l0 = find("node0", "layer")
        i_l1 = find("node1", "layer")
        if i_l0 is None:
            i_l0 = find("layer")
        if i_l1 is None:
            i_l1 = i_l0
        i_cur = find("current")
        i_w = find("width")
        i_net = find("net")
        if i_l0 is None or i_cur is None:
            return  # not a per-segment EM CSV
        for row in reader:
            if not row or len(row) <= max(i_l0, i_cur):
                continue
            cur = _num(row[i_cur])
            if cur is None:
                continue
            layer0 = row[i_l0].strip()
            layer1 = row[i_l1].strip() if (i_l1 is not None and len(row) > i_l1) else layer0
            width = _num(row[i_w]) if (i_w is not None and len(row) > i_w) else None
            net = (row[i_net].strip() if (i_net is not None and len(row) > i_net)
                   else (net_hint or "unknown"))
            yield {"net": net, "layer0": layer0, "layer1": layer1,
                   "current_A": abs(cur), "width_um": width}


def _iter_json_segments(data: Any, net_hint: Optional[str]
                        ) -> Iterator[Dict[str, Any]]:
    segs = data.get("segments") if isinstance(data, dict) else (
        data if isinstance(data, list) else None)
    if not isinstance(segs, list):
        return
    for s in segs:
        if not isinstance(s, dict):
            continue
        cur = _num(s.get("current_A", s.get("current")))
        if cur is None:
            continue
        layer0 = str(s.get("layer0", s.get("layer", ""))).strip()
        layer1 = str(s.get("layer1", s.get("layer0", s.get("layer", "")))).strip()
        yield {"net": str(s.get("net", net_hint or "unknown")),
               "layer0": layer0, "layer1": layer1,
               "current_A": abs(cur),
               "width_um": _num(s.get("width_um", s.get("width")))}


def iter_segments(em_path: Path, net_hint: Optional[str]
                  ) -> Tuple[Optional[Iterable[Dict[str, Any]]], Optional[str]]:
    """Return (iterable-of-segments, error). error set => cannot read."""
    if em_path.suffix.lower() == ".json":
        try:
            data = json.loads(em_path.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"cannot read EM JSON: {exc}"
        # a bare em.json summary (no segments) is not per-segment data
        if isinstance(data, dict) and "segments" not in data:
            # try a sibling em_segments.csv next to the summary
            sib = em_path.parent / "em_segments.csv"
            if sib.is_file():
                hint = net_hint
                if net_hint is None:
                    nets = data.get("power_nets")
                    if isinstance(nets, list) and len(nets) == 1:
                        hint = str(nets[0])
                return _iter_csv_segments(sib, hint), None
            return [], None  # empty → caller emits SKIPPED (no per-segment data)
        return list(_iter_json_segments(data, net_hint)), None
    try:
        return list(_iter_csv_segments(em_path, net_hint)), None
    except OSError as exc:
        return None, f"cannot read EM CSV: {exc}"


# ---------------------------------------------------------------------------
# Screening.
# ---------------------------------------------------------------------------
def _screen_segment(seg: Dict[str, Any], table: Dict[str, Dict[str, Any]],
                    margin: float, blacks_n: float) -> Dict[str, Any]:
    """Screen one segment → dict with status in
    {ok, offender, unscreened}. Numeric detail included when screened."""
    l0 = seg["layer0"].lower()
    l1 = seg["layer1"].lower()
    cur = seg["current_A"]
    net = seg["net"]

    # via / cut segment: metal ends on different layers.
    if l0 != l1:
        cut = table.get(l0) if table.get(l0, {}).get("kind") == "cut" else None
        cut = cut or (table.get(l1) if table.get(l1, {}).get("kind") == "cut" else None)
        if cut is None:
            return {"status": "unscreened", "net": net,
                    "layer": f"{seg['layer0']}->{seg['layer1']}",
                    "reason": "via_cut_layer_not_in_jmax_reference",
                    "current_A": cur}
        limit = cut["jmax_per_cut_A"]
        util = cur / limit if limit > 0 else math.inf
        offender = util >= (1.0 - margin)
        return {"status": "offender" if offender else "ok", "net": net,
                "layer": cut["orig_name"], "basis": "per_cut",
                "current_A": cur, "value_A_per_cut": cur,
                "limit_A_per_cut": limit, "utilization": util,
                "lifetime_ratio": _lifetime_ratio(util, blacks_n)}

    entry = table.get(l0)
    if entry is None:
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "layer_not_in_jmax_reference", "current_A": cur}
    if entry.get("kind") != "routing":
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "layer_is_not_routing", "current_A": cur}
    width = seg.get("width_um") or entry.get("width_um")
    if not width:
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "no_segment_or_layer_width", "current_A": cur}

    thickness = entry.get("thickness_um")
    dens_per_width = cur / width  # A/um
    dens_areal = (cur / (width * thickness)) if thickness else None  # A/um^2

    # Compare in areal space when possible (the task's I/(w*t) formula),
    # else fall back to per-width space. Both give the identical verdict when
    # the LEF limit is per-width (thickness cancels), so this is exact.
    if entry.get("jmax_areal_A_per_um2") is not None and dens_areal is not None:
        basis = "areal"
        value = dens_areal
        limit = entry["jmax_areal_A_per_um2"]
    elif entry.get("jmax_per_width_A_per_um") is not None:
        basis = "per_width"
        value = dens_per_width
        limit = entry["jmax_per_width_A_per_um"]
    else:
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "no_usable_jmax_for_layer", "current_A": cur}

    util = value / limit if limit > 0 else math.inf
    offender = util >= (1.0 - margin)
    return {
        "status": "offender" if offender else "ok",
        "net": net, "layer": entry["orig_name"], "basis": basis,
        "current_A": cur, "width_um": width, "thickness_um": thickness,
        "density_A_per_um2": dens_areal,
        "density_A_per_um": dens_per_width,
        "value": value, "limit": limit, "utilization": util,
        "lifetime_ratio": _lifetime_ratio(util, blacks_n),
    }


def _lifetime_ratio(util: float, n: float) -> Optional[float]:
    """Black's-equation RELATIVE lifetime headroom vs the Jmax reference:
    MTTF ∝ J^-n  ⇒  (Jmax/J)^n = (1/util)^n. util=0 → unbounded (None)."""
    if util <= 0:
        return None
    try:
        return (1.0 / util) ** n
    except OverflowError:
        return None


def evaluate(em_path: Optional[Path], jmax_path: Optional[Path],
             tech_lef: Optional[Path], margin: float, blacks_n: float,
             net_hint: Optional[str], top_offenders: int
             ) -> Tuple[str, Dict[str, Any]]:
    """Return (verdict, report). verdict in {PASS, FAIL, SKIPPED}."""
    rep: Dict[str, Any] = {
        "program": "em_current_density_check", "version": VERSION,
        "margin": margin, "blacks_n": blacks_n, "findings": [],
    }

    # (1) EM report present?
    if em_path is None:
        rep["verdict"] = "SKIPPED"
        rep["pass"] = False
        rep["skip_reason"] = "em_report_absent"
        rep["findings"].append({"severity": "SKIPPED", "rule": "EM_REPORT_ABSENT",
                                "message": "no EM per-segment report found "
                                "(§4.05: absence is not PASS)"})
        return "SKIPPED", rep
    rep["em_report"] = str(em_path)

    # (2) Jmax reference present?
    table, jmax_src, jerr = load_jmax_table(jmax_path, tech_lef)
    rep["jmax_source"] = jmax_src
    if not table:
        rep["verdict"] = "SKIPPED"
        rep["pass"] = False
        rep["skip_reason"] = "jmax_reference_absent"
        rep["findings"].append({
            "severity": "SKIPPED", "rule": "JMAX_REFERENCE_ABSENT",
            "message": f"no Jmax reference ({jerr or 'no usable per-layer limit'}); "
                       "§4.05: cannot fabricate PASS and will not use the "
                       "decap-count proxy"})
        return "SKIPPED", rep

    # (3) parse segments
    segs, serr = iter_segments(em_path, net_hint)
    if serr is not None:
        rep["verdict"] = "SKIPPED"
        rep["pass"] = False
        rep["skip_reason"] = "em_report_unreadable"
        rep["findings"].append({"severity": "SKIPPED", "rule": "EM_REPORT_UNREADABLE",
                                "message": serr})
        return "SKIPPED", rep

    n_total = n_screened = n_unscreened = 0
    offenders: List[Dict[str, Any]] = []
    worst_util = -1.0
    min_life: Optional[float] = None
    per_layer: Dict[str, Dict[str, Any]] = {}
    unscreened_reasons: Dict[str, int] = {}

    for seg in segs:
        n_total += 1
        r = _screen_segment(seg, table, margin, blacks_n)
        if r["status"] == "unscreened":
            n_unscreened += 1
            unscreened_reasons[r["reason"]] = unscreened_reasons.get(r["reason"], 0) + 1
            continue
        n_screened += 1
        lyr = r["layer"]
        pl = per_layer.setdefault(lyr, {"segments": 0, "max_utilization": 0.0})
        pl["segments"] += 1
        pl["max_utilization"] = max(pl["max_utilization"], r["utilization"])
        if r["utilization"] > worst_util:
            worst_util = r["utilization"]
        lr = r.get("lifetime_ratio")
        if lr is not None and (min_life is None or lr < min_life):
            min_life = lr
        if r["status"] == "offender":
            offenders.append(r)

    rep["summary"] = {
        "segments_total": n_total,
        "segments_screened": n_screened,
        "segments_unscreened": n_unscreened,
        "unscreened_reasons": unscreened_reasons,
        "worst_utilization": (round(worst_util, 6) if worst_util >= 0 else None),
        "worst_case_lifetime_ratio": (round(min_life, 4) if min_life is not None else None),
        "per_layer": {k: {"segments": v["segments"],
                          "max_utilization": round(v["max_utilization"], 6)}
                      for k, v in sorted(per_layer.items())},
        "jmax_layers": sorted(e["orig_name"] for e in table.values()),
    }

    # (3b) report present + Jmax present but nothing mapped → SKIPPED, never PASS
    if n_screened == 0:
        rep["verdict"] = "SKIPPED"
        rep["pass"] = False
        rep["skip_reason"] = ("no_segments" if n_total == 0
                              else "no_segment_maps_to_jmax_reference")
        rep["findings"].append({
            "severity": "SKIPPED", "rule": "NOTHING_SCREENED",
            "message": (f"{n_total} segment(s) read but none could be screened "
                        f"against the Jmax reference ({dict(unscreened_reasons)}); "
                        "§4.05: not a PASS")})
        return "SKIPPED", rep

    # (4) verdict
    offenders.sort(key=lambda o: o["utilization"], reverse=True)
    if offenders:
        rep["verdict"] = "FAIL"
        rep["pass"] = False
        rep["offenders"] = offenders[:max(1, top_offenders)]
        rep["offender_count"] = len(offenders)
        for o in offenders[:max(1, top_offenders)]:
            if o.get("basis") == "per_cut":
                msg = (f"net={o['net']} via-layer={o['layer']} "
                       f"current={o['current_A']:.3e} A >= "
                       f"{(1 - margin) * o['limit_A_per_cut']:.3e} A "
                       f"(Jmax/cut={o['limit_A_per_cut']:.3e} A, "
                       f"margin={margin})")
            else:
                dens = o.get("density_A_per_um2")
                dens_s = (f"{dens:.4e} A/um^2" if dens is not None
                          else f"{o['value']:.4e} A/um")
                msg = (f"net={o['net']} layer={o['layer']} "
                       f"J={dens_s} >= {(1 - margin) * o['limit']:.4e} "
                       f"({'A/um^2' if o.get('basis') == 'areal' else 'A/um'}) "
                       f"(Jmax={o['limit']:.4e}, util={o['utilization']:.3f}, "
                       f"margin={margin})")
            rep["findings"].append({"severity": "ERROR",
                                    "rule": "EM_CURRENT_DENSITY_OVER_JMAX",
                                    "message": msg})
        return "FAIL", rep

    rep["verdict"] = "PASS"
    rep["pass"] = True
    rep["findings"].append({
        "severity": "INFO", "rule": "EM_CURRENT_DENSITY_UNDER_JMAX",
        "message": (f"all {n_screened} screened segment(s) below Jmax with "
                    f"margin {margin}; worst utilization {worst_util:.4f} "
                    f"(worst-case Black's lifetime headroom "
                    f"{min_life:.2f}x)" if min_life is not None else
                    f"all {n_screened} screened segment(s) below Jmax")})
    return "PASS", rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("em_report",
                    help="em_segments.csv / segment JSON / project-or-report dir")
    ap.add_argument("--jmax", default=None,
                    help="per-layer Jmax JSON (or a tech LEF)")
    ap.add_argument("--tech-lef", default=None,
                    help="PDK tech LEF carrying DCCURRENTDENSITY / THICKNESS")
    ap.add_argument("--margin", type=float, default=_DEFAULT_MARGIN,
                    help=f"guardband fraction, PASS iff J < Jmax*(1-margin) "
                         f"(default {_DEFAULT_MARGIN})")
    ap.add_argument("--blacks-n", type=float, default=_DEFAULT_BLACKS_N,
                    help=f"Black's-equation current-density exponent "
                         f"(default {_DEFAULT_BLACKS_N})")
    ap.add_argument("--net", default=None,
                    help="net name hint when the CSV has no net column")
    ap.add_argument("--top-offenders", type=int, default=20,
                    help="max offenders to list on FAIL (default 20)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not (0.0 <= args.margin < 1.0):
        print("ERROR: --margin must be in [0, 1)", file=sys.stderr)
        return 2
    if args.blacks_n <= 0:
        print("ERROR: --blacks-n must be positive", file=sys.stderr)
        return 2

    em_path = _discover_em_report(Path(args.em_report))
    jmax_path = Path(args.jmax) if args.jmax else None
    tech_lef = Path(args.tech_lef) if args.tech_lef else None

    verdict, rep = evaluate(em_path, jmax_path, tech_lef, args.margin,
                            args.blacks_n, args.net, args.top_offenders)
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return {"PASS": 0, "FAIL": 1, "SKIPPED": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
