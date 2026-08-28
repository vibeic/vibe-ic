#!/usr/bin/env python3
"""subservient x gf180mcuD — clock-buffer-downsize legalization recovery.

Field evidence (measured on THIS design, gf180mcuD, util 0.3):
    POST_HOLD_LEGALIZE_FAILED            (every displacement rung exhausted)
    468 / 575 clock buffers left OFF the site grid
    [ERROR DRT-0073] No access point ... (gf180mcu..__clkbuf_16)   x1001
    routed.def NETS 6520 with only 2 `+ ROUTED` lines (both power stripes)
    -> DRC 268225 user violations, LVS aborts "no signal routing", SS setup junk

Root cause: GF180's `clkbuf_16` is 28 um = 50 sites wide; CTS/`repair_timing`
inserted 257 of them, and a 50-site cell has NO contiguous free-site run at ANY
displacement, so the displacement ladder (#295/#337) cannot legalize them and
`detailed_route` then writes signal routing to NO net. Signal cells (all Metal1
pins, same as the clock cells) were 100 % on-grid and routed fine — the failure
is specific to the OVER-WIDE clock buffers.

Fix: after every displacement rung fails, swap each clock-tree buffer WIDER than
the CTS sink buffer down to the sink master (pin-compatible I/Z) and re-legalize.
PROVEN on post_hold.def: 259 buffers swapped clkbuf_16->clkbuf_4, DPL converged
at the DEFAULT window, DRT-0073 = 0, 6482 signal nets `+ ROUTED`.

These tests EXECUTE the emitted Tcl under a real `tclsh` with a stubbed odb, so
they verify the recovery BEHAVIOUR (which instances get swapped, and that the
design then legalizes) rather than matching strings in the emitter.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TCLSH = shutil.which("tclsh")
_needs_tcl = pytest.mark.skipif(_TCLSH is None, reason="tclsh not installed")

_SINK = "gf180mcu_fd_sc_mcu7t5v0__clkbuf_4"

# An odb stub: 4 instances — two OVER-WIDE clock buffers (clkbuf_16, 50 sites),
# one sink-width clock buffer (clkbuf_4, 14 sites), one non-clock cell (and2_1).
# `detailed_placement` FAILS with DPL-0036 while ANY clock buffer wider than the
# sink remains (models the no-contiguous-run reality), and succeeds once they
# are gone. So only the swapMaster recovery can make it legal.
_ODB_STUB = r"""
namespace eval ord {}
set ::mw(M16) 50 ; set ::mn(M16) gf180mcu_fd_sc_mcu7t5v0__clkbuf_16
set ::mw(M4)  14 ; set ::mn(M4)  gf180mcu_fd_sc_mcu7t5v0__clkbuf_4
set ::mw(MA)   8 ; set ::mn(MA)  gf180mcu_fd_sc_mcu7t5v0__and2_1
set ::insts {i0 i1 i2 i3}
set ::im(i0) M16 ; set ::im(i1) M16 ; set ::im(i2) M4 ; set ::im(i3) MA
set ::swaps {}
proc ord::get_db {} { return DB }
proc ord::get_db_block {} { return BLK }
proc DB {sub args} {
  if {$sub eq "findMaster"} {
    set n [lindex $args 0]
    foreach h [array names ::mn] { if {$::mn($h) eq $n} { return $h } }
    return "NULL"
  }
}
proc ord::get_die_area {} { return {0 0 400 400} }
proc BLK {sub args} { if {$sub eq "getInsts"} { return $::insts } }
foreach _h {M16 M4 MA} {
  proc $_h {sub args} [format {
    if {$sub eq "getName"}  { return $::mn(%s) }
    if {$sub eq "getWidth"} { return $::mw(%s) }
  } $_h $_h]
}
foreach _h {i0 i1 i2 i3} {
  proc $_h {sub args} [format {
    if {$sub eq "getMaster"}  { return $::im(%s) }
    if {$sub eq "swapMaster"} { set ::im(%s) [lindex $args 0]
                                lappend ::swaps %s ; return }
  } $_h $_h $_h]
}
proc detailed_placement {args} {
  foreach h $::insts {
    set m $::im($h)
    if {[string match {*clkbuf*} $::mn($m)] && $::mw($m) > 14} {
      error "DPL-0036 Detailed placement failed inside DPL."
    }
  }
  return
}
proc check_placement {} { return }
"""


def _run(builder_tcl: str, tmp_path) -> str:
    tcl = (_ODB_STUB + builder_tcl
           + '\nputs "SWAPS: $::swaps"\n'
           + 'foreach h $::insts { puts "IM: $h $::im($h)" }\n')
    f = tmp_path / "recovery.tcl"
    f.write_text(tcl)
    r = _pr.run([_TCLSH, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@_needs_tcl
def test_recovery_swaps_over_wide_clock_buffers_and_legalizes(tmp_path):
    """THE case: displacement ladder fails, the swap rung downsizes the two
    50-site clkbuf_16 to the sink and the design then legalizes."""
    out = _run(p3._build_escalating_legalize_tcl("POST_HOLD", "_ph",
                                                 clk_sink_buf=_SINK), tmp_path)
    assert "POST_HOLD_CLKBUF_DOWNSIZE swapped=2" in out, out
    assert "POST_HOLD_LEGALIZE_OK disp=clkswap" in out, out
    assert "POST_HOLD_LEGALIZE_FAILED" not in out


@_needs_tcl
def test_recovery_only_touches_clock_buffers_wider_than_the_sink(tmp_path):
    """The guard must be surgical: the sink-width clock buffer (i2) and the
    non-clock cell (i3) are NEVER swapped; only the two wide clkbuf_16 are."""
    out = _run(p3._build_escalating_legalize_tcl("POST_HOLD", "_ph",
                                                 clk_sink_buf=_SINK), tmp_path)
    swaps = next(l for l in out.splitlines() if l.startswith("SWAPS:"))
    assert "i0" in swaps and "i1" in swaps
    assert "i2" not in swaps and "i3" not in swaps, swaps
    # i2 (sink clkbuf) and i3 (and2) keep their master; i0/i1 became the sink
    assert "IM: i2 M4" in out and "IM: i3 MA" in out
    assert "IM: i0 M4" in out and "IM: i1 M4" in out


@_needs_tcl
def test_negative_control_without_sink_no_recovery_and_honest_fail(tmp_path):
    """NEGATIVE CONTROL: the SAME unlegalizable stub, but the builder called
    WITHOUT clk_sink_buf (its pre-fix form). No swap is emitted, so the design
    stays illegal and the ladder reports the honest FAILED — proving the swap
    rung is what recovers, not the test's own stub."""
    out = _run(p3._build_escalating_legalize_tcl("POST_HOLD", "_ph"), tmp_path)
    assert "CLKBUF_DOWNSIZE" not in out
    assert "POST_HOLD_LEGALIZE_FAILED" in out
    assert "POST_HOLD_LEGALIZE_OK" not in out
    assert "SWAPS: \n" in out or out.rstrip().endswith("SWAPS:")


