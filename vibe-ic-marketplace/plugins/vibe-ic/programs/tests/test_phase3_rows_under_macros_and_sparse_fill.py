#!/usr/bin/env python3
"""Two floorplan omissions, one consequence each, both measured on a real die.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phase3_one_shot_runner as R  # noqa: E402


# ---------------------------------------------------------------------------
# 1. A ROW UNDER A MACRO IS A ROW THE PDN MUST STRAP AND CANNOT.
#
# `initialize_floorplan` lays rows across the whole core and nothing removed
# the ones the macros cover, so `pdngen` saw follow-pin rails inside every
# macro and in the few-micron slivers between macro and core edge, could not
# reach them with a strap, and returned `PDN-0178 Remaining channel …` x7 then
# `[ERROR PDN-0179] Unable to repair all channels` — reported as PDN_NONFATAL,
# which makes the pnr step BLOCKED and SKIPs DRC, LVS and the whole sign-off
# tail. In a hand-run of the same design the rails that DID get built ran
# through the macros' own metal and produced 105 of 151 die DRC violations.
# Measured after: 7 channels -> 0, no PDN-0179, and no PDN ring needed (a ring
# was tried first and left 6 of the 7 — the channels are rows, not a missing
# edge feed).
# ---------------------------------------------------------------------------

def test_rows_are_cut_under_placed_macros_before_the_pdn():
    src = R.__file__ and Path(R.__file__).read_text()
    assert "cut_rows -halo_width_x" in src
    # and it is GUARDED: an OpenROAD without the command must leave the flow
    # as it was rather than abort the deck
    assert "CUT_ROWS_NONFATAL" in src
    assert "CUT_ROWS_DONE" in src
    # …and it must sit INSIDE the macro-placement block — between the placer
    # call and the DEF that block writes — because that block is emitted
    # before the PDN section of the template. Cutting rows after the PDN has
    # already been generated repairs nothing.
    lo = src.index("rtl_macro_placer -halo_width")
    hi = src.index("macro_placed.def", lo)
    assert lo < src.index("cut_rows -halo_width_x") < hi


# ---------------------------------------------------------------------------
# 2. A DESIGN'S OWN DECLARED DIE IS NOT AN EMPTY FIXED WRAPPER.
#
# The sparse-die guard skips full-die fill below a utilization threshold, to
# avoid tiling a wrapper the design does not own. On a design whose L19 states
# its die verbatim and whose core utilization is 0.08%, the skip fired, NO
# filler was placed anywhere, and the sign-off deck reported 6 `NW.b` WELL
# notches — one at every one-site gap between a tie cell and its neighbour.
# The skip's own text says the occupied region is "covered by the downstream
# metal-fill gate", which is true of METAL and false of a WELL.
# ---------------------------------------------------------------------------

_MASTERS = ["x_decap_8", "x_decap_4", "x_fill_8", "x_fill_4", "x_fill_2",
            "x_fill_1"]


def test_a_design_declared_die_gets_a_device_free_fill():
    tcl = R._build_sparse_die_aware_filler_tcl(
        _MASTERS, slot_pinned_core=False, design_declared_die=True)
    assert "SPARSE_DIE_FILL_NOT_APPLICABLE" in tcl
    assert "SPARSE_DIE_FILL_SKIPPED" not in tcl.split(
        "SPARSE_DIE_FILL_NOT_APPLICABLE")[1]
    # DEVICE-FREE: the decap family stays withheld on THIS arm (the
    # above-threshold arm in the same block still uses the full master list)
    arm = tcl.split("SPARSE_DIE_FILL_NOT_APPLICABLE")[1].split("} else")[0]
    assert "x_fill_1" in arm
    assert "decap" not in arm


def test_a_shuttle_slot_still_takes_the_same_arm():
    tcl = R._build_sparse_die_aware_filler_tcl(
        _MASTERS, slot_pinned_core=True, design_declared_die=False)
    assert "SPARSE_DIE_FILL_NOT_APPLICABLE" in tcl


def test_neither_signal_keeps_the_legacy_skip():
    """The guard still exists: a design that neither pins a slot nor declares
    its own die is exactly the empty-fixed-wrapper case it was written for."""
    tcl = R._build_sparse_die_aware_filler_tcl(
        _MASTERS, slot_pinned_core=False, design_declared_die=False)
    assert "SPARSE_DIE_FILL_SKIPPED" in tcl
    assert "SPARSE_DIE_FILL_NOT_APPLICABLE" not in tcl


def test_no_masters_is_still_a_named_skip():
    tcl = R._build_sparse_die_aware_filler_tcl([], design_declared_die=True)
    assert "FILLER_SKIPPED" in tcl
