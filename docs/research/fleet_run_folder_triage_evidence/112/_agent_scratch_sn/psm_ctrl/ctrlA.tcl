
read_lef /home/reyerchu/_n25_sn2025/run26/input/pdk/lef/m18e80pm180su_lef_210820/STD/m18e80pm180su_5lm_tech_v56.lef
read_lef /home/reyerchu/_n25_sn2025/run26/phase3/pdk_stage/m18e80pm180su_macro_v56_supplydir_fix.lef
read_lef /home/reyerchu/_n25_sn2025/run26/input/pdk_local/otp_ip/LEF/EO0128X8KA180BA11_M3.lef
read_liberty /home/reyerchu/_n25_sn2025/run26/input/pdk/liberty/m18e80pm180su_typ.lib
catch {set_operating_conditions typical}
read_def /home/reyerchu/_n25_sn2025/run26/phase3/stage3/pnr/chip_top_asic.def
if {[catch {set_wire_rc -signal -layer MET1} _e1]} {
  catch {set_wire_rc -layer MET1}
}
catch {set_wire_rc -clock -layer MET5}
catch {set_layer_rc -via VIA1 -resistance 5.5}
catch {set_layer_rc -via VIA2 -resistance 5.5}
catch {set_layer_rc -via VIA3 -resistance 5.5}
catch {set_layer_rc -via VIA4 -resistance 3.0}
puts "=== PSM_NET VDD ==="
if {[catch {analyze_power_grid -net VDD -enable_em -em_outfile /home/reyerchu/_n25_sn2025/run26/reports/phase3//tmp/ctrlA_em.csv} _psm_err]} {
  puts "PSM_NONFATAL VDD: $_psm_err"
}
exit
