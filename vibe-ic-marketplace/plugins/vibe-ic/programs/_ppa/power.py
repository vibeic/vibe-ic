#!/usr/bin/env python3
"""_ppa/power.py — the power split, and the thing that makes a power number
mean anything: WHERE THE ACTIVITY CAME FROM.

Spec §7.2. Owns exactly one question: given a power artefact, what are the
internal / switching / leakage / total figures, and on what ACTIVITY BASIS were
they computed. Nothing here decides a verdict against a threshold — that is the
gate's job (`power_total_vs_budget_check`), and keeping the two apart is why
adding a second power engine will not change a single rule.

WHY THE BASIS IS NOT A FOOTNOTE
===============================
A vectorless estimate and a VCD-driven measurement are both "total power" and
they are not the same number. `PPA_INTERFACES.md` §2 says so in one line —
"Vectorless power and VCD power are different metrics" — and the consequence is
the whole of this module: two power records whose activity basis differs are
NOT COMPARABLE, and a comparison across them is UNDETERMINED, never a winner.
The failure mode this prevents is the cheapest possible win: run the candidate
vectorless, run the baseline against a VCD, and report an improvement that is
an artefact of the activity model.

AND A DECLARED BASIS IS A CLAIM, NOT EVIDENCE
=============================================
MEASURED on the published corpus 2026-08-21, all 17 runs carrying a power
report:

    POWER_ANALYSIS_MODE absent           6
    POWER_ANALYSIS_MODE: vectorless_sdc  3
    POWER_ANALYSIS_MODE: vector_vcd      8

and every one of those 8 is contradicted by its OWN transcript — 5 carry
``READ_VCD_FAIL: ...`` from the `catch` around `read_power_activities`, and 3
carry OpenSTA's own count, ``Annotated 0 pin activities.``. Zero published power
numbers in this repository are vector-driven; eight of them say they are. The
label is written by the runner from the mere EXISTENCE of a `.vcd` file, before
the read is attempted, and the read failure is caught and printed rather than
raised — so `vector_vcd` in these files records an intention.

Therefore this module never takes the declared mode as the answer. It reads the
mode, then reads the evidence that would corroborate or falsify it, and returns
a basis with the corroboration state attached. A vector basis contradicted by
its own transcript is `CONTRADICTED`, the record is `INVALID` per §2, and an
INVALID record may not enter a numeric comparison. That is a REFUSAL, not a
reclassification: this module will not silently re-label such a run
"vectorless", because what the tool actually did with zero annotated activities
is a claim about OpenSTA's fallback that this repository has not measured.

WHAT AN ABSENT BASIS IS
=======================
`UNSTATED`, and UNSTATED is not comparable with anything — INCLUDING another
UNSTATED. Two numbers whose activity models are both unknown are not known to
share an activity model. Treating "unknown == unknown" as a match is exactly
the numeric-sentinel defect §2 forbids, one level up: it turns "not measured"
into a value that participates in arithmetic.

IR DROP IS NOT TOTAL POWER
==========================
Nothing here reads an IR-drop artefact. Peak-current and voltage-droop belong
to power integrity (`ir_drop_*`, `em_peak_current_authority_check`) and answer
a different question; a per-net total power stated by an IR engine on a
different netlist view is a different metric with a different scope and must not
be folded into this axis. On the corpus the two already differ by 4.3x at
baseline, so any tolerance wide enough to reconcile them would be a ruler
fitted to the data.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import sys
from pathlib import Path

from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

import _path_layout as _pl

from . import canonical_json as _cj
# The vocabulary of "nobody established this" lives in ONE place, with the
# validator that refuses it. A second copy here is a second copy of the
# question, which is the defect this lane exists to close.
from . import metrics as _metrics
from .backends import opensta as _opensta

__all__ = [
    "SCHEMA_METRIC", "PARSER",
    "BASIS_VCD", "BASIS_SAIF", "BASIS_VECTORLESS", "BASIS_UNSTATED",
    "BASIS_CONTRADICTED", "KNOWN_BASES",
    "CORROBORATED", "UNCORROBORATED", "CONTRADICTED", "NO_CORROBORATION_NEEDED",
    "STATUS_MEASURED", "STATUS_NOT_MEASURED", "STATUS_INVALID", "STATUS_DERIVED",
    "CATEGORIES", "TOTAL_GROUP", "PRIMARY_SCOPE_KEY",
    "activity_provenance", "parse_power_report", "read_power_report",
    "metric_records", "total_record", "comparable", "compare_total_power",
    "V_A_LOWER", "V_B_LOWER", "V_EQUAL", "V_UNDETERMINED",
    "pdn_ring_dimensions", "pdn_strap_min_core_span_um", "pdn_strap_core_misfit",
    "POWER_VERDICT_MEASURED", "signoff_record", "emit_signoff_record",
    "retire_signoff_record",
    "verdict_is_backed_by_a_number",
    "_step33_current_power_due", "_adopt_current_power_report",
]


def pdn_ring_dimensions(cfg: Dict[str, Any]
                        ) -> Tuple[float, float, List[float], List[float], float]:
    """Validate the shared recipe and measure its two-rail footprint.

    Floorplanning must reserve the same widths, spacing, core offset and
    pad clearance that the later PDN emitter will require.
    """
    layers = cfg.get("layers") or []
    widths = cfg.get("widths") or []
    spacings = cfg.get("spacings") or []
    pad_layers = cfg.get("connect_to_pad_layers") or []
    connects = cfg.get("connects") or []
    try:
        offset = float(cfg.get("core_offset_um"))
        clearance = float(cfg.get("min_clearance_um"))
        widths_f = [float(v) for v in widths]
        spacings_f = [float(v) for v in spacings]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid pdn_ring numeric config: {exc}") from exc
    names = list(layers) + list(pad_layers) + [n for pair in connects
                                               for n in (pair or [])]
    if (len(layers) != 2 or len(widths_f) != 2 or len(spacings_f) != 2
            or not pad_layers or offset <= 0 or clearance < 0
            or any(v <= 0 for v in widths_f + spacings_f)
            or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", str(n))
                   for n in names)
            or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                   for pair in connects)):
        raise ValueError("invalid pdn_ring shape or layer identifier")

    footprint = max(2.0 * widths_f[i] + spacings_f[i] for i in range(2))
    return offset, clearance, widths_f, spacings_f, footprint


def pdn_strap_min_core_span_um(stripes: Sequence[Mapping[str, Any]], *,
                               nets: int = 2,
                               site_dims_um: Optional[Tuple[float, float]] = None
                               ) -> Tuple[Optional[int], str]:
    """The smallest CORE side (um) on which every strap group of `stripes` fits.

    pdngen lays one group per period: `nets` straps of `width` at the default
    spacing `pitch/nets - width`, so a group spans `width + (nets-1)*pitch/nets`
    and must start at `offset`. It refuses the grid when the core's extent is
    shorter than `offset + group`. MEASURED in image 0.3.83 on gf180mcuD
    (Metal4 1.6/153.6/16.32, Metal5 1.6/153.18/16.65; 2 nets): a 94.64 um
    row extent was refused for Metal4 (needs 94.72), 94.08 for Metal5 (needs
    94.84), and a 99.68 x 98.0 core built the grid.

    The extent pdngen measures is the core after rows snap to the site grid,
    which is up to one site width / row height short of the rectangle asked
    for; so each axis is rounded UP to whole sites/rows and one more step is
    added. Unknown site: +5 % instead. Returns `(None, why)` with no strap.
    """
    need = 0.0
    worst = ""
    n = max(int(nets), 1)
    for st in stripes or []:
        try:
            w = float(st.get("width"))
            p = float(st.get("pitch"))
            off = float(st.get("offset") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if not (w > 0 and p > 0):
            continue
        span = off + w + (n - 1) * p / n
        if span > need:
            need, worst = span, (f"{st.get('layer')} offset {off:g} + width {w:g}"
                                 f" + {n - 1}x pitch {p:g}/{n} = {span:.2f} um")
    if need <= 0:
        return None, "no strap with a width and pitch in the plan"
    steps = [s for s in (site_dims_um or ()) if s and s > 0]
    if steps:
        side = max(math.ceil(need / s) * s + s for s in steps)
        snap = (f"rounded up to whole site/row steps {'/'.join(f'{s:g}' for s in steps)} um"
                f" plus one step for row snapping")
    else:
        side = need * 1.05
        snap = "+5 % for row snapping (site size unknown)"
    return int(math.ceil(side - 1e-9)), f"{worst}; {snap}"


def pdn_strap_core_misfit(stripes: Sequence[Mapping[str, Any]],
                          core_w: float, core_h: float, *,
                          nets: int = 2,
                          site_dims_um: Optional[Tuple[float, float]] = None,
                          directions: Optional[Mapping[str, str]] = None
                          ) -> List[Dict[str, Any]]:
    """The strap groups that do NOT fit a GIVEN core, judged the way pdngen
    judges them. `[]` means every group fits.

    `pdn_strap_min_core_span_um` is an UPPER bound, right for GROWING a core
    the flow owns; it is not a "below this pdngen fails" threshold for a core
    somebody pinned. This is that threshold, with no padding:

      * each stripe needs `offset + width + (nets-1) * pitch/nets` of core
        extent, on ONE axis: a VERTICAL layer against the core WIDTH, a
        HORIZONTAL layer against the core HEIGHT;
      * the extent pdngen measures is the core snapped to whole sites (x) and
        whole rows (y): `floor(core / step) * step`.

    CALIBRATED in image 0.3.83 on gf180mcuD with the registry straps (Metal4
    VERTICAL 1.6/153.6/16.32, Metal5 HORIZONTAL 1.6/153.18/16.65; site
    0.56 x 3.92): this reproduces all eight measured outcomes -- cores of
    65/80/90/94/95 um refused on Metal4, 96/97 um refused on Metal5, 100 um
    (99.68 x 98.0) built.

    A layer whose DIRECTION is unknown is judged against the LARGER extent, so
    an unknown can only make this refuse less, never more. An unknown site
    leaves the extent unsnapped for the same reason.
    """
    n = max(int(nets), 1)
    sw, sh = (site_dims_um if site_dims_um and all(
        s and s > 0 for s in site_dims_um) else (None, None))
    ext_w = math.floor(core_w / sw + 1e-9) * sw if sw else float(core_w)
    ext_h = math.floor(core_h / sh + 1e-9) * sh if sh else float(core_h)
    dirs = {str(k).lower(): str(v).upper() for k, v in (directions or {}).items()}
    out: List[Dict[str, Any]] = []
    for st in stripes or []:
        try:
            w = float(st.get("width"))
            p = float(st.get("pitch"))
            off = float(st.get("offset") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if not (w > 0 and p > 0):
            continue
        need = off + w + (n - 1) * p / n
        d = dirs.get(str(st.get("layer")).lower(), "")
        if d == "VERTICAL":
            axis, have = "width", ext_w
        elif d == "HORIZONTAL":
            axis, have = "height", ext_h
        else:
            axis, have = "larger extent (direction unknown)", max(ext_w, ext_h)
        if have + 1e-9 < need:
            out.append({"layer": st.get("layer"), "direction": d or None,
                        "axis": axis, "need_um": round(need, 4),
                        "have_um": round(have, 4)})
    return out


def pdn_rail_pitch_plan(segments: Sequence[Mapping[str, Any]], *,
                        rail_layer: str, rail_width_um: float,
                        jmax_A_per_um: float, margin: float,
                        old_pitch_um: float, grid_um: float
                        ) -> Optional[Dict[str, Any]]:
    """Conservative linear-span plan for a fixed-width follow-pin rail.

    The largest measured current on the rail is the starting point.  With
    unchanged distributed load per unit length, current is proportional to
    the distance to the next perpendicular strap.  Thus I_new/I_old =
    pitch_new/pitch_old.  This is a prediction, never an EM verdict; the
    rebuilt grid still requires a fresh PSM and final DEF check.
    """
    if not (rail_width_um > 0 and jmax_A_per_um > 0 and old_pitch_um > 0
            and grid_um > 0 and 0 < margin < 1):
        return None
    currents = [float(s.get("current_A", 0)) for s in segments
                if str(s.get("layer0", "")).lower() == rail_layer.lower()
                and str(s.get("layer1", "")).lower() == rail_layer.lower()
                and float(s.get("current_A", 0)) > 0]
    if not currents:
        return None
    peak = max(currents)
    limit = rail_width_um * jmax_A_per_um * (1 - margin)
    if peak < limit:
        return None
    bound = old_pitch_um * limit / peak
    # Stay strictly below the gate's >= threshold; two-grid pitch also keeps
    # the centred stripe and its offset representable by pdngen.
    quantum = 2 * grid_um
    pitch = math.floor(bound / quantum + 1e-9) * quantum
    if pitch >= bound - 1e-12:
        pitch -= quantum
    if pitch <= 0:
        return {"code": "PDN_EM_RAIL_PITCH_UNREACHABLE",
                "old_pitch_um": old_pitch_um, "bound_pitch_um": bound,
                "rail_current_A": peak, "rail_limit_A": limit}
    return {"applied": "DENSER_STRAPS", "rail_layer": rail_layer,
            "old_pitch_um": old_pitch_um, "new_pitch_um": round(pitch, 6),
            "rail_current_A": peak, "rail_limit_A": limit,
            "rail_j_before_A_per_um": peak / rail_width_um,
            "rail_j_predicted_after_A_per_um": (
                peak * pitch / old_pitch_um / rail_width_um),
            "jmax_A_per_um": jmax_A_per_um, "margin": margin,
            "model": "I_new = I_measured * new_pitch / old_pitch; "
                     "fresh PSM must verify changed load distribution"}


def pdn_strap_segment_peak(def_text: str,
                           segments: Sequence[Mapping[str, Any]],
                           layer: str) -> Optional[float]:
    """Largest measured edge covered by a same-layer DEF STRIPE.

    Ring and pad-entry peaks must not be used as a per-strap current. The CSV
    has no structure field, so the layout's own SPECIALNETS supply that fact.
    """
    dbm = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    snet = re.search(r"SPECIALNETS\b(.*?)END\s+SPECIALNETS", def_text, re.S)
    if not dbm or not snet or int(dbm.group(1)) <= 0:
        return None
    dbu = int(dbm.group(1))
    boxes = []
    pat = re.compile(
        r"(?:ROUTED|NEW)\s+(\S+)\s+(\d+)\s+\+\s+SHAPE\s+STRIPE\s+"
        r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+"
        r"\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    for match in pat.finditer(snet.group(1)):
        lay, raw_w, *raw_xy = match.groups()
        if lay.lower() != layer.lower() or int(raw_w) <= 0:
            continue
        x0, y0, x1, y1 = (int(v) / dbu for v in raw_xy)
        half = int(raw_w) / dbu / 2
        boxes.append((min(x0, x1) - half, min(y0, y1) - half,
                      max(x0, x1) + half, max(y0, y1) + half))
    peaks = []
    for seg in segments:
        if (str(seg.get("layer0", "")).lower() != layer.lower()
                or str(seg.get("layer1", "")).lower() != layer.lower()):
            continue
        pts = seg.get("points_um")
        if not pts or any(v is None for pt in pts for v in pt):
            continue
        if any(all(lx - 1e-6 <= x <= hx + 1e-6 and
                   ly - 1e-6 <= y <= hy + 1e-6 for x, y in pts)
               for lx, ly, hx, hy in boxes):
            peaks.append(float(seg["current_A"]))
    return max(peaks) if peaks else None


def pdn_def_stripe_pitch(def_text: str, layer: str) -> Optional[float]:
    """Per-net stripe pitch in the measured DEF, excluding the other rail.

    A newer Tcl can coexist with an older final DEF after a failed PnR tail.
    The current distribution belongs to the DEF, so its pitch is the only
    valid denominator for predicting the next distribution.
    """
    dbm = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    snet = re.search(r"SPECIALNETS\b(.*?)END\s+SPECIALNETS", def_text, re.S)
    if not dbm or not snet or int(dbm.group(1)) <= 0:
        return None
    dbu = int(dbm.group(1))
    pitches = []
    pat = re.compile(
        r"(?:ROUTED|NEW)\s+(\S+)\s+\d+\s+\+\s+SHAPE\s+STRIPE\s+"
        r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+"
        r"\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    for statement in snet.group(1).split(";"):
        axes = {"x": set(), "y": set()}
        for match in pat.finditer(statement):
            lay, x0, y0, x1, y1 = match.groups()
            if lay.lower() != layer.lower():
                continue
            x0, y0, x1, y1 = map(int, (x0, y0, x1, y1))
            if x0 == x1 and y0 != y1:
                axes["x"].add(x0)
            elif y0 == y1 and x0 != x1:
                axes["y"].add(y0)
        for coords in axes.values():
            vals = sorted(coords)
            if len(vals) >= 2:
                diffs = [(b - a) / dbu for a, b in zip(vals, vals[1:])
                         if b > a]
                if diffs:
                    pitches.append(sorted(diffs)[len(diffs) // 2])
    return max(pitches) if pitches else None


def pdn_ring_segment_peaks(def_text: str,
                           segments: Sequence[Mapping[str, Any]]
                           ) -> Dict[str, float]:
    """Peak PSM current on a width-bearing DEF RING rectangle, per layer."""
    dbm = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", def_text)
    snet = re.search(r"SPECIALNETS\b(.*?)END\s+SPECIALNETS",
                     def_text, re.S)
    if not dbm or not snet or int(dbm.group(1)) <= 0:
        return {}
    dbu = int(dbm.group(1))
    boxes: Dict[str, List[Tuple[float, float, float, float]]] = {}
    pat = re.compile(
        r"(?:ROUTED|NEW)\s+(\S+)\s+(\d+)\s+\+\s+SHAPE\s+RING\s+"
        r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+"
        r"\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    for m in pat.finditer(snet.group(1)):
        layer, raw_width, *xy = m.groups()
        width = int(raw_width) / dbu
        if width <= 0:
            continue
        x0, y0, x1, y1 = [int(v) / dbu for v in xy]
        half = width / 2
        boxes.setdefault(layer.lower(), []).append((
            min(x0, x1) - half, min(y0, y1) - half,
            max(x0, x1) + half, max(y0, y1) + half))
    peaks: Dict[str, float] = {}
    for s in segments:
        layer = str(s.get("layer0", "")).lower()
        if layer != str(s.get("layer1", "")).lower():
            continue
        pts = s.get("points_um")
        if not pts or any(v is None for pt in pts for v in pt):
            continue
        for lx, ly, hx, hy in boxes.get(layer, []):
            if all(lx - 1e-6 <= x <= hx + 1e-6 and
                   ly - 1e-6 <= y <= hy + 1e-6 for x, y in pts):
                peaks[layer] = max(peaks.get(layer, 0.0),
                                   float(s.get("current_A", 0)))
                break
    return peaks


def pdn_ring_capacity_plan(cfg: Mapping[str, Any], *, gap_um: float,
                           peaks_A: Mapping[str, float],
                           jmax_A_per_um: Mapping[str, float],
                           margin: float, grid_um: float
                           ) -> Dict[str, Any]:
    """Size configured ring rails; refuse a measured gap that cannot fit.

    No undeclared stacked ring, extra rail or pad bypass is presumed legal.
    Such topology needs a proven layer, via and pad-pin plan before use.
    """
    _, clearance, widths, spacings, _ = pdn_ring_dimensions(dict(cfg))
    layers = [str(x) for x in cfg["layers"]]
    required = []
    for layer, recipe in zip(layers, widths):
        peak = float(peaks_A.get(layer.lower(), 0))
        jmax = float(jmax_A_per_um.get(layer.lower(), 0))
        if peak > 0 and jmax > 0:
            bound = peak / (jmax * (1 - margin))
            quantum = 2 * grid_um
            width = math.ceil(bound / quantum - 1e-9) * quantum
            if width <= bound + 1e-12:
                width += quantum
            required.append(max(recipe, round(width, 6)))
        else:
            required.append(recipe)
    footprint = max(2 * w + s for w, s in zip(required, spacings))
    record = {"gap_um": gap_um, "clearance_um": clearance,
              "layers": layers, "recipe_widths_um": widths,
              "required_widths_um": required, "spacings_um": spacings,
              "required_footprint_um": footprint,
              "available_footprint_um": gap_um - clearance,
              "measured_ring_peak_A": dict(peaks_A),
              "margin": margin}
    if footprint >= gap_um - clearance:
        return {**record, "code": "PDN_EM_RING_CAPACITY_UNREACHABLE",
                "reason": "measured ring EM widths and two supply rails do not fit "
                          "the measured pad-to-core gap; no additional "
                          "ring layer, rail or direct pad bypass is declared "
                          "and geometry-proven"}
    return {**record, "applied": (
        "WIDER_RING" if any(w > old for w, old in zip(required, widths))
        else "NO_CHANGE")}


def pdn_pad_entry_plan(segments: Sequence[Mapping[str, Any]], *,
                       pad_layers: Sequence[str], drawn_widths_um: Mapping[str, float],
                       jmax_A_per_um: Mapping[str, float], margin: float,
                       grid_um: float) -> List[Dict[str, Any]]:
    """Measured pad-layer current and EM width; geometry approval is separate."""
    out = []
    for name in pad_layers:
        layer = str(name).lower()
        currents = [float(s.get("current_A", 0)) for s in segments
                    if str(s.get("layer0", "")).lower() == layer
                    and str(s.get("layer1", "")).lower() == layer]
        peak = max(currents, default=0.0)
        width = float(drawn_widths_um.get(layer, 0))
        jmax = float(jmax_A_per_um.get(layer, 0))
        if not (peak > 0 and width > 0 and jmax > 0 and grid_um > 0):
            continue
        bound = peak / (jmax * (1 - margin))
        quantum = 2 * grid_um
        required = math.ceil(bound / quantum - 1e-9) * quantum
        if required <= bound + 1e-12:
            required += quantum
        out.append({"layer": name, "measured_peak_A": peak,
                    "drawn_width_um": width,
                    "required_width_um": round(required, 6),
                    "j_before_A_per_um": peak / width,
                    "jmax_A_per_um": jmax, "margin": margin,
                    "status": ("CAPACITY_NOT_PROVEN" if width < required
                               else "WIDTH_SUFFICIENT")})
    return out


def pdn_supply_entry_count_plan(*, current_A: float,
                                ring_plan: Mapping[str, Any],
                                pad_entries: Sequence[Mapping[str, Any]],
                                jmax_A_per_um: Mapping[str, float],
                                margin: float) -> Dict[str, Any]:
    """Plan paired supply entries from this layout's PSM current and LEF Jmax.

    The existing ring recipe, rather than an unbuildable proposed width, is
    the capacity of each new entry.  This is a conservative count proposal;
    only a new PSM run can establish the actual current distribution.
    """
    if not (math.isfinite(current_A) and current_A > 0
            and 0 <= margin < 1):
        raise ValueError("SUPPLY_ENTRY_CURRENT_UNMEASURED")
    capacities = []
    for layer, width in zip(ring_plan.get("layers", ()),
                            ring_plan.get("recipe_widths_um", ())):
        jmax = float(jmax_A_per_um.get(str(layer).lower(), 0))
        if jmax > 0 and float(width) > 0:
            capacities.append({"structure": "ring", "layer": str(layer),
                               "width_um": float(width),
                               "capacity_A": float(width) * jmax * (1 - margin)})
    for entry in pad_entries:
        width = float(entry.get("drawn_width_um") or 0)
        jmax = float(entry.get("jmax_A_per_um") or 0)
        if width > 0 and jmax > 0:
            capacities.append({"structure": "pad_entry",
                               "layer": str(entry["layer"]),
                               "width_um": width,
                               "capacity_A": width * jmax * (1 - margin)})
    if not capacities or not any(c["structure"] == "pad_entry" for c in capacities):
        raise ValueError("SUPPLY_ENTRY_CAPACITY_UNPROVEN")
    pad_capacity = min(c["capacity_A"] for c in capacities
                       if c["structure"] == "pad_entry")
    ring_caps = [c for c in capacities if c["structure"] == "ring"]
    ring_peaks = ring_plan.get("measured_ring_peak_A") or {}
    ring_demands = []
    for c in ring_caps:
        peak = float(ring_peaks.get(c["layer"].lower(), 0))
        if peak > 0:
            ring_demands.append({**c, "measured_peak_A": peak,
                                 "required_pairs": math.floor(peak / c["capacity_A"]) + 1})
    if ring_caps and not ring_demands:
        raise ValueError("RING_SEGMENT_CURRENT_UNMEASURED")
    # J == Jmax after guardband is an offender, so equality needs one more.
    pad_pairs = math.floor(current_A / pad_capacity) + 1
    ring_pairs = max((x["required_pairs"] for x in ring_demands), default=1)
    pairs = max(1, pad_pairs, ring_pairs)
    limiting = min(capacities, key=lambda c: c["capacity_A"])
    return {"verdict": "PLANNED", "rule": "PSM_CURRENT_OVER_ENTRY_CAPACITY",
            "current_A": current_A, "margin": margin,
            "capacities": capacities, "limiting": limiting,
            "pad_pair_floor": pad_pairs, "ring_pair_floor": ring_pairs,
            "ring_demands": ring_demands, "pair_count": pairs,
            "validation": "NEW_PSM_REQUIRED: count extrapolates measured peak sharing; final EM must remeasure every segment"}


SCHEMA_METRIC = "vibeic.ppa.metric.v1"
PARSER = "_ppa/power.py"

# ── the activity basis vocabulary ──────────────────────────────────────────
#: A vector-driven measurement whose activity came from a value-change dump.
BASIS_VCD = "VCD"
#: A vector-driven measurement whose activity came from a SAIF activity file.
BASIS_SAIF = "SAIF"
#: A vectorless estimate: activity propagated from the constraints, not observed.
BASIS_VECTORLESS = "VECTORLESS"
#: The artefact states no basis at all. NOT comparable, not even with another
#: UNSTATED — see the module docstring.
BASIS_UNSTATED = "UNSTATED"
#: The artefact states a basis its own transcript falsifies.
BASIS_CONTRADICTED = "CONTRADICTED"

#: The only bases a numeric comparison may run across.
KNOWN_BASES = (BASIS_VCD, BASIS_SAIF, BASIS_VECTORLESS)

CORROBORATED = "CORROBORATED"
UNCORROBORATED = "UNCORROBORATED"
CONTRADICTED = "CONTRADICTED"
NO_CORROBORATION_NEEDED = "NO_CORROBORATION_NEEDED"

# ── §2 record statuses used here ───────────────────────────────────────────
STATUS_MEASURED = "MEASURED"
STATUS_NOT_MEASURED = "NOT_MEASURED"
STATUS_INVALID = "INVALID"
STATUS_DERIVED = "DERIVED"

#: The four figures every `report_power` row carries, in the tool's own order.
CATEGORIES = ("internal", "switching", "leakage", "total")
TOTAL_GROUP = "Total"

#: metric names, one per category. Watts, because that is the unit the artefact
#: states; converting to uW here would make every record DERIVED for no gain.
_METRIC_NAME = {c: f"power.{c}_w" for c in CATEGORIES}

# ── parsing ────────────────────────────────────────────────────────────────
_NUM = r"[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?"
#: A `report_power` row: a group label then four figures, optionally a percent.
_ROW_RE = re.compile(
    r"^[ \t]*(?P<group>[A-Za-z][A-Za-z0-9_ /-]*?)[ \t]+"
    r"(?P<internal>" + _NUM + r")[ \t]+"
    r"(?P<switching>" + _NUM + r")[ \t]+"
    r"(?P<leakage>" + _NUM + r")[ \t]+"
    r"(?P<total>" + _NUM + r")\b", re.M)

_MODE_RE = re.compile(r"^POWER_ANALYSIS_MODE:[ \t]*(?P<mode>\S+)", re.M)
#: OpenSTA's own count of what the activity read actually annotated. This is
#: the ONLY positive evidence in the artefact that a vector basis is real.
_ANNOTATED_RE = re.compile(
    r"^.*?Annotated[ \t]+(?P<n>\d+)[ \t]+pin[ \t]+activit(?:y|ies)\b", re.M)
#: The runner catches a failed activity read and PRINTS it, so a report can
#: state a vector basis and carry the failure of the read that would have
#: produced it, three lines apart.
_FAIL_RE = re.compile(
    r"^(?P<line>(?:READ_VCD_FAIL|READ_SAIF_FAIL|REPORT_POWER_FAIL):.*)$", re.M)
#: The tool's own banner, used for `source.tool_version`. Never for a verdict.
#: Only the runner's `-no_splash` invocations are shipped, so this banner is
#: absent from every published artefact and the envelope reader below is what
#: actually establishes the tool.
_TOOL_RE = re.compile(r"^(?P<tool>OpenSTA)[ \t]+(?P<version>\S+)", re.M)

#: The provenance envelope, in BOTH spellings the flow has shipped. The LIBERTY
#: and the TOOL are measurement CONDITIONS: a power number at one corner's
#: library, or off one engine, is not the same metric as one at another's, so
#: they belong in `scope` and not only in prose.
#:
#: MEASURED on this checkout. `phase3_one_shot_runner.canonicalize_artefacts`
#: prepends a COLON-delimited block (`#   liberty: <name>`), and the published
#: artefacts this repository ships as fixtures carry a column-ALIGNED one
#: (`#   liberty  <path>`, `#   tool     OpenSTA 2.7.0 in <image>`) with no
#: colon at all. The old expressions read only the colon spelling, so for an
#: artefact that STATES its liberty and its tool this module resolved neither
#: and then wrote both into `scope` as `null` — see `metric_records`. The
#: punctuation between a key and its value is not a second fact, so one reader
#: accepts either. The key must still be the FIRST token of the comment line,
#: which is what keeps a prose line that merely mentions the word out of it.
_ENVELOPE_RE = {
    key: re.compile(r"^[ \t]*#[ \t]*" + key + r"[ \t]*:?[ \t]+(?P<value>\S+)",
                    re.M | re.IGNORECASE)
    for key in ("liberty", "netlist", "tool")
}
#: A version token, so a `tool` line whose second token is NOT one (the runner
#: writes `# Tool: openroad / sta (...)`) reports no version rather than the
#: punctuation that happened to follow. An invented version is a provenance
#: claim nobody made.
_VERSION_TOKEN_RE = re.compile(r"^v?\d+(?:\.\d+)*$")


def _envelope(text: str, key: str) -> Optional[str]:
    """The value the artefact's provenance block states for `key`, or None."""
    m = _ENVELOPE_RE[key].search(text)
    return m.group("value") if m else None


