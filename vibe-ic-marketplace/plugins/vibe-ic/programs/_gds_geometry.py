#!/usr/bin/env python3
"""_gds_geometry — read a GDSII layout's GEOMETRY with no third-party library.

WHY THIS EXISTS
===============
The general tape-out precheck has three classes of check, and they differ by
WHERE THE TRUTH COMES FROM:

    pure geometry          needs no PDK data at all: is the origin at (0,0),
                           is the top cell the declared one, are there
                           zero-area polygons, is the database unit the one
                           the tech file declares.
    the PDK's own rules    DRC deck, density, antenna, Magic DRC. We CALL
                           them. We never reimplement them.
    a DECLARATION          die size, seal ring, forbidden layers. Compared
                           against something a human wrote down.

This module serves ONLY the first class. It exists because the first class is
the one that needs no tool at all — a GDSII file is a self-describing binary
record stream, and the four facts above are read straight out of it. Reaching
for KLayout to answer "is the origin at (0,0)" would make a check that cannot
run without a 13 GB container out of one that needs 300 lines of struct
unpacking, and a check that cannot run is a check that reports nothing.

`gds_topcell_name_check.py` already parses STRNAME/SNAME the same way for the
same reason; this module generalises that to the records a geometric question
needs (XY, UNITS, STRANS/MAG/ANGLE, COLROW) and is shared rather than copied.

WHAT IS DELIBERATELY NOT HERE
=============================
No DRC rule, no density window, no antenna ratio, no layer number, no PDK name
and no design name. Those belong to somebody else's deck, and a copy of them
here would be OURS — editable, and able to drift into passing. This module
reports MEASUREMENTS; every threshold lives in the caller, and every rule lives
in the PDK.

THE BOUNDING BOX IS FLATTENED, AND THE TRANSFORM IS THE REAL ONE
================================================================
A die's origin question cannot be answered from the top cell's own geometry:
in a real analog layout the top cell may hold almost nothing and place 21
instances that carry all of it. MEASURED on a published layout
(`u_hawaii_adc` sky130A, `phase3/stage4/gds/ldo.gds`): the top cell's own
polygons sit inside a few microns of the origin while the placed device cells —
origin-CENTRED by their generator's convention — drag the flattened box to
y = -223.305 um. Reading only the top cell's own XY records would have reported
an origin that was fine. So SREF/AREF are resolved, with reflection, magnification
and rotation applied in GDSII's own order (reflect about X, then scale, then
rotate, then translate), and AREF repetitions are expanded from COLROW.

DEGENERATE RECURSION IS BOUNDED, NOT ASSUMED AWAY
=================================================
A structure that references itself, directly or through a cycle, is malformed —
and it is exactly the sort of malformed a checker must survive rather than
recurse to death on. The walk carries its own visited set per path and reports
the cycle as a datum (`cycles`) instead of raising.

chip/PDK-AGNOSTIC: nothing here names a vendor, a process, a layer or a design.
"""
from __future__ import annotations

import gzip
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# --------------------------------------------------------------------------- #
# The GDSII record vocabulary this module needs.
#
# Numbers are the format's own record-type bytes. Only the records a GEOMETRIC
# question reads are named; everything else is skipped by length, which is what
# makes the reader tolerant of records it has never heard of instead of
# refusing a file some other tool wrote.
# --------------------------------------------------------------------------- #
_RT = {
    0x00: "HEADER", 0x01: "BGNLIB", 0x02: "LIBNAME", 0x03: "UNITS",
    0x04: "ENDLIB", 0x05: "BGNSTR", 0x06: "STRNAME", 0x07: "ENDSTR",
    0x08: "BOUNDARY", 0x09: "PATH", 0x0A: "SREF", 0x0B: "AREF", 0x0C: "TEXT",
    0x0D: "LAYER", 0x0E: "DATATYPE", 0x0F: "WIDTH", 0x10: "XY", 0x11: "ENDEL",
    0x12: "SNAME", 0x13: "COLROW", 0x15: "NODE", 0x16: "TEXTTYPE",
    0x17: "PRESENTATION", 0x19: "STRING", 0x1A: "STRANS", 0x1B: "MAG",
    0x1C: "ANGLE", 0x21: "PATHTYPE", 0x2A: "NODETYPE", 0x2B: "PROPATTR",
    0x2C: "PROPVALUE", 0x2D: "BOX", 0x2E: "BOXTYPE",
}

