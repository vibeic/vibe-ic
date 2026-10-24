#!/usr/bin/env python3
"""em_current_density_check.py — REAL electromigration current-density sign-off.

The tapeout-checklist skill's EM row requires a genuine per-segment current
DENSITY vs the foundry's Jmax limit (per metal / via layer), not a proxy.

The plugin measures EM current and executes the native density arm:

  * `phase3_one_shot_runner._emit_ir_em_reports` runs OpenROAD PSM
    `analyze_power_grid -net <VPWR> -enable_em -em_outfile em_segments.csv`
    and writes `reports/phase3/em.json` with `verdict: "MEASURED"` plus a
    per-segment CSV whose columns are:
        Node0 Layer, Node0 X, Node0 Y, Node1 Layer, Node1 X, Node1 Y, Current
    (Current in Amperes). The same Default session runs check_current_density
    on declared routing/cut limits; this gate binds it before its retained screen.
  * `signoff_ladder_run.check_tier_2_decap` calls its "EM" tier a
    DECAP-CELL-COUNT proxy (`decap_cells >= 100`) — a placement heuristic,
    not a current-density check.

This program closes that gap with the physical sign-off computation:

    current-density  J = current / (width x thickness)          [A/um^2]
    PASS   iff  for EVERY screened segment  J < Jmax * (1 - margin)
    FAIL   iff  any segment reaches/exceeds the margined Jmax (offenders listed)

The per-layer Jmax and thickness are read from the PDK.  Conductor width is
proved per segment by same-net routed DEF special wires or placed LEF PG PORT
rectangles emitted from OpenROAD ODB.  LEF default layer WIDTH and
the narrowest width elsewhere on the layer are never segment geometry.

  * a foundry / open-PDK **tech LEF** (sky130 / gf180 both carry, per LAYER:
      THICKNESS <um> ; WIDTH <um> ;
      DCCURRENTDENSITY AVERAGE <v> ;   # mA/um for ROUTING, mA/um^2 for CUT
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
  * conductor width unproved for any segment                 → NOT_MEASURED (rc 3)
  * every segment measured and under margined Jmax           → PASS   (rc 0)
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

main(argv) -> int : 0 PASS / 1 FAIL / 2 arg-error / 3 unmeasured/skipped.

chip-AGNOSTIC: pure numeric current/geometry compare; no chip literal.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import csv
import heapq
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

#: OpenROAD Tcl that dumps the loaded ODB's supply-net routing-layer boxes
#: (special wires, via metal, and placed standard-cell/macro/pad LEF PG PORT
#: rectangles) as TSV
#: `_odb_pg_geometry_rects` reads. DEF SPECIALNETS omit the layer metal inside
#: generated via arrays, yet PSM reports current between nodes on those via
#: enclosures; this gives those edges a real cross section. One instrument for
#: every session that feeds this gate: the Step-25 producer and the pre-route
#: PDN sweep (`_ppa/pdn_em_presweep`). `__GEOMETRY_PATH__` is the output path.
PG_GEOMETRY_TCL = r'''
set _eg_f [open __GEOMETRY_PATH__ w]
puts $_eg_f "net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource"
set _eg_dbu [[ord::get_db_tech] getDbUnitsPerMicron]
foreach _eg_n [[ord::get_db_block] getNets] {
  if {[$_eg_n getSigType] ni {POWER GROUND}} {continue}
  foreach _eg_sw [$_eg_n getSWires] {
    foreach _eg_s [$_eg_sw getWires] {
      if {[$_eg_s isVia]} {
        lassign [$_eg_s getViaXY] _eg_vx _eg_vy
        set _eg_v [$_eg_s getTechVia]
        if {$_eg_v eq "NULL"} {set _eg_v [$_eg_s getBlockVia]}
        if {$_eg_v eq "NULL"} {continue}
        foreach _eg_b [$_eg_v getBoxes] {
          set _eg_l [$_eg_b getTechLayer]
          if {$_eg_l eq "NULL" || [$_eg_l getRoutingLevel] <= 0} {continue}
          puts $_eg_f [join [list [$_eg_n getName] [$_eg_l getName] \
            [expr {double($_eg_vx+[$_eg_b xMin])/$_eg_dbu}] \
            [expr {double($_eg_vy+[$_eg_b yMin])/$_eg_dbu}] \
            [expr {double($_eg_vx+[$_eg_b xMax])/$_eg_dbu}] \
            [expr {double($_eg_vy+[$_eg_b yMax])/$_eg_dbu}] via_metal] "\t"]
        }
      } else {
        set _eg_l [$_eg_s getTechLayer]
        if {$_eg_l eq "NULL" || [$_eg_l getRoutingLevel] <= 0} {continue}
        puts $_eg_f [join [list [$_eg_n getName] [$_eg_l getName] \
          [expr {double([$_eg_s xMin])/$_eg_dbu}] \
          [expr {double([$_eg_s yMin])/$_eg_dbu}] \
          [expr {double([$_eg_s xMax])/$_eg_dbu}] \
          [expr {double([$_eg_s yMax])/$_eg_dbu}] special_wire] "\t"]
      }
    }
  }
  # dbITerm geometries are LEF PG PORT rectangles transformed by the placed
  # instance.  Adjacent IO cells abut, so their port rectangles can form one
  # continuous rail even when no DEF SPECIALNET wire describes that rail.
  foreach _eg_t [$_eg_n getITerms] {
    if {[[$_eg_t getMTerm] getSigType] ni {POWER GROUND}} {continue}
    set _eg_m [[$_eg_t getInst] getMaster]
    if {[$_eg_m isPad]} {
      set _eg_src pg_port
    } elseif {[$_eg_m isBlock]} {
      set _eg_src macro_pg_port
    } elseif {[$_eg_m isCore]} {
      set _eg_src stdcell_pg_port
    } else {
      set _eg_src other_pg_port
    }
    if {[catch {set _eg_gs [$_eg_t getGeometries]}]} {continue}
    foreach _eg_g $_eg_gs {
      if {[catch {lassign $_eg_g _eg_l _eg_b}]} {continue}
      if {$_eg_l eq "NULL" || [$_eg_l getRoutingLevel] <= 0} {continue}
      puts $_eg_f [join [list [$_eg_n getName] [$_eg_l getName] \
        [expr {double([$_eg_b xMin])/$_eg_dbu}] \
        [expr {double([$_eg_b yMin])/$_eg_dbu}] \
        [expr {double([$_eg_b xMax])/$_eg_dbu}] \
        [expr {double([$_eg_b yMax])/$_eg_dbu}] $_eg_src] "\t"]
    }
  }
}
close $_eg_f
'''


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
#   cut:     LEF areal A/um^2, or explicitly supplied JSON A/cut
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
_VIA_BLOCK_RE = re.compile(
    r"^\s*(?:VIA|VIARULE)\s+(\S+)[^\n]*\n(.*?)^\s*END\s+\1\b",
    re.MULTILINE | re.DOTALL | re.IGNORECASE)
_VIA_LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;", re.MULTILINE | re.IGNORECASE)


def parse_lef_jmax(text: str) -> Dict[str, Dict[str, Any]]:
    """Build a normalised Jmax table from a tech-LEF string."""
    table: Dict[str, Dict[str, Any]] = {}
    layer_types: Dict[str, str] = {}
    for m in _LAYER_BLOCK_RE.finditer(text):
        name = m.group(1)
        body = m.group(2)
        tm = _TYPE_RE.search(body)
        ltype = (tm.group(1).upper() if tm else "")
        layer_types[name.lower()] = ltype
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
                # LEF CUT scalar is mA/um^2, unlike explicit JSON mA/cut.
                "jmax_areal_A_per_um2": dc * 1e-3,
            }
    # PSM names the routing layers at both ends of a via edge. Only an
    # explicit VIA in this same authority can identify its cut layer; layer
    # names or their numeric suffixes are not a connectivity declaration.
    connections: Dict[Tuple[str, str], set] = {}
    for via in _VIA_BLOCK_RE.finditer(text):
        layers = {name.lower() for name in _VIA_LAYER_RE.findall(via.group(2))}
        routing = sorted(name for name in layers if layer_types.get(name) == "ROUTING")
        cuts = {name for name in layers if layer_types.get(name) == "CUT"}
        if len(routing) == 2 and len(cuts) == 1 and len(layers) == 3:
            connections.setdefault(tuple(routing), set()).update(cuts)
    for pair, cuts in connections.items():
        # A second possible cut (including one without a limit) is ambiguous.
        if len(cuts) == 1:
            cut = table.get(next(iter(cuts)))
            if cut is not None and cut["kind"] == "cut":
                cut.setdefault("routing_pairs", []).append(pair)
    return table


def _segment_geometry_key(net, layer0, layer1, points, current):
    return (str(net).lower(), str(layer0).lower(), str(layer1).lower(),
            tuple(tuple(float(value) for value in point) for point in points),
            abs(float(current)))


def _native_density_roundtrip_matches(current: float, area: float, density: float,
                                     *, exact_divisor: bool = False) -> bool:
    """Check the native I/divisor=J codec; an integer cut count is exact.

    These rounding intervals only validate serialized observations. They do
    not modify a current, area, Jmax, margin, or the sign-off comparison.
    """
    if not all(math.isfinite(v) for v in (current, area, density)) or area <= 0:
        return False

    def interval(value, digits):
        half_ulp = (0.5 * 10 ** (math.floor(math.log10(abs(value))) - digits)
                    if value else 0.0)
        return max(0.0, value - half_ulp), value + half_ulp

    i_lo, i_hi = interval(abs(current), 3)
    a_lo, a_hi = (area, area) if exact_divisor else interval(area, 4)
    j_lo, j_hi = interval(density, 3)
    return a_lo > 0 and max(i_lo / a_hi, j_lo) <= min(i_hi / a_lo, j_hi)


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
        i_x0, i_y0 = find("node0", "x location"), find("node0", "y location")
        i_x1, i_y1 = find("node1", "x location"), find("node1", "y location")
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
                   "current_A": abs(cur), "width_um": width,
                   "points_um": (
                       ((_num(row[i_x0]), _num(row[i_y0])),
                        (_num(row[i_x1]), _num(row[i_y1])))
                       if all(i is not None and len(row) > i
                              for i in (i_x0, i_y0, i_x1, i_y1)) else None)}


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
# Routed-DEF PG geometry and the legacy width inventory (#1215-PDN).
# ---------------------------------------------------------------------------
# The layer-wide minimum parser remains for PDN planning and diagnostic
# inventory.  It never supplies a width to the per-segment Jmax verdict:
# another wire on the same layer cannot prove this segment's cross section.
_DEF_DBU_RE = re.compile(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)")
_DEF_SNET_SECTION_RE = re.compile(r"SPECIALNETS\b(.*?)END\s+SPECIALNETS",
                                  re.DOTALL)
_DEF_SNET_WIRE_RE = re.compile(r"(?:^|[+\s])(?:ROUTED|NEW)\s+(\S+)\s+(\d+)\b")
_DEF_LOCAL_WIRE_RE = re.compile(
    r"(?:ROUTED|NEW)\s+(\S+)\s+(\d+)\s+\+\s+SHAPE\s+"
    r"(?:STRIPE|RING|FOLLOWPIN)\s+"
    r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)")


def _def_pg_local_rects(def_path: Path) -> Dict[Tuple[str, str], List[Tuple[float, ...]]]:
    """Same-net DEF wire rectangles. Unparsed geometry remains unmeasured."""
    try:
        txt = def_path.read_text(errors="replace")
    except OSError:
        return {}
    dbm = _DEF_DBU_RE.search(txt)
    sm = _DEF_SNET_SECTION_RE.search(txt)
    if not dbm or not sm or int(dbm.group(1)) <= 0:
        return {}
    dbu = int(dbm.group(1))
    out: Dict[Tuple[str, str], List[Tuple[float, ...]]] = {}
    for statement in sm.group(1).split(";"):
        nm = re.match(r"\s*-\s+(\S+)", statement)
        if not nm:
            continue
        net = nm.group(1).lower()
        for m in _DEF_LOCAL_WIRE_RE.finditer(statement):
            layer, raw_w, *raw_xy = m.groups()
            width = int(raw_w) / dbu
            if width <= 0:
                continue
            x0, y0, x1, y1 = (int(v) / dbu for v in raw_xy)
            # DEF routes are Manhattan. A diagonal or unsupported path cannot
            # establish a cross section, so leave its conservative bound.
            if x0 != x1 and y0 != y1:
                continue
            half = width / 2
            out.setdefault((net, layer.lower()), []).append(
                (min(x0, x1) - half, min(y0, y1) - half,
                 max(x0, x1) + half, max(y0, y1) + half, width,
                 "def_special_wire"))
    return out


def _odb_pg_geometry_rects(path: Path
                           ) -> Dict[Tuple[str, str], List[Tuple[float, ...]]]:
    """Width-bearing special wires and via-metal boxes emitted from OpenROAD ODB.

    The caller authenticates the file against the exact DEF PSM measured.
    A malformed row proves no width; it never creates a PASS default.
    """
    out: Dict[Tuple[str, str], List[Tuple[float, ...]]] = {}
    try:
        with path.open(newline="", errors="replace") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                try:
                    net = str(row["net"]).lower()
                    layer = str(row["layer"]).lower()
                    x0, y0, x1, y1 = (float(row[k]) for k in
                                      ("x0_um", "y0_um", "x1_um", "y1_um"))
                    if not (math.isfinite(x0) and math.isfinite(y0) and
                            math.isfinite(x1) and math.isfinite(y1) and
                            x1 > x0 and y1 > y0):
                        continue
                    source = str(row["source"])
                    # OBS marks routing exclusion, not net ownership.  A
                    # macro OBS alone cannot prove a current path or width.
                    if source not in {"special_wire", "via_metal", "pg_port",
                                      "macro_pg_port", "stdcell_pg_port",
                                      "other_pg_port"}:
                        continue
                    out.setdefault((net, layer), []).append(
                        (x0, y0, x1, y1, min(x1 - x0, y1 - y0), source))
                except (KeyError, ValueError, TypeError):
                    continue
    except OSError:
        return {}
    return out


_GEOMETRY_TILE_UM = 20.0  # spatial index only; never an EM or width limit


def _geometry_index(rects: Dict[Tuple[str, str], List[Tuple[float, ...]]]
                    ) -> Dict[Tuple[str, str, int, int], List[Tuple[float, ...]]]:
    """Index real conductor boxes in 2-D, including dense standard-cell pins."""
    out: Dict[Tuple[str, str, int, int], List[Tuple[float, ...]]] = {}
    for (net, layer), boxes in rects.items():
        for box in boxes:
            for xtile in range(math.floor(box[0] / _GEOMETRY_TILE_UM),
                               math.floor(box[2] / _GEOMETRY_TILE_UM) + 1):
                for ytile in range(math.floor(box[1] / _GEOMETRY_TILE_UM),
                                   math.floor(box[3] / _GEOMETRY_TILE_UM) + 1):
                    out.setdefault((net, layer, xtile, ytile), []).append(box)
    return out


def _point_metal_boxes(
        key: Tuple[str, str], point: Tuple[float, float],
        index: Dict[Tuple[str, str, int, int], List[Tuple[float, ...]]]
        ) -> List[Tuple[float, ...]]:
    """Find net-owned metal containing a PSM node, including tile boundaries."""
    x, y = point
    xtile = math.floor(x / _GEOMETRY_TILE_UM)
    ytile = math.floor(y / _GEOMETRY_TILE_UM)
    found: Dict[int, Tuple[float, ...]] = {}
    for tx in (xtile - 1, xtile):
        for ty in (ytile - 1, ytile):
            for box in index.get((*key, tx, ty), []):
                if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                    found[id(box)] = box
    return list(found.values())


def _metal_contact_width(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    """Shared edge/area width, capped by each real conductor's minor width."""
    x_overlap = min(a[2], b[2]) - max(a[0], b[0])
    y_overlap = min(a[3], b[3]) - max(a[1], b[1])
    if x_overlap > 0 and y_overlap >= 0:
        span = min(x_overlap, y_overlap) if y_overlap > 0 else x_overlap
    elif y_overlap > 0 and x_overlap == 0:
        span = y_overlap
    else:
        return 0.0  # gap or point contact cannot carry a proven width
    return min(span, a[4], b[4])


