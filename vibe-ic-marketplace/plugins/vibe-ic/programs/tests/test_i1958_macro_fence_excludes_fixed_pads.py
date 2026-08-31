#!/usr/bin/env python3
"""vibe-ic#1958 (3/3) — the macro fence included the pad ring's FIXED pads.

`rtl_macro_placer` was emitted BARE, so its global fence defaulted to the whole
core.  MPL's rule (OpenROAD `src/mpl/src/clusterEngine.cpp`) is:

    setFloorplanShape():
      tree_->floorplan_shape = block_->getCoreArea().intersect(tree_->global_fence);
    computeModuleMetrics():
      } else if (inst->isFixed() && !inst->getMaster()->isCover()
                 && inst->getBBox()->getBox().overlaps(tree_->floorplan_shape)) {
        logger_->error(MPL, 50, "Found fixed non-macro instance {} inside the "
                                "macro placement area.", ...);

On the chip / pad-ring path the ring's pads are FIXED, not BLOCK, and inside the
core, so every chip-path run with a hard macro hit MPL-0050, the macros stayed
unplaced, and global route congested around them.

The fence is the only one of the four conditions this flow can move, so the
emitted deck now carves the core down to the largest sub-rectangle no such
instance overlaps and passes it as `-fence_*`.

REPRODUCED on OpenROAD 26Q3-1165-g58dbde489f (vibeic-eda:0.2.70): a 400x400 um
die whose rows span it, four FIXED CLASS PAD instances and one CLASS BLOCK
macro.

    bare                -> [ERROR MPL-0050] Found fixed non-macro instance pad_n
                           inside the macro placement area.
    carved fence        -> MACRO_FENCE_CARVED: ... -> fence (20000 60000 380000
                           340000) dbu, and MPL echoes
                           `Floorplan Area: (20.00, 60.00) (380.00, 340.00)`
                           -- which also confirms -fence_* is MICRONS -- then
                           places the macro.
    same die, no pads   -> MACRO_FENCE_UNCHANGED, `Floorplan Area: (0.00, 0.00)
                           (399.74, 399.84)`, i.e. the whole core: a design
                           without a pad ring is untouched.

The Tcl is executed under a real `tclsh` against a synthetic odb stub, in the
shape `test_unplaceable_master_width_cap.py` established.  The stub carries no
design, PDK, library or cell name, and every assertion is against what the
block PRINTED or SET, never against the emitter's source text.
"""
from __future__ import annotations

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

#: A synthetic odb: one core rectangle, a per-test instance list. `mkinst`
#: takes the four numbers MPL's own rule reads -- status, master type, bbox.
_STUB = r"""
proc _mkrect {name x0 y0 x1 y1} {
  proc $name {args} [format {
    switch -- [lindex $args 0] {
      xMin { return %d }
      yMin { return %d }
      xMax { return %d }
      yMax { return %d }
    }
    error "rect: $args"
  } $x0 $y0 $x1 $y1]
}
set ::INSTS {}
proc mkinst {name status type x0 y0 x1 y1} {
  _mkrect ${name}_bb $x0 $y0 $x1 $y1
  proc ${name}_m {args} [format {
    if {[lindex $args 0] eq "getType"} { return %s }
    error "master: $args"
  } $type]
  proc $name {args} [format {
    switch -- [lindex $args 0] {
      getName { return %s }
      getPlacementStatus { return %s }
      getMaster { return %s_m }
      getBBox { return %s_bb }
    }
    error "inst: $args"
  } $name $status $name $name]
  lappend ::INSTS $name
}
proc BLK {args} {
  switch -- [lindex $args 0] {
    getCoreArea { return CORE }
    getInsts { return $::INSTS }
  }
  error "BLK $args"
}
proc TECH {args} {
  if {[lindex $args 0] eq "getDbUnitsPerMicron"} { return 1000 }
  error "TECH $args"
}
namespace eval ord {
  proc get_db_block {} { return BLK }
  proc get_db_tech {} { return TECH }
}
"""

_VAR = p3._I1958_MACRO_FENCE_VAR
#: a 400x400 um core in dbu.
_CORE = "_mkrect CORE 0 0 400000 400000\n"
#: a ring of FIXED PAD instances 20 um deep on each side, i.e. the shape
#: `pad_ring_gen` leaves behind.
_PAD_RING = (
    "mkinst pw FIXED PAD      0      0  20000 400000\n"
    "mkinst pe FIXED PAD 380000      0 400000 400000\n"
    "mkinst ps FIXED PAD      0      0 400000  20000\n"
    "mkinst pn FIXED PAD      0 380000 400000 400000\n")


