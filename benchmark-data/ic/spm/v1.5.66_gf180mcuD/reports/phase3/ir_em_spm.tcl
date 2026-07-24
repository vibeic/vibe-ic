
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef
read_lef /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef

read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_def /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase3/stage3/pnr/spm.def
if {[catch {set_wire_rc -signal -layer Metal1} _e1]} {
  catch {set_wire_rc -layer Metal1}
}
catch {set_wire_rc -clock -layer Metal5}
catch {set_layer_rc -via Via1 -resistance 4.5}
catch {set_layer_rc -via Via2 -resistance 4.5}
catch {set_layer_rc -via Via3 -resistance 4.5}
catch {set_layer_rc -via Via4 -resistance 4.5}
puts "=== PSM_NET VDD ==="
if {[catch {analyze_power_grid -net VDD -enable_em -em_outfile /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/reports/phase3/em_segments.csv} _psm_err]} {
  puts "PSM_NONFATAL VDD: $_psm_err"
}
exit
