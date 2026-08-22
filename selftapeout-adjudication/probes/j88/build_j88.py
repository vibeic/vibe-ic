#!/usr/bin/env python3
"""J88 — two full post-hold probes differing ONLY in -root_buf.

placed.def -> width cap -> estimate_parasitics -> set_propagated_clock -> CTS ->
repair_timing -hold -> post-hold DPL rungs 1-4 -> census.  The FULL-DIE rung
(pnr.tcl:8318-8324) and everything after rung 4 are absent by construction.
"""
import sys, pathlib
SRC = "/home/reyerchu/_jself_priv/proj/edge_llm_matmul_accel/phase3/stage3/pnr/pnr.tcl"
DEF = "/home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/placed.def"
SDC = "/home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/constraint.sdc"
sys.path.insert(0, "/home/reyerchu/_jself_priv/wt_j80/vibe-ic-marketplace/"
                   "plugins/vibe-ic/programs")
import phase3_one_shot_runner as p3

tag, buf_list, root_buf = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(SRC).read().split("\n")
def L(n): return lines[n-1]
assert L(11).startswith("read_verilog"), L(11)
assert L(13).startswith("read_sdc"), L(13)
assert L(138).strip() == 'puts "PNR_STAGE: floorplan"', L(138)
assert L(8268).strip().startswith("if {[catch {estimate_parasitics -placement}"), L(8268)
assert L(8303).strip() == 'puts "PNR_STAGE: hold_repair"', L(8303)
assert L(8307).strip() == "set _dplok_ph 0", L(8307)
assert L(8317).strip() == "}", L(8317)
assert L(8318).strip().startswith("if {$_dplok_ph == 0 && ![catch {ord::get_die_area} _da_ph]"), L(8318)

cap = p3._build_unplaceable_master_cap_tcl()
assert "PLACEABLE_WIDTH_BOUND" in cap
out  = [f"# J88 {tag}: -root_buf {root_buf}. rungs 1-4 only; no full-die rung.", ""]
out += lines[0:9]
out += ["", 'puts "PROBE_STAGE: read_def"', f"read_def {DEF}", "", f"read_sdc {SDC}"]
out += lines[13:137]
out += ["", 'puts "PROBE_STAGE: width_cap"', cap]
out += ["", 'puts "PROBE_STAGE: estimate_parasitics"'] + lines[8267:8270]
out += ["", 'puts "PROBE_STAGE: propagate_clock"',
        "if {[catch {set_propagated_clock [all_clocks]} _e]} { puts \"PROP_NONFATAL: $_e\" }"]
out += ["", 'puts "PROBE_STAGE: cts"',
        f"if {{[catch {{clock_tree_synthesis -buf_list {{{buf_list}}} "
        f"-root_buf {{{root_buf}}}}} _e]}} {{ puts \"CTS_NONFATAL: $_e\" }}"]
out += ["", 'puts "PROBE_STAGE: census_post_cts"',
        "set _blk [ord::get_db_block]",
        "set _u [[[ord::get_db] getTech] getDbUnitsPerMicron]",
        "array unset _c ; array unset _w",
        "foreach _in [$_blk getInsts] {",
        "  set _m [$_in getMaster] ; set _n [$_m getName]",
        "  if {[string match {*__clkbuf_*} $_n]} {",
        "    if {[info exists _c($_n)]} { incr _c($_n) } else { set _c($_n) 1 }",
        "    set _w($_n) [$_m getWidth] } }",
        "foreach _n [lsort [array names _c]] {",
        "  puts [format \"CENSUS %-46s n=%-7d %8.3f um\" $_n $_c($_n) "
        "[expr {double($_w($_n))/$_u}]] }"]
out += ["", 'puts "PROBE_STAGE: hold_and_rungs"'] + lines[8302:8317]
out += ['puts "PROBE_PRESWAP_OK=$_dplok_ph"',
        f'puts "PROBE_DONE {tag} (full-die rung deliberately NOT run)"', ""]
txt = "\n".join(out)
assert "disp=full-die" not in txt, "a full-die rung leaked in"
assert txt.count("initialize_floorplan") == 0
pathlib.Path(f"{tag}.tcl").write_text(txt)
print(f"{tag}.tcl  {len(out)} lines  root_buf={root_buf}  "
      f"braces delta {txt.count('{')-txt.count('}')}")
