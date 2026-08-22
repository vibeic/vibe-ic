#!/usr/bin/env python3
"""J83 — build a probe that reaches the ARMS' OWN post-hold state and then runs the
clkswap rung, without running the full-die rung the arms are stuck in.

J80 probed the POST-CTS state and had to bound the difference to post-hold by argument
(hold repair adds 222 cells / 3 644.04 um^2 / 7 residual).  This removes the argument:
it reads the same `post_cts.def`, runs the flow's OWN `repair_timing -hold`, and only
then runs the ladder.

ENTRY CONTROL, and it is what makes the probe worth running: after hold repair the
probe must reproduce the die-3800 arm's own post-hold numbers -- 391 980 cells,
movable 6 054 418.68 um^2, fixed 667 191.53 um^2, residual 2 352.  If it does, the
probe IS in the arm's state and everything after is directly comparable.  If it does
not, that is reported and the probe is the weaker instrument.

Everything is the runner's own pnr.tcl, verbatim, with THREE substitutions and no
others:
  * `read_verilog` + `link_design` -> `read_def post_cts.def` (DEF entry: the DEF
    carries the netlist, and it is the netlist AFTER CTS which is the whole point);
  * the SDC path re-pointed at the die-3800 project's own constraint.sdc;
  * the floorplan..CTS body (lines 138..8301) dropped, because the DEF already IS
    that state, and the full-die rung (the block at 8318..8324) dropped, because the
    arms are inside it and this probe must not become a sixth one.
"""
import re, sys, pathlib

SRC  = "/home/reyerchu/_jself_priv/proj/edge_llm_matmul_accel/phase3/stage3/pnr/pnr.tcl"
DEF  = "/home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/post_cts.def"
SDC  = "/home/reyerchu/_jself_priv/proj/matmul_d3800/phase3/stage3/pnr/constraint.sdc"

lines = open(SRC).read().split("\n")
def L(n): return lines[n-1]

# --- prove every anchor before touching anything ---
assert L(11).startswith("read_verilog"),            L(11)
assert L(12).startswith("link_design"),             L(12)
assert L(13).startswith("read_sdc"),                L(13)
assert L(138).strip() == 'puts "PNR_STAGE: floorplan"', L(138)
assert L(8268).strip().startswith("if {[catch {estimate_parasitics -placement}"), L(8268)
assert L(8270).strip() == "}",                      L(8270)
assert L(8303).strip() == 'puts "PNR_STAGE: hold_repair"', L(8303)
assert L(8304).strip().startswith("if {[catch {repair_timing -hold}"), L(8304)
assert L(8307).strip() == "set _dplok_ph 0",        L(8307)
assert L(8317).strip() == "}",                      L(8317)   # end of rungs 1-4
# the FULL-DIE rung, 8318..8324: the block this probe must NOT run
assert L(8318).strip().startswith("if {$_dplok_ph == 0 && ![catch {ord::get_die_area} _da_ph]"), L(8318)
assert "disp=full-die" in L(8322),                  L(8322)
assert L(8324).strip() == "}",                      L(8324)
# the clkswap rung, 8325..8343; 8344 starts clkswap-full-die and is NOT taken
assert L(8325).strip() == "if {$_dplok_ph == 0} {", L(8325)
assert L(8340).strip().startswith("} _rec_ph]}"),   L(8340)
assert "disp=clkswap" in L(8342),                   L(8342)
assert L(8343).strip() == "}",                      L(8343)
assert "_da2_ph" in L(8344),                        L(8344)

out = []
out += [f"# J83 POST-HOLD PROBE -- the runner's own pnr.tcl.  Setup 1..9 and 14..137",
        f"# verbatim, DEF entry instead of read_verilog+link_design, then 8302..8317",
        f"# (hold repair + ladder rungs 1-4) and 8325..8347 (the clkswap rung).",
        f"# The FULL-DIE rung 8318..8324 is deliberately ABSENT: five arms are inside",
        f"# it and this probe must not become a sixth.", ""]

out += lines[0:9]                                   # 1..9  lef + corners + liberty
out += ["", 'puts "PROBE_STAGE: read_def"', f"read_def {DEF}", ""]
out += [f"read_sdc {SDC}"]                          # 13, re-pointed
out += lines[13:137]                                # 14..137 dont_use / opt / wire_rc
out += ["", 'puts "PROBE_STAGE: entry_control"',
        "report_design_area", ""]
# v2: the parasitics estimate the flow runs at 8268, WITHOUT the buffer_ports /
# repair_design around it -- those are pre-CTS optimisations already baked into
# post_cts.def, and re-running them would change the netlist this probe is comparing.
# v1 omitted this and `repair_timing -hold` answered "no estimated parasitics ...
# No hold violations found" and inserted 0 buffers where the arm inserted 222.
# v3: propagate the clock.  v2 added the parasitics estimate, EST-0027 disappeared,
# and `repair_timing -hold` STILL said "No hold violations found" -- so parasitics was
# a real gap and not THE gap.  Post-CTS hold violations are created by clock-tree SKEW;
# entering from a DEF leaves the clock IDEAL, every clock arrival is 0, there is no
# skew, and there is nothing to violate.  `clock_tree_synthesis` propagates the clock
# as a side effect, which is why the arm never had to say this and this probe does.
# It is a TIMING-VIEW reconstruction, not a change to the design: no cell moves, no
# rule is relaxed, and the netlist is byte-identical either way.
out += ["", 'puts "PROBE_STAGE: propagate_clock"',
        "if {[catch {set_propagated_clock [all_clocks]} _spc_e]} {",
        '  puts "PROPAGATE_CLOCK_NONFATAL: $_spc_e"', "}"]
out += ["", 'puts "PROBE_STAGE: estimate_parasitics"']
out += lines[8267:8270]                             # 8268..8270 estimate_parasitics
out += lines[8302:8317]                             # 8303..8317 hold repair + rungs 1-4
out += ['puts "PROBE_PRESWAP_OK=$_dplok_ph"', "",
        'puts "PROBE_STAGE: clkswap"']
out += lines[8324:8343]                             # 8325..8343 clkswap + default DPL
out += ["}"]                                        # close the 8325 `if`, since the
                                                    # clkswap-full-die rung is dropped
out += ['puts "PROBE_POSTSWAP_OK=$_dplok_ph"',
        'puts "PROBE_DONE posthold_3800 (full-die rung deliberately NOT run)"', ""]

txt = "\n".join(out)
assert "ord::get_die_area" not in txt.split("PROBE_STAGE: clkswap")[0], \
    "a full-die rung leaked into the pre-swap half"
assert txt.count("initialize_floorplan") == 0, "floorplan leaked in"
assert txt.count("clock_tree_synthesis") == 0, "CTS leaked in"
pathlib.Path("posthold_probe_3800_v3.tcl").write_text(txt)
print(f"posthold_probe_3800_v3.tcl  {len(out)} lines")
print("  full-die rungs in file:", txt.count("ord::get_die_area"))
print("  repair_timing -hold   :", txt.count("repair_timing -hold"))
print("  estimate_parasitics   :", txt.count("estimate_parasitics"))
print("  clkswap blocks        :", txt.count("POST_HOLD_CLKBUF_DOWNSIZE swapped"))