def _run(setup: str, core: str = _CORE) -> str:
    """Execute the fence block and report everything it printed plus the fence
    it produced."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write(_STUB + core + setup + p3._i1958_macro_fence_tcl()
                 + f'\nputs "FENCE: ${_VAR}"\n')
        path = fh.name
    try:
        r = subprocess.run([_TCLSH, path], capture_output=True, text=True,
                           timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout
    finally:
        Path(path).unlink(missing_ok=True)


def _fence(out: str) -> dict:
    line = [ln for ln in out.splitlines() if ln.startswith("FENCE: ")][0]
    toks = line[len("FENCE: "):].split()
    return dict(zip(toks[0::2], (float(v) for v in toks[1::2])))


# ── the defect ──────────────────────────────────────────────────────────────
@_needs_tcl
def test_a_pad_ring_carves_the_fence_off_every_pad():
    """THE defect.  Pre-fix no fence was passed at all, so the placement area
    was the core and all four pads were inside it."""
    out = _run(_PAD_RING)
    assert "MACRO_FENCE_CARVED" in out, out
    f = _fence(out)
    assert f == {"-fence_lx": 20.0, "-fence_ly": 20.0,
                 "-fence_ux": 380.0, "-fence_uy": 380.0}, out


@_needs_tcl
def test_no_pad_bbox_overlaps_the_carved_fence():
    """The PROPERTY, not the numbers: MPL errors on OVERLAP, so what has to
    hold is that the carved rectangle intersects no offender.  Asserted over an
    asymmetric ring so a carve that happened to be symmetric cannot pass by
    coincidence."""
    pads = [("pw", 0, 0, 15000, 400000), ("pe", 355000, 0, 400000, 400000),
            ("ps", 0, 0, 400000, 47000), ("pn", 0, 362000, 400000, 400000)]
    setup = "".join(f"mkinst {n} FIXED PAD {a} {b} {c} {d}\n"
                    for n, a, b, c, d in pads)
    f = _fence(_run(setup))
    lx, ly = f["-fence_lx"] * 1000, f["-fence_ly"] * 1000
    ux, uy = f["-fence_ux"] * 1000, f["-fence_uy"] * 1000
    assert ux > lx and uy > ly
    for n, a, b, c, d in pads:
        assert not (c > lx and a < ux and d > ly and b < uy), \
            f"{n} still overlaps the fence"


@_needs_tcl
def test_the_carve_keeps_the_largest_rectangle_it_can():
    """A fence that cleared the pads by shrinking to nothing useful would pass
    the overlap test and leave the macros nowhere to go, so the area kept is
    asserted too: a 20 um ring must cost exactly the ring."""
    f = _fence(_run(_PAD_RING))
    area = (f["-fence_ux"] - f["-fence_lx"]) * (f["-fence_uy"] - f["-fence_ly"])
    assert area == pytest.approx(360.0 * 360.0)


# ── the negative controls ───────────────────────────────────────────────────
@_needs_tcl
def test_a_die_with_no_fixed_instance_gets_no_fence_at_all():
    """INERT.  An empty list expands to nothing, so `rtl_macro_placer` is
    invoked with exactly the arguments it carried before this block existed --
    a design without a pad ring cannot be changed by the fix."""
    out = _run("mkinst c0 PLACED CORE 100000 100000 110000 110000\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_UNCHANGED" in out


@_needs_tcl
def test_a_fixed_MACRO_does_not_shrink_the_fence():
    """MPL's condition is `isFixed() && !isBlock()`.  A fixed macro is a macro
    -- excluding it would fence the placer off the very thing it is placing."""
    out = _run("mkinst m0 FIXED BLOCK 100000 100000 200000 200000\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_UNCHANGED" in out


@_needs_tcl
def test_a_COVER_master_does_not_shrink_the_fence():
    """MPL exempts COVER masters itself (`!inst->getMaster()->isCover()`), so
    carving around one would give away die area for nothing."""
    out = _run("mkinst b0 FIXED COVER_BUMP 0 0 40000 40000\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_UNCHANGED" in out


@_needs_tcl
def test_an_unfixed_instance_does_not_shrink_the_fence():
    """A PLACED (movable) instance is not an offender: MPL will move it."""
    out = _run("mkinst c0 PLACED CORE 0 0 40000 400000\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_UNCHANGED" in out


@_needs_tcl
def test_a_fixed_instance_outside_the_core_does_not_shrink_the_fence():
    """The third condition is OVERLAP.  Pads that sit in the die margin outside
    the core are already outside the placement area."""
    out = _run("mkinst pw FIXED PAD -30000 0 -10000 400000\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_UNCHANGED" in out
    assert "none of them overlapping" in out


@_needs_tcl
def test_an_uncarvable_die_passes_no_fence_and_says_why():
    """DEGRADE LOUDLY.  An offender spanning the core in both axes cannot be
    cut away.  Passing a degenerate fence would trade MPL's named MPL-0050 for
    an unplaced macro nobody looks for (and MPL-0068 for a fence outside the
    core is no better), so no fence is passed and the reason is printed."""
    out = _run("mkinst big FIXED PAD 0 0 400000 400000\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_UNAVAILABLE" in out
    assert "big" in out


@_needs_tcl
def test_an_odb_error_leaves_the_call_exactly_as_it_was():
    """FAIL-SAFE.  The macro placer must still run if the measurement cannot."""
    out = _run("proc BLK {args} { error \"synthetic odb failure\" }\n")
    assert _fence(out) == {}
    assert "MACRO_FENCE_NONFATAL" in out
    assert "synthetic odb failure" in out


@_needs_tcl
def test_the_carve_terminates_on_a_die_full_of_fixed_instances():
    """The loop is bounded by the offender count; a die that is mostly pads
    must still finish rather than spin."""
    setup = "".join(
        f"mkinst p{i} FIXED PAD {i * 8000} 0 {i * 8000 + 4000} 400000\n"
        for i in range(40))
    out = _run(setup)
    assert ("MACRO_FENCE_CARVED" in out or "MACRO_FENCE_UNAVAILABLE" in out), out


# ── the wiring ──────────────────────────────────────────────────────────────
_MP_BEGIN = "    macro_place_block = (\n"
_MP_END = 'f"write_def {out_dir_c}/macro_placed.def\\n")'
_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")


def _macro_place_block() -> str:
    """The REAL `macro_place_block` the runner emits, extracted from the one
    place that builds it.  Anchored on source markers this asserts still exist,
    so a refactor that moves the block fails here instead of silently leaving
    these tests measuring a hand-built copy."""
    import textwrap
    assert _SRC.count(_MP_BEGIN) == 1, "macro_place_block moved; test is blind"
    assert _SRC.count(_MP_END) == 1, "the end anchor moved; test is blind"
    body = textwrap.dedent(
        _SRC[_SRC.index(_MP_BEGIN):_SRC.index(_MP_END) + len(_MP_END)])
    ns = dict(vars(p3))
    ns["out_dir_c"] = "/work/pnr"
    exec(body, ns)              # noqa: S102 - executing the block under test
    return ns["macro_place_block"]


@_needs_tcl
def test_the_real_emitted_block_hands_the_carved_fence_to_the_macro_placer():
    """The composition, executed rather than read: run the deck the runner
    actually emits against the odb stub, with `rtl_macro_placer` and
    `write_def` stubbed to record what they were called with."""
    import tempfile
    recorder = ('proc rtl_macro_placer {args} { puts "CALLED: $args" }\n'
                'proc write_def {args} { }\n')
    results = {}
    for label, insts in (("ring", _PAD_RING),
                         ("no_ring",
                          "mkinst c0 PLACED CORE 1000 1000 2000 2000\n")):
        with tempfile.NamedTemporaryFile("w", suffix=".tcl",
                                         delete=False) as fh:
            fh.write(_STUB + _CORE + recorder + insts + _macro_place_block())
            path = fh.name
        try:
            r = subprocess.run([_TCLSH, path], capture_output=True, text=True,
                               timeout=120)
            assert r.returncode == 0, r.stdout + r.stderr
            called = [ln for ln in r.stdout.splitlines()
                      if ln.startswith("CALLED: ")]
            assert len(called) == 1, r.stdout
            results[label] = called[0][len("CALLED: "):].split()
        finally:
            Path(path).unlink(missing_ok=True)

    # a pad ring -> the placer is fenced off it
    assert results["ring"] == [
        "-halo_width", "20", "-halo_height", "20",
        "-fence_lx", "20.0", "-fence_ly", "20.0",
        "-fence_ux", "380.0", "-fence_uy", "380.0"], results["ring"]
    # no pad ring -> byte-for-byte the arguments the pre-fix deck passed
    assert results["no_ring"] == ["-halo_width", "20", "-halo_height", "20"]


def test_the_fence_block_names_no_pdk_or_design_literal():
    """chip-AGNOSTIC.  The block may only read odb: core rectangle, placement
    status, master type, bounding boxes."""
    tcl = p3._i1958_macro_fence_tcl().lower()
    for literal in ("sky130", "gf180", "nangate", "asap7", "sg13", "ihp",
                    "pad_", "vpwr", "vgnd", "met1", "unithd"):
        assert literal not in tcl, literal


@_needs_tcl
def test_the_emitted_pnr_tcl_still_parses():
    """A brace-unbalanced fence block would break the whole deck, not just the
    macro placement."""
    import tempfile
    body = (p3._i1958_macro_fence_tcl()
            + "if {[catch {rtl_macro_placer -halo_width 20 -halo_height 20 "
            + "{*}$" + _VAR + "} e]} { puts \"NONFATAL: $e\" }\n")
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write("proc parse_only {f} {\n"
                 "  set fh [open $f r]; set t [read $fh]; close $fh\n"
                 "  if {![info complete $t]} { error \"incomplete script\" }\n"
                 "  puts PARSE_OK\n}\n")
        checker = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write(body)
        target = fh.name
    try:
        r = subprocess.run(
            [_TCLSH, "-"], input=f"source {checker}\nparse_only {target}\n",
            capture_output=True, text=True, timeout=60)
        assert "PARSE_OK" in r.stdout, r.stdout + r.stderr
    finally:
        Path(checker).unlink(missing_ok=True)
        Path(target).unlink(missing_ok=True)
