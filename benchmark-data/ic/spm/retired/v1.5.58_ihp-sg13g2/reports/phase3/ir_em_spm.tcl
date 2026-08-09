
read_lef /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef
read_lef /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef

read_liberty /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib
read_def /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase3/stage3/pnr/spm.def
if {[catch {set_wire_rc -signal -layer Metal1} _e1]} {
  catch {set_wire_rc -layer Metal1}
}
catch {set_wire_rc -clock -layer Metal5}
puts "=== PSM_NET VDD ==="
if {[catch {analyze_power_grid -net VDD -enable_em -em_outfile /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/reports/phase3/em_segments.csv} _psm_err]} {
  puts "PSM_NONFATAL VDD: $_psm_err"
}
exit
