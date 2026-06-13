
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /foss/designs/lpc_phase3/phase3/stage3/pnr/chip_top.def
puts "=== DESIGN AREA (pre-fill) ==="
report_design_area
# ECO-aware fill: filler_placement only ADDS filler instances into row
# gaps; it never removes or overlaps existing (dont_touch) instances, so
# the Step 18 spares are preserved by construction.
if {[catch {filler_placement {sky130_fd_sc_hd__decap_12 sky130_fd_sc_hd__decap_8 sky130_fd_sc_hd__decap_6 sky130_fd_sc_hd__decap_4 sky130_fd_sc_hd__decap_3 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_1}} _fp_err]} {
  puts "FILLER_PLACEMENT_NONFATAL: $_fp_err"
}
puts "=== DESIGN AREA (post-fill) ==="
report_design_area
write_def /foss/designs/lpc_phase3/phase3/stage3/pnr/filled.def
exit
