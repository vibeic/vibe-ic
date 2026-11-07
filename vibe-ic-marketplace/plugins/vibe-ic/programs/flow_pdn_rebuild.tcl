source $::env(_TCL_ENV_IN)
# Rip-up deletes PG terminals, so this process reads no STA libraries or SDC.
read_db $::env(CURRENT_ODB)
set block [ord::get_db_block]
set power $::env(VDD_PIN)
set ground $::env(GND_PIN)
if {[info exists ::env(VDD_NETS)] && [llength $::env(VDD_NETS)]} {
    set power [lindex $::env(VDD_NETS) 0]
}
if {[info exists ::env(GND_NETS)] && [llength $::env(GND_NETS)]} {
    set ground [lindex $::env(GND_NETS) 0]
}
set_voltage_domain -name CORE -power $power -ground $ground
set terminals {}
foreach terminal [$block getBTerms] {
    set net [$terminal getNet]
    if {$net ne "NULL" && [$net getSigType] in {POWER GROUND}} {
        lappend terminals [list $terminal $net]
        $terminal disconnect
    }
}
pdngen -ripup
foreach connection $terminals {
    lassign $connection terminal net
    $terminal connect $net
}
foreach net [$block getNets] {
    if {![$net isSpecial] && [$net getSigType] ni {POWER GROUND}} {
        set wire [$net getWire]
        if {$wire ne "NULL"} {odb::dbWire_destroy $wire}
    }
}
write_db $::env(SAVE_ODB)
write_def $::env(SAVE_DEF)
