
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /foss/designs/_usb_pd_phase3_stage/phase3/stage3/pnr/chip_top.def
puts "=== ERC: floating nets ==="
if {[catch {report_floating_nets} _fn]} { puts "ERC_FN_NONFATAL: $_fn" }
puts "=== ERC metrics ==="
if {[catch {report_erc_metrics} _erc]} { puts "ERC_METRICS_NONFATAL: $_erc" }
exit
