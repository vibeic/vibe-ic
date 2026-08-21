"""#595 — A8 shipped the abstract and the body in different coordinate frames.

#594 made the defect VISIBLE: the A8 outline gate had been comparing LEF `SIZE`
against the GDS width and height, which are exactly the two numbers a
misregistered pair agrees on. v1.9.21 then measured the fact that CHOOSES
between the two remedies — whether the offset is a whole number of manufacturing
grid steps — and deliberately stopped there, because picking wrong "converts a
loud FAIL into a silent misplacement in the other direction".

Both of those are the layer that NOTICES. This is the layer that PRODUCES.

A8 ships two views of one block from two Magic writers: `lef write` normalises
the abstract to the cell bounding box, `gds write` preserves the `.mag`'s own
coordinates. Any A5 layout whose bounding box does not start at the origin
therefore leaves A8 self-inconsistent by construction, and every downstream
consumer inherits the wrong frame.

MEASURED ON THE TRACKED `u_hawaii_adc` IHP SG13G2 RUN, both hardmacro blocks,
KLayout, Metal3 = 30/0, counting shapes touching each LEF `PORT` rect:

    delta_sigma  GDS bbox ll (-0.620,-30.320)um   LEF ORIGIN 0 0
                 vin vhi vlo clk bs vdd vss  -> 0 hits as-is, 1 hit shifted
    ldo          GDS bbox ll (-0.620,-31.920)um   LEF ORIGIN 0 0
                 vin_io vref vout vss        -> 0 hits as-is, 1 hit shifted

    after this fix, same measurement, same tool: 1 hit as-is on every pin of
    both blocks, shape counts unchanged (288 and 119 Metal3 shapes).

WHAT THIS DOES NOT DO, and the tests below are mostly about this half: it does
not CHOOSE a remedy. The translation is applied only when it is provably
grid-preserving, read from the real PDK the layout's own `tech` line names. An
offset that is not an exact multiple, a grid that cannot be read, a PDK that
declares two different grids, a stream with no single top structure — every one
of those leaves the file byte-for-byte as Magic wrote it, so the outline gate
still FAILs and a human picks `FOREIGN`. A guessed grid would decide the
question, so it is never guessed and there is no default.
"""
from __future__ import annotations

import importlib.util
import pathlib
import struct
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GATE = _load("analog_lef_gds_outline_check")
E = _load("analog_hardmacro_gds_emit")


# ───────────────────────────── fixtures ─────────────────────────────

def _rec(rec_type: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rec_type) + payload


def _units(dbu_per_um: float = 1000.0) -> bytes:
    return _rec(0x0305, GATE.encode_gds_real8(1.0 / dbu_per_um)
                + GATE.encode_gds_real8(1e-6 / dbu_per_um))


def _boundary(pts) -> bytes:
    return (_rec(0x0800) + _rec(0x0D02, struct.pack(">h", 1))
            + _rec(0x0E02, struct.pack(">h", 0))
            + _rec(0x1003, b"".join(struct.pack(">ii", x, y) for x, y in pts))
            + _rec(0x1100))


def flat_gds(ll=(0, 0), wh=(1000, 1000), dbu_per_um=1000.0,
             top=b"TOP") -> bytes:
    """One structure, one rectangle, lower-left at `ll` DATABASE UNITS."""
    x, y = ll
    w, h = wh
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    return (_rec(0x0002, struct.pack(">h", 600))
            + _rec(0x0102, struct.pack(">12h", *([0] * 12)))
            + _rec(0x0206, b"LIB\x00") + _units(dbu_per_um)
            + _rec(0x0502, struct.pack(">12h", *([0] * 12)))
            + _rec(0x0606, top + b"\x00")
            + _boundary(pts) + _rec(0x0700) + _rec(0x0400))


def hier_gds(sref_at=(100_000, 200_000), child_wh=(10_000, 10_000),
             dbu_per_um=1000.0) -> bytes:
    """CHILD holds the geometry at its own origin; TOP places it with an SREF.

    The whole point of the hierarchy fixture: a translation of TOP must move
    TOP's SREF origin and NOT the child's own coordinates. Moving both would
    displace every instanced cell twice, and matched/arrayed devices are
    exactly how real analog layouts are drawn."""
    cw, ch = child_wh
    child = (_rec(0x0502, struct.pack(">12h", *([0] * 12)))
             + _rec(0x0606, b"CHILD\x00")
             + _boundary([(0, 0), (cw, 0), (cw, ch), (0, ch), (0, 0)])
             + _rec(0x0700))
    top = (_rec(0x0502, struct.pack(">12h", *([0] * 12)))
           + _rec(0x0606, b"TOP\x00")
           + _rec(0x0A00) + _rec(0x1206, b"CHILD\x00")
           + _rec(0x1003, struct.pack(">ii", *sref_at))
           + _rec(0x1100) + _rec(0x0700))
    return (_rec(0x0002, struct.pack(">h", 600))
            + _rec(0x0102, struct.pack(">12h", *([0] * 12)))
            + _rec(0x0206, b"LIB\x00") + _units(dbu_per_um)
            + child + top + _rec(0x0400))