@_needs_tcl
def test_no_op_when_default_window_legalizes(tmp_path):
    """Zero regression: when the default window succeeds the swap rung is never
    entered — get_db_block must never be called (it errors if it is)."""
    stub = (_ODB_STUB.replace(
        'proc ord::get_db_block {} { return BLK }',
        'proc ord::get_db_block {} { error "RECOVERY MUST NOT RUN" }')
        # make the default window legal from the start
        .replace('set ::im(i0) M16 ; set ::im(i1) M16',
                 'set ::im(i0) M4 ; set ::im(i1) M4'))
    tcl = (stub + p3._build_escalating_legalize_tcl(
        "POST_HOLD", "_ph", clk_sink_buf=_SINK))
    f = tmp_path / "noop.tcl"
    f.write_text(tcl)
    r = _pr.run([_TCLSH, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "POST_HOLD_LEGALIZE_OK disp=default" in r.stdout
    assert "CLKBUF_DOWNSIZE" not in r.stdout


def test_recovery_emitted_only_post_cts_never_pre_cts():
    """The recovery is emitted ONLY when a sink buffer is passed (POST-CTS,
    where clock buffers exist). The pre-CTS INITIAL_DPL ladder — and every
    other caller that passes no sink — stays byte-for-byte unchanged."""
    with_sink = p3._build_escalating_legalize_tcl("POST_HOLD", "_ph",
                                                  clk_sink_buf=_SINK)
    assert "CLKBUF_DOWNSIZE" in with_sink and "swapMaster" in with_sink
    no_sink = p3._build_escalating_legalize_tcl("INITIAL_DPL", "_ip")
    assert "CLKBUF_DOWNSIZE" not in no_sink and "swapMaster" not in no_sink
    # byte-identical to the historical 2-arg form
    assert no_sink == p3._build_escalating_legalize_tcl("INITIAL_DPL", "_ip", "")


def test_emitted_pnr_tcl_wires_sink_into_post_hold_only():
    """In the shipped pnr.tcl the swap rung appears in the POST_HOLD ladder and
    is fed the SAME sink master that drives `-buf_list`, and the INITIAL_DPL
    ladder carries no swap rung."""
    import inspect
    sig = inspect.signature(p3._build_pnr_tcl_text)
    kw = {n: (0 if "int" in str(pm.annotation)
              else (0.5 if "float" in str(pm.annotation) else "X"))
          for n, pm in sig.parameters.items() if pm.default is inspect._empty}
    kw["clk_buf"] = _SINK
    tcl = p3._build_pnr_tcl_text(**kw)
    assert "POST_HOLD_CLKBUF_DOWNSIZE" in tcl
    # fed the buf_list sink master
    assert f"findMaster {_SINK}" in tcl
    # not attached to the pre-CTS initial ladder
    assert "INITIAL_DPL_CLKBUF_DOWNSIZE" not in tcl


# --- the downsize's own diagnostic: it must speak on FAILURE and be silent on
# SUCCESS.  Field-measured on gf180mcuD (die 3800, 2 089 instances swapped): the
# emitted Tcl printed `POST_HOLD_CLKBUF_DOWNSIZE_NONFATAL:` with an EMPTY message
# straight after `swapped=2089`, i.e. on the success path -- and, by the same
# inverted guard, printed nothing at all when the body threw.  A rung measured to
# take the illegal-cell count from 2 337 to 296 must not be able to fail in silence.

_ODB_STUB_FINDMASTER_THROWS = _ODB_STUB + r"""
# make the swap body throw the way a PDK whose clock buffer is named differently,
# or an odb that refuses swapMaster, would make it throw
proc DB {sub args} { error "findMaster: no such master in this PDK" }
"""


@_needs_tcl
def test_downsize_diagnostic_is_silent_when_the_swap_succeeds(tmp_path):
    """A `_NONFATAL:` line on the success path is a diagnostic that means nothing."""
    out = _run(p3._build_escalating_legalize_tcl("POST_HOLD", "_ph",
                                                 clk_sink_buf=_SINK), tmp_path)
    assert "POST_HOLD_CLKBUF_DOWNSIZE swapped=2" in out, out
    assert "POST_HOLD_CLKBUF_DOWNSIZE_NONFATAL" not in out, out


@_needs_tcl
def test_downsize_diagnostic_speaks_when_the_swap_throws(tmp_path):
    """And the failure path must NAME the failure rather than fall through mute."""
    tcl = (_ODB_STUB_FINDMASTER_THROWS
           + p3._build_escalating_legalize_tcl("POST_HOLD", "_ph",
                                               clk_sink_buf=_SINK))
    f = tmp_path / "recovery_throws.tcl"
    f.write_text(tcl)
    r = _pr.run([_TCLSH, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "POST_HOLD_CLKBUF_DOWNSIZE_NONFATAL: findMaster: no such master" in out, out
    # and it must not claim a swap it did not make
    assert "POST_HOLD_CLKBUF_DOWNSIZE swapped=" not in out, out
