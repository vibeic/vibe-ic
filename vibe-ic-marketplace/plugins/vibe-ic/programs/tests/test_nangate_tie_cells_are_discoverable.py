"""Nangate / Si2 Open-Cell tie cells are LOGIC0_X1 / LOGIC1_X1.

The tie-cell discoverer's token vocabulary (`conb`, `conp`, `tiehi`, `tielo`,
`tieh`, `tiel`, `tiep`, `tien`) did not include the Nangate spelling.  The A8
comment beside the patterns records this explicitly -- "nangate (unmatched, as
before)" -- when the ASAP7 suffix was added.  This closes that gap.

MEASURED, edge_llm_accel x nangate45, v1.9.65, on a library that DOES ship both
cells (`cell (LOGIC0_X1)` / `cell (LOGIC1_X1)` in the Liberty, `MACRO
LOGIC0_X1` / `MACRO LOGIC1_X1` in the LEF).  Two independent consequences in
one run:

  * ``SPARE_TIEOFF_SKIPPED: no tie-low cell discovered in this PDK liberty --
    spare inputs remain floating`` beside ``SPARE_FIRM_LOCKED: 27121
    instances``.  27,121 design-for-ECO spare cells placed with FLOATING
    inputs, and ``tied_off`` left false -- a hard FAIL condition of
    ``spare_cell_coverage_check`` ("PASS iff ... all spares are tied off").
  * ``hilomap`` stayed inert, so 1'b0 / 1'b1 literals reached the DEF as
    constant nets: ``PG_CLEANUP_DEL: zero_ (GROUND)`` and
    ``PG_CLEANUP_UNROUTED_SUPPLY: one_ (POWER) iterms=780 bterms=0`` -- the
    same `Net zero_` shape v1.6.604 fixed for sky130A.

chip-AGNOSTIC: `logic0` / `logic1` is standard-cell-library naming vocabulary,
exactly like `conb` / `tiehi`.  The digit is part of the token, so a functional
`LOGIC_AND2` cannot match -- the bare `hi`/`lo` alternatives the A8 comment
rejected as over-matching are NOT reintroduced.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase3_one_shot_runner as P  # noqa: E402

HI = P._V1_6_596_TIE_HI_PAT
LO = P._V1_6_596_TIE_LO_PAT


# ── the defect ────────────────────────────────────────────────────────────

def test_nangate_tie_cells_match_their_own_pattern():
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix."""
    assert HI.search("logic1_x1"), "LOGIC1_X1 is not recognised as tie-high"
    assert LO.search("logic0_x1"), "LOGIC0_X1 is not recognised as tie-low"


def test_the_two_nangate_cells_do_not_cross_match():
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix.

    The discoverer's HI/LO disambiguation relies on a tie-high name not also
    matching the tie-low pattern; assert the two new tokens are disjoint or
    the cells would be assigned to the wrong rail.
    """
    assert not LO.search("logic1_x1")
    assert not HI.search("logic0_x1")


def test_discovery_on_a_nangate_shaped_liberty(tmp_path):
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix.

    End-to-end through the discoverer, including the output-pin sniff, on a
    minimal Liberty in the Nangate shape (pg_pin before the signal pin, which
    is the #404 R2 trap the pin regex was hardened against).
    """
    lib = tmp_path / "opencell_typical.lib"
    lib.write_text(
        'library (opencell) {\n'
        '  cell (AND2_X1) {\n'
        '    pg_pin(VDD) { }\n'
        '    pin (ZN) { direction : output; }\n'
        '  }\n'
        '  cell (LOGIC0_X1) {\n'
        '    pg_pin(VDD) { }\n'
        '    pin (Z) { direction : output; function : "0"; }\n'
        '  }\n'
        '  cell (LOGIC1_X1) {\n'
        '    pg_pin(VDD) { }\n'
        '    pin (Z) { direction : output; function : "1"; }\n'
        '  }\n'
        '}\n')
    got = P._v1_6_596_discover_tie_cells(str(lib))
    assert got["hi_cell"] == "LOGIC1_X1", got
    assert got["lo_cell"] == "LOGIC0_X1", got
    assert got["hi_pin"] == "Z", got
    assert got["lo_pin"] == "Z", got


# ── what must keep working (these pass BOTH before and after) ─────────────

def test_a_functional_logic_cell_is_not_a_tie_cell():
    """TIGHTENING GUARD — `logic` alone must not match; the digit is part of
    the token.  This is the over-match the A8 comment rejected."""
    for name in ("logic_and2", "logicgate_x1", "and2_logic", "logicx1"):
        assert not HI.search(name), name
        assert not LO.search(name), name


def test_sky130_and_gf180_and_ihp_and_asap7_vocabularies_are_unchanged():
    """The other shipped libraries must resolve exactly as before."""
    assert HI.search("sky130_fd_sc_hd__conb_1")
    assert LO.search("sky130_fd_sc_hd__conb_1")
    assert HI.search("gf180mcu_fd_sc_mcu7t5v0__tieh")
    assert LO.search("gf180mcu_fd_sc_mcu7t5v0__tiel")
    assert HI.search("sg13g2_tiehi")
    assert LO.search("sg13g2_tielo")
    assert HI.search("tiehix1_asap7_75t_r")
    assert LO.search("tielox1_asap7_75t_r")


def test_the_sky130_dual_cell_still_serves_both_rails(tmp_path):
    """conb_1 is one cell with HI and LO outputs; that path is untouched."""
    lib = tmp_path / "sky.lib"
    lib.write_text(
        'library (sky) {\n'
        '  cell ("sky130_fd_sc_hd__conb_1") {\n'
        '    pg_pin(VPWR) { }\n'
        '    pin (HI) { direction : output; }\n'
        '    pin (LO) { direction : output; }\n'
        '  }\n'
        '}\n')
    got = P._v1_6_596_discover_tie_cells(str(lib))
    assert got["hi_cell"] == "sky130_fd_sc_hd__conb_1", got
    assert got["lo_cell"] == "sky130_fd_sc_hd__conb_1", got