#: Element records that OPEN an element. ENDEL closes whichever is open.
_ELEMENTS = frozenset(
    ("BOUNDARY", "PATH", "SREF", "AREF", "TEXT", "NODE", "BOX"))

#: Elements that carry AREA. TEXT and NODE do not — a label is not geometry and
#: must not move a bounding box, which is a real difference from "every XY
#: record in the file" and is the reason this set is named rather than implied.
_AREA_ELEMENTS = frozenset(("BOUNDARY", "PATH", "BOX"))

#: Elements that carry area AND are CLOSED polygons, i.e. the ones on which
#: "zero area" is a meaningful question. A PATH is a centre line with a width;
#: a zero-extent PATH is a legal (if pointless) wire, not a zero-area polygon,
#: and the upstream zero-area checker is a polygon checker. Naming the set
#: keeps that distinction from being lost in a loop condition.
_POLYGON_ELEMENTS = frozenset(("BOUNDARY", "BOX"))

#: A GDSII file that is not one. The first record of every GDSII stream is
#: HEADER; anything else is not a layout and is refused rather than parsed into
#: an empty, clean-looking result.
_HEADER = 0x00

#: Bound on the walk. A pathological hierarchy must degrade to a REPORTED
#: truncation, never to a silent partial answer and never to a stack overflow.
MAX_HIERARCHY_DEPTH = 64
MAX_AREF_REPETITIONS = 1_000_000


class GdsError(Exception):
    """The file is not a GDSII stream, or is truncated mid-record."""


# --------------------------------------------------------------------------- #
# GDSII's 8-byte real: sign, 7-bit excess-64 base-16 exponent, 56-bit mantissa.
# Not IEEE 754. Decoded here because UNITS is stored in it and the database
# unit is one of the four facts this module exists to report.
# --------------------------------------------------------------------------- #
def real8(raw: bytes) -> float:
    if len(raw) < 8:
        raise GdsError("truncated 8-byte real")
    v = int.from_bytes(raw[:8], "big")
    sign = -1.0 if v >> 63 else 1.0
    exponent = ((v >> 56) & 0x7F) - 64
    mantissa = v & ((1 << 56) - 1)
    return sign * (mantissa / float(1 << 56)) * (16.0 ** exponent)


@dataclass
class Element:
    kind: str
    layer: Optional[int] = None
    datatype: Optional[int] = None
    xy: List[Tuple[int, int]] = field(default_factory=list)
    sname: Optional[str] = None
    mag: float = 1.0
    angle: float = 0.0
    reflect: bool = False
    colrow: Optional[Tuple[int, int]] = None


@dataclass
class Cell:
    name: str
    elements: List[Element] = field(default_factory=list)

    def refs(self) -> List[Element]:
        return [e for e in self.elements if e.kind in ("SREF", "AREF")]

    def own_area_elements(self) -> List[Element]:
        return [e for e in self.elements if e.kind in _AREA_ELEMENTS]


