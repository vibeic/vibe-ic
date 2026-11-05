"""Post-route passes that move or insert cells remove the pre-route fill first
and restore it after; a failed legalize is never "spurious"; no diode goes on a
net a diode cannot help.

MEASURED (subservient x gf180mcuD, two copies of run2, main 240c0a353):
fillers are inserted PRE-ROUTE (R-0915-105), so every post-route pass that
calls `detailed_placement` saw them as movable instances -- "Movable instances
area 1,363,895 um^2" in a 1,377,710 um^2 core, `[WARNING DPL-0037] Use
remove_fillers before detailed placement`, `[ERROR DPL-0038] Utilization
greater than 100%, impossible to legalize` on a 5.5 % design.

  * both SDR transactions were REJECTED for it (2,430 / 2,863 candidate
    placement violations) -> no post-route DRV/timing repair was ever adopted
    -> the 2x-limit slews shipped;
  * the antenna-reconverge pass inserted 12 diodes onto filler-tiled sites,
    its DPL-0038 was classed ANTENNA_NATIVE_ERROR_SPURIOUS (no net lost wire),
    and 29 check_placement violations shipped (16 overlap / 9 padding / 4
    site) -- no GDS behind them;
  * the 12 nets already carried a diode and still violated: ANT-0019 "the
    diodes already on them do not help and another one would not either".

Asserts on the REAL deck builders' text and, for the antenna block, on the
same emulated-ODB tclsh harness `test_r0915_116_*` drives.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


SPEC = {"filler_masters": ["fx__fill_1", "fx__fill_2"],
        "slot_pinned_core": False, "design_declared_die": True,
        "sparse_active_row_fill": False}
RUNNER_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()




# --- 1. the SDR child session -------------------------------------------------






# --- 2. the antenna repair/reconverge ------------------------------------------








def test_the_pnr_builder_hands_every_post_route_pass_the_same_fill_facts():
    """ONE statement of the fill facts (`_postroute_filler_spec`) reaches
    preroute_fill, both SDR stages and both antenna slots."""
    tree = ast.parse(RUNNER_SRC)
    wanted = {"_antenna_repair_tcl", "_post_route_spef_repair_tcl",
              "_v1_8_100_signoff_drv_repair_tcl"}
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in wanted:
            kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
            seen.setdefault(node.func.id, []).append(kw.get("filler_spec"))
    assert set(seen) == wanted, seen
    assert seen["_antenna_repair_tcl"] == ["_postroute_filler_spec"]
    assert seen["_post_route_spef_repair_tcl"] == ["_postroute_filler_spec"]
    assert sorted(seen["_v1_8_100_signoff_drv_repair_tcl"]) == \
        ["_postroute_filler_spec", "filler_spec"]




# --- 3. a failed legalize is never spurious (DRIVEN) ---------------------------






# --- 4. no diode where a diode cannot help (ANT-0019) --------------------------


# --- 5. RULING: mixed case -> futile diodes destroyed by name (DRIVEN) ---------
_MIXED_HARNESS = r"""
set ::calls 0
set ::reports {{nA nB} {nA nB} {nA} {nA}}
set ::counts {2 2 1 1}
proc check_antennas {args} {
  set i [expr {min($::calls, [llength $::counts]-1)}]
  set f [lindex $args [expr {[lsearch $args -report_file]+1}]]
  if {[lsearch $args -report_file] >= 0} {
    set fh [open $f w]
    foreach n [lindex $::reports $i] { puts $fh "Net: $n" }
    close $fh
  }
  incr ::calls
  return [lindex $::counts $i]
}
proc detailed_route {args} { return "" }
proc write_db {args} { return "" }
proc remove_fillers {args} { puts "CALL_REMOVE_FILLERS" }
set ::insts {d0}
proc repair_antennas {args} {
  puts "CALL_REPAIR_ANTENNAS $args"
  if {[lsearch $args -jumper_only] >= 0} { return "" }
  if {![info exists ::inserted]} { set ::inserted 1; lappend ::insts d1 d2 }
  return ""
}
namespace eval ord { proc get_db_block {} { return ::BLK } }
namespace eval odb {
  proc dbInst_destroy {i} {
    set n [$i getName]
    puts "DESTROYED_ONE $n"
    set x [lsearch $::insts $n]
    if {$x >= 0} { set ::insts [lreplace $::insts $x $x] }
  }
}
proc ::BLK {method args} {
  switch -- $method {
    getInsts { set r {}; foreach n $::insts { lappend r ::INST_$n }; return $r }
    findInst { set n [lindex $args 0]
               if {[lsearch $::insts $n] < 0} { return NULL }; return ::INST_$n }
    findNet  { set n [lindex $args 0]
               if {$n ne "nA" && $n ne "nB"} { return NULL }; return ::NET_$n }
    getNets  { return {} }
  }
  return NULL
}
proc ::MASTER_D {method args} { if {$method eq "getName"} { return fx__antenna }; return "" }
foreach d {d0 d1 d2} net {nA nA nB} {
  proc ::INST_$d [list method args] [string map [list @D@ $d @N@ $net] {
    switch -- $method {
      getName   { return @D@ }
      getMaster { return ::MASTER_D }
      getITerms { return {::IT_@D@} }
    }
    return 0
  }]
  proc ::IT_$d [list method args] [string map [list @D@ $d @N@ $net] {
    switch -- $method { getInst { return ::INST_@D@ } getNet { return ::NET_@N@ } }
    return NULL
  }]
}
proc ::NET_nA {method args} {
  switch -- $method {
    getName { return nA } isSpecial { return 0 } getWire { return W }
    getITerms { set r {}; foreach d {d0 d1} { if {[lsearch $::insts $d] >= 0} { lappend r ::IT_$d } }; return $r }
  }
  return 0
}
proc ::NET_nB {method args} {
  switch -- $method {
    getName { return nB } isSpecial { return 0 } getWire { return W }
    getITerms { if {[lsearch $::insts d2] >= 0} { return {::IT_d2} }; return {} }
  }
  return 0
}
"""
