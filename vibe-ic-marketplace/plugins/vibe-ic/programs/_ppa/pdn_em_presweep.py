#!/usr/bin/env python3
"""_ppa/pdn_em_presweep.py — size the PDN for electromigration BEFORE routing.

Steps 25 / 25b (migration T103). The EM gate (`em_peak_current_authority_check`
over `em_current_density_check`) judges the ROUTED grid. Before this module the
only remedy for a red was the post-route resize: widen the straps, then run a
second PnR. That loop is gone (v1.24.85); this is its replacement, one step
earlier, where changing a strap costs one PSM solve instead of one PnR.

WHERE IT RUNS
=============
Inside the PnR session, after CTS and hold repair and before global routing.
The design is placed, the clock tree exists, the declared SDC and every library
of the session (the IO pads' included) are loaded, and placement parasitics are
estimated. So the grid carries the design's own current on the design's own
power basis, and the straps can still change without disturbing anything that
has been routed: nothing has.

For each candidate the session deletes the supply special wiring (every PG
special wire comes from the PDN block; the supply BTerms are kept -- see
below), re-runs the SAME deck block the flow emitted with only the strap
widths / pitches changed, and measures:

  * OpenROAD PSM `analyze_power_grid -enable_em` per supply net, and
  * OpenROAD `check_current_density` on the same solve (the tool arm, recorded
    as an A/B; see JUDGE),

then asks this module (staged into the run, executed by the session's own
python) which candidate to evaluate next. The candidate chosen is rebuilt in
place and the flow continues to global routing. When the flow's own grid
already passes, nothing is rebuilt and the deck is unchanged.

THE LATTICE
===========
Per strap layer, a width multiplier and a pitch divisor, applied to the width
and pitch the deck itself planned (never a number from another run):
`LAYER_OPTIONS`. Width is rounded UP to 2x the tech LEF MANUFACTURINGGRID
(pdngen centres a stripe, so the half width must be on grid: PDN-0117); a
changed pitch is rounded down to the grid and its offset re-derived by the
deck's own rule. A layer option is admitted only when two nets still fit in a
pitch at the layer's LEF spacing, the straps take at most the deck's routing
budget of the layer's tracks, and the width is inside the layer's MAXWIDTH.
Candidates are ordered by the planned strap track fraction (sum of 2w/p), so
the first feasible candidate is the cheapest feasible one.

THE SEARCH
==========
Candidate 0 is the grid the flow drew, measured in place. If it passes, done.
Otherwise the layers that carry an offender are the layers to change: only
candidates that change at least one of them are evaluated (all strap layers if
no offender is on a strap layer), cheapest first, until one passes or
`MAX_EVALUATIONS` is spent. No pass: the candidate with the lowest worst
utilisation is kept if it improves on the flow's grid, and the record says
INFEASIBLE -- the Step-25 gate then still judges the routed grid. The supply
pad count is the next axis and is NOT swept here: a pad is a floorplan fact,
and this session is past the floorplan. The record names that.

JUDGE
=====
Feasibility is the Step-25 gate's own instrument: `em_current_density_check.
evaluate` with the candidate's DEF widths and its drawn PG geometry, at the
gate's margin, on every supply net. OpenROAD's `check_current_density` runs on
the same solve and is recorded beside it, never used to select: MEASURED on spm
it reports Metal1 segments 5 nm wide (a single shape's dimension where same-net
metal overlaps) at 1000%+ of the limit on every candidate, so it cannot tell
two grids apart.

SOURCE MODEL
============
`pdngen -ripup` also deletes the supply BTerms' pins (MEASURED: VDD=1 -> 0),
and PSM then falls back to its generated sources: every top-layer node becomes
a source and the peak segment current drops 4x (1.40 mA -> 0.38 mA on spm).
So the session never rips up; it destroys the special wires only, and the
BTerms stay where the pad ring put them. Following T101 (step 24): when every
supply BTerm lies on a declared supply pad, PSM's default BTerm sources ARE the
declared-pad model and no -vsrc is passed; otherwise the declared pads' BTerms
are written to a VSRC file and passed explicitly; a supply net with no BTerm on
a declared pad stops the sweep (NOT_MEASURED), never a guessed source.

chip-AGNOSTIC: layers, widths, pitches, nets, pads, corners and limits come
from the deck, the tech LEF, the session and the design's declarations.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import vibeic_temp as tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

if __package__ in (None, ""):
    # Run by path (the PnR session execs the staged copy): the parent of
    # `_ppa` holds `em_current_density_check` and the `_ppa` package.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import em_current_density_check as _emcd  # noqa: E402

SCHEMA = "vibeic.ppa.pdn_em_presweep.v1"
SWEEP_DIR = "pdn_em_presweep"
LATTICE_FILE = "lattice.json"
RECORD_FILE = "presweep.json"
REPORT_REL = "reports/phase3/pdn_em_presweep.json"
#: (width multiplier, pitch divisor) per strap layer. The (1, 1) entry is the
#: deck's own plan; the rest double at most the strap count and triple at most
#: the width, which is the envelope the post-route resize never exceeded.
LAYER_OPTIONS: Tuple[Tuple[float, int], ...] = (
    (1.0, 1), (1.5, 1), (2.0, 1), (1.0, 2), (3.0, 1), (1.5, 2), (2.0, 2), (3.0, 2))
#: The session solves PSM once per net per candidate; a spent budget ends the
#: search with the best measured candidate, never with an unmeasured guess.
MAX_EVALUATIONS = 8


# --------------------------------------------------------------------------
# tech LEF rules
# --------------------------------------------------------------------------
def _layer_body(tlef: str, layer: str) -> str:
    m = re.search(r"^\s*LAYER\s+" + re.escape(layer) + r"\s*$(.*?)^\s*END\s+"
                  + re.escape(layer) + r"\s*$", tlef or "", re.M | re.S | re.I)
    return re.sub(r"#[^\n]*", "", m.group(1)) if m else ""


def layer_rules(tlef: str, layer: str) -> Dict[str, Any]:
    """Spacing (largest plain SPACING, or the first SPACINGTABLE entry),
    MAXWIDTH and DIRECTION of one routing layer, from its LEF statements."""
    body = _layer_body(tlef, layer)
    spaces = [float(x) for x in re.findall(r"^\s*SPACING\s+([0-9.]+)\s*;", body, re.M | re.I)]
    if not spaces:
        tab = re.search(r"SPACINGTABLE.*?WIDTH\s+[0-9.]+((?:\s+[0-9.]+)+)", body, re.S | re.I)
        if tab:
            spaces = [float(tab.group(1).split()[-1])]
    maxw = re.search(r"^\s*MAXWIDTH\s+([0-9.]+)\s*;", body, re.M | re.I)
    direc = re.search(r"^\s*DIRECTION\s+(\w+)\s*;", body, re.M | re.I)
    return {"spacing_um": max(spaces) if spaces else None,
            "max_width_um": float(maxw.group(1)) if maxw else None,
            "direction": direc.group(1).upper() if direc else None}


def manufacturing_grid(tlef: str) -> float:
    m = re.search(r"^\s*MANUFACTURINGGRID\s+([0-9.eE+\-]+)\s*;", tlef or "", re.M | re.I)
    try:
        g = float(m.group(1)) if m else 0.001
    except ValueError:
        g = 0.001
    return g if 0 < g <= 1.0 else 0.001


def _up(v: float, q: float) -> float:
    return round(math.ceil(v / q - 1e-9) * q, 6)


def _down(v: float, q: float) -> float:
    return round(math.floor(v / q + 1e-9) * q, 6)


# --------------------------------------------------------------------------
# the lattice
# --------------------------------------------------------------------------
def layer_options(strap: Mapping[str, Any], rules: Mapping[str, Any], *, grid: float,
                  budget: float, offset_div: float) -> List[Dict[str, Any]]:
    """Every admitted (width, pitch, offset) for one strap layer, (1, 1) first.
    A refused option carries its reason, so the record shows why it was not
    measured."""
    w0, p0, o0 = float(strap["width"]), float(strap["pitch"]), float(strap.get("offset") or 0)
    out: List[Dict[str, Any]] = []
    for mult, div in LAYER_OPTIONS:
        w = w0 if mult == 1 else _up(w0 * mult, 2 * grid)
        p = p0 if div == 1 else _down(p0 / div, grid)
        o = o0 if div == 1 else _down(p / offset_div, grid)
        row = {"width": w, "pitch": p, "offset": o, "width_x": mult, "pitch_div": div}
        s = rules.get("spacing_um")
        why = None
        if (mult, div) != (1.0, 1):
            if s is None:
                why = "tech LEF states no SPACING for the layer"
            elif not 2 * w + s < p:
                why = f"two straps of {w}um plus spacing {s}um do not fit pitch {p}um"
            elif 2 * w / p > budget + 1e-12:
                why = f"strap track fraction {2 * w / p:.4f} exceeds the routing budget {budget}"
            elif rules.get("max_width_um") and w > float(rules["max_width_um"]):
                why = f"width {w}um exceeds MAXWIDTH {rules['max_width_um']}um"
        if why:
            row["refused"] = why
        out.append(row)
    return out


def lattice(straps: Sequence[Mapping[str, Any]], tlef: str, *, budget: float,
            offset_div: float) -> Dict[str, Any]:
    """The candidate set over the deck's strap layers, cheapest first after
    the deck's own grid (candidate "0")."""
    grid = manufacturing_grid(tlef)
    by_layer: Dict[str, Mapping[str, Any]] = {}
    for st in straps:
        if st.get("layer") and st.get("width") and st.get("pitch"):
            by_layer.setdefault(str(st["layer"]), st)
    layers = sorted(by_layer)
    options = {l: layer_options(by_layer[l], layer_rules(tlef, l), grid=grid,
                                budget=budget, offset_div=offset_div) for l in layers}
    refused = [{"layer": l, **o} for l in layers for o in options[l] if o.get("refused")]
    combos: List[Dict[str, Dict[str, Any]]] = [{}]
    for l in layers:
        combos = [dict(c, **{l: o}) for c in combos for o in options[l] if not o.get("refused")]
    cands = []
    for combo in combos:
        changed = sorted(l for l, o in combo.items() if (o["width_x"], o["pitch_div"]) != (1.0, 1))
        cands.append({
            "straps": {l: {k: o[k] for k in ("width", "pitch", "offset", "width_x", "pitch_div")}
                       for l, o in combo.items()},
            "changed": changed,
            "planned_track_fraction": round(sum(2 * o["width"] / o["pitch"] for o in combo.values()), 6),
        })
    cands.sort(key=lambda c: (bool(c["changed"]), c["planned_track_fraction"], len(c["changed"]),
                              json.dumps(c["straps"], sort_keys=True)))
    for i, c in enumerate(cands):
        c["id"] = str(i)
    return {"schema": SCHEMA, "manufacturing_grid_um": grid, "routing_budget": budget,
            "offset_div": offset_div, "layers": layers,
            "directions": {l: layer_rules(tlef, l)["direction"] for l in layers},
            "candidates": cands, "refused_options": refused}


