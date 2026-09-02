"""The residual violations ship having had no routing action aimed at them.

MEASURED (subservient x gf180mcuD round 3, plugin 1.15.55, host 8HD-9,
image ...@sha256:66c33ff2..., OpenROAD 26Q3-1472). The tail of the PnR run:

    PNR_STAGE: postroute_fill        -> filler, PG re-connect
    ... PG re-route: `detailed_route -verbose 0`
        logged DRT-0178/0036/0179 and NOT ONE routing iteration -- with no
        PG-dirty net there was nothing for it to do
    PNR_STAGE: write_routed

and the last call that actually routed was the DRV loop's, which ended:

    [INFO DRT-0199]   Number of violations = 1.       (x ~50 iterations)
    [WARNING DRT-0701] Post-route verification found 3 violation(s) that the
    routing loop did not report (1 in-loop). The published result is the
    verified one.

So the three violations that SHIP are, in OpenROAD's own words, ones the
routing loop never reported -- and after the whole-design verification found
them, nothing routed again. Nothing can be expected of a loop that is not
shown the finding.

This stage shows it: the nets the router NAMES in its own DRC report
(`detailed_route -output_drc`, which this flow asks for) are cleared so they
are unrouted, and `detailed_route` is re-invoked. Bounded to
`_NAMED_VIOL_REROUTE_MAX_PASSES`, and it stops the moment a pass does not
strictly reduce the count.

NO `global_route`. This repo has already MEASURED that stale detailed routes
against fresh guides abort the whole re-route (DRT-0206 -- see
`_spare_safe_routing_clear_tcl`'s v1.8.43 note). The guides every current
route was laid against are left untouched.

NO `-verbose 0` on the re-route, deliberately: the published count is read
from the LOG, so a routing call that changes geometry and prints no count
would leave the verdict quoting the previous route's number.

DECLARED: ADVISORY. The `pnr` verdict re-measures the count after this stage;
this can never turn a failing count into a passing one, only change the
geometry the count is taken on.

HOW THIS IS PROVEN. The generated Tcl is EXECUTED by `tclsh` against stubs for
the odb handles, so the control flow, the protections and the bound are
measured rather than pattern-matched. The four inert paths make ZERO
`detailed_route` calls.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
_spec = importlib.util.spec_from_file_location("_p3r_named_viol", _PROG)
_p3r = importlib.util.module_from_spec(_spec)
sys.modules["_p3r_named_viol"] = _p3r
_spec.loader.exec_module(_p3r)

pytestmark = pytest.mark.skipif(
    shutil.which("tclsh") is None,
    reason="tclsh not on PATH: this test EXECUTES the generated Tcl rather "
           "than pattern-matching it, so without an interpreter it would be "
           "a vacuous pass")

# The real round-3 report, verbatim (same bytes as the sibling fixture).
_REPORT = (Path(__file__).resolve().parent / "fixtures" / "drt_residual_types"
           / "routed_router_ns_metal.drc.rpt").read_text()
_NETS = ["__uuf__._0114_", "__uuf__._0053_", "_128_"]

_STUBS = textwrap.dedent(r"""
    # Every odb handle is a single command token, as in the real API.
    set ::DR_CALLS 0
    set ::DESTROYED {}
    set ::HN 0
    proc _mkhandle {kind name} {
        set h "h[incr ::HN]"
        proc ::$h {sub args} [format {
            return [_handle_dispatch %s {%s} $sub $args]
        } $kind [string map {\\ \\\\ \{ \\\{ \} \\\}} $name]]
        return $h
    }
    proc _handle_dispatch {kind name sub args} {
        switch -- $kind {
            block { switch -- $sub {
                findNet { set n [lindex [lindex $args 0] 0]
                          if {[lsearch -exact $::MISSING $n] >= 0} { return "NULL" }
                          return [_mkhandle net $n] } } }
            net { switch -- $sub {
                getSigType { if {[lsearch -exact $::PGNETS $name] >= 0} { return POWER }
                             return SIGNAL }
                getITerms  { return [list [_mkhandle iterm $name]] }
                getWire    { if {[lsearch -exact $::NOWIRE $name] >= 0} { return "NULL" }
                             return "wire:$name" } } }
            iterm { switch -- $sub { getInst { return [_mkhandle inst $name] } } }
            inst  { switch -- $sub { isDoNotTouch {
                        return [expr {[lsearch -exact $::DNT $name] >= 0}] } } }
        }
        error "stub: unhandled $kind.$sub"
    }
    namespace eval ord { proc get_db_block {} { return [_mkhandle block ""] } }
    namespace eval odb { proc dbWire_destroy {w} { lappend ::DESTROYED $w } }
    proc detailed_route args {
        incr ::DR_CALLS
        set nxt [lindex $::AFTER_REPORTS [expr {$::DR_CALLS - 1}]]
        if {$nxt ne "KEEP"} { set f [open $::RPT w]; puts -nonewline $f $nxt; close $f }
    }
