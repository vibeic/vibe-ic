#!/usr/bin/env python3
"""magic_gencell_layout_lib.py — chip-AGNOSTIC deterministic core of the
Magic-gencell analog layout path (skill `analog-layout`, step A5).

Distilled from the u_hawaii_adc campaign's generator (benchmark-data
`uhadc/a5-layout-generator`), which converged two analog blocks (an LDO and a
switched-capacitor delta-sigma modulator) to netgen "Circuits match uniquely."
+ KLayout sign-off DRC 0 on IHP SG13G2. Every rule here was MEASURED on real
tool output and then falsified two-tree before being written down; the LAWS
numbering below matches the campaign's A5_STATUS.md so the evidence trail
stays navigable. No PDK, chip, or dimension literal appears except as a
DEFAULT ARGUMENT taken from a named deck rule, and every such default is
overridable by the caller.

What belongs here (Bucket A — deterministic, testable):
  * .mag COORDINATE SPACES (LAW #22): the `magscale a b` header governs the
    unit of `use` transforms and `rect` lines, PER FILE — a parent .mag gains
    `magscale 1 2` the moment any geometry sits off the lambda grid (e.g. a
    half-lambda column of an odd-length LV device), and a gencell child may
    or may not carry it. `rlabel` coordinates are ALWAYS internal (2x lambda)
    regardless of the header (measured on both kinds of file).
  * LADDER DISCIPLINE (LAW #23): right-side exit ladders stay short-proof
    ("a rung at Y_i can only cross a descent whose top is below Y_i") ONLY
    while rung y's are strictly ascending with rank. D and S labels of one
    MOS share a y, so tied taps MUST be staggered up their own full-height
    column M2 (LAW #9) by at least wire-width + spacing, order-preserved.
    Descents must be allocated ascending AND obstacle-aware: a blind
    `ox + pitch*(rank-1)` walked one block's descent straight through a
    neighbour row's tap pads.
  * CAP PLATE EXITS (LAW #24): a MIM cap's top/bottom-plate via stacks must
    be placed from the cap's MEASURED plate bbox, never fixed offsets — the
    top-plate stack's via ladder auto-paints a bottom-metal pad, so a fixed
    lateral offset landed it ON the cap's own bottom plate (plate short),
    and a fixed bottom-plate offset reached the NEIGHBOUR cap's plate.
  * CROSS-NET MANIFEST AUDIT: with every top-level painted box recorded as
    (net, layer, box), cross-net shorts are a pure geometry scan over
    same-layer overlaps plus via-adjacency — cheap enough to run after every
    generation, and it localised all 28 of the campaign's ladder shorts.
  * LVS COMPARISON GRID (measured): the drawn mask is on the manufacturing
    grid while a derived netlist parameter may not be; the PDK's own netgen
    deck declares a 1% tolerance for exactly this, but that tolerance clause
    is INERT in current netgen builds (pristine-setup control run: a 0.006%
    delta still reported at cutoff=0%). Quantizing the COMPARISON side to
    the grid implements the deck's stated intent without touching the
    design netlist.

What stays judgment (Bucket B, in the skill): which nets share a rail, the
floorplan row assignment, matching styles, and any deviation a specific PDK's
gencell dialect forces — those are recorded per-design, not encoded here.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ── LAW #22: .mag coordinate spaces ───────────────────────────────────────

_MAGSCALE_RE = re.compile(r"^magscale (\d+) (\d+)", re.M)
_USE_RE = re.compile(
    r"use \S+\s+(\S+)\s*\ntimestamp \d+\s*\n"
    r"transform 1 0 (-?\d+) 0 1 (-?\d+)")
_RECT_RE = re.compile(r"rect\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")
_RLABEL_RE = re.compile(
    r"rlabel\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+\d+\s+(\S+)")


def mag_scale(text: str) -> Tuple[int, int]:
    """(num, den) of the file's `magscale` header; (1, 1) when absent.

    A value in the file multiplied by num/den is in LAMBDA. Magic writes
    `magscale 1 2` when any geometry is off the lambda grid, and files
    without the header are already lambda — measured: an odd-l LV MOS forces
    it onto the PARENT, while cap gencell children ship without it, so the
    header must be read PER FILE, never assumed for a family of files.
    """
    m = _MAGSCALE_RE.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


def to_lambda(v: int, scale: Tuple[int, int]):
    """File-unit value -> lambda (int when exact, float when half-grid)."""
    num, den = scale
    v = v * num
    return v // den if v % den == 0 else v / den


def parse_use_transforms(text: str) -> Dict[str, Tuple[float, float]]:
    """Instance name -> (x, y) origin in LAMBDA, magscale-aware.

    Reading transforms as lambda without the header check doubled every
    origin of a `magscale 1 2` parent — the whole wiring layer landed
    off-die and extraction saw one single-pin net per terminal.
    """
    sc = mag_scale(text)
    return {m.group(1): (to_lambda(int(m.group(2)), sc),
                         to_lambda(int(m.group(3)), sc))
            for m in _USE_RE.finditer(text)}


def parse_rects_lambda(section_text: str,
                       scale: Tuple[int, int]) -> List[Tuple]:
    """All `rect` lines of a section, scaled to lambda."""
    return [tuple(to_lambda(int(v), scale) for v in m.groups())
            for m in _RECT_RE.finditer(section_text)]


def parse_rlabels(text: str) -> List[Dict]:
    """rlabel entries with centre coordinates in LAMBDA.

    rlabel coordinates are ALWAYS internal units (2x lambda), independent of
    the file's magscale header — measured against streamed GDS text on both
    a `magscale 1 2` MOS child and a header-less cap child. The centre is
    therefore (x1+x2)//4 in lambda.
    """
    out = []
    for m in _RLABEL_RE.finditer(text):
        layer, x1, y1, x2, y2, name = m.groups()
        out.append({"layer": layer,
                    "x": (int(x1) + int(x2)) // 4,
                    "y": (int(y1) + int(y2)) // 4,
                    "name": name})
    return out


# ── LAW #23: ladder tie-stagger + obstacle-aware descents ─────────────────

def stagger_ladder_taps(taps: Sequence[Tuple[str, float, float]],
                        col_top: float,
                        min_pitch: float = 51.0,
                        ) -> List[Tuple[str, float, float]]:
    """Stagger same-y ladder taps upward along their own column.

    `taps` = (net, x, y) sorted or unsorted; returns them sorted by y with
    every consecutive pair at least `min_pitch` apart in y, raising later
    entries only (order after sort is preserved, so rung y stays strictly
    ascending with rank and the one-sided ladder proof holds). `min_pitch`
    defaults to 51 lambda = m3 wire width 30 + deck spacing Mn_b 21 on the
    measured PDK — pass the caller's own deck numbers for any other stack.
    `col_top` clamps the stagger to the column's real M2 extent; a tap that
    cannot be staggered within the column is still raised past its
    predecessor (a short is never the correct fallback) and the caller can
    detect the clamp breach by comparing against `col_top`.
    """
    ordered = sorted(taps, key=lambda t: t[2])
    out: List[Tuple[str, float, float]] = []
    last_y: Optional[float] = None
    for net, x, y in ordered:
        if last_y is not None and y < last_y + min_pitch:
            y = max(min(last_y + min_pitch, col_top), last_y + min_pitch)
        out.append((net, x, y))
        last_y = y
    return out


def allocate_descent(prefer: float,
                     last_descent: float,
                     net: str,
                     y_span: Tuple[float, float],
                     obstacles: Iterable[Tuple[str, float, float]],
                     lanes: Iterable[float],
                     min_lane_pitch: float = 60.0,
                     step: float = 10.0) -> float:
    """Pick the next ladder-descent x: ascending and obstacle-aware.

    Starts at max(prefer, last_descent + min_lane_pitch) — the ascending
    rule that keeps the ladder proof — then walks right in `step`s until the
    candidate clears (a) every existing lane by `min_lane_pitch` and (b)
    every FOREIGN terminal point whose y lies inside the descent's span.
    The blind `prefer + pitch*(rank-1)` this replaces put one macro's
    descent through the tap pads of a device two rows below (measured on
    the manifest, 4 cross-net hits from a single descent).
    """
    lo, hi = min(y_span), max(y_span)
    lanes = list(lanes)
    obstacles = list(obstacles)
    cand = max(prefer, last_descent + min_lane_pitch)

    def bad(cx: float) -> bool:
        for onet, px, py in obstacles:
            if onet == net:
                continue
            if abs(cx - px) < min_lane_pitch and lo - 40 <= py <= hi + 40:
                return True
        return any(abs(cx - lx) < min_lane_pitch for lx in lanes
                   if lx != last_descent)

    while bad(cand):
        cand += step
    return cand


# ── LAW #24: cap plate exits from the measured plate bbox ─────────────────

def cap_plate_exits(plate_bbox: Tuple[float, float, float, float],
                    top_clear: float = 160.0,
                    bottom_clear: float = 80.0) -> Tuple[float, float]:
    """(top_plate_exit_x, bottom_plate_exit_x) for a MIM cap.

    The top-plate via stack must land OUTSIDE the cap's own bottom plate —
    its lowest via auto-paints a bottom-metal pad, so an exit over the plate
    is a plate-to-plate short (measured: two of three caps shorted, and the
    third cap's bottom exit reached its NEIGHBOUR's plate). The clearances
    default to the measured-safe values on a 10nm-lambda stack (top: via
    ladder pad half-width + metal spacing; bottom: pad + Mn_b); both are
    caller-overridable with the target deck's numbers. The unit is whatever
    the bbox is in.
    """
    llx, _lly, urx, _ury = plate_bbox
    return llx - top_clear, urx + bottom_clear


# ── cross-net manifest audit ──────────────────────────────────────────────

#: Layer pairs that are electrically linked when their boxes overlap:
#: same-layer touch plus each via against BOTH metals it joins. Extend for
#: taller stacks by passing `extra_links` to `cross_net_overlaps`.
_DEFAULT_LINKS = {
    ("metal1", "metal1"), ("metal2", "metal2"), ("metal3", "metal3"),
    ("via1", "metal1"), ("via1", "metal2"), ("via1", "via1"),
    ("via2", "metal2"), ("via2", "metal3"), ("via2", "via2"),
}


def cross_net_overlaps(manifest: Sequence[Dict],
                       extra_links: Optional[Iterable[Tuple[str, str]]] = None
                       ) -> List[Tuple]:
    """Cross-net electrically-linked overlaps in a wiring manifest.

    `manifest` rows are {"net": .., "layer": .., "box": [x1,y1,x2,y2]}
    (the shape the generator records for every top-level paint). Returns
    (net_a, layer_a, box_a, net_b, layer_b, box_b) per hit. This scan
    found all 28 same-device ladder shorts in one pass and its empty
    result was a necessary (not sufficient) condition for every clean LVS.
    """
    links = set(_DEFAULT_LINKS)
    if extra_links:
        links.update(extra_links)

    def ov(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    hits = []
    n = len(manifest)
    for i in range(n):
        a = manifest[i]
        for j in range(i + 1, n):
            b = manifest[j]
            if a["net"] == b["net"]:
                continue
            pair = (a["layer"], b["layer"])
            if pair in links or (pair[1], pair[0]) in links:
                if ov(a["box"], b["box"]):
                    hits.append((a["net"], a["layer"], a["box"],
                                 b["net"], b["layer"], b["box"]))
    return hits


# ── LVS comparison-side grid quantization ─────────────────────────────────

_WL_RE = re.compile(r"\b([wl])=([0-9.]+)u\b")


def grid_snap_spice_params(line: str, grid_um: float = 0.01) -> str:
    """Snap w=/l= parameters of one SPICE card to the layout grid.

    Comparison-side only: the drawn mask IS on the grid, and the PDK netgen
    deck's own declared 1% tolerance for these parameters is inert in
    current netgen builds (measured with a pristine-setup control run —
    delta 0.006% still reported at cutoff=0%). The design netlist is never
    touched; only the copy handed to the comparator is quantized, which is
    the deck's stated intent executed where the tool fails to.
    """
    def snap(m):
        v = float(m.group(2))
        q = round(v / grid_um) * grid_um
        return f"{m.group(1)}={q:g}u"
    return _WL_RE.sub(snap, line)
