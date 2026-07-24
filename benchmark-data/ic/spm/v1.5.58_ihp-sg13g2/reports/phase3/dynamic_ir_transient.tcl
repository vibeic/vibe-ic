read_lef /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_tech.lef
read_lef /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef

read_liberty /foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib
read_def /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase3/stage3/pnr/filled.def
catch {read_sdc /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase3/stage3/pnr/constraint.sdc}
if {[catch {set_wire_rc -signal -layer MET1}]} { catch {set_wire_rc -layer MET1} }
catch {set_wire_rc -clock -layer MET5}
puts "=== DYN_IR PSM VDD transient period=10.0ns ==="
if {[catch {analyze_power_grid -net VDD -transient -period 10.0 -steps 100} _psm_err]} {
  puts "PSM_TRANSIENT_NONFATAL VDD: $_psm_err"
}
exit
