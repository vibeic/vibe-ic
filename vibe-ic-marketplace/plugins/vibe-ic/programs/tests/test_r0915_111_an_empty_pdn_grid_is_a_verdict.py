"""R-0915-111: a pdngen that builds no grid is a NAMED refusal at the PDN step.

MEASURED on spm x gf180mcuD (run10, 2026-09-21, front door, live main): the EM
floor widened the Metal5 strap from 1.6 to 1.96 um, the macro-grid plan kept the
4.655 um pitch it had derived for 1.6, and pdngen refused the deck outright:

    [ERROR PDN-0108] Spacing (0.3650 um) specified for layer Metal5 is less
                     than minimum spacing (0.4600 um)
    PDN_NONFATAL: PDN-0108

0.3650 = 4.655/2 - 1.96. pdngen emitted NOTHING — the DEF that run carried has
no Metal4 SPECIALNETS geometry at all — the note scrolled past, and the flow
discovered it two steps and 143 s later as

    PG_UNROUTED_SUPPLY: 2 POWER/GROUND net(s) carry real terminals and no
    special-net geometry — pdngen did not build the grid

with no GDS, `drc` NOT_MEASURED, `lvs` skipped and `tapeout_precheck` FAIL.

TWO DEFECTS, AND THIS FILE PINS BOTH.

  1. THE ARITHMETIC. `_macro_pdn_grid_plan` floored the pitch at
     `2*width + spacing`. pdngen lays the power AND the ground strap inside one
     pitch, so the gap it measures is `pitch/2 - width`: the floor is
     `2*(width + spacing)`. The two agree while the strap is narrow (at 1.6 um:
     3.66 vs 4.12, and the 4.655 um pitch clears both), which is why this held
     until an EM floor widened one.

  2. THE SILENCE. A `catch` printed `PDN_NONFATAL: <err>` and walked on. Now
     every supply net that carries a real terminal must own special-net
     geometry after pdngen, and a net that does not raises PDN_GRID_EMPTY
     carrying pdngen's OWN reason.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

#: run10's own numbers.
W_EM, SPACING, PORT = 1.96, 0.46, 4.655


# ------------------------------------------------------------ the arithmetic

def test_the_pitch_floor_holds_two_straps_not_one():
    """`pitch/2 - width >= spacing`, i.e. `pitch >= 2*(width+spacing)`."""
    src = inspect.getsource(R._macro_pdn_grid_outcome)
    assert "2.0 * (sw + s_minw)" in src, "the floor must hold two straps"
    assert "2.0 * sw + s_minw" not in src, "the one-strap floor is the defect"


def test_run10s_width_is_refused_by_the_corrected_floor():
    """The measured case, as arithmetic: 1.96 um straps cannot live on a
    4.655 um pitch, and the old floor said they could."""
    old_floor = 2.0 * W_EM + SPACING                 # 4.38  -> 4.655 "fits"
    new_floor = 2.0 * (W_EM + SPACING)               # 4.84  -> 4.655 refused
    assert old_floor < PORT < new_floor
    # and pdngen's own measure of the gap that pitch would give
    assert round(PORT / 2 - W_EM, 4) == 0.3675       # < 0.46, i.e. PDN-0108


def test_the_narrow_strap_that_worked_still_works():
    """The other direction: at the width the flow drew before any EM floor,
    the corrected floor still admits the same pitch, so a design that never
    widens is untouched."""
    assert 2.0 * (1.6 + SPACING) == 4.12 <= PORT


def test_the_refusal_names_the_two_strap_arithmetic():
    src = inspect.getsource(R._macro_pdn_grid_outcome)
    assert "2*(width+spacing)" in src
    assert "pitch/2-width" in src


# ------------------------------------------------------------- the silence









# ------------------------------------------- stripes first, width second (2)















# --------------------------------- the geometry it hands pdngen must be legal
