#!/usr/bin/env python3
"""A REAL GDSII carrying dummy-fill shapes, and just enough KLayout to measure it.

WHY THIS EXISTS (vibe-ic#990)
=============================
The per-layer density producer reads ONE datatype per metal layer — the
routing/NET row of the PDK's LEF/DEF layermap — while the PDK's own density
deck counts routing PLUS a separate dummy-fill datatype. On the measured run
the two agreed to 0.00e+00 on all six layers, and #988 recorded exactly why:

    measured 0 shapes on 36/28, 41/28, 34/28, 51/28 and 68..72/99

That GDS has no fill in it. So on THIS corpus the two paths cannot disagree,
and any fix to the producer is unfalsifiable — which is what this fixture is
for. It is a layout with fill shapes on a datatype the routing row does not
name, so the pre-fix and post-fix selections give provably different numbers.

WHY IT IS A GDS FILE AND NOT A MOCK
-----------------------------------
`filled.gds` beside this module is a real GDSII stream a reviewer can open in
KLayout, and the recipe under test is the one the runner actually emits. A
fixture that existed only as a Python object would prove the producer's
BOOKKEEPING and never that a stream with fill in it measures differently.

WHY THERE IS A KLAYOUT STAND-IN
-------------------------------
No `klayout`, no `pya`, no container and no PDK tree is installed on the host
this was written on, so the recipe cannot be run for real here. `PyaStub`
provides the seven calls the recipe makes (`Layout`, `read`, `top_cell`, `dbu`,
`bbox`, `find_layer`, `begin_shapes_rec`, `Region`, `merge`, `area`) over the
reader below. It is deliberately NARROW and it REFUSES rather than guesses:
anything the recipe asks for that this fixture does not model raises, so a
recipe that starts doing something else fails loudly instead of being measured
by a stub that quietly answers zero.

`Region.area()` is an EXACT union of axis-aligned rectangles (coordinate
compression), not a sum — a sum would make an overlapping fill shape look like
extra density, which is the direction that would flatter the fix.

chip-AGNOSTIC: no design, foundry, SKU or process token. The layer/datatype
numbers here are fixture constants chosen to be distinct, not a PDK's.
"""
from __future__ import annotations

import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
GDS = HERE / "filled.gds"
LAYERMAP = HERE / "fill.map"
DECK = HERE / "density_deck.drc"

#: One database unit, in micrometres. 1 nm, the usual choice.
DBU_UM = 0.001

#: The fixture's own layout, stated once and used by BOTH the writer and the
#: expected-value arithmetic in the tests, so the numbers a test asserts are
#: derived from the same declaration the stream is built from.
#:
#: `die` is a frame drawn on a layer nothing counts, purely so the top cell's
#: bounding box is a fixed, stated area rather than whatever the metal happens
#: to span. Without it, adding fill shapes would MOVE the denominator and the
#: density delta would not be the fill area.
DIE_UM = 100.0
DIE_LAYER = (0, 0)

#: The metal layer under test: routing on one datatype, dummy fill on another.
#: The producer's pre-fix selector sees only the first.
METAL_GDS_LAYER = 68
ROUTING_DATATYPE = 20
FILL_DATATYPE = 36

#: (x0, y0, x1, y1) in micrometres. Disjoint by construction on each datatype
#: AND across the two, so the union area is the plain sum and every expected
#: value in the tests is arithmetic a reader can do by hand.
ROUTING_RECTS_UM = (
    (10.0, 10.0, 30.0, 20.0),     # 20 x 10 = 200
    (40.0, 10.0, 50.0, 30.0),     # 10 x 20 = 200
)
FILL_RECTS_UM = (
    (10.0, 40.0, 60.0, 50.0),     # 50 x 10 = 500
    (70.0, 10.0, 80.0, 40.0),     # 10 x 30 = 300
)


def _rect_area(rects):
    return sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)


ROUTING_AREA_UM2 = _rect_area(ROUTING_RECTS_UM)          # 400.0
FILL_AREA_UM2 = _rect_area(FILL_RECTS_UM)                # 800.0
DIE_AREA_UM2 = DIE_UM * DIE_UM                           # 10000.0


# ── GDSII stream ────────────────────────────────────────────────────────────
# Record layout: [uint16 length incl. header][uint8 rectype][uint8 datatype][data]

_NODATA, _INT2, _INT4, _REAL8, _ASCII = 0x00, 0x02, 0x03, 0x05, 0x06

_HEADER, _BGNLIB, _LIBNAME, _UNITS = 0x00, 0x01, 0x02, 0x03
_ENDLIB, _BGNSTR, _STRNAME, _ENDSTR = 0x04, 0x05, 0x06, 0x07
_BOUNDARY, _LAYER, _DATATYPE, _XY, _ENDEL = 0x08, 0x0D, 0x0E, 0x10, 0x11


