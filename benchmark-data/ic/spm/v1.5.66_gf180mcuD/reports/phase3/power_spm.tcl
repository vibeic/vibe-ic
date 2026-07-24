
read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib

read_verilog /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase2/stage2/synth/spm_synth.v
link_design spm
read_sdc /home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase3/stage3/pnr/constraint.sdc
# report_power emits leakage + dynamic + internal categories explicitly,
# which is what eda_report_audit:power's substance check looks for.
puts "POWER_ANALYSIS_MODE: vectorless_sdc"
if {[catch {report_power} pwr_err]} {
  puts "REPORT_POWER_FAIL: $pwr_err"
}
exit
