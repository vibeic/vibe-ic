# vibe-ic DRV stage probe (programs/drv_stage_receipts.py installs it as the
# OpenROAD / OpenSTA init file of a LibreLane chain that runs a DRV stage).
#
# It wraps the stage command IN THE PROCESS THAT RUNS IT and, around each call,
# writes into <step dir>/vibeic_drv_stage/:
#   <tag>.pre.sdc       `write_sdc` taken on the line before the command
#   <tag>.behavior.rpt  `sta::max_fanout_check_limit` before the command, then
#                       the DRV census after it (report_check_types violators
#                       + the tool's own violation counters)
#   <tag>.args          the command's own argument list
#   <tag>.clock_fanout  (clock_tree_synthesis) every CLOCK net's driver/loads
# It judges nothing and never changes what the stage does: a probe error is
# written to <tag>.error and the stage command still runs.
namespace eval ::vibeic_drv {
    variable seq 0
    variable busy 0
}

# The step folder is where LibreLane asks the step to save its views.
proc ::vibeic_drv::dir {} {
    foreach view {SAVE_SDC SAVE_ODB SAVE_DEF SAVE_NL} {
        if {[info exists ::env($view)] && $::env($view) ne ""} {
            set d [file join [file dirname $::env($view)] vibeic_drv_stage]
            file mkdir $d
            return $d
        }
    }
    return ""
}

proc ::vibeic_drv::rct {args} {
    if {[llength [info commands ::vibeic_drv::orig_report_check_types]]} {
        return [uplevel 1 [list ::vibeic_drv::orig_report_check_types {*}$args]]
    }
    return [uplevel 1 [list ::report_check_types {*}$args]]
}

proc ::vibeic_drv::corner {argv} {
    set i [lsearch -exact $argv -corner]
    if {$i >= 0 && $i + 1 < [llength $argv]} { return [lindex $argv [expr {$i + 1}]] }
    return all
}

proc ::vibeic_drv::append_line {path line} {
    set f [open $path a]
    puts $f $line
    close $f
}

proc ::vibeic_drv::census {path} {
    ::vibeic_drv::append_line $path \
        "# census: report_check_types -max_slew -max_capacitance -max_fanout -violators -verbose"
    # Let the public report wrapper finish its SDC warmup before the native
    # command opens the report. OpenROAD cannot nest logger redirections.
    ::vibeic_drv::rct -max_slew -max_capacitance -max_fanout -violators -verbose >> $path
    foreach kind {max_slew max_capacitance max_fanout} {
        ::vibeic_drv::append_line $path "$kind violators=[sta::${kind}_violation_count]"
    }
}

proc ::vibeic_drv::clock_fanout {path} {
    set f [open $path w]
    foreach net [[ord::get_db_block] getNets] {
        if {[$net getSigType] ne "CLOCK"} { continue }
        set driver ""
        set loads 0
        foreach it [$net getITerms] {
            if {[$it isOutputSignal]} {
                set driver "[[$it getInst] getName]/[[$it getMTerm] getName]"
            } elseif {[$it isInputSignal]} {
                incr loads
            }
        }
        foreach bt [$net getBTerms] {
            if {[$bt getIoType] eq "INPUT"} { set driver [$bt getName] } else { incr loads }
        }
        puts $f "clock_driver_fanout\t$driver\t[$net getName]\t$loads"
    }
    close $f
}

# Post-synthesis census (no stage command to wrap): the linked netlist under
# the run's SDC with its clocks as the SDC leaves them, each clock's
# propagation state recorded first so a reader can see the ideal clocks the
# tool's checks exclude.
proc ::vibeic_drv::synth_census {path} {
    set f [open $path w]
    puts $f "# vibe-ic DRV stage probe: synth"
    set clocks [all_clocks]
    puts $f "clocks [llength $clocks]"
    foreach clk $clocks {
        puts $f "clock [get_property $clk full_name] is_propagated=[get_property $clk is_propagated]"
    }
    close $f
    ::vibeic_drv::census $path
}