class FakeStage:
    """Stands in for the container. `grid_text` is what a `grep
    MANUFACTURINGGRID` over the PDK root would have printed."""

    def __init__(self, grid_text: str = "MANUFACTURINGGRID 0.005 ;"):
        self.grid_text = grid_text
        self.cmds = []

    def sh(self, cmd: str, timeout: int = 900):
        self.cmds.append(cmd)
        return 0, self.grid_text, ""


def _project(tmp_path, block="blk", lef_origin="0 0", gds=b"",
             size=(1000.0, 1000.0), foreign=None):
    d = tmp_path / "phase3" / "analog" / "hardmacro" / block
    d.mkdir(parents=True, exist_ok=True)
    lef = ["MACRO " + block, "  CLASS BLOCK ;"]
    if foreign is not None:
        lef.append(f"  FOREIGN {block} {foreign[0]} {foreign[1]} ;")
    lef += [f"  ORIGIN {lef_origin} ;",
            f"  SIZE {size[0]:.3f} BY {size[1]:.3f} ;", "END " + block]
    (d / f"{block}.lef").write_text("\n".join(lef) + "\n", encoding="utf-8")
    (d / f"{block}.gds").write_bytes(gds)
    return d / f"{block}.gds"


# ─────────── the translation itself: exact, and only where told ───────────

def test_a_grid_multiple_offset_is_translated_into_the_lef_frame(tmp_path):
    """The measured u_hawaii_adc shape: body 0.62/30.32um below a 0 0 ORIGIN,
    both an exact multiple of the 0.005um SG13G2 grid."""
    raw = flat_gds(ll=(-620, -30_320), wh=(556_810, 158_400))
    gds = _project(tmp_path, gds=raw, size=(556.81, 158.4))
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "ALIGNED", rec
    assert rec["offset_is_grid_multiple"] is True
    assert rec["moved_dbu"] == [620, 30_320]
    llx, lly, urx, ury = GATE.parse_gds_bbox_extent(gds.read_bytes())
    assert (round(llx, 6), round(lly, 6)) == (0.0, 0.0)
    # A RIGID move: the outline the digital floorplan reserves is unchanged.
    assert (round(urx - llx, 3), round(ury - lly, 3)) == (556.81, 158.4)


def test_the_moved_body_satisfies_the_gate_that_judges_it(tmp_path):
    """Producer and gate must agree. They import the same parsers; this proves
    the agreement end-to-end rather than trusting it."""
    raw = flat_gds(ll=(-620, -30_320), wh=(556_810, 158_400))
    gds = _project(tmp_path, gds=raw, size=(556.81, 158.4))
    before = GATE.check_block(tmp_path, "blk", GATE.DEFAULT_TOL_PCT,
                              GATE.DEFAULT_TOL_UM)
    assert before["status"] == "FAIL", before
    E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                         "/foss/pdks", "ihp-sg13g2")
    after = GATE.check_block(tmp_path, "blk", GATE.DEFAULT_TOL_PCT,
                             GATE.DEFAULT_TOL_UM)
    assert after["status"] == "PASS", after


def test_a_child_structure_is_not_moved_twice(tmp_path):
    """LOAD-BEARING. Only TOP's own records move; CHILD keeps its local
    coordinates, so the instance travels exactly once."""
    raw = hier_gds(sref_at=(100_000, 200_000), child_wh=(10_000, 10_000))
    moved = E.translate_structure(raw, "TOP", 5_000, 5_000)
    llx, lly, urx, ury = GATE.parse_gds_bbox_extent(moved)
    assert (round(llx, 3), round(lly, 3)) == (105.0, 205.0)
    assert (round(urx - llx, 3), round(ury - lly, 3)) == (10.0, 10.0)
    # CHILD's own XY record is byte-identical to the one that went in.
    child_xy = struct.pack(">ii", 0, 0)
    assert raw.count(child_xy) == moved.count(child_xy)


def test_translation_preserves_length_and_every_non_xy_record(tmp_path):
    raw = hier_gds()
    moved = E.translate_structure(raw, "TOP", 7, -3)
    assert len(moved) == len(raw)
    # Layer/datatype/sname/structure records survive verbatim.
    for marker in (b"CHILD\x00", b"TOP\x00", b"LIB\x00"):
        assert raw.count(marker) == moved.count(marker)


def test_translating_a_structure_that_is_not_there_changes_nothing():
    raw = hier_gds()
    assert E.translate_structure(raw, "ABSENT", 1000, 1000) == raw


# ─────────── the half that must NOT act: negative controls ───────────

def test_a_non_grid_multiple_offset_is_left_exactly_as_magic_wrote_it(tmp_path):
    """LOAD-BEARING NEGATIVE CONTROL. 0.0123um is past the 0.01um registration
    tolerance — so this IS a real mismatch the gate FAILs on — and it is 2.46
    grid steps, not a whole number of them. Translating here would trade a
    loud registration FAIL for a silent off-grid streamout, which is the
    failure #595 refused to risk."""
    raw = flat_gds(ll=(-12_300, -12_300), wh=(100_000, 100_000),
                   dbu_per_um=1e6)
    gds = _project(tmp_path, gds=raw, size=(0.1, 0.1))
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "NOT_ALIGNED", rec
    assert rec["offset_is_grid_multiple"] is False
    assert "FOREIGN blk" in rec["detail"]
    assert gds.read_bytes() == before, "the file was modified anyway"


