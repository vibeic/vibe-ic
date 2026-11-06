"""A native antenna raise is judged on every wire the pass took, not on its own.

R-0915-121. TWO ICs, ONE WALL, and the scope of my own R-0915-116(2)(ii)
judgement was the defect.

spm x gf180mcuD as a DIE (lane icspm5, run13, main 287e8a7b0): the antenna
loop's native `repair_antennas -reroute` raised DRT-0206 with checkConnectivity
naming 86 DISTINCT nets. The judgement asked only whether the ONE net the pass
had touched (p__core) was still wired, found that it was, and called the raise
SPURIOUS. 450 lines later the sign-off integrity check found 84 signal nets
with two or more terminals and no wire, and the run died
NAMED_VIOL_REROUTE_INCOMPLETE with no routed.def. run12 -> run13 counters were
otherwise identical (DRT-0199 494/201/129/2/0; DRT-0702 0).

subservient x gf180mcuD as a DIE (int9 and int10, this lane, the same main):
the identical shape at 77 nets, and bracketed to this stage by measurement --
`routed_preantenna.def`, the post-route tail's own INPUT, text-parsed with no
tool in the way, carries 5319 net records of which 34 have no routing, 33 of
those have two or more terminals, and ALL 33 are the I/O nets the abutment
clause correctly excuses (VDD, VSS, i_clk, i_rst, i_sram_data[0..7], o_gpio,
o_sram_addr[*]) -- ZERO `u_core/*` among them. The antenna stage's own entry
checkpoint `antenna_pre_repair.odb` reads ODB_TOTAL_NETS 5528, ODB_NOWIRE 1,
ODB_NOWIRE_MULTITERM 0. By NAMED_VIOL_REROUTE the count is 77. Wired at the
stage entry, wireless at the stage exit.

(a) So the scope becomes EVERY NET THIS PASS COULD HAVE UNWIRED: a census of
which non-special nets had a wire before the native call, compared against the
same census after it. That is a SUPERSET of the ruling's "every net
checkConnectivity named PLUS every net the pass touched", and it is the form
that can be implemented at all -- the raise reaches Tcl as the string
"DRT-0206" with no net in it, so the names exist only in the tool's own log.
A superset also cannot miss a net the message failed to name; on spm the 12
names the Tcl emitted were not among the 86 the router named.

Any net that lost its wire -> the pre-native checkpoint is RESTORED, the pass
is REFUSED, the antenna violation stands by name, and the loop terminates on
the count exactly as before. "Spurious" now means a raise after which every
net that had a wire still has one.

(b) is measured by `test_r0915_121_the_flow_measures_its_own_wires.py`.
"""
import shutil
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")






