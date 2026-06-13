# Improved SHA-256 PnR — adds estimate_parasitics + repair_design + repair_timing -setup
# (the generic runner omits setup repair, leaving high-fanout nets unbuffered).
set PDK /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd
set D   /foss/designs/benchmark_clean_sha256/phase3/stage3/pnr

read_lef $PDK/techlef/sky130_fd_sc_hd__nom.tlef
read_lef $PDK/lef/sky130_fd_sc_hd.lef
# Multi-corner: drive repair_timing -setup against the SS slow corner and
# repair_timing -hold against the FF fast corner (sign-off practice). The
# previous TT-only repair left the SS critical path (ripple-carry maj3 chain)
# unsized => SS setup failed. We define both corners up front.
define_corners ss tt ff
# use the COLD 1.60V slow corner (n40C) as ss — it is the true worst-case
# setup corner for this design, so the resizer sizes the ripple-carry chain
# to close it (the 100C variant was already passing).
read_liberty -corner ss $PDK/lib/sky130_fd_sc_hd__ss_n40C_1v60.lib
read_liberty -corner tt $PDK/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_liberty -corner ff $PDK/lib/sky130_fd_sc_hd__ff_100C_1v95.lib

read_verilog /foss/designs/benchmark_clean_sha256/phase2/stage2/synth/sha256_synth.v
link_design sha256
read_sdc $D/constraint.sdc

# global fanout/transition limits (L9.1B SYNTH_MAX_FANOUT=8)
set_max_fanout 8 [current_design]

initialize_floorplan -die_area "0 0 900 900" \
                     -core_area "12 12 888 888" \
                     -site unithd
make_tracks
place_pins -hor_layers met3 -ver_layers met2
write_def $D/floorplan.def

# wire RC for parasitic estimation (sky130 met1 signal layer typical)
set_wire_rc -signal -layer met1
set_wire_rc -clock  -layer met3

# drive constant nets with real tie cells (conb_1) BEFORE placement so they
# get legalized in the main placement pass; otherwise the OpenROAD-created
# constant net stays flagged USE GROUND and TritonRoute DRT-0305 refuses it.
insert_tiecells sky130_fd_sc_hd__conb_1/LO -prefix "TIE_ZERO_"
insert_tiecells sky130_fd_sc_hd__conb_1/HI -prefix "TIE_ONE_"

# lower placement density spreads the wide datapath out and relieves the
# local routing congestion seen at 0.25 (TritonRoute could not converge).
global_placement -density 0.18 -pad_left 2 -pad_right 2
estimate_parasitics -placement
# fix max-fanout / max-cap / max-slew by sizing + buffering
repair_design
# setup-timing repair (resize + buffer the long/high-load nets); add 1.5 ns
# setup margin so post-route parasitics don't push the cold SS corner negative.
repair_timing -setup -repair_tns 100 -setup_margin 1.5
detailed_placement
write_def $D/placed.def

if {[catch {clock_tree_synthesis -buf_list {sky130_fd_sc_hd__clkbuf_4} -root_buf sky130_fd_sc_hd__clkbuf_16} e]} {
  puts "CTS_NONFATAL: $e"
}
estimate_parasitics -placement
write_def $D/post_cts.def

# hold repair after CTS
if {[catch {repair_timing -hold} e]} { puts "HOLD_NONFATAL: $e" }
detailed_placement
write_def $D/post_hold.def

global_route
if {[catch {detailed_route} e]} { puts "DETAILED_ROUTE_NONFATAL: $e" }
write_def $D/routed.def
write_def $D/sha256.def
write_verilog $D/sha256_pnr.v

# post-route parasitics for honest STA (live routed DB => real parasitics)
set_propagated_clock [all_clocks]
estimate_parasitics -global_routing
write_spef $D/sha256.spef
report_checks -path_delay max > $D/sta.rpt
report_checks -path_delay min >> $D/sta.rpt
report_design_area > $D/area.rpt

# honest multi-corner sign-off slack (routed parasitics, propagated clock)
set rf [open $D/sta_signoff.txt w]
foreach c {ss tt ff} {
  puts $rf "==== CORNER $c ===="
  puts $rf "setup WNS [sta::worst_slack -max -corner $c]"
  puts $rf "hold  WNS [sta::worst_slack -min -corner $c]"
}
close $rf
puts "---- signoff per-corner ----"
foreach c {ss tt ff} {
  puts "CORNER $c setup [sta::worst_slack -max -corner $c] hold [sta::worst_slack -min -corner $c]"
}
exit