# --------------------------------------------------------------------------
# the session side (Tcl emitted by the host, executed by OpenROAD)
# --------------------------------------------------------------------------
def jmax_limits_text(tlef: str, margin: float) -> str:
    """`check_current_density -em_limits_file`: areal A/um^2 per routing
    layer, the gate's own LEF reading and margin."""
    rows = [f"{r['orig_name']} {r['jmax_areal_A_per_um2'] * (1 - margin):.12g}"
            for r in _emcd.parse_lef_jmax(tlef).values()
            if r.get("kind") == "routing" and r.get("jmax_areal_A_per_um2")]
    return "\n".join(rows) + ("\n" if rows else "")


def session_tcl(*, sweep_dir: str, python: str, nets: Mapping[str, float],
                corner: Optional[str], declared_pads: Sequence[str],
                stage_marker: str) -> str:
    """The pre-route block. `nets` maps each swept supply net to its voltage;
    `corner` qualifies PSM in a multi-corner session. Every failure inside is
    caught: the flow then continues on the grid it had, and says so."""
    corner_opt = f" -corner {corner}" if corner else ""
    net_list = " ".join(nets)
    volts = "".join(f"  set_pdnsim_net_voltage -net {n} -voltage {v:g}{corner_opt}\n"
                    for n, v in nets.items())
    pads = " ".join(declared_pads)
    geom = _emcd.PG_GEOMETRY_TCL.replace("__GEOMETRY_PATH__", "$_pes_cd/em_pg_geometry.tsv")
    # A padless block's promoted supply pins are its interface, not PSM's
    # source model (`_psm_source_model`): every candidate is solved with them
    # marked PSM_DISCONNECT, and the marks are removed again because this
    # session goes on to write the database. Imported here, on the host: the
    # staged copy the session execs only runs `next`.
    import _psm_source_model as _psm_sm
    psm_x = _psm_sm.exclude_promoted_pins_tcl()
    psm_r = _psm_sm.restore_promoted_pins_tcl()
    psm_clear = _psm_sm.clear_generated_supply_pins_tcl()
    return f'''# === T103 — size the PDN for EM before routing (_ppa/pdn_em_presweep) ===
puts "{stage_marker} preroute_pdn_em_sizing"
set _pes_dir {{{sweep_dir}}}
proc _vibeic_pes_build {{k}} {{
  global _pes_dir
{psm_clear}  # PdnGen retains FIRM pin boxes from the previous pitch. The
  # padless grid owns those boxes; a die's pad-ring boxes are retained.
  foreach _n [[ord::get_db_block] getNets] {{
    if {{[$_n getSigType] ni {{POWER GROUND}}}} {{ continue }}
    foreach _sw [$_n getSWires] {{ odb::dbSWire_destroy $_sw }}
  }}
  pdngen -reset
  uplevel #0 [list source $_pes_dir/cand_$k.tcl]
}}
# Instances created after the PDN step (CTS and repair buffers) have their
# supply pins on no net until the deck's own post-route re-connect; PSM draws
# no current for them (MEASURED on spm: 0.153 of Jmax connected vs 1.25 with
# the clock tree on the grid). Connect them as that block does -- do-not-touch
# lifted across the connect and restored -- and count what is still floating.
proc _vibeic_pes_connect {{}} {{
  set _dnt {{}}
  foreach _i [[ord::get_db_block] getInsts] {{
    if {{[$_i isDoNotTouch]}} {{ lappend _dnt $_i; $_i setDoNotTouch false }}
  }}
  set _rc [catch {{global_connect}} _e]
  foreach _i $_dnt {{ $_i setDoNotTouch true }}
  if {{$_rc}} {{ error "PDN_EM_PRESWEEP_CONNECT_FAILED: $_e" }}
  set _n 0
  foreach _i [[ord::get_db_block] getInsts] {{
    foreach _t [$_i getITerms] {{
      if {{[[$_t getMTerm] getSigType] ni {{POWER GROUND}}}} {{ continue }}
      if {{[$_t getNet] eq "NULL"}} {{ incr _n }}
    }}
  }}
  return $_n
}}
proc _vibeic_pes_measure {{k vsrc_opt}} {{
  global _pes_dir
  set _pes_cd $_pes_dir/c$k
  file mkdir $_pes_cd
  set _f [open $_pes_cd/pg_on_no_net.txt w]; puts $_f [_vibeic_pes_connect]; close $_f
{geom}
  write_def $_pes_cd/cand.def
  set _pf [open $_pes_cd/power.rpt w]
  puts $_pf [report_power{corner_opt}]
  close $_pf
{psm_x}  set _vibeic_psm_rc [catch {{
  foreach _n {{{net_list}}} {{
    set _vs [expr {{[dict exists $vsrc_opt $_n] ? [list -vsrc [dict get $vsrc_opt $_n]] : {{}}}}]
    analyze_power_grid -net $_n{corner_opt} -enable_em -em_outfile $_pes_cd/em_segments_$_n.csv -voltage_file $_pes_cd/voltage_$_n.txt {{*}}$_vs
    if {{[catch {{check_current_density -net $_n{corner_opt} -em_limits_file $_pes_dir/em_limits.txt -em_report $_pes_cd/cd_$_n.csv -allow_reuse {{*}}$_vs}} _e]}} {{
      set _f [open $_pes_cd/cd_$_n.err w]; puts $_f $_e; close $_f
    }}
  }}
  }} _vibeic_psm_e _vibeic_psm_o]
{psm_r}  if {{$_vibeic_psm_rc}} {{ return -options $_vibeic_psm_o $_vibeic_psm_e }}
  set _f [open $_pes_cd/MEASURED w]; puts $_f $k; close $_f
}}
set _pes_k 0
set _pes_have 0
if {{[catch {{
  if {{[auto_execok {python}] eq ""}} {{ error "PDN_EM_PRESWEEP_NO_PYTHON: {python} is not on PATH in this session" }}
  estimate_parasitics -placement
{volts}  # Source model: the declared supply pads' BTerms (T101 rule).
  set _pes_vsrc [dict create]
  set _pes_model "psm_default_bterms_undeclared_pads"
  set _pes_pads {{{pads}}}
  if {{[llength $_pes_pads]}} {{
    set _pes_model "declared_pads_bterm_shapes"
    set _pes_u [[[ord::get_db] getTech] getDbUnitsPerMicron]
    foreach _n {{{net_list}}} {{
      set _rows {{}}; set _outside 0
      foreach _t [[[ord::get_db_block] findNet $_n] getBTerms] {{
        foreach _p [$_t getBPins] {{
          foreach _b [$_p getBoxes] {{
            set _in 0
            foreach _pn $_pes_pads {{
              set _i [[ord::get_db_block] findInst $_pn]
              if {{$_i eq "NULL"}} {{ continue }}
              set _bb [$_i getBBox]
              if {{[$_b xMin] >= [$_bb xMin] && [$_b yMin] >= [$_bb yMin] && [$_b xMax] <= [$_bb xMax] && [$_b yMax] <= [$_bb yMax]}} {{ set _in 1; break }}
            }}
            if {{!$_in}} {{ incr _outside; continue }}
            set _sz [expr {{min([$_b xMax]-[$_b xMin], [$_b yMax]-[$_b yMin]) / double($_pes_u)}}]
            lappend _rows [format "%.4f,%.4f,%.4f,%s" [expr {{([$_b xMin]+[$_b xMax])/2.0/$_pes_u}}] [expr {{([$_b yMin]+[$_b yMax])/2.0/$_pes_u}}] $_sz [dict get {{{" ".join(f"{n} {v:g}" for n, v in nets.items())}}} $_n]]
          }}
        }}
      }}
      if {{![llength $_rows]}} {{ error "PDN_EM_PRESWEEP_NET_UNSOURCED: $_n has no BTerm on a declared supply pad" }}
      if {{$_outside}} {{
        set _pes_model "declared_pads_vsrc"
        set _f [open $_pes_dir/$_n.vsrc w]; puts $_f [join $_rows "\\n"]; close $_f
        dict set _pes_vsrc $_n $_pes_dir/$_n.vsrc
      }}
    }}
  }}
  if {{$_pes_model eq "psm_default_bterms_undeclared_pads"}} {{
{psm_x}    if {{[llength $_vibeic_psm_props]}} {{ set _pes_model "psm_generated_bumps_promoted_pins_excluded" }}
{psm_r}  }}
  set _f [open $_pes_dir/source_model.txt w]; puts $_f $_pes_model; close $_f
  while 1 {{
    if {{$_pes_k ne "0"}} {{
      if {{[catch {{_vibeic_pes_build $_pes_k}} _be]}} {{
        file mkdir $_pes_dir/c$_pes_k
        set _f [open $_pes_dir/c$_pes_k/BUILD_FAILED w]; puts $_f $_be; close $_f
      }} else {{
        set _pes_have $_pes_k
        _vibeic_pes_measure $_pes_k $_pes_vsrc
      }}
    }} else {{
      _vibeic_pes_measure 0 $_pes_vsrc
    }}
    lassign [exec {python} $_pes_dir/lib/_ppa/pdn_em_presweep.py next $_pes_dir] _pes_op _pes_next
    if {{$_pes_op eq "EVAL"}} {{ set _pes_k $_pes_next; continue }}
    break
  }}
  if {{$_pes_next ne $_pes_have}} {{ _vibeic_pes_build $_pes_next; set _pes_have $_pes_next }}
  puts "PDN_EM_PRESWEEP_CHOSEN: candidate $_pes_next (source model $_pes_model; record $_pes_dir/{RECORD_FILE})"
}} _pes_err]}} {{
  puts "PDN_EM_PRESWEEP_NONFATAL: $_pes_err"
  if {{$_pes_have ne "0"}} {{
    if {{[catch {{_vibeic_pes_build 0}} _pes_rb]}} {{ error "PDN_EM_PRESWEEP_RESTORE_FAILED: $_pes_rb" }}
    puts "PDN_EM_PRESWEEP_RESTORED: the flow's own grid (candidate 0) was rebuilt"
  }}
}}
'''


