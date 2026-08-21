#!/usr/bin/env python3
"""A master too WIDE for the tap grid has no legal site, and the flow then
ships a DEF with zero signal routing.

Measured field failure (core utilization 27 %, so not a space problem):

    tapcell -distance D               -> WELLTAP cells FIXED every 50 sites
    longest free-site run, all rows   -> 50 sites (measured, 64/64 rows)
    widest buffer master in the pool  -> 62 sites   <-- no legal site, anywhere
    [ERROR DPL-0701] NegotiationLegalizer did not fully converge.
    POST_HOLD_LEGALIZE_FAILED
    [ERROR DRT-0073] No access point ... (18 distinct instances)
    routed.def: 563 signal nets, 2 "+ ROUTED" (both power) -> NO interconnect

DRC, LVS and EM were then all measured on a design with no signal routing at
all.  Utilization is irrelevant: the taps are FIXED, so a master wider than
the inter-tap run has no legal site at 27 % or at 90 %.

Two things are under test here, and BOTH directions of each:

  * the width cap must EXCLUDE a master that cannot be placed, and must NOT
    exclude one that can -- otherwise the cap could "pass" by forbidding
    everything, which would be a different way to lose the design;
  * the legalize ladder must REACH its diamond-legalizer rung when every
    earlier rung fails, and must NOT reach it when the default window works.

Every assertion is against a value the program RETURNED or PRINTED.  No test
in this file inspects the emitter's source text.  The Tcl is executed under a
real `tclsh` against a stubbed odb, so the stubs are synthetic and carry no
design, PDK, library or cell name.
"""
from __future__ import annotations

import inspect
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

_TCLSH = shutil.which("tclsh")
_needs_tcl = pytest.mark.skipif(_TCLSH is None, reason="tclsh not installed")

# ── a minimal synthetic odb / OpenSTA stub ──────────────────────────────────
# One row spanning 0..1000 dbu with a site width of 10 dbu (=> 100 sites).
# Fixed obstructions and masters are declared per-test.  No PDK is involved.
_STUB = r"""
proc _mkbb {name xmin xmax ymin} {
  proc $name {args} [format {
    switch -- [lindex $args 0] {
      xMin { return %d }
      xMax { return %d }
      yMin { return %d }
      yMax { return %d }
    }
    error "bbox: $args"
  } $xmin $xmax $ymin $ymin]
}
_mkbb ROWBB 0 1000 0
proc SITE {args} {
  if {[lindex $args 0] eq "getWidth"} { return 10 }
  error "SITE $args"
}
proc ROW0 {args} {
  switch -- [lindex $args 0] {
    getSite { return SITE }
    getBBox { return ROWBB }
  }
  error "ROW0 $args"
}
set ::INSTS {}
set ::MASTERS {}
set ::DONTUSE {}
proc mkmaster {name width {core 1}} {
  proc $name {args} [format {
    switch -- [lindex $args 0] {
      getName { return %s }
      getWidth { return %d }
      isCore { return %d }
    }
    error "master: $args"
  } $name $width $core]
  lappend ::MASTERS $name
}
proc mkinst {name status xmin xmax ymin master} {
  _mkbb ${name}_bb $xmin $xmax $ymin
  proc $name {args} [format {
    switch -- [lindex $args 0] {
      getPlacementStatus { return %s }
      getBBox { return %s_bb }
      getMaster { return %s }
      getName { return %s }
    }
    error "inst: $args"
  } $status $name $master $name]
  lappend ::INSTS $name
}
proc BLK {args} {
  switch -- [lindex $args 0] {
    getRows { return [list ROW0] }
    getInsts { return $::INSTS }
  }
  error "BLK $args"
}
proc LIB {args} {
  if {[lindex $args 0] eq "getMasters"} { return $::MASTERS }
  error "LIB $args"
}
proc DB {args} {
  if {[lindex $args 0] eq "getLibs"} { return [list LIB] }
  error "DB $args"
}
namespace eval ord {
  proc get_db_block {} { return BLK }
  proc get_db {} { return DB }
}
# OpenSTA-side stubs.  A "lib cell" is just the master name; a master whose
# name starts with "drv" is a buffer (synthetic naming, no library involved).
proc get_lib_cells {args} {
  set pat [lindex $args end]
  set out {}
  foreach m $::MASTERS {
    if {[string match $pat $m]} { lappend out $m }
  }
  return $out
}
proc get_name {c} { return $c }
proc get_property {c prop} {
  switch -- $prop {
    is_buffer { return [expr {[string match "drv*" $c] ? 1 : 0}] }
    dont_use  { return [expr {[lsearch -exact $::DONTUSE $c] >= 0 ? 1 : 0}] }
  }
  error "get_property $prop"
}
proc set_dont_use {cells} { foreach c $cells { lappend ::DONTUSE $c } }
"""

