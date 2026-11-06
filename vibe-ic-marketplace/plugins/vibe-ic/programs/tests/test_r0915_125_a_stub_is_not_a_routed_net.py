"""A net stripped to a stub still HAS a wire, and the census must see that.

MEASURED on spm run17 (main 41a1613e6 + released 0.3.70). The run reported
`0 unrouted at every boundary`, antenna repair APPLIED, scoped_reroute=1 --
and its routed.def carries 33,557 wire lines against run15's 92,576.

Measured again on run17's own two surviving checkpoints, which is what makes
the case airtight:

    sdr_transaction/pre_repair.odb             655 nets, 0 with no wire,
                                               32634 wire units
    sdr_transaction_reconverge/pre_repair.odb  655 nets, 0 with no wire,
                                               17857 wire units
    nets whose wire CONTENT moved: 655 -- 654 shrank, 1 grew
    the one that GREW is p__core, 30 -> 50: the scoped route's own target,
    doing exactly what it should
    biggest losses: u_core/net12 1680->846, u_core/net8 550->278,
                    u_core/yr 415->216

-45.3 % of the wire across one transaction, every net still "routed", and the
instrument said zero. R-0915-121's boundary probe asks whether a net HAS a
wire; that question cannot see this. The antenna census in the same ruling
DOES compare `[$wire length]`, which is why it caught its own damage -- the
two were written to different standards and only one of them was right.
"""
import shutil
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")

_H = r"""
set ::nets {%(nets)s}
array set ::len0 {%(len0)s}
array set ::len1 {%(len1)s}
set ::phase 0
namespace eval ord { proc get_db_block {} { return ::BLK } }
proc ::BLK {method args} {
  switch -- $method { getNets { set r {} ; foreach n $::nets { lappend r ::NET_$n } ; return $r } }
  return NULL
}
foreach _n $::nets {
  proc ::NET_$_n {method args} [string map [list @N $_n] {
    switch -- $method {
      getName   { return @N }
      isSpecial { return 0 }
      getWire   {
        set l [expr {$::phase ? $::len1(@N) : $::len0(@N)}]
        if {$l == 0} { return NULL }
        return ::WIRE_@N
      }
    }
    return 0
  }]
  proc ::WIRE_$_n {method args} [string map [list @N $_n] {
    switch -- $method { length { return [expr {$::phase ? $::len1(@N) : $::len0(@N)}] } }
    return 0
  }]
}
"""






















# ── extraction is a DB-mutating step and is bracketed like one ─────────────
#
# It reads like a measurement and is not: OpenRCX's `orderWires` re-encodes
# every net through `tmg_conn`, and on spm run17 that is what took the wire
# (fork PR #23, merged 9e331799; the fork's RoutingPreserver restores
# 655/655). The flow cannot rely on a fork fix to know whether its own
# database survived a step -- it measures.













def test_extraction_changing_a_wire_is_named_as_mutation_not_measurement():
    src = Path(R.__file__).read_text()
    assert "SPEF_EXTRACT_MUTATED_THE_ROUTE" in src
    assert "supposed to READ this database" in src
    assert "RoutingPreserver" in src