def _contact_result(
        contacts: List[Tuple[float, List[str]]]
        ) -> Tuple[Optional[Tuple[float, List[str]]], bool]:
    if not contacts:
        return None, False
    widths = [width for width, _ in contacts]
    if max(widths) - min(widths) > 1e-6:
        return None, True
    return (min(widths), sorted({source for _, names in contacts
                                 for source in names})), False


def _direct_metal_contact(
        first: List[Tuple[float, ...]], second: List[Tuple[float, ...]]
        ) -> Tuple[Optional[Tuple[float, List[str]]], bool]:
    """Prove contact between endpoint conductors; reject width ambiguity."""
    contacts: List[Tuple[float, str, str]] = []
    for a in first:
        for b in second:
            if a is b:
                continue
            width = _metal_contact_width(a, b)
            if width > 0:
                contacts.append((width, a[5], b[5]))
    return _contact_result([(width, [sa, sb]) for width, sa, sb in contacts])


def _bridged_metal_contact(
        key: Tuple[str, str], first: List[Tuple[float, ...]],
        second: List[Tuple[float, ...]],
        points: Tuple[Tuple[float, float], Tuple[float, float]],
        index: Dict[Tuple[str, str, int, int], List[Tuple[float, ...]]],
        bridge_count: int = 1
        ) -> Tuple[Optional[Tuple[float, List[str]]], bool]:
    """Prove a short, unambiguous same-net contact chain between PSM nodes.

    Search only rectangles intersecting the nodes' bounding tiles.  One or
    two intermediate rectangles cover a follow-pin rail or abutting IO cells.
    Longer paths have no bounded width proof here and remain NOT_MEASURED.
    """
    (x0, y0), (x1, y1) = points
    bridges: Dict[int, Tuple[float, ...]] = {}
    for xtile in range(math.floor(min(x0, x1) / _GEOMETRY_TILE_UM),
                       math.floor(max(x0, x1) / _GEOMETRY_TILE_UM) + 1):
        for ytile in range(math.floor(min(y0, y1) / _GEOMETRY_TILE_UM),
                           math.floor(max(y0, y1) / _GEOMETRY_TILE_UM) + 1):
            for box in index.get((*key, xtile, ytile), []):
                bridges[id(box)] = box
    contacts: List[Tuple[float, List[str]]] = []
    endpoint_ids = {id(box) for box in first + second}
    for bridge in bridges.values():
        if id(bridge) in endpoint_ids:
            continue
        for a in first:
            width_a = _metal_contact_width(a, bridge)
            if width_a <= 0:
                continue
            if bridge_count == 1:
                for b in second:
                    width_b = _metal_contact_width(bridge, b)
                    if width_b > 0:
                        contacts.append((min(width_a, bridge[4], width_b),
                                         [a[5], bridge[5], b[5]]))
            elif bridge_count == 2:
                for next_bridge in bridges.values():
                    if (next_bridge is bridge or
                            id(next_bridge) in endpoint_ids):
                        continue
                    width_mid = _metal_contact_width(bridge, next_bridge)
                    if width_mid <= 0:
                        continue
                    for b in second:
                        width_b = _metal_contact_width(next_bridge, b)
                        if width_b > 0:
                            contacts.append((min(width_a, bridge[4],
                                                 width_mid, next_bridge[4],
                                                 width_b),
                                             [a[5], bridge[5],
                                              next_bridge[5], b[5]]))
    return _contact_result(contacts)