def _tool_of(text: str) -> Tuple[Optional[str], Optional[str]]:
    """`(tool, tool_version)` as the ARTEFACT states them, or `(None, None)`.

    The tool's own banner wins when it is present; the provenance envelope is
    read only when it is not. Neither is guessed: an artefact that names no
    tool returns None here and `metrics.validate` then refuses the MEASURED
    record for `SOURCE_UNTOOLED`, which is the correct outcome — a number with
    no provenance cannot be checked against the artefact it came from.
    """
    m = _TOOL_RE.search(text)
    if m:
        return m.group("tool").lower(), m.group("version")
    m = _ENVELOPE_RE["tool"].search(text)
    if not m:
        return None, None
    rest = m.string[m.end():].split("\n", 1)[0].split()
    version = rest[0] if rest and _VERSION_TOKEN_RE.match(rest[0]) else None
    return m.group("value").lower(), version

#: What a declared mode token means. Unrecognised tokens are UNSTATED, not
#: guessed — a mode this module does not know is a mode it cannot corroborate.
_DECLARED_BASIS = {
    "vector_vcd": BASIS_VCD,
    "vcd": BASIS_VCD,
    "vector_saif": BASIS_SAIF,
    "saif": BASIS_SAIF,
    "vectorless_sdc": BASIS_VECTORLESS,
    "vectorless": BASIS_VECTORLESS,
    "propagated": BASIS_VECTORLESS,
}
_VECTOR_BASES = (BASIS_VCD, BASIS_SAIF)

#: Category figures are printed to three significant digits, so a row's three
#: components sum to its total only to about that. This tolerance exists for a
#: DISCLOSURE, never for a verdict.
_SUM_RTOL = 0.02


#: Where a run declares the operating MODE it analysed. Same three locations
#: `_ppa/timing.py` reads, because it is the same declaration about the same
#: run: a power number and a timing number taken from one run were taken in one
#: mode, and two modules disagreeing about where that is written would make the
#: two axes incomparable for a reason that has nothing to do with the silicon.
_PVT_MATRIX = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "constraints/pvt_matrix.json",
    "phase3/stage3/constraints/pvt_matrix.json",
)


def _mode_for(project: Path) -> Tuple[Optional[str], Optional[str]]:
    """The run's operating MODE, from `pvt_matrix.json`'s own `modes` list.

    A VERBATIM MIRROR OF `_ppa/timing.py._mode_for`, and deliberately not a
    cleverer rule: `REQUIRED_SCOPE["power_mw"]` and `REQUIRED_SCOPE[
    "timing_wns_ns"]` both name `mode`, `check_scope_parity` compares the two
    scopes key by key, and a power module that resolved the mode by a different
    rule from its timing sibling would produce two records that disagree about
    the mode of ONE run.

    Exactly one declared mode is attributable to a report that never names one.
    Two or more is not: the reports carry no mode marker, so choosing between
    them would be invention. Zero declared modes is likewise null, and in every
    null case the REASON is returned beside it and is recorded in `provenance.
    mode_gap` -- a scope key this module could not fill says WHY, rather than
    arriving as a bare absence the reader has to explain.
    """
    path = next((project / rel for rel in _PVT_MATRIX
                 if (project / rel).is_file()), None)
    if path is None:
        return None, "no pvt_matrix.json declaring a mode"
    pvt = _load_json(path)
    if not isinstance(pvt, dict):
        return None, "no pvt_matrix.json declaring a mode"
    modes = pvt.get("modes")
    if not isinstance(modes, list) or not modes:
        return None, "pvt_matrix.json declares no modes"
    modes = [str(m) for m in modes]
    if len(set(modes)) != 1:
        return None, ("pvt_matrix.json declares %d modes (%s) and the power "
                      "reports name none" % (len(set(modes)),
                                             ",".join(sorted(set(modes)))))
    return modes[0], None


