#!/usr/bin/env python3
"""R-0915-83 — a DRV census taken with no parasitics in STA reports 0.

THE MEASUREMENT THAT FORCED THIS, and the mistake it corrects. Investigating
the opentitan_aes wall I ran three "extraction" arms that each called
`extract_parasitics` and then counted violators, got 0 from all three, and
reported that the loop's 41,956 was a phantom. It was not. The control, one
session on that run's own checkpoint DEF at the max corner:

    extract_parasitics ONLY ............................    0 violators
    the SAME extraction, then write_spef + read_spef ...   45,237 violators

`extract_parasitics` populates the ODB; OpenSTA does not see it until a SPEF is
read back. A census taken after extraction alone is not a clean design -- it is
a design nobody measured, and the two are byte-indistinguishable. Worse, the
loop reads 0 as `SDR_CONVERGED: pass 1` and stops, so the unmeasured case is
the one that looks best.

The second silent zero is in the same block: `report_check_types ... > rpt` was
wrapped in a bare `catch`, so a failed report left the counter at 0 and the
loop called that convergence too.

SEPARATELY, and NOT fixed here because it is OpenROAD's own behaviour: on all
four passes of that run the tool printed `[WARNING EST-0027] no estimated
parasitics. Using wire load models.` right after the census. The census is
sound -- `read_spef` feeds STA -- but `repair_design` wants ESTIMATED
parasitics, finds none, and optimises against a wire-load model while being
graded on SPEF. The deck now says so in its own log rather than leaving it in a
tool warning.

The fixture is the shipping log's own four occurrences.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The four occurrences as they appear in the shipping log, with the census line
# each one followed. Pass, extraction net count, census total.
SHIPPING_LOG = """\
[INFO RCX-0045] Extract 41087 nets, 197710 rsegs, 197710 caps, 461909 ccs
SDR_DRV_BY_KIND: total=41956 max_capacitance=5805
[WARNING EST-0027] no estimated parasitics. Using wire load models.
[INFO RCX-0045] Extract 49218 nets, 224874 rsegs, 224874 caps, 561189 ccs
SDR_DRV_BY_KIND: total=19013 max_capacitance=4983
[WARNING EST-0027] no estimated parasitics. Using wire load models.
[INFO RCX-0045] Extract 49964 nets, 226925 rsegs, 226925 caps, 569809 ccs
SDR_DRV_BY_KIND: total=2647 max_capacitance=599
[WARNING EST-0027] no estimated parasitics. Using wire load models.
[INFO RCX-0045] Extract 50268 nets, 227506 rsegs, 227506 caps, 574383 ccs
SDR_DRV_BY_KIND: total=1896 max_capacitance=437
[WARNING EST-0027] no estimated parasitics. Using wire load models.
"""




# ─────────────── the fixture is real, and it says what I claim ─────────────

def test_the_fixture_is_the_shipping_logs_own_four_occurrences():
    """NEGATIVE CONTROL for the fixture. A test built on a log excerpt is only
    as good as the excerpt; assert its shape before asserting anything from
    it."""
    est = re.findall(r"EST-0027", SHIPPING_LOG)
    totals = re.findall(r"SDR_DRV_BY_KIND: total=(\d+)", SHIPPING_LOG)
    assert len(est) == 4, est
    assert totals == ["41956", "19013", "2647", "1896"], totals
    # every census is IMMEDIATELY followed by the warning -- that adjacency is
    # the whole claim about which command lacked parasitics.
    lines = SHIPPING_LOG.strip().split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("SDR_DRV_BY_KIND"):
            assert "EST-0027" in lines[i + 1], (i, lines[i + 1])


# ───────────────────── the census refuses, by name ─────────────────────────











# ───────────── the wire-load fallback is disclosed, not hidden ─────────────



# ────────────────── with-parasitics control: it GRADES ────────────────────

# A session whose `read_spef` returns and whose violator report counts 7 -- the
# SAME stand-in both tests below drive; only the annotation census differs.
_WORKING_SESSION = (
    "namespace eval ord { proc get_db_block {} { return ::_vic_blk } }\n"
    "proc ::_vic_blk {op args} {\n"
    "  switch -- $op { getDefUnits { return 1000 } "
    "getDieArea { return ::_vic_die } default { return \"\" } }\n"
    "}\n"
    "proc ::_vic_die {op args} {\n"
    "  switch -- $op { dx - dy { return 1150000 } default { return \"\" } }\n"
    "}\n"
    "proc read_spef {path} { return }\n"
    "proc write_spef {path} {\n"
    "  file mkdir [file dirname $path]\n"
    "  set f [open $path w]; puts $f SPEF; close $f\n"
    "}\n"
    "proc extract_parasitics {args} { return }\n"
    "proc report_check_types {args} {\n"
    "  set path \"\"; set take 0\n"
    "  foreach a $args {\n"
    "    if {$take} { set path $a; set take 0; continue }\n"
    "    if {$a eq \">\"} { set take 1 } elseif {[string index $a 0] eq \">\"} "
    "{ set path [string range $a 1 end] }\n"
    "  }\n"
    "  if {$path eq \"\"} { return }\n"
    "  file mkdir [file dirname $path]\n"
    "  set f [open $path w]\n"
    "  puts $f \"max capacitance\"\n"
    "  for {set i 0} {$i < 7} {incr i} "
    "{ puts $f \"  net_$i 0.1 0.2 -0.1 (VIOLATED)\" }\n"
    "  close $f\n"
    "}\n"
    "proc detailed_route {args} {\n"
    "  # -output_drc\n"
    "  return\n"
    "}\n"
    "proc global_route {args} { return }\n"
    "proc write_db {path} {\n"
    "  file mkdir [file dirname $path]\n"
    "  set f [open $path w]; puts -nonewline $f ODB; close $f\n"
    "}\n"
    "proc write_def {path} {\n"
    "  file mkdir [file dirname $path]\n"
    "  set f [open $path w]; puts -nonewline $f DEF; close $f\n"
    "}\n"
    "proc write_verilog {path} {}\n")