def _segment_geometry_width(
        seg: Dict[str, Any], index: Dict[Tuple[str, str, int, int], List[Tuple[float, ...]]]
        ) -> Optional[Tuple[float, List[str]]]:
    """Prove a same-net conductor width for one PSM metal edge.

    Same-net same-layer rectangles may abut at a placed macro boundary.  For
    every axial slab, find the metal component containing the edge centreline;
    adjacent slabs must overlap with positive transverse area.  The minimum
    component width is the actual bottleneck, including a narrow strap even
    when it touches a broad ring.  Diagonal PSM edges use a containing metal
    box or an unambiguous short contact chain because they are virtual edges.
    An uncovered slab or ambiguous contact proves no width.
    """
    pts = seg.get("points_um")
    if not pts or any(v is None for point in pts for v in point):
        return None
    (x0, y0), (x1, y1) = pts
    horizontal = y0 == y1 and x0 != x1
    vertical = x0 == x1 and y0 != y1
    if x0 == x1 and y0 == y1:
        return None
    key = (str(seg["net"]).lower(), str(seg["layer0"]).lower())
    xtiles = range(math.floor(min(x0, x1) / _GEOMETRY_TILE_UM),
                   math.floor(max(x0, x1) / _GEOMETRY_TILE_UM) + 1)
    ytiles = range(math.floor(min(y0, y1) / _GEOMETRY_TILE_UM),
                   math.floor(max(y0, y1) / _GEOMETRY_TILE_UM) + 1)
    if not (horizontal or vertical):
        # A diagonal PSM edge is virtual.  Its geometric line is not an
        # observed route; do not infer a width from a grazing line across
        # multiple boxes.  One box containing both nodes is a direct proof.
        length = math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length

        def chord(x: float, y: float, box: Tuple[float, ...]) -> float:
            limits = []
            for pos, direction, lo, hi in (
                    (x, nx, box[0], box[2]), (y, ny, box[1], box[3])):
                if abs(direction) < 1e-12:
                    if not lo <= pos <= hi:
                        return 0.0
                else:
                    a0, b0 = (lo - pos) / direction, (hi - pos) / direction
                    limits.append((min(a0, b0), max(a0, b0)))
            return max(0.0, min(v[1] for v in limits) -
                       max(v[0] for v in limits)) if limits else 0.0

        first = _point_metal_boxes(key, (x0, y0), index)
        second = _point_metal_boxes(key, (x1, y1), index)
        covering = [box for box in first if any(box is other for other in second)]
        if covering:
            widths = [min(box[4], chord(x0, y0, box), chord(x1, y1, box))
                      for box in covering]
            usable = [(width, box[5]) for width, box in zip(widths, covering)
                      if width > 0]
            if usable:
                width, source = max(usable)
                return width, [source]
        contact, ambiguous = _direct_metal_contact(first, second)
        if contact or ambiguous:
            return contact
        bridged, ambiguous = _bridged_metal_contact(
            key, first, second, ((x0, y0), (x1, y1)), index)
        if bridged or ambiguous:
            return bridged
        twice, _ = _bridged_metal_contact(
            key, first, second, ((x0, y0), (x1, y1)), index, 2)
        return twice
    a, b = sorted((x0, x1) if horizontal else (y0, y1))
    trans = y0 if horizontal else x0
    boxes = []
    seen: set[int] = set()
    for xtile in xtiles:
        for ytile in ytiles:
            for box in index.get((*key, xtile, ytile), []):
                if id(box) in seen:
                    continue
                seen.add(id(box))
                axial_lo, axial_hi = ((box[0], box[2]) if horizontal
                                      else (box[1], box[3]))
                trans_lo, trans_hi = ((box[1], box[3]) if horizontal
                                      else (box[0], box[2]))
                if axial_hi > a and axial_lo < b and trans_lo <= trans <= trans_hi:
                    boxes.append((max(a, axial_lo), min(b, axial_hi),
                                  trans_lo, trans_hi, box[5]))
    if not boxes:
        return None
    breaks = sorted({a, b, *(v for box in boxes for v in box[:2])})
    minimum = math.inf
    prior = None
    sources: set[str] = set()
    for lo, hi in zip(breaks, breaks[1:]):
        if hi <= lo:
            continue
        mid = (lo + hi) / 2
        spans = sorted((tl, th, src) for al, ah, tl, th, src in boxes
                       if al < mid < ah)
        if not spans:
            return None
        components = []
        for tl, th, src in spans:
            if components and tl <= components[-1][1]:
                old = components[-1]
                components[-1] = (old[0], max(old[1], th), old[2] | {src})
            else:
                components.append((tl, th, {src}))
        match = next((c for c in components if c[0] <= trans <= c[1]), None)
        if match is None or (prior is not None and
                             min(prior[1], match[1]) <= max(prior[0], match[0])):
            return None
        minimum = min(minimum, match[1] - match[0])
        sources.update(match[2])
        prior = match
    return (minimum, sorted(sources)) if math.isfinite(minimum) else None


def _geometry_gap_reason(
        seg: Dict[str, Any], index: Dict[Tuple[str, str, int, int], List[Tuple[float, ...]]]
        ) -> Tuple[str, str]:
    """Name the PSM edge class for which no continuous conductor was proved."""
    pts = seg.get("points_um")
    if not pts or any(v is None for point in pts for v in point):
        return "psm_segment_coordinates_missing", "unknown"
    key = (str(seg["net"]).lower(), str(seg["layer0"]).lower())
    ends = [_point_metal_boxes(key, point, index) for point in pts]
    a, b = ends
    family = ("same_shape" if {id(box) for box in a} & {id(box) for box in b} else
              "two_shapes" if a and b else
              "one_shape" if a or b else "no_shape")
    (x0, y0), (x1, y1) = pts
    diagonal = x0 != x1 and y0 != y1
    if diagonal:
        if family == "two_shapes":
            _, ambiguous = _direct_metal_contact(a, b)
            if not ambiguous:
                _, ambiguous = _bridged_metal_contact(key, a, b, pts, index)
            if not ambiguous:
                _, ambiguous = _bridged_metal_contact(key, a, b, pts, index, 2)
            if ambiguous:
                return "psm_virtual_diagonal_ambiguous_contact_width", family
        if family == "one_shape":
            source = (a or b)[0][5]
            return f"psm_virtual_diagonal_leaves_{source}", family
        return f"psm_virtual_diagonal_{family}_path_unproven", family
    if family == "one_shape":
        return "psm_edge_partly_outside_same_net_metal", family
    if family == "no_shape":
        return "psm_edge_without_same_net_metal", family
    return "psm_edge_has_no_continuous_cross_section", family


