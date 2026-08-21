# ACTIVITY BASIS: VECTORLESS. No VCD is read. Switching activity is a DECLARED
# assumption (a uniform toggle rate applied to the input ports), propagated by
# OpenSTA. The numbers are a function of that assumption, not of any stimulus.
read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_verilog chip_top_synth.v
link_design chip_top
read_sdc constraint.sdc
set_power_activity -input -activity 0.1 -duty 0.5
puts "POWER_ANALYSIS_MODE: vectorless_sdc"
puts "ACTIVITY_BASIS: declared uniform input activity 0.1, duty 0.5; no VCD read"
report_power -digits 4
