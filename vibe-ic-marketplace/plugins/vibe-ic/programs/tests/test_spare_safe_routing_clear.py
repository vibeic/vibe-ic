#!/usr/bin/env python3
"""ORGANIC #349 salvage (from #332/#333/#334) — spare-net-safe routing clear.

The v1.5.65 post-mortem: a reroute loop cleared ALL signal-net wires, then the
rerouter merged the now-unrouted spare-tie nets (`spare_tielo`/`spare_tiehi`,
the Design-for-ECO spare-input bindings) into unrelated signal nets
(`la_data_out`, `user_irq`) — a real LVS mismatch. The escalation that exposed
it was disabled; the CLEAR that enabled it stayed unfiltered.

Measured on main before this fix: all THREE routing-clear sites filter only
POWER/GROUND — the spare/dont_touch hole is open at every one of them, so any
reroute loop can repeat the v1.5.65 failure even with the escalation off.

These tests EXECUTE the generated Tcl under a real tclsh with stubbed odb/ord,
verifying behaviour rather than string shape.
"""
from __future__ import annotations
import ast
import shutil, sys
from pathlib import Path
import pytest
_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402
_TCLSH = shutil.which("tclsh")
_needs_tcl = pytest.mark.skipif(_TCLSH is None, reason="tclsh not installed")

# odb/ord stubs: 5 nets — signal(routed), spare_tielo(routed), POWER,
# dont_touch signal, plain signal(unrouted).
_STUB = """
namespace eval ord {}
proc ord::get_db_block {} { return BLK }
set ::destroyed {}
proc BLK {m} { if {$m eq "getNets"} { return {n_sig n_spare n_pwr n_dnt n_unrouted} } }
foreach n {n_sig n_spare n_pwr n_dnt n_unrouted} {
  proc $n {m args} [format {
    set n %s
    switch -- $m {
      getSigType { if {$n eq "n_pwr"} { return POWER } else { return SIGNAL } }
      getName    { if {$n eq "n_spare"} { return spare_tielo_7 } else { return $n } }
      getITerms  { if {$n eq "n_dnt"} { return {it_dnt} } else { return {} } }
      getBTerms  { if {$n eq "n_unrouted"} { return {bt_a bt_b} } else { return {} } }
      getWire    { if {$n eq "n_unrouted"} { return NULL } else { return w_$n } }
    }
  } $n]
}
proc it_dnt {m} { return inst_dnt }
proc inst_dnt {m} { if {$m eq "isDoNotTouch"} { return 1 } }
namespace eval odb {}
proc odb::dbWire_destroy {w} { lappend ::destroyed $w }
"""

