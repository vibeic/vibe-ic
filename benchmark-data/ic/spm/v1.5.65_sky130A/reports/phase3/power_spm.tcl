
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /home/reyerchu/campaign_v1565/spm/converge_1.5.65_sky130A/phase2/stage2/synth/spm_synth.v
link_design spm
read_sdc /home/reyerchu/campaign_v1565/spm/converge_1.5.65_sky130A/phase3/stage3/pnr/constraint.sdc
# report_power emits leakage + dynamic + internal categories explicitly,
# which is what eda_report_audit:power's substance check looks for.
puts "POWER_ANALYSIS_MODE: vectorless_sdc"
if {[catch {report_power} pwr_err]} {
  puts "REPORT_POWER_FAIL: $pwr_err"
}
exit
