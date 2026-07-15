
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef

read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/phase3/stage3/pnr/sha256.def
if {[catch {set_wire_rc -signal -layer met1} _e1]} {
  catch {set_wire_rc -layer met1}
}
catch {set_wire_rc -clock -layer met5}
puts "=== PSM_NET VPWR ==="
if {[catch {analyze_power_grid -net VPWR -enable_em -em_outfile /home/reyerchu/vibe-ic/benchmark-data/ic/sha256/clean_run_v1422_20260715/reports/phase3/em_segments.csv} _psm_err]} {
  puts "PSM_NONFATAL VPWR: $_psm_err"
}
exit
