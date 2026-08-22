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

# The same library plus the obstruction master, for the generated floorplans.
_LIB = "mkmaster OBST 20\n" + _UNOBSTRUCTED


def _rows(*spans: tuple) -> str:
    """Re-declare the stub block with one row per `(xMin, xMax, yMin)` span.

    The shipped stub hard-codes a SINGLE row, which is how the #966 defect
    (rows with no fixed instance are never measured) survived a green suite.
    Row count and row extents are parameters here so that a test states the
    floorplan it means and nothing is tied to "one row"."""
    out, names = [], []
    for i, (x0, x1, y) in enumerate(spans):
        row, bb = f"ROW{i}", f"ROWBB{i}"
        names.append(row)
        out.append(f"_mkbb {bb} {x0} {x1} {y}\n"
                   f"proc {row} {{args}} {{\n"
                   "  switch -- [lindex $args 0] {\n"
                   "    getSite { return SITE }\n"
                   f"    getBBox {{ return {bb} }}\n"
                   "  }\n"
                   f'  error "{row} $args"\n'
                   "}\n")
    out.append("proc BLK {args} {\n"
               "  switch -- [lindex $args 0] {\n"
               f"    getRows {{ return [list {' '.join(names)}] }}\n"
               "    getInsts { return $::INSTS }\n"
               "  }\n"
               '  error "BLK $args"\n'
               "}\n")
    return "".join(out)


def _obstruct(y: int, pitch: int = 200, width: int = 20,
              span: int = 1000) -> str:
    """A FIXED obstruction `width` dbu wide every `pitch` dbu in the row at
    `y`, i.e. the shape `tapcell -distance D` leaves behind."""
    return (f"for {{set x {pitch}}} {{$x < {span}}} {{incr x {pitch}}} {{\n"
            f"  mkinst obst{y}_$x FIXED $x [expr {{$x+{width}}}] {y} OBST\n"
            "}\n")


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


# ── #966: the bound is measured over the ROWS, not the fixed-instance buckets ─