@dataclass
class Layout:
    """Everything read out of one GDSII stream.

    `dbu_meters` is metres per database unit, straight from UNITS. `dbu_um` is
    the same number in microns, which is the form every tech file states. Both
    are kept: the file's own number is what a comparison must be made against,
    and a derived one that silently replaced it would be a rounding nobody
    asked for.
    """
    path: str
    libname: str = ""
    user_units_per_dbu: Optional[float] = None
    dbu_meters: Optional[float] = None
    cells: Dict[str, Cell] = field(default_factory=dict)
    truncated: bool = False
    truncated_reason: Optional[str] = None

    @property
    def dbu_um(self) -> Optional[float]:
        return None if self.dbu_meters is None else self.dbu_meters * 1e6

    # -- hierarchy ---------------------------------------------------------- #
    def referenced(self) -> Set[str]:
        out: Set[str] = set()
        for c in self.cells.values():
            for r in c.refs():
                if r.sname:
                    out.add(r.sname)
        return out

    def top_cells(self) -> List[str]:
        """Defined and never referenced — GDSII's own definition of a top.

        Returned SORTED and as a LIST, never collapsed to one: a stream that
        carries two un-referenced structures has two tops, and that fact is
        precisely what a submission check refuses on. Handing back a single
        name would delete the finding before the caller could see it.
        """
        return sorted(set(self.cells) - self.referenced())

    def dangling_references(self) -> List[str]:
        """Names referenced by an SREF/AREF with no structure to match.

        A dangling reference is a hole in the layout, and it is reported rather
        than skipped because the flattened bounding box below is computed
        WITHOUT it — so a box that looks small may be small only because part
        of the design is missing.
        """
        return sorted(n for n in self.referenced() if n not in self.cells)


def _iter_records(data: bytes):
    """(record_type, datatype, payload) for every record, in order."""
    i, n = 0, len(data)
    while i + 4 <= n:
        length, rt, dt = struct.unpack_from(">HBB", data, i)
        if length < 4:
            raise GdsError(f"record at byte {i} declares length {length} (< 4)")
        end = i + length
        if end > n:
            raise GdsError(
                f"record at byte {i} declares length {length} but only "
                f"{n - i} byte(s) remain")
        yield rt, dt, data[i + 4:end]
        i = end
        if _RT.get(rt) == "ENDLIB":
            return


def _read_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".gz" or path.name.lower().endswith(".gds.gz"):
        with gzip.open(path, "rb") as fh:
            return fh.read()
    return path.read_bytes()


def read_layout(path: Path) -> Layout:
    """Parse `path` into a `Layout`, or raise `GdsError`.

    OASIS is NOT parsed. It is a different container with a different record
    grammar, and half-parsing it would produce an empty, clean-looking result —
    the exact failure this whole tree keeps finding. A caller handed a `.oas`
    gets an explicit refusal it can report as NOT_DETERMINED.
    """
    if path.suffix.lower() in (".oas", ".oasis"):
        raise GdsError(
            f"{path.name} is OASIS, not GDSII; this reader parses GDSII "
            "records only and will not guess at a container it cannot read")
    try:
        raw = _read_bytes(path)
    except OSError as exc:
        raise GdsError(f"cannot read {path}: {exc}") from exc
    except (gzip.BadGzipFile, EOFError) as exc:
        raise GdsError(f"cannot decompress {path}: {exc}") from exc
    if len(raw) < 4:
        raise GdsError(f"{path.name} is {len(raw)} byte(s); not a GDSII stream")
    if struct.unpack_from(">HBB", raw, 0)[1] != _HEADER:
        raise GdsError(
            f"{path.name} does not begin with a GDSII HEADER record; it is not "
            "a GDSII stream")

    lay = Layout(path=str(path))
    current: Optional[Cell] = None
    element: Optional[Element] = None
    try:
        for rt, _dt, payload in _iter_records(raw):
            name = _RT.get(rt)
            if name == "LIBNAME":
                lay.libname = payload.rstrip(b"\x00").decode("ascii", "replace")
            elif name == "UNITS":
                if len(payload) >= 16:
                    lay.user_units_per_dbu = real8(payload[0:8])
                    lay.dbu_meters = real8(payload[8:16])
            elif name == "STRNAME":
                cname = payload.rstrip(b"\x00").decode("ascii", "replace")
                current = lay.cells.setdefault(cname, Cell(cname))
            elif name == "ENDSTR":
                current, element = None, None
            elif name in _ELEMENTS:
                element = Element(kind=name)
            elif element is None:
                continue                       # a property of no open element
            elif name == "LAYER" and len(payload) >= 2:
                element.layer = struct.unpack_from(">h", payload, 0)[0]
            elif name in ("DATATYPE", "BOXTYPE") and len(payload) >= 2:
                element.datatype = struct.unpack_from(">h", payload, 0)[0]
            elif name == "XY":
                count = len(payload) // 4
                if count >= 2:
                    vals = struct.unpack(f">{count}i", payload[:count * 4])
                    element.xy = list(zip(vals[0::2], vals[1::2]))
            elif name == "SNAME":
                element.sname = payload.rstrip(b"\x00").decode("ascii", "replace")
            elif name == "STRANS" and len(payload) >= 2:
                element.reflect = bool(
                    struct.unpack_from(">H", payload, 0)[0] & 0x8000)
            elif name == "MAG" and len(payload) >= 8:
                element.mag = real8(payload)
            elif name == "ANGLE" and len(payload) >= 8:
                element.angle = real8(payload)
            elif name == "COLROW" and len(payload) >= 4:
                element.colrow = struct.unpack_from(">hh", payload, 0)
            elif name == "ENDEL":
                if current is not None:
                    current.elements.append(element)
                element = None
    except GdsError as exc:
        # A stream that stops mid-record has still told us about every
        # structure before the cut. Keep them, and SAY the answer is partial —
        # a truncated read reported as complete is the failure mode this tree
        # exists to refuse.
        lay.truncated = True
        lay.truncated_reason = str(exc)
    return lay


