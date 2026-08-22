#!/usr/bin/env python3
"""J86 — build a CTS buf_list/root_buf probe from the runner's own pnr.tcl.

Setup lines 1..9 and 14..137 verbatim (LEF, corners, Liberty, dont_use, opt config,
wire_rc), DEF entry at `placed.def` instead of read_verilog+link_design, the flow's own
unplaceable-master width cap re-emitted from its own function so the same masters are
excluded, its own `estimate_parasitics -placement`, then ONE `clock_tree_synthesis`
invocation with the variant under test, then a census.

It STOPS after the census: no legalizer, no ladder, no full-die rung.
"""
import sys, pathlib

SRC = "/home/reyerchu/_jself_priv/proj/edge_llm_matmul_accel/phase3/stage3/pnr/pnr.tcl"
DEF = "/home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/placed.def"
SDC = "/home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/constraint.sdc"
P   = "gf180mcu_fd_sc_mcu7t5v0__"

sys.path.insert(0, "/home/reyerchu/_jself_priv/wt_j80/vibe-ic-marketplace/"
                   "plugins/vibe-ic/programs")
import phase3_one_shot_runner as p3          # main's copy, unmodified

tag, buf_list, root_buf = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(SRC).read().split("\n")
def L(n): return lines[n-1]
assert L(11).startswith("read_verilog"), L(11)
assert L(13).startswith("read_sdc"),     L(13)
assert L(138).strip() == 'puts "PNR_STAGE: floorplan"', L(138)
assert L(8268).strip().startswith("if {[catch {estimate_parasitics -placement}"), L(8268)

cap = p3._build_unplaceable_master_cap_tcl()
assert "PLACEABLE_WIDTH_BOUND" in cap and "set_dont_use" in cap

out  = [f"# J86 CTS PROBE {tag}", f"# -buf_list {{{buf_list}}}  -root_buf {{{root_buf}}}",
        "# stops after CTS + census; no legalizer, no ladder.", ""]
out += lines[0:9]
out += ["", 'puts "PROBE_STAGE: read_def"', f"read_def {DEF}", "", f"read_sdc {SDC}"]
out += lines[13:137]
out += ["", 'puts "PROBE_STAGE: width_cap"', cap]
out += ["", 'puts "PROBE_STAGE: estimate_parasitics"']
out += lines[8267:8270]
out += ["", 'puts "PROBE_STAGE: cts"',
        f"if {{[catch {{clock_tree_synthesis -buf_list {{{buf_list}}} "
        f"-root_buf {{{root_buf}}}}} _e]}} {{ puts \"CTS_NONFATAL: $_e\" }}",
        "", 'puts "PROBE_STAGE: census"',
        "set _blk [ord::get_db_block]",
        "set _u [[[ord::get_db] getTech] getDbUnitsPerMicron]",
        "array unset _c ; array unset _w",
        "foreach _in [$_blk getInsts] {",
        "  set _m [$_in getMaster] ; set _n [$_m getName]",
        "  if {[string match {*__clkbuf_*} $_n]} {",
        "    if {[info exists _c($_n)]} { incr _c($_n) } else { set _c($_n) 1 }",
        "    set _w($_n) [$_m getWidth]",
        "  }",
        "}",
        "set _tot 0 ; set _atbound 0",
        "foreach _n [lsort [array names _c]] {",
        "  set _sw [expr {double($_w($_n))/$_u/0.56}]",
        "  puts [format \"CENSUS %-46s n=%-7d %8.3f um = %5.1f site(s)\" "
        "$_n $_c($_n) [expr {double($_w($_n))/$_u}] $_sw]",
        "  incr _tot $_c($_n)",
        "  if {$_sw >= 50.0} { incr _atbound $_c($_n) }",
        "}",
        f"puts \"CENSUS_TOTAL clkbuf instances=$_tot at-or-over-50-sites=$_atbound\"",
        "", 'puts "PROBE_STAGE: skew"',
        "if {[catch {estimate_parasitics -placement} _pe]} { puts \"EP_NONFATAL: $_pe\" }",
        "if {[catch {report_clock_skew} _sk]} { puts \"SKEW_NONFATAL: $_sk\" }",
        "if {[catch {report_clock_latency -clock [get_clocks *]} _la]} { puts \"LAT_NONFATAL: $_la\" }",
        f"puts \"PROBE_DONE {tag}\"", ""]
pathlib.Path(f"cts_probe_{tag}.tcl").write_text("\n".join(out))
print(f"cts_probe_{tag}.tcl  {len(out)} lines  buf_list={buf_list}  root_buf={root_buf}")
