"""#168 (A8) — tie-cell discovery must recognise a library that appends a
drive-strength + library suffix AFTER the tie token.

The pre-fix trailing anchor (`_?\\d*$`) matched sky130's end-anchored
`…__conb_1` but NOT ASAP7's `TIEHIx1_ASAP7_75t_R` / `TIELOx1_ASAP7_75t_R`
(token then `x1_ASAP7_75t_R`), so `_v1_6_596_discover_tie_cells` returned
`lo_cell=None`; the spare-input tie-off then emitted SPARE_TIEOFF_SKIPPED and
`spare_cells.json` carried `tied_off=false`, FAILing spare_cell_coverage_check
on spm/ASAP7. These tests prove ASAP7-style names are now discovered while
sky130 (conb/conp) and nangate (LOGIC0/1, never matched) are byte-identical.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ASAP7-style tie cells: TIE token + `x1` drive strength + `_ASAP7_75t_R`
# library suffix, with the canonical pg_pin-before-signal-pin shape and
# ASAP7's real output-pin names (H / L).
_ASAP7_LIB = """\
library(asap7_tie) {
  cell (TIEHIx1_ASAP7_75t_R) {
    area : 0.1 ;
    pg_pin (VDD) { pg_type : primary_power ; }
    pg_pin (VSS) { pg_type : primary_ground ; }
    pin (H) { direction : output ; function : "1" ; }
  }
  cell (TIELOx1_ASAP7_75t_R) {
    area : 0.1 ;
    pg_pin (VDD) { pg_type : primary_power ; }
    pg_pin (VSS) { pg_type : primary_ground ; }
    pin (L) { direction : output ; function : "0" ; }
  }
}
"""

# sky130 dual-output tie cell (conb_1) — the pre-fix path already handled it;
# these assertions pin that it is UNCHANGED.
_SKY130_LIB = """\
library(sky130) {
  cell (sky130_fd_sc_hd__conb_1) {
    pg_pin (VPWR) { pg_type : primary_power ; }
    pg_pin (VGND) { pg_type : primary_ground ; }
    pin (HI) { direction : output ; function : "1" ; }
    pin (LO) { direction : output ; function : "0" ; }
  }
}
"""

# nangate uses LOGIC0_X1 / LOGIC1_X1 — no tie/con/hi/lo token; it was never
# matched by this discoverer and MUST stay unmatched (behaviour identical).
_NANGATE_LIB = """\
library(nangate) {
  cell (LOGIC1_X1) { pin (Z) { direction : output ; function : "1" ; } }
  cell (LOGIC0_X1) { pin (Z) { direction : output ; function : "0" ; } }
}
"""


def _write(tmp, text):
    p = tmp / "lib.lib"
    p.write_text(text)
    return str(p)


def test_asap7_suffixed_tie_cells_discovered(tmp_path):
    out = R._v1_6_596_discover_tie_cells(_write(tmp_path, _ASAP7_LIB))
    assert out["hi_cell"] == "TIEHIx1_ASAP7_75t_R"
    assert out["lo_cell"] == "TIELOx1_ASAP7_75t_R"
    # the real output-pin names are read from the liberty (not the HI/LO default)
    assert out["hi_pin"] == "H"
    assert out["lo_pin"] == "L"


def test_asap7_tie_low_enables_tied_off_flag(tmp_path):
    # The spm/ASAP7 FAIL was `tied_off != true`; with lo_cell now discovered the
    # runner's honest flag (bool(lo_cell and instances)) becomes true.
    out = R._v1_6_596_discover_tie_cells(_write(tmp_path, _ASAP7_LIB))
    assert bool(out["lo_cell"])  # the load-bearing condition for tied_off


def test_sky130_conb_unchanged(tmp_path):
    out = R._v1_6_596_discover_tie_cells(_write(tmp_path, _SKY130_LIB))
    assert out["hi_cell"] == "sky130_fd_sc_hd__conb_1"
    assert out["lo_cell"] == "sky130_fd_sc_hd__conb_1"
    assert out["hi_pin"] == "HI"
    assert out["lo_pin"] == "LO"


def test_the_a8_suffix_broadening_alone_never_matched_a_bare_logic_name():
    # SUPERSEDED SCOPE LIMIT. This was `test_nangate_logic_cells_still_
    # unmatched`, and it asserted the BLAST RADIUS of the #168 A8 change:
    # broadening the trailing group for ASAP7's `TIE(HI|LO)x1_...` names must
    # not have started matching nangate's LOGIC0/1_X1 as a side effect. That
    # was true and still is.
    #
    # It was NOT a decision that nangate tie cells should stay undiscovered.
    # `LOGIC0_X1` / `LOGIC1_X1` are the Nangate / Si2 Open-Cell tie cells, and
    # leaving them unmatched placed 27,121 design-for-ECO spare cells with
    # FLOATING inputs on a real run. They are now matched by an EXPLICIT
    # `logic0` / `logic1` token, not by the A8 suffix rule — so the invariant
    # this test actually guards is unchanged and is restated here directly:
    # the A8 trailing-suffix group does not turn a bare `logic`-family name
    # into a tie cell.
    for name in ("logic_and2", "logicgate_x1", "and2_logic", "logicx1"):
        assert not R._V1_6_596_TIE_HI_PAT.search(name), name
        assert not R._V1_6_596_TIE_LO_PAT.search(name), name


def test_nangate_logic_cells_are_now_discovered(tmp_path):
    # The replacement of the assertion above: the same fixture, the intended
    # verdict. See test_nangate_tie_cells_are_discoverable.py for the measured
    # consequence that motivated it.
    out = R._v1_6_596_discover_tie_cells(_write(tmp_path, _NANGATE_LIB))
    assert out["hi_cell"] == "LOGIC1_X1", out
    assert out["lo_cell"] == "LOGIC0_X1", out
