# ACTIVITY BASIS: VCD. Per-pin toggle counts come from a simulation of THIS
# netlist. Same liberty, same netlist, same SDC as the vectorless run — the
# activity basis is the only thing that differs.
read_liberty /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
read_verilog chip_top_synth.v
link_design chip_top
read_sdc constraint.sdc
read_vcd -scope tb/dut chip_top.vcd
puts "POWER_ANALYSIS_MODE: vector_vcd"
puts "ACTIVITY_BASIS: chip_top.vcd, scope tb/dut"
report_power -digits 4