@_needs_tcl
def test_a_row_with_no_fixed_instance_is_measured_too(tmp_path):
    """THE #966 DEFECT.  Two rows of the same extent; the first carries an
    obstruction every 200 dbu, the second carries nothing.  The longest free
    run on this floorplan is the WHOLE second row, and both wide masters fit in
    it with 600 dbu to spare.  Scanning the fixed instances' yMin buckets never
    visits the empty row, reports 200 dbu, and `set_dont_use`s two masters that
    are placeable -- the one outcome the docstring guarantees against."""
    setup = _rows((0, 1000, 0), (0, 1000, 100)) + _LIB + _obstruct(0)
    out = _run_cap(setup, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 1000 dbu = 100 site(s)" in out, out
    assert "rows=2" in out, out
    assert "UNPLACEABLE_MASTERS_NONE" in out, out
    assert _excluded(out) == [], out


@_needs_tcl
def test_a_free_row_is_credited_only_with_its_own_extent(tmp_path):
    """OPPOSITE VERDICT for the same two-row shape: the free row is SHORT
    (0..150), so it cannot beat the obstructed row's 200 dbu run and the wide
    masters stay forbidden.  Without this, "measure every row" could be bought
    by crediting every row with the union extent of all rows -- which would
    hand a short row a free run it does not have."""
    setup = _rows((0, 1000, 0), (0, 150, 100)) + _LIB + _obstruct(0)
    out = _run_cap(setup, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 200 dbu = 20 site(s)" in out, out
    assert sorted(_excluded(out)) == ["cell_wide", "drv_wide"], out


@_needs_tcl
def test_the_converged_shape_with_a_tap_in_every_row_is_unchanged(tmp_path):
    """PAIRED GUARD.  The floorplan the cap was first measured against had a
    FIXED tap in EVERY row -- the case where bucket iteration and row iteration
    agree by construction.  Four rows, same pitch: the answer must be the same
    200 dbu = 20 sites, with the narrow master still usable.  The #966 fix may
    not be bought by changing the verdict on the case that already worked.

    Deliberately asserts nothing about the REPORT text (the bound line gained a
    `rows=` field), only about the two things that must not move: the measured
    bound and the set of masters excluded.  So this test passes unchanged
    against the pre-#966 program as well as against the fixed one."""
    spans = [(0, 1000, y) for y in (0, 100, 200, 300)]
    setup = _rows(*spans) + _LIB + "".join(_obstruct(y) for _, _, y in spans)
    out = _run_cap(setup, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 200 dbu = 20 site(s)" in out, out
    assert sorted(_excluded(out)) == ["cell_wide", "drv_wide"], out


@_needs_tcl
def test_a_master_exactly_at_the_bound_stays_legal(tmp_path):
    """The comparison is STRICT, and both sides of the boundary are pinned: a
    master exactly as wide as the longest free run has a legal site and must
    stay usable, one dbu wider does not and must go.  On the floorplan #951 was
    measured against the surviving masters sat EXACTLY at the bound, so a
    `>` -> `>=` slip would have forbidden every one of them."""
    setup = (_OBSTRUCTED
             + "mkmaster cell_at_bound 200\nmkmaster cell_over_bound 201\n")
    out = _run_cap(setup, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 200 dbu" in out, out
    excluded = _excluded(out)
    assert "cell_at_bound" not in excluded, out
    assert "cell_over_bound" in excluded, out


@_needs_tcl
def test_a_floorplan_with_no_free_space_excludes_nothing(tmp_path):
    """DEGENERATE-MEASUREMENT FLOOR: one obstruction covering the only row
    leaves a zero-dbu free run, so EVERY master is "too wide".  Forbidding the
    whole library cannot give the floorplan free space; report the measurement
    and change nothing.  (The buffer-pool floor happens to catch this shape too
    -- it is a floor on the consequence, and it says nothing about whether the
    bound was measured correctly.)"""
    setup = _LIB + "mkinst obst_all FIXED 0 1000 0 OBST\n"
    out = _run_cap(setup, tmp_path)
    assert "PLACEABLE_WIDTH_BOUND: 0 dbu" in out, out
    assert "no row has free space" in out, out
    assert _excluded(out) == [], out


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

def _run_cap_named(setup: str, tmp_path, cts) -> str:
    f = tmp_path / "cap_named.tcl"
    f.write_text(_STUB + setup
                 + p3._build_unplaceable_master_cap_tcl(cts)
                 + '\nputs "DONTUSE: $::DONTUSE"\n')
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


@_needs_tcl
def test_a_master_exactly_at_the_bound_is_named_even_though_it_stays_legal(
        tmp_path):
    """`one fits` is not `many fit`. The master stays usable -- that part is
    deliberate and unchanged -- but it is now SAID, at floorplan time."""
    setup = _OBSTRUCTED + "mkmaster cell_at_bound 200\n"
    out = _run_cap(setup, tmp_path)
    assert "MASTERS_AT_PLACEABILITY_BOUND:" in out, out
    assert "cell_at_bound" in out.split("MASTERS_AT_PLACEABILITY_BOUND:")[1]
    assert "20 site(s)" in out.split("MASTERS_AT_PLACEABILITY_BOUND:")[1]
    # and it is still NOT excluded -- the strict bound is untouched
    assert "cell_at_bound" not in _excluded(out), out


@_needs_tcl
def test_nothing_at_the_bound_means_no_such_line(tmp_path):
    """NEGATIVE CONTROL: a library with no master exactly at the run must not
    produce the line. Without this, the assertion above passes on a checker
    that prints unconditionally."""
    out = _run_cap(_OBSTRUCTED, tmp_path)   # 100 / 300 / 400 against a 200 run
    assert "MASTERS_AT_PLACEABILITY_BOUND:" not in out, out


@_needs_tcl
def test_a_cts_master_at_the_bound_is_named_by_name(tmp_path):
    """The load-bearing one: the master the flow will hand to CTS is checked
    against the bound the flow just measured."""
    setup = _OBSTRUCTED + "mkmaster clkroot 200\n"
    out = _run_cap_named(setup, tmp_path, ("drv_narrow", "clkroot"))
    assert "CTS_MASTER_AT_PLACEABILITY_BOUND: clkroot is 20 site(s)" in out, out
    assert "free-site run of 20 site(s)" in out, out
    assert "clkroot" not in _excluded(out), out


@_needs_tcl
def test_a_cts_master_that_fits_is_silent(tmp_path):
    """NEGATIVE CONTROL for the same check: the narrow buffer must NOT be
    named, or the line means nothing."""
    out = _run_cap_named(_OBSTRUCTED, tmp_path, ("drv_narrow",))
    assert "CTS_MASTER_AT_PLACEABILITY_BOUND" not in out, out


@_needs_tcl
def test_a_cts_master_wider_than_the_bound_is_named_too(tmp_path):
    """At-or-above, not only at: a master already excluded by the cap is still
    worth naming, because -root_buf names it explicitly and set_dont_use does
    not stop an explicit argument."""
    out = _run_cap_named(_OBSTRUCTED, tmp_path, ("drv_wide",))
    assert "CTS_MASTER_AT_PLACEABILITY_BOUND: drv_wide is 30 site(s)" in out, out


@_needs_tcl
def test_the_named_check_is_inert_when_the_caller_supplies_nothing(tmp_path):
    """A caller that does not know its CTS masters is unchanged -- the emitter
    must add no Tcl at all."""
    assert p3._cts_master_bound_check_tcl() == ""
    assert p3._cts_master_bound_check_tcl(()) == ""
    assert p3._cts_master_bound_check_tcl((None, "")) == ""
    out = _run_cap(_OBSTRUCTED + "mkmaster clkroot 200\n", tmp_path)
    assert "CTS_MASTER_AT_PLACEABILITY_BOUND" not in out, out


def test_the_call_site_supplies_the_resolved_cts_masters():
    """The composer must PASS THEM THROUGH -- a check wired to nothing is the
    defect this file exists to close, one layer up."""
    import inspect
    src = inspect.getsource(p3._build_tapcell_and_placeability_tcl)
    assert "cts_masters" in src, src
    whole = inspect.getsource(p3)
    assert "_build_tapcell_and_placeability_tcl(\n        pdk, cts_masters=" in whole \
        or "cts_masters=(clk_buf, clk_buf_root)" in whole, \
        "the call site does not supply the resolved masters"