def _num(tok: Any) -> Optional[float]:
    try:
        f = float(tok)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN is not a measurement


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def activity_provenance(text: str) -> Dict[str, Any]:
    """Where this report's switching activity came from — from EVIDENCE.

    Returns a dict with the declared mode, the corroborating and falsifying
    evidence found beside it, and the resolved `basis` / `corroboration`. It
    never returns a bare string, because "VCD" on its own is the claim this
    module exists to stop taking at face value.
    """
    evidence: List[Dict[str, Any]] = []

    m = _MODE_RE.search(text)
    declared_token = m.group("mode") if m else None
    if m:
        evidence.append({"kind": "declared_mode", "line": _lineno(text, m.start()),
                         "text": m.group(0).strip()})
    declared = _DECLARED_BASIS.get((declared_token or "").lower())

    annotated: Optional[int] = None
    for am in _ANNOTATED_RE.finditer(text):
        n = int(am.group("n"))
        annotated = n if annotated is None else annotated + n
        evidence.append({"kind": "annotated_pin_activities",
                         "line": _lineno(text, am.start()),
                         "text": am.group(0).strip()})

    failures: List[str] = []
    for fm in _FAIL_RE.finditer(text):
        failures.append(fm.group("line").strip())
        evidence.append({"kind": "activity_read_failure",
                         "line": _lineno(text, fm.start()),
                         "text": fm.group("line").strip()})

    prov: Dict[str, Any] = {
        "declared_mode": declared_token,
        "declared_basis": declared,
        "annotated_pin_activities": annotated,
        "read_failures": failures,
        "evidence": evidence,
    }

    if declared is None:
        # No mode line, or a token this module does not know. Either way the
        # artefact does not say, and "does not say" is not "vectorless".
        prov["basis"] = BASIS_UNSTATED
        prov["corroboration"] = NO_CORROBORATION_NEEDED
        prov["reason"] = (
            "the artefact states no activity basis"
            if declared_token is None else
            f"the artefact states an activity basis this parser does not "
            f"recognise: {declared_token!r}")
        return prov

    if declared in _VECTOR_BASES:
        if failures:
            prov["basis"] = BASIS_CONTRADICTED
            prov["corroboration"] = CONTRADICTED
            prov["reason"] = (
                f"the artefact declares {declared} activity and carries the "
                f"failure of the read that would have produced it: "
                f"{failures[0]}")
            return prov
        if annotated == 0:
            prov["basis"] = BASIS_CONTRADICTED
            prov["corroboration"] = CONTRADICTED
            prov["reason"] = (
                f"the artefact declares {declared} activity and the tool "
                f"reports it annotated 0 pin activities")
            return prov
        if annotated is None:
            prov["basis"] = declared
            prov["corroboration"] = UNCORROBORATED
            prov["reason"] = (
                f"the artefact declares {declared} activity and carries no "
                f"annotated-activity count to corroborate it")
            return prov
        prov["basis"] = declared
        prov["corroboration"] = CORROBORATED
        prov["reason"] = (f"{annotated} pin activities annotated")
        return prov

    # Declared vectorless. The mirror case is real: a report that says
    # vectorless while the tool annotated activities is just as wrong about
    # itself as the other direction, and stating one and not the other would
    # make the check depend on which lie was told.
    if annotated:
        prov["basis"] = BASIS_CONTRADICTED
        prov["corroboration"] = CONTRADICTED
        prov["reason"] = (
            f"the artefact declares vectorless activity and the tool reports "
            f"it annotated {annotated} pin activities")
        return prov
    prov["basis"] = BASIS_VECTORLESS
    prov["corroboration"] = NO_CORROBORATION_NEEDED
    prov["reason"] = "vectorless is the tool default; there is nothing to read"
    return prov


#: Where step 4's DUT-scoped activity dump writes its manifest, under a sim
#: directory (`sim_activity_dump.MANIFEST` in `activity/`).
ACTIVITY_MANIFEST_REL = "activity/activity.json"


def select_activity(sim_dirs: Sequence[Path]) -> Optional[Dict[str, Any]]:
    """The activity input for a vector power session, and the scope to read it at.

    A step-4 manifest whose VCD header was verified to carry the DUT scope wins:
    MEASURED in OpenSTA 3.1.0, `read_vcd` without `-scope` on a testbench VCD
    annotates 0 pins, so a VCD without its scope is an intention, not an input.
    With no manifest, the first non-empty `.vcd` is returned with `scope`
    None, exactly the file the deck used to pick; the report's own
    `Annotated N pin activities.` then decides whether it counted
    (`activity_provenance`)."""
    for root in sim_dirs:
        manifest = Path(root) / ACTIVITY_MANIFEST_REL
        try:
            doc = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        vcd = Path(str(doc.get("vcd") or ""))
        if doc.get("scope_verified") is True and doc.get("scope") \
                and vcd.is_file() and vcd.stat().st_size > 0:
            return {"vcd": vcd, "scope": str(doc["scope"]),
                    "source": str(manifest)}
    for root in sim_dirs:
        for vcd in sorted(Path(root).rglob("*.vcd")):
            if vcd.stat().st_size > 0:
                return {"vcd": vcd, "scope": None, "source": "legacy-glob"}
    return None


def activity_read_tcl(vcd_c: str, scope: Optional[str]) -> str:
    """The deck line that reads the activity, caught and printed on failure.

    `read_vcd` and not `read_power_activities -vcd`: MEASURED in OpenSTA 3.1.0
    (vibeic-eda 0.3.77) the latter is deprecated and raises `default is not a
    mode object`, which is why every shipped `vector_vcd` report carried
    READ_VCD_FAIL."""
    scope_arg = f"-scope {scope} " if scope else ""
    return (f"if {{[catch {{read_vcd {scope_arg}{vcd_c}}} _vcd_err]}} {{\n"
            f"  puts \"READ_VCD_FAIL: $_vcd_err\"\n}}\n")


def parse_power_report(text: str, *, path: Optional[str] = None,
                       sha256: Optional[str] = None) -> Dict[str, Any]:
    """Parse one `report_power` artefact into rows plus activity provenance.

    Returns a dict; `rows` is a list of group rows in the order the artefact
    states them, `total_row` is the `Total` row or None. Figures are the values
    PARSED — the raw token is kept beside each one so a consumer can hash what
    the tool wrote rather than what a float round-tripped to (§3).
    """
    rows: List[Dict[str, Any]] = []
    for m in _ROW_RE.finditer(text):
        group = m.group("group").strip()
        row: Dict[str, Any] = {"group": group, "line": _lineno(text, m.start())}
        ok = True
        for c in CATEGORIES:
            v = _num(m.group(c))
            if v is None:
                ok = False
                break
            row[f"{c}_w"] = v
            row[f"{c}_raw"] = m.group(c)
        if ok:
            rows.append(row)

    total_rows = [r for r in rows if r["group"].lower() == TOTAL_GROUP.lower()]
    group_rows = [r for r in rows if r["group"].lower() != TOTAL_GROUP.lower()]

    tool, tool_version = _tool_of(text)
    out: Dict[str, Any] = {
        "path": path,
        "sha256": sha256,
        "tool": tool,
        "tool_version": tool_version,
        "liberty": _envelope(text, "liberty"),
        "netlist": _envelope(text, "netlist"),
        # WHAT THE SESSION LINKED, read here beside the other envelope facts
        # so every consumer of a parsed report gets the same answer.
        "power_basis": (_POWER_BASIS_RE.search(text).group("basis")
                        if _POWER_BASIS_RE.search(text) else None),
        "activity": activity_provenance(text),
        "rows": group_rows,
        "total_row": total_rows[0] if total_rows else None,
        "total_rows_seen": len(total_rows),
    }
    out["split_consistency"] = _split_consistency(out)
    out["group_sum_consistency"] = _group_sum_consistency(out)
    return out


