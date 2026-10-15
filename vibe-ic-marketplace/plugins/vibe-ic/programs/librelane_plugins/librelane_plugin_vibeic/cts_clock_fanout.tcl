# Shared by the two post-CTS topology owners, before their final census/views.
# Only an actual clock net driven by a post-snapshot instance is eligible.
proc vic_cts_buffer_master {inst} {
    set cell [get_cells -quiet [$inst getName]]
    if {$cell eq ""} { return "" }
    set lib [get_lib_cells -quiet -of_objects $cell]
    if {$lib eq "" || ![get_property $lib is_buffer] ||
        [get_property $lib is_inverter] || [get_property $lib dont_use]} { return "" }
    set inputs {}; set outputs {}
    foreach it [$inst getITerms] {
        set mt [$it getMTerm]
        if {[$mt getSigType] in {POWER GROUND}} { continue }
        switch -- [$mt getIoType] {
            INPUT { lappend inputs $it }
            OUTPUT { lappend outputs $it }
            default { return "" }
        }
    }
    if {[llength $inputs] != 1 || [llength $outputs] != 1} { return "" }
    return [[$inst getMaster] getName]
}

proc vic_close_cts_clock_fanout {prects} {
    if {![info exists ::env(MAX_FANOUT_CONSTRAINT)] ||
        $::env(MAX_FANOUT_CONSTRAINT) eq ""} { return }
    set cap $::env(MAX_FANOUT_CONSTRAINT)
    if {![string is double -strict $cap] || $cap < 0} {
        error "VIC_CTS_FANOUT_CAP_INVALID: $cap"
    }
    # Fanout is an integer population; a fractional declaration is not rounded up.
    set limit [expr {int(floor($cap))}]
    set block [ord::get_db_block]
    set clock_nets [dict create]
    foreach clock [all_clocks] {
        foreach net [sta::find_clk_nets $clock] { dict set clock_nets $net 1 }
    }
    set targets {}
    foreach inst [$block getInsts] {
        if {[dict exists $prects [$inst getName]]} { continue }
        set master [vic_cts_buffer_master $inst]
        foreach it [$inst getITerms] {
            if {[[$it getMTerm] getIoType] ne "OUTPUT"} { continue }
            set net [$it getNet]
            if {$net eq "NULL" || $net eq "" ||
                ![dict exists $clock_nets $net]} { continue }
            set terms [$net getITerms]
            set fanout [expr {[llength $terms] - 1 + [llength [$net getBTerms]]}]
            if {$fanout <= $cap} { continue }
            if {$limit < 2} {
                error "VIC_CTS_FANOUT_CAP_UNSPLITTABLE: [$net getName] has $fanout loads, cap=$cap"
            }
            if {$master eq ""} {
                error "VIC_CTS_FANOUT_BUFFER_UNAVAILABLE: [$net getName] has no linked noninverting driver buffer"
            }
            if {[$net getSigType] in {POWER GROUND} || [llength [$net getBTerms]]} {
                error "VIC_CTS_FANOUT_LOAD_UNSUPPORTED: [$net getName] has supply/port loads"
            }
            set drivers {}; set pins {}; set pin_terms [dict create]
            foreach term $terms {
                set mt [$term getMTerm]
                if {[$mt getSigType] in {POWER GROUND}} {
                    error "VIC_CTS_FANOUT_LOAD_UNSUPPORTED: [$net getName] has supply terminal"
                }
                switch -- [$mt getIoType] {
                    OUTPUT { lappend drivers $term }
                    INPUT {
                        set pin "[[$term getInst] getName]/[$mt getName]"
                        lappend pins $pin
                        dict set pin_terms $pin $term
                    }
                    default { error "VIC_CTS_FANOUT_LOAD_UNSUPPORTED: [$net getName] has bidirectional terminal" }
                }
            }
            if {[llength $drivers] != 1 || [lindex $drivers 0] ne $it} {
                error "VIC_CTS_FANOUT_DRIVER_UNSUPPORTED: [$net getName]"
            }
            lappend targets [list [$net getName] $net [lsort -dictionary $pins] $master $pin_terms]
        }
    }
    if {![llength $targets]} { return }
    set created {}
    foreach target [lsort -dictionary -index 0 $targets] {
        lassign $target net_name net pins master pin_terms
        # Each replacement reduces the original net's population by take-1.
        # Reinserted buffer inputs may themselves be grouped, forming tiers.
        while {[llength $pins] > $limit} {
            set take [expr {min($limit, [llength $pins] - $limit + 1)}]
            set group [lrange $pins 0 [expr {$take - 1}]]
            set pins [lrange $pins $take end]
            set serial [llength $created]
            set name "vic_cts_fanout_${serial}"
            while {[$block findInst $name] ne "NULL" ||
                   [$block findNet "${name}_net"] ne "NULL"} {
                incr serial; set name "vic_cts_fanout_${serial}"
            }
            set load_pins [get_pins $group]
            if {[llength $load_pins] != $take} {
                error "VIC_CTS_FANOUT_LOAD_UNRESOLVED: $net_name $group"
            }
            set before [dict create]
            foreach old [$block getInsts] { dict set before [$old getName] 1 }
            insert_buffer -buffer_cell $master -load_pins $load_pins \
                -buffer_name $name -net_name "${name}_net"
            # The public API takes base names and may uniquify the result.
            # Consume the unique actual instance, as the post-route owner does.
            set inserted {}
            foreach newer [$block getInsts] {
                if {![dict exists $before [$newer getName]]} { lappend inserted $newer }
            }
            if {[llength $inserted] != 1} {
                error "VIC_CTS_FANOUT_INSERT_INVALID: $name created [llength $inserted] instances"
            }
            set inst [lindex $inserted 0]
            set name [$inst getName]
            if {[vic_cts_buffer_master $inst] ne $master} {
                error "VIC_CTS_FANOUT_INSERT_INVALID: $name"
            }
            set input ""; set output ""
            foreach it [$inst getITerms] {
                set mt [$it getMTerm]
                if {[$mt getSigType] in {POWER GROUND}} { continue }
                if {[$mt getIoType] eq "INPUT" && [$it getNet] eq $net} {
                    set input "$name/[$mt getName]"
                    dict set pin_terms $input $it
                }
                if {[$mt getIoType] eq "OUTPUT"} { set output [$it getNet] }
            }
            if {$input eq "" || $output eq "" || $output eq "NULL" || $output eq $net ||
                [llength [$output getITerms]] != $take + 1 || [llength [$output getBTerms]]} {
                error "VIC_CTS_FANOUT_INSERT_INVALID: $name connectivity"
            }
            foreach pin $group {
                set load [dict get $pin_terms $pin]
                if {$load eq "NULL" || [$load getNet] ne $output} {
                    error "VIC_CTS_FANOUT_INSERT_INVALID: $name lost $pin"
                }
            }
            lappend created $inst
            lappend pins $input
        }
        foreach pin $pins {
            if {[[dict get $pin_terms $pin] getNet] ne $net} {
                error "VIC_CTS_FANOUT_INSERT_INVALID: $net_name lost $pin"
            }
        }
        if {[llength [$net getITerms]] - 1 + [llength [$net getBTerms]] > $cap} {
            error "VIC_CTS_FANOUT_REMAINS: $net_name"
        }
    }
    # Move only the newly inserted buffers. Original CTS/data/spare placement
    # and protection are restored even when legalization fails; no views follow.
    set mine [dict create]; set locked {}
    foreach inst $created { dict set mine [$inst getName] 1 }
    foreach inst [$block getInsts] {
        if {[dict exists $mine [$inst getName]]} { continue }
        set status [$inst getPlacementStatus]
        if {$status ni {LOCKED FIRM COVER}} {
            lappend locked [list $inst $status]
            $inst setPlacementStatus LOCKED
        }
    }
    set failed [catch {
        set placement_args {}
        if {[info exists ::env(PL_MAX_DISPLACEMENT_X)] &&
            [info exists ::env(PL_MAX_DISPLACEMENT_Y)]} {
            lappend placement_args -max_displacement \
                [list $::env(PL_MAX_DISPLACEMENT_X) $::env(PL_MAX_DISPLACEMENT_Y)]
        }
        detailed_placement {*}$placement_args
        check_placement -verbose
    } why options]
    foreach pair $locked { [lindex $pair 0] setPlacementStatus [lindex $pair 1] }
    if {$failed} { return -options $options $why }
    puts "VIC_CTS_FANOUT_CLOSED: inserted=[llength $created] cap=$cap"
}
