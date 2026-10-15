# Vibeic.ExternalCaptureLaunchRetap, after ClockPathDriveSizing and before
# ResizerTimingPostCTS. The snapshot is the same CTS-input instance census
# that ClockPathDriveSizing used; no master or net name selects a candidate.
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl
read_current_odb
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
estimate_parasitics -placement

set _vic_prects_insts [dict create]
set _vic_fh [open $::env(VIBEIC_CLKPATH_PRECTS_INSTANCES)]
foreach _vic_pi [split [read $_vic_fh] "\n"] {
    if {$_vic_pi ne ""} { dict set _vic_prects_insts $_vic_pi 1 }
}
close $_vic_fh

source [file join [file dirname [info script]] external_capture_launch_retap.tcl]

# Retap can add a load even when the preceding sizing state met the cap.
source [file join [file dirname [info script]] cts_clock_fanout.tcl]
if {[catch {vic_close_cts_clock_fanout $_vic_prects_insts} _vic_why]} {
    puts stderr "VIC_CTS_FANOUT_REFUSED: $_vic_why"
    exit 1
}

# Re-measure CTS fanout after retap, since a retained launch register is a
# new load on its target net. This is the metric consumed by CTS quality.
set _vic_cts_insts 0
set _vic_cts_maxfo 0
foreach _vic_inst [[ord::get_db_block] getInsts] {
    if {[dict exists $_vic_prects_insts [$_vic_inst getName]]} { continue }
    incr _vic_cts_insts
    foreach _vic_it [$_vic_inst getITerms] {
        if {[[$_vic_it getMTerm] getIoType] ne "OUTPUT"} { continue }
        set _vic_net [$_vic_it getNet]
        if {$_vic_net eq "NULL" || $_vic_net eq ""} { continue }
        set _vic_fo [expr {[llength [$_vic_net getITerms]] - 1
                           + [llength [$_vic_net getBTerms]]}]
        if {$_vic_fo > $_vic_cts_maxfo} { set _vic_cts_maxfo $_vic_fo }
    }
}
puts "CLKPATH_CTS_TREE: created_instances=$_vic_cts_insts max_fanout=$_vic_cts_maxfo"
utl::metric_integer "vibeic__cts__created_instance__count" $_vic_cts_insts
utl::metric_integer "vibeic__cts__max_fanout" $_vic_cts_maxfo

estimate_parasitics -placement
write_views
