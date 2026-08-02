read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /home/reyerchu/_c_car15_run/phase3/stage3/pnr/filled.def
catch {read_sdc /home/reyerchu/_c_car15_run/phase3/stage3/pnr/constraint.sdc}
if {[catch {set_wire_rc -signal -layer MET1}]} { catch {set_wire_rc -layer MET1} }
catch {set_wire_rc -clock -layer MET5}
puts "=== DYN_IR PSM VPWR transient period=25.0ns ==="
if {[catch {analyze_power_grid -net VPWR -transient -period 25.0 -steps 100} _psm_err]} {
  puts "PSM_TRANSIENT_NONFATAL VPWR: $_psm_err"
}
exit
