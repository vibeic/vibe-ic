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
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

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


def _run(dpl_fail_cond: str, check_body: str = "return", tmp_path=None) -> str:
    tcl = (_STUB % (dpl_fail_cond, check_body)
           + p3._build_escalating_legalize_tcl("TEST", "_t")
           + '\nputs "CALLS: $::calls"\n')
    f = tmp_path / "leg.tcl"
    f.write_text(tcl)
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@_needs_tcl
def test_295_escalates_until_the_window_is_wide_enough(tmp_path):
    """THE #295 case: the default window fails, a wider one succeeds."""
    out = _run('$disp eq "default" || $disp < 20', tmp_path=tmp_path)
    assert "TEST_LEGALIZE_OK disp=20" in out, out
    assert "default 5 20" in out          # it really did escalate, in order


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
    out = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                         timeout=60).stdout
    assert "PRE_FIX_NONFATAL: swallowed" in out
    assert "LEGALIZE_OK" not in out       # never becomes legal
    assert "CALLS: default" in out and " 20" not in out   # never retried


@_needs_tcl
def test_295_exhausting_every_rung_reports_an_honest_failure(tmp_path):
    """An unlegalizable placement must FAIL loudly, not be swallowed."""
    out = _run("1", tmp_path=tmp_path)
    assert "TEST_LEGALIZE_FAILED" in out
    assert "TEST_LEGALIZE_OK" not in out


@_needs_tcl
def test_295_no_wasted_retry_when_the_default_window_works(tmp_path):
    """The overwhelmingly common case must cost exactly one call."""
    out = _run("0", tmp_path=tmp_path)
    assert "TEST_LEGALIZE_OK disp=default" in out
    assert "CALLS: default\n" in out or out.rstrip().endswith("CALLS: default")


@_needs_tcl
def test_295_silent_illegal_placement_is_not_accepted(tmp_path):
    """`detailed_placement` not throwing is NOT evidence the placement is
    legal — check_placement is the proof, and its failure must block."""
    out = _run("0", check_body='error "DPL-0033 not aligned"',
               tmp_path=tmp_path)
    assert "TEST_LEGALIZE_FAILED" in out, out
    assert "TEST_LEGALIZE_OK" not in out


@_needs_tcl
def test_295_generated_tcl_is_syntactically_valid(tmp_path):
    """The emitter must produce Tcl a real interpreter accepts — brace-balance
    bugs in generated Tcl have bitten this file before (#581)."""
    tcl = ("proc detailed_placement args {}\nproc check_placement {} {}\n"
           + p3._post_buffered_repair_tcl("SHIP", "_X", "_v")
           .replace("repair_timing", "list"))
    f = tmp_path / "emit.tcl"
    f.write_text(tcl)
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr


def test_295_shared_builder_no_longer_swallows_the_failure():
    """The old swallow-and-continue form must be GONE from the shared
    post-buffered repair builder."""
    t = p3._post_buffered_repair_tcl("SHIP", "_X", "_v")
    assert "_REPAIR_LEGALIZE_NONFATAL" not in t
    assert "-max_displacement" in t and "check_placement" in t
    assert "LEGALIZE_FAILED" in t


def test_295_escalation_ladder_is_bounded_and_ordered():
    """Bounded so an unlegalizable design terminates; ascending so the cheapest
    window is tried first."""
    assert list(p3._DPL_ESCALATION_SITES) == sorted(p3._DPL_ESCALATION_SITES)
    assert len(p3._DPL_ESCALATION_SITES) <= 5
    assert all(d > 0 for d in p3._DPL_ESCALATION_SITES)


# ── #296: the OTHER bare detailed_placement calls in the emitted pnr.tcl ──────
# #296 reported the post-hold call: 87 clustered clkbuf_16 (50 sites each) fail
# the default window and DPL-0036 then kills the whole OpenROAD process. It was
# masked until #295 landed, because the flow never reached CTS before.
# A third bare call (post-global-placement) was found while wiring it.

def _emitted_pnr_tcl() -> str:
    import inspect
    sig = inspect.signature(p3._build_pnr_tcl_text)
    kw = {n: (0 if "int" in str(pm.annotation)
              else (0.5 if "float" in str(pm.annotation) else "X"))
          for n, pm in sig.parameters.items() if pm.default is inspect._empty}
    return p3._build_pnr_tcl_text(**kw)


def test_296_no_bare_detailed_placement_survives_in_pnr_tcl():
    """A BARE `detailed_placement` has no catch and no escalation, so DPL-0036
    kills the whole OpenROAD process. None may remain."""
    import re
    bare = [i for i, l in enumerate(_emitted_pnr_tcl().splitlines(), 1)
            if re.match(r"^detailed_placement\s*$", l)]
    assert bare == [], f"bare detailed_placement at emitted lines {bare}"


def test_296_post_hold_and_initial_use_the_same_ladder():
    tcl = _emitted_pnr_tcl()
    assert "POST_HOLD_LEGALIZE_OK" in tcl and "POST_HOLD_LEGALIZE_FAILED" in tcl
    assert "INITIAL_DPL_LEGALIZE_OK" in tcl
    assert tcl.count("-max_displacement") >= 2


def test_296_cts_buffer_selection_is_untouched():
    """The fix must NOT buy placement success by narrowing the CTS root buffer:
    that moves clock skew / insertion delay and needs multi-corner clock
    sign-off evidence first. Placement window only."""
    tcl = _emitted_pnr_tcl()
    assert "-root_buf" in tcl and "clock_tree_synthesis" in tcl


@_needs_tcl
def test_296_emitted_post_hold_ladder_executes_and_recovers(tmp_path):
    """Extract the ladder FROM THE EMITTED pnr.tcl (not from the builder) and
    run it, so the test covers what actually ships."""
    import re
    tcl = _emitted_pnr_tcl()
    m = re.search(r"set _dplok_ph 0\n.*?POST_HOLD_LEGALIZE_FAILED\"\s*\}\n",
                  tcl, re.S)
    assert m, "post-hold ladder not found in the emitted pnr.tcl"
    f = tmp_path / "ph.tcl"
    f.write_text(_STUB % ('$disp eq "default" || $disp < 20', "return")
                 + m.group(0) + '\nputs "CALLS: $::calls"\n')
    out = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert "POST_HOLD_LEGALIZE_OK disp=20" in out.stdout
