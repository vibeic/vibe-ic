read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_def /home/reyerchu/_f7dynir/phase3/stage3/pnr/spm.def
catch {read_sdc /home/reyerchu/_f7dynir/phase3/stage3/pnr/constraint.sdc}
if {[catch {set_wire_rc -signal -layer Metal1} _e1]} { catch {set_wire_rc -layer Metal1} }
catch {set_wire_rc -clock -layer Metal5}
puts "=== NEGATIVE CONTROL: no set_operating_conditions (the campaign's shape) ==="
puts "=== DYN_IR PSM VDD transient period=10.0ns ==="
if {[catch {analyze_power_grid -net VDD -transient -period 10.0 -steps 100} _psm_err]} {
  puts "PSM_TRANSIENT_NONFATAL VDD: $_psm_err"
}
exit