def test_an_unreadable_grid_never_authorises_a_move(tmp_path):
    """A guessed grid would decide the question. There is no default."""
    raw = flat_gds(ll=(-620, -30_320), wh=(556_810, 158_400))
    gds = _project(tmp_path, gds=raw, size=(556.81, 158.4))
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(grid_text=""),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "NOT_ALIGNED", rec
    assert rec["manufacturing_grid_um"] is None
    assert rec["offset_is_grid_multiple"] is None
    assert gds.read_bytes() == before


def test_a_contradictory_pdk_grid_never_authorises_a_move(tmp_path):
    """Two different grids under one PDK root is not an answer, and picking
    the first one seen would be a guess wearing a measurement's clothes."""
    stage = FakeStage(grid_text="MANUFACTURINGGRID 0.005 ;\n"
                                "MANUFACTURINGGRID 0.001 ;\n")
    assert E.pdk_manufacturing_grid_um(stage, "/foss/pdks", "t") is None
    raw = flat_gds(ll=(-620, -30_320), wh=(556_810, 158_400))
    gds = _project(tmp_path, gds=raw, size=(556.81, 158.4))
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, stage, "/foss/pdks", "t")
    assert rec["status"] == "NOT_ALIGNED"
    assert gds.read_bytes() == before


def test_one_grid_repeated_is_still_one_answer():
    stage = FakeStage(grid_text="MANUFACTURINGGRID 0.005 ;\n"
                                "manufacturinggrid 0.005 ;\n")
    assert E.pdk_manufacturing_grid_um(stage, "/foss/pdks", "t") == 0.005


def test_a_stream_with_several_tops_is_not_guessed_at(tmp_path):
    two_tops = (_rec(0x0002, struct.pack(">h", 600))
                + _rec(0x0102, struct.pack(">12h", *([0] * 12)))
                + _rec(0x0206, b"LIB\x00") + _units()
                + _rec(0x0502, struct.pack(">12h", *([0] * 12)))
                + _rec(0x0606, b"A\x00")
                + _boundary([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
                + _rec(0x0700)
                + _rec(0x0502, struct.pack(">12h", *([0] * 12)))
                + _rec(0x0606, b"B\x00")
                + _boundary([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
                + _rec(0x0700) + _rec(0x0400))
    assert E.top_structure_name(two_tops) is None


def test_an_already_aligned_body_is_not_touched(tmp_path):
    raw = flat_gds(ll=(0, 0), wh=(556_810, 158_400))
    gds = _project(tmp_path, gds=raw, size=(556.81, 158.4))
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "ALREADY_ALIGNED", rec
    assert gds.read_bytes() == before


def test_a_block_with_no_lef_has_no_frame_to_align_to(tmp_path):
    d = tmp_path / "phase3" / "analog" / "hardmacro" / "blk"
    d.mkdir(parents=True)
    gds = d / "blk.gds"
    gds.write_bytes(flat_gds(ll=(-620, -30_320)))
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "NO_LEF"
    assert gds.read_bytes() == before


def test_an_unparseable_body_is_reported_not_moved(tmp_path):
    gds = _project(tmp_path, gds=b"not a gds at all")
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "UNMEASURED"
    assert gds.read_bytes() == before


# ─────────── the frame comes from the LEF, not from an assumption ───────────

def test_a_foreign_statement_is_the_frame_that_is_aligned_to(tmp_path):
    """A LEF that already DECLARES the offset is self-consistent, and moving
    the body would break the pair the other way — the exact "silent
    misplacement in the other direction" #595 warned about."""
    raw = flat_gds(ll=(-620, -30_320), wh=(556_810, 158_400))
    gds = _project(tmp_path, gds=raw, size=(556.81, 158.4),
                   foreign=(-0.62, -30.32))
    before = gds.read_bytes()
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "ALREADY_ALIGNED", rec
    assert rec["lef_frame_source"] == "FOREIGN"
    assert gds.read_bytes() == before


def test_a_non_zero_origin_moves_the_body_to_where_that_origin_puts_it(tmp_path):
    """`ORIGIN x y` puts the box at (-x, -y); the body must land there, not
    at (0, 0). Hardcoding the origin would pass the common case and
    misplace this one."""
    raw = flat_gds(ll=(0, 0), wh=(100_000, 100_000))
    gds = _project(tmp_path, gds=raw, lef_origin="1.5 2.5", size=(100.0, 100.0))
    rec = E.align_to_lef_frame(tmp_path, "blk", gds, FakeStage(),
                               "/foss/pdks", "ihp-sg13g2")
    assert rec["status"] == "ALIGNED", rec
    llx, lly, _, _ = GATE.parse_gds_bbox_extent(gds.read_bytes())
    assert (round(llx, 6), round(lly, 6)) == (-1.5, -2.5)