def read_power_report(path: Path) -> Optional[Dict[str, Any]]:
    """`parse_power_report` on a file, with the file's own sha256 attached.

    Returns None when the file cannot be READ. The caller must not conflate
    that with a file that was read and held nothing: those are different facts
    and this repository has paid for treating them the same.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    return parse_power_report(raw.decode("utf-8", errors="replace"),
                              path=str(path),
                              sha256="sha256:" + hashlib.sha256(raw).hexdigest())


def _split_consistency(report: Dict[str, Any]) -> Dict[str, Any]:
    """Does internal + switching + leakage reach the row's own total?

    A DISCLOSURE. It is not a verdict and it is deliberately not one: the
    mutation this axis was written against
    (`matrix_mutation_ledger.ART-POWER-FIGURES-X1000`) multiplies every non-zero
    figure by 1000 and therefore PRESERVES this property exactly. A check that
    the mutation cannot move is not a check that discriminates.
    """
    t = report.get("total_row")
    if not t:
        return {"status": STATUS_NOT_MEASURED,
                "reason": "the artefact states no Total row"}
    parts = t["internal_w"] + t["switching_w"] + t["leakage_w"]
    total = t["total_w"]
    if total == 0:
        return {"status": STATUS_DERIVED, "formula":
                "internal_w + switching_w + leakage_w", "sum_w": parts,
                "total_w": total, "consistent": parts == 0,
                "note": "total is zero; a relative tolerance does not apply"}
    return {"status": STATUS_DERIVED,
            "formula": "internal_w + switching_w + leakage_w",
            "sum_w": parts, "total_w": total,
            "relative_error": abs(parts - total) / abs(total),
            "tolerance": _SUM_RTOL,
            "consistent": abs(parts - total) <= _SUM_RTOL * abs(total)}


def _group_sum_consistency(report: Dict[str, Any]) -> Dict[str, Any]:
    """Do the group rows reach the Total row? Same disclosure, same reason."""
    t = report.get("total_row")
    rows = report.get("rows") or []
    if not t or not rows:
        return {"status": STATUS_NOT_MEASURED,
                "reason": "the artefact states no Total row"
                          if not t else "the artefact states no group rows"}
    parts = sum(r["total_w"] for r in rows)
    total = t["total_w"]
    if total == 0:
        return {"status": STATUS_DERIVED, "formula": "sum(group.total_w)",
                "sum_w": parts, "total_w": total, "consistent": parts == 0}
    return {"status": STATUS_DERIVED, "formula": "sum(group.total_w)",
            "sum_w": parts, "total_w": total,
            "relative_error": abs(parts - total) / abs(total),
            "tolerance": _SUM_RTOL,
            "consistent": abs(parts - total) <= _SUM_RTOL * abs(total)}


# ── canonical records ──────────────────────────────────────────────────────
def _parser_sha256() -> str:
    try:
        return "sha256:" + hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()
    except OSError:                                   # pragma: no cover
        return "sha256:unavailable"


def _source(report: Dict[str, Any]) -> Dict[str, Any]:
    return {"path": report.get("path"), "sha256": report.get("sha256"),
            "tool": report.get("tool"),
            "tool_version": report.get("tool_version"),
            "liberty": report.get("liberty"), "netlist": report.get("netlist"),
            "parser": PARSER, "parser_sha256": _parser_sha256()}


def _record(metric: str, status: str, value: Optional[float],
            scope: Dict[str, Any], source: Dict[str, Any], *,
            raw: Optional[str] = None, reason: Optional[str] = None,
            scope_gaps: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"schema": SCHEMA_METRIC, "metric": metric,
                           "status": status, "unit": "W", "scope": scope,
                           "source": source}
    if scope_gaps:
        # OUTSIDE `scope`, and that is the whole point: a reason recorded here
        # cannot make two records compare equal, whereas the same reason spelled
        # as a scope value can and did. Same channel and same convention as
        # `_ppa/timing._gaps_for`.
        rec["scope_gaps"] = dict(sorted(scope_gaps.items()))
    if status in (STATUS_MEASURED, STATUS_DERIVED):
        rec["value"] = value
        if raw is not None:
            rec["value_raw"] = raw
    else:
        # §2: a not-measured record carries a reason, NOT a value. No 0, no -1,
        # no "". The row is printed, never omitted.
        rec["reason"] = reason or "not stated by the artefact"
    return rec


def metric_records(report: Dict[str, Any], *, stage: Optional[str] = None,
                   scenario: str = "default",
                   project: Optional[Path] = None,
                   extra_scope: Optional[Dict[str, Any]] = None
                   ) -> List[Dict[str, Any]]:
    """Every figure the artefact states, as `vibeic.ppa.metric.v1` records.

    One record per (group, category), plus the Total group. Every record's
    scope carries `activity_basis`, because a power number without one is not a
    comparable fact. A record whose basis is CONTRADICTED is `INVALID` — §2:
    "the artefact exists but cannot support the metric".
    """
    act = report.get("activity") or {}
    basis = act.get("basis", BASIS_UNSTATED)
    src = _source(report)
    # SCOPE IS THE MEASUREMENT'S CONDITIONS, and §2 says two numbers are
    # comparable only if their scope matches — so everything that makes this a
    # different measurement goes in, and nothing else does. `tool` is here as
    # well as in `source` (where §2's example puts it) because for power a
    # different engine on a different netlist view IS a different condition:
    # on the run the mutation ledger replays, the STA and IR engines' totals
    # differ by 4.3x.  The CORROBORATION state is deliberately NOT here: it
    # describes how well we know the basis, not what was measured.
    # THE WORD HALF OF THE SAME RULE. Until now `stage` was written
    # unconditionally and defaulted to the WORD `"unknown"`, which nothing in
    # this system refused: `metrics.validate`'s required-key test is satisfied
    # by any non-empty string, and `benchmark.check_scope_parity` granted two
    # arms parity on it and compared a synthesis power number against a
    # post-route one. `activity_basis` is the same defect with a
    # documented-looking value -- `UNSTATED` says the artefact named no basis,
    # and `"UNSTATED" == "UNSTATED"`, so two power numbers that never said what
    # they were computed against passed parity as if they had said the same
    # thing. CONTRADICTED stays IN: the artefact stated two bases, which is a
    # determinate finding about it rather than a silence, and every record
    # carrying it is INVALID and so can never enter a comparison anyway.
    base_scope: Dict[str, Any] = {"scenario": scenario}
    _word_gaps: Dict[str, str] = {}
    if stage is not None and not _metrics.is_scope_silence(stage):
        base_scope["stage"] = stage
    else:
        _word_gaps["stage"] = (
            "the caller could not establish which stage this power number "
            f"belongs to (it passed {stage!r}); a stage is derived from the "
            "netlist the power session linked, never from the directory the "
            "report was filed in")
    if basis == BASIS_UNSTATED:
        _word_gaps["activity_basis"] = (
            "the artefact states no POWER_ANALYSIS_MODE / activity source, so "
            "what this number was computed against is unrecorded")
    else:
        base_scope["activity_basis"] = basis
    # ── the two conditions this module used to NULL ────────────────────────
    # `liberty` and `tool` were written in unconditionally as
    # `report.get(...)`, which is `None` for any artefact whose provenance
    # block this module could not read -- and until `_envelope`/`_tool_of`
    # above that was EVERY published artefact, because only one of the two
    # shipped spellings was parsed. §2: "a `scope` key that is present and null
    # is worse than one that is absent", because `null == null` makes two runs
    # against two different libraries, or off two different engines, one
    # measurement -- and `metrics.validate` refuses the null spelling outright
    # (SCOPE_SENTINEL), so 48 of 48 records built from this repository's own
    # power fixtures were refused by the canonical consumer.
    #
    # They are now emitted under the SAME rule the PVT keys below already
    # follow: only what the artefact STATES is emitted, a condition it does not
    # state is left OUT rather than nulled, and the reason is recorded in
    # `provenance.scope_gaps` -- outside `scope`, where it cannot make two
    # records compare equal. An artefact that names no tool still loses its
    # MEASURED records to `SOURCE_UNTOOLED`; that refusal is correct and it is
    # deliberately not softened here.
    scope_gaps: Dict[str, str] = dict(_word_gaps)
    for key, val, gap in (
            ("liberty", report.get("liberty"),
             "the artefact states no liberty file, so the library these "
             "figures were computed against is unread"),
            ("tool", report.get("tool"),
             "the artefact states no tool, so the engine that produced these "
             "figures is unread")):
        if val:
            base_scope[key] = val
        else:
            scope_gaps[key] = gap
    # ── the PVT the liberty file names ────────────────────────────────────
    # `_ppa/benchmark.REQUIRED_SCOPE["power_mw"]` needs stage, mode, process,
    # voltage_v, temperature_c and activity_basis before two power numbers may
    # be compared at all. This module emitted four of the six, so every shipped
    # power record was refused SCOPE_INCOMPLETE by the head-to-head before it
    # could compare anything -- while carrying, in `scope.liberty`, the file
    # name that states three of the missing four, and while the same lane
    # shipped the parser for it.
    #
    # ONLY WHAT THE PARSER RESOLVED IS EMITTED. `check_scope_parity` tests
    # required keys for PRESENCE, so `process: None` would satisfy the key check
    # and then compare equal to another `None` -- two records that say nothing
    # about their corner, passing as the same corner. That is worse than the
    # refusal it replaces. A field the stem does not state is left OUT, the
    # refusal stands, and the reason the parser gave is recorded below.
    pvt = _opensta.parse_liberty_pvt(report.get("liberty"))
    for key, val in (("process", pvt.process), ("voltage_v", pvt.voltage_v),
                     ("temperature_c", pvt.temperature_c)):
        if val is not None:
            base_scope[key] = val
    # ── the sixth required key, and the one this module never emitted ──────
    # The comment above says this module "emitted four of the six" and then
    # fixed three; `mode` was the fourth and stayed unemittable, because
    # `base_scope` has no branch that can set it and no production caller
    # passes `extra_scope` (MEASURED: the only three `extra_scope=` call sites
    # in the tree are in tests). So every power record this module has ever
    # written was SCOPE_INCOMPLETE at `ppa_head_to_head_check` BY
    # CONSTRUCTION -- refused for a key the producer had no way to fill, while
    # the timing sibling read it from `pvt_matrix.json` all along.
    #
    # Resolved by the SAME rule as `_ppa/timing.py`, and emitted under the SAME
    # discipline as the three above: only what was resolved is emitted, a mode
    # nothing declares is left OUT rather than nulled, and the refusal stands
    # with the reason recorded in `provenance.mode_gap`.
    mode, mode_gap = (_mode_for(project) if project is not None
                      else (None, "no project directory was given to resolve "
                                  "the mode from"))
    if mode is not None:
        base_scope["mode"] = mode
    provenance = {"scope_gaps": scope_gaps or None,
                  "activity_corroboration": act.get("corroboration"),
                  "activity_reason": act.get("reason"),
                  # NOT the scope's `mode`. This is the ACTIVITY token
                  # (`vcd`/`saif`/`vectorless`) that `POWER_ANALYSIS_MODE:`
                  # states; the scope's `mode` is the operating mode
                  # (functional/scan) and is `mode_gap`'s subject. Two
                  # different axes that the word "mode" spells the same.
                  "declared_mode": act.get("declared_mode"),
                  "mode_gap": mode_gap,
                  # The parser's own account of what it could not read, kept
                  # beside the scope it did not fill. `ambiguous:...` means the
                  # stem carried two candidates and it refused to pick one.
                  "liberty_pvt_stem": pvt.stem,
                  "liberty_pvt_gaps": dict(pvt.gaps) or None}
    if extra_scope:
        base_scope.update(extra_scope)

    rows = list(report.get("rows") or [])
    if report.get("total_row"):
        rows.append(report["total_row"])

    out: List[Dict[str, Any]] = []
    if not rows:
        for c in CATEGORIES:
            out.append(_record(
                _METRIC_NAME[c], STATUS_NOT_MEASURED, None,
                dict(base_scope, group=TOTAL_GROUP), src,
                reason="the artefact states no power rows",
                scope_gaps=scope_gaps))
        return out

    invalid = basis == BASIS_CONTRADICTED
    for r in rows:
        scope = dict(base_scope, group=r["group"])
        for c in CATEGORIES:
            rec = _record(
                _METRIC_NAME[c],
                STATUS_INVALID if invalid else STATUS_MEASURED,
                r[f"{c}_w"], scope, src, raw=r[f"{c}_raw"],
                reason=act.get("reason") if invalid else None,
                scope_gaps=scope_gaps)
            rec["provenance"] = dict(provenance)
            out.append(rec)
    return out


def total_record(report: Dict[str, Any], **kw: Any) -> Optional[Dict[str, Any]]:
    """The one record a budget comparison is entitled to use, or None.

    None means the artefact states no Total row — which the caller must report
    as NOT MEASURED, never as zero power.
    """
    if not report.get("total_row"):
        return None
    for rec in metric_records(report, **kw):
        if rec["metric"] == _METRIC_NAME["total"] and \
                rec["scope"].get("group", "").lower() == TOTAL_GROUP.lower():
            return rec
    return None                                        # pragma: no cover


# ── comparability ──────────────────────────────────────────────────────────
V_A_LOWER = "A_LOWER"
V_B_LOWER = "B_LOWER"
V_EQUAL = "EQUAL"
V_UNDETERMINED = "UNDETERMINED"

#: The scope key this lane exists for, checked FIRST and by name, because it is
#: the one that is easiest to fake and the one whose refusal must be legible.
#: Everything ELSE in scope is compared too — §2 says two numbers are comparable
#: only if their scope MATCHES, and enumerating a subset here would silently
#: exempt whatever a later author adds to scope.
PRIMARY_SCOPE_KEY = "activity_basis"


def comparable(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[bool, str]:
    """`(is_comparable, reason)` for two `vibeic.ppa.metric.v1` records.

    The refusals, in the order they are checked:
      * a record that is not MEASURED may not enter a numeric comparison (§2);
      * a basis outside the known set — UNSTATED or CONTRADICTED — is not a
        basis, and UNSTATED does not match another UNSTATED;
      * differing scope is a different metric, not a worse result.
    """
    for name, rec in (("A", a), ("B", b)):
        if rec.get("metric") != _METRIC_NAME["total"]:
            return False, (f"{name} is {rec.get('metric')!r}, not "
                           f"{_METRIC_NAME['total']!r}")
        if rec.get("status") != STATUS_MEASURED:
            return False, (f"{name} is {rec.get('status')}, and only MEASURED "
                           f"records may enter a numeric comparison"
                           + (f": {rec['reason']}" if rec.get("reason") else ""))
    for name, rec in (("A", a), ("B", b)):
        basis = (rec.get("scope") or {}).get("activity_basis")
        if basis not in KNOWN_BASES:
            return False, (
                f"{name} has activity basis {basis!r}; two numbers whose "
                f"activity models are unknown are not known to share one")
    a_scope = a.get("scope") or {}
    b_scope = b.get("scope") or {}
    for key in sorted(set(a_scope) | set(b_scope)):
        av, bv = a_scope.get(key), b_scope.get(key)
        if av != bv:
            return False, (f"scope.{key} differs: {av!r} vs {bv!r} — these are "
                           f"different metrics, so the comparison is "
                           f"UNDETERMINED and not a winner")
    return True, "scope matches on " + ", ".join(sorted(a_scope))


def compare_total_power(a: Dict[str, Any], b: Dict[str, Any], *,
                        rel_tol: float = 0.0) -> Dict[str, Any]:
    """Which of two total-power records is lower, or UNDETERMINED.

    `rel_tol` is a dead band around equality, expressed relative to the larger
    magnitude. It defaults to 0: this function does not invent a noise floor,
    because a tolerance nobody declared turns an unanswered question into an
    answered one.
    """
    ok, reason = comparable(a, b)
    if not ok:
        return {"verdict": V_UNDETERMINED, "code": "NOT_COMPARABLE",
                "reason": reason}
    av, bv = a["value"], b["value"]
    band = rel_tol * max(abs(av), abs(bv))
    if abs(av - bv) <= band:
        verdict = V_EQUAL
    else:
        verdict = V_A_LOWER if av < bv else V_B_LOWER
    return {"verdict": verdict, "code": "COMPARED", "reason": reason,
            "a_value_w": av, "b_value_w": bv,
            "activity_basis": a["scope"]["activity_basis"],
            "delta_w": bv - av, "rel_tol": rel_tol}


def digest(obj: Any) -> str:
    """The identity of a power document. One serializer, always (§3)."""
    return _cj.digest_of(obj)


# ── the requirement side: a budget is a CONTRACT term, not a constant ──────
#: The document that may declare a power requirement. `PPA_INTERFACES.md` §4
#: gives `_ppa/contract.py` to the contract lane; until that module lands with
#: a loader, this reads the frozen document SHAPE directly and nothing else, so
#: the swap is one function body.
CONTRACT_SCHEMA = "vibeic.ppa.contract.v1"
#: Where a PPA contract may sit. DISCOVERED, never enumerated by design name.
CONTRACT_GLOBS: Tuple[str, ...] = (
    "ppa_contract*.json", "**/ppa_contract*.json",
    "**/*.ppa.contract.json", "contracts/ppa/*.json",
    "phase1/**/PPA_CONTRACT*.json",
)
#: The L-document the flow has always carried. It is a LOWER authority than a
#: PPA contract and it declares no activity basis, which is exactly why the
#: contract exists.
L19_GLOBS: Tuple[str, ...] = (
    "phase1/**/L19*.json", "generated_docs/L19*.json",
    "**/L19_CONSTRAINTS_PDK.json",
)

AUTHORITY_CONTRACT = "ppa_contract"
AUTHORITY_L19 = "L19.power_budget_uw"
AUTHORITY_CLI = "--budget-uw"
#: The design's own L7 sign-off row, resolved FOR THE TECHNOLOGY THIS RUN BUILT
#: AGAINST (vibe-ic#2147). It sits BELOW L19 because L19 is a typed field a
#: consuming layer owns, and this is a row read out of a document — but it is
#: above nothing, which is what it was worth before: on the measured run L19
#: declared no budget and the L7 row that DID declare one reached no gate.
AUTHORITY_L7_SIGNOFF = "L7.signoff_row"

_MICRO = 1e-6
#: The metric names a power requirement may be written against, and the factor
#: that takes the stated limit to Watts. A requirement in any other unit is not
#: silently converted — it is reported as unreadable.
_REQ_METRIC_TO_W = {"power.total_w": 1.0, "power.total_uw": _MICRO}
_REQ_UNIT_TO_W = {"W": 1.0, "w": 1.0, "uW": _MICRO, "uw": _MICRO,
                  "µW": _MICRO, "microwatt": _MICRO}


def _discover(project: Path, globs: Sequence[str]) -> List[Path]:
    seen: Dict[str, Path] = {}
    for pat in globs:
        for p in project.glob(pat):
            if p.is_file():
                seen[str(p.resolve())] = p
    return [seen[k] for k in sorted(seen)]


def _rel(p: Path, project: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:                                 # pragma: no cover
        return str(p)


def _load_json(p: Path) -> Optional[Any]:
    try:
        return json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def contract_power_requirements(project: Path) -> List[Dict[str, Any]]:
    """Every total-power requirement stated by a `vibeic.ppa.contract.v1` doc.

    A document that does not carry the schema key is not a contract and is
    ignored — silently guessing that some other JSON "looks like" a contract is
    how an authority nobody declared gets invented.
    """
    out: List[Dict[str, Any]] = []
    for fp in _discover(project, CONTRACT_GLOBS):
        doc = _load_json(fp)
        if not isinstance(doc, dict) or doc.get("schema") != CONTRACT_SCHEMA:
            continue
        reqs = doc.get("requirements")
        if not isinstance(reqs, list):
            continue
        for req in reqs:
            if not isinstance(req, dict):
                continue
            metric = req.get("metric")
            if metric not in _REQ_METRIC_TO_W:
                continue
            limit = req.get("limit")
            raw_max = limit.get("max") if isinstance(limit, dict) else None
            val = _num(raw_max)
            unit = req.get("unit")
            metric_factor = _REQ_METRIC_TO_W[metric]
            unit_factor = (_REQ_UNIT_TO_W.get(unit) if unit is not None
                           else metric_factor)
            # A requirement whose metric NAME and whose `unit` imply different
            # scales is self-contradictory, and resolving it by preferring one
            # of them would pick a limit off by a million with nothing in the
            # output to say which reading was taken.
            mismatch = (unit_factor is not None
                        and unit_factor != metric_factor)
            factor = None if mismatch else unit_factor
            entry: Dict[str, Any] = {
                "file": _rel(fp, project), "authority": AUTHORITY_CONTRACT,
                "metric": metric, "unit": unit,
                "scope": req.get("scope") if isinstance(req.get("scope"), dict)
                         else {},
                "declared_by": req.get("authority"),
            }
            if val is None or val <= 0 or factor is None:
                entry["max_w"] = None
                entry["max_uw"] = None
                entry["unreadable"] = (
                    f"metric={metric!r} and unit={unit!r} imply different "
                    f"scales" if mismatch else
                    f"limit.max={raw_max!r} unit={unit!r} is not a positive "
                    f"power in a unit this parser knows")
            else:
                entry["max_w"] = val * factor
                # §3: report the value PARSED, not one round-tripped through a
                # unit conversion. 1000.0 uW -> W -> uW is 1000.0000000000001,
                # and an identity taken over that is an identity over an
                # arithmetic artefact.
                entry["max_uw"] = val if factor == _MICRO else val / _MICRO
            out.append(entry)
    return out


def l19_power_budgets(project: Path) -> List[Dict[str, Any]]:
    """Every published L19 copy's `power_budget_uw`, read as stated.

    Every copy is read. Phase 1 publishes the same document into several
    directories, and taking the first would make the verdict depend on glob
    order.
    """
    out: List[Dict[str, Any]] = []
    for fp in _discover(project, L19_GLOBS):
        doc = _load_json(fp)
        if not isinstance(doc, dict):
            continue
        fields = doc.get("fields")
        raw = fields.get("power_budget_uw") if isinstance(fields, dict) else None
        if raw is None and "power_budget_uw" in doc:
            raw = doc.get("power_budget_uw")
        val = _num(raw)
        out.append({"file": _rel(fp, project), "authority": AUTHORITY_L19,
                    "metric": "power.total_uw", "unit": "uW",
                    "power_budget_uw": val,
                    "max_w": val * _MICRO if val is not None and val > 0
                             else None,
                    "max_uw": val if val is not None and val > 0 else None,
                    # An L-document states no activity basis. That is not a
                    # defect in the document; it is the reason a requirement
                    # read from it cannot police the basis of the number it
                    # judges, and the verdict says so.
                    "scope": {}})
    return out


def _l7_signoff_requirement(project: Path, library: str, pdk: str
                            ) -> Tuple[Optional[Dict[str, Any]], Optional[str],
                                       Optional[Dict[str, Any]]]:
    """``(requirement, refusal, report)`` from the design's L7 sign-off row.

    THE TECHNOLOGY IS THE WHOLE QUESTION (vibe-ic#2136/#2147). The row states an
    absolute in watts that is the product of a baseline measured on ONE library;
    applying it to a run built on another is a verdict about a design that was
    never judged. `area_signoff_baseline` owns that resolution for both metrics
    and returns a NAMED refusal rather than a number when it cannot answer, so
    this function never has to decide what "close enough" means.
    """
    try:
        import area_signoff_baseline as _asb          # noqa: PLC0415
    except Exception as exc:                          # pragma: no cover
        return None, f"the L7 sign-off resolver is unavailable ({exc})", None
    rep = _asb.resolve_for_project(project, metric=_asb.METRIC_TOTAL_POWER,
                                   library=library, pdk=pdk)
    if not rep.get("signoff_row_found"):
        return None, None, rep
    if not rep.get("determined"):
        return None, (f"the design's L7 total-power sign-off row is "
                      f"NOT_DETERMINED for this run ({rep.get('reason')}): "
                      f"{rep.get('note')}"), rep
    uw = float(rep["threshold"])
    req = {"authority": AUTHORITY_L7_SIGNOFF,
           "file": rep.get("source") or "L7", "line": rep.get("line"),
           "metric": "power.total_uw", "unit": "uW",
           "max_w": uw * _MICRO, "max_uw": uw, "scope": {},
           "tier": rep.get("tier"), "note": rep.get("note")}
    return req, None, rep


def resolve_power_requirement(project: Path, *,
                              budget_uw: Optional[float] = None,
                              library: str = "", pdk: str = ""
                              ) -> Dict[str, Any]:
    """The single total-power requirement in force, or a stated refusal.

    Authority order, highest first:

      1. `--budget-uw` — an explicit caller-supplied requirement. A caller that
         states one has taken the authority on itself, and is entitled to.
      2. A `vibeic.ppa.contract.v1` requirement on `power.total_w`.
      3. L19 `fields.power_budget_uw`.
      4. The design's own L7 sign-off row, resolved for the technology THIS RUN
         built against (vibe-ic#2147). It answers only when the higher tiers
         declared nothing — a design that typed a budget is not overruled by a
         document row — and it refuses BY NAME rather than applying another
         technology's number.

    A higher authority SUPERSEDES a lower one and the superseded value is
    disclosed, not discarded — a contract exists so that it can override the
    flow's default, and treating any disagreement with a lower document as
    fatal would make declaring one impossible. Disagreement WITHIN one level is
    different: two copies of one authority stating two numbers is not an
    authority, and that refuses.

    Returns `{"requirement": <dict|None>, "sources": [...], "refusal": <str|None>}`.
    """
    sources: List[Dict[str, Any]] = []
    contract_reqs = contract_power_requirements(project)
    l19 = l19_power_budgets(project)
    sources.extend(contract_reqs)
    sources.extend(l19)

    if budget_uw is not None:
        req = {"authority": AUTHORITY_CLI, "file": AUTHORITY_CLI,
               "metric": "power.total_uw", "unit": "uW",
               "max_w": budget_uw * _MICRO, "max_uw": budget_uw,
               "scope": {}}
        sources.insert(0, req)
        return {"requirement": req, "sources": sources, "refusal": None,
                "superseded": [s for s in (contract_reqs + l19)
                               if s.get("max_w") is not None]}

    readable = [r for r in contract_reqs if r.get("max_w") is not None]
    if readable:
        # Identity of a requirement is (limit, the basis it was written
        # against) — NOT the limit alone. Two requirements at one limit for two
        # activity bases are two requirements, and one requirement stated twice
        # with two limits is not an authority.
        distinct = sorted({(r["max_w"],
                            (r.get("scope") or {}).get("activity_basis"))
                           for r in readable})
        if len(distinct) > 1:
            return {"requirement": None, "sources": sources,
                    "refusal": (
                        f"{len(distinct)} distinct {CONTRACT_SCHEMA} "
                        f"total-power requirements (limit_W, activity_basis): "
                        f"{distinct}. This gate applies ONE limit and will "
                        f"not choose between them"),
                    "superseded": []}
        return {"requirement": readable[0], "sources": sources,
                "refusal": None,
                "superseded": [s for s in l19 if s.get("max_w") is not None]}
    unreadable = [r for r in contract_reqs if r.get("unreadable")]

    stated = sorted({s["max_w"] for s in l19 if s.get("max_w") is not None})
    if len(stated) == 1:
        return {"requirement": next(s for s in l19
                                    if s.get("max_w") == stated[0]),
                "sources": sources, "refusal": None, "superseded": []}
    if len(stated) > 1:
        return {"requirement": None, "sources": sources,
                "refusal": (f"L19 copies disagree: "
                            f"{[round(v / _MICRO, 6) for v in stated]} uW"),
                "superseded": []}
    # ── the L7 sign-off row, LAST and only when nothing above declared ─────
    #
    # MEASURED (vibe-ic#2147): on the subservient run L19's power_budget_uw is
    # null and the design's own L7 table states a total-power ceiling. Before
    # this tier the gate answered INCOMPLETE — a correct refusal over a
    # requirement the design HAD written down, which is the whole finding.
    l7_req, l7_refusal, l7_rep = _l7_signoff_requirement(project, library, pdk)
    if l7_rep is not None:
        sources.append({"file": l7_rep.get("source") or "L7",
                        "authority": AUTHORITY_L7_SIGNOFF,
                        "tier": l7_rep.get("tier"),
                        "determined": bool(l7_rep.get("determined")),
                        "reason": l7_rep.get("reason"),
                        "max_uw": l7_rep.get("threshold"),
                        "max_w": ((l7_rep.get("threshold") or 0) * _MICRO
                                  if l7_rep.get("determined") else None),
                        "note": l7_rep.get("note"),
                        # vibe-ic#2277 — the CONSUMER needs to tell the two
                        # NOT_DETERMINED shapes apart: "the design states no
                        # total-power sign-off row at all" and "it states one,
                        # bound to another technology". Only this branch knows
                        # which, so it says so here rather than leaving the
                        # consumer to re-parse the prose.
                        "signoff_row_found": bool(
                            l7_rep.get("signoff_row_found")),
                        "attributions_seen": l7_rep.get("attributions_seen"),
                        "run_technology": l7_rep.get("run_technology")})
    if l7_req is not None:
        return {"requirement": l7_req, "sources": sources, "refusal": None,
                "superseded": []}

    unset = len([s for s in l19 if s.get("max_w") is None])
    bits = [f"L19_CONSTRAINTS_PDK.json fields.power_budget_uw (unset in "
            f"{unset} of {len(l19)} published copy/copies)"]
    if unreadable:
        bits.append(f"{len(unreadable)} {CONTRACT_SCHEMA} requirement(s) "
                    f"unreadable: {unreadable[0]['unreadable']}")
    if l7_refusal:
        bits.append(l7_refusal)
    else:
        bits.append("the design's own L7 documents state no total-power "
                    "sign-off row either")
    return {"requirement": None, "sources": sources,
            "refusal": "; ".join(bits), "superseded": []}


#: Verdicts `judge_against_requirement` may return. UNDETERMINED is a first
#: class answer here and not an error tier: it is what an honest gate says when
#: it holds both a number and a threshold that do not belong to each other.
J_PASS, J_FAIL, J_UNDETERMINED = "PASS", "FAIL", "UNDETERMINED"


def judge_against_requirement(record: Optional[Dict[str, Any]],
                              requirement: Optional[Dict[str, Any]]
                              ) -> Dict[str, Any]:
    """Compare one total-power record against one requirement, or refuse.

    The refusals, and each is a comparison this function is NOT entitled to
    make:

      * no record  -> the artefact stated no total. Not zero power.
      * no requirement -> nothing to compare against.
      * record not MEASURED -> §2: an INVALID or NOT_MEASURED record may not
        enter a numeric comparison. This is the branch that catches a power
        number whose declared VCD basis its own transcript falsifies.
      * requirement declares an activity basis and the record's differs -> a
        budget written against observed activity cannot judge a vectorless
        estimate, and vice versa.

    A requirement that declares NO basis still bounds the number, and says so:
    `basis_policed` is False and the reader can see that the threshold does not
    know what activity model it is judging.
    """
    if record is None:
        return {"verdict": J_UNDETERMINED, "code": "NO_TOTAL_POWER",
                "reason": "no artefact states a Total row"}
    if requirement is None:
        return {"verdict": J_UNDETERMINED, "code": "NO_REQUIREMENT",
                "reason": "no authority declares a total-power limit"}
    if record.get("status") != STATUS_MEASURED:
        return {"verdict": J_UNDETERMINED, "code": "TOTAL_NOT_MEASURED",
                "reason": (f"the total-power record is "
                           f"{record.get('status')}: "
                           f"{record.get('reason', 'no reason stated')}")}
    rec_basis = (record.get("scope") or {}).get("activity_basis")
    if rec_basis not in KNOWN_BASES:
        return {"verdict": J_UNDETERMINED, "code": "ACTIVITY_BASIS_UNUSABLE",
                "reason": (f"the total-power record's activity basis is "
                           f"{rec_basis!r}; a power figure whose activity "
                           f"model is unknown cannot be judged against a "
                           f"threshold")}
    req_basis = (requirement.get("scope") or {}).get("activity_basis")
    if req_basis is not None and req_basis != rec_basis:
        return {"verdict": J_UNDETERMINED, "code": "ACTIVITY_BASIS_MISMATCH",
                "reason": (f"the requirement is declared against "
                           f"{req_basis!r} activity and the measurement is "
                           f"{rec_basis!r} — different metrics, so this is "
                           f"UNDETERMINED and not a verdict")}
    total_w = record["value"]
    max_w = requirement["max_w"]
    out = {"verdict": J_PASS if total_w <= max_w else J_FAIL,
           "code": "COMPARED",
           "total_power_w": total_w, "total_power_uw": total_w / _MICRO,
           "limit_w": max_w,
           "limit_uw": (requirement.get("max_uw")
                        if requirement.get("max_uw") is not None
                        else max_w / _MICRO),
           "utilization": total_w / max_w if max_w else None,
           "activity_basis": rec_basis,
           "basis_policed": req_basis is not None,
           "authority": requirement.get("authority"),
           "authority_file": requirement.get("file")}
    if req_basis is None:
        out["reason"] = (
            f"the requirement ({requirement.get('authority')}) declares no "
            f"activity basis, so it bounds a {rec_basis} number without "
            f"knowing that is what it bounds")
    return out


# ── the instance document ──────────────────────────────────────────────────
SCHEMA_POWER = "vibeic.ppa.power.v1"
#: The schema this document is written against. Versioned by filename; a change
#: is v2, because something has already hashed against v1 by the time anyone
#: wants to change it.
SCHEMA_PATH = "schemas/ppa/power.v1.schema.json"


def power_document(report: Dict[str, Any], *, stage: Optional[str] = None,
                   scenario: str = "default",
                   project: Optional[Path] = None,
                   extra_scope: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    """One `vibeic.ppa.power.v1` document for one power artefact.

    The activity block sits at the top level as well as inside every record's
    scope, on purpose: a reader who wants to know whether this document may be
    compared to another one must not have to reach into an array to find out.
    """
    return {
        "schema": SCHEMA_POWER,
        "scenario": scenario,
        "stage": stage,
        "activity": report.get("activity") or {},
        "metrics": metric_records(report, stage=stage, scenario=scenario,
                                  project=project, extra_scope=extra_scope),
        "split_consistency": report.get("split_consistency"),
        "group_sum_consistency": report.get("group_sum_consistency"),
        "source": _source(report),
    }


# ── the sign-off companion: reports/phase3/power.json ──────────────────────
#
# THE DEFECT THIS EXISTS TO CLOSE. MEASURED on a signed-off run: the runner
# wrote a 2,616-byte `power.rpt` carrying OpenSTA's own group table --
#
#     Group            Internal  Switching   Leakage     Total
#     Sequential       1.41e-03   6.97e-05  2.62e-08  1.48e-03  15.6%
#     ...
#     Total            7.35e-03   2.19e-03  1.37e-06  9.54e-03 100.0%
#
# -- and beside it a 152-byte `power.json` reading, in full,
#
#     {"tool": "opensta", "source": "reports/phase3/power.rpt",
#      "analysis_mode": "vectorless_sdc", "verdict": "PASS",
#      "evidence": "report_power output below"}
#
# A verdict, a pointer, and the word "evidence" over a document with no
# evidence in it -- there is no output below, the file ends there. The
# release reader asked the only question that matters of a power record,
# "is there a power number in here", and refused the product documents:
#
#     POWER_NO_TOTAL [power] reports/phase3/power.json: the power record
#     carries no power number anywhere -- no total, no per-group figure. A
#     Power section written over it prints a consumption nobody estimated.
#
# It was right to. 9.54 mW was measured, by this tree, and no machine-readable
# artefact of the run said so.
#
# THE RULE, and it is the whole point of the function: a verdict is a
# statement ABOUT a number, so a record may not carry one without carrying the
# other. When the report yields no total, this writer does not downgrade the
# claim and it does not invent a zero -- it declines to state a verdict at
# all and says, by name, that nothing was measured and why.

#: The verdict a power record carries when it has a total to stand on. Only
#: this spelling is a claim; everything else is a disclosure.
POWER_VERDICT_MEASURED = "PASS"

#: What the SESSION stamped about what it linked (`POWER_BASIS:` in the
#: report's envelope, written by `_emit_power_report`).
_POWER_BASIS_RE = re.compile(
    r"(?:^|\n)\s*#?\s*POWER_BASIS\s*:\s*(?P<basis>[A-Z_]+)")

#: The bases on which a number IS a measurement of the design being taped out.
#: Both link the ROUTED netlist; the no-SPEF one computes switching power
#: without parasitics and says so, which is a caveat on a real measurement.
POWER_SIGNOFF_BASES = frozenset({"POST_ROUTE_SPEF", "POST_ROUTE_NO_SPEF"})

#: And the one on which it is NOT. The runner's own note, at the point it
#: stamps this basis, says why: the pre-PnR netlist "carries no clock tree, so
#: its Clock group reads 0.000 and its total UNDERSTATES the routed design". A
#: figure known to understate the thing being taped out is not that thing, and
#: step 33 is a SIGN-OFF step. It may be published as an estimate; it may not
#: stand as the sign-off number.
POWER_ESTIMATE_BASIS = "PRE_LAYOUT_ESTIMATE"


def _row_number(row: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    if not isinstance(row, dict):
        return None
    val = row.get(key)
    return float(val) if isinstance(val, (int, float)) and not isinstance(
        val, bool) else None


def verdict_is_backed_by_a_number(record: Optional[Dict[str, Any]]) -> bool:
    """Does this power record state a verdict it has a measurement for?

    ONE function, called by the writer before it emits and by the test that
    proves the writer cannot emit otherwise. A second copy of this question
    would be a second answer, and the two would drift the way the report and
    its companion already did.
    """
    if not isinstance(record, dict):
        return False
    verdict = str(record.get("verdict") or "").strip().upper()
    if verdict != POWER_VERDICT_MEASURED:
        # Not a claim: a record that declines to judge owes no number.
        return True
    return isinstance(record.get("total_power_w"), (int, float)) and \
        not isinstance(record.get("total_power_w"), bool)


def signoff_record(report: Optional[Dict[str, Any]], *,
                   source: str,
                   analysis_mode: Optional[str] = None,
                   tool: str = "opensta") -> Dict[str, Any]:
    """The `reports/phase3/power.json` companion to a `report_power` artefact.

    `report` is `read_power_report`'s output, or None when the file could not
    be read -- and those are different facts, kept different here.
    """
    unreadable = report is None
    report = report or {}
    total_row = report.get("total_row")
    rows = [r for r in (report.get("rows") or []) if isinstance(r, dict)]

    total_w = _row_number(total_row, "total_w")
    record: Dict[str, Any] = {
        "tool": (report.get("tool") or tool),
        "tool_version": report.get("tool_version"),
        "source": source,
        "analysis_mode": analysis_mode,
        # The basis, CORROBORATED against the transcript rather than taken
        # from its own label -- see this module's header on why a declared
        # `vector_vcd` is a claim and not a measurement.
        "activity": report.get("activity") or {},
    }

    if total_w is None:
        record["power_measurement"] = STATUS_NOT_MEASURED
        # NO VERDICT. The writer refuses rather than downgrades: "PASS" here
        # would be a judgement with nothing behind it, and "FAIL" would be a
        # judgement this writer has no standing to make.
        record["verdict"] = STATUS_NOT_MEASURED
        record["power_not_measured_reason"] = (
            f"{source} could not be read, so no power figure was recovered"
            if unreadable else
            f"{source} was read and carries no OpenSTA report_power total "
            f"row, so there is no power number to publish; a verdict is not "
            f"stated over an absent measurement")
        record["evidence"] = f"{source} (read, no total row)"
        return record

    # ONE MODULE, ONE ANSWER. `activity_provenance` already decided whether
    # this report's stated activity basis survives its own transcript, and
    # `metric_records` already refuses a CONTRADICTED one as STATUS_INVALID --
    # a vector claim refuted by `READ_VCD_FAIL` or `Annotated 0 pin
    # activities.` is not silently a vectorless measurement either, because
    # what the tool did with zero annotated activities is a claim this
    # repository has not measured. Publishing MEASURED/PASS here while the
    # neighbouring reader publishes INVALID for the same Total is the module
    # disagreeing with itself, and `_power_class` would then present it as the
    # run's vector-driven sign-off power. MEASURED by the pre-landing review,
    # 2026-09-23.
    # WHAT THE SESSION LINKED, carried rather than inferred. MEASURED by the
    # round-2 review: three different bases published the same MEASURED/PASS,
    # with nothing in the record saying which one the number came from.
    _power_basis = report.get("power_basis")
    record["power_basis"] = _power_basis
    record["signoff_basis"] = (_power_basis in POWER_SIGNOFF_BASES
                               if _power_basis else None)

    if _power_basis == POWER_ESTIMATE_BASIS:
        record["power_measurement"] = STATUS_NOT_MEASURED
        record["verdict"] = STATUS_NOT_MEASURED
        record["power_not_measured_reason"] = (
            f"{source} is stamped POWER_BASIS: {POWER_ESTIMATE_BASIS} — it "
            f"was computed on the PRE-PnR netlist, which carries no clock "
            f"tree, so its Clock group reads 0.000 and its total UNDERSTATES "
            f"the routed design. Step 33 is a sign-off step; this figure is "
            f"published as an estimate (pre_layout_estimate_w) and is not the "
            f"sign-off number")
        # The number is NOT lost. It is published under a name that says what
        # it is, and under no key naming power/total/watt, so the release
        # reader cannot mistake it for the sign-off total.
        record["pre_layout_estimate_w"] = total_w
        record["evidence"] = f"{source} (read; pre-layout estimate basis)"
        return record

    _basis = str((report.get("activity") or {}).get("basis") or "")
    if _basis == BASIS_CONTRADICTED:
        _corr = str((report.get("activity") or {}).get("reason") or "").strip()
        record["power_measurement"] = STATUS_NOT_MEASURED
        record["verdict"] = STATUS_NOT_MEASURED
        record["power_not_measured_reason"] = (
            f"{source} states an activity basis its own transcript refutes "
            f"(basis CONTRADICTED"
            + (f": {_corr}" if _corr else "")
            + "). The report's Total is not published: a vector claim its own "
              "transcript denies is not a vectorless measurement either, and "
              "this module's `metric_records` refuses the same number as "
              "INVALID")
        record["evidence"] = f"{source} (read; activity basis CONTRADICTED)"
        return record

    record["power_measurement"] = STATUS_MEASURED
    record["total_power_w"] = total_w
    for cat in ("internal", "switching", "leakage"):
        val = _row_number(total_row, f"{cat}_w")
        if val is not None:
            record[f"{cat}_power_w"] = val
    record["power_by_group"] = [
        {"group": r.get("group"),
         **{f"{c}_power_w": _row_number(r, f"{c}_w") for c in CATEGORIES}}
        for r in rows]
    # HOW MANY FIGURES THIS ANALYSIS PRODUCED, counted rather than inferred
    # from a key scan. MEASURED by the round-2 review: the published 'Power
    # datapoints' read 27 over a report carrying 24 -- the four totals plus
    # 5 groups x 4 columns -- because the consumer counted every number under
    # a power/total/watt key, which swept in `power_groups` (a COUNT) and the
    # `total_w` inside each of the two consistency blocks. A reader takes that
    # field as "how many numbers this analysis produced".
    record["power_figures"] = (
        sum(1 for k in ("total", "internal", "switching", "leakage")
            if _row_number(total_row, f"{k}_w") is not None)
        + sum(1 for r in rows for c in CATEGORIES
              if _row_number(r, f"{c}_w") is not None))
    record["power_scan"] = {"groups": len(rows)}
    # Published beside the number, never folded into it: the parser's own
    # arithmetic check that the split adds up and that the groups sum to the
    # total. A reader who distrusts the number can see whether the report
    # was self-consistent without re-parsing it.
    record["split_consistency"] = report.get("split_consistency")
    record["group_sum_consistency"] = report.get("group_sum_consistency")
    record["verdict"] = POWER_VERDICT_MEASURED
    record["evidence"] = (
        f"{source}: OpenSTA report_power Total row "
        f"{total_row.get('total_raw') or total_w} W over "
        f"{len(rows)} group(s)")
    return record


# The atomic writer the runner uses, imported the way `_ppa/timing.py` already
# does: `_ppa` is importable on its own (the tests do it), so the dependency is
# optional and the fallback is a plain write rather than a failure to load.
try:  # pragma: no cover - exercised by the runner, not by the unit path
    from _atomic_artefact import write_text as _atomic_write_text
except Exception:  # pragma: no cover
    _atomic_write_text = None


def retire_signoff_record(out: Path, reason: str,
                          notes: Optional[List[str]] = None) -> None:
    """Replace a power record whose report no longer exists or is not usable.

    MEASURED by the pre-landing review (2026-09-23). A record OUTLIVES the
    measurement it describes: run 1 succeeds and writes
    `{verdict: PASS, total_power_w: 9.54e-3}`; run 2 comes after an RTL change,
    the step regenerates, `sta` fails, `_emit_power_report` writes its
    'not computed' fallback and returns False -- so the emitter never runs and
    the file is never touched. The PREVIOUS LAYOUT's number now sits beside a
    report that says nothing was computed, `_ic_release_artefacts._power_class`
    finds it, and the release is documented with a power figure for a design
    that no longer exists. Nothing refuses it anywhere.

    A verdict about a measurement that has been superseded is the same defect
    as a verdict with no measurement, one run later. So the record is REPLACED
    -- not deleted, because silence would leave a reader unable to tell a run
    that never measured power from one whose measurement was withdrawn -- by a
    record that states NOT_MEASURED and carries no number under any key naming
    power, total or watt.
    """
    # RETIRING MEANS REPLACING SOMETHING. With nothing to replace it must do
    # NOTHING, and the asymmetry is not cosmetic: `_ic_release_artefacts.
    # _power_class` reads NUMBERS, never the record's own
    # `power_measurement`, so an ABSENT power.json means "Power rows
    # NOT_MEASURED, documents written" while a PRESENT one carrying no number
    # means POWER_NO_TOTAL and ALL release documents refused. Writing
    # unconditionally therefore made a FIRST-run power failure fatal to the
    # whole release, and flipped D3 step 33 from ABSENT to SUBSTANTIVE.
    # MEASURED by the round-2 review, 2026-09-23.
    if not Path(out).is_file():
        if notes is not None:
            notes.append(f"power.json: no record to retire (the run produced "
                         f"none): {reason}")
        return
    doc = {
        "source": None,
        "power_measurement": STATUS_NOT_MEASURED,
        "verdict": STATUS_NOT_MEASURED,
        "power_not_measured_reason": reason,
        "evidence": ("the previous record was retired: the measurement it "
                     "stated is no longer the one this run produced"),
    }
    payload = json.dumps(doc, indent=2) + "\n"
    try:
        if _atomic_write_text is not None:
            _atomic_write_text(out, payload)
        else:  # pragma: no cover
            Path(out).write_text(payload, encoding="utf-8")
    except OSError:  # pragma: no cover - a tree we cannot write is not ours
        return
    if notes is not None:
        notes.append(f"power.json retired (no usable power report): {reason}")


def emit_signoff_record(project: Path, power_rpt: Path, out: Path,
                        analysis_mode: str,
                        notes: List[str],
                        produced_after: Optional[float] = None,
                        tool_rc: Optional[int] = None) -> Dict[str, Any]:
    """Write `reports/phase3/power.json` beside a `report_power` artefact.

    HERE, NOT IN THE RUNNER, and the placement is the point.
    `test_ppa_runner_extraction_ledger` MEASURED the first version of this
    function sitting in `phase3_one_shot_runner.py` and named where it
    belonged:

        New PPA-named function(s) added to phase3_one_shot_runner.py:
          _emit_power_signoff_json  (line 59648)  -> belongs in _ppa/power.py
        The runner orchestrates: it calls `_ppa` modules, passes artefact
        paths and collects return codes.

    It was right, and the reason it was right is the reason this module exists:
    "what does this power artefact say" has ONE owner, and a second answer
    written inside the step that produced the artefact is how a report and its
    companion come to disagree.

    THE RULE IT ENFORCES, asserted rather than assumed: a verdict is a
    statement ABOUT a number, so the record may not carry one without the
    other. `signoff_record` makes the failing branch unreachable; if a later
    edit makes it reachable, the run stops HERE rather than three phases later
    in a release that cannot be documented, because the file this would write
    outlives the run that wrote it.
    """
    # THE RECORD IS BOUND TO THIS INVOCATION, and round 2 is why. A power
    # step can fail WITHOUT THE RUNNER KNOWING: `docker exec` fails before
    # bash starts, so the `> power.rpt` redirect never truncates, the previous
    # layout's report is still on disk, it clears both size floors, and the
    # non-zero rc is never read. A fresh power.json was then written
    # MEASURED/PASS from a report describing a design that no longer exists --
    # the same stale-record defect round 1 closed, reached through the one
    # path where nothing signals failure.
    #
    # Two independent bindings, because either alone leaves a hole: the tool's
    # own exit status, and whether the artefact was written by THIS call.
    _rel = str(power_rpt.relative_to(project))
    if power_rpt.is_file() and 'POST_ROUTE_SPEF' in power_rpt.read_text(errors='replace'):
        import _opensta_current as current
        try:
            current.power_binding(project)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            retire_signoff_record(out, f'current power input binding refused: {exc}', notes)
            return {'verdict': STATUS_NOT_MEASURED, 'power_measurement': STATUS_NOT_MEASURED,
                    'power_not_measured_reason': str(exc)}
    if tool_rc is not None and tool_rc != 0:
        retire_signoff_record(
            out, f"the power tool exited {tool_rc}; no measurement was "
                 f"produced by this run", notes)
        return {"verdict": STATUS_NOT_MEASURED,
                "power_measurement": STATUS_NOT_MEASURED,
                "power_not_measured_reason": f"the power tool exited {tool_rc}"}
    if produced_after is not None:
        try:
            _mtime = power_rpt.stat().st_mtime
        except OSError:
            _mtime = None
        if _mtime is None or _mtime < produced_after:
            retire_signoff_record(
                out, f"this run did not produce {_rel}: the file on disk "
                     f"predates this power step, so its number describes an "
                     f"earlier layout", notes)
            return {"verdict": STATUS_NOT_MEASURED,
                    "power_measurement": STATUS_NOT_MEASURED,
                    "power_not_measured_reason": (
                        f"this run did not produce {_rel}")}

    record = signoff_record(read_power_report(power_rpt),
                            source=_rel,
                            analysis_mode=analysis_mode)
    if not verdict_is_backed_by_a_number(record):
        # RETIRE BEFORE RAISING. Returning here without touching `out` leaves
        # the PREVIOUS run's PASS and its number on disk -- the same stale
        # record the review found on the `_emit_power_report` failure path,
        # reached through the assertion instead.
        retire_signoff_record(
            out, f"the record this run would have written states a verdict "
                 f"with no power number behind it: {record!r}")
        raise AssertionError(
            f"{out.name} would state a verdict with no power number: {record!r}")
    payload = json.dumps(record, indent=2) + "\n"
    if _atomic_write_text is not None:
        _atomic_write_text(out, payload)
    else:  # pragma: no cover - only when _ppa is used standalone
        Path(out).write_text(payload, encoding="utf-8")
    if record.get("power_measurement") != STATUS_MEASURED:
        notes.append("power.json states NOT_MEASURED: "
                     + str(record.get("power_not_measured_reason") or ""))
    return record


# ── PDN/EM SIZING BASIS: whose measurement, and which layout ───────────────
# Lifted out of phase3_one_shot_runner by that file's own taxonomy gate
# (test_ppa_runner_extraction_ledger): the runner orchestrates, PPA logic
# lives here.

#: The DEF every EM/IR measurement deck reads (`read_def .../routed.def`). One
#: spelling, so the producer that RECORDS the subject and the consumer that
#: CHECKS it cannot drift apart.
_PDN_EM_SUBJECT_DEF = "routed.def"


def _pdn_em_post_resize_check(project: Path, top: str, pdk: Any,
                              container: str,
                              emit_ir_em_reports: Callable[..., Any],
                              emit_em_current_authority: Callable[..., Any],
                              rerun_started_ns: Optional[int] = None
                              ) -> Tuple[str, str]:
    """Measure the second DEF before it can advance to GDS."""
    rpt3 = _pl.reports_phase3_dir(project)
    def_file = _pl.pnr_dir(project) / f"{top}.def"
    if not def_file.is_file():
        return "NOT_MEASURED", "PDN_EM_POSTCHECK_NO_DEF"
    # The second PnR may return success after writing intermediate DEFs while
    # leaving the old shipped DEF untouched. EM on that old file is not a
    # measurement of the requested width/pitch repair.
    if (rerun_started_ns is not None
            and def_file.stat().st_mtime_ns <= rerun_started_ns):
        return "NOT_MEASURED", "PDN_EM_POSTCHECK_STALE_DEF"
    notes: List[str] = []
    try:
        rpt3.mkdir(parents=True, exist_ok=True)
        em_rpt = rpt3 / "em.rpt"
        _ir_ok, em_ok = emit_ir_em_reports(project, top, pdk, container,
                                          rpt3 / "ir_drop.rpt", em_rpt, notes)
        if not em_ok:
            return "NOT_MEASURED", "PDN_EM_POSTCHECK_NATIVE_UNMEASURED: " + "; ".join(notes)
        if not em_rpt.is_file() or em_rpt.stat().st_mtime < def_file.stat().st_mtime:
            return "NOT_MEASURED", "PDN_EM_POSTCHECK_STALE_REPORT"
        if not emit_em_current_authority(project, pdk, container, notes):
            return "NOT_MEASURED", "PDN_EM_POSTCHECK_AUTHORITY_MISSING: " + "; ".join(notes)
        doc = json.loads((rpt3 / "em_current_authority.json").read_text())
        verdict = doc.get("verdict")
        if verdict == "PASS":
            return "PASS", "PDN_EM_JMAX_CLOSED: final DEF segment screen PASS"
        if verdict == "FAIL":
            count = (doc.get("jmax_screen") or {}).get("offender_count")
            return "FAIL", f"PDN_EM_JMAX_UNCLOSED: {count} final DEF segment(s) exceed Jmax"
        return "NOT_MEASURED", f"PDN_EM_POSTCHECK_UNRESOLVED: {verdict}"
    except Exception as exc:
        return "NOT_MEASURED", f"PDN_EM_POSTCHECK_ERROR: {exc}"


def _pdn_em_postcheck_reason_class(status: str, detail: str) -> str:
    """Classify an unavailable second-pass EM result by its producer cause."""
    if status != "NOT_MEASURED":
        return ""
    if detail.startswith("PDN_EM_POSTCHECK_NO_DEF"):
        return "input_absent"
    if detail.startswith("PDN_EM_POSTCHECK_STALE_DEF"):
        return "upstream_failed"
    if detail.startswith("PDN_EM_POSTCHECK_UNRESOLVED"):
        return "inconclusive"
    # Native PSM, report freshness, authority emission and exceptions failed
    # during execution. An earlier EM report cannot close this measurement.
    return "execution_error"


def _pdn_em_resize_chain_continues(pnr_row: Any, post_status: str,
                                   pnr_chain_continues: Callable[[Any], bool]
                                   ) -> bool:
    """A one-shot resize may proceed to GDS only after measured EM closure."""
    return pnr_chain_continues(pnr_row) and post_status == "PASS"


def _pdn_em_spent_on(project: Path) -> Optional[str]:
    """Digest of the DEF measured before re-PnR, retained for provenance.

    This digest alone cannot prove the resize took effect: a failed re-PnR may
    leave that exact DEF on disk. Binding needs the recorded width floor too.
    """
    return _pdn_em_subject_digest(project)

def _pdn_em_sentinel_binds(sentinel: Path, project: Path,
                           run_id: Optional[str] = None,
                           repair_class: Optional[str] = None
                           ) -> Tuple[bool, str]:
    """Bind a spent resize only if its floor reached this DEF, or this run spent it.

    The run id is the anti-loop bound while pass 2 is in flight or still narrow.
    A prior run's sentinel is evidence of an effective resize only when every
    recorded strap floor is present in the currently routed DEF.
    """
    if not sentinel.exists():
        return False, "no resize has been spent in this tree"
    try:
        doc = json.loads(sentinel.read_text())
    except (OSError, ValueError):
        return False, ("the sentinel could not be read, so it cannot be shown "
                       "to bound this design; the resize is not spent")
    if (run_id and isinstance(doc, Mapping)
            and doc.get("run_id") == run_id):
        return True, ("this run already spent its one resize; a crashed or "
                      "still-narrow second pass cannot buy a third")
    recorded = doc.get("spent_on_def") if isinstance(doc, Mapping) else None
    if not isinstance(recorded, str) or not recorded:
        return False, ("the sentinel names no layout (written before this "
                       "rule), so it cannot be shown to bound this pass")
    now = _pdn_em_spent_on(project)
    if now is None:
        return False, ("the routed DEF could not be read, so the sentinel "
                       "cannot be matched to a layout")
    applied = doc.get("applied")
    short = applied if isinstance(applied, list) and applied else doc.get("short")
    if not isinstance(short, list) or not short:
        return False, "the sentinel records no strap-width floor to verify"
    try:
        import em_current_density_check as _emcd
        drawn = _emcd._def_pg_widths_of(
            _pl.pnr_dir(project) / _PDN_EM_SUBJECT_DEF)
    except Exception:
        drawn = {}
    floors = {}
    for row in short:
        if not isinstance(row, Mapping) or not isinstance(row.get("layer"), str):
            return False, "the sentinel has an invalid strap-width floor"
        try:
            width = float(row["width_um"] if short is applied else row["w_em_um"])
        except (KeyError, TypeError, ValueError):
            return False, "the sentinel has an invalid strap-width floor"
        if not math.isfinite(width) or width <= 0:
            return False, "the sentinel has an invalid strap-width floor"
        layer = row["layer"].lower()
        floors[layer] = max(width, floors.get(layer, 0.0))
    missing = [layer for layer, floor in floors.items()
               if drawn.get(layer, 0.0) + 1e-9 < floor]
    if missing:
        return False, ("the previous resize did not take effect: the routed "
                       "DEF is below its recorded floor on "
                       + ", ".join(sorted(missing)))
    if (repair_class and isinstance(doc, Mapping)
            and doc.get("repair_class") != repair_class):
        return False, ("a previous run spent a different PDN remedy; "
                       "this architecture remedy has not been tried")
    return True, ("the previous resize took effect: every recorded strap "
                  "floor is present in the routed DEF")


def _pdn_em_subject_digest(project: Path) -> Optional[str]:
    """sha256 of the layout an EM measurement is being taken on, RIGHT NOW.

    Called by the emitter at measurement time, so the digest it records is the
    subject's, and by the consumer to digest the layout in front of it. None
    when the DEF cannot be read — which is a third state, not a mismatch.
    """
    try:
        return hashlib.sha256(
            (_pl.pnr_dir(project) / _PDN_EM_SUBJECT_DEF).read_bytes()
        ).hexdigest()
    except OSError:
        return None


def _pdn_em_measures_this_layout(rpt3: Path, project: Path) -> Tuple[bool, str]:
    """Does the EM measurement on disk describe the layout we have NOW?

    WHY NOT mtime, AND WHY NOT `_pdn_em_measured_subject`. An earlier draft of
    this fix asked "was the file written during this run?". That is not
    identity: a same-build re-run that cache-hits the PnR DEF has a measurement
    of EXACTLY this layout, and refusing it by clock would discard an accurate
    number and republish the sizing record as NOT_DERIVED for a DEF that WAS
    drawn with the floor -- two runs, identical inputs, different artefacts.

    `_pdn_em_measured_subject` cannot answer either, and the reason is worth
    stating because it looks like it can: it digests the DEF **at read time**,
    so comparing its `def_sha256` to the DEF on disk compares the file with
    itself and is TRUE always. A check that cannot fail is not a check.

    So the subject digest has to be RECORDED BY THE PRODUCER at measurement
    time (`subject_def_sha256` in em.json), and a measurement that does not
    carry one cannot be shown to describe this layout. That is declined, not
    accepted: a legacy artefact is exactly the stale-basis case this closes.
    """
    try:
        doc = json.loads((rpt3 / "em.json").read_text())
    except (OSError, ValueError):
        return False, "reports/phase3/em.json could not be read"
    recorded = doc.get("subject_def_sha256") if isinstance(doc, Mapping) else None
    if not isinstance(recorded, str) or not recorded:
        return False, ("reports/phase3/em.json records no subject_def_sha256 "
                       "(written before this rule), so it cannot be shown to "
                       "measure the layout this pass has")
    now = _pdn_em_subject_digest(project)
    if now is None:
        return False, (f"phase3/stage3/pnr/{_PDN_EM_SUBJECT_DEF} could not be "
                       f"read, so the measurement's subject cannot be checked")
    if now != recorded:
        return False, (f"reports/phase3/em.json measures {recorded[:12]}… but "
                       f"the layout on disk is {now[:12]}… — a different "
                       f"design state")
    return True, (f"reports/phase3/em.json measures {recorded[:12]}…, which is "
                  f"the layout this pass has")


def _pdn_em_declared_current(project: Path,
                             pdk_nominal_v: Optional[float] = None
                             ) -> Tuple[Optional[float], Optional[str], str]:
    """The supply current the DESIGN declares, as I = P / V. (I, source, gap)

    R-0924-3: `input/` and `phase1/` are the design's; a file the FLOW wrote is
    not evidence for the next run's decisions. The declared power budget is the
    only current that is BOTH available at PDN time (before any route exists)
    and not written by a previous run.

    WHERE THE VOLTAGE COMES FROM, AND WHY NOT THE L DOC. An earlier draft read
    `supply_voltage_v` from L19 and was UNREACHABLE on every flow-produced
    project: the generated L19 carries `fields.power_budget_uw` and NO voltage
    field at all (measured on spm run23 -- the only power/voltage key in the
    whole document is `fields.power_budget_uw`). A rung no real design can
    climb is not a fallback. The voltage therefore comes from the PDK's own
    liberty `nom_voltage`, which the run has already resolved for timing, and
    the L doc is consulted first only so a design MAY override it.

    `gap` names precisely what is missing, because "no budget declared" and
    "a budget with no voltage to divide it by" are different facts and a
    reader who is told the wrong one goes looking in the wrong file.
    """
    p_uw: Optional[float] = None
    v: Optional[float] = None
    src = ""
    for rel in ("phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
                "input/docs/L19_CONSTRAINTS_PDK.json"):
        try:
            doc = json.loads((project / rel).read_text())
        except (OSError, ValueError):
            continue
        for holder in (doc.get("fields") if isinstance(doc, Mapping) else None,
                       doc.get("power") if isinstance(doc, Mapping) else None,
                       doc):
            if not isinstance(holder, Mapping):
                continue
            if p_uw is None and isinstance(holder.get("power_budget_uw"),
                                           (int, float)):
                p_uw = float(holder["power_budget_uw"])
                src = f"{rel} power_budget_uw"
            for vk in ("supply_voltage_v", "nominal_voltage_v"):
                if v is None and isinstance(holder.get(vk), (int, float)):
                    v = float(holder[vk])
                    src += f" / {vk}"
        if p_uw is not None:
            break
    if p_uw is None or p_uw <= 0:
        return None, None, ("phase1/generated_docs/L19_CONSTRAINTS_PDK.json "
                            "declares no power_budget_uw")
    if v is None and pdk_nominal_v is not None:
        v = float(pdk_nominal_v)
        src += " / PDK liberty nom_voltage"
    if v is None or v <= 0:
        return None, None, (
            f"a power budget IS declared ({p_uw} uW) but no supply voltage to "
            f"divide it by: the L doc states none and the PDK liberty states "
            f"no nom_voltage")
    return (p_uw * 1e-6) / v, src, ""


# Layout identity and resize-spend authority live with the power evidence.
_PDN_EM_RESIZE_SENTINEL = ".pdn_em_resize_done"
_PDN_EM_RUN_ID = __import__("os").urandom(16).hex()
_PDN_EM_LAYOUT_IDENTITY = ".pdn_em_layout_identity.json"


def _runner_context():
    """Resolve orchestration hooks without importing the runner at module load."""
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "_producer_identity_now"):
        return main
    return sys.modules.get("phase3_one_shot_runner") or importlib.import_module(
        "phase3_one_shot_runner")

def _pdn_em_input_identity(project: Path, top: str, pdk: "PdkConfig",
                           container: str, die_um: str, util: float,
                           spare_density: Any) -> Optional[Dict[str, Any]]:
    """Identity of the inputs that can change a PnR layout. Unknown is no reuse.

    The tool image and producer recipe are resolved by the same helpers used
    for phase-3 provenance. All declared input and generated L-doc bytes are
    included, so a new floorplan declaration invalidates the old floor.
    """
    try:
        import _eda_pin
        image, _ = _eda_pin.container_image_digest(container)
        producer = _runner_context()._producer_identity_now()
        netlist, _, _ = _runner_context().pnr_input_netlist(project, top)
        sdc = _runner_context()._resolve_staged_silicon_sdc(project)
        if (not image or not producer.get("plugin_version")
                or not producer.get("recipe_sha256") or not netlist.is_file()
                or (sdc is not None and not sdc.is_file())):
            return None
        files = {"netlist": hashlib.sha256(netlist.read_bytes()).hexdigest(),
                 "sdc": (hashlib.sha256(sdc.read_bytes()).hexdigest()
                         if sdc else "AUTO_FROM_DESIGN_DOCS")}
        for root_name, root in (("input", project / "input"),
                                ("docs", _pl.generated_docs_dir(project))):
            if root.is_dir():
                for path in sorted(p for p in root.rglob("*") if p.is_file()):
                    files[f"{root_name}/{path.relative_to(root)}"] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        pdk_fields = vars(pdk).copy()
        for key in ("tech_lef", "cell_lef", "liberty"):
            source = pdk_fields.get(key)
            content = _runner_context()._read_pdk_text(source, container) if source else None
            if not content:
                return None
            pdk_fields[key + "_sha256"] = hashlib.sha256(
                content.encode()).hexdigest()
        payload = {"files": files, "top": top, "die_um": die_um,
                   "util": util, "spare_density": spare_density,
                   "pdk": pdk_fields, "tool_image": image,
                   "producer": producer}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                            default=str).encode()).hexdigest()
        return {"sha256": digest, "tool_image": image,
                "producer": producer}
    except (OSError, ValueError, TypeError):
        return None


def _pdn_em_reusable_floor(project: Path, identity: Optional[Dict[str, Any]]
                           ) -> Optional[Dict[str, Any]]:
    """Reuse only a measured floor whose source and final drawn layout bind."""
    if identity is None:
        return None
    pnr = _pl.pnr_dir(project)
    sentinel = pnr / _PDN_EM_RESIZE_SENTINEL
    try:
        doc = json.loads(sentinel.read_text())
        layout = json.loads((pnr / _PDN_EM_LAYOUT_IDENTITY).read_text())
        floor = doc.get("floor")
        if (doc.get("input_identity") != identity
                or layout.get("input_identity") != identity
                or layout.get("def_sha256") != _pdn_em_subject_digest(project)
                or not isinstance(floor, dict) or not floor.get("per_layer")
                or doc.get("measurement_subject_sha256") != doc.get("spent_on_def")):
            return None
        binds, _ = _pdn_em_sentinel_binds(sentinel, project)
        if not binds:
            return None
        # The sentinel's `short` names only layers that needed widening on
        # pass 1. Prove the FULL reusable floor on every stripe the final
        # PnR deck drew; otherwise a partial/mismatched record could borrow
        # a floor that the final DEF never implemented.
        import em_current_density_check as _emcd
        drawn = _emcd._def_pg_widths_of(
            pnr / _PDN_EM_SUBJECT_DEF) or {}
        deck = (pnr / "pnr.tcl").read_text(errors="replace")
        straps = {m.group(1).lower() for m in re.finditer(
            r"add_pdn_stripe\b[^\n]*?-layer\s+(\S+)[^\n]*", deck)
            if "-followpins" not in m.group(0)}
        if not straps:
            return None
        selected = {str(r["layer"]).lower(): float(r["width_um"])
                    for r in doc.get("applied", [])
                    if isinstance(r, Mapping) and r.get("layer") and r.get("width_um")}
        for layer in straps:
            row = floor["per_layer"].get(layer)
            width = selected.get(layer, float(row["w_em_um"]) if row else 0.0)
            if width and drawn.get(layer, 0.0) + 1e-9 < width:
                return None
        return floor
    except Exception:  # nosec — uncertain proof must keep the old floorless path
        return None


def _record_pdn_em_resize_spend(project: Path, decision: Mapping[str, Any]
                                ) -> bool:
    """Record this run's spend before re-PnR; refuse the pass if it cannot bind."""
    sentinel = decision["sentinel"]
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        proof: Dict[str, Any] = {}
        try:
            layout = json.loads((sentinel.parent /
                                 _PDN_EM_LAYOUT_IDENTITY).read_text())
            measured = json.loads((_pl.reports_phase3_dir(project) /
                                   "em.json").read_text())
            subject = _pdn_em_spent_on(project)
            if (layout.get("def_sha256") == subject
                    and measured.get("subject_def_sha256") == subject
                    and layout.get("input_identity")):
                proof = {"input_identity": layout["input_identity"],
                         "measurement_subject_sha256": subject,
                         "floor": decision["floor"]}
        except (OSError, ValueError, AttributeError):
            pass
        sentinel.write_text(json.dumps({
            "reason": "pdn_em_first_pass_resize",
            "spent_on_def": _pdn_em_spent_on(project),
            "run_id": _PDN_EM_RUN_ID,
            "repair_class": decision.get("repair_class"),
            "short": decision["short"],
            "applied": decision.get("floor", {}).get("applied", []),
            **proof,
        }, indent=2) + "\n")
        return True
    except OSError as exc:
        print(f"[pnr] PDN_EM_RESIZE_SENTINEL_WRITE_FAILED: {exc}; "
              "no re-PnR dispatched", file=sys.stderr)
        return False


# ── T106 — STEP 33 FROM THE TOOL: STAPostPNR's per-corner report_power ──────
#
# LibreLane `OpenROAD.STAPostPNR` runs `report_power -corner <c>` for every STA
# corner on the post-PnR state with that corner's SPEF (`sta/corner.tcl`), and
# writes it to `<corner>/power.rpt`. Its `power__total` METRIC is written
# WITHOUT a `__corner:` modifier by every corner process, and
# `OpenROAD.STAPostPNR.run` merges the corners' metric dicts in `STA_CORNERS`
# order, so the value that survives is the LAST listed corner's; the metric's
# declared `sum_aggregator` never sees a per-corner key. MEASURED on spm
# (0.3.79): `power__total` 26.46 mW = max_ff (last in STA_CORNERS) while
# nom_tt reads 20.76 mW; t89_ref_077 likewise 11.37 mW = max_ff vs nom_tt
# 8.78 mW. The metric is therefore never read here; the per-corner reports are.
#
# The tool reads no activity file (`backends/librelane.py`, measured: zero
# `read_vcd`/`read_saif` in the installed tool), so its basis is VECTORLESS by
# construction. A corner whose transcript shows an activity read contradicts
# that and is refused rather than relabelled.

_ACTIVITY_READ_RE = re.compile(
    r"^\s*(read_vcd|read_saif|read_power_activities|set_power_activity)\b", re.M)
_CORNER_LIB_RE = re.compile(
    r"^Reading cell library for the '([^']+)' corner at '([^']+)'", re.M)


def stapostpnr_corner_power(sta_folder: Path) -> Dict[str, Any]:
    """{corner: power record} from every analysed corner's `power.rpt`."""
    corners: Dict[str, Any] = {}
    for folder in sorted(p for p in Path(sta_folder).iterdir()
                         if (p / "sta.log").is_file()):
        report = read_power_report(folder / "power.rpt")
        log = (folder / "sta.log").read_text(errors="replace")
        libs = [path for name, path in _CORNER_LIB_RE.findall(log)
                if name == folder.name]
        row: Dict[str, Any] = {"report": str(folder / "power.rpt"),
                               "liberties": libs}
        total = (report or {}).get("total_row")
        if total is None:
            row.update(status=STATUS_NOT_MEASURED,
                       reason="no report_power Total row in the corner report")
        elif _ACTIVITY_READ_RE.search(log):
            row.update(status=STATUS_INVALID, basis=BASIS_CONTRADICTED,
                       reason="the corner transcript reads activity; the tool "
                              "is measured to be vectorless by construction")
        else:
            row.update(status=STATUS_MEASURED, basis=BASIS_VECTORLESS,
                       sha256=report.get("sha256"),
                       **{f"{c}_w": total[f"{c}_w"] for c in CATEGORIES},
                       total_raw=total["total_raw"])
        corners[folder.name] = row
    return corners


def _printed_half_unit(raw: Optional[str]) -> Optional[float]:
    """Half a unit in the last digit a report printed: what a number read back
    from it can be trusted to. `2.15e-02` -> 5e-05; `8.777829e-03` -> 5e-10."""
    m = re.fullmatch(r"[+-]?(\d*)\.?(\d*)(?:[eE]([+-]?\d+))?", (raw or "").strip())
    if not m or not (m.group(1) or m.group(2)):
        return None
    return 0.5 * 10.0 ** (int(m.group(3) or 0) - len(m.group(2)))


def signoff_power_arms(direct: Optional[Dict[str, Any]],
                       direct_report: Optional[Dict[str, Any]],
                       corners: Dict[str, Any], *,
                       direct_liberty: Optional[str],
                       direct_spef_sha256: Optional[str],
                       tool_spef_sha256: Dict[str, str]) -> Dict[str, Any]:
    """Which arm carries step 33's sign-off power, and whether the two agree.

    The engine is the same (OpenSTA `report_power`), so the choice is FIDELITY,
    never the smaller number:

    * the direct arm is canonical only when its activity basis is a VECTOR read
      the transcript CORROBORATES (`Annotated N pin activities`, N > 0);
    * otherwise the tool's per-corner vectorless reports are canonical, and the
      reported total is the largest analysed corner's (a budget is a ceiling).

    AGREEMENT: a vectorless direct session and the tool corner that read the
    SAME liberty file and the SAME SPEF bytes must agree to within what the two
    reports' printed digits resolve. Different parasitics or a different
    liberty is NOT_COMPARABLE -- declared, never a disagreement.
    """
    measured = {c: r for c, r in corners.items() if r.get("status") == STATUS_MEASURED}
    activity = (direct or {}).get("activity") or {}
    vector = (activity.get("basis") in _VECTOR_BASES
              and activity.get("corroboration") == CORROBORATED)
    out: Dict[str, Any] = {"direct_basis": activity.get("basis"),
                           "direct_corroboration": activity.get("corroboration"),
                           "tool_corners": corners}
    if vector:
        out.update(canonical="direct", reason=(
            "the direct arm's activity basis is a corroborated vector read; the "
            "tool is vectorless by construction"))
    elif measured and len(measured) == len(corners):
        worst = max(measured, key=lambda c: measured[c]["total_w"])
        out.update(canonical="librelane", worst_corner=worst,
                   total_power_w=measured[worst]["total_w"], reason=(
                       "no corroborated vector basis: sign-off power is the tool's "
                       "vectorless report at every analysed corner"))
    else:
        out.update(canonical=None, reason="LL_POWER_CORNER_NOT_MEASURED: " + ", ".join(
            sorted(set(corners) - set(measured))) if corners else "no analysed corner")
    # The agreement check, on the corner(s) that read the direct deck's inputs.
    same = [c for c, r in measured.items()
            if direct_liberty and any(Path(p).name == Path(direct_liberty).name
                                      for p in r.get("liberties") or [])
            and direct_spef_sha256 and tool_spef_sha256.get(c) == direct_spef_sha256]
    total = _row_number((direct_report or {}).get("total_row"), "total_w")
    if vector or total is None:
        out["agreement"] = {"verdict": "NOT_COMPARABLE", "reason": (
            "the direct arm is vector-driven" if vector else
            "the direct arm has no measured total")}
    elif len(same) != 1:
        out["agreement"] = {"verdict": "NOT_COMPARABLE", "matched_corners": same,
                            "reason": "no single tool corner read the direct "
                                      "deck's liberty AND SPEF bytes"}
    else:
        tool = measured[same[0]]
        bound = ((_printed_half_unit(direct_report["total_row"].get("total_raw")) or 0.0)
                 + (_printed_half_unit(tool.get("total_raw")) or 0.0))
        delta = abs(total - tool["total_w"])
        out["agreement"] = {"verdict": "AGREE" if delta <= bound else "DISAGREE",
                            "corner": same[0], "direct_w": total,
                            "tool_w": tool["total_w"], "delta_w": delta,
                            "resolution_w": bound}
    return out


def tool_power_report_text(corner: str, row: Dict[str, Any], report_text: str,
                           state_sha256: str) -> str:
    """The step-33 `power.rpt` when the tool arm is canonical: the tool's own
    corner report, byte for byte, under an envelope naming where it came from
    and the stamps the step-33 readers take (`POWER_ANALYSIS_MODE`,
    `POWER_BASIS`, `STA_BASIS`). Nothing in the report body is edited."""
    return (
        "# OpenSTA report_power -- LibreLane OpenROAD.STAPostPNR corner report,\n"
        "# handed to step 33 unedited (T106).\n"
        "# tool: opensta\n"
        f"# source: {row['report']}\n"
        f"# source_sha256: {row.get('sha256')}\n"
        f"# stapostpnr_state_sha256: {state_sha256}\n"
        f"# corner: {corner} (the largest total of the analysed corners)\n"
        f"# liberty: {Path((row.get('liberties') or ['unstated'])[0]).name}\n"
        f"# liberties_read: {' '.join(Path(p).name for p in row.get('liberties') or [])}\n"
        "# STA_BASIS: POST_ROUTE_SPEF\n"
        "# Every analysed corner is recorded in reports/phase3/power_arms.json.\n"
        "# Group rows: Sequential / Combinational / Clock / Macro / Pad; each\n"
        "# carries Internal, Switching and Leakage (static) Power, then the total.\n"
        "POWER_ANALYSIS_MODE: vectorless_sdc\n"
        "POWER_BASIS: POST_ROUTE_SPEF\n"
        f"POWER_BASIS_CORNER: {corner}\n"
        "# === Begin OpenSTA Power Report ===\n"
        + report_text)


def em_power_basis(log: str, *, sdc: Optional[str], spef: Optional[str],
                    spef_reason: Optional[str], liberties: Sequence[str],
                    uncalibrated: Optional[str] = None,
                    basis_id: Optional[str] = None) -> Dict[str, Any]:
    """What the EM currents were computed from: the inputs read and OpenSTA's
    own power split (the `report_power` the session printed between its
    EM_POWER_BASIS markers). `clock_reaches_network` is False when clocks are
    defined yet the clock group draws nothing -- the clock stopped at a cell
    with no timing view, and every current is then understated.
    `uncalibrated` (the caller's `instrument_calibration` refusal) withholds
    that judgement. `basis_id` is the declared basis's id
    (`dynamic_ir_vectored_emit.power_basis`), the same one the static IR and
    the transient IR records carry."""
    body = log.split("=== EM_POWER_BASIS ===", 1)[-1].split("=== EM_POWER_BASIS_END ===", 1)[0] \
        if "=== EM_POWER_BASIS ===" in log else ""
    groups: Dict[str, float] = {}
    for m in re.finditer(r"^(Sequential|Combinational|Clock|Macro|Pad|Total)\s+"
                         r"(?:\S+\s+){3}(\S+)", body, re.M):
        try:
            groups[m.group(1).lower()] = float(m.group(2))
        except ValueError:
            continue
    uncal = ("NOT_MEASURED", uncalibrated) if uncalibrated else None
    return {"basis_id": basis_id, "sdc": sdc, "spef": spef, "spef_not_read": spef_reason,
            "liberties": list(dict.fromkeys(liberties)),
            "power_W": groups or None,
            "clock_reaches_network": (None if uncal or not sdc or "clock" not in groups
                                      else groups["clock"] > 0),
            "calibration": f"uncalibrated: {uncal[1]}" if uncal else "CALIBRATED",
            "basis": ("declared SDC (propagated clocks) + step-22 SPEF + session liberties"
                      if sdc and spef else
                      "declared SDC (propagated clocks), no SPEF" if sdc else
                      "no SDC: OpenSTA default activity, not the design's clock")}


# ── Step 15's declared `pdn.done` (FX_LL21_DECLARED_OUTPUTS) ───────────────

def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, project: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(project).resolve()))
    except ValueError:
        return str(path)