# Obstructions 20 dbu wide every 200 dbu inside a 0..1000 row, so the longest
# contiguous free run is 200 dbu = 20 sites.  drv_narrow fits; the others do not.
_OBSTRUCTED = """
mkmaster OBST 20
mkmaster drv_narrow 100
mkmaster drv_wide 300
mkmaster cell_wide 400
for {set x 200} {$x < 1000} {incr x 200} {
  mkinst obst$x FIXED $x [expr {$x+20}] 0 OBST
}
"""

# Same library, but NOTHING is fixed — every master fits.
_UNOBSTRUCTED = """
mkmaster drv_narrow 100
mkmaster drv_wide 300
mkmaster cell_wide 400
"""


def _run_cap(setup: str, tmp_path) -> str:
    """Execute the emitted cap block and return everything it printed."""
    f = tmp_path / "cap.tcl"
    f.write_text(_STUB + setup + p3._build_unplaceable_master_cap_tcl()
                 + '\nputs "DONTUSE: $::DONTUSE"\n')
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def _excluded(out: str) -> list:
    """The masters the block actually forbade, as the block itself reports."""
    line = [l for l in out.splitlines() if l.startswith("DONTUSE:")][-1]
    return line.split(":", 1)[1].split()


# ── direction 1: the unplaceable master IS excluded ─────────────────────────

