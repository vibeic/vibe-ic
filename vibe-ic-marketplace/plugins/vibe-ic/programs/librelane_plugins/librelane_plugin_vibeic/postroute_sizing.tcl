source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl
read_current_odb
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
set_propagated_clock [all_clocks]
set_dont_touch_objects
remove_fillers

foreach corner [lln::get_corner_names] {
    set matched 0
    foreach {pattern spef} $::env(VIBEIC_ROUTED_SPEFS) {
        if {[string match $pattern $corner]} {
            read_spef -corner $corner $spef
            set matched 1
            break
        }
    }
    if {!$matched} {error "No routed SPEF for corner $corner"}
}
estimate_parasitics -detailed_routing

set sizing_args [list]
append_if_exists_argument sizing_args VIBEIC_PRR_LIMIT_SIZING_AREA -limit_sizing_area
append_if_exists_argument sizing_args VIBEIC_PRR_LIMIT_SIZING_LEAKAGE -limit_sizing_leakage
if {[llength $sizing_args]} {log_cmd set_opt_config {*}$sizing_args}

set rd_args [list -verbose]
append_if_exists_argument rd_args VIBEIC_PRR_MAX_WIRE_LENGTH -max_wire_length
append_if_exists_argument rd_args VIBEIC_PRR_SLEW_MARGIN_PCT -slew_margin
append_if_exists_argument rd_args VIBEIC_PRR_CAP_MARGIN_PCT -cap_margin
append_if_exists_argument rd_args VIBEIC_PRR_MAX_UTIL_PCT -max_utilization
odb::dbDatabase_beginEco $::block
log_cmd repair_design {*}$rd_args

if {[info exists ::env(VIBEIC_PRR_RECOVER_POWER_PCT)]} {
    set power_args [list -recover_power $::env(VIBEIC_PRR_RECOVER_POWER_PCT)]
    append_if_exists_argument power_args VIBEIC_PRR_MAX_UTIL_PCT -max_utilization
    log_cmd repair_timing {*}$power_args
}
set setup_args [list -setup -verbose -skip_buffer_removal \
    -setup_margin $::env(VIBEIC_PRR_SETUP_MARGIN) \
    -max_buffer_percent $::env(VIBEIC_PRR_SETUP_MAX_BUFFER_PCT)]
if {$::env(VIBEIC_PRR_SETUP_SEQUENCE) ne "default"} {
    lappend setup_args -sequence $::env(VIBEIC_PRR_SETUP_SEQUENCE)
}
append_if_exists_argument setup_args VIBEIC_PRR_SETUP_REPAIR_TNS_PCT -repair_tns
append_if_exists_argument setup_args VIBEIC_PRR_MAX_UTIL_PCT -max_utilization
log_cmd repair_timing {*}$setup_args

set hold_args [list -hold -verbose -skip_buffer_removal \
    -setup_margin $::env(VIBEIC_PRR_SETUP_MARGIN) \
    -hold_margin $::env(VIBEIC_PRR_HOLD_MARGIN) \
    -max_buffer_percent $::env(VIBEIC_PRR_HOLD_MAX_BUFFER_PCT)]
append_if_exists_argument hold_args VIBEIC_PRR_MAX_UTIL_PCT -max_utilization
log_cmd repair_timing {*}$hold_args
log_cmd repair_design {*}$rd_args

set changed [expr {![odb::dbDatabase_ecoEmpty $::block]}]
odb::dbDatabase_endEco $::block
odb::dbDatabase_commitEco $::block
utl::metric_integer vibeic__postroute__changed $changed

# A full reroute lets the router move neighbors that a scoped ECO route freezes.
if {$changed} {
    foreach net [$::block getNets] {
        if {![$net isSpecial] && [$net getSigType] ni {POWER GROUND}} {
            set wire [$net getWire]
            if {$wire ne "NULL"} {odb::dbWire_destroy $wire}
        }
    }
}
unset_dont_touch_objects
write_views