def _def_supply_subject_sha256(path: Path) -> Optional[str]:
    """Hash the cells and POWER/GROUND grid a PDN measurement is about.

    Route DEFs may reorder BTerm connections and signal special nets while
    retaining the same supply grid. Canonicalize those harmless differences,
    but retain every cell, placement, supply connection and routed shape.
    An unparseable or absent population/grid cannot corroborate a zero count.
    """
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return None
    section = re.search(
        r"(?ms)^SPECIALNETS\s+(\d+)\s*;(.*?)^END SPECIALNETS\s*$", text)
    components = re.search(
        r"(?ms)^COMPONENTS\s+(\d+)\s*;(.*?)^END COMPONENTS\s*$", text)
    if section is None or components is None:
        return None
    rows = list(re.finditer(r"(?ms)^\s*-\s+(\S+)\s+(.*?);", section.group(2)))
    if len(rows) != int(section.group(1)):
        return None
    cells = [
        (m.group(1), m.group(2), re.sub(r"\s+", " ", m.group(3)).strip())
        for m in re.finditer(
            r"(?ms)^\s*-\s+(\S+)\s+(\S+)(.*?);", components.group(2))]
    if len(cells) != int(components.group(1)):
        return None
    supplies = []
    for row in rows:
        head, delimiter, tail = row.group(2).partition("+ USE ")
        if not delimiter:
            return None
        use = tail.split(None, 1)[0] if tail.split() else ""
        if use not in ("POWER", "GROUND"):
            continue
        connections = sorted(re.sub(r"\s+", " ", item).strip()
                             for item in re.findall(r"\([^()]*\)", head))
        supplies.append((row.group(1), connections,
                         re.sub(r"\s+", " ", tail).strip()))
    if not supplies:
        return None
    canonical = json.dumps({"components": sorted(cells),
                            "supplies": sorted(supplies)},
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


DIRECT_PDN_RECEIPT_NAME = "direct_pdn.receipt.json"


def _write_direct_pdn_receipt(pnr_out: Path, routed_def: Path,
                              invocation_output: str, pdn_ok: bool,
                              pdn_marker: str) -> Optional[Path]:
    """Bind this direct route's PDN marker to the DEF it actually emitted.

    Only step_pnr calls this after the route invocation returns. Canonicalize
    may consume the receipt, but cannot mint one from a sibling log.
    """
    receipt = Path(pnr_out) / DIRECT_PDN_RECEIPT_NAME
    receipt.unlink(missing_ok=True)
    log = Path(pnr_out) / "openroad.log"
    subject = _def_supply_subject_sha256(routed_def)
    source_sha = _sha256_of(log) if log.is_file() else None
    marker_line = re.compile(rf"(?m)^{re.escape(pdn_marker)}(?=[:\s]|$)")
    if (not pdn_ok or pdn_marker not in ("PDN_INSERTED", "PDN_INSERTED_ADAPTIVE")
            or not subject or not source_sha
            or not marker_line.search(invocation_output)
            or not marker_line.search(log.read_text(errors="replace"))):
        return None
    receipt.write_text(json.dumps({
        "schema": "vibeic.direct_pdn_receipt.v1",
        "producer": "phase3_one_shot_runner.step_pnr",
        "marker": pdn_marker,
        "log_sha256": source_sha,
        "routed_def": Path(routed_def).name,
        "routed_def_sha256": _sha256_of(routed_def),
        "supply_subject_sha256": subject,
    }, sort_keys=True, indent=2) + "\n")
    return receipt


def _direct_pdn_receipt_matches(pnr_out: Path, source_sha: Optional[str],
                                supply_subject: Optional[str],
                                pdn_marker: str) -> bool:
    receipt = Path(pnr_out) / DIRECT_PDN_RECEIPT_NAME
    try:
        rec = json.loads(receipt.read_text())
    except (OSError, ValueError):
        return False
    return (isinstance(rec, dict)
            and rec.get("schema") == "vibeic.direct_pdn_receipt.v1"
            and rec.get("producer") == "phase3_one_shot_runner.step_pnr"
            and rec.get("marker") == pdn_marker
            and source_sha is not None and rec.get("log_sha256") == source_sha
            and supply_subject is not None
            and rec.get("supply_subject_sha256") == supply_subject)


def librelane_pdn_evidence(project: Path) -> Optional[Dict[str, Any]]:
    """The power-grid verdict LibreLane's OWN step-15 chain measured, or None.

    On the LibreLane path the grid is built by LibreLane's PDN step and judged
    by its power-grid checker; `pnr.tcl` never runs `pdngen`, so the PnR
    transcript carries none of the direct deck's `PDN_*` markers. The chain
    is the one the floorplan handoff record names
    (`reports/phase3/librelane_floorplan_handoff.json` -> `state`), read under
    THIS project (the record stores an absolute path). LibreLane carries a
    metric forward in later states. A carried zero cannot erase a nonzero
    measurement from this chain; the highest observed count is retained, and
    every state and the selected source DEF bind the freshness key.
    chip- and PDK-agnostic: the metric names are LibreLane's."""
    project = Path(project)
    rec = project / "reports/phase3/librelane_floorplan_handoff.json"
    try:
        parts = Path(json.loads(rec.read_text())["state"]).parts
        k = next(i for i in range(len(parts) - 1)
                 if parts[i] == "phase3" and parts[i + 1] == "librelane")
        chain = project.joinpath(*parts[k:]).parent.parent
        steps = sorted((d for d in chain.iterdir()
                        if d.is_dir() and d.name.split("-", 1)[0].isdigit()),
                       key=lambda d: int(d.name.split("-", 1)[0]))
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return None
    measured: List[Dict[str, Any]] = []
    chain_inputs: List[Tuple[str, str]] = []
    for d in steps:
        so = d / "state_out.json"
        try:
            state = json.loads(so.read_text())
            metrics = state.get("metrics") or {}
        except (OSError, ValueError, AttributeError):
            continue
        chain_inputs.append((_rel(so, project), _sha256_of(so)))
        n = metrics.get("design__power_grid_violation__count")
        if not isinstance(n, (int, float)) or isinstance(n, bool):
            continue
        per_net = {k.rsplit(":", 1)[-1]: v for k, v in metrics.items()
                   if k.startswith("design__power_grid_violation__count__net:")}
        source_def = Path(state.get("def") or "")
        if not source_def.is_absolute():
            source_def = project / source_def
        try:
            in_project = source_def.resolve().is_relative_to(project.resolve())
        except (OSError, RuntimeError):
            in_project = False
        measured.append({"step": _rel(d, project),
                         "state_sha256": chain_inputs[-1][1],
                         "count": int(n), "per_net": per_net,
                         "source_def_sha256": (_sha256_of(source_def)
                                               if in_project and source_def.is_file()
                                               else None),
                         "supply_subject_sha256": (_def_supply_subject_sha256(source_def)
                                                   if in_project else None)})
    if not measured:
        return None
    # A later carried-forward zero cannot erase an earlier native violation.
    # The whole chain is bound, so changing any metric-bearing state refreshes
    # pdn.done even if a later state kept its old bytes.
    found = max(measured, key=lambda row: row["count"])
    found["chain_sha256"] = hashlib.sha256(json.dumps(
        (chain_inputs, found["source_def_sha256"]),
        separators=(",", ":")).encode()).hexdigest()
    return found


def pdn_done_text(project: Path, pnr_out: Path, primary_def: Path,
                  pdn_ok: bool, pdn_marker: str,
                  def_evidence: Mapping[str, Any]) -> Optional[str]:
    """The text of Step 15's declared `<pnr>/pdn.done`, or None when the flag
    on disk already describes exactly this DEF.

    `pdn_ok` / `pdn_marker` are the direct deck's transcript verdict
    (`phase3_one_shot_runner._pnr_pdn_status`), `def_evidence` the DEF's own
    SPECIALNETS census. The flag is bound to the DEF, the source transcript or
    LibreLane state chain, and the POWER/GROUND special-net subject. A changed
    source remeasures; a changed grid without matching source geometry is NOT
    MEASURED. With neither tool marker nor LibreLane metric, the status is
    NOT MEASURED -- a missing marker is not a disconnected grid."""
    project, pnr_out = Path(project), Path(pnr_out)
    flag = pnr_out / "pdn.done"
    def_sha = _sha256_of(primary_def)
    supply_subject = _def_supply_subject_sha256(primary_def)
    missing_marker = pdn_marker in ("no PDN insertion marker",
                                    "openroad.log unreadable")
    ll = (None if pdn_ok or not missing_marker
          else librelane_pdn_evidence(project))
    log_path = pnr_out / "openroad.log"
    source_sha = (ll["chain_sha256"] if ll is not None else
                  _sha256_of(log_path) if log_path.is_file() else None)
    try:
        prior = flag.read_text(errors="replace") if flag.is_file() else ""
    except OSError:
        prior = ""
    if ll is not None:
        subject_matches = (supply_subject is not None
                           and ll["supply_subject_sha256"] == supply_subject)
        status = ("NOT MEASURED" if not subject_matches else
                  "CONNECTED" if ll["count"] == 0 else "NOT CONNECTED")
        marker = (f"LibreLane {ll['step']}: design__power_grid_violation__count="
                  f"{ll['count']} (per net {ll['per_net']})"
                  + ("; source and routed DEF supply geometry do not match"
                     if not subject_matches else ""))
        source = f"{ll['step']}/state_out.json sha256:{ll['state_sha256']}"
        tool = f"openroad, run by LibreLane (chain of {ll['step']})"
    else:
        status = ("CONNECTED" if pdn_ok else
                  "NOT MEASURED" if missing_marker
                  else "NOT CONNECTED")
        marker = pdn_marker
        source = _rel(log_path, project)
        tool = f"openroad (see {_rel(pnr_out / 'pnr.tcl', project)})"
        # The first flag needs the same route-time binding as every later one.
        # A log by itself never proves that this DEF population was measured.
        if (status == "CONNECTED" and not _direct_pdn_receipt_matches(
                pnr_out, source_sha, supply_subject, pdn_marker)):
            status = "NOT MEASURED"
            marker += "; direct route receipt missing or DEF supply subject changed"
    if (source_sha is not None and supply_subject is not None
            and f"# PDN status: {status}\n" in prior
            and f"# measured_def_sha256: {def_sha}\n" in prior
            and f"# source_identity_sha256: {source_sha}\n" in prior
            and f"# supply_subject_sha256: {supply_subject}\n" in prior):
        return None
    ev = def_evidence or {}
    body = (f"# PDN status: {status}\n"
            f"# marker: {marker}\n"
            f"# measured in {Path(primary_def).name} SPECIALNETS: "
            f"follow-pin rails={ev.get('followpin', '?')} "
            f"straps={ev.get('stripe', '?')} ring={ev.get('ring', '?')} "
            f"vias={ev.get('vias', '?')} layers={ev.get('layers', '?')}\n"
            f"# measured_def_sha256: {def_sha}\n"
            f"# supply_subject_sha256: {supply_subject or 'NOT_MEASURED'}\n"
            f"# source_identity_sha256: {source_sha or 'NOT_MEASURED'}\n"
            f"# source: {source}\n"
            f"# tool: {tool}\n")
    return None if prior == body else body
def current_tool_power_text(corner, row, report_text, state_sha256, subject):
    """The tool report body, unchanged, plus its current material identities."""
    provenance = '\n'.join('# ' + line for line in json.dumps(subject, indent=2).splitlines())
    return tool_power_report_text(corner, row, report_text, state_sha256) + '\n# Current material inputs\n' + provenance + '\n'


def _step33_current_power_due(project: Path) -> bool:
    """Return whether the retained Step 33 current-power adoption is stale.

    This is cache admission for the power consumer.  The runner owns the
    surrounding step order; the power module owns the current report's binding
    and canonical scalar record.
    """
    try:
        import _opensta_current as current

        current.power_binding(project)
        report = _pl.reports_phase3_dir(project) / "power.rpt"
        doc = json.loads(report.with_suffix(".json").read_text())
        expected = signoff_record(
            read_power_report(report), source="reports/phase3/power.rpt",
            analysis_mode=doc.get("analysis_mode"))
        return doc != expected or doc.get("power_measurement") != "MEASURED"
    except (OSError, ValueError, KeyError, TypeError):
        return True


def _adopt_current_power_report(project: Path, top: str, power_rpt: Path,
                                notes: List[str]) -> bool:
    """Adopt the current native STAPostPNR power report for Step 33.

    The phase-3 runner supplies orchestration inputs and retains control of
    step sequencing.  All power-specific selection, text construction,
    provenance and signoff behavior lives here.
    """
    import _atomic_artefact as _aa
    import _opensta_current as current
    import librelane_postroute as lp

    power_rpt.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = power_rpt.with_suffix('.current.json')
    for path in (power_rpt, receipt_path):
        path.unlink(missing_ok=True)
    try:
        if power_rpt.absolute() != (_pl.reports_phase3_dir(project) / 'power.rpt').absolute():
            raise current.Refusal('CURRENT_POWER_OUTPUT_PATH_MISMATCH')
        folder, _ = lp.stapostpnr_state(project)
        corners = stapostpnr_corner_power(folder)
        if not corners or any(row['status'] != 'MEASURED' for row in corners.values()):
            raise current.Refusal('CURRENT_POWER_CORNERS_UNMEASURED')
        # Validate every measured corner before choosing the largest total.
        for corner in corners:
            current.tool_subject(project, top, corner=corner)
        worst = max(corners, key=lambda corner: corners[corner]['total_w'])
        subject, tool = current.tool_subject(project, top, corner=worst)
        source = Path(corners[worst]['report'])
        power_rpt.write_text(current_tool_power_text(
            worst, corners[worst], source.read_text(), current.digest(tool['state']), subject))
        receipt = {**subject, 'schema': 'stapostpnr-power-current-v1', 'step': '33',
                   'tool_state': str(tool['state']),
                   'source_report': current.file_record(source, 'source_power', project),
                   'outputs': [current.file_record(power_rpt, 'power_report', project)]}
        _aa.write_json(receipt_path, receipt)
        current.power_binding(project)
        record = emit_signoff_record(project, power_rpt, power_rpt.with_suffix('.json'),
                                     'vectorless_sdc', notes, tool_rc=0)
        if record.get('power_measurement') != 'MEASURED':
            raise current.Refusal('CURRENT_POWER_DOWNSTREAM_NOT_MEASURED')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        receipt_path.unlink(missing_ok=True)
        power_rpt.unlink(missing_ok=True)
        retire_signoff_record(power_rpt.with_suffix('.json'), str(exc), notes)
        notes.append(f'Power NOT_MEASURED: {exc}')
        return False
    notes.append(f'Step 33 adopted current STAPostPNR power corner {worst}')
    return True