# --------------------------------------------------------------------------- #
# Flattened bounding box
# --------------------------------------------------------------------------- #
def _transform(pts: Sequence[Tuple[float, float]], ref: Element
               ) -> List[Tuple[float, float]]:
    """GDSII's transform order: reflect about X, scale, rotate, translate."""
    ox, oy = (ref.xy[0] if ref.xy else (0, 0))
    rad = math.radians(ref.angle or 0.0)
    ca, sa = math.cos(rad), math.sin(rad)
    mag = ref.mag if ref.mag else 1.0
    out: List[Tuple[float, float]] = []
    for x, y in pts:
        if ref.reflect:
            y = -y
        x, y = x * mag, y * mag
        out.append((ox + x * ca - y * sa, oy + x * sa + y * ca))
    return out


def _aref_offsets(ref: Element) -> List[Tuple[float, float]]:
    """Every repetition offset of an AREF, or a single (0,0) for an SREF.

    An AREF's three XY points are the origin, the END of the column run and the
    END of the row run — the pitch is that displacement DIVIDED BY the count,
    which is the step the format actually specifies and the one a naive reader
    gets wrong by using the raw displacement.
    """
    if ref.kind != "AREF" or not ref.colrow or len(ref.xy) < 3:
        return [(0.0, 0.0)]
    cols, rows = ref.colrow
    if cols <= 0 or rows <= 0:
        return [(0.0, 0.0)]
    if cols * rows > MAX_AREF_REPETITIONS:
        # Bound rather than expand: the CORNERS of the array are enough for a
        # bounding box, and an unbounded expansion is a denial of service on a
        # file we did not write.
        p0, pc, pr = ref.xy[0], ref.xy[1], ref.xy[2]
        dcx, dcy = (pc[0] - p0[0]), (pc[1] - p0[1])
        drx, dry = (pr[0] - p0[0]), (pr[1] - p0[1])
        return [(0.0, 0.0), (dcx, dcy), (drx, dry), (dcx + drx, dcy + dry)]
    p0, pc, pr = ref.xy[0], ref.xy[1], ref.xy[2]
    scx, scy = (pc[0] - p0[0]) / cols, (pc[1] - p0[1]) / cols
    srx, sry = (pr[0] - p0[0]) / rows, (pr[1] - p0[1]) / rows
    return [(scx * i + srx * j, scy * i + sry * j)
            for i in range(cols) for j in range(rows)]