# ── the emulator ─────────────────────────────────────────────────────────────
# ::wire(<net>) is 1 while the net has a wire. The stubbed
# `repair_antennas -reroute` raises, and on the way out it may insert a diode
# and/or unwire nets -- including nets it inserted nothing on, which is the
# whole point.
_H = r"""
set ::seq {%(seq)s}
set ::i 0
proc check_antennas {args} {
  set v [lindex $::seq $::i]
  if {$::i < [expr {[llength $::seq]-1}]} { incr ::i }
  return $v
}
proc detailed_route {args} { puts "ROUTED_WHOLE_DESIGN" ; return "" }
proc write_db {args} { puts "WROTE_DB [lindex $args 0]" ; return "" }
proc read_db  {args} { puts "READ_DB [lindex $args 0]" ; return "" }

set ::insts {i1}
set ::destroyed {}
set ::nets {nA nX}
set ::wire(nA) 1
set ::wire(nX) 1
set ::inserts {%(inserts)s}
set ::unwire {%(unwire)s}
set ::shrink {%(shrink)s}
set ::wlen(nA) 100
set ::wlen(nX) 100

proc repair_antennas {args} {
  if {[lsearch $args -reroute] >= 0} {
    foreach n $::inserts { lappend ::insts $n }
    foreach n $::unwire  { set ::wire($n) 0 }
    foreach n $::shrink  { set ::wlen($n) 40 }
    error "DRT-0206 checkConnectivity"
  }
  return ""
}

namespace eval ord { proc get_db_block {} { return ::BLK } }
namespace eval odb {
  proc dbInst_destroy {i} {
    set n [$i getName]
    # R-0915-121(3): the deck now STOPS on a refusal, so a probe printed
    # after it never runs. Each destroy reports itself as it happens.
    puts "DESTROYED_ONE $n"
    lappend ::destroyed $n
    set x [lsearch $::insts $n]
    if {$x >= 0} { set ::insts [lreplace $::insts $x $x] }
  }
}
proc ::BLK {method args} {
  switch -- $method {
    getInsts {
      set r {}
      foreach n $::insts { lappend r ::INST_$n }
      return $r
    }
    getNets {
      set r {}
      foreach n $::nets { lappend r ::NET_$n }
      return $r
    }
    findInst {
      set n [lindex $args 0]
      if {[lsearch $::insts $n] < 0} { return NULL }
      return ::INST_$n
    }
    findNet {
      set n [lindex $args 0]
      if {[lsearch $::nets $n] < 0} { return NULL }
      return ::NET_$n
    }
  }
  return NULL
}
proc ::INST_i1 {method args} {
  switch -- $method { getName { return i1 } getITerms { return {} } }
  return 0
}
proc ::INST_d1 {method args} {
  switch -- $method { getName { return d1 } getITerms { return {::IT_d1} } }
  return 0
}
proc ::IT_d1 {method args} {
  switch -- $method { getNet { return ::NET_nA } }
  return NULL
}
foreach _n {nA nX} {
  proc ::NET_$_n {method args} [string map [list @N $_n] {
    switch -- $method {
      getName   { return @N }
      isSpecial { return 0 }
      getWire   { return [expr {$::wire(@N) ? "::WIRE_@N" : "NULL"}] }
    }
    return 0
  }]
  proc ::WIRE_$_n {method args} [string map [list @N $_n] {
    switch -- $method { length { return $::wlen(@N) } }
    return 0
  }]
}
"""




# ── (a) the scope ────────────────────────────────────────────────────────────























# ── the SECOND damage mode: the wire is still there and there is less of it ──
#
# icspm5's probe on spm run13 settled that the two modes are DISJOINT:
# |84 n 86| = 0. The 86 nets checkConnectivity NAMED still have a wire whose
# pieces no longer reach each other; the 84 the checker later found have no
# wire at all. A judgement that only asks "is the wire NULL?" sees the 84 and
# is blind to the 86, and one native call did both.











# ── (c) completed: the parent accepts the checkpoint the deck names ──────────
#
# MEASURED on int11 (subservient x gf180mcuD as a DIE, 2026-09-21, tree
# 5b5bd02af): the deck named `antenna_pass_pre.odb` exactly as R-0915-121(c)
# requires, and the parent answered
#
#   ANTENNA_ROLLBACK FAILED antenna_repair=NOT_APPLIED reason=the antenna
#   repair REFUSED (...) and named .../antenna_pass_pre.odb as its checkpoint,
#   which is not antenna_pre_repair.odb; refused rather than restored from a
#   file this module did not write
#
# -- so the ruling's restore could not happen at all. The reader's PROPERTY is
# right and stays: restore only from a file THIS MODULE WROTE. What changed is
# that R-0915-121(c) makes that two files, and the reader knew one.







def test_the_restore_uses_the_name_the_deck_gave():
    """It used to rebuild the path from the stage-entry constant whatever the
    marker said, which silently disagreed with the emitter the moment there
    were two checkpoints."""
    src = Path(R.__file__).read_text()
    assert "ckpt = out_dir / ckpt_name" in src
    assert 'ckpt_c = f"{out_dir_c}/{ckpt_name}"' in src
