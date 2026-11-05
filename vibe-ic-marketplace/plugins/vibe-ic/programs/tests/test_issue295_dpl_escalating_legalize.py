#!/usr/bin/env python3
"""ORGANIC #295 — DPL-0036 legalization failure after timing-buffer insertion.

Field evidence (subservient x gf180mcuD):
    [INFO RSZ-0038] Inserted 564 buffers in 155 nets
    [INFO DPL-0034] Detailed placement failed on the following 13 instances
    [ERROR DPL-0036] Detailed placement failed inside DPL.
`repair_design` inserted 564 buffers, detailed placement could not find a legal
site for 13 of them, and the whole PnR died on a step unrelated to that cell's
real engineering residual. The die-upsize retry loop does not catch a
LEGALIZATION failure.

The shipped mitigation — `catch {detailed_placement}` + a NONFATAL puts — is
not a fix either: it swallows the error and carries on with an ILLEGAL
placement, so routing and sign-off are built on overlapping cells. Same false-
certificate family as the rest of this campaign: recorded, then ignored.

These tests EXECUTE the generated Tcl under a real `tclsh` with stubbed
OpenROAD commands, so they verify the retry BEHAVIOUR rather than matching
strings in the emitter.
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

_STUB = """
set ::calls {}
proc detailed_placement args {
    set disp default
    if {[llength $args] >= 2} { set disp [lindex $args 1] }
    lappend ::calls $disp
    if {%s} { error "DPL-0036 Detailed placement failed inside DPL." }
}
proc check_placement {} { %s }
"""






@_needs_tcl
def test_295_negative_control_pre_fix_behaviour_would_not_recover(tmp_path):
    """NEGATIVE CONTROL (the one #295 says must exist before landing).

    The pre-fix emitter did ONE `detailed_placement` and swallowed the error.
    Reproduce exactly that shape against the same stub: it neither recovers nor
    reports a legal placement — proving the ladder is what does the work, not
    the test's own stub."""
    pre_fix = ('if {[catch {detailed_placement} e]} { '
               'puts "PRE_FIX_NONFATAL: swallowed" }\n')
    tcl = (_STUB % ('$disp eq "default" || $disp < 20', "return")
           + pre_fix + 'puts "CALLS: $::calls"\n')
    f = tmp_path / "prefix.tcl"
    f.write_text(tcl)
    out = _pr.run([_TCLSH, str(f)], capture_output=True, text=True).stdout
    assert "PRE_FIX_NONFATAL: swallowed" in out
    assert "LEGALIZE_OK" not in out       # never becomes legal
    assert "CALLS: default" in out and " 20" not in out   # never retried














# ── #296: the OTHER bare detailed_placement calls in the emitted pnr.tcl ──────
# #296 reported the post-hold call: 87 clustered clkbuf_16 (50 sites each) fail
# the default window and DPL-0036 then kills the whole OpenROAD process. It was
# masked until #295 landed, because the flow never reached CTS before.
# A third bare call (post-global-placement) was found while wiring it.









# ── #337 (harvested via #349): the FULL-DIE final rung ───────────────────────
# The fixed rungs top out at 100 um; on a large die that can still be far
# smaller than the nearest legal site for a wide buffer (#337 measured drive-20
# buffers with NO free run reachable at 42 % utilization). The final rung
# widens the window to the LIVE die extent via `ord::get_die_area` — measured
# at RUN time, so a die-upsize retry that rewrote initialize_floorplan is
# still covered (the builder receives no geometry).

_GDA_STUB = ("namespace eval ord { proc get_die_area {} "
             "{ return {0 0 %s %s} } }\n")
