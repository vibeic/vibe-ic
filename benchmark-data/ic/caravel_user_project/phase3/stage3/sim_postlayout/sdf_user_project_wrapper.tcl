
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_def /foss/designs/_bench7_caravel_v1034_cleanroom/caravel_r11/phase3/stage3/pnr/user_project_wrapper.def
read_sdc /foss/designs/_bench7_caravel_v1034_cleanroom/caravel_r11/phase3/stage3/pnr/constraint.sdc
if {[catch {write_sdf /foss/designs/_bench7_caravel_v1034_cleanroom/caravel_r11/phase3/stage3/sim_postlayout/user_project_wrapper.sdf} sdf_err]} {
  puts "WRITE_SDF_FAIL: $sdf_err"
}
exit
