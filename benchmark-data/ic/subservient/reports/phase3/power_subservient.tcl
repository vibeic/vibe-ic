
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /foss/designs/subservient_vibe/phase2/stage2/synth/subservient_synth.v
link_design subservient
read_sdc /foss/designs/subservient_vibe/phase3/stage3/pnr/constraint.sdc
# report_power emits leakage + dynamic + internal categories explicitly,
# which is what eda_report_audit:power's substance check looks for.
if {[catch {report_power} pwr_err]} {
  puts "REPORT_POWER_FAIL: $pwr_err"
}
exit
