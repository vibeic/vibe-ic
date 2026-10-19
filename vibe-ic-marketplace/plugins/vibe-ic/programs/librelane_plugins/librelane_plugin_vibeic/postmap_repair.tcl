# Unplaced mapped-product transform. No geometry or timing exception.
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
read_pnr_libs
read_lefs
read_current_netlist
unset_propagated_clock [all_clocks]
set_dont_use_cells
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl
set_dont_touch_objects
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
proc postmap_measure {tag} {
    puts "POSTMAP $tag setup_ns [worst_slack -max]"
    puts "POSTMAP $tag hold_ns [worst_slack -min]"
    puts "POSTMAP $tag tns_ns [total_negative_slack -max]"
    puts "POSTMAP $tag slew_count [sta::max_slew_violation_count]"
    puts "POSTMAP $tag cap_count [sta::max_capacitance_violation_count]"
    puts "POSTMAP $tag fanout_count [sta::max_fanout_violation_count]"
}
postmap_measure before
log_cmd repair_design -pre_placement
postmap_measure after
unset_dont_touch_objects
write_verilog $::env(SAVE_NL)