@dataclass
class BBoxResult:
    """A flattened bounding box in DATABASE UNITS, and what it could not see.

    `cycles` and `depth_exceeded` are part of the result and not a warning on
    the side, because a box computed over a hierarchy that was cut short is a
    box that may be too small, and a caller comparing it to a declared die size
    has to be able to tell.
    """
    bbox: Optional[Tuple[float, float, float, float]] = None
    cells_visited: int = 0
    cycles: List[str] = field(default_factory=list)
    depth_exceeded: List[str] = field(default_factory=list)
    missing_cells: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not (self.cycles or self.depth_exceeded or self.missing_cells)


def flattened_bbox(layout: Layout, cell: str) -> BBoxResult:
    """Bounding box of `cell` with every reference resolved, in dbu."""
    res = BBoxResult()
    seen_cells: Set[str] = set()

    def walk(name: str, path: Tuple[str, ...]
             ) -> Optional[Tuple[float, float, float, float]]:
        if name not in layout.cells:
            if name not in res.missing_cells:
                res.missing_cells.append(name)
            return None
        if name in path:
            marker = " -> ".join(path + (name,))
            if marker not in res.cycles:
                res.cycles.append(marker)
            return None
        if len(path) >= MAX_HIERARCHY_DEPTH:
            if name not in res.depth_exceeded:
                res.depth_exceeded.append(name)
            return None
        seen_cells.add(name)
        lo_x = lo_y = math.inf
        hi_x = hi_y = -math.inf
        c = layout.cells[name]
        for el in c.own_area_elements():
            for x, y in el.xy:
                lo_x, hi_x = min(lo_x, x), max(hi_x, x)
                lo_y, hi_y = min(lo_y, y), max(hi_y, y)
        for ref in c.refs():
            if not ref.sname:
                continue
            sub = walk(ref.sname, path + (name,))
            if sub is None:
                continue
            corners = [(sub[0], sub[1]), (sub[2], sub[1]),
                       (sub[0], sub[3]), (sub[2], sub[3])]
            placed = _transform(corners, ref)
            for dx, dy in _aref_offsets(ref):
                for x, y in placed:
                    lo_x, hi_x = min(lo_x, x + dx), max(hi_x, x + dx)
                    lo_y, hi_y = min(lo_y, y + dy), max(hi_y, y + dy)
        if lo_x is math.inf:
            return None
        return (lo_x, lo_y, hi_x, hi_y)

    res.bbox = walk(cell, ())
    res.cells_visited = len(seen_cells)
    return res


# --------------------------------------------------------------------------- #
# Zero-area polygons
# --------------------------------------------------------------------------- #
@dataclass
class ZeroAreaHit:
    cell: str
    layer: Optional[int]
    datatype: Optional[int]
    kind: str
    reason: str
    vertices: int


def _shoelace2(pts: Sequence[Tuple[int, int]]) -> int:
    """Twice the signed area, in dbu^2, as an EXACT integer.

    Integer arithmetic on purpose. GDSII coordinates ARE integers, so the
    doubled area is an integer too, and "== 0" is then an exact question. A
    float area would need a tolerance, a tolerance would be a threshold of
    ours, and a threshold of ours is the thing that can be tuned until a
    violation passes.
    """
    n = len(pts)
    if n < 3:
        return 0
    total = 0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total)


