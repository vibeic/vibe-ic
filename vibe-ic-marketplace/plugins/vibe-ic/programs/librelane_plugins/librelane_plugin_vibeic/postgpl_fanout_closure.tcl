# The first RepairDesignPostGPL can create a first level of buffers that
# themselves exceed set_max_fanout. The input SDC and active Liberty are the
# only limits; no design or PDK number is embedded here.
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl
read_current_odb
unset_propagated_clock [all_clocks]
set_dont_touch_objects
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
estimate_parasitics -placement
set args [list -verbose -max_wire_length $::env(DESIGN_REPAIR_MAX_WIRE_LENGTH) \
    -slew_margin $::env(DESIGN_REPAIR_MAX_SLEW_PCT) \
    -cap_margin $::env(DESIGN_REPAIR_MAX_CAP_PCT)]
if {[info exists ::env(DESIGN_REPAIR_MAX_UTILIZATION)]} {
    lappend args -max_utilization $::env(DESIGN_REPAIR_MAX_UTILIZATION)
}
if {[info exists ::env(DESIGN_REPAIR_BUFFER_GAIN)]} {
    lappend args -buffer_gain $::env(DESIGN_REPAIR_BUFFER_GAIN)
}
log_cmd repair_design {*}$args
# Setup repair belongs to this placement session, before legalization. A tool
# error must fail the native step rather than publish an unexecuted chain.
log_cmd repair_timing -setup
# Setup can insert another buffer level. Keep the hook's final fanout/DRV
# repair after that edit, under the very same active limits.
log_cmd repair_design {*}$args
source $::env(SCRIPTS_DIR)/openroad/common/dpl.tcl
unset_dont_touch_objects
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
estimate_parasitics -placement
write_views
