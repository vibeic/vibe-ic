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
    or may not carry it. `rlabel` coordinates follow the SAME header as the
    geometry — corrected against magic's own streamed GDS on both kinds of
    file after the older "always internal" claim put a header-less cap
    child's bottom-plate terminal in the middle of its top plate.
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

import math
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

    rlabel corner coordinates are in the FILE'S OWN units, exactly like
    `rect` and `use`, so the centre is (x1+x2)/2 converted by the file's
    `magscale` header.

    THE CORRECTION, AND HOW IT WAS SETTLED. This function previously read
    the coordinates as ALWAYS internal (2x lambda) and divided by four, on
    a docstring claim that it had been measured on both kinds of file. It
    had not: dividing by four is right ONLY for a `magscale 1 2` file, where
    the two conversions coincide. Magic's own streamed GDS is the
    adjudicator and it answers both cases, on ihp-sg13g2 gencell children
    written by the PDK itself, at 100 lambda per micron:

      `magscale 1 2` MOS child   rlabel hvndiffc 238 ...  -> GDS 1.19 um
                                 = 119 lambda            = 238 * 1/2   OK
      header-less cap child      rlabel metal5   510 ...  -> GDS 5.10 um
                                 = 510 lambda            != 510 // 2

    The cap child is the one that mattered. Its bottom-plate terminal at 510
    lambda sits just outside the top plate (+-480) and inside the bottom
    plate (+-560), which is the only place a bottom-plate contact can be;
    halved to 255 it lands in the DEAD CENTRE of the top plate. Every reader
    of that label — the terminal's conductor level, the via island position,
    the short audit — was then answering about the wrong plate, and both of
    the capacitor's terminals resolved to one conductor.
    """
    scale = mag_scale(text)
    num, den = scale
    out = []
    for m in _RLABEL_RE.finditer(text):
        layer, x1, y1, x2, y2, name = m.groups()
        out.append({"layer": layer,
                    "x": (int(x1) + int(x2)) * num // (2 * den),
                    "y": (int(y1) + int(y2)) * num // (2 * den),
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


# ── LAW #25: contact-enclosure repair of a gencell child ──────────────────

def _covered(rects: Sequence[Tuple[float, float, float, float]],
             box: Tuple[float, float, float, float]) -> bool:
    """True when `box` is entirely covered by the union of `rects`.

    Exact rectangle-union coverage by vertical slabs — no tolerance, no
    grid assumption, so it answers the same question the sign-off deck's
    enclosure check asks.
    """
    bx1, by1, bx2, by2 = box
    if bx1 >= bx2 or by1 >= by2:
        return True
    xs = {bx1, bx2}
    for x1, _y1, x2, _y2 in rects:
        for x in (x1, x2):
            if bx1 < x < bx2:
                xs.add(x)
    cuts = sorted(xs)
    for i in range(len(cuts) - 1):
        xa, xb = cuts[i], cuts[i + 1]
        spans = sorted((max(y1, by1), min(y2, by2))
                       for x1, y1, x2, y2 in rects
                       if x1 <= xa and x2 >= xb and y1 < by2 and y2 > by1)
        reach = by1
        for lo, hi in spans:
            if lo > reach:
                break
            reach = max(reach, hi)
        if reach < by2:
            return False
    return True


def _touch_components(rects: Sequence[Tuple[float, float, float, float]]
                      ) -> List[int]:
    """Union-find label per rect; touching or overlapping rects share one.

    A sub-minimum gap inside ONE conductor island is not a space violation
    — the shapes merge — so a repair that only ever grows the island it is
    repairing must not be refused on account of its own neighbours. The
    distinction is what separates the band that fixed the resistor head
    (own island, gap 0.005 um to the pad it extends) from the band that
    broke the MOS (a different island: the device's guard ring).
    """
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _rect_gap(rects[i], rects[j]) == 0:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    return [find(i) for i in range(n)]


def _rect_gap(a, b) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return math.hypot(dx, dy)


def contact_enclosure_patches(
        contacts: Sequence[Tuple[float, float, float, float]],
        metal: Sequence[Tuple[float, float, float, float]],
        enclosure: float,
        min_space: Optional[float] = None,
        ) -> Tuple[List[Tuple[float, float, float, float]],
                   List[Tuple[float, float, float, float]]]:
    """Metal patches that raise every contact's metal enclosure to `enclosure`.

    MEASURED failure this exists for: the PDK's own Magic gencell for the
    poly resistor caps each head contact with a metal pad whose TOP
    enclosure is half the deck's minimum (0.025 um against a 0.05 um rule,
    identical for every w/l the generator asked for — four parameter sets
    probed, four short by the same amount), so every block instantiating
    that device shipped that rule violation into sign-off DRC. A generator
    consuming a vendor gencell therefore cannot assume the gencell is
    clean: it must measure the enclosure it got and repair the shortfall.

    `contacts` and `metal` are rect tuples in ONE coordinate space (the
    caller's — this function has no unit of its own); the CONTACT rects
    must also be passed in `metal` when the target format implies metal
    under a contact tile (Magic's `*cont` types do). Only the sides that
    are actually short get a band, so a compliant side is never disturbed.

    `min_space` is the deck's metal space/notch minimum, and it is what
    makes the repair SAFE rather than merely correct: applied without it,
    the same repair walked over every MOS gate contact in the campaign's
    two blocks and traded 6 enclosure violations for 30 metal1 notch
    violations against the device's own guard ring (measured, both arms).
    A band that would leave a sub-minimum gap is REFUSED, not painted, and
    returned in the second element so the caller can report a shortfall it
    could not repair instead of silently shipping either defect. Returns
    ([], []) when nothing is short, which is what makes this safe to run
    unconditionally after every gencell call.
    """
    e = enclosure
    patches: List[Tuple[float, float, float, float]] = []
    refused: List[Tuple[float, float, float, float]] = []
    have = list(metal)
    for x1, y1, x2, y2 in contacts:
        bands = [
            (x1 - e, y2, x2 + e, y2 + e),   # top
            (x1 - e, y1 - e, x2 + e, y1),   # bottom
            (x1 - e, y1, x1, y2),           # left
            (x2, y1, x2 + e, y2),           # right
        ]
        for band in bands:
            if _covered(have, band):
                continue
            if min_space is not None:
                probe = have + [band]
                labels = _touch_components(probe)
                own = labels[-1]
                if any(0 < _rect_gap(band, m) < min_space
                       for m, lab in zip(have, labels) if lab != own):
                    refused.append(band)
                    continue
            patches.append(band)
            have.append(band)
    return patches, refused


def mag_section_rects(text: str, section: str) -> List[Tuple[int, ...]]:
    """Raw `rect` tuples of one `<< section >>` in FILE units (not scaled).

    Repairs are written back in file units, so the repair path deliberately
    does NOT go through the lambda conversion of LAW #22: converting and
    converting back is where a half-grid child loses a unit.
    """
    m = re.search(r"<< %s >>(.*?)(?=^<<|\Z)" % re.escape(section),
                  text, re.S | re.M)
    if not m:
        return []
    return [tuple(int(v) for v in r.groups())
            for r in _RECT_RE.finditer(m.group(1))]


def implicit_metal_sections(text: str, metal_section: str) -> List[str]:
    """Every section of a .mag whose tiles also carry `metal_section`.

    In Magic a contact type IS its two conductors plus the cut, so the
    metal picture read from the `<< metal1 >>` section alone is incomplete
    — and incomplete by exactly the guard-ring and diffusion contacts a
    repair has to keep its distance from. Reading the metal from that one
    section is what let a spacing-aware repair still paint 30 notch
    violations (measured): the neighbour it had to see was a
    `psubdiffcont` tile, invisible to a `metal1`-only reader.
    """
    names = re.findall(r"^<< (\S+) >>", text, re.M)
    out = [metal_section]
    for n in names:
        if n == metal_section or n in ("end", "labels", "properties",
                                       "checkpaint"):
            continue
        if "cont" in n or n.endswith("c") or n.startswith("via"):
            out.append(n)
    return out


def repair_mag_contact_enclosure(text: str,
                                 contact_section: str,
                                 metal_section: str,
                                 enclosure: int,
                                 min_space: Optional[int] = None,
                                 metal_sections: Optional[Sequence[str]] = None,
                                 ) -> Tuple[str, int]:
    """Append the LAW #25 patches to a .mag file's metal section.

    Returns (new_text, n_patches). `enclosure` is in the file's own units —
    the caller converts the deck rule once, at the boundary, where the
    file's `magscale` is known. A file whose metal section is absent gains
    one; a file that needs no patch is returned byte-identical, so this can
    sit unconditionally in the generator's post-gencell path.
    """
    contacts = mag_section_rects(text, contact_section)
    if not contacts:
        return text, 0
    if metal_sections is None:
        metal_sections = implicit_metal_sections(text, metal_section)
    metal = []
    for sec in metal_sections:
        metal += mag_section_rects(text, sec)
    metal += list(contacts)
    patches, _refused = contact_enclosure_patches(
        contacts, metal, enclosure, min_space)
    if not patches:
        return text, 0
    lines = "".join("rect %d %d %d %d\n" % tuple(int(v) for v in p)
                    for p in patches)
    hdr = "<< %s >>\n" % metal_section
    if hdr in text:
        text = text.replace(hdr, hdr + lines, 1)
    else:
        text = text.replace("<< end >>", hdr + lines + "<< end >>", 1)
    return text, len(patches)


# ── LAW #26: the manifest audit also has to ask about SPACE ───────────────

def cross_net_spacing_violations(manifest: Sequence[Dict],
                                 min_space: Dict[str, float],
                                 ) -> List[Tuple]:
    """Same-layer cross-net pairs closer than the deck's minimum space.

    The overlap audit above answers "is it shorted"; it says nothing about
    "is it manufacturable", and that gap shipped: a top-level routing rung
    was painted 0.10 um from a device child's own metal2 against a 0.21 um
    rule — no overlap, no short, clean LVS, and a sign-off DRC violation.
    Distance is the true (Euclidean) rectangle gap (0 when they touch or overlap; an
    overlap is the overlap audit's finding, not this one's, so touching and
    overlapping pairs are skipped here). `min_space` is keyed by layer, so
    the caller supplies its own deck's numbers and no rule value is baked
    in. Rows are the same shape the overlap audit takes, which is what lets
    a generator run both scans over one manifest.
    """
    hits = []
    rows = [r for r in manifest if r["layer"] in min_space]
    for i in range(len(rows)):
        a = rows[i]
        for j in range(i + 1, len(rows)):
            b = rows[j]
            if a["net"] == b["net"] or a["layer"] != b["layer"]:
                continue
            ax1, ay1, ax2, ay2 = a["box"]
            bx1, by1, bx2, by2 = b["box"]
            dx = max(bx1 - ax2, ax1 - bx2, 0)
            dy = max(by1 - ay2, ay1 - by2, 0)
            if dx == 0 and dy == 0:
                continue
            gap = math.hypot(dx, dy)
            if gap < min_space[a["layer"]]:
                hits.append((a["net"], b["net"], a["layer"], gap,
                             a["box"], b["box"]))
    return hits