def _def_pg_widths_of(def_path: Path) -> Dict[str, float]:
    """Parse ONE DEF's SPECIALNETS into {layer_lc: min positive width um}."""
    try:
        text = def_path.read_text(errors="replace")
    except OSError:
        return {}
    dbm = _DEF_DBU_RE.search(text)
    dbu = _num(dbm.group(1)) if dbm else None
    if not dbu or dbu <= 0:
        return {}
    sm = _DEF_SNET_SECTION_RE.search(text)
    if not sm:
        return {}
    out: Dict[str, float] = {}
    for wm in _DEF_SNET_WIRE_RE.finditer(sm.group(1)):
        w_um = _num(wm.group(2))
        if w_um is None or w_um <= 0:
            continue  # 0-width entries are via points, not wires
        w_um = w_um / dbu
        lyr = wm.group(1).lower()
        if lyr not in out or w_um < out[lyr]:
            out[lyr] = w_um
    return out


def discover_def_pg_min_widths(root: Optional[Path]) -> Dict[str, float]:
    """Per-layer lower bound (um) on routed PG wire width, from SPECIALNETS.

    ``root`` may be a DEF file or a project directory (searched at the
    canonical ``phase3/stage3/pnr/*.def``). Returns {} when no readable DEF
    with SPECIALNETS exists. This inventory is not a segment-width proof.
    Layer keys are lowercased to match ``parse_lef_jmax`` tables.

    Candidates are tried NEWEST-FIRST and the first non-empty width map
    wins. Alphabetical order answered about the WRONG SUBJECT, measured on
    spm x gf180mcuD 2026-08-31: ``sorted(...)[0]`` picked ``filled.def``,
    which at gate time was still the PREVIOUS (PDN-failed) run's copy with
    ZERO SPECIALNETS — {} — so the gate fell back to LEF widths and FAILed a
    grid whose freshly-routed DEF (13:13) carried the sized 7.24 um straps;
    the same command re-run 70 s later, after the new filled.def landed,
    PASSed. Newest-first also skips ``floorplan.def`` (written before
    pdngen, legitimately SPECIALNETS-free) instead of returning {} for the
    whole project."""
    if root is None:
        return {}
    try:
        if root.is_file():
            return _def_pg_widths_of(root)
        if not root.is_dir():
            return {}
        cands = sorted(root.glob("phase3/stage3/pnr/*.def"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return {}
    for c in cands:
        w = _def_pg_widths_of(c)
        if w:
            return w
    return {}


# ---------------------------------------------------------------------------
# Screening.
# ---------------------------------------------------------------------------
def _screen_segment(seg: Dict[str, Any], table: Dict[str, Dict[str, Any]],
                    margin: float, blacks_n: float,
                    def_widths: Optional[Dict[str, float]] = None
                    ) -> Dict[str, Any]:
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
            pair = tuple(sorted((l0, l1)))
            candidates = [entry for entry in table.values()
                          if entry.get("kind") == "cut"
                          and pair in entry.get("routing_pairs", ())]
            if len(candidates) == 1:
                cut = candidates[0]
        if cut is None:
            return {"status": "unscreened", "net": net,
                    "layer": f"{seg['layer0']}->{seg['layer1']}",
                    "reason": "via_cut_layer_not_in_jmax_reference",
                    "current_A": cur}
        if "jmax_areal_A_per_um2" in cut:
            area = seg.get("native_area_um2")
            if (seg.get("native_layer") != cut["orig_name"].lower()
                    or not isinstance(area, (int, float))
                    or not math.isfinite(area) or area <= 0):
                return {"status": "unscreened", "net": net,
                        "layer": cut["orig_name"],
                        "reason": "via_cut_area_unproven", "current_A": cur}
            limit = cut["jmax_areal_A_per_um2"]
            density = cur / area
            util = density / limit if limit > 0 else math.inf
            return {"status": "offender" if util >= (1.0 - margin) else "ok",
                    "net": net, "layer": cut["orig_name"], "basis": "areal",
                    "current_A": cur, "cross_section_area_um2": area,
                    "cuts": seg["native_cuts"],
                    "density_A_per_um2": density, "value": density,
                    "limit": limit, "utilization": util,
                    "geometry_source": "bound_native_current_density",
                    "lifetime_ratio": _lifetime_ratio(util, blacks_n)}
        # The native tool owns its effective cut population. Offline inputs
        # keep the conservative whole-branch screen; no VIA-master count is
        # substituted for the measured native branch.
        limit = cut["jmax_per_cut_A"]
        cuts = seg.get("native_cuts") if seg.get("native_basis") == "PER_CUT" else None
        value = cur / cuts if isinstance(cuts, int) and cuts > 0 else cur
        util = value / limit if limit > 0 else math.inf
        offender = util >= (1.0 - margin)
        return {"status": "offender" if offender else "ok", "net": net,
                "layer": cut["orig_name"], "basis": "per_cut",
                "current_A": cur, "value_A_per_cut": value,
                **({"cuts": cuts, "geometry_source": "bound_native_current_density"}
                   if cuts is not None else {}),
                "limit_A_per_cut": limit, "utilization": util,
                "lifetime_ratio": _lifetime_ratio(util, blacks_n)}

    entry = table.get(l0)
    if entry is None:
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "layer_not_in_jmax_reference", "current_A": cur}
    if entry.get("kind") != "routing":
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "layer_is_not_routing", "current_A": cur}
    area = seg.get("native_area_um2") if seg.get("native_layer") == l0 else None
    thickness = entry.get("thickness_um")
    width = area / thickness if area and thickness else seg.get("width_um")
    if not width or width <= 0:
        return {"status": "unscreened", "net": net, "layer": seg["layer0"],
                "reason": "segment_conductor_geometry_unproven", "current_A": cur}

    dens_per_width = cur / width  # A/um
    dens_areal = cur / area if area else (cur / (width * thickness)) if thickness else None

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
        "width_source": seg.get("width_source", "segment_geometry"),
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


_PDK_REGISTRY = Path(__file__).with_name("pdk_registry.json")


