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

Three things are under test here, and BOTH directions of each:

  * the width cap must EXCLUDE a master that cannot be placed, and must NOT
    exclude one that can -- otherwise the cap could "pass" by forbidding
    everything, which would be a different way to lose the design;
  * the bound must be measured over EVERY row the design declares, including a
    row that holds no fixed instance (#966: such a row is a full-width free run
    and the first version of the block never visited it, so it forbade masters
    that were placeable) -- and a free row must lend the maximum only its OWN
    extent, never a neighbour's;
  * the legalize ladder must REACH its diamond-legalizer rung when every
    earlier rung fails, and must NOT reach it when the default window works.

Row counts are generated, not fixed: `_rows()` re-declares the block with
whatever rows a test needs, so no test here is tied to a one-row floorplan --
which is exactly how the #966 defect survived the first suite.

Every assertion is against a value the program RETURNED or PRINTED.  No test
in this file inspects the emitter's source text.  The Tcl is executed under a
real `tclsh` against a stubbed odb, so the stubs are synthetic and carry no
design, PDK, library or cell name.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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

# The same library plus the obstruction master, for the generated floorplans.
_LIB = "mkmaster OBST 20\n" + _UNOBSTRUCTED








def _excluded(out: str) -> list:
    """The masters the block actually forbade, as the block itself reports."""
    line = [l for l in out.splitlines() if l.startswith("DONTUSE:")][-1]
    return line.split(":", 1)[1].split()


# ── direction 1: the unplaceable master IS excluded ─────────────────────────



# ── direction 2: the OPPOSITE verdict is still reachable ────────────────────
# Without these, a cap that forbade every master would pass direction 1 and
# still destroy the design.











# ── #966: the bound is measured over the ROWS, not the fixed-instance buckets ─













@_needs_tcl
def test_negative_control_the_recovery_is_not_the_stubs(tmp_path):
    """Run the SAME stub and the SAME floorplan with the emitted block
    removed: nothing is excluded and no bound is reported.  Whatever the
    tests above measure therefore comes from the emitted block."""
    f = tmp_path / "prefix.tcl"
    f.write_text(_STUB + _OBSTRUCTED + '\nputs "DONTUSE: $::DONTUSE"\n')
    out = _pr.run([_TCLSH, str(f)], capture_output=True, text=True).stdout
    assert "PLACEABLE_WIDTH_BOUND" not in out
    assert _excluded(out) == []


# ── the ordering contract, asserted on returned values ──────────────────────













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










# ── the bound was PRINTED AND NEVER CONSULTED ───────────────────────────────
# `PLACEABLE_WIDTH_BOUND` is measured from the live tap grid, and a `git grep`
# used to find it in the emitter and in this file and NOWHERE ELSE. Meanwhile
# `clk_buf_root` comes from the PDK registry (or "the last clkbuf in the
# Liberty", i.e. the widest) and is fixed before a floorplan exists. Nothing
# joined the two, so the flow could hand `clock_tree_synthesis -root_buf` a
# master its own cap had just measured to sit exactly at the placeability
# limit. Measured on three designs of one open PDK: all three printed
# `PLACEABLE_WIDTH_BOUND: 56000 dbu = 50 site(s)` and all three named a 50-site
# master as -root_buf. On the small one CTS used it ONCE and the design
# legalized; on the large one CTS used it 2 055 times and the post-hold
# legalizer was left with ~2 344 illegal cells.
#
# These are REPORT-ONLY. Nothing new is excluded: the strict `>` above is
# correct and stays, pinned by test_a_master_exactly_at_the_bound_stays_legal.
