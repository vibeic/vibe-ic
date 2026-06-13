
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /foss/designs/subservient_vibe/phase3/stage3/pnr/subservient.def
# OpenROAD uses estimate_parasitics for net-RC + write_spef for sign-off SPEF.
# Wire-load model: prefer detailed-route topology, fall back to placement.
if {[catch {estimate_parasitics -global_routing} pe_err1]} {
  if {[catch {estimate_parasitics -placement} pe_err2]} {
    puts "ESTIMATE_PARASITICS_FAIL: $pe_err1 / $pe_err2"
  }
}
if {[catch {write_spef /foss/designs/subservient_vibe/phase3/stage3/extracted/subservient.spef} spef_err]} {
  puts "SPEF_WRITE_FAIL: $spef_err"
}
exit