# R-0929-DRV-FANOUT-LIMIT: the zero-argument sta::max_fanout_check_limit is
# the limit of OpenSTA's worst-slack fanout pin (an IO pad's library default
# on a padded die).  Record every pin's enforced fanout limit, and each pin's
# master cell, so the reader can take the design-level limit on core drivers
# and the IO cells' limit apart.
proc ::vibeic_drv::fanout_limits {tag} {
    set path $tag.fanout_limits.rpt
    ::vibeic_drv::rct -max_fanout -verbose -max_count 1000000000 > $path
    set f [open $path r]
    set body [read $f]
    close $f
    set out [open $tag.pin_cells w]
    foreach line [split $body "\n"] {
        if {![regexp {^\s*Pin\s+(\S+)} $line -> name]} { continue }
        set pin [get_pins -quiet $name]
        if {[llength $pin]} {
            puts $out "pin_cell\t$name\t[get_property [get_cells -of_objects $pin] ref_name]"
        } else {
            puts $out "pin_cell\t$name\t<port>"
        }
    }
    close $out
}

proc ::vibeic_drv::pre {command argv} {
    variable seq
    set d [::vibeic_drv::dir]
    if {$d eq ""} { return "" }
    incr seq
    set tag [file join $d "$command.[::vibeic_drv::corner $argv].$seq"]
    if {[catch {
        set f [open $tag.args w]
        puts $f $argv
        close $f
        write_sdc -no_timestamp $tag.pre.sdc
        set f [open $tag.behavior.rpt w]
        puts $f "# vibe-ic DRV stage probe: $command"
        if {![catch {sta::max_fanout_check_limit} limit]} {
            puts $f "sta::max_fanout_check_limit $limit"
        }
        close $f
        ::vibeic_drv::fanout_limits $tag
    } msg]} {
        ::vibeic_drv::append_line $tag.error "pre: $msg"
    }
    return $tag
}

proc ::vibeic_drv::post {command tag} {
    if {$tag eq ""} { return }
    if {[catch {
        if {$command eq "clock_tree_synthesis"} {
            ::vibeic_drv::clock_fanout $tag.clock_fanout
            # The census is the post-CTS behaviour: propagated clocks, then the
            # caller's own propagation state is restored.
            set ideal [list]
            foreach clk [all_clocks] {
                if {![get_property $clk is_propagated]} { lappend ideal $clk }
            }
            if {[llength $ideal]} { set_propagated_clock $ideal }
            if {[llength [info commands ::estimate_parasitics]]} {
                estimate_parasitics -placement
            }
            ::vibeic_drv::census $tag.behavior.rpt
            if {[llength $ideal]} { unset_propagated_clock $ideal }
        } else {
            ::vibeic_drv::census $tag.behavior.rpt
        }
    } msg]} {
        ::vibeic_drv::append_line $tag.error "post: $msg"
    }
}

proc ::vibeic_drv::wrap {command} {
    if {[llength [info commands ::$command]] == 0} { return }
    if {[llength [info commands ::vibeic_drv::orig_$command]]} { return }
    rename ::$command ::vibeic_drv::orig_$command
    proc ::$command {args} [string map [list @CMD@ $command] {
        if {$::vibeic_drv::busy} {
            return [uplevel 1 [list ::vibeic_drv::orig_@CMD@ {*}$args]]
        }
        set ::vibeic_drv::busy 1
        set tag [::vibeic_drv::pre @CMD@ $args]
        set code [catch {uplevel 1 [list ::vibeic_drv::orig_@CMD@ {*}$args]} result options]
        ::vibeic_drv::post @CMD@ $tag
        set ::vibeic_drv::busy 0
        return -options $options $result
    }]
}

if {[namespace exists ::ord]} {
    ::vibeic_drv::wrap repair_design
    ::vibeic_drv::wrap clock_tree_synthesis
} else {
    ::vibeic_drv::wrap report_check_types
}
