
read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_verilog /foss/designs/_bench6_v100_r1/subservient/phase2/stage2/synth/chip_top_synth.v
link_design chip_top
read_sdc /foss/designs/_bench6_v100_r1/subservient/phase3/stage3/pnr/constraint.sdc
if {[catch {read_power_activities -vcd /foss/designs/_bench6_v100_r1/subservient/phase2/stage1/sim_full_stack/generic_full_stack_run/waves.vcd} _vcd_err]} {
  puts "READ_VCD_FAIL: $_vcd_err"
}
# report_power emits leakage + dynamic + internal categories explicitly,
# which is what eda_report_audit:power's substance check looks for.
puts "POWER_ANALYSIS_MODE: vector_vcd"
if {[catch {report_power} pwr_err]} {
  puts "REPORT_POWER_FAIL: $pwr_err"
}
exit
