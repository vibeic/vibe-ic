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
import shutil, subprocess, sys
from pathlib import Path
import pytest
_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402
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
    r = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout

@_needs_tcl
def test_spare_and_dnt_nets_survive_the_clear(tmp_path):
    out = _run(p3._spare_safe_routing_clear_tcl("SHIP"), tmp_path)
    assert "w_n_sig" in out.split("DESTROYED:")[1]
    assert "w_n_spare" not in out, "the spare net's wire was destroyed — v1.5.65 again"
    assert "w_n_dnt" not in out, "a dont_touch net's wire was destroyed"
    assert "spare_preserved=2" in out

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

def test_all_routing_clear_sites_use_the_filtered_helper():
    """No bare unfiltered clear may remain: every dbWire_destroy loop must go
    through the spare-safe helper (or be the helper itself)."""
    import re
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn_start = src.index("def _spare_safe_routing_clear_tcl")
    fn_end = src.index("\ndef ", fn_start + 1)
    outside = src[:fn_start] + src[fn_end:]
    bare = [m.start() for m in re.finditer(r"dbWire_destroy", outside)]
    assert bare == [], (
        f"{len(bare)} routing-clear site(s) still bypass the spare-safe filter")
