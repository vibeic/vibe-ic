read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_def /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase3/stage3/pnr/filled.def
catch {read_sdc /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase3/stage3/pnr/constraint.sdc}
if {[catch {set_wire_rc -signal -layer MET1}]} { catch {set_wire_rc -layer MET1} }
catch {set_wire_rc -clock -layer MET5}
puts "=== DYN_IR PSM VDD transient period=10.0ns ==="
if {[catch {analyze_power_grid -net VDD -transient -period 10.0 -steps 100} _psm_err]} {
  puts "PSM_TRANSIENT_NONFATAL VDD: $_psm_err"
}
exit