""")


def _run(tmp_path, report, *, after, dnt=(), pg=(), missing=()):
    rpt = tmp_path / "routed_router.drc.rpt"
    if report is not None:
        rpt.write_text(report)
    body = _p3r._named_violation_reroute_tcl(str(rpt))
    script = tmp_path / "drive.tcl"
    script.write_text(
        f'set ::RPT "{rpt}"\n'
        f'set ::MISSING {{{" ".join(missing)}}}\n'
        f'set ::PGNETS {{{" ".join(pg)}}}\n'
        f'set ::DNT {{{" ".join(dnt)}}}\n'
        f'set ::NOWIRE {{}}\n'
        f'set ::AFTER_REPORTS [list {" ".join(chr(123) + a + chr(125) for a in after)}]\n'
        + _STUBS + "\n" + body
        + '\nputs "DR_CALLS=$::DR_CALLS"\nputs "DESTROYED=$::DESTROYED"\n')
    p = subprocess.run(["tclsh", str(script)], capture_output=True, text=True,
                       timeout=60)
    assert p.returncode == 0, p.stderr
    out = p.stdout
    calls = int(out.split("DR_CALLS=")[1].split("\n")[0])
    return out, calls


def test_it_rips_up_exactly_the_named_nets_and_reroutes_them(tmp_path):
    out, calls = _run(tmp_path, _REPORT, after=[""])
    assert "NAMED_VIOL_REROUTE_PASS1_BEFORE: 3 named_nets=3" in out
    assert "NAMED_VIOL_REROUTE_CLEARED: 3 (skipped=0)" in out
    assert calls == 1
    for n in _NETS:
        assert f"wire:{n}" in out
    # the router's own re-count is what closes the loop, not an assumption
    assert "NAMED_VIOL_REROUTE_PASS1_AFTER: 0 (was 3)" in out
    assert "NAMED_VIOL_REROUTE_CLEAN: pass 2" in out


def test_a_pass_that_does_not_improve_stops_the_repair(tmp_path):
    """THE BOUND. If the residual is not one a re-route of these nets moves,
    the stage must cost exactly one pass and say so -- not spend its budget."""
    out, calls = _run(tmp_path, _REPORT, after=["KEEP", "KEEP"])
    assert calls == 1
    assert "NAMED_VIOL_REROUTE_PASS1_AFTER: 3 (was 3)" in out
    assert "NAMED_VIOL_REROUTE_NO_IMPROVEMENT: 3 -> 3" in out


def test_protected_nets_are_never_ripped_up(tmp_path):
    """Same protection every other routing-clear site in this file applies: a
    net touching a dont_touch instance (the Design-for-ECO spare bindings) and
    a PG net are skipped. With nothing left to clear the router is not called
    at all."""
    out, calls = _run(tmp_path, _REPORT, after=["KEEP"],
                      dnt=_NETS[:2], pg=_NETS[2:])
    assert calls == 0
    assert "NAMED_VIOL_REROUTE_CLEARED: 0 (skipped=3)" in out
    assert "NAMED_VIOL_REROUTE_NOTHING_CLEARED" in out
    assert "DESTROYED=\n" in out


def test_no_report_is_named_not_assumed(tmp_path):
    """A build whose `detailed_route` does not accept `-output_drc` writes no
    report. Silence there must read as SKIP, not as a clean route."""
    out, calls = _run(tmp_path, None, after=["KEEP"])
    assert calls == 0
    assert "NAMED_VIOL_REROUTE_SKIP: no router DRC report" in out


def test_an_empty_report_is_a_clean_route(tmp_path):
    out, calls = _run(tmp_path, "", after=["KEEP"])
    assert calls == 0
    assert "NAMED_VIOL_REROUTE_CLEAN: pass 1" in out


def test_the_stage_is_wired_into_the_flow_and_declared_nonfatal():
    assert ("postroute_named_violation_reroute"
            in _p3r._PNR_STAGE_ORDER)
    assert ("postroute_named_violation_reroute"
            in _p3r._PNR_NONFATAL_STAGES)
    order = list(_p3r._PNR_STAGE_ORDER)
    assert (order.index("postroute_named_violation_reroute")
            > order.index("postroute_fill"))
    assert (order.index("postroute_named_violation_reroute")
            < order.index("write_routed")), (
        "the repair must run BEFORE the route is written, or the shipped DEF "
        "is the un-repaired one")


def test_the_reroute_is_not_silenced():
    """`-verbose 0` would change the geometry without printing a count, and the
    published count is read from the log."""
    body = _p3r._named_violation_reroute_tcl("/x/rpt")
    assert "detailed_route {*}$_vic_drc_opt" in body
    assert "-verbose 0" not in body
    assert "global_route" not in body, (
        "a full global_route here re-derives guides under every OTHER net's "
        "stale detailed route -- measured to abort the whole re-route "
        "(DRT-0206)")
