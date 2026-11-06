"""The same deck is correct on a scoped router and an unscoped one.

icord1 put the missing capability into the fork rather than around it in Tcl,
and MEASURED it on run15's own `antenna_pass_pre.odb` with ONE patched binary
(26Q3-2625-g79f27347e2):

    detailed_route -nets {p__core}   LOST 0, SHRANK 0, 0 of 654 untouched nets
                                     changed a byte, antenna 0, rc 0, 26 s,
                                     DRC 621 byte-identical to baseline
    the SAME binary, no -nets        LOST 93, SHRANK 55, GREW 505, DRT-0206

The second line reproduces this lane's numbers exactly -- I measured 93/55/505
on the same DB through a `dont_touch`-scoped attempt, which is how we learned
that `dont_touch` does not restrain `detailed_route` and that 0.3.67 offers no
net subset at all (its own help lists none). On the patched build
`repair_antennas -reroute` routes scoped by itself: GRT-0313 antenna-clean
after one pass, only p__core's bytes changed.

So the deck keeps everything R-0915-121 landed -- the loop, the wire census,
the refusal, the rollback, the stop -- and adds only what tells the two
regimes apart:

  (a) the `-reroute` path is NOT stripped. On 0.3.70 it IS the scoped one.
  (b) a healthy pass censuses 0 lost / 0 shrunk and the loop CONTINUES; the
      refusal is driven by measurement, so it simply does not fire there.
  (c) the router's version is RECORDED, and the scoping capability is ASKED
      FOR rather than inferred from it -- a version string is a label,
      `-nets` in the command's own registered body is the fact. MEASURED on
      0.3.67 in this lane's container: `ord::openroad_version` =
      26Q3-2599-g697a63f1ad, and `info body detailed_route` contains
      `-verbose` and NOT `-nets`.

Both probes fail SAFE: an unreadable version records UNKNOWN and an unreadable
body records scoped=0, which keeps today's refuse-and-roll-back.
"""
import shutil
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")

SCOPED_VERSION = "26Q3-2625-g79f27347e2"      # icord1's patched fork
UNSCOPED_VERSION = "26Q3-2599-g697a63f1ad"    # 0.3.67, measured in-container






# ── a fake router that reports a version AND a command body ─────────────────
#
# `info body detailed_route` is the capability probe, so the fake defines
# `detailed_route` as a real proc whose body does or does not mention -nets.
_ROUTER = r"""
set ::seq {%(seq)s}
set ::i 0
proc check_antennas {args} {
  set v [lindex $::seq $::i]
  if {$::i < [expr {[llength $::seq]-1}]} { incr ::i }
  return $v
}
proc write_db {args} { return "" }
namespace eval ord {
  proc openroad_version {} { return "%(version)s" }
  proc get_db_block {} { return ::BLK }
}
%(route_proc)s
set ::insts {i1}
set ::nets {nA}
set ::wire(nA) 1
set ::wlen(nA) 100
proc repair_antennas {args} { %(repair)s }
namespace eval odb { proc dbInst_destroy {i} { return "" } }
proc ::BLK {method args} {
  switch -- $method {
    getInsts { set r {} ; foreach n $::insts { lappend r ::INST_$n } ; return $r }
    getNets  { return {::NET_nA} }
    findInst { return NULL }
    findNet  { return ::NET_nA }
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
proc ::IT_d1 {method args} { switch -- $method { getNet { return ::NET_nA } } ; return NULL }
proc ::NET_nA {method args} {
  switch -- $method {
    getName   { return nA }
    isSpecial { return 0 }
    getWire   { return [expr {$::wire(nA) ? "::WIRE_nA" : "NULL"}] }
  }
  return 0
}
proc ::WIRE_nA {method args} { switch -- $method { length { return $::wlen(nA) } } ; return 0 }
"""

# the two command bodies the probe distinguishes -- the ONLY difference is
# whether `-nets` appears, which is exactly what the deck asks about.
# The registered spec (`sta::cmd_args`) and the GENERATED proc body are two
# different surfaces, and run16L proved they can disagree: icord1's fork takes
# `-nets` and its generated body does not say so. The fakes cover all four
# combinations, because the deck must read YES from either one alone.
_BODY_NETS = ('proc detailed_route {args} '
              '{ # supports -nets <list>\n  return "" }')
_BODY_PLAIN = ('proc detailed_route {args} '
               '{ # supports -verbose <level>\n  return "" }')
_SPEC_NETS = ('namespace eval sta { variable cmd_args }\n'
              'array set ::sta::cmd_args '
              '{detailed_route "[-verbose level] [-nets nets]"}')
_SPEC_PLAIN = ('namespace eval sta { variable cmd_args }\n'
               'array set ::sta::cmd_args '
               '{detailed_route "[-verbose level]"}')
# the default fakes: a scoped build registers the option, an unscoped one
# registers neither surface.
_SCOPED_PROC = _BODY_PLAIN + "\n" + _SPEC_NETS
_UNSCOPED_PROC = _BODY_PLAIN + "\n" + _SPEC_PLAIN

_HEALTHY = 'return ""'                                   # no raise at all
_DAMAGING = ('lappend ::insts d1 ; set ::wire(nA) 0 ; '
             'error "DRT-0206 checkConnectivity"')




# ── (c) the record, on both images ─────────────────────────────────────────









# ── (a) and (b): the scoped path is kept, and a healthy pass proceeds ───────


















# ── the two surfaces, and the run16L defect ────────────────────────────────












# ── the wrapper, which is what actually happened on run16L ─────────────────
#
# ROOT CAUSE (icspm5, openroad.log:1280 vs pnr.tcl:12615): this deck's own
# route-guide discipline does `rename detailed_route _vibeic_real_detailed_route`
# and installs a wrapper, so `info body detailed_route` returns THE WRAPPER'S
# body. The router had scoped correctly -- GRT-0325 "re-routing 1 net(s) ...
# every other net held fixed", DRT-0633 "Scoped detailed routing: 1 named,
# 654 of 654 held fixed" -- and only the label was wrong.

_WRAPPED = (
    # the real command, carrying the option, under its renamed identity
    'proc _vibeic_real_detailed_route {args} '
    '{ # supports -nets <list>\n  return "" }\n'
    # the deck's own wrapper, which says nothing about -nets
    'proc detailed_route {args} '
    '{ # guides\n  return [uplevel 1 _vibeic_real_detailed_route $args] }')








def test_the_probe_follows_the_rename_the_same_way_the_deck_already_does():
    """The DRC-option probe in this same file resolves the identical rename.
    A second spelling of the same resolution is how the two drift apart."""
    src = Path(R.__file__).read_text()
    assert src.count("info commands _vibeic_real_detailed_route") >= 2
