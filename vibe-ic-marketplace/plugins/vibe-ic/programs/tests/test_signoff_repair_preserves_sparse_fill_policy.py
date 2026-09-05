"""Regression for run7's promoted-route device-layer fill loss."""
from __future__ import annotations

import inspect
from pathlib import Path
import sys


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


MASTERS = [
    "gf180mcu_fd_sc_mcu7t5v0__fillcap_64",
    "gf180mcu_fd_sc_mcu7t5v0__fill_64",
    "gf180mcu_fd_sc_mcu7t5v0__fill_1",
]


def _deck(**fill_context: bool) -> str:
    return R._ship_signoff_spef_repair_tcl(
        "chip_top", "/pdk/tech.lef", "/pdk/cells.lef", "/pdk/ss.lib",
        "/work/pnr", "/pdk/max.captable", "Metal", 8,
        filler_masters=MASTERS, **fill_context)


def test_pad_wrapper_repair_restores_device_free_active_row_fill():
    tcl = _deck(sparse_active_row_fill=True)
    assert "remove_fillers" in tcl
    assert "SPARSE_DIE_ACTIVE_ROW_FILL:" in tcl
    assert "selector=functional_core_mterm" in tcl
    assert "VIBEIC_ACTIVE_ROW_FILL_" in tcl
    below = tcl[tcl.index("SPARSE_DIE_ACTIVE_ROW_FILL:"):
                tcl.index("SPARSE_DIE_ACTIVE_ROW_FILL_DONE:")]
    assert "fillcap_64" not in below
    assert "fill_64" in below
    assert tcl.index("remove_fillers") < tcl.index("SPARSE_DIE_ACTIVE_ROW_FILL:")
    assert tcl.index("SPARSE_DIE_ACTIVE_ROW_FILL_DONE:") < tcl.index("write_def")


def test_context_absence_keeps_the_bounded_skip_arm():
    tcl = _deck()
    assert "SPARSE_DIE_FILL_SKIPPED:" in tcl
    assert "SPARSE_DIE_ACTIVE_ROW_FILL:" not in tcl


def test_production_step_derives_and_forwards_all_three_floorplan_facts():
    source = inspect.getsource(R.step_signoff_spef_repair)
    for token in (
        "_slot_geometry(project)",
        "_l9_declared_die_area(project)",
        "_l19_declared_die_area(project)",
        "_padring_core_inset_um(project)",
        "slot_pinned_core=_repair_slot is not None",
        "design_declared_die=_repair_declared_die",
        "sparse_active_row_fill=bool(",
    ):
        assert token in source