def _run(tcl_body: str, tmp_path) -> str:
    f = tmp_path / "t.tcl"
    f.write_text(_STUB + tcl_body + '\nputs "DESTROYED: $::destroyed"\n')
    r = _pr.run([_TCLSH, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout

@_needs_tcl
def test_dnt_nets_survive_the_clear_and_spare_named_nets_do_not(tmp_path):
    """v1.8.43 CONTRACT CHANGE, and the reason, stated where it will be read.

    Until v1.8.42 this test asserted that a net merely NAMED `*spare*` kept its
    routing across the clear. MEASURED on spm x sky130A at v1.8.42 (two real Tcl
    files differing only in that filter, everything else identical):

        with the *spare* name filter    -> [ERROR DRT-0206] checkConnectivity
                                           error, SHIP_REROUTE_INCOMPLETE, the
                                           repaired route DISCARDED
        without it                      -> reroute completes, SHIP_WNS_POSTROUTE

    Preserving ONE net's stale detailed routing across a global re-route of
    every other net leaves TritonRoute a net it cannot reconcile against the
    fresh guides. The filter also protected nothing: `dbWire_destroy` destroys a
    WIRE, never the net or its iterms, so the Design-for-ECO binding (the DEF
    NETS terminal list) is untouched and the spare cells stay `+ FIXED`.

    The v1.5.65 hazard the filter was written for — a spare-tie net that comes
    back UNROUTED, whose pins extraction then merges into a neighbour — is now
    MEASURED by `_routing_integrity_check_tcl` and refused by the promotion
    gate, instead of being guessed at by a name match. See
    `test_routing_integrity_check_*` below.

    What survives the clear is what actually must: a net touching a
    `dont_touch` instance."""
    out = _run(p3._spare_safe_routing_clear_tcl("SHIP"), tmp_path)
    destroyed = out.split("DESTROYED:")[1]
    assert "w_n_sig" in destroyed
    assert "w_n_spare" in destroyed, (
        "a spare-NAMED net with no dont_touch instance must now be cleared like "
        "any other signal net — keeping it is what caused DRT-0206")
    assert "w_n_dnt" not in destroyed, "a dont_touch net's wire was destroyed"
    assert "spare_preserved=1" in out, (
        "only the dont_touch net is preserved now (was 2 with the name filter)")


@_needs_tcl
def test_routing_integrity_check_counts_unrouted_multiterm_nets(tmp_path):
    """The replacement protection: after the reroute, a multi-terminal signal
    net with NO wire is the v1.5.65 failure mode itself, whatever it is named.
    The stub's `n_unrouted` has 2 terminals and returns NULL for getWire."""
    out = _run(p3._routing_integrity_check_tcl("SHIP"), tmp_path)
    line = [l for l in out.splitlines() if l.startswith("SHIP_UNROUTED_NETS:")]
    assert line, out
    assert line[0].startswith("SHIP_UNROUTED_NETS: 1"), line[0]
    assert "n_unrouted" in line[0], "the offender must be NAMED, not just counted"


def test_promotion_gate_refuses_a_route_that_left_a_net_unrouted():
    """`detailed_route` can return rc=0 and still leave a net with no wire.
    A MEASURED non-zero count must refuse promotion; an ABSENT marker must not
    change any pre-existing decision (UNMEASURED is not ZERO, and this guard is
    strictly additive)."""
    base = dict(wns_before=1.0, wns_after_repair=2.0, wns_postroute=2.0,
                route_violations=0, reroute_incomplete=0)
    assert p3._ship_repair_should_promote({**base, "unrouted_nets": 0}, True, True)
    assert p3._ship_repair_should_promote({**base, "unrouted_nets": None}, True, True)
    assert not p3._ship_repair_should_promote({**base, "unrouted_nets": 2}, True, True)


def test_parse_ship_repair_log_reads_the_integrity_marker():
    assert p3._parse_ship_repair_log("SHIP_UNROUTED_NETS: 0 \n")["unrouted_nets"] == 0
    assert p3._parse_ship_repair_log("SHIP_UNROUTED_NETS: 3 a,b,c\n")["unrouted_nets"] == 3
    assert p3._parse_ship_repair_log("nothing here")["unrouted_nets"] is None

@_needs_tcl
def test_negative_control_the_old_shape_destroys_the_spare_wire(tmp_path):
    """The pre-fix shape (filter POWER/GROUND only) DOES destroy the spare
    net's wire — proving the filter is what protects it, not the stub."""
    old = (
        "if {[catch {\n"
        "  foreach _net [[ord::get_db_block] getNets] {\n"
        "    set _st [$_net getSigType]\n"
        '    if {$_st eq "POWER" || $_st eq "GROUND"} { continue }\n'
        "    set _w [$_net getWire]\n"
        '    if {$_w ne "NULL"} { odb::dbWire_destroy $_w }\n'
        "  }\n"
        '} e]} { puts "OLD_NONFATAL: $e" }\n')
    out = _run(old, tmp_path)
    assert "w_n_spare" in out, "control broken: old shape should hit the spare net"

@_needs_tcl
def test_marker_prefix_differentiates_call_sites(tmp_path):
    out = _run(p3._spare_safe_routing_clear_tcl("SHIP_ESC"), tmp_path)
    assert "SHIP_ESC_ROUTING_CLEARED:" in out

_OWNER = "_spare_safe_clear_net_proc_tcl"


def _owner_span():
    """(first, last) line of the function that owns the destroy."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == _OWNER:
            return node.lineno, node.end_lineno
    raise AssertionError(f"{_OWNER} is gone; the guard below would be vacuous")


def _in_owner(line):
    lo, hi = _owner_span()
    return lo <= line <= hi


def _emitted_destroy_lines():
    """Lines of the runner that EMIT `dbWire_destroy` into a Tcl script.

    The population is the string constants the runner writes, NOT every
    occurrence of the token: a docstring that explains what
    `odb::dbWire_destroy` does to a wire is documentation, and three of the
    four occurrences in this file are exactly that. A guard whose population
    counts its own rationale goes red on the sentence that justifies it — the
    shape that has already cost this repo a batch. Docstrings are excluded
    structurally (AST), never by an allow-list of phrases.
    """
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docs.add(id(first.value))
    return sorted(
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docs and "dbWire_destroy" in node.value)


def test_all_routing_clear_sites_use_the_filtered_helper():
    """No bare unfiltered clear may remain: `odb::dbWire_destroy` is written in
    exactly ONE function, the one that owns the decision.

    THE FOURTH SITE, MEASURED. On tree 5e850b3acee8 one `dbWire_destroy` sat
    outside the helper — phase3_one_shot_runner.py:19323, the
    `NAMED_VIOL_REROUTE` loop that commit 1ec22dabcb landed to rip up the nets
    the router's own DRC report cites. It was not a stale guard: that loop had
    RE-TYPED the same two protections (skip POWER/GROUND, skip any net touching
    an `isDoNotTouch` instance) in place. Two copies of the v1.5.65 protection
    is precisely how the first one drifts, and pasting the helper's string a
    third time to satisfy a regex would have made it three.

    Adding this site to an exception list, or moving the helper's function
    boundary around it, would be a hand-written allow-list — blind to the fifth
    site the same way this one was blind to the fourth. The loops differ only in
    WHICH nets they walk, so the decision moved into a Tcl proc both emit, and
    the population here is "every occurrence in the file", with no exceptions to
    keep in step.
    """
    emitted = _emitted_destroy_lines()
    outside = [ln for ln in emitted if not _in_owner(ln)]
    assert outside == [], (
        f"{len(outside)} routing-clear site(s) still bypass the spare-safe "
        f"filter, at line(s) {outside}; route them through {_OWNER}")


def test_the_owner_really_emits_the_destroy():
    """THE CONTROL FOR THE GUARD ABOVE. "No occurrence outside function F" is
    satisfied completely by an F that has been renamed away, or by a file that
    no longer destroys anything — a guard that has gone blind reads identically
    to a clean tree."""
    emitted = _emitted_destroy_lines()
    assert len(emitted) == 1, (
        f"expected exactly one emitted destroy in the runner, found {emitted}")
    assert _in_owner(emitted[0])


# ── the fourth site, DRIVEN under the same stubs as the helper ─────────────
_FINDNET_STUB = """
proc BLK2 {m args} {
  if {$m eq "getNets"} { return {n_sig n_spare n_pwr n_dnt n_unrouted} }
  if {$m eq "findNet"} { return [lindex $args 0] }
}
proc ord::get_db_block {} { return BLK2 }
"""


@_needs_tcl
def test_the_named_violation_reroute_site_protects_the_same_nets(tmp_path):
    """BEHAVIOUR, not string shape: emit the NAMED_VIOL_REROUTE Tcl, hand it a
    router DRC report that cites EVERY net including the protected ones, and
    execute it under the same odb/ord stubs the helper is driven with.

    A string guard cannot tell a correct filter from a copy that has drifted;
    this can. The report is truncated after the rip-up (`detailed_route` and
    the recount are not stubbed), so the assertion is on what the rip-up
    destroyed, which is the subject.
    """
    rpt = tmp_path / "drc.rpt"
    rpt.write_text(
        "violation type: Metal Spacing\n"
        "  srcs: net:n_sig net:n_spare net:n_pwr net:n_dnt net:n_unrouted\n")
    body = (_FINDNET_STUB
            + "proc detailed_route {args} { error \"stop-here\" }\n"
            + p3._named_violation_reroute_tcl(str(rpt)))
    out = _run(body, tmp_path)
    destroyed = out.split("DESTROYED:")[1]
    assert "w_n_pwr" not in destroyed, "a POWER net's wire was destroyed"
    assert "w_n_dnt" not in destroyed, "a dont_touch net's wire was destroyed"
    assert "w_n_sig" in destroyed, (
        "control: an ordinary named signal net must still be ripped up, or "
        "this test would pass on a site that clears nothing")
    assert "NAMED_VIOL_REROUTE_CLEARED: 2 (skipped=2)" in out, out


@_needs_tcl
def test_the_named_violation_reroute_emits_the_integrity_check(tmp_path):
    """The `*spare*` NAME filter was removed in v1.8.43 and replaced, by the
    helper's own docstring, with the post-reroute integrity CHECK. On tree
    5e850b3acee8 that check was wired at ONE call site (marker SHIP) and this
    reroute — which rips up and re-routes real nets inside the PnR script — had
    none, so the very failure mode the filter was traded away for was
    unobservable here. It is emitted now and NAMES the offender."""
    rpt = tmp_path / "drc.rpt"
    rpt.write_text("violation type: x\n  srcs: net:n_sig\n")
    body = (_FINDNET_STUB + p3._named_violation_reroute_tcl(str(rpt)))
    out = _run(body, tmp_path)
    line = [l for l in out.splitlines()
            if l.startswith("NAMED_VIOL_REROUTE_UNROUTED_NETS:")]
    assert line, out
    assert line[0].startswith("NAMED_VIOL_REROUTE_UNROUTED_NETS: 1"), line[0]
    assert "n_unrouted" in line[0], "the offender must be NAMED, not just counted"
