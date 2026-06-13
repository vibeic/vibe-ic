# single-corner STA driven by env LIBFILE + CORNER. Run once per corner.
set PDK /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd
set D   /foss/designs/benchmark_clean_sha256/phase3/stage3/pnr
set lib $::env(LIBFILE)
set name $::env(CORNER)
puts "================ CORNER: $name ($lib) ================"
read_lef $PDK/techlef/sky130_fd_sc_hd__nom.tlef
read_lef $PDK/lef/sky130_fd_sc_hd.lef
read_liberty $PDK/lib/$lib
read_verilog $D/sha256_pnr.v
link_design sha256
read_sdc $D/constraint.sdc
set_wire_rc -signal -layer met1
set_wire_rc -clock  -layer met3
estimate_parasitics -placement
puts "---- $name setup (max) ----"
report_worst_slack -max
report_tns -max
puts "---- $name hold (min) ----"
report_worst_slack -min
report_tns -min
exit