def _rec(rectype: int, datatype: int, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HBB", len(payload) + 4, rectype, datatype) + payload


def encode_real8(value: float) -> bytes:
    """GDSII 8-byte excess-64 base-16 float."""
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0x00
    value = abs(value)
    exponent = 64
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    mantissa = int(round(value * (1 << 56)))
    if mantissa >= (1 << 56):          # rounding carried out of the mantissa
        mantissa >>= 4
        exponent += 1
    return struct.pack(">B", sign | exponent) + mantissa.to_bytes(7, "big")


def decode_real8(raw: bytes) -> float:
    head = raw[0]
    exponent = (head & 0x7F) - 64
    mantissa = int.from_bytes(raw[1:8], "big") / float(1 << 56)
    value = mantissa * (16.0 ** exponent)
    return -value if head & 0x80 else value


def _boundary(layer: int, datatype: int, rect_um) -> bytes:
    x0, y0, x1, y1 = (int(round(v / DBU_UM)) for v in rect_um)
    pts = ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))
    xy = b"".join(struct.pack(">ii", x, y) for x, y in pts)
    return (_rec(_BOUNDARY, _NODATA)
            + _rec(_LAYER, _INT2, struct.pack(">h", layer))
            + _rec(_DATATYPE, _INT2, struct.pack(">h", datatype))
            + _rec(_XY, _INT4, xy)
            + _rec(_ENDEL, _NODATA))


#: A fixed timestamp. A stream that changes on every run cannot be committed and
#: diffed, which is the same reason the census generator refuses to stamp one.
_STAMP = struct.pack(">12h", *([2026, 1, 1, 0, 0, 0] * 2))

TOP_CELL = "DENSITY_FILL_FIXTURE"


def build_gds() -> bytes:
    """The fixture stream, byte-for-byte deterministic."""
    body = [
        _rec(_HEADER, _INT2, struct.pack(">h", 600)),
        _rec(_BGNLIB, _INT2, _STAMP),
        _rec(_LIBNAME, _ASCII, b"DENSITY_FILL_LIB"),
        _rec(_UNITS, _REAL8, encode_real8(DBU_UM) + encode_real8(DBU_UM * 1e-6)),
        _rec(_BGNSTR, _INT2, _STAMP),
        _rec(_STRNAME, _ASCII, TOP_CELL.encode()),
        _boundary(DIE_LAYER[0], DIE_LAYER[1], (0.0, 0.0, DIE_UM, DIE_UM)),
    ]
    for r in ROUTING_RECTS_UM:
        body.append(_boundary(METAL_GDS_LAYER, ROUTING_DATATYPE, r))
    for r in FILL_RECTS_UM:
        body.append(_boundary(METAL_GDS_LAYER, FILL_DATATYPE, r))
    body += [_rec(_ENDSTR, _NODATA), _rec(_ENDLIB, _NODATA)]
    return b"".join(body)


def read_gds(path):
    """`{(layer, datatype): [rect_in_dbu, …]}, dbu, cell_name` from a stream.

    Boundaries only, and it REFUSES anything else it is given a shape record
    for — see the module docstring. A reader that silently skipped a path
    record would under-measure and look like a clean result.
    """
    data = Path(path).read_bytes()
    shapes, dbu, cell = {}, None, None
    layer = datatype = None
    off = 0
    while off < len(data):
        (length, rectype, dtype) = struct.unpack(">HBB", data[off:off + 4])
        if length < 4:
            raise ValueError(f"malformed GDS record at byte {off}")
        payload = data[off + 4:off + length]
        off += length
        if rectype == _UNITS:
            dbu = decode_real8(payload[0:8])
        elif rectype == _STRNAME:
            cell = payload.rstrip(b"\x00").decode()
        elif rectype == _LAYER:
            layer = struct.unpack(">h", payload)[0]
        elif rectype == _DATATYPE:
            datatype = struct.unpack(">h", payload)[0]
        elif rectype == _XY:
            n = len(payload) // 8
            pts = [struct.unpack(">ii", payload[i * 8:i * 8 + 8])
                   for i in range(n)]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            shapes.setdefault((layer, datatype), []).append(
                (min(xs), min(ys), max(xs), max(ys)))
        elif rectype in (0x09, 0x0A, 0x0B, 0x0C):   # PATH/SREF/AREF/TEXT
            raise ValueError(
                f"this fixture reader models BOUNDARY records only; record "
                f"type 0x{rectype:02X} is present and would be silently "
                f"dropped, which is the shape of an under-measurement")
    if dbu is None or cell is None:
        raise ValueError("stream carries no UNITS or no STRNAME")
    return shapes, dbu, cell


