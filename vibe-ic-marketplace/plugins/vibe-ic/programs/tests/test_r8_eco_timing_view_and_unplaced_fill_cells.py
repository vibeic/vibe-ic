"""r8 — three sign-off paths that answered about a design other than the one shipped.

Measured on `subservient` x `gf180mcuD` (Vibe-IC benchmark matrix, r8). Each test
below pins a fact taken from that run's own artefacts, quoted in the assertion
message so a failure says what changed rather than only that something did.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402


PDK = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
CORNER_LIBS = {
    "ss": f"{PDK}/lib/gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib",
    "tt": f"{PDK}/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib",
    "ff": f"{PDK}/lib/gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib",
}


def _eco_tcl(top="subservient", pnr="/run/phase3/stage3/pnr"):
    return p3._build_eco_repair_tcl(
        top, f"{PDK}/techlef/x.tlef", f"{PDK}/lef/x.lef", CORNER_LIBS["tt"],
        pnr, "/run/phase3/stage3/eco", "Metal", corner_libs=CORNER_LIBS)


# ---------------------------------------------------------------------------
# 1. The ECO was triggered by a number its own timing view could not contain.
# ---------------------------------------------------------------------------

def test_eco_deck_carries_the_same_clock_and_derate_as_the_measurement_that_fires_it():
    """The auto-trigger fires on the multi-corner OCV sign-off number. Every deck
    that produces that number applies a flat-OCV derate and a PROPAGATED clock;
    the ECO deck applied neither, so `repair_timing -setup` analysed a more
    optimistic design than the one that failed and logged
    `RSZ-0098 No setup violations found` on both passes.
    """
    tcl = _eco_tcl()
    assert "set_propagated_clock [all_clocks]" in tcl, (
        "the ECO deck reads a post-CTS DEF; an ideal clock cannot describe it")
    assert f"set_timing_derate -early {p3._FLAT_OCV_DERATE_EARLY}" in tcl
    assert f"set_timing_derate -late {p3._FLAT_OCV_DERATE_LATE}" in tcl, (
        "the ECO must not analyse without the derate the trigger measured with")


def test_the_propagated_clock_disclosure_states_why_it_applies_here():
    """`_propagated_clock_tcl` names post-route SPEF annotation as its reason,
    and this deck annotates none — it uses `estimate_parasitics`. The reason is
    different (post_hold.def is POST-CTS), so the emitted comment must say that
    rather than assert something untrue of the deck it sits in."""
    tcl = _eco_tcl()
    assert "post_hold.def is POST-CTS" in tcl
    assert "Post-route parasitics are annotated" not in tcl
    # the default caller is untouched
    assert "Post-route parasitics are annotated" in p3._propagated_clock_tcl()


def test_derate_and_clock_are_applied_after_the_design_sdc_is_read():
    """Order matters: both commands must land after `read_sdc` so a design SDC
    that already sets them is not contradicted."""
    tcl = _eco_tcl()
    assert tcl.index("read_sdc") < tcl.index("set_propagated_clock")
    assert tcl.index("read_sdc") < tcl.index("set_timing_derate -early")


# ---------------------------------------------------------------------------
# 3. A fill cell that was never placed is a second top cell.
# ---------------------------------------------------------------------------

def _pya_or_skip():
    try:
        import pya  # noqa: F401
        return pya
    except Exception:                                    # pragma: no cover
        pytest.skip("KLayout pymod (pya) not importable in this environment")


def test_unplaced_fill_cell_does_not_become_a_second_top_cell(tmp_path):
    """`fill_layer` creates one `FILL_<layer>_<size>` cell per ladder rung before
    it knows whether the rung fits. A rung that places nothing used to stay in
    the stream with zero instances, and GDS has no notion of an unused cell — it
    is another root. gf180mcu's own sign-off deck then refuses the file before a
    single rule runs:

        ERROR: 'source': The layout has multiple top cells in Layout::top_cell

    Reproduced here on a layout whose only open channel is far narrower than the
    ladder's top rung.
    """
    pya = _pya_or_skip()
    sys.path.insert(0, str(PROGRAMS / "metal_fill"))
    import metal_fill

    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("TOP")
    li = ly.layer(36, 0)
    # A die with two drawn stripes leaving one ~6 um channel: the 3.37 um top
    # rung cannot be placed once the 2 um dummy-to-drawn keep-out is applied.
    top.shapes(li).insert(pya.Box(0, 0, 50000, 22000))
    top.shapes(li).insert(pya.Box(0, 28000, 50000, 50000))
    gds_in = tmp_path / "in.gds"
    ly.write(str(gds_in))

    cfg = {
        "boundary_layer": None, "window_um": None, "max_passes": 4,
        "mfg_grid_um": 0.005, "fill_datatype": None,
        "layers": [{"name": "metal2", "layer": [36, 0], "target": 0.35,
                    "max": 0.95, "space": 0.98, "space_to_metal": 2.0,
                    "width": 3.37, "fill_datatype": 4}],
    }
    out = tmp_path / "out.gds"
    res = metal_fill.run(str(gds_in), cfg, str(out), "TOP")
    assert "unplaced_fill_cells_pruned" in res, (
        "the report must disclose which fill cells it removed")
    assert res["unplaced_fill_cells_pruned"], (
        "this fixture is built so at least one ladder rung cannot be placed; "
        "if none was pruned the fixture stopped reproducing the defect")

    back = pya.Layout()
    back.read(str(out))
    tops = [back.cell(i).name for i in back.each_top_cell()]
    assert tops == ["TOP"], (
        f"a sign-off DRC deck reads this file with `source`; extra roots {tops} "
        "abort it before any rule executes")


def test_a_fill_that_placed_something_keeps_its_cell(tmp_path):
    """Negative control: pruning must only remove cells that were never
    instanced, so a normal fill is unaffected."""
    pya = _pya_or_skip()
    sys.path.insert(0, str(PROGRAMS / "metal_fill"))
    import metal_fill

    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("TOP")
    li = ly.layer(36, 0)
    # A 100x100 um die (boundary layer sets the extent) with one thin drawn
    # stripe: the top rung fits easily, so nothing should be pruned.
    top.shapes(ly.layer(0, 0)).insert(pya.Box(0, 0, 100000, 100000))
    top.shapes(li).insert(pya.Box(0, 0, 100000, 2000))
    gds_in = tmp_path / "in.gds"
    ly.write(str(gds_in))
    cfg = {
        "boundary_layer": None, "window_um": None, "max_passes": 4,
        "mfg_grid_um": 0.005, "fill_datatype": None,
        "layers": [{"name": "metal2", "layer": [36, 0], "target": 0.35,
                    "max": 0.95, "space": 0.98, "space_to_metal": 2.0,
                    "width": 3.37, "fill_datatype": 4}],
    }
    out = tmp_path / "out.gds"
    res = metal_fill.run(str(gds_in), cfg, str(out), "TOP")
    assert res["layers"][0]["fill_shapes"] > 0, "fixture placed no fill at all"
    assert res["unplaced_fill_cells_pruned"] == [], (
        "a rung that placed shapes must keep its cell: "
        f"{res['unplaced_fill_cells_pruned']}")
    back = pya.Layout()
    back.read(str(out))
    assert [back.cell(i).name for i in back.each_top_cell()] == ["TOP"]
    assert any(back.cell(i).name.startswith("FILL_")
               for i in range(back.cells())), "the placed fill cell was removed"


# ---------------------------------------------------------------------------
# 4. The DRV seed is geometric; whether a wire is too long is electrical.
# ---------------------------------------------------------------------------

def test_signoff_drv_seed_is_raised_to_the_tools_own_electrical_floor():
    """OpenROAD prints its answer on every pass it disagrees with
    (`RSZ-0065 max wire length less than 7936u increases wire delays`) while the
    seed was `int(min(die_w, die_h)/8)` = 150 um. FLOOR-ONLY: the raise can never
    tighten a run."""
    tcl = p3._v1_8_100_signoff_drv_repair_tcl("/run/phase3/stage3/pnr")
    assert "rsz::find_max_wire_length" in tcl
    assert "SDR_MWL_RAISED_TO_ELECTRICAL_FLOOR" in tcl
    assert "if {$_sdr_crit > $_sdr_mwl} {" in tcl, (
        "the raise must be conditional, so a tighter electrical floor is ignored")
    assert "SDR_CRIT_WIRE_LEN_NONFATAL" in tcl, (
        "an OpenROAD without the command must keep the geometric seed")
