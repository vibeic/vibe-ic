#!/usr/bin/env python3
"""Sparse fixed wrappers must fill occupied rows without flooding empty rows."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phase3_one_shot_runner as R  # noqa: E402


MASTERS = ["lib__fillcap_8", "lib__fill_8", "lib__fill_4", "lib__fill_1"]


def test_sparse_active_row_fill_is_structural_bounded_and_device_free():
    tcl = R._build_sparse_die_aware_filler_tcl(
        MASTERS, sparse_active_row_fill=True)
    assert "SPARSE_DIE_ACTIVE_ROW_FILL" in tcl
    assert "getMTerms" in tcl
    assert 'eq "POWER"' in tcl and 'eq "GROUND"' in tcl
    assert "getIoType" in tcl
    assert "VIBEIC_ACTIVE_ROW_FILL_" in tcl
    assert "dbInst_destroy" in tcl
    assert "array size _arf_active_y" in tcl
    assert "_arf_active_y([$_arf_bb yMin])" in tcl
    active_arm = tcl.split("SPARSE_DIE_ACTIVE_ROW_FILL", 1)[1]
    assert "filler_placement" in active_arm
    assert "lib__fill_8 lib__fill_4 lib__fill_1" in active_arm
    assert "fillcap" not in active_arm


def test_sparse_active_row_fill_is_opt_in_for_fixed_wrapper_geometry():
    legacy = R._build_sparse_die_aware_filler_tcl(MASTERS)
    assert "SPARSE_DIE_FILL_SKIPPED" in legacy
    assert "SPARSE_DIE_ACTIVE_ROW_FILL" not in legacy


def test_design_owned_floorplans_keep_the_existing_full_spacer_arm():
    tcl = R._build_sparse_die_aware_filler_tcl(
        MASTERS, design_declared_die=True, sparse_active_row_fill=True)
    assert "SPARSE_DIE_FILL_NOT_APPLICABLE" in tcl
    assert "SPARSE_DIE_ACTIVE_ROW_FILL" not in tcl
