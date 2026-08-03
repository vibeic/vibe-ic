"""ORGANIC #563 r4 — one tie driver PER SPARE, not one for the whole pool.

WHY
===
`_build_spare_postfix_tcl` ties every floating spare INPUT to a tie-low net so
netgen sees a driven pin (#563 r2 — floating spare inputs get wired to a
neighbour's pseudo-net and LVS mismatches). Until r4 it did that with ONE tie
driver and ONE net for the entire pool.

MEASURED (caravel_user_project x sky130A, plugin v1.9.71, image
ghcr.io/vibeic/vibeic-eda:0.2.62), read from the run's own routed DEF:

    net spare_tielo : 38 connections on 27 instances
                      = 1 tie driver + 20 spare inputs + 17 antenna diodes
    placement span  : x 17.02 .. 2677.20 um, y 184.96 .. 2287.52 um

One tie cell against 37 sinks over a 2.66 mm x 2.10 mm box. The net is
`setDoNotTouch` by design (a dont_touch LOAD pin makes `repair_design` raise
RSZ-3006 and abort the WHOLE repair pass), so no repair stage may buffer it —
sign-off STA reported 54 max_slew rows against a 1.50 ns limit, at 6.98 / 4.08 /
3.23 ns, every one of them on that net, and the post-route STA step FAILed.

v1.8.100 had already moved the single driver from `instances[0]` to the MEDIAN
spare. That is the right move for one driver and it does not change the shape:
the shape is one driver against the whole pool.

r4 gives each spare its own tie driver at its own coordinates. Every tie net is
then one spare's input count (2-6 pins) over ~0 um of wire, so the transition is
a cell delay, not an RC tree. The Design-for-ECO contract is untouched: every
spare input is still tied, every spare instance is still dont_touch + FIRM, and
every tie net is still dont_touch.

NEGATIVE CONTROL. `test_pre_r4_shape_is_gone` fails against the pre-r4 producer
(which emits exactly one `place_inst -name spare_tielo_drv`), so this file
cannot pass on the code it was written to change.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "p3_r4", _PROGRAMS / "phase3_one_shot_runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p3_r4"] = mod
    spec.loader.exec_module(mod)
    return mod


P3 = _load()

# Three spares at deliberately far-apart coordinates — the pre-r4 producer put
# ONE driver at the median of these, ~1.3 mm from the outer two.
_PLAN = {"instances": [
    {"name": "spare_dff_0", "cell": "CELL_A", "llx": 100, "lly": 200},
    {"name": "spare_nand2_0", "cell": "CELL_B", "llx": 1400, "lly": 1500},
    {"name": "spare_oai_0", "cell": "CELL_C", "llx": 2800, "lly": 3400},
]}


def _tcl() -> str:
    return P3._build_spare_postfix_tcl(_PLAN, tie_lo_cell="TIE_LO_CELL",
                                       tie_lo_pin="LO")


def test_one_driver_per_spare_at_that_spares_own_location():
    """N spares -> N drivers, each placed from the per-spare coordinate list."""
    t = _tcl()
    # the coordinate list carries every spare's OWN x/y, not one median pair
    triples = re.findall(r"\{(spare_\w+) (\d+) (\d+)\}", t)
    assert triples == [("spare_dff_0", "100", "200"),
                       ("spare_nand2_0", "1400", "1500"),
                       ("spare_oai_0", "2800", "3400")], triples
    # the driver is placed at the loop variable, so one per iteration
    assert "-location [list $_sx $_sy]" in t
    assert "place_inst -name ${_dnm}_drv" in t


def test_pre_r4_shape_is_gone():
    """NEGATIVE CONTROL — the single pool-wide driver must not be emitted.

    The pre-r4 producer emits `place_inst -name spare_tielo_drv ... -location
    {<median_x> <median_y>}` exactly once. If that line reappears this test
    fails, which is what makes the rest of this file meaningful.
    """
    t = _tcl()
    assert "place_inst -name spare_tielo_drv " not in t, (
        "one pool-wide tie driver is back")
    assert "findNet spare_tielo\"" not in t
    # and no literal median computation survives
    assert re.search(r"-location \{\d+ \d+\}", t) is None, (
        "a constant driver location means one driver for the whole pool")


def test_each_spare_gets_its_own_net_name():
    t = _tcl()
    assert "set _dnm spare_tielo_$_sn" in t, (
        "the tie net must be derived from the spare's own name")
    assert "lappend _spare_tie_nets $_dnm" in t


def test_sinks_are_connected_only_to_that_spares_net():
    """The connect loop must run INSIDE the per-spare iteration.

    If it ran outside, every sink would land on whichever `$_tlnet` was set
    last — which is the pool-wide net under a different name.
    """
    t = _tcl()
    i_dnm = t.index("set _dnm spare_tielo_$_sn")
    i_connect = t.index("odb::dbITerm_connect $_it $_tlnet")
    i_loop_end = t.index("puts \"SPARE_TIEOFF_CONNECTED")
    assert i_dnm < i_connect < i_loop_end


def test_a_spare_with_no_floating_input_gets_no_driver():
    """COUNT FIRST, PLACE SECOND — no tie cell for a spare that needs none."""
    t = _tcl()
    i_need = t.index("set _need 0")
    i_place = t.index("place_inst -name ${_dnm}_drv")
    assert i_need < i_place
    assert "if {$_need == 0} { continue }" in t


def test_no_net_is_created_without_a_placed_driver():
    """A driverless net with sinks is the DRT-0305 dangling-net shape (#571)."""
    t = _tcl()
    i_drv_check = t.index("SPARE_TIEOFF_SKIPPED $_sn: tie driver not placed")
    i_net_create = t.index("odb::dbNet_create $_blk $_dnm")
    assert i_drv_check < i_net_create


def test_every_created_net_is_dont_touched():
    """The resizer must skip every tie net, not just the first."""
    t = _tcl()
    assert "foreach _stn [concat $_spare_tie_nets [list spare_tiehi]] {" in t
    assert "$_stnet setDoNotTouch true" in t


def test_consumers_never_see_an_unset_list():
    """PDK with no tie cell -> the block never runs -> the guard must cover it."""
    t_none = P3._build_spare_postfix_tcl(_PLAN, tie_lo_cell=None)
    assert "SPARE_TIEOFF_SKIPPED: no tie-low cell discovered" in t_none
    assert "if {![info exists _spare_tie_nets]} { set _spare_tie_nets {} }" \
        in t_none, "the dont_touch loop would error on an unset variable"


def test_the_count_marker_the_runner_parses_still_matches():
    """`_spare_tieoff_measured_from_log` reads this line; it must not drift."""
    t = _tcl()
    assert "puts \"SPARE_TIEOFF_CONNECTED $_tie_n of $_tie_tot\"" in t
    assert P3._SPARE_TIEOFF_COUNT_RE.search(
        "SPARE_TIEOFF_CONNECTED 20 of 20") is not None


def test_antenna_window_reads_the_same_list():
    """The antenna unprotect window must cover every tie net, not one name."""
    class _Pdk:
        antenna_diode_cell = "DIODE_CELL"
    a = P3._antenna_repair_tcl(_Pdk())
    assert "foreach _astn [concat $_spare_tie_nets [list spare_tiehi]] {" in a
    assert "if {![info exists _spare_tie_nets]} { set _spare_tie_nets {} }" in a
    assert "foreach _astn $_ant_unprot" in a, "restore only what was lifted"