def union_area_dbu(rects) -> int:
    """EXACT union area of axis-aligned rectangles, by coordinate compression.

    Not a sum. An overlapping fill shape counted twice would make the fix look
    bigger than it is, in the one direction nobody would question.
    """
    if not rects:
        return 0
    xs = sorted({x for r in rects for x in (r[0], r[2])})
    total = 0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        spans = sorted((r[1], r[3]) for r in rects if r[0] <= x0 and r[2] >= x1)
        covered, cur_lo, cur_hi = 0, None, None
        for lo, hi in spans:
            if cur_hi is None or lo > cur_hi:
                if cur_hi is not None:
                    covered += cur_hi - cur_lo
                cur_lo, cur_hi = lo, hi
            else:
                cur_hi = max(cur_hi, hi)
        if cur_hi is not None:
            covered += cur_hi - cur_lo
        total += (x1 - x0) * covered
    return total


# ── the KLayout stand-in ────────────────────────────────────────────────────

class _Box:
    def __init__(self, x0, y0, x1, y1):
        self._x0, self._y0, self._x1, self._y1 = x0, y0, x1, y1

    def width(self):
        return self._x1 - self._x0

    def height(self):
        return self._y1 - self._y0


class _Region:
    """A bag of rectangles whose `area()` is their exact union."""

    def __init__(self, source=None):
        if source is None:
            self._rects = []
        elif isinstance(source, list):
            self._rects = list(source)
        else:
            raise TypeError(
                f"the fixture Region models an explicit rectangle list only; "
                f"got {type(source).__name__}")

    def __add__(self, other):
        return _Region(self._rects + other._rects)

    def merge(self):
        return self          # `area()` is already a union; nothing to do

    def area(self):
        return union_area_dbu(self._rects)


class _Cell:
    def __init__(self, shapes, name):
        self._shapes, self._name = shapes, name

    def bbox(self):
        allr = [r for rs in self._shapes.values() for r in rs]
        xs = [v for r in allr for v in (r[0], r[2])]
        ys = [v for r in allr for v in (r[1], r[3])]
        return _Box(min(xs), min(ys), max(xs), max(ys))

    def begin_shapes_rec(self, li):
        return list(self._shapes.get(li, []))


class _Layout:
    def __init__(self):
        self._shapes, self.dbu, self._cell = {}, None, None

    def read(self, path):
        self._shapes, self.dbu, self._cell = read_gds(path)

    def top_cell(self):
        return _Cell(self._shapes, self._cell)

    def find_layer(self, gl, gd):
        return (gl, gd) if (gl, gd) in self._shapes else None


class PyaStub:
    """The `pya` module as the density recipe uses it, and no wider."""
    Layout = _Layout
    Region = _Region


def write_fixture() -> None:
    """(Re)generate every file in this directory. The tests assert the
    committed bytes still match what this produces."""
    GDS.write_bytes(build_gds())
    LAYERMAP.write_text(LAYERMAP_TEXT, encoding="utf-8")
    DECK.write_text(DECK_TEXT, encoding="utf-8")


#: A LEF/DEF streamout layermap in the `<lefname> <purpose> <gdslayer>
#: <gdsdatatype>` shape the producer already parses. The FILL row is the one
#: the pre-fix selector cannot see: it keeps the first NET row and nothing else.
LAYERMAP_TEXT = f"""\
# fixture streamout layermap — <lefname> <purpose> <gdslayer> <gdsdatatype>
met1     LEFPIN,NET,SPNET,PIN       {METAL_GDS_LAYER} {ROUTING_DATATYPE}
met1     FILL                       {METAL_GDS_LAYER} {FILL_DATATYPE}
met1     TEXT                       {METAL_GDS_LAYER} 5
met1     LEFOBS                     {METAL_GDS_LAYER} {ROUTING_DATATYPE}
via1     VIA,LEFPIN,PIN             {METAL_GDS_LAYER} 44
"""

#: A KLayout DRC density deck in the Ruby-DSL layer-binding forms the PDKs in
#: this registry use. The producer discovers the datatype SET from here; the
#: numbers are never typed into the producer.
#:
#: `met1_via` and `met1_label` are present ON PURPOSE: #988 recorded that the
#: PDK deck counts "all datatypes on the metal layer EXCEPT text and via", so a
#: discovery that swept the layer number blindly would over-count, and a
#: fixture without them could not tell the two apart.
DECK_TEXT = f"""\
# fixture density deck (KLayout DRC DSL)
met1        = input({METAL_GDS_LAYER}, {ROUTING_DATATYPE})
met1_fill   = input({METAL_GDS_LAYER}, {FILL_DATATYPE})
met1_via    = input({METAL_GDS_LAYER}, 44)
met1_label  = polygons({METAL_GDS_LAYER}, 5)
other       = polygons(99, 0)

met1_all = met1 + met1_fill
met1_all.raw.forget
# density rule: (met1_all.area / chip.area) * 100 < 30
"""


if __name__ == "__main__":
    write_fixture()
    print(f"wrote {GDS} ({GDS.stat().st_size} B), {LAYERMAP.name}, {DECK.name}")
