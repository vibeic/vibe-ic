crashbackups stop
gds readonly true
gds rescale false
set ::env_lefs [split $env(LEFS) ";"]
foreach lf $::env_lefs {
    if {[string trim $lf] ne ""} { lef read $lf }
}
def read $env(DEF)
load $env(TOP)
select top cell
cellname rename $env(TOP) $env(TOP)
gds write $env(GDS_OUT)
puts "MAGIC_GDS_WRITTEN $env(GDS_OUT)"
quit -noprompt