# --------------------------------------------------------------------------
# judging a candidate (runs in the session's python, and on the host)
# --------------------------------------------------------------------------
def _voltage_extreme(path: Path, nominal: float) -> Optional[float]:
    """Worst |V - nominal| over PSM's -voltage_file node rows."""
    worst: Optional[float] = None
    try:
        with path.open(errors="replace") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                try:
                    v = float(row[-1])
                except ValueError:
                    continue
                d = abs(v - nominal)
                worst = d if worst is None or d > worst else worst
    except OSError:
        return None
    return worst


def _pdn_metal(geometry: Path) -> Dict[str, float]:
    area: Dict[str, float] = {}
    try:
        with geometry.open(errors="replace") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if row.get("source") != "special_wire":
                    continue
                a = (float(row["x1_um"]) - float(row["x0_um"])) * (float(row["y1_um"]) - float(row["y0_um"]))
                area[row["layer"]] = area.get(row["layer"], 0.0) + a
    except (OSError, KeyError, ValueError):
        return {}
    return {k: round(v, 3) for k, v in sorted(area.items())}


def judge(cand_dir: Path, tech_lef: Path, nets: Mapping[str, float], margin: float) -> Dict[str, Any]:
    """The Step-25 gate's own instrument on one measured candidate, run at the
    CLEARING bar (1 - (1 - margin)^2).

    Why not at the gate's margin: the gate judges a segment at the layer's
    narrowest drawn PG width first and re-judges it at the width of the wire
    that covers it only if that bound makes it an offender. A segment under
    the bar keeps its bound, so the gate's reported worst utilisation of a
    PASSING grid is a ceiling, not a measurement -- MEASURED on spm, 3.2 um
    straps read 0.871 at margin 0.10 and 0.803 once refined. Refining every
    segment above the clearing bar makes the worst utilisation exact wherever
    it matters to either bar; `passes` (below 1 - margin) and `clears` (below
    (1 - margin)^2) are both read from it."""
    bar = 1 - (1 - margin) ** 2
    if (cand_dir / "BUILD_FAILED").is_file():
        return {"verdict": "BUILD_FAILED",
                "reason": (cand_dir / "BUILD_FAILED").read_text(errors="replace").strip()}
    if not (cand_dir / "MEASURED").is_file():
        return {"verdict": "NOT_MEASURED", "reason": "the session wrote no MEASURED marker"}
    try:
        floating = int((cand_dir / "pg_on_no_net.txt").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        floating = None
    if floating != 0:
        # PSM draws no current for an instance whose supply pin is on no net;
        # a grid judged without them is judged on part of the design.
        return {"verdict": "NOT_MEASURED",
                "reason": (f"{floating} supply terminal(s) on no net when PSM solved"
                           if floating is not None else
                           "the session recorded no supply-connection count")}
    d = cand_dir / "cand.def"
    widths = _emcd._def_pg_widths_of(d)
    out: Dict[str, Any] = {"nets": {}, "tool_ab": {}, "ir_worst_v": {}}
    verdicts = []
    for net, volts in nets.items():
        v, rep = _emcd.evaluate(cand_dir / f"em_segments_{net}.csv", None, tech_lef, bar,
                                _emcd._DEFAULT_BLACKS_N, net, 5, def_widths=widths or None,
                                def_path=d, pg_geometry_path=cand_dir / "em_pg_geometry.tsv")
        s = rep.get("summary") or {}
        out["nets"][net] = {
            "verdict": v, "worst_utilization": s.get("worst_utilization"),
            "per_layer": {k: x.get("max_utilization") for k, x in (s.get("per_layer") or {}).items()},
            "segments_screened": s.get("segments_screened"),
            "segments_unscreened": s.get("segments_unscreened"),
            "offender_count": rep.get("offender_count", 0)}
        verdicts.append(v)
        tool: Dict[str, float] = {}
        cd = cand_dir / f"cd_{net}.csv"
        if cd.is_file():
            with cd.open(errors="replace") as fh:
                for r in csv.DictReader(fh):
                    try:
                        tool[r["Layer"]] = max(tool.get(r["Layer"], 0.0), float(r["Ratio"]))
                    except (KeyError, ValueError):
                        continue
        out["tool_ab"][net] = ({k: round(x, 4) for k, x in sorted(tool.items())} if tool
                               else "NOT_MEASURED")
        out["ir_worst_v"][net] = _voltage_extreme(cand_dir / f"voltage_{net}.txt", volts)
    utils = [n["worst_utilization"] for n in out["nets"].values()
             if isinstance(n.get("worst_utilization"), (int, float))]
    out["worst_utilization"] = max(utils) if utils else None
    measured = bool(verdicts) and all(v in ("PASS", "FAIL") for v in verdicts)
    out["verdict"] = ("NOT_MEASURED" if not measured or out["worst_utilization"] is None
                      else "PASS" if out["worst_utilization"] < 1 - margin else "FAIL")
    out["judged_at"] = {"refine_above": round(1 - bar, 6), "gate_bar": round(1 - margin, 6)}
    out["pdn_metal_um2"] = _pdn_metal(cand_dir / "em_pg_geometry.tsv")
    return out


def _offending_layers(result: Mapping[str, Any], margin: float) -> List[str]:
    bad = set()
    for n in (result.get("nets") or {}).values():
        for layer, u in (n.get("per_layer") or {}).items():
            if isinstance(u, (int, float)) and u >= 1 - margin:
                bad.add(layer)
    return sorted(bad)


def _worst_layer(result: Mapping[str, Any]) -> Optional[str]:
    rows = [(u, layer) for n in (result.get("nets") or {}).values()
            for layer, u in (n.get("per_layer") or {}).items() if isinstance(u, (int, float))]
    return max(rows)[1] if rows else None


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.atomic_mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def next_action(sweep: Path) -> Tuple[str, str]:
    """("EVAL", id) for the next candidate to measure, or ("DONE", id) for
    the one to keep. Re-judges every measured candidate from its files and
    rewrites the record each call, so the record is the search's state.

    TWO BARS. `passes` is the Step-25 gate itself: worst utilisation below
    1 - margin. `clears` applies the gate's guardband once more, to this
    estimate: worst utilisation below (1 - margin)^2. The routed layout gains
    wire load and repair cells after this measurement -- MEASURED on spm, the
    gate's worst utilisation grew 1.304 -> 1.438 (VDD, x1.103) and 1.175 ->
    1.295 (VSS, x1.102) from this pre-route basis to the routed layout with
    its SPEF, inside the 1/(1 - margin) = x1.111 the second guardband allows.
    (The runner's measured-basis factor, 2.0, is for widths derived from one
    peak current by arithmetic; on spm no candidate of the lattice reaches
    it -- best 0.871 -- because a full solve shows current following the wider
    strap.) The cheapest candidate that CLEARS is chosen; if none does within
    the budget, the passing candidate with the most headroom; if none passes,
    the lowest utilisation.

    WHICH CANDIDATES. Only those that change the layer carrying the flow grid's
    worst utilisation, and change nothing but layers short of the clearing bar:
    a strap that already clears is not the one to widen."""
    lat = json.loads((sweep / LATTICE_FILE).read_text())
    margin = float(lat["margin"])
    safety = 1.0 / (1.0 - margin)
    nets = {str(k): float(v) for k, v in lat["nets"].items()}
    tlef = Path(lat["tech_lef"])
    cands = {c["id"]: c for c in lat["candidates"]}
    order = [c["id"] for c in lat["candidates"]]
    results: Dict[str, Any] = {}
    for cid in order:
        cd = sweep / f"c{cid}"
        if cd.is_dir():
            results[cid] = judge(cd, tlef, nets, margin)

    def util(cid: str) -> Optional[float]:
        u = results.get(cid, {}).get("worst_utilization")
        return u if isinstance(u, (int, float)) else None

    def passes(cid: str) -> bool:
        return results.get(cid, {}).get("verdict") == "PASS"

    def clears(cid: str) -> bool:
        return passes(cid) and util(cid) is not None and util(cid) * safety < 1 - margin

    record: Dict[str, Any] = {"schema": SCHEMA, "margin": margin, "estimate_guardband": safety, "nets": nets,
                              "source_model": ((sweep / "source_model.txt").read_text().strip()
                                               if (sweep / "source_model.txt").is_file() else None),
                              "evaluated": results, "max_evaluations": MAX_EVALUATIONS}
    for cid, r in results.items():
        r["passes_gate"], r["clears_with_guardband"] = passes(cid), clears(cid)
    decision: Tuple[str, str]
    base = results.get("0")
    if base is None or util("0") is None:
        record.update(verdict="NOT_MEASURED", chosen="0",
                      reason="the flow's own grid was not measured; nothing is changed")
        decision = ("DONE", "0")
    elif clears("0"):
        record.update(verdict="PASS", chosen="0",
                      reason="the flow's own grid clears the Step-25 gate with the estimate guardband")
        decision = ("DONE", "0")
    else:
        bad = _offending_layers(base, 1 - (1 - margin) / safety)
        strap_bad = [l for l in bad if l in lat["layers"]]
        worst = _worst_layer(base)
        eligible = [cid for cid in order if cid != "0" and cands[cid]["changed"]
                    and (not strap_bad or set(cands[cid]["changed"]) <= set(strap_bad))
                    and (worst not in lat["layers"] or worst in cands[cid]["changed"])]
        record["worst_layer"] = worst
        record["layers_short_of_headroom"] = bad
        record["eligible"] = eligible
        spent = len([cid for cid in results if cid != "0"])
        pending = [cid for cid in eligible if cid not in results]
        clearing = [cid for cid in eligible if clears(cid)]
        if clearing:
            # Ascending planned cost, every cheaper eligible candidate measured:
            # the first that clears is the cheapest that clears.
            record.update(verdict="PASS", chosen=clearing[0],
                          reason="cheapest candidate that clears the Step-25 gate with the estimate guardband")
            decision = ("DONE", clearing[0])
        elif pending and spent < MAX_EVALUATIONS:
            decision = ("EVAL", pending[0])
            record.update(verdict="SEARCHING", chosen=None)
        else:
            measured = [cid for cid in results if util(cid) is not None]
            passing = [cid for cid in measured if passes(cid)]
            pool = passing or measured
            best = min(pool, key=lambda cid: (util(cid), order.index(cid)))
            record.update(
                verdict="PASS_WITHOUT_HEADROOM" if passing else "INFEASIBLE", chosen=best,
                reason=(f"no candidate within {len(eligible)} eligible / {MAX_EVALUATIONS} evaluations "
                        "clears with the estimate guardband; kept the "
                        + ("passing candidate with the most headroom" if passing
                           else "lowest worst utilisation") +
                        "; the Step-25 gate judges the routed grid"),
                next_axis=("supply pad count: a floorplan fact, not swept after placement "
                           "(_ppa/power.pdn_supply_entry_count_plan sizes it from measured current)"))
            decision = ("DONE", best)
    if record.get("chosen") is not None:
        record["chosen_straps"] = cands[record["chosen"]]["straps"]
    _write_json(sweep / RECORD_FILE, record)
    return decision


# --------------------------------------------------------------------------
# host side
# --------------------------------------------------------------------------
def stage(sweep: Path, *, lattice_doc: Mapping[str, Any], blocks: Mapping[str, str],
          tech_lef: Path, tech_lef_text: str, nets: Mapping[str, float], margin: float) -> None:
    """Write the lattice, one deck block per candidate, the tool's limit file
    and a copy of the judge (this module, the gate and the `_ppa` modules it
    reads) where the session can execute it."""
    import shutil
    if sweep.exists():
        shutil.rmtree(sweep)
    (sweep / "lib" / "_ppa").mkdir(parents=True)
    here = Path(__file__).resolve()
    shutil.copy2(here, sweep / "lib" / "_ppa" / here.name)
    (sweep / "lib" / "_ppa" / "__init__.py").write_text("")
    for mod in ("pareto.py", "feasibility.py"):
        shutil.copy2(here.parent / mod, sweep / "lib" / "_ppa" / mod)
    shutil.copy2(Path(_emcd.__file__).resolve(), sweep / "lib" / "em_current_density_check.py")
    for cid, text in blocks.items():
        (sweep / f"cand_{cid}.tcl").write_text(text)
    (sweep / "em_limits.txt").write_text(jmax_limits_text(tech_lef_text, margin))
    doc = dict(lattice_doc, nets=dict(nets), margin=margin, tech_lef=str(tech_lef))
    _write_json(sweep / LATTICE_FILE, doc)


def prepare(*, pnr_dir: Path, sweep_dir_c: str, plan: Mapping[str, Any], build,
            tech_lef: Path, tech_lef_c: str, tech_lef_text: str, nets: Mapping[str, float],
            corner: Optional[str], declared_pads: Sequence[str], stage_marker: str,
            margin: float = _emcd._DEFAULT_MARGIN,
            python: str = "python3") -> Tuple[str, str]:
    """(Tcl block, note). The block is empty -- and the note says why -- when
    there is nothing this sweep can size: no strap plan, no strap layer with a
    tech-LEF Jmax, or a supply net with no voltage. `build(straps)` returns the
    deck's own PDN block with those straps (`_build_pdn_tcl`)."""
    straps = [s for s in (plan.get("straps") or []) if s.get("layer")]
    if not straps:
        return "", "PDN_EM_PRESWEEP_NOT_APPLICABLE: the deck draws no strap layer"
    jmax = _emcd.parse_lef_jmax(tech_lef_text)
    if not any(str(s["layer"]).lower() in jmax for s in straps):
        return "", "PDN_EM_PRESWEEP_NOT_APPLICABLE: the tech LEF states no Jmax for any strap layer"
    if not nets or any(not isinstance(v, (int, float)) for v in nets.values()):
        return "", "PDN_EM_PRESWEEP_NOT_MEASURED: a swept supply net has no declared voltage"
    doc = lattice(straps, tech_lef_text, budget=float(plan.get("routing_budget", 0.5)),
                  offset_div=float(plan.get("offset_div", 4.0)))
    blocks = {c["id"]: build({l: {k: o[k] for k in ("width", "pitch", "offset")}
                              for l, o in c["straps"].items()})
              for c in doc["candidates"]}
    sweep = pnr_dir / SWEEP_DIR
    stage(sweep, lattice_doc=doc, blocks=blocks, tech_lef=Path(tech_lef_c),
          tech_lef_text=tech_lef_text, nets=nets, margin=margin)
    tcl = session_tcl(sweep_dir=sweep_dir_c, python=python, nets=nets, corner=corner,
                      declared_pads=declared_pads, stage_marker=stage_marker)
    return tcl, (f"PDN_EM_PRESWEEP_STAGED: {len(doc['candidates'])} candidates over "
                 f"{', '.join(doc['layers'])}; {len(doc['refused_options'])} layer options refused")


def frontier(record: Mapping[str, Any]) -> Dict[str, Any]:
    """The measured candidates on `_ppa/pareto`: minimise PDN metal and worst
    Jmax utilisation; feasibility is the gate's verdict, applied first."""
    from _ppa import feasibility as feas, pareto
    objectives = (pareto.Objective("pdn_metal", "pdn.metal_area_um2", pareto.SENSE_MIN,
                                   {"subject": "preroute_post_cts"}),
                  pareto.Objective("em_util", "em.jmax_utilization", pareto.SENSE_MIN,
                                   {"subject": "preroute_post_cts"}))
    cands, results = [], []
    for cid, r in sorted((record.get("evaluated") or {}).items(), key=lambda x: int(x[0])):
        metal = sum((r.get("pdn_metal_um2") or {}).values())
        util = r.get("worst_utilization")
        src = {"path": f"c{cid}/em_pg_geometry.tsv", "sha256": "sha256:" + str(r.get("geometry_sha256") or "")}
        metrics = []
        for metric, value, unit in (("pdn.metal_area_um2", metal, "um2"),
                                    ("em.jmax_utilization", util, "ratio")):
            if isinstance(value, (int, float)) and r.get("geometry_sha256"):
                metrics.append({"schema": feas.METRIC_SCHEMA, "metric": metric, "status": "MEASURED",
                                "value": value, "unit": unit, "scope": {"subject": "preroute_post_cts"},
                                "source": src})
        cands.append({"candidate_id": cid, "metrics": metrics})
        v = r.get("verdict")
        results.append(feas.FeasibilityResult(
            cid, feas.FEASIBLE if v == "PASS" else feas.INFEASIBLE if v in ("FAIL", "BUILD_FAILED")
            else feas.UNDETERMINED, (), ()))
    return pareto.build_frontier(cands, results, objectives)


def finalize(project: Path, pnr_dir: Path) -> Optional[Dict[str, Any]]:
    """Publish the session's record with the frontier beside it. None when the
    session staged no sweep."""
    import hashlib
    sweep = pnr_dir / SWEEP_DIR
    rec_path = sweep / RECORD_FILE
    if not rec_path.is_file():
        return None
    rec = json.loads(rec_path.read_text())
    for cid, r in (rec.get("evaluated") or {}).items():
        g = sweep / f"c{cid}" / "em_pg_geometry.tsv"
        if g.is_file():
            r["geometry_sha256"] = hashlib.sha256(g.read_bytes()).hexdigest()
    lat = json.loads((sweep / LATTICE_FILE).read_text())
    rec["lattice"] = {"layers": lat["layers"], "directions": lat.get("directions"),
                      "candidates": lat["candidates"], "refused_options": lat["refused_options"],
                      "routing_budget": lat["routing_budget"]}
    rec["frontier"] = frontier(rec)
    rec["sweep_dir"] = str(sweep.relative_to(project)) if sweep.is_relative_to(project) else str(sweep)
    chosen = rec.get("chosen")
    front = rec["frontier"].get("frontier") or []
    if rec.get("verdict") == "PASS" and chosen not in ("0", None) and chosen not in front:
        rec["frontier_disagrees"] = (f"chosen candidate {chosen} (cheapest by planned tracks) is "
                                     f"not on the measured frontier {front}")
    out = project / REPORT_REL
    _write_json(out, rec)
    return rec


def librelane_pdn_config(project: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """The straps this design's own pre-route EM search chose, as the LibreLane
    variables `OpenROAD.GeneratePDN` reads ({} when there is no usable record).
    The strap layers are named with them, so a width is never applied to a
    layer it was not measured on. Offsets stay LibreLane's: they were not the
    swept quantity."""
    path = project / REPORT_REL
    try:
        rec = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}, None
    straps = rec.get("chosen_straps") or {}
    dirs = (rec.get("lattice") or {}).get("directions") or {}
    if rec.get("verdict") not in ("PASS", "PASS_WITHOUT_HEADROOM") or not straps:
        return {}, None
    by_dir: Dict[str, List[str]] = {}
    for layer in straps:
        by_dir.setdefault(str(dirs.get(layer) or ""), []).append(layer)
    if sorted(by_dir) != ["HORIZONTAL", "VERTICAL"] or any(len(v) != 1 for v in by_dir.values()):
        return {}, None
    out: Dict[str, Any] = {}
    for d, key in (("VERTICAL", "V"), ("HORIZONTAL", "H")):
        layer = by_dir[d][0]
        out[f"PDN_{'VERTICAL' if key == 'V' else 'HORIZONTAL'}_LAYER"] = layer
        out[f"PDN_{key}WIDTH"] = straps[layer]["width"]
        out[f"PDN_{key}PITCH"] = straps[layer]["pitch"]
    return out, (f"{REPORT_REL}.chosen_straps (candidate {rec.get('chosen')}, "
                 f"{rec.get('verdict')}: this design's pre-route PSM EM search)")


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "next":
        print("usage: pdn_em_presweep.py next <sweep_dir>", file=sys.stderr)
        return 2
    op, cid = next_action(Path(args[1]))
    print(f"{op} {cid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
