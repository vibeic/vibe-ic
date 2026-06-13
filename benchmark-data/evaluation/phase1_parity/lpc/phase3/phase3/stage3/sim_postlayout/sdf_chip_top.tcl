
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_def /foss/designs/lpc_phase3/phase3/stage3/pnr/chip_top.def
read_sdc /foss/designs/lpc_phase3/phase3/stage3/pnr/constraint.sdc
if {[catch {write_sdf /foss/designs/lpc_phase3/phase3/stage3/sim_postlayout/chip_top.sdf} sdf_err]} {
  puts "WRITE_SDF_FAIL: $sdf_err"
}
exit