def native_jmax_table(text: str, pdk_name: Optional[str] = None
                      ) -> Tuple[Dict[str, Dict[str, Any]], Optional[dict]]:
    """Apply only a selected PDK's cited per-cut rule to its matching cuts.

    Raw LEF semantics remain areal. An explicit registry rule is a separate
    foundry authority, never an interpretation of the LEF's numeric value.
    """
    table = parse_lef_jmax(text)
    registry = json.loads(_PDK_REGISTRY.read_text())
    selected = next((row for row in registry.get("pdks", [])
                     if row.get("name") == pdk_name), {})
    rule = selected.get("em_current_limits")
    if rule is None:
        return table, None
    if not isinstance(rule, dict) or not isinstance(rule.get("source"), dict):
        raise ValueError("declared per-cut authority has no source")
    source = rule["source"]
    if (not source.get("url") or not source.get("section")
            or not re.fullmatch(r"[a-f0-9]{40}", str(source.get("commit", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(source.get("sha256", "")))
            or not math.isfinite(float(rule["temperature_c"]))
            or rule.get("direction") != "unidirectional"):
        raise ValueError("declared per-cut authority provenance is incomplete")
    sizes = {}
    for via in _VIA_BLOCK_RE.finditer(text):
        body = via.group(2)
        layers = list(_VIA_LAYER_RE.finditer(body))
        for i, layer in enumerate(layers):
            part = body[layer.end():layers[i + 1].start() if i + 1 < len(layers) else len(body)]
            for rect in re.finditer(r"\bRECT\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+"
                                    r"([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*;", part):
                x0, y0, x1, y1 = map(float, rect.groups())
                sizes.setdefault(layer.group(1).lower(), set()).add(
                    tuple(sorted((round(abs(x1 - x0), 10), round(abs(y1 - y0), 10)))))
    overrides = parse_json_jmax(rule)
    applied = {}
    for name, row in overrides.items():
        prior = table.get(name)
        if prior is None:
            continue  # This metal-stack variant does not contain that cut.
        if prior.get("kind") != "cut" or row.get("kind") != "cut":
            raise ValueError("per-cut authority names a routing layer")
        dimensions = tuple(sorted(map(float, rule["layers"][row["orig_name"]]["cut_size_um"])))
        limit = row["jmax_per_cut_A"]
        if (len(dimensions) != 2 or not all(math.isfinite(x) and x > 0 for x in dimensions)
                or sizes.get(name) != {dimensions} or not math.isfinite(limit) or limit <= 0):
            raise ValueError(f"per-cut authority cut geometry is unsupported: {name}")
        replacement = dict(prior, **row, cut_size_um=list(dimensions))
        replacement.pop("jmax_areal_A_per_um2", None)
        table[name] = replacement
        applied[name] = {"jmax_A_per_cut": limit, "cut_size_um": list(dimensions)}
    if not applied:
        raise ValueError("declared per-cut authority matches no current cut layer")
    return table, {"registry_sha256": _native_sha(_PDK_REGISTRY),
                   "source": source, "temperature_c": rule["temperature_c"],
                   "direction": rule["direction"], "layers": applied}


def native_limits(text: str, margin: float = _DEFAULT_MARGIN,
                  pdk_name: Optional[str] = None) -> str:
    """Fork limits: cited per-cut authority, otherwise literal LEF areal."""
    table, _ = native_jmax_table(text, pdk_name)
    result = []
    for row in table.values():
        per_cut = row.get("jmax_per_cut_A")
        value = per_cut if per_cut is not None else row.get("jmax_areal_A_per_um2")
        if value is not None and math.isfinite(value) and value > 0:
            basis = " per_cut" if per_cut is not None else ""
            result.append(f"{row['orig_name']}{basis} {value * (1 - margin):.12g}\n")
    return "".join(result)


def native_source_identity() -> Dict[str, str]:
    """Bind the owned producer functions and both consumers, not unrelated steps."""
    root = Path(__file__).resolve().parent
    runner = (root / "phase3_one_shot_runner.py").read_text()
    lines = runner.splitlines(keepends=True)
    owned = {"_step24_basis_inputs", "_step24_transient_argv",
             "_emit_ir_em_reports", "_emit_em_current_authority",
             "_step25_native_density_due", "_librelane_step24_record",
             "_librelane_step24_publish", "_librelane_step24_refusal_publish",
             "_step24_primary_mode", "_step24_adopt_primary"}
    result = {}
    for node in ast.parse(runner).body:
        if isinstance(node, ast.FunctionDef) and node.name in owned:
            result[node.name] = hashlib.sha256(
                "".join(lines[node.lineno - 1:node.end_lineno]).encode()).hexdigest()
    for name in ("em_current_density_check.py", "em_peak_current_authority_check.py",
                 "librelane_ir_antenna.py", "dynamic_ir_vectored_emit.py",
                 "ir_drop_report_check.py"):
        result[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    return result


# Step 24 consumes its IR producers/readers from the existing joint identity.
# The EM-only consumers remain mandatory for Step 25, not for an unchanged
# adopted IR measurement. Missing required keys never compare equal by absence.
_PRIMARY_IR_SOURCE_KEYS = (
    "_librelane_step24_record", "_librelane_step24_refusal_publish",
    "_librelane_step24_publish", "_step24_primary_mode", "_step24_adopt_primary",
    "_step24_basis_inputs", "_step24_transient_argv", "_emit_ir_em_reports",
    "librelane_ir_antenna.py", "dynamic_ir_vectored_emit.py", "ir_drop_report_check.py",
)


def _native_sha(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _retained_project_root(project: Path, doc: Dict[str, Any],
                           recorded: Path, expected: str) -> tuple[Optional[Path], Path]:
    """Bind a recorded absolute state to its identical relocated project file.

    The immutable receipt already contains the project-relative artifact name
    and digest.  Derive the old root only when exactly one such artifact is a
    suffix of the recorded absolute path, then require an ordinary contained
    file with the same digest at the current root.  Nothing is rewritten.
    """
    matches = []
    for raw, digest in (doc.get("artifacts") or {}).items():
        rel = Path(raw) if isinstance(raw, str) else None
        if (rel is None or rel.is_absolute() or ".." in rel.parts
                or digest != expected or tuple(recorded.parts[-len(rel.parts):]) != rel.parts):
            continue
        matches.append(rel)
    if len(matches) != 1:
        raise ValueError("LibreLane IR project-relative tool state binding is ambiguous")
    rel = matches[0]
    current = project / rel
    if (current.is_symlink() or not current.is_file()
            or not current.resolve().is_relative_to(project.resolve())
            or _native_sha(current) != expected):
        raise ValueError("LibreLane IR tool state changed")
    old_root = recorded
    for _part in rel.parts:
        old_root = old_root.parent
    return old_root, current


def _retained_native_path(project: Path, raw: str, expected: str,
                          old_root: Optional[Path]) -> Path:
    """Resolve one native-basis path without changing receipt authority."""
    recorded = Path(raw)
    if not recorded.is_absolute():
        if ".." in recorded.parts:
            raise ValueError("LibreLane IR native basis path is unsafe")
        current = project / recorded
    elif old_root is not None and recorded.is_relative_to(old_root):
        current = project / recorded.relative_to(old_root)
    else:
        current = recorded
    if (current.is_symlink() or not current.is_file()
            or (current != recorded and
                not current.resolve().is_relative_to(project.resolve()))
            or not expected or _native_sha(current) != expected):
        raise ValueError("LibreLane IR native basis changed")
    return current


def native_project(em_path: Path) -> Optional[Path]:
    """Production reports owe native evidence; standalone offline screens do not."""
    for candidate in (em_path, *em_path.parents):
        report = candidate / "reports/phase3/em.json"
        try:
            doc = json.loads(report.read_text())
        except (OSError, ValueError):
            continue
        if doc.get("tool") == "openroad-psm":
            return candidate
        return None
    # Deleting the companion does not retire a production report's obligation.
    if em_path.parent.name == "phase3" and em_path.parent.parent.name == "reports":
        try:
            if "phase3_one_shot_runner" in (em_path.parent / "em.rpt").read_text():
                return em_path.parent.parent.parent
        except OSError:
            pass
    return None


def validate_primary_ir(project: Path) -> Dict[str, Any]:
    """Step-24's existing gate consumes the adopted current tool result.

    This validates the IR producer's own state and publication, independently
    of Step-25 density coverage. A partial EM result cannot retire a static IR
    measurement, nor can report keywords substitute for primary adoption.
    """
    try:
        doc = json.loads((project / "reports/phase3/ir_drop_librelane.json").read_text())
        recorded_source = doc.get("source_identity")
        current_source = native_source_identity()
        if (not doc.get("adopted") or not isinstance(recorded_source, dict)
                or any(not current_source.get(name)
                       or recorded_source.get(name) != current_source[name]
                       for name in _PRIMARY_IR_SOURCE_KEYS)):
            raise ValueError("LibreLane IR primary was not adopted by current source")
        if (not {"def", "netlist", "sdc", "spef"}.issubset(doc["inputs"])
                or not {"reports/phase3/ir_drop.json", "reports/phase3/ir_drop.rpt"}.issubset(doc["published"])):
            raise ValueError("LibreLane IR required input/publication binding removed")
        record = doc["record"]
        recorded_state = Path(record["tool_state"])
        state_sha = record["tool_state_sha256"]
        if recorded_state.is_absolute() and _native_sha(recorded_state) != state_sha:
            old_root, tool_state = _retained_project_root(
                project, doc, recorded_state, state_sha)
        else:
            old_root = None
            tool_state = _retained_native_path(
                project, record["tool_state"], state_sha, None)
        selected = None
        if record.get("input_mode") == "current_stapostpnr_odb":
            selected = record.get("selected_inputs")
            required = {"odb", "def", "netlist", "sdc", "spef", "sta_state",
                        "sta_receipt", "sta_config", "step23_record"}
            if not isinstance(selected, dict) or set(selected) != required:
                raise ValueError("LibreLane IR current STA input population changed")
            for role, row in selected.items():
                if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
                    raise ValueError(f"LibreLane IR current STA {role} binding malformed")
                path = Path(row["path"])
                target = path if path.is_absolute() else project / path
                if ((not path.is_absolute() and ".." in path.parts)
                        or not row["sha256"] or target.is_symlink()
                        or not target.is_file() or _native_sha(target) != row["sha256"]):
                    raise ValueError(f"LibreLane IR current STA bytes changed: {role}")
            chain = record.get("input_source_chain") or {}
            if (chain.get("source") != "current validated OpenROAD.STAPostPNR state"
                    or not chain.get("image") or not chain.get("pdk_root")
                    or not chain.get("pdk")):
                raise ValueError("LibreLane IR current STA source chain missing")
            config_path = Path(selected["sta_config"]["path"])
            config_path = config_path if config_path.is_absolute() else project / config_path
            import librelane_ir_antenna as la
            try:
                owner = la._current_stapostpnr_ir_inputs(
                    project, chain["image"], Path(chain["pdk_root"]), chain["pdk"],
                    json.loads(config_path.read_text()))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, la.Refusal) as exc:
                raise ValueError(f"LibreLane IR current STA owner invalid: {exc}") from exc
            if not owner or owner.get("records") != selected:
                raise ValueError("LibreLane IR current STA owner selection changed")
        for population in ("inputs", "artifacts", "published"):
            rows = doc[population]
            if not rows:
                raise ValueError(f"LibreLane IR {population} population absent")
            for key, row in rows.items():
                name, digest = (row["path"], row["sha256"]) if population == "inputs" else (key, row)
                path = Path(name)
                target = path if path.is_absolute() else project / path
                absolute_current_owner = (population == "inputs" and path.is_absolute()
                                          and selected is not None and key in selected
                                          and row == selected[key])
                if (population == "inputs" and selected is not None
                        and (key not in selected or row != selected[key])):
                    raise ValueError(f"LibreLane IR current STA role binding changed: {key}")
                if ((path.is_absolute() and not absolute_current_owner)
                        or (not path.is_absolute() and ".." in path.parts)
                        or not digest or _native_sha(target) != digest):
                    raise ValueError(f"LibreLane IR current bytes changed: {name}")
        # Preserve exact native-basis/relocation validation after the more
        # specific current-selection checks, keeping their refusal diagnosis.
        for row in [doc["native_basis"][key] for key in ("odb", "sdc", "spef", "tech_lef")] + doc["native_basis"]["liberties"]:
            _retained_native_path(project, row["path"], row["sha256"], old_root)
        if selected is not None:
            native_odb = doc["native_basis"]["odb"]
            if (selected["odb"]["sha256"] != native_odb["sha256"]
                    or Path(native_odb["path"]).resolve()
                    != (project / selected["odb"]["path"]).resolve()):
                raise ValueError("LibreLane IR did not consume selected current STA ODB")
        import librelane_ir_antenna as la
        rebound_record = dict(record)
        rebound_record["tool_state"] = str(tool_state)
        judged = la.judge_ir(rebound_record)
        if judged != doc["judgment"] or judged["verdict"] not in ("PASS", "FAIL"):
            raise ValueError("LibreLane IR measurement/coverage unavailable")
        return {"valid": True, "verdict": judged["verdict"],
                "producer": doc["producer"], "tool_state_sha256": record["tool_state_sha256"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"valid": False, "verdict": "NOT_MEASURED",
                "reason": str(exc), "rule": "LL_IR_CURRENT_BINDING_INVALID"}


def validate_native_density(project: Path, margin: float = _DEFAULT_MARGIN,
                            *, segment_geometry: Optional[dict] = None
                            ) -> Dict[str, Any]:
    """Existing Step-25 blocking consumer: verify execution, inputs and authority.

    A digest-bound snapshot makes an image-internal authority readable by the
    host gate. When the declared original is host-readable it is also checked.
    This is provenance, not a substitute for native measurements or full power
    basis coverage. Missing evidence is NOT_MEASURED; known native FAIL wins
    over valid partial coverage.
    """
    rpt = project / "reports/phase3"
    def local(name: str) -> Path:
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("non-project path in native binding")
        return project / rel

    try:
        doc = json.loads((rpt / "em_openroad_density.json").read_text())
        if doc.get("schema") != "em_native_density/1":
            raise ValueError("native execution binding absent")
        if doc.get("source_identity") != native_source_identity():
            raise ValueError("native producer/consumer source changed")
        execution = doc["execution"]
        if execution["native_rc"] != 0 or not execution["argv"]:
            raise ValueError("native invocation did not succeed")
        for name, digest in doc["outputs"].items():
            if not digest or _native_sha(local(name)) != digest:
                raise ValueError(f"native output changed: {name}")
        log = (rpt / "ir_em.log").read_text()
        if not doc["outputs"] or not doc["inputs"]:
            raise ValueError("empty native binding")
        required = {f"reports/phase3/{name}" for name in (
            "em.rpt", "em.json", "ir_drop.rpt", "ir_drop.json", "ir_em.log",
            "em_segments.csv", "em_pg_geometry.tsv", "em_pg_geometry_subject.json",
            "em_native_authority.tlef", "em_openroad_limits.txt")}
        required.update(f"reports/phase3/{prefix}_{net}.csv"
                        for net in doc["nets"] for prefix in ("em_segments", "em_openroad_density"))
        if not required.issubset(doc["outputs"]) or not {"layout", "tech_lef", "cell_lef", "liberty0"}.issubset(doc["inputs"]):
            raise ValueError("required native input/output binding removed")
        for role, row in doc["inputs"].items():
            digest = row["sha256"]
            if not digest or any(
                    f"EM_BOUND_{stage} {role} {digest}" not in log
                    for stage in ("BEFORE", "AFTER")):
                raise ValueError(f"native input was not read unchanged: {role}")
            current = local(row["project_path"]) if row.get("project_path") else Path(row["declared_path"])
            if (row.get("project_path") or current.is_file()) and _native_sha(current) != digest:
                raise ValueError(f"current input changed: {role}")
        authority = local(doc["authority"]["snapshot"])
        authority_sha = doc["inputs"]["tech_lef"]["sha256"]
        if _native_sha(authority) != authority_sha:
            raise ValueError("PDK authority snapshot changed")
        if not doc["pdk"]["name"] or doc["pdk"]["tech_lef"] != doc["inputs"]["tech_lef"]["declared_path"]:
            raise ValueError("declared PDK identity disagrees")
        text = authority.read_text()
        table, per_cut_authority = native_jmax_table(text, doc["pdk"]["name"])
        if doc["authority"].get("per_cut") != per_cut_authority:
            raise ValueError("selected PDK per-cut authority changed")
        if per_cut_authority is not None:
            per_cut_path = local(doc["authority"]["per_cut_snapshot"])
            relative = str(per_cut_path.relative_to(project))
            if (relative not in doc["outputs"] or "per_cut_authority" not in doc["inputs"]
                    or json.loads(per_cut_path.read_text()) != per_cut_authority
                    or doc["inputs"]["per_cut_authority"]["sha256"] != _native_sha(per_cut_path)):
                raise ValueError("per-cut authority was not bound to the native invocation")
        if doc["margin"] != margin:
            raise ValueError("Jmax margin differs from native execution")
        limits = rpt / "em_openroad_limits.txt"
        if limits.read_text() != native_limits(text, margin, doc["pdk"]["name"]):
            raise ValueError("native Jmax is not the declared routing authority")
        subject = json.loads((rpt / "em.json").read_text())
        static = json.loads((rpt / "ir_drop.json").read_text())
        basis = doc["power_basis"]
        for role, field in (("layout", "layout"), ("sdc", "sdc"), ("spef", "spef")):
            if basis.get(field) and basis[field + "_sha256"] != doc["inputs"][role]["sha256"]:
                raise ValueError("power basis input digest disagrees")
        primary = doc.get("step24_primary")
        if primary is not None:
            checked = validate_primary_ir(project)
            if not checked["valid"] or checked != primary:
                raise ValueError("current Step-24 primary binding changed")
            # This EM solve must carry its own complete basis. The primary
            # was measured independently and is compared by its actual native
            # SDC/SPEF/tech LEF/ODB/library population below, without rewriting
            # that earlier step's published dictionary.
            if not (doc.get("librelane_ir") or {}).get("adopted"):
                raise ValueError("current Step-24 primary reference absent")
        if ((primary is None and basis != static["power_basis"])
                or subject["power_basis"]["basis_id"] != basis["id"]
                or subject["subject_def_sha256"] != doc["inputs"]["layout"]["sha256"]
                or subject["subject_def"] != doc["inputs"]["layout"]["project_path"]):
            raise ValueError("DEF or power basis disagrees with the measurement")
        ll = doc.get("librelane_ir")
        if ll and ll.get("adopted"):
            ll_path = local(ll["record"])
            if _native_sha(ll_path) != ll["record_sha256"]:
                raise ValueError("LibreLane primary record changed")
            ll_doc = json.loads(ll_path.read_text())
            if primary is not None and (
                    ll_doc["inputs"]["def"]["sha256"] != doc["inputs"]["layout"]["sha256"]
                    or ll_doc["record"]["def_sha256"] != doc["inputs"]["layout"]["sha256"]):
                raise ValueError("LibreLane/EM layout basis differs")
            ll_basis = ll_doc["native_basis"]
            for role in ("sdc", "spef", "tech_lef"):
                if ll_basis[role]["sha256"] != doc["inputs"][role]["sha256"]:
                    raise ValueError(f"LibreLane/EM power basis differs: {role}")
            if ll_basis["odb"]["sha256"] != doc["inputs"]["librelane_odb"]["sha256"]:
                raise ValueError("EM did not consume the LibreLane PSM ODB")
            ll_libs = {row["sha256"] for row in ll_basis["liberties"]}
            em_libs = {row["sha256"] for role, row in doc["inputs"].items() if role.startswith("liberty")}
            if not ll_libs or ll_libs != em_libs:
                raise ValueError("LibreLane/EM library populations differ")
        coverage = {}
        for net in doc["nets"]:
            if f"EM_DENSITY_DONE {net}" not in log:
                raise ValueError(f"native density execution bypassed: {net}")
            csv_path = rpt / f"em_openroad_density_{net}.csv"
            csv_sha = _native_sha(csv_path)
            if f"EM_BOUND_OUTPUT {csv_path.name} {csv_sha}" not in log:
                raise ValueError(f"native density bytes unbound: {net}")
            rows = list(csv.DictReader(csv_path.open(newline="")))
            psm = list(csv.DictReader((rpt / f"em_segments_{net}.csv").open(newline="")))
            if not rows or len(rows) != len(psm):
                raise ValueError(f"native segment coverage disagrees: {net}")
            counts = {"checked": 0, "no_limit": 0, "violated": 0,
                      "psm_segments": len(psm), "worst_ratio": None}
            for row, psm_row in zip(rows, psm):
                layer = table.get(row["Layer"].lower(), {})
                status = row["Status"]
                if ((segment_geometry is not None or row["Basis"] == "PER_CUT") and layer
                        and status in ("OK", "VIOLATED") and row["Basis"] in ("AREAL", "PER_CUT")):
                    l0, l1 = (psm_row[name] for name in ("Node0 Layer", "Node1 Layer"))
                    points = tuple(tuple(float(psm_row[f"Node{node} {axis} location"])
                                         for axis in ("X", "Y")) for node in (0, 1))
                    current = abs(float(psm_row["Current"]))
                    if row["Basis"] == "PER_CUT" and l0.lower() == l1.lower():
                        raise ValueError("per-cut density has no routing-to-cut topology")
                    if (any(float(row[f"Node{node} {axis}"]) != points[node][axis_index]
                            for node in (0, 1) for axis_index, axis in enumerate(("X", "Y")))
                            or abs(float(row["Current(A)"])) != current):
                        raise ValueError("native density row differs from its PSM segment")
                    if (l0.lower() != l1.lower()
                            or points[0][0] != points[1][0] and points[0][1] != points[1][1]):
                        pair = tuple(sorted((l0.lower(), l1.lower())))
                        if (layer["kind"] == "cut" and pair not in layer.get("routing_pairs", ())
                                or layer["kind"] == "routing" and
                                not l0.lower() == l1.lower() == row["Layer"].lower()):
                            raise ValueError("native density layer disagrees with VIA topology")
                        area = float(row["Area(um^2)"])
                        cuts = int(row["Cuts"])
                        per_cut = row["Basis"] == "PER_CUT"
                        divisor = float(cuts) if per_cut else area
                        if (not math.isfinite(area) or area <= 0
                                or not math.isfinite(current)
                                or layer["kind"] == "cut" and cuts <= 0
                                or per_cut and (layer["kind"] != "cut"
                                    or not layer.get("jmax_per_cut_A")
                                    or not math.isclose(area / cuts,
                                        math.prod(layer["cut_size_um"]), rel_tol=0.0001))
                                or not _native_density_roundtrip_matches(
                                    current, divisor, float(row["J(A/um^2)"]),
                                    exact_divisor=per_cut)):
                            raise ValueError("native conductor cross section is unproven")
                        key = _segment_geometry_key(net, l0, l1, points, current)
                        geometry = {"native_area_um2": area, "native_cuts": cuts,
                                    "native_layer": row["Layer"].lower(),
                                    "native_basis": row["Basis"]}
                        if segment_geometry is not None:
                            if key in segment_geometry and segment_geometry[key] != geometry:
                                raise ValueError("ambiguous native segment cross section")
                            segment_geometry[key] = geometry
                if status == "NO_LIMIT":
                    counts["no_limit"] += 1
                    continue
                expected_basis = "PER_CUT" if layer.get("jmax_per_cut_A") is not None else "AREAL"
                if status not in ("OK", "VIOLATED") or layer.get("kind") not in ("routing", "cut") or row["Basis"] != expected_basis:
                    raise ValueError("wire-to-via substitution or invalid native status")
                expected = layer["jmax_per_cut_A" if expected_basis == "PER_CUT" else "jmax_areal_A_per_um2"] * (1 - margin)
                if not math.isclose(float(row["Jlimit(A/um^2)"]), expected, rel_tol=0.0006):
                    raise ValueError("native CSV Jmax differs from PDK authority")
                ratio = float(row["Ratio"])
                if not math.isfinite(ratio) or ratio < 0:
                    raise ValueError("invalid native density ratio")
                counts["checked"] += 1
                counts["violated"] += status == "VIOLATED"
                counts["worst_ratio"] = max(counts["worst_ratio"] or 0, ratio)
            if counts != doc["nets"][net]:
                raise ValueError("native coverage summary changed")
            coverage[net] = counts
        if not coverage or set(coverage) != set(subject["nets_analysed"]):
            raise ValueError("native density omitted a supply net")
        violations = sum(x["violated"] for x in coverage.values())
        missing = sum(x["no_limit"] for x in coverage.values())
        verdict = ("FAIL" if violations else "NOT_MEASURED" if missing or not basis.get("complete") or (ll and not ll.get("adopted"))
                   else "PASS")
        return {"valid": True, "verdict": verdict, "authority": str(authority),
                "authority_sha256": authority_sha, "pdk": doc["pdk"],
                "nets": coverage, "violations": violations,
                "unmeasured_segments": missing, "power_basis_complete": bool(basis.get("complete")),
                "source_identity": doc["source_identity"],
                "per_cut_authority": per_cut_authority}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"valid": False, "verdict": "NOT_MEASURED",
                "reason": str(exc), "rule": "EM_NATIVE_BINDING_INVALID"}


def evaluate(em_path: Optional[Path], jmax_path: Optional[Path],
             tech_lef: Optional[Path], margin: float, blacks_n: float,
             net_hint: Optional[str], top_offenders: int,
             def_widths: Optional[Dict[str, float]] = None,
             def_path: Optional[Path] = None,
             pg_geometry_path: Optional[Path] = None
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

    # Normal producer reports must reach this consumer through the native
    # invocation on the current basis. Offline segment fixtures stay offline.
    native = None
    native_geometry = {}
    production = native_project(em_path)
    if production is not None:
        native = validate_native_density(production, margin, segment_geometry=native_geometry)
        rep["native_density"] = native
        supplied = tech_lef or jmax_path
        if native["valid"] and supplied is not None and _native_sha(supplied) != native["authority_sha256"]:
            native = dict(native, valid=False, verdict="NOT_MEASURED",
                          reason="selected Jmax differs from the native PDK authority")
            rep["native_density"] = native
        if not native["valid"]:
            rep.update(verdict="NOT_MEASURED", **{"pass": False},
                       skip_reason="native_execution_or_basis_unbound")
            rep["findings"].append({"severity": "NOT_MEASURED",
                                    "rule": "EM_NATIVE_BINDING_INVALID",
                                    "message": native["reason"]})
            return "NOT_MEASURED", rep
        tech_lef, jmax_path = Path(native["authority"]), None

    # (2) Jmax reference present?
    if production is not None:
        table, _ = native_jmax_table(tech_lef.read_text(), native["pdk"]["name"])
        jmax_src, jerr = str(tech_lef), None
    else:
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
    unscreened_by_net_layer: Dict[str, int] = {}
    unmeasured_shape_families: Dict[str, int] = {}

    local_rects = _geometry_index(_def_pg_local_rects(def_path)) if def_path else {}
    odb_rects = (_geometry_index(_odb_pg_geometry_rects(pg_geometry_path))
                 if pg_geometry_path else {})
    local_width_uses = 0
    odb_width_uses = 0
    not_measured_segments: List[Dict[str, Any]] = []
    worst_segments: List[Tuple[float, int, Dict[str, Any]]] = []
    for seg in segs:
        n_total += 1
        measured = seg
        native_shape = (native_geometry.get(_segment_geometry_key(
            seg["net"], seg["layer0"], seg["layer1"], seg["points_um"], seg["current_A"]))
                        if native_geometry and seg.get("points_um") else None)
        if native_shape and seg["layer0"].lower() != seg["layer1"].lower():
            measured = dict(seg, **native_shape)
        if seg["layer0"].lower() == seg["layer1"].lower():
            geometry = _segment_geometry_width(seg, odb_rects)
            source = "odb_pg_metal_geometry"
            if geometry is None:
                geometry = _segment_geometry_width(seg, local_rects)
                source = "def_same_net_covering_wire"
            measured = dict(seg, width_um=geometry[0] if geometry else None,
                            width_source=source)
            if not geometry and native_shape:
                measured.update(native_shape, width_source="bound_native_current_density")
            if geometry:
                if source == "odb_pg_metal_geometry":
                    odb_width_uses += 1
                else:
                    local_width_uses += 1
                measured["geometry_sources"] = geometry[1]
        r = _screen_segment(measured, table, margin, blacks_n, def_widths)
        if "geometry_sources" in measured and r["status"] != "unscreened":
            r["geometry_sources"] = measured["geometry_sources"]
        if r["status"] == "unscreened":
            if r["reason"] == "segment_conductor_geometry_unproven":
                reason, family = _geometry_gap_reason(
                    seg, odb_rects if odb_rects else local_rects)
                r["reason"] = reason
                r["shape_family"] = family
                unmeasured_shape_families[family] = (
                    unmeasured_shape_families.get(family, 0) + 1)
            n_unscreened += 1
            unscreened_reasons[r["reason"]] = unscreened_reasons.get(r["reason"], 0) + 1
            net_layer = f"{seg['net']}:{seg['layer0']}"
            unscreened_by_net_layer[net_layer] = (
                unscreened_by_net_layer.get(net_layer, 0) + 1)
            if len(not_measured_segments) < max(1, top_offenders):
                not_measured_segments.append(dict(r, status="NOT_MEASURED",
                                                  points_um=seg.get("points_um")))
            continue
        n_screened += 1
        r["points_um"] = seg.get("points_um")
        ranked = (r["utilization"], n_total, r)
        if len(worst_segments) < max(1, top_offenders):
            heapq.heappush(worst_segments, ranked)
        elif ranked[0] > worst_segments[0][0]:
            heapq.heapreplace(worst_segments, ranked)
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
        "unscreened_by_net_layer": unscreened_by_net_layer,
        "unmeasured_shape_families": unmeasured_shape_families,
        "worst_utilization": (round(worst_util, 6) if worst_util >= 0 else None),
        "worst_case_lifetime_ratio": (round(min_life, 4) if min_life is not None else None),
        "per_layer": {k: {"segments": v["segments"],
                          "max_utilization": round(v["max_utilization"], 6)}
                      for k, v in sorted(per_layer.items())},
        "jmax_layers": sorted(e["orig_name"] for e in table.values()),
        "local_def_width_uses": local_width_uses,
        "odb_pg_geometry_width_uses": odb_width_uses,
    }
    rep["worst_segments"] = [item[2] for item in sorted(worst_segments, reverse=True)]
    rep["not_measured_segments"] = not_measured_segments

    # (3b) report present + Jmax present but nothing mapped → SKIPPED, never PASS
    if n_screened == 0 and not (native and native["verdict"] == "FAIL"):
        geometry_missing = any(k.startswith("psm_") for k in unscreened_reasons)
        empty_verdict = "NOT_MEASURED" if geometry_missing else "SKIPPED"
        rep["verdict"] = empty_verdict
        rep["pass"] = False
        rep["skip_reason"] = ("no_segments" if n_total == 0
                              else "segment_conductor_geometry_unproven" if geometry_missing
                              else "no_segment_maps_to_jmax_reference")
        rep["findings"].append({
            "severity": empty_verdict, "rule": "NOTHING_SCREENED",
            "message": (f"{n_total} segment(s) read but none could be screened "
                        f"against the Jmax reference ({dict(unscreened_reasons)}); "
                        "§4.05: not a PASS")})
        return empty_verdict, rep

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

    if native and native["verdict"] == "FAIL":
        rep.update(verdict="FAIL", **{"pass": False})
        rep["findings"].append({"severity": "ERROR",
                                "rule": "EM_NATIVE_CURRENT_DENSITY_OVER_JMAX",
                                "message": f"native checker measured {native['violations']} over-limit segments"})
        return "FAIL", rep

    if n_unscreened or (native and native["verdict"] != "PASS"):
        rep["verdict"] = "NOT_MEASURED"
        rep["pass"] = False
        rep["skip_reason"] = "one_or_more_segments_not_measured"
        rep["findings"].append({
            "severity": "NOT_MEASURED", "rule": "EM_SEGMENT_GEOMETRY_UNPROVEN",
            "message": f"{n_unscreened} of {n_total} segment(s) lack a proven "
                       "same-net conductor cross section or Jmax"})
        if native and not native["power_basis_complete"]:
            rep["findings"].append({"severity": "NOT_MEASURED",
                                    "rule": "EM_POWER_BASIS_INCOMPLETE",
                                    "message": "native static basis lacks matched SPEF or readable constraints"})
        return "NOT_MEASURED", rep

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


def emit_openroad_ab(project: Path, notes: List[str]) -> None:
    """Compare two measurements of one DEF without promoting an empty tool PASS."""
    from _atomic_artefact import write_text as _atomic_write_text
    rpt = project / "reports/phase3"
    output = rpt / "em_openroad_ab.json"
    try:
        tool = json.loads((rpt / "em_openroad_density.json").read_text())
        gate = json.loads((rpt / "em_current_authority.json").read_text())
        subject = json.loads((rpt / "em.json").read_text())
    except (OSError, ValueError) as exc:
        _atomic_write_text(output, json.dumps({"verdict": "NOT_MEASURED",
            "reason": f"A/B input absent or invalid: {exc}"}, indent=2) + "\n")
        return
    same_def = (tool.get("def_sha256") and
                tool.get("def_sha256") == subject.get("subject_def_sha256"))
    nets = tool.get("nets") or {}
    measured = (same_def and tool.get("verdict") == "MEASURED" and
                isinstance(nets, dict) and nets and
                all(row.get("checked", 0) > 0 and row.get("no_limit") == 0
                    for row in nets.values()))
    jmax = gate.get("jmax_screen") or {}
    summary = jmax.get("summary") or {}
    if not measured or jmax.get("verdict") not in ("PASS", "FAIL"):
        result = {"verdict": "NOT_MEASURED", "same_def": bool(same_def),
                  "reason": "tool coverage or retained Jmax gate unavailable"}
    else:
        tool_violations = sum(int(row.get("violated", 0)) for row in nets.values())
        gate_offenders = int(jmax.get("offender_count", 0))
        tool_util = max(float(row.get("worst_ratio") or 0) for row in nets.values())
        gate_util = summary.get("worst_utilization")
        result = {
            "verdict": "MEASURED", "same_def": True,
            "tool_violations": tool_violations,
            "vibeic_offender_count": gate_offenders,
            "offender_count_agrees": tool_violations == gate_offenders,
            "offender_sets": "NOT_MEASURED: retained gate records only top offenders",
            "tool_worst_utilization": tool_util,
            "vibeic_worst_utilization": gate_util,
            "utilization_agrees": gate_util is not None and abs(tool_util - gate_util) < 0.001,
            "source_model": tool.get("source_model"),
            "sdc_spef_loaded": tool.get("sdc_spef_loaded"),
            "signal_em": tool.get("signal_em"),
            "via_cut_status": tool.get("via_cut_status"),
        }
        if not result["offender_count_agrees"] or not result["utilization_agrees"]:
            notes.append("EM OpenROAD/vibe-ic A/B differs; see em_openroad_ab.json")
    _atomic_write_text(output, json.dumps(result, indent=2) + "\n")


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
    ap.add_argument("--def-file", default=None,
                    help="the exact routed DEF measured by the EM report")
    ap.add_argument("--pg-geometry", default=None,
                    help="ODB TSV of actual placed PG port, special-wire and "
                         "via-metal rectangles for the measured DEF")
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
    def_file = Path(args.def_file) if args.def_file else None
    geometry_file = Path(args.pg_geometry) if args.pg_geometry else None

    verdict, rep = evaluate(em_path, jmax_path, tech_lef, args.margin,
                            args.blacks_n, args.net, args.top_offenders,
                            def_path=def_file, pg_geometry_path=geometry_file)
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return {"PASS": 0, "FAIL": 1, "SKIPPED": 3, "NOT_MEASURED": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