@_needs_tcl
def test_a_master_wider_than_the_free_run_is_excluded(tmp_path):
    out = _run_cap(_OBSTRUCTED, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 200 dbu = 20 site(s)" in out, out
    assert sorted(_excluded(out)) == ["cell_wide", "drv_wide"], out


# ── direction 2: the OPPOSITE verdict is still reachable ────────────────────
# Without these, a cap that forbade every master would pass direction 1 and
# still destroy the design.

@_needs_tcl
def test_a_master_that_fits_is_left_usable(tmp_path):
    """Same run, same library: the narrow master must survive."""
    out = _run_cap(_OBSTRUCTED, tmp_path)
    assert "drv_narrow" not in _excluded(out), out


@_needs_tcl
def test_the_same_library_is_untouched_when_nothing_obstructs_it(tmp_path):
    """Identical masters, obstructions removed -> the cap must exclude NOTHING.
    This is the opposite verdict for the identical cell library, so the
    exclusion provably tracks the floorplan and not the master list."""
    out = _run_cap(_UNOBSTRUCTED, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 1000 dbu" in out, out
    assert "UNPLACEABLE_MASTERS_NONE" in out, out
    assert _excluded(out) == [], out


@_needs_tcl
def test_the_buffer_pool_is_never_emptied(tmp_path):
    """GUARD: if EVERY buffer is too wide, forbidding them all leaves the
    resizer nothing to insert.  Report and leave them enabled instead."""
    setup = """
mkmaster OBST 20
mkmaster drv_wide 300
mkmaster drv_wider 400
for {set x 200} {$x < 1000} {incr x 200} {
  mkinst obst$x FIXED $x [expr {$x+20}] 0 OBST
}
"""
    out = _run_cap(setup, tmp_path)
    assert "UNPLACEABLE_MASTERS_SKIPPED" in out, out
    assert _excluded(out) == [], out


@_needs_tcl
def test_a_movable_instance_does_not_bound_the_free_run(tmp_path):
    """Only FIXED obstructions bound the run — a movable cell can be pushed
    aside by the legalizer, so counting it would over-exclude."""
    setup = _UNOBSTRUCTED + "mkinst u_mov PLACED 400 500 0 cell_wide\n"
    out = _run_cap(setup, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 1000 dbu" in out, out
    assert _excluded(out) == [], out


@_needs_tcl
def test_an_already_instantiated_unplaceable_master_is_named(tmp_path):
    """`set_dont_use` cannot undo a master synthesis already used — the flow
    must say so rather than report a clean cap."""
    setup = _OBSTRUCTED + "mkinst u_big PLACED 0 400 0 cell_wide\n"
    out = _run_cap(setup, tmp_path)
    assert "UNPLACEABLE_INSTANCES_PRESENT: 1 instance(s)" in out, out
    assert "u_big" in out


@_needs_tcl
def test_a_broken_odb_degrades_to_the_prior_behaviour(tmp_path):
    """Any error must become a NONFATAL note, never a dead PnR."""
    f = tmp_path / "broken.tcl"
    f.write_text("namespace eval ord { proc get_db_block {} "
                 "{ error \"no block linked\" } }\n"
                 + p3._build_unplaceable_master_cap_tcl()
                 + '\nputs "SURVIVED"\n')
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert "UNPLACEABLE_MASTERS_NONFATAL" in r.stdout
    assert "SURVIVED" in r.stdout


@_needs_tcl
def test_negative_control_the_recovery_is_not_the_stubs(tmp_path):
    """Run the SAME stub and the SAME floorplan with the emitted block
    removed: nothing is excluded and no bound is reported.  Whatever the
    tests above measure therefore comes from the emitted block."""
    f = tmp_path / "prefix.tcl"
    f.write_text(_STUB + _OBSTRUCTED + '\nputs "DONTUSE: $::DONTUSE"\n')
    out = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                         timeout=60).stdout
    assert "PLACEABLE_WIDTH_BOUND" not in out
    assert _excluded(out) == []


# ── the ordering contract, asserted on returned values ──────────────────────

class _FakePdk:
    """Synthetic PDK record — the two attributes the tapcell emitter reads."""
    tapcell_master = "SYNTH_TAP"
    tapcell_distance_um = 1.0


def test_the_cap_is_measured_after_the_taps_are_inserted():
    """Measuring before `tapcell` would measure an empty die and exclude
    nothing.  Asserted on the composed block this flow actually emits."""
    block = p3._build_tapcell_and_placeability_tcl(_FakePdk())
    assert block.index("tapcell ") < block.index("PLACEABLE_WIDTH_BOUND")


def test_the_cap_survives_a_pdk_with_no_tapcell_master():
    """A PDK that configures no tap master must still get the cap (its bound
    is then simply the whole row) rather than losing the block entirely."""
    class _NoTap:
        tapcell_master = ""
        tapcell_distance_um = 1.0
    block = p3._build_tapcell_and_placeability_tcl(_NoTap())
    assert "TAPCELL_SKIPPED" in block
    assert "PLACEABLE_WIDTH_BOUND" in block


def _emitted_pnr_tcl(**over) -> str:
    sig = inspect.signature(p3._build_pnr_tcl_text)
    kw = {n: (0 if "int" in str(pm.annotation)
              else (0.5 if "float" in str(pm.annotation) else "X"))
          for n, pm in sig.parameters.items() if pm.default is inspect._empty}
    kw.update(over)
    return p3._build_pnr_tcl_text(**kw)


def test_the_cap_is_in_force_before_any_repeater_master_is_chosen():
    """A cap applied after the fact changes nothing.  The slot the composed
    block is emitted into must precede every command that inserts a buffer."""
    tcl = _emitted_pnr_tcl(tapcell_block="TAPCELL_AND_CAP_SLOT")
    slot = tcl.index("TAPCELL_AND_CAP_SLOT")
    # (`repair_timing` is deliberately not probed positionally: the token also
    #  occurs in an earlier explanatory comment, so its index is meaningless.)
    for later in ("buffer_ports", "repair_design", "clock_tree_synthesis"):
        assert slot < tcl.index(later), f"{later} precedes the width cap"


def test_the_cap_carries_no_design_pdk_or_cell_literal():
    """chip-AGNOSTIC: every number must come from the live floorplan.  Asserted
    on the emitted Tcl, i.e. the value the program returns."""
    import re
    body = "\n".join(l for l in p3._build_unplaceable_master_cap_tcl()
                     .splitlines() if not l.strip().startswith("#"))
    assert not re.search(r"[A-Za-z]{2,}_fd_sc_|__[a-z]+_\d+\b", body)
    # no hard-coded geometry: the only integers may be small loop/guard values
    nums = {int(n) for n in re.findall(r"\b\d{3,}\b", body)}
    assert nums == set(), f"hard-coded geometry in the emitted Tcl: {nums}"


# ── the diamond-legalizer rung, both directions ─────────────────────────────

_LADDER_STUB = r"""
set ::calls {}
set ::legal 0
proc detailed_placement args {
    lappend ::calls $args
    if {%s} {
        error "DPL-0701 NegotiationLegalizer did not fully converge."
    }
    set ::legal 1
}
proc check_placement {} { if {!$::legal} { error "DPL-0033" } }
namespace eval ord { proc get_die_area {} { return {0 0 100 100} } }
"""


def _run_ladder(fail_cond: str, tmp_path) -> str:
    f = tmp_path / "lad.tcl"
    f.write_text((_LADDER_STUB % fail_cond)
                 + p3._build_escalating_legalize_tcl("T", "_t")
                 + '\nputs "NCALLS: [llength $::calls]"\n')
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@_needs_tcl
def test_the_ladder_reaches_the_diamond_rung_when_every_other_rung_fails(
        tmp_path):
    """The default legalizer fails at every window; the diamond one succeeds."""
    out = _run_ladder('[lsearch -exact $args -use_diamond_legalizer] < 0',
                      tmp_path)
    assert "T_LEGALIZE_OK disp=diamond" in out, out
    assert "T_LEGALIZE_FAILED" not in out, out


@_needs_tcl
def test_the_diamond_rung_is_not_entered_when_the_default_window_works(
        tmp_path):
    """OPPOSITE VERDICT: the common case must still cost exactly one call, so
    the rung cannot be silently changing every design's placement."""
    out = _run_ladder("0", tmp_path)
    assert "T_LEGALIZE_OK disp=default" in out, out
    assert "diamond" not in out, out
    assert "NCALLS: 1" in out, out


@_needs_tcl
def test_an_unlegalizable_placement_still_fails_loudly(tmp_path):
    """OPPOSITE VERDICT: adding a rung must not turn a genuine failure into a
    pass.  When the diamond rung fails too, the honest FAILED must survive."""
    out = _run_ladder("1", tmp_path)
    assert "T_LEGALIZE_FAILED" in out, out
    assert "T_LEGALIZE_OK" not in out, out