def zero_area_polygons(layout: Layout) -> Tuple[List[ZeroAreaHit], int]:
    """(the zero-area polygons, the total polygon count).

    BOTH numbers are returned because the count alone cannot be read: "0
    violations" over 0 polygons is an empty file, not a clean one, and the
    caller needs the denominator to tell those apart.

    A polygon is zero-area when its exact doubled shoelace area is 0. That
    covers all three shapes the question is asked about — fewer than three
    distinct vertices, all vertices collinear, and a self-cancelling loop —
    without enumerating them, and without a tolerance.
    """
    hits: List[ZeroAreaHit] = []
    total = 0
    for cname in sorted(layout.cells):
        for el in layout.cells[cname].elements:
            if el.kind not in _POLYGON_ELEMENTS:
                continue
            total += 1
            pts = el.xy
            # A GDSII BOUNDARY repeats its first point as its last; the
            # shoelace sum closes the ring itself, so the duplicate is dropped
            # rather than counted as a vertex it is not.
            if len(pts) >= 2 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(pts) < 3:
                hits.append(ZeroAreaHit(
                    cname, el.layer, el.datatype, el.kind,
                    f"{len(pts)} distinct vertex/vertices; a polygon needs 3",
                    len(pts)))
                continue
            if _shoelace2(pts) == 0:
                hits.append(ZeroAreaHit(
                    cname, el.layer, el.datatype, el.kind,
                    "exact doubled shoelace area is 0 (degenerate or "
                    "self-cancelling)", len(pts)))
    return hits, total


# --------------------------------------------------------------------------- #
# Layers actually used
# --------------------------------------------------------------------------- #
def layers_used(layout: Layout) -> Dict[Tuple[int, int], int]:
    """(layer, datatype) -> element count, over every cell.

    Every element that carries a layer is counted, INCLUDING text and nodes: a
    forbidden layer is forbidden whether the design drew a polygon on it or
    only wrote a label there.
    """
    out: Dict[Tuple[int, int], int] = {}
    for c in layout.cells.values():
        for el in c.elements:
            if el.layer is None:
                continue
            key = (el.layer, el.datatype if el.datatype is not None else 0)
            out[key] = out.get(key, 0) + 1
    return out


def summarise(layout: Layout, top: Optional[str] = None) -> Dict[str, Any]:
    """The whole geometric read, as JSON-ready data. No verdict is taken here.

    Verdicts belong to the caller with the DECLARATION in hand: this function
    knows what the layout says and nothing about what it was supposed to say.
    """
    tops = layout.top_cells()
    chosen = top or (tops[0] if len(tops) == 1 else None)
    bb = flattened_bbox(layout, chosen) if chosen else BBoxResult()
    za, total = zero_area_polygons(layout)
    doc: Dict[str, Any] = {
        "path": layout.path,
        "libname": layout.libname,
        "truncated": layout.truncated,
        "truncated_reason": layout.truncated_reason,
        "user_units_per_dbu": layout.user_units_per_dbu,
        "dbu_meters": layout.dbu_meters,
        "dbu_um": layout.dbu_um,
        "cell_count": len(layout.cells),
        "top_cells": tops,
        "top_cell_count": len(tops),
        "examined_top_cell": chosen,
        "dangling_references": layout.dangling_references(),
        "polygon_count": total,
        "zero_area_polygon_count": len(za),
        "zero_area_polygons": [vars(h) for h in za[:100]],
        "zero_area_polygons_truncated": len(za) > 100,
        "bbox_dbu": list(bb.bbox) if bb.bbox else None,
        "bbox_complete": bb.complete,
        "bbox_cycles": bb.cycles,
        "bbox_depth_exceeded": bb.depth_exceeded,
        "bbox_missing_cells": bb.missing_cells,
        "cells_visited": bb.cells_visited,
    }
    if bb.bbox and layout.dbu_um:
        u = layout.dbu_um
        doc["bbox_um"] = [v * u for v in bb.bbox]
        doc["width_um"] = (bb.bbox[2] - bb.bbox[0]) * u
        doc["height_um"] = (bb.bbox[3] - bb.bbox[1]) * u
    else:
        doc["bbox_um"] = None
        doc["width_um"] = None
        doc["height_um"] = None
    return doc
